"""Reconciliation: make the database agree with the filesystem.

Filesystem events are hints, not truth (they are lost on overflow, while the
daemon is stopped, on network shares, ...). The reconciler walks a root and
detects new, modified, deleted and renamed files:

* size + mtime are the cheap change detector; ``deep`` mode re-hashes every file;
* renames are detected by filesystem identity (dev:inode / NTFS file index)
  and, failing that, by a unique content-hash match between a vanished file
  and a new file of the same size;
* a missing root (e.g. an unmounted drive) aborts the scan instead of
  marking every file as deleted.
"""

from __future__ import annotations

import os
import time
from collections import Counter
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from undo_core.config.settings import Settings
from undo_core.database.engine import Database
from undo_core.database.models import Root, Version
from undo_core.database.repositories import FileRepository, SkipRepository
from undo_core.domain import ReconcileReport
from undo_core.filesystem.exclusions import ExclusionMatcher
from undo_core.filesystem.identity import file_identity
from undo_core.filesystem.scanner import ScanEntry, ScanSkip, scan_tree
from undo_core.platform.paths import path_key
from undo_core.storage.content_addressing import hash_file
from undo_core.utils.logging import get_logger
from undo_core.utils.timeutil import utcnow
from undo_core.versioning.capture import (
    SKIP_STATUSES,
    CaptureEngine,
    CaptureResult,
    CaptureStatus,
    RootRef,
)
from undo_core.versioning.version_manager import record_delete, record_move

log = get_logger(__name__)


@dataclass(frozen=True)
class _Known:
    id: int
    rel: str
    size: int | None
    mtime_ns: int | None
    identity: str | None
    blob: str | None


