"""UndoService: the single business-logic facade used by the API, CLI, TUI and GUI.

Every public method returns pydantic models from :mod:`undo_core.domain` (or
lists of them) so callers in other processes see exactly the same data.
"""

from __future__ import annotations

import os
import shutil
import sys
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

from sqlalchemy import delete, func, select, update

from undo_core import API_VERSION, __version__
from undo_core.config.defaults import BUILTIN_EXCLUSIONS
from undo_core.context import UndoContext
from undo_core.database.models import (
    Blob,
    BlobStatus,
    Exclusion,
    File,
    PathHistory,
    Root,
    SkipRecord,
    Snapshot,
    SnapshotEntry,
    Version,
)
from undo_core.database.repositories import (
    ExclusionRepository,
    FileRepository,
    MetaRepository,
    RootRepository,
    SkipRepository,
    VersionRepository,
)
from undo_core.domain import (
    AddRootResult,
    BlobInfo,
    DiffHunk,
    DiffRow,
    DoctorCheck,
    ExclusionInfo,
    FileDiff,
    FileHistory,
    FileInfo,
    FilePage,
    ForgetResult,
    GCReport,
    HealthInfo,
    MergeDraft,
    MergeSource,
    MergeWriteResult,
    ReconcileReport,
    RestoreResult,
    RetentionReport,
    RootInfo,
    SearchHit,
    SkipInfo,
    SnapshotDetail,
    SnapshotDiff,
    SnapshotInfo,
    StatusInfo,
    StorageStats,
    VerifyReport,
    VersionContent,
    VersionDetail,
    VersionDiff,
    VersionInfo,
)
from undo_core.platform.paths import (
    PLATFORM_NAME,
    is_within,
    path_key,
    resolve_root_path,
    to_relative,
    validate_relative,
)
from undo_core.recovery import merge as merging
from undo_core.recovery.deleted_files import list_deleted
from undo_core.recovery.directory_restore import entries_at, entries_from_snapshot
from undo_core.recovery.restore import RestoreEntry
from undo_core.roots import find_root_for_path, resolve_path, root_ref
from undo_core.storage.deduplication import compute_accounting
from undo_core.storage.garbage_collection import collect_garbage
from undo_core.storage.integrity import verify_storage
from undo_core.utils.errors import (
    ConflictError,
    InvalidInputError,
    NotFoundError,
    PathOutsideRootError,
)
from undo_core.utils.logging import get_logger
from undo_core.utils.timeutil import parse_timestamp, to_aware, to_db, utcnow
from undo_core.versioning import history, snapshots
from undo_core.versioning.capture import RootRef
from undo_core.versioning.diff import (
    MAX_DIFF_BYTES,
    TEXT_SAMPLE,
    is_probably_text,
    line_ending_note,
    side_by_side,
    unified_diff,
)
from undo_core.versioning.forget import (
    apply_forget,
    plan_delete_versions,
    plan_forget,
    skip_records_cleanup,
)
from undo_core.versioning.retention import apply_retention, plan_retention

log = get_logger(__name__)


class DaemonHooks(Protocol):
    """Implemented by the daemon so service calls can update live components."""

    def on_roots_changed(self) -> None: ...

    def request_reconcile(self, root_id: int, prefix: str = "") -> None: ...

    def health(self) -> HealthInfo: ...

    def watch_mode(self, root_id: int) -> str | None: ...


def _as_time(value: datetime | str | None) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        # Programmatic datetimes follow the internal convention: naive means UTC.
        return value if value.tzinfo is None else to_db(value)
    return parse_timestamp(value)  # user text: naive means local time


def _installed_app_dir() -> Path | None:
    """Undo's own program folder in an installed (frozen) build: <app> holding backend/undo.exe."""
    if not getattr(sys, "frozen", False):
        return None
    return Path(sys.executable).resolve().parent.parent


