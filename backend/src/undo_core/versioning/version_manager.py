"""Metadata-level version bookkeeping (runs inside short write transactions).

Rules:
* A new version is created only when content differs from the latest version.
* DELETE versions carry no blob; the previous content stays recoverable.
* RENAME/MOVE versions reference the *same* blob as before (no data copied).
* A file deleted and later re-created at the same path continues its history.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from undo_core.database.models import File, Operation, PathHistory, Version
from undo_core.database.repositories import FileRepository, latest_version_for_file
from undo_core.filesystem.identity import file_identity, stat_metadata
from undo_core.platform.paths import parent_of, path_key
from undo_core.utils.timeutil import utcnow


@dataclass(frozen=True)
class RecordResult:
    file_id: int
    version_id: int | None
    created: bool
    operation: str | None


def _open_path_history(session: Session, file: File, rel: str, now: datetime) -> None:
    session.add(
        PathHistory(file_id=file.id, relative_path=rel, path_key=path_key(rel), valid_from=now)
    )


def _close_path_history(session: Session, file: File, now: datetime) -> None:
    rows = (
        session.query(PathHistory)
        .filter(PathHistory.file_id == file.id, PathHistory.valid_to.is_(None))
        .all()
    )
    for row in rows:
        row.valid_to = now


def _add_version(
    session: Session,
    file: File,
    *,
    operation: Operation,
    blob_hash: str | None,
    size: int,
    rel: str,
    meta: dict[str, Any],
    now: datetime,
) -> Version:
    version = Version(
        file_id=file.id,
        blob_hash=blob_hash,
        file_size=size,
        timestamp=now,
        operation=operation.value,
        parent_version_id=file.latest_version_id,
        relative_path=rel,
        meta=meta,
    )
    session.add(version)
    session.flush()
    file.latest_version_id = version.id
    file.version_count = (file.version_count or 0) + 1
    return version


def record_content(
    session: Session,
    root_id: int,
    rel: str,
    *,
    blob_hash: str,
    size: int,
    st: os.stat_result | None,
    identity: str | None = None,
    extra_meta: dict[str, Any] | None = None,
) -> RecordResult:
    files = FileRepository(session)
    now = utcnow()
    meta: dict[str, Any] = stat_metadata(st) if st is not None else {}
    if extra_meta:
        meta.update(extra_meta)
    identity = identity or (file_identity(st) if st is not None else None)
    file = files.active_by_path(root_id, rel)
    operation = Operation.MODIFY
    if file is None:
        operation = Operation.CREATE
        file = files.latest_deleted_by_path(root_id, rel)
        if file is not None:
            file.deleted_at = None
            file.relative_path = rel
            file.path_key = path_key(rel)
            _close_path_history(session, file, now)
            _open_path_history(session, file, rel, now)
        else:
            file = File(
                root_id=root_id,
                relative_path=rel,
                path_key=path_key(rel),
                filesystem_identity=identity,
                file_type="file",
                created_at=now,
                last_seen_at=now,
                version_count=0,
            )
            session.add(file)
            session.flush()
            _open_path_history(session, file, rel, now)
    else:
        latest = latest_version_for_file(session, file)
        if (
            latest is not None
            and latest.blob_hash == blob_hash
            and latest.operation != Operation.DELETE
        ):
            file.last_seen_at = now
            if st is not None:
                file.last_size = st.st_size
                file.last_mtime_ns = st.st_mtime_ns
            if identity:
                file.filesystem_identity = identity
            if file.relative_path != rel:  # case-only rename on case-insensitive FS
                file.relative_path = rel
            return RecordResult(file.id, latest.id, False, None)
    version = _add_version(
        session,
        file,
        operation=operation,
        blob_hash=blob_hash,
        size=size,
        rel=rel,
        meta=meta,
        now=now,
    )
    file.last_seen_at = now
    file.filesystem_identity = identity or file.filesystem_identity
    if st is not None:
        file.last_size = st.st_size
        file.last_mtime_ns = st.st_mtime_ns
    return RecordResult(file.id, version.id, True, operation.value)


def touch_metadata(session: Session, root_id: int, rel: str, st: os.stat_result) -> None:
    file = FileRepository(session).active_by_path(root_id, rel)
    if file is not None:
        file.last_size = st.st_size
        file.last_mtime_ns = st.st_mtime_ns
        file.last_seen_at = utcnow()


def _delete_file(session: Session, file: File, now: datetime, reason: str | None) -> Version:
    latest = latest_version_for_file(session, file)
    version = _add_version(
        session,
        file,
        operation=Operation.DELETE,
        blob_hash=None,
        size=0,
        rel=file.relative_path,
        meta={"reason": reason} if reason else {},
        now=now,
    )
    if latest is not None and latest.blob_hash:
        version.meta = {**version.meta, "last_content_version_id": latest.id}
    file.deleted_at = now
    _close_path_history(session, file, now)
    return version


def record_delete(
    session: Session, root_id: int, rel: str, *, reason: str | None = None
) -> list[RecordResult]:
    """Mark a file, or every file below a directory, as deleted."""
    files = FileRepository(session)
    now = utcnow()
    results: list[RecordResult] = []
    file = files.active_by_path(root_id, rel)
    targets = [file] if file is not None else list(files.active_under(root_id, rel))
    for target in targets:
        version = _delete_file(session, target, now, reason)
        results.append(RecordResult(target.id, version.id, True, Operation.DELETE.value))
    return results


def _move_one(session: Session, file: File, new_rel: str, now: datetime) -> RecordResult:
    files = FileRepository(session)
    old_rel = file.relative_path
    if path_key(old_rel) != path_key(new_rel):
        occupant = files.active_by_path(file.root_id, new_rel)
        if occupant is not None and occupant.id != file.id:
            _delete_file(session, occupant, now, "replaced by move")
            session.flush()
    operation = Operation.RENAME if parent_of(old_rel) == parent_of(new_rel) else Operation.MOVE
    latest = latest_version_for_file(session, file)
    file.relative_path = new_rel
    file.path_key = path_key(new_rel)
    file.last_seen_at = now
    _close_path_history(session, file, now)
    _open_path_history(session, file, new_rel, now)
    version = _add_version(
        session,
        file,
        operation=operation,
        blob_hash=latest.blob_hash if latest else None,
        size=latest.file_size if latest else 0,
        rel=new_rel,
        meta={**(latest.meta if latest else {}), "from_path": old_rel},
        now=now,
    )
    return RecordResult(file.id, version.id, True, operation.value)


def record_move(session: Session, root_id: int, old_rel: str, new_rel: str) -> list[RecordResult]:
    """Rename/move a file or a whole directory. Returns [] if nothing was known at ``old_rel``."""
    files = FileRepository(session)
    now = utcnow()
    file = files.active_by_path(root_id, old_rel)
    if file is not None:
        return [_move_one(session, file, new_rel, now)]
    results: list[RecordResult] = []
    prefix = old_rel.rstrip("/") + "/"
    for child in sorted(files.active_under(root_id, old_rel), key=lambda f: f.path_key):
        suffix = child.relative_path[len(prefix) :]
        results.append(_move_one(session, child, f"{new_rel.rstrip('/')}/{suffix}", now))
        session.flush()
    return results
