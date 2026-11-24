"""Deleted-file discovery. Recovery itself goes through RestoreEngine.restore_file."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from undo_core.database.models import File
from undo_core.domain import FileInfo
from undo_core.platform.paths import path_key
from undo_core.versioning.history import files_to_info


def list_deleted(
    session: Session, root_id: int | None = None, prefix: str = "", limit: int = 1000
) -> list[FileInfo]:
    stmt = select(File).where(File.deleted_at.is_not(None))
    if root_id is not None:
        stmt = stmt.where(File.root_id == root_id)
    if prefix:
        key = path_key(prefix.rstrip("/")) + "/"
        stmt = stmt.where(File.path_key.startswith(key, autoescape=True))
    files = list(session.scalars(stmt.order_by(File.deleted_at.desc()).limit(limit)))
    return [f for f in files_to_info(session, files) if f.latest_version_id is not None]