class UndoService:
    def __init__(self, ctx: UndoContext, hooks: DaemonHooks | None = None) -> None:
        self.ctx = ctx
        self.hooks = hooks

    @property
    def db(self):  # type: ignore[no-untyped-def]
        return self.ctx.db

    # ================================================================== status
    def status(self) -> StatusInfo:
        with self.db.read() as s:
            files_active, files_deleted = FileRepository(s).counts()
            acc = compute_accounting(s)
            info = StatusInfo(
                initialized=True,
                data_dir=str(self.ctx.paths.data_dir),
                daemon_running=self.hooks is not None,
                daemon=self.hooks.health() if self.hooks else None,
                root_count=s.scalar(select(func.count()).select_from(Root)) or 0,
                file_count=files_active,
                deleted_file_count=files_deleted,
                version_count=VersionRepository(s).count(),
                snapshot_count=s.scalar(select(func.count()).select_from(Snapshot)) or 0,
                skipped_count=SkipRepository(s).count(),
                stored_bytes=acc.stored_bytes,
                logical_bytes=acc.logical_bytes,
            )
        return info

    def health(self) -> HealthInfo | None:
        return self.hooks.health() if self.hooks else None

    # ================================================================== roots
    def _root_info(
        self, root: Root, counts: dict[int, tuple[int, int]], vcounts: dict[int, int]
    ) -> RootInfo:
        active, deleted = counts.get(root.id, (0, 0))
        return RootInfo(
            id=root.id,
            path=root.absolute_path,
            platform=root.platform,
            enabled=root.enabled,
            created_at=to_aware(root.created_at) or root.created_at,
            last_scan_at=to_aware(root.last_scan_at),
            file_count=active,
            deleted_file_count=deleted,
            version_count=vcounts.get(root.id, 0),
            watch_mode=self.hooks.watch_mode(root.id) if self.hooks else None,
            configuration=dict(root.configuration or {}),
        )

    def list_roots(self) -> list[RootInfo]:
        with self.db.read() as s:
            counts = FileRepository(s).counts_by_root()
            vcounts = VersionRepository(s).count_by_root()
            return [self._root_info(r, counts, vcounts) for r in RootRepository(s).all()]

    def get_root(self, root_ref_: int | str) -> RootInfo:
        root = self._find_root(root_ref_)
        with self.db.read() as s:
            counts = FileRepository(s).counts_by_root()
            vcounts = VersionRepository(s).count_by_root()
            return self._root_info(root, counts, vcounts)

    def _find_root(self, ref: int | str) -> Root:
        with self.db.read() as s:
            if isinstance(ref, int) or (isinstance(ref, str) and ref.isdigit()):
                root = s.get(Root, int(ref))
                if root is None:
                    raise NotFoundError(f"Root {ref} not found")
                return root
            path = resolve_root_path(ref)
            root = RootRepository(s).by_key(path_key(str(path)))
            if root is None:
                root = find_root_for_path(s, Path(ref))
                if root is None or path_key(root.absolute_path) != path_key(str(path)):
                    raise NotFoundError(f"{ref} is not a tracked root (see `undo roots`)")
            return root

    def add_root(self, path: str, *, scan: bool = True) -> AddRootResult:
        target = resolve_root_path(path)
        if not target.exists():
            raise NotFoundError(f"{target} does not exist")
        if not target.is_dir():
            raise InvalidInputError(f"{target} is not a directory")
        data_dir = self.ctx.paths.data_dir
        if is_within(target, data_dir):
            raise InvalidInputError("Cannot track Undo's own data directory or anything inside it")
        app_dir = _installed_app_dir()
        if app_dir is not None and is_within(target, app_dir):
            raise InvalidInputError(
                f"{target} is inside Undo's program folder ({app_dir}); choose a folder with your files"
            )
        with self.db.write() as s:
            for existing in RootRepository(s).all():
                if path_key(existing.absolute_path) == path_key(str(target)):
                    raise ConflictError(f"{target} is already tracked (root {existing.id})")
                if is_within(target, existing.absolute_path):
                    raise ConflictError(f"{target} is inside tracked root {existing.absolute_path}")
                if is_within(existing.absolute_path, target):
                    raise ConflictError(
                        f"{target} contains tracked root {existing.absolute_path}; untrack it first"
                    )
            root = Root(
                absolute_path=str(target),
                path_key=path_key(str(target)),
                platform=PLATFORM_NAME,
                created_at=utcnow(),
                enabled=True,
                configuration={},
            )
            s.add(root)
            s.flush()
            root_id = root.id
        log.info("root added", extra={"root": str(target), "id": root_id})
        report: ReconcileReport | None = None
        if self.hooks is not None:
            self.hooks.on_roots_changed()
            if scan:
                self.hooks.request_reconcile(root_id, "")
        elif scan:
            report = self.ctx.reconciler.reconcile(RootRef(root_id, target))
        return AddRootResult(root=self.get_root(root_id), scan=report)

    def set_root_enabled(self, ref: int | str, enabled: bool) -> RootInfo:
        root = self._find_root(ref)
        with self.db.write() as s:
            row = s.get(Root, root.id)
            assert row is not None
            row.enabled = enabled
        if self.hooks:
            self.hooks.on_roots_changed()
            if enabled:
                self.hooks.request_reconcile(root.id, "")
        return self.get_root(root.id)

    def remove_root(self, ref: int | str, *, purge: bool = False) -> RootInfo:
        """Stop tracking. Without ``purge`` the root is disabled and its history kept."""
        root = self._find_root(ref)
        info = self.get_root(root.id)
        if not purge:
            return self.set_root_enabled(root.id, False)
        with self.db.write() as s:
            snap_ids = select(Snapshot.id).where(Snapshot.root_id == root.id).scalar_subquery()
            file_ids = select(File.id).where(File.root_id == root.id).scalar_subquery()
            s.execute(delete(SnapshotEntry).where(SnapshotEntry.snapshot_id.in_(snap_ids)))
            s.execute(
                update(Version)
                .where(Version.file_id.in_(file_ids))
                .values(parent_version_id=None, snapshot_id=None)
            )
            s.execute(delete(Snapshot).where(Snapshot.root_id == root.id))
            s.execute(delete(Version).where(Version.file_id.in_(file_ids)))
            s.execute(delete(PathHistory).where(PathHistory.file_id.in_(file_ids)))
            s.execute(delete(File).where(File.root_id == root.id))
            s.execute(delete(SkipRecord).where(SkipRecord.root_id == root.id))
            s.execute(delete(Exclusion).where(Exclusion.root_id == root.id))
            s.execute(delete(Root).where(Root.id == root.id))
        self.ctx.invalidate_exclusions()
        if self.hooks:
            self.hooks.on_roots_changed()
        log.info("root purged", extra={"root": root.absolute_path})
        return info

    def scan(self, target: str | int | None = None, *, deep: bool = False) -> list[ReconcileReport]:
        """Reconcile one root, a directory inside a root, or every enabled root."""
        jobs: list[tuple[RootRef, str]] = []
        with self.db.read() as s:
            if target is None or target == "":
                jobs = [(root_ref(r), "") for r in RootRepository(s).all(enabled_only=True)]
            elif isinstance(target, int) or str(target).isdigit():
                root = s.get(Root, int(target))
                if root is None:
                    raise NotFoundError(f"Root {target} not found")
                jobs = [(root_ref(root), "")]
            else:
                root = find_root_for_path(s, Path(str(target)))
                if root is None:
                    raise NotFoundError(f"{target} is not inside a tracked root")
                rel = to_relative(Path(root.absolute_path), resolve_root_path(str(target)))
                if rel and not Path(str(target)).is_dir():
                    rel = rel.rsplit("/", 1)[0] if "/" in rel else ""
                jobs = [(root_ref(root), rel)]
        return [self.ctx.reconciler.reconcile(r, prefix=p, deep=deep) for r, p in jobs]

    # ================================================================== files & history
    def list_files(
        self,
        *,
        root_id: int | None = None,
        query: str | None = None,
        include_deleted: bool = False,
        deleted_only: bool = False,
        prefix: str | None = None,
        limit: int = 200,
        offset: int = 0,
        sort: str = "path",
        descending: bool = False,
    ) -> FilePage:
        limit = max(1, min(limit, 5000))
        with self.db.read() as s:
            return history.list_files(
                s,
                root_id=root_id,
                query=query,
                include_deleted=include_deleted,
                deleted_only=deleted_only,
                prefix=prefix,
                limit=limit,
                offset=max(0, offset),
                sort=sort,
                descending=descending,
            )

    def get_file(self, file_id: int) -> FileInfo:
        with self.db.read() as s:
            return history.get_file_info(s, file_id)

    def resolve_file(self, path: str) -> FileInfo:
        with self.db.read() as s:
            target = resolve_path(s, path)
            if target.file_id is None:
                raise NotFoundError(f"{path} is a directory, not a file")
            return history.get_file_info(s, target.file_id)

    def file_history(
        self, *, file_id: int | None = None, path: str | None = None, limit: int | None = None
    ) -> FileHistory:
        if file_id is None:
            if not path:
                raise InvalidInputError("Give a file id or a path")
            file_id = self.resolve_file(path).id
        with self.db.read() as s:
            return history.file_history(s, file_id, limit)

    def get_version(self, version_id: int) -> VersionDetail:
        with self.db.read() as s:
            version = VersionRepository(s).get(version_id)
            if version is None:
                raise NotFoundError(f"Version {version_id} not found")
            file_info = history.get_file_info(s, version.file_id)
            blob_row = s.get(Blob, version.blob_hash) if version.blob_hash else None
            blob: BlobInfo | None = history.blob_info(s, blob_row) if blob_row else None
            prev_id, next_id = history.neighbours(s, version)
            vinfo = history.version_info(version, file_info.root_id, file_info.root_path)
        is_text = False
        if blob is not None and blob.status == BlobStatus.OK:
            try:
                sample = next(iter(self.ctx.store.iter_content(blob.hash)), b"")[:TEXT_SAMPLE]
                is_text = is_probably_text(sample)
            except Exception:
                is_text = False
        return VersionDetail(
            version=vinfo,
            file=file_info,
            blob=blob,
            previous_version_id=prev_id,
            next_version_id=next_id,
            is_text=is_text,
        )

    def version_content(self, version_id: int, *, max_bytes: int = 256 * 1024) -> VersionContent:
        detail = self.get_version(version_id)
        if detail.blob is None:
            raise InvalidInputError(f"Version {version_id} has no content (deletion marker)")
        size = detail.blob.original_size
        if not detail.is_text:
            return VersionContent(
                version_id=version_id, is_text=False, size=size, truncated=size > 0, text=None
            )
        data = bytearray()
        for block in self.ctx.store.iter_content(detail.blob.hash):
            data.extend(block)
            if len(data) >= max_bytes:
                break
        truncated = size > max_bytes
        if not truncated:
            from undo_core.storage.content_addressing import hash_bytes

            if hash_bytes(bytes(data)) != detail.blob.hash:
                raise InvalidInputError("Stored content failed verification")
        from undo_core.versioning.diff import decode_text

        return VersionContent(
            version_id=version_id,
            is_text=True,
            size=size,
            truncated=truncated,
            text=decode_text(bytes(data[:max_bytes])),
        )

    def iter_version_bytes(self, version_id: int) -> tuple[VersionDetail, Iterator[bytes]]:
        detail = self.get_version(version_id)
        if detail.blob is None:
            raise InvalidInputError(f"Version {version_id} has no content (deletion marker)")
        return detail, self.ctx.store.iter_content(detail.blob.hash)

    def diff_versions(self, a: int, b: int) -> VersionDiff:
        va, vb = self.get_version(a), self.get_version(b)
        size_a = va.blob.original_size if va.blob else 0
        size_b = vb.blob.original_size if vb.blob else 0
        identical = va.version.blob_hash == vb.version.blob_hash
        base: dict[str, Any] = {
            "a": va.version,
            "b": vb.version,
            "identical": identical,
            "size_delta": size_b - size_a,
        }
        if identical:
            return VersionDiff(**base, is_text=va.is_text, diff="", note="contents are identical")
        if (va.blob and not va.is_text) or (vb.blob and not vb.is_text):
            return VersionDiff(**base, is_text=False, note="binary content; no text diff")
        if size_a > MAX_DIFF_BYTES or size_b > MAX_DIFF_BYTES:
            return VersionDiff(**base, is_text=True, note="files too large for an inline diff")
        data_a = self.ctx.store.read_bytes(va.blob.hash) if va.blob else b""
        data_b = self.ctx.store.read_bytes(vb.blob.hash) if vb.blob else b""
        text, truncated = unified_diff(
            data_a, data_b, f"{va.version.relative_path}@v{a}", f"{vb.version.relative_path}@v{b}"
        )
        sbs = side_by_side(data_a, data_b)
        hunks = [
            DiffHunk(
                a_start=h.a_start,
                a_count=h.a_count,
                b_start=h.b_start,
                b_count=h.b_count,
                rows=[DiffRow(**vars(r)) for r in h.rows],
            )
            for h in sbs.hunks
        ]
        note = line_ending_note(data_a, data_b)
        if not hunks:
            note = (note + "; no other changes") if note else "no line changes"
        return VersionDiff(
            **base,
            is_text=True,
            diff=text,
            hunks=hunks,
            added=sbs.added,
            removed=sbs.removed,
            truncated=truncated or sbs.truncated,
            note=note,
        )

    def diff_version_with_file(self, version_id: int, path: str | None = None) -> FileDiff:
        """Compare a stored version with a file on disk (default: the file's current location).

        Left is the file now, right is the version: what a restore would change. Only files
        inside a tracked folder can be read, so the API cannot be used to read arbitrary files.
        A missing file compares as empty (a restore would create it).
        """
        detail = self.get_version(version_id)
        if detail.blob is None:
            raise InvalidInputError(f"Version {version_id} records a deletion; it has no content")
        target = Path(path) if path else Path(detail.version.absolute_path)
        with self.db.read() as s:
            if find_root_for_path(s, target) is None:
                raise PathOutsideRootError(
                    f"{target} is not inside a tracked folder; only tracked files can be compared"
                )
        exists = target.is_file()
        current_size = target.stat().st_size if exists else 0
        base: dict[str, Any] = {
            "version": detail.version,
            "path": str(target),
            "exists": exists,
            "size_delta": detail.blob.original_size - current_size,
        }
        if not detail.is_text:
            return FileDiff(
                **base, identical=False, is_text=False, note="binary content; no text diff"
            )
        if detail.blob.original_size > MAX_DIFF_BYTES or current_size > MAX_DIFF_BYTES:
            return FileDiff(
                **base, identical=False, is_text=True, note="files too large for an inline diff"
            )
        stored = self.ctx.store.read_bytes(detail.blob.hash)  # verified against its hash
        current = target.read_bytes() if exists else b""
        if exists and not is_probably_text(current[:TEXT_SAMPLE]):
            return FileDiff(
                **base,
                identical=False,
                is_text=False,
                note="the file on disk is binary; no text diff",
            )
        if exists and current == stored:
            return FileDiff(**base, identical=True, is_text=True, note="contents are identical")
        text, truncated = unified_diff(
            current, stored, f"{target.name} (now on disk)", f"{target.name}@v{version_id}"
        )
        sbs = side_by_side(current, stored)
        hunks = [
            DiffHunk(
                a_start=h.a_start,
                a_count=h.a_count,
                b_start=h.b_start,
                b_count=h.b_count,
                rows=[DiffRow(**vars(r)) for r in h.rows],
            )
            for h in sbs.hunks
        ]
        notes = []
        if not exists:
            notes.append("the file is not on disk; a restore would create it")
        endings = line_ending_note(current, stored) if exists else None
        if endings:
            notes.append(endings)
        if exists and not hunks:
            notes.append("no line changes")
        return FileDiff(
            **base,
            identical=False,
            is_text=True,
            diff=text,
            hunks=hunks,
            added=sbs.added,
            removed=sbs.removed,
            truncated=truncated or sbs.truncated,
            note="; ".join(notes) or None,
        )

    # ================================================================== merge (resolve a restore)
    def _tracked_target(self, path: Path) -> RootRef:
        with self.db.read() as s:
            root = find_root_for_path(s, path)
            if root is None:
                raise PathOutsideRootError(
                    f"{path} is not inside a tracked folder; only tracked files can be merged"
                )
            return root_ref(root)

    def merge_source(self, version_id: int, path: str | None = None) -> MergeSource:
        """Both texts for a merge editor: the file on disk now and the stored version."""
        detail = self.get_version(version_id)
        if detail.blob is None:
            raise InvalidInputError(f"Version {version_id} records a deletion; it has no content")
        target = Path(path) if path else Path(detail.version.absolute_path)
        self._tracked_target(target)
        exists = target.is_file()
        current_size = target.stat().st_size if exists else 0
        if detail.blob.original_size > MAX_DIFF_BYTES or current_size > MAX_DIFF_BYTES:
            raise InvalidInputError(
                "The file is too large to merge here; restore it to another folder"
            )
        if not detail.is_text:
            raise InvalidInputError(
                "Binary files cannot be merged; restore the version or keep the file"
            )
        stored = self.ctx.store.read_bytes(detail.blob.hash)
        current = target.read_bytes() if exists else b""
        if exists and not is_probably_text(current[:TEXT_SAMPLE]):
            raise InvalidInputError("The file on disk is binary and cannot be merged")
        current_lines, version_lines = merging.line_pair(current, stored)
        sbs = side_by_side(current, stored)
        hunks = [
            DiffHunk(
                a_start=h.a_start,
                a_count=h.a_count,
                b_start=h.b_start,
                b_count=h.b_count,
                rows=[DiffRow(**vars(r)) for r in h.rows],
            )
            for h in sbs.hunks
        ]
        raw_draft = merging.load_draft(self.ctx.paths.data_dir, str(target))
        draft = MergeDraft.model_validate(raw_draft) if raw_draft else None
        return MergeSource(
            version=detail.version,
            path=str(target),
            exists=exists,
            current_lines=current_lines,
            version_lines=version_lines,
            current_hash=merging.content_hash(current),
            line_ending=merging.detect_line_ending(current, stored),
            hunks=hunks,
            identical=exists and current == stored,
            draft=draft,
        )

    def merge_write(
        self,
        *,
        path: str,
        text: str,
        version_id: int,
        expected_hash: str | None = None,
    ) -> MergeWriteResult:
        """Write a merged result to ``path``. The current content is saved as a version first."""
        target = Path(path)
        ref = self._tracked_target(target)
        detail = self.get_version(version_id)
        stored = self.ctx.store.read_bytes(detail.blob.hash) if detail.blob else b""
        current = merging.check_unchanged(target, expected_hash)
        final_newline = (current or stored).endswith(b"\n")
        data = merging.encode_text(
            text, merging.detect_line_ending(current, stored), final_newline=final_newline
        )
        pre_vid: int | None = None
        note: str | None = None
        if target.is_file():
            ok, pre_vid, note = self.ctx.restore._preserve_existing(target)
            if not ok:
                raise ConflictError(note or "could not save the current content first")
        merging.write_merged(target, data)
        captured = self.ctx.capture.capture(ref, target, force_hash=True)
        merging.delete_drafts(self.ctx.paths.data_dir, [str(target)])
        log.info("merge written", extra={"path": str(target), "bytes": len(data)})
        return MergeWriteResult(
            path=str(target),
            bytes_written=len(data),
            pre_restore_version_id=pre_vid,
            version_id=captured.version_id,
            note=note,
        )

    def list_merge_drafts(self) -> list[MergeDraft]:
        return [MergeDraft.model_validate(d) for d in merging.list_drafts(self.ctx.paths.data_dir)]

    def save_merge_draft(
        self,
        *,
        path: str,
        version_id: int,
        text: str,
        choices: dict[str, str] | None = None,
        edited: bool = False,
    ) -> MergeDraft:
        self._tracked_target(Path(path))
        return MergeDraft.model_validate(
            merging.save_draft(
                self.ctx.paths.data_dir,
                path=path,
                version_id=version_id,
                text=text,
                choices=choices or {},
                edited=edited,
            )
        )

    def delete_merge_draft(self, path: str) -> int:
        return merging.delete_drafts(self.ctx.paths.data_dir, [path])

    def activity(
        self, *, limit: int = 100, root_id: int | None = None, since: str | None = None
    ) -> list[VersionInfo]:
        with self.db.read() as s:
            return history.activity(
                s, limit=max(1, min(limit, 5000)), root_id=root_id, since=_as_time(since)
            )

    def search(self, query: str, *, limit: int = 100) -> list[SearchHit]:
        if not query.strip():
            raise InvalidInputError("Search query must not be empty")
        with self.db.read() as s:
            return history.search(s, query.strip(), max(1, min(limit, 1000)))

    def deleted_files(
        self, *, root_id: int | None = None, path: str | None = None, limit: int = 1000
    ) -> list[FileInfo]:
        prefix = ""
        if path:
            with self.db.read() as s:
                target = resolve_path(s, path)
                root_id = target.root.id
                prefix = target.relative_path if target.is_directory else ""
        with self.db.read() as s:
            return list_deleted(s, root_id, prefix, limit)

    def skipped_files(self, *, root_id: int | None = None, limit: int = 1000) -> list[SkipInfo]:
        with self.db.read() as s:
            return history.skipped(s, root_id, limit)

    # ================================================================== restore
    def restore(
        self,
        path: str,
        *,
        version_id: int | None = None,
        at: str | datetime | None = None,
        before_version_id: int | None = None,
        destination: str | None = None,
        overwrite: bool = False,
        dry_run: bool = False,
    ) -> RestoreResult:
        """Restore a file or a directory identified by its (current or historical) path."""
        with self.db.read() as s:
            target = resolve_path(s, path)
        if target.file_id is not None:
            return self.ctx.restore.restore_file(
                target.file_id,
                version_id=version_id,
                at=_as_time(at),
                before_version_id=before_version_id,
                destination=destination,
                overwrite=overwrite,
                dry_run=dry_run,
            )
        if version_id is not None or before_version_id is not None:
            raise InvalidInputError("--version/--before apply to files; use --at for directories")
        return self.restore_directory(
            root_id=target.root.id,
            prefix=target.relative_path,
            at=at,
            destination=destination,
            overwrite=overwrite,
            dry_run=dry_run,
        )

    def restore_version(
        self,
        version_id: int,
        *,
        destination: str | None = None,
        overwrite: bool = False,
        dry_run: bool = False,
    ) -> RestoreResult:
        with self.db.read() as s:
            version = VersionRepository(s).get(version_id)
            if version is None:
                raise NotFoundError(f"Version {version_id} not found")
            file_id = version.file_id
        return self.ctx.restore.restore_file(
            file_id,
            version_id=version_id,
            destination=destination,
            overwrite=overwrite,
            dry_run=dry_run,
        )

    def restore_directory(
        self,
        *,
        root_id: int,
        prefix: str = "",
        at: str | datetime | None = None,
        destination: str | None = None,
        overwrite: bool = False,
        dry_run: bool = False,
    ) -> RestoreResult:
        if prefix:
            prefix = validate_relative(prefix)
        when = _as_time(at) or utcnow()
        entries = entries_at(self.db, root_id, prefix, when)
        if not entries:
            raise NotFoundError("No files existed below that directory at that time")
        return self.ctx.restore.restore_tree(
            root_id,
            entries,
            prefix=prefix,
            destination=destination,
            overwrite=overwrite,
            dry_run=dry_run,
        )

    def recover(
        self,
        path: str,
        *,
        destination: str | None = None,
        overwrite: bool = False,
        dry_run: bool = False,
    ) -> RestoreResult:
        """Recover a deleted file, or every deleted file below a directory."""
        with self.db.read() as s:
            target = resolve_path(s, path)
        if target.file_id is not None:
            return self.ctx.restore.restore_file(
                target.file_id, destination=destination, overwrite=overwrite, dry_run=dry_run
            )
        deleted = self.deleted_files(path=path, limit=100_000)
        entries: list[RestoreEntry] = []
        with self.db.read() as s:
            for f in deleted:
                v = VersionRepository(s).latest_content(f.id)
                if v is not None and v.blob_hash:
                    entries.append(
                        RestoreEntry(
                            f.relative_path, v.id, v.blob_hash, v.file_size, dict(v.meta or {})
                        )
                    )
        if not entries:
            raise NotFoundError("No deleted files with stored content below that path")
        return self.ctx.restore.restore_tree(
            target.root.id,
            entries,
            prefix=target.relative_path,
            destination=destination,
            overwrite=overwrite,
            dry_run=dry_run,
        )

    # ================================================================== snapshots
    def _root_for(self, ref: int | str | None) -> Root:
        if ref is None or ref == "":
            with self.db.read() as s:
                roots = list(RootRepository(s).all())
            if len(roots) == 1:
                return roots[0]
            raise InvalidInputError("Several roots are tracked; specify which one (id or path)")
        if isinstance(ref, int) or str(ref).isdigit():
            return self._find_root(int(ref))
        with self.db.read() as s:
            root = find_root_for_path(s, Path(str(ref)))
        if root is None:
            raise NotFoundError(f"{ref} is not inside a tracked root")
        return root

    def create_snapshot(
        self,
        *,
        name: str,
        root: int | str | None = None,
        description: str | None = None,
        scan: bool = True,
    ) -> SnapshotInfo:
        row = self._root_for(root)
        started = utcnow()
        if scan:
            self.ctx.reconciler.reconcile(RootRef(row.id, Path(row.absolute_path)))
        with self.db.write() as s:
            return snapshots.create_snapshot(
                s, row.id, name, description, scan_started_at=started if scan else None
            )

    def list_snapshots(self, *, root: int | str | None = None) -> list[SnapshotInfo]:
        root_id = self._root_for(root).id if root not in (None, "") else None
        with self.db.read() as s:
            return snapshots.list_snapshots(s, root_id)

    def get_snapshot(self, ref: int | str) -> SnapshotDetail:
        with self.db.read() as s:
            snap = snapshots.find_snapshot(s, str(ref))
            return snapshots.snapshot_detail(s, snap.id)

    def diff_snapshots(self, a: int | str, b: int | str) -> SnapshotDiff:
        with self.db.read() as s:
            sa = snapshots.find_snapshot(s, str(a))
            sb = snapshots.find_snapshot(s, str(b))
            return snapshots.diff_snapshots(s, sa.id, sb.id)

    def restore_snapshot(
        self,
        ref: int | str,
        *,
        destination: str | None = None,
        prefix: str = "",
        overwrite: bool = False,
        dry_run: bool = False,
    ) -> RestoreResult:
        with self.db.read() as s:
            snap = snapshots.find_snapshot(s, str(ref))
            snap_id, root_id = snap.id, snap.root_id
        if prefix:
            prefix = validate_relative(prefix)
        entries = entries_from_snapshot(self.db, snap_id, prefix)
        if not entries:
            raise NotFoundError("The snapshot contains no files below that path")
        return self.ctx.restore.restore_tree(
            root_id,
            entries,
            prefix=prefix,
            destination=destination,
            overwrite=overwrite,
            dry_run=dry_run,
        )

    def rename_snapshot(
        self, ref: int | str, *, name: str | None = None, description: str | None = None
    ) -> SnapshotInfo:
        """Rename a snapshot and/or change its description. Its contents are unchanged."""
        if name is None and description is None:
            raise InvalidInputError("Give a new name and/or description")
        with self.db.write() as s:
            snap = snapshots.find_snapshot(s, str(ref))
            snapshots.rename_snapshot(s, snap.id, name=name, description=description)
            root = s.get(Root, snap.root_id)
            return snapshots.snapshot_info(snap, root.absolute_path if root else "?")

    def delete_snapshot(self, ref: int | str) -> SnapshotInfo:
        with self.db.write() as s:
            snap = snapshots.find_snapshot(s, str(ref))
            return snapshots.delete_snapshot(s, snap.id)

    # ================================================================== storage
    def storage_stats(self) -> StorageStats:
        with self.db.read() as s:
            acc = compute_accounting(s)
            active, deleted = FileRepository(s).counts()
            meta = MetaRepository(s)
            unhealthy = (
                s.scalar(select(func.count()).select_from(Blob).where(Blob.status != BlobStatus.OK))
                or 0
            )
            stats = StorageStats(
                data_dir=str(self.ctx.paths.data_dir),
                root_count=s.scalar(select(func.count()).select_from(Root)) or 0,
                file_count=active,
                deleted_file_count=deleted,
                version_count=VersionRepository(s).count(),
                snapshot_count=s.scalar(select(func.count()).select_from(Snapshot)) or 0,
                blob_count=acc.blob_count,
                chunk_count=acc.chunk_count,
                chunked_blob_count=acc.chunked_blob_count,
                logical_bytes=acc.logical_bytes,
                unique_bytes=acc.unique_bytes,
                stored_bytes=acc.stored_bytes,
                blob_disk_bytes=self.ctx.store.disk_usage(),
                database_bytes=self.db.size_bytes(),
                dedup_savings_bytes=acc.dedup_savings,
                compression_savings_bytes=acc.compression_savings,
                total_savings_bytes=acc.total_savings,
                compression_algorithms=acc.by_algorithm,
                unhealthy_blobs=unhealthy,
                skipped_files=SkipRepository(s).count(),
                last_verify_at=meta.get("last_verify_at"),
                last_verify_ok=meta.get("last_verify_ok"),
                last_gc_at=meta.get("last_gc_at"),
                last_retention_at=meta.get("last_retention_at"),
            )
        return stats

    def verify_storage(self, *, full: bool = True, repair: bool = True) -> VerifyReport:
        out = verify_storage(self.db, self.ctx.store, full=full, repair=repair)
        return VerifyReport(
            full=out.full,
            checked_blobs=out.checked_blobs,
            checked_chunks=out.checked_chunks,
            ok=out.ok,
            missing=out.missing,
            corrupt=out.corrupt,
            repaired=out.repaired,
            orphan_files=out.orphan_files[:1000],
            database_problems=out.database_problems,
            healthy=out.healthy,
            duration_seconds=out.duration_seconds,
        )

    def garbage_collect(
        self, *, dry_run: bool = True, grace_seconds: int | None = None
    ) -> GCReport:
        grace = (
            self.ctx.settings.daemon.gc_grace_seconds if grace_seconds is None else grace_seconds
        )
        out = collect_garbage(self.db, self.ctx.store, dry_run=dry_run, grace_seconds=grace)
        return GCReport(**out.__dict__)

    def apply_retention(self, *, dry_run: bool = True) -> RetentionReport:
        policy = self.ctx.settings.retention
        stored = self.storage_stats().stored_bytes if policy.max_storage_bytes is not None else 0
        if dry_run:
            with self.db.read() as s:
                plan = plan_retention(s, policy, stored_bytes=stored)
            removed = 0
        else:
            with self.db.write() as s:
                plan = plan_retention(s, policy, stored_bytes=stored)
                removed = apply_retention(s, plan)
        return RetentionReport(
            dry_run=dry_run,
            policy=policy.model_dump(),
            files_examined=plan.files_examined,
            versions_examined=plan.versions_examined,
            versions_removed=len(plan.remove) if dry_run else removed,
            files_affected=plan.files_affected,
            estimated_reclaim_bytes=plan.estimated_reclaim_bytes,
            removed_version_ids=sorted(plan.remove)[:1000],
        )

    # ================================================================== forgetting history
    def forget(
        self,
        path: str,
        *,
        before: datetime | str | None = None,
        dry_run: bool = False,
    ) -> ForgetResult:
        """Remove the history of one file, or of every file below a folder.

        Without ``before`` every version goes (the file is forgotten; if it still exists it is
        captured again as a new file by the next scan). With ``before`` only versions older than
        that time go, and each file's latest version is always kept. Snapshot versions stay.
        """
        cutoff = _as_time(before)
        with self.db.read() as s:
            target = resolve_path(s, path)
            root_id = target.root.id
            if target.file_id is not None:
                file_ids = [target.file_id]
                prefix_key: str | None = None
            else:
                prefix_key = (
                    path_key(target.relative_path).rstrip("/") if target.relative_path else None
                )
                q = select(File.id).where(File.root_id == root_id)
                if prefix_key:
                    q = q.where(
                        (File.path_key == prefix_key)
                        | File.path_key.startswith(prefix_key + "/", autoescape=True)
                    )
                file_ids = list(s.scalars(q))
        if not file_ids:
            raise NotFoundError(f"No history recorded for {path}")
        with self.db.read() if dry_run else self.db.write() as s:
            plan = plan_forget(s, file_ids, before=cutoff)
            removed_files: set[int] = set()
            if not dry_run:
                removed_files = apply_forget(s, plan)
                if cutoff is None and target.file_id is None:
                    skip_records_cleanup(s, root_id, prefix_key)
        notes = []
        if plan.kept_in_snapshots:
            notes.append(
                f"{plan.kept_in_snapshots} version(s) kept because they belong to a snapshot; "
                "delete the snapshot to remove them"
            )
        if not dry_run and plan.remove:
            notes.append("run garbage collection (undo storage gc) to free the disk space")
            if cutoff is None:
                if self.hooks is not None:
                    rel = target.relative_path
                    prefix = (
                        rel
                        if target.file_id is None
                        else (rel.rsplit("/", 1)[0] if "/" in rel else "")
                    )
                    self.hooks.request_reconcile(root_id, prefix)
                    notes.append("files that still exist are being captured again as new history")
                else:
                    notes.append("files that still exist are captured again by the next scan")
        log.info(
            "history forgotten",
            extra={"path": path, "versions": len(plan.remove), "dry_run": dry_run},
        )
        return ForgetResult(
            dry_run=dry_run,
            target=path,
            before=cutoff,
            files_examined=plan.files_examined,
            files_affected=len(plan.files_affected),
            files_removed=len(plan.files_emptied) if dry_run else len(removed_files),
            versions_removed=len(plan.remove),
            versions_kept_in_snapshots=plan.kept_in_snapshots,
            removed_version_ids=sorted(plan.remove)[:1000],
            note="; ".join(notes) or None,
        )

    def delete_versions(self, version_ids: list[int], *, dry_run: bool = False) -> ForgetResult:
        """Delete individual versions. The latest version of a file and snapshot versions are refused."""
        with self.db.read() if dry_run else self.db.write() as s:
            plan = plan_delete_versions(s, version_ids)
            if not dry_run:
                apply_forget(s, plan)
        log.info("versions deleted", extra={"versions": sorted(plan.remove), "dry_run": dry_run})
        return ForgetResult(
            dry_run=dry_run,
            target=", ".join(f"v{v}" for v in sorted(plan.remove)),
            files_examined=plan.files_examined,
            files_affected=len(plan.files_affected),
            versions_removed=len(plan.remove),
            removed_version_ids=sorted(plan.remove),
            note=None
            if dry_run
            else "run garbage collection (undo storage gc) to free the disk space",
        )

    # ================================================================== exclusions
    def list_exclusions(self, *, root: int | str | None = None) -> list[ExclusionInfo]:
        out = [ExclusionInfo(pattern=p, source="builtin") for p in BUILTIN_EXCLUSIONS]
        out += [
            ExclusionInfo(pattern=p, source="default")
            for p in self.ctx.settings.exclusions.defaults
        ]
        out.append(ExclusionInfo(pattern=str(self.ctx.paths.data_dir), source="builtin"))
        root_id = self._root_for(root).id if root not in (None, "") else None
        with self.db.read() as s:
            repo = ExclusionRepository(s)
            rows = repo.for_root(root_id) if root_id is not None else repo.all()
            out += [
                ExclusionInfo(
                    id=e.id,
                    pattern=e.pattern,
                    root_id=e.root_id,
                    source="user",
                    created_at=to_aware(e.created_at),
                )
                for e in rows
            ]
        return out

    def add_exclusion(self, pattern: str, *, root: int | str | None = None) -> ExclusionInfo:
        pattern = pattern.strip()
        if not pattern:
            raise InvalidInputError("Pattern must not be empty")
        root_id = self._root_for(root).id if root not in (None, "") else None
        with self.db.write() as s:
            repo = ExclusionRepository(s)
            if repo.find(pattern, root_id):
                raise ConflictError(f"Exclusion {pattern!r} already exists")
            row = Exclusion(root_id=root_id, pattern=pattern, created_at=utcnow())
            s.add(row)
            s.flush()
            info = ExclusionInfo(
                id=row.id,
                pattern=pattern,
                root_id=root_id,
                source="user",
                created_at=to_aware(row.created_at),
            )
        self.ctx.invalidate_exclusions()
        return info

    def remove_exclusion(self, pattern: str, *, root: int | str | None = None) -> ExclusionInfo:
        pattern = pattern.strip()
        if pattern in BUILTIN_EXCLUSIONS:
            raise InvalidInputError(f"{pattern!r} is a built-in exclusion and cannot be removed")
        root_id = self._root_for(root).id if root not in (None, "") else None
        with self.db.write() as s:
            row = ExclusionRepository(s).find(pattern, root_id)
            if row is not None:
                info = ExclusionInfo(
                    id=row.id, pattern=row.pattern, root_id=row.root_id, source="user"
                )
                s.delete(row)
                self.ctx.invalidate_exclusions()
                return info
        defaults = list(self.ctx.settings.exclusions.defaults)
        if pattern in defaults and root_id is None:
            defaults.remove(pattern)
            self.ctx.settings_store.update({"exclusions": {"defaults": defaults}})
            self.ctx.invalidate_exclusions()
            return ExclusionInfo(pattern=pattern, source="default")
        raise NotFoundError(f"No exclusion {pattern!r}")

    # ================================================================== settings
    def get_settings(self) -> dict[str, Any]:
        data = self.ctx.settings_store.as_dict()
        data["_info"] = {
            "data_dir": str(self.ctx.paths.data_dir),
            "config_path": str(self.ctx.paths.config_path),
            "version": __version__,
            "api_version": API_VERSION,
        }
        return data

    def set_setting(self, key: str, value: Any) -> dict[str, Any]:
        self.ctx.settings_store.set_value(key, value)
        self.ctx.invalidate_exclusions()
        return self.get_settings()

    def update_settings(self, values: dict[str, Any]) -> dict[str, Any]:
        values = {k: v for k, v in values.items() if not k.startswith("_")}
        self.ctx.settings_store.update(values)
        self.ctx.invalidate_exclusions()
        return self.get_settings()

    # ================================================================== doctor
    def doctor(self) -> list[DoctorCheck]:
        checks: list[DoctorCheck] = []
        paths = self.ctx.paths
        try:
            probe = paths.staging_dir / ".doctor-probe"
            probe.write_bytes(b"ok")
            probe.unlink()
            checks.append(
                DoctorCheck(name="data directory writable", ok=True, detail=str(paths.data_dir))
            )
        except OSError as exc:
            checks.append(
                DoctorCheck(
                    name="data directory writable", ok=False, severity="error", detail=str(exc)
                )
            )
        problems = self.db.quick_check()
        checks.append(
            DoctorCheck(
                name="database integrity",
                ok=not problems,
                severity="error" if problems else "info",
                detail="; ".join(problems) or "quick_check ok",
            )
        )
        usage = shutil.disk_usage(paths.data_dir)
        low = usage.free < 1024**3
        checks.append(
            DoctorCheck(
                name="free disk space",
                ok=not low,
                severity="warning" if low else "info",
                detail=f"{usage.free / 1024**3:.1f} GiB free on the data volume",
            )
        )
        token_ok = paths.token_path.exists()
        detail = "present"
        if token_ok and os.name != "nt":
            mode = paths.token_path.stat().st_mode & 0o777
            token_ok = mode & 0o077 == 0
            detail = f"mode {oct(mode)}"
        checks.append(
            DoctorCheck(
                name="API token",
                ok=token_ok,
                severity="info" if token_ok else "warning",
                detail=detail,
            )
        )
        with self.db.read() as s:
            roots = list(RootRepository(s).all())
            bad_blobs = (
                s.scalar(select(func.count()).select_from(Blob).where(Blob.status != BlobStatus.OK))
                or 0
            )
        for r in roots:
            ok = Path(r.absolute_path).is_dir()
            checks.append(
                DoctorCheck(
                    name=f"root {r.id} accessible",
                    ok=ok,
                    severity="info" if ok else "warning",
                    detail=r.absolute_path + ("" if r.enabled else " (disabled)"),
                )
            )
        checks.append(
            DoctorCheck(
                name="stored blobs healthy",
                ok=bad_blobs == 0,
                severity="info" if bad_blobs == 0 else "error",
                detail=f"{bad_blobs} blob(s) missing or corrupt"
                if bad_blobs
                else "no known problems (run `undo storage verify`)",
            )
        )
        from undo_core.filesystem.adapters import get_adapter

        info = get_adapter().info()
        checks.append(
            DoctorCheck(
                name="monitoring backend",
                ok=True,
                detail=", ".join(f"{k}={v}" for k, v in info.items()),
            )
        )
        watches = info.get("max_user_watches")
        if isinstance(watches, int) and watches < 65536:
            checks.append(
                DoctorCheck(
                    name="inotify watch limit",
                    ok=False,
                    severity="warning",
                    detail=f"fs.inotify.max_user_watches={watches}; large trees may fall back to polling",
                )
            )
        checks.append(
            DoctorCheck(
                name="independent backup",
                ok=True,
                severity="info",
                detail="Undo keeps local history only; keep a separate backup on another device",
            )
        )
        return checks
