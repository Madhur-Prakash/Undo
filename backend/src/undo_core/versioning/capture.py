"""Safe file capture.

A filesystem event never implies a file is finished. Capture therefore:

1. takes a per-file lock (duplicate events for one file serialise),
2. checks exclusions, file type and size,
3. skips work when size + mtime match the last recorded state,
4. waits until size + mtime stay stable for ``capture.stable_seconds``,
5. hashes, stores and verifies the content (see BlobStore.ingest_file), and
   detects modification during capture,
6. retries a bounded number of times, then records *why* it gave up.

A failed capture never touches existing versions.
"""

from __future__ import annotations

import os
import stat
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from sqlalchemy.exc import IntegrityError as SAIntegrityError

from undo_core.config.settings import Settings
from undo_core.daemon.locking import KeyedLocks
from undo_core.database.engine import Database
from undo_core.database.models import Operation
from undo_core.database.repositories import FileRepository, SkipRepository, latest_version_for_file
from undo_core.filesystem.exclusions import ExclusionMatcher
from undo_core.filesystem.identity import file_identity
from undo_core.platform.paths import is_within, path_key, to_relative
from undo_core.storage.blob_store import BlobStore
from undo_core.utils.errors import FileChangedDuringCapture, PathOutsideRootError
from undo_core.utils.logging import get_logger
from undo_core.versioning.version_manager import record_content

log = get_logger(__name__)

# Windows sharing violation / lock violation
_BUSY_WINERRORS = {32, 33}


class CaptureStatus(StrEnum):
    CAPTURED = "captured"
    ALREADY_STORED = "already_stored"  # new version, content deduplicated against an existing blob
    UNCHANGED = "unchanged"  # same content as the latest version: nothing recorded
    EXCLUDED = "excluded"
    PERMISSION_DENIED = "permission_denied"
    TOO_LARGE = "too_large"
    UNAVAILABLE = "temporarily_unavailable"
    FAILED = "capture_failed"
    NOT_FOUND = "not_found"
    SYMLINK = "symlink_not_followed"
    SPECIAL = "special_file"


SKIP_STATUSES = {
    CaptureStatus.EXCLUDED,
    CaptureStatus.PERMISSION_DENIED,
    CaptureStatus.TOO_LARGE,
    CaptureStatus.UNAVAILABLE,
    CaptureStatus.FAILED,
    CaptureStatus.SYMLINK,
    CaptureStatus.SPECIAL,
}


@dataclass(frozen=True)
class RootRef:
    id: int
    path: Path


@dataclass(frozen=True)
class CaptureResult:
    status: CaptureStatus
    relative_path: str
    version_id: int | None = None
    operation: str | None = None
    blob_hash: str | None = None
    size: int = 0
    detail: str | None = None
    stored_new_blob: bool = False

    @property
    def new_version(self) -> bool:
        return self.status in (CaptureStatus.CAPTURED, CaptureStatus.ALREADY_STORED)


class CaptureStats:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.counts: dict[str, int] = {}
        self.bytes_stored = 0

    def add(self, result: CaptureResult) -> None:
        with self._lock:
            self.counts[result.status.value] = self.counts.get(result.status.value, 0) + 1
            if result.stored_new_blob:
                self.bytes_stored += result.size

    def snapshot(self) -> dict[str, int]:
        with self._lock:
            return dict(self.counts)


