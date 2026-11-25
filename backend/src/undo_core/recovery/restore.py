"""File restore: choose a version, plan, preserve what would be overwritten, write safely."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select

from undo_core.database.engine import Database
from undo_core.database.models import File, Operation, Root, Version
from undo_core.domain import RestoreItem, RestoreResult
from undo_core.platform.paths import is_within, normalize_path, safe_join
from undo_core.recovery.restore_safety import RestoreAction, plan_target, write_verified
from undo_core.roots import find_root_for_path, root_ref
from undo_core.storage.blob_store import BlobStore
from undo_core.utils.errors import (
    ConflictError,
    InvalidInputError,
    NotFoundError,
    StorageIntegrityError,
    UndoError,
)
from undo_core.utils.logging import get_logger
from undo_core.versioning.capture import CaptureEngine, CaptureStatus

log = get_logger(__name__)

_PRESERVED_OK = {CaptureStatus.CAPTURED, CaptureStatus.ALREADY_STORED, CaptureStatus.UNCHANGED}
_PRESERVE_NOT_APPLICABLE = {
    CaptureStatus.EXCLUDED,
    CaptureStatus.TOO_LARGE,
    CaptureStatus.NOT_FOUND,
}


@dataclass(frozen=True)
class RestoreEntry:
    relative_path: str
    version_id: int
    blob_hash: str
    size: int
    meta: dict[str, Any]


def select_version(
    db: Database,
    file_id: int,
    *,
    version_id: int | None = None,
    at: datetime | None = None,
    before_version_id: int | None = None,
) -> Version:
    """Pick the content version to restore according to exactly one selector."""
    if sum(x is not None for x in (version_id, at, before_version_id)) > 1:
        raise InvalidInputError("Use only one of version, at, before")
    with db.read() as s:
        if version_id is not None:
            v = s.get(Version, version_id)
            if v is None or v.file_id != file_id:
                raise NotFoundError(f"Version {version_id} does not belong to this file")
            if v.blob_hash is None:
                raise InvalidInputError(
                    f"Version {version_id} is a deletion marker; pick an earlier version"
                )
            return v
        if before_version_id is not None:
            ref = s.get(Version, before_version_id)
            if ref is None or ref.file_id != file_id:
                raise NotFoundError(f"Version {before_version_id} does not belong to this file")
            prev = s.scalar(
                select(Version)
                .where(
                    Version.file_id == file_id, Version.id < ref.id, Version.blob_hash.is_not(None)
                )
                .order_by(Version.id.desc())
                .limit(1)
            )
            if prev is None:
                raise NotFoundError(
                    f"There is no content version before version {before_version_id}"
                )
            return prev
        if at is not None:
            v = s.scalar(
                select(Version)
                .where(Version.file_id == file_id, Version.timestamp <= at)
                .order_by(Version.timestamp.desc(), Version.id.desc())
                .limit(1)
            )
            if v is None:
                raise NotFoundError("The file has no version at or before that time")
            if v.operation == Operation.DELETE or v.blob_hash is None:
                raise NotFoundError("The file was deleted at that time")
            return v
        v = s.scalar(
            select(Version)
            .where(Version.file_id == file_id, Version.blob_hash.is_not(None))
            .order_by(Version.id.desc())
            .limit(1)
        )
        if v is None:
            raise NotFoundError("The file has no stored content")
        return v


class RestoreEngine:
    def __init__(self, db: Database, store: BlobStore, capture: CaptureEngine) -> None:
        self.db = db
        self.store = store
        self.capture = capture
        # Called with the destinations a (non dry-run) restore wrote; used to clear merge drafts.
        self.after_write: Callable[[list[str]], object] | None = None

    def _preserve_existing(self, dest: Path) -> tuple[bool, int | None, str | None]:
        """Capture the content about to be overwritten so the overwrite is itself undoable."""
        with self.db.read() as s:
            root = find_root_for_path(s, dest)
            ref = root_ref(root) if root else None
        if ref is None:
            return (
                True,
                None,
                "destination is outside tracked roots; previous content not versioned",
            )
        result = self.capture.capture(ref, dest, force_hash=True, record_skips=False)
        if result.status in _PRESERVED_OK:
            return True, result.version_id, None
        if result.status in _PRESERVE_NOT_APPLICABLE:
            return True, None, f"previous content not versioned ({result.status.value})"
        return (
            False,
            None,
            f"could not preserve current content: {result.status.value} {result.detail or ''}",
        )

    def restore_entries(
        self,
        entries: list[RestoreEntry],
        dest_for: dict[str, Path],
        *,
        overwrite: bool,
        dry_run: bool,
    ) -> RestoreResult:
        result = RestoreResult(dry_run=dry_run, items=[])
        restored_meta: set[str] = set()
        not_restored: set[str] = set()
        hashes = sorted({e.blob_hash for e in entries})
        with self.store.pin(hashes, "restore") if not dry_run and hashes else _null():
            for entry in entries:
                dest = dest_for[entry.relative_path]
                action, detail = plan_target(dest, entry.blob_hash, entry.size, overwrite=overwrite)
                item = RestoreItem(
                    relative_path=entry.relative_path,
                    destination=str(dest),
                    action=action.value,
                    version_id=entry.version_id,
                    blob_hash=entry.blob_hash,
                    size=entry.size,
                    detail=detail,
                )
                if not dry_run and action in (RestoreAction.CREATE, RestoreAction.OVERWRITE):
                    try:
                        if action == RestoreAction.OVERWRITE:
                            ok, pre_vid, note = self._preserve_existing(dest)
                            if not ok:
                                raise ConflictError(note or "could not preserve existing content")
                            if pre_vid:
                                result.pre_restore_versions.append(pre_vid)
                            if note:
                                item.detail = note
                        report = write_verified(
                            self.store,
                            entry.blob_hash,
                            dest,
                            entry.meta,
                            allow_replace=action == RestoreAction.OVERWRITE,
                        )
                        restored_meta.update(report.restored)
                        not_restored.update(report.not_restored)
                    except (UndoError, OSError) as exc:
                        item.action = RestoreAction.ERROR.value
                        item.detail = getattr(exc, "message", None) or str(exc)
                        if isinstance(exc, StorageIntegrityError):
                            item.detail = f"stored data failed verification: {item.detail}"
                        log.error("restore failed", extra={"dest": str(dest), "error": item.detail})
                result.items.append(item)
        for item in result.items:
            if item.action == RestoreAction.CREATE:
                result.created += 1
            elif item.action == RestoreAction.OVERWRITE:
                result.overwritten += 1
            elif item.action == RestoreAction.IDENTICAL:
                result.identical += 1
            elif item.action == RestoreAction.CONFLICT:
                result.conflicts += 1
            else:
                result.errors += 1
        result.metadata_restored = sorted(restored_meta)
        result.metadata_not_restored = sorted(not_restored)
        if not dry_run and self.after_write is not None:
            written = [
                i.destination
                for i in result.items
                if i.action in (RestoreAction.CREATE.value, RestoreAction.OVERWRITE.value)
            ]
            if written:
                self.after_write(written)
        return result

    def restore_file(
        self,
        file_id: int,
        *,
        version_id: int | None = None,
        at: datetime | None = None,
        before_version_id: int | None = None,
        destination: str | None = None,
        overwrite: bool = False,
        dry_run: bool = False,
    ) -> RestoreResult:
        version = select_version(
            self.db, file_id, version_id=version_id, at=at, before_version_id=before_version_id
        )
        with self.db.read() as s:
            file = s.get(File, file_id)
            assert file is not None
            root = s.get(Root, file.root_id)
            assert root is not None
            original = safe_join(Path(root.absolute_path), file.relative_path)
        if destination:
            dest = normalize_path(destination)
            if dest.is_dir() or destination.endswith(("/", "\\")):
                dest = dest / original.name
        else:
            dest = original
        assert version.blob_hash is not None
        entry = RestoreEntry(
            file.relative_path,
            version.id,
            version.blob_hash,
            version.file_size,
            dict(version.meta or {}),
        )
        return self.restore_entries(
            [entry], {entry.relative_path: dest}, overwrite=overwrite, dry_run=dry_run
        )

    def restore_tree(
        self,
        root_id: int,
        entries: list[RestoreEntry],
        *,
        prefix: str,
        destination: str | None,
        overwrite: bool,
        dry_run: bool,
    ) -> RestoreResult:
        """Restore many files below ``prefix``; with ``destination`` the layout is re-rooted there."""
        with self.db.read() as s:
            root = s.get(Root, root_id)
            if root is None:
                raise NotFoundError(f"Root {root_id} not found")
            root_path = Path(root.absolute_path)
        base = (
            normalize_path(destination)
            if destination
            else (safe_join(root_path, prefix) if prefix else root_path)
        )
        dest_for: dict[str, Path] = {}
        strip = prefix.rstrip("/") + "/" if prefix else ""
        for e in entries:
            rel = (
                e.relative_path[len(strip) :]
                if strip and e.relative_path.startswith(strip)
                else e.relative_path
            )
            dest = safe_join(base, rel)
            if not is_within(dest, base):
                raise InvalidInputError(f"Refusing to restore outside {base}")
            dest_for[e.relative_path] = dest
        return self.restore_entries(entries, dest_for, overwrite=overwrite, dry_run=dry_run)


class _null:
    def __enter__(self) -> None:
        return None

    def __exit__(self, *exc: object) -> None:
        return None