class Reconciler:
    def __init__(
        self,
        db: Database,
        capture: CaptureEngine,
        matcher_for: Callable[[RootRef], ExclusionMatcher],
        settings: Callable[[], Settings],
    ) -> None:
        self.db = db
        self.capture = capture
        self._matcher_for = matcher_for
        self._settings = settings

    def _known_files(self, root: RootRef, prefix: str) -> dict[str, _Known]:
        with self.db.read() as s:
            repo = FileRepository(s)
            files = repo.active_under(root.id, prefix) if prefix else repo.active_for_root(root.id)
            latest_ids = [f.latest_version_id for f in files if f.latest_version_id]
            blobs: dict[int, str | None] = {}
            for i in range(0, len(latest_ids), 500):
                for v in s.query(Version).filter(Version.id.in_(latest_ids[i : i + 500])):
                    blobs[v.id] = v.blob_hash
            return {
                f.path_key: _Known(
                    f.id,
                    f.relative_path,
                    f.last_size,
                    f.last_mtime_ns,
                    f.filesystem_identity,
                    blobs.get(f.latest_version_id or -1),
                )
                for f in files
            }

    def reconcile(
        self,
        root: RootRef,
        *,
        prefix: str = "",
        deep: bool = False,
        detect_deletions: bool = True,
        progress: Callable[[str], None] | None = None,
    ) -> ReconcileReport:
        started = time.monotonic()
        settings = self._settings()
        report = ReconcileReport(
            root_id=root.id, root_path=str(root.path), prefix=prefix, deep=deep
        )
        if not root.path.is_dir():
            report.errors.append(
                f"root {root.path} is not accessible; scan aborted (no deletions recorded)"
            )
            log.error("root unavailable", extra={"root": str(root.path)})
            return report
        start_dir = root.path / Path(*prefix.split("/")) if prefix else root.path
        matcher = self._matcher_for(root)

        entries: dict[str, ScanEntry] = {}
        skips: list[ScanSkip] = []
        if start_dir.is_dir():
            for item in scan_tree(
                root.path,
                matcher,
                start=prefix,
                follow_symlinks=settings.monitor.follow_symlinks,
                max_file_size=settings.capture.max_file_size,
            ):
                if isinstance(item, ScanEntry):
                    entries[path_key(item.relative_path)] = item
                else:
                    skips.append(item)
        report.scanned = len(entries)
        if progress:
            progress(f"scanned {len(entries)} files")

        with self.db.write() as s:
            repo = SkipRepository(s)
            repo.clear_root(root.id, prefix)
            for skip in skips:
                repo.record(root.id, skip.relative_path, skip.reason, skip.detail)
        reasons = Counter(skip.reason.split(":", 1)[0] for skip in skips)
        report.skip_reasons = dict(reasons)
        report.skipped = len(skips)

        known = self._known_files(root, prefix)
        new_keys = [k for k in entries if k not in known]
        missing = {k: v for k, v in known.items() if k not in entries}
        changed = [
            k
            for k in entries
            if k in known
            and (
                deep
                or known[k].size != entries[k].stat.st_size
                or known[k].mtime_ns != entries[k].stat.st_mtime_ns
            )
        ]
        report.unchanged = len(entries) - len(new_keys) - len(changed)

        # ---------------------------------------------------------- rename detection
        moved_targets: list[str] = []
        if missing and new_keys:
            by_identity = {v.identity: k for k, v in missing.items() if v.identity}
            remaining_new: list[str] = []
            for k in new_keys:
                entry = entries[k]
                ident = file_identity(entry.stat)
                if ident is None:
                    try:
                        ident = file_identity(os.stat(entry.absolute_path))
                    except OSError:
                        ident = None
                old_key = by_identity.get(ident) if ident else None
                # Inode numbers are recycled after deletion: require a second signal
                # (same file name or same size) before trusting an identity match.
                if old_key is not None and old_key in missing:
                    old = missing[old_key]
                    same_name = old.rel.rsplit("/", 1)[-1] == entry.relative_path.rsplit("/", 1)[-1]
                    if not (same_name or old.size == entry.stat.st_size):
                        old_key = None
                if old_key is not None and old_key in missing:
                    if ident is not None:
                        by_identity.pop(ident, None)
                    self._move(root, missing.pop(old_key).rel, entry.relative_path, report)
                    moved_targets.append(k)
                else:
                    remaining_new.append(k)
            new_keys = remaining_new
            if missing and new_keys:
                by_blob: dict[str, list[str]] = {}
                sizes = {v.size for v in missing.values()}
                for k, v in missing.items():
                    if v.blob:
                        by_blob.setdefault(v.blob, []).append(k)
                remaining_new = []
                for k in new_keys:
                    entry = entries[k]
                    if entry.stat.st_size not in sizes:
                        remaining_new.append(k)
                        continue
                    try:
                        digest, _ = hash_file(entry.absolute_path)
                    except OSError:
                        remaining_new.append(k)
                        continue
                    candidates = [c for c in by_blob.get(digest, []) if c in missing]
                    if len(candidates) == 1:
                        self._move(
                            root, missing.pop(candidates[0]).rel, entry.relative_path, report
                        )
                        moved_targets.append(k)
                    else:
                        remaining_new.append(k)
                new_keys = remaining_new

        # ---------------------------------------------------------- captures
        jobs: list[tuple[str, bool]] = [(k, deep) for k in changed]
        jobs += [(k, False) for k in new_keys]
        jobs += [(k, False) for k in moved_targets]  # pick up content changes made with the move
        workers = max(1, settings.capture.max_concurrent)

        def run(job: tuple[str, bool]) -> CaptureResult:
            key, force = job
            return self.capture.capture(root, entries[key].absolute_path, force_hash=force)

        results: list[CaptureResult] = []
        if jobs:
            with ThreadPoolExecutor(
                max_workers=workers, thread_name_prefix="undo-reconcile"
            ) as pool:
                results = list(pool.map(run, jobs))
        for result in results:
            if result.new_version:
                if result.operation == "CREATE":
                    report.new += 1
                else:
                    report.modified += 1
                if result.status == CaptureStatus.ALREADY_STORED:
                    report.deduplicated += 1
                if result.stored_new_blob:
                    report.stored_bytes += result.size
            elif (
                result.status == CaptureStatus.UNCHANGED or result.status == CaptureStatus.NOT_FOUND
            ):
                pass
            elif result.status in SKIP_STATUSES:
                report.skipped += 1
                report.skip_reasons[result.status.value] = (
                    report.skip_reasons.get(result.status.value, 0) + 1
                )
                if result.status in (
                    CaptureStatus.FAILED,
                    CaptureStatus.UNAVAILABLE,
                    CaptureStatus.PERMISSION_DENIED,
                ):
                    report.failed += 1
                    if len(report.errors) < 50:
                        report.errors.append(
                            f"{result.relative_path}: {result.status.value} {result.detail or ''}".strip()
                        )

        # ---------------------------------------------------------- deletions
        if detect_deletions and missing:
            gone = [
                v
                for v in missing.values()
                if not os.path.lexists(root.path / Path(*v.rel.split("/")))
            ]
            for i in range(0, len(gone), 200):
                with self.db.write() as s:
                    for v in gone[i : i + 200]:
                        report.deleted += len(record_delete(s, root.id, v.rel, reason="reconcile"))

        if not prefix:
            with self.db.write() as s:
                row = s.get(Root, root.id)
                if row is not None:
                    row.last_scan_at = utcnow()
        report.duration_seconds = round(time.monotonic() - started, 3)
        log.info(
            "reconcile finished",
            extra={
                "root": str(root.path),
                "prefix": prefix,
                "new": report.new,
                "modified": report.modified,
                "deleted": report.deleted,
                "renamed": report.renamed,
                "skipped": report.skipped,
                "seconds": report.duration_seconds,
            },
        )
        return report

    def _move(self, root: RootRef, old_rel: str, new_rel: str, report: ReconcileReport) -> None:
        with self.db.write() as s:
            moved = record_move(s, root.id, old_rel, new_rel)
        report.renamed += len(moved)