class CaptureEngine:
    def __init__(
        self,
        db: Database,
        store: BlobStore,
        settings: Callable[[], Settings],
        matcher_for: Callable[[RootRef], ExclusionMatcher],
        locks: KeyedLocks | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.db = db
        self.store = store
        self._settings = settings
        self._matcher_for = matcher_for
        self.locks = locks or KeyedLocks()
        self.stats = CaptureStats()
        self._sleep = sleep

    # ---------------------------------------------------------------- helpers
    def _record_skip(self, root: RootRef, rel: str, reason: str, detail: str | None) -> None:
        try:
            with self.db.write() as s:
                SkipRepository(s).record(root.id, rel, reason, detail)
        except Exception as exc:
            log.error("could not record skip", extra={"path": rel, "error": str(exc)})

    def _clear_skip(self, root: RootRef, rel: str) -> None:
        try:
            with self.db.write() as s:
                SkipRepository(s).clear(root.id, rel)
        except Exception as exc:
            log.warning("could not clear skip record", extra={"path": rel, "error": str(exc)})

    def _finish(self, root: RootRef, result: CaptureResult, *, record_skips: bool) -> CaptureResult:
        self.stats.add(result)
        if result.status in SKIP_STATUSES and record_skips:
            self._record_skip(root, result.relative_path, result.status.value, result.detail)
            if result.status in (
                CaptureStatus.FAILED,
                CaptureStatus.UNAVAILABLE,
                CaptureStatus.PERMISSION_DENIED,
            ):
                log.warning(
                    "file not captured",
                    extra={
                        "path": result.relative_path,
                        "status": result.status.value,
                        "detail": result.detail,
                    },
                )
        return result

    def _is_unchanged(self, root: RootRef, rel: str, st: os.stat_result) -> bool:
        with self.db.read() as s:
            file = FileRepository(s).active_by_path(root.id, rel)
            if file is None or file.last_size != st.st_size or file.last_mtime_ns != st.st_mtime_ns:
                return False
            latest = latest_version_for_file(s, file)
            return (
                latest is not None
                and latest.operation != Operation.DELETE
                and latest.blob_hash is not None
            )

    def _wait_stable(
        self, path: Path, st: os.stat_result, stable_seconds: float
    ) -> os.stat_result | None:
        """Return a stat that stayed unchanged for ``stable_seconds``, or None if it moved."""
        if stable_seconds <= 0:
            return st
        age = time.time() - st.st_mtime
        if age >= stable_seconds:
            return st  # not modified recently: treat as settled
        self._sleep(stable_seconds)
        try:
            st2 = os.stat(path)
        except OSError:
            return None
        if st2.st_size == st.st_size and st2.st_mtime_ns == st.st_mtime_ns:
            return st2
        return None

    # ---------------------------------------------------------------- main entry
    def capture(
        self,
        root: RootRef,
        abs_path: Path,
        *,
        force_hash: bool = False,
        record_skips: bool = True,
        extra_meta: dict[str, object] | None = None,
    ) -> CaptureResult:
        try:
            rel = to_relative(root.path, abs_path)
        except PathOutsideRootError as exc:
            return CaptureResult(CaptureStatus.EXCLUDED, str(abs_path), detail=str(exc))
        if not rel:
            return CaptureResult(CaptureStatus.SPECIAL, rel, detail="root directory itself")
        settings = self._settings()
        matcher = self._matcher_for(root)
        with self.locks.hold((root.id, path_key(rel))):
            return self._finish(
                root,
                self._capture_locked(
                    root, abs_path, rel, settings, matcher, force_hash, extra_meta
                ),
                record_skips=record_skips,
            )

    def _capture_locked(
        self,
        root: RootRef,
        abs_path: Path,
        rel: str,
        settings: Settings,
        matcher: ExclusionMatcher,
        force_hash: bool,
        extra_meta: dict[str, object] | None,
    ) -> CaptureResult:
        cap = settings.capture
        last_detail = ""
        for attempt in range(cap.max_retries + 1):
            if attempt:
                self._sleep(cap.retry_seconds)
            try:
                st = os.lstat(abs_path)
            except FileNotFoundError:
                return CaptureResult(CaptureStatus.NOT_FOUND, rel)
            except PermissionError as exc:
                return CaptureResult(CaptureStatus.PERMISSION_DENIED, rel, detail=exc.strerror)
            except OSError as exc:
                last_detail = str(exc)
                continue
            if stat.S_ISLNK(st.st_mode):
                if not settings.monitor.follow_symlinks:
                    return CaptureResult(CaptureStatus.SYMLINK, rel)
                try:
                    if not is_within(os.path.realpath(abs_path), root.path):
                        return CaptureResult(
                            CaptureStatus.SYMLINK, rel, detail="target outside tracked root"
                        )
                    st = os.stat(abs_path)
                except OSError as exc:
                    return CaptureResult(CaptureStatus.SYMLINK, rel, detail=f"broken link: {exc}")
            if stat.S_ISDIR(st.st_mode):
                return CaptureResult(CaptureStatus.SPECIAL, rel, detail="directory")
            reason = matcher.check(rel, is_dir=False, st=st)
            if reason:
                status = CaptureStatus.EXCLUDED
                return CaptureResult(status, rel, detail=reason)
            if not stat.S_ISREG(st.st_mode):
                return CaptureResult(CaptureStatus.SPECIAL, rel, detail="not a regular file")
            if st.st_size > cap.max_file_size:
                return CaptureResult(
                    CaptureStatus.TOO_LARGE,
                    rel,
                    size=st.st_size,
                    detail=f"{st.st_size} bytes > limit {cap.max_file_size}",
                )
            if not force_hash and self._is_unchanged(root, rel, st):
                return CaptureResult(CaptureStatus.UNCHANGED, rel, size=st.st_size)
            stable = self._wait_stable(abs_path, st, cap.stable_seconds)
            if stable is None:
                last_detail = "file still changing"
                continue
            st = stable
            try:
                ingest = self.store.ingest_file(abs_path, st)
            except FileChangedDuringCapture as exc:
                last_detail = exc.message
                continue
            except FileNotFoundError:
                return CaptureResult(CaptureStatus.NOT_FOUND, rel)
            except PermissionError as exc:
                if getattr(exc, "winerror", None) in _BUSY_WINERRORS:
                    last_detail = f"file is locked by another process ({exc.strerror})"
                    continue
                return CaptureResult(CaptureStatus.PERMISSION_DENIED, rel, detail=exc.strerror)
            except OSError as exc:
                if getattr(exc, "winerror", None) in _BUSY_WINERRORS:
                    last_detail = f"file is locked by another process ({exc.strerror})"
                else:
                    last_detail = str(exc)
                continue
            except Exception as exc:
                log.exception("unexpected capture error", extra={"path": rel})
                return CaptureResult(CaptureStatus.FAILED, rel, detail=str(exc))
            ident = file_identity(st) or (
                file_identity(os.stat(abs_path)) if os.path.exists(abs_path) else None
            )
            try:
                # GC never deletes blobs younger than its grace period, and the FK on
                # versions.blob_hash makes a lost race fail loudly (retry) instead of dangling.
                with self.db.write() as s:
                    recorded = record_content(
                        s,
                        root.id,
                        rel,
                        blob_hash=ingest.hash,
                        size=ingest.size,
                        st=st,
                        identity=ident,
                        extra_meta=dict(extra_meta) if extra_meta else None,
                    )
            except SAIntegrityError as exc:
                # e.g. the blob was garbage-collected between dedup check and commit.
                last_detail = f"metadata conflict: {exc.orig}"
                continue
            self._clear_skip(root, rel)
            if not recorded.created:
                return CaptureResult(
                    CaptureStatus.UNCHANGED,
                    rel,
                    version_id=recorded.version_id,
                    blob_hash=ingest.hash,
                    size=ingest.size,
                )
            status = CaptureStatus.CAPTURED if ingest.created else CaptureStatus.ALREADY_STORED
            return CaptureResult(
                status,
                rel,
                version_id=recorded.version_id,
                operation=recorded.operation,
                blob_hash=ingest.hash,
                size=ingest.size,
                stored_new_blob=ingest.created,
            )
        return CaptureResult(
            CaptureStatus.UNAVAILABLE,
            rel,
            detail=f"gave up after {cap.max_retries + 1} attempts: {last_detail}",
        )
