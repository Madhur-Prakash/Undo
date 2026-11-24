"""Directory and snapshot restore: rebuild the state of a subtree at a point in time.

Only files that existed below the directory at that time are restored.
Files that exist now but did not exist then are left alone (never deleted).
"""

from __future__ import annotations

from datetime import datetime

from undo_core.database.engine import Database
from undo_core.database.models import Operation, Version
from undo_core.database.repositories import SnapshotRepository, VersionRepository
from undo_core.platform.paths import path_key
from undo_core.recovery.restore import RestoreEntry


def _under(rel: str, prefix: str) -> bool:
    if not prefix:
        return True
    key, pkey = path_key(rel), path_key(prefix.rstrip("/"))
    return key == pkey or key.startswith(pkey + "/")


def entries_at(db: Database, root_id: int, prefix: str, at: datetime) -> list[RestoreEntry]:
    with db.read() as s:
        versions: list[Version] = list(VersionRepository(s).state_at(root_id, at))
    out = [
        RestoreEntry(v.relative_path, v.id, v.blob_hash, v.file_size, dict(v.meta or {}))
        for v in versions
        if v.operation != Operation.DELETE and v.blob_hash and _under(v.relative_path, prefix)
    ]
    return sorted(out, key=lambda e: e.relative_path)


def entries_from_snapshot(db: Database, snapshot_id: int, prefix: str = "") -> list[RestoreEntry]:
    with db.read() as s:
        rows = SnapshotRepository(s).entries(snapshot_id)
        metas = {
            v.id: dict(v.meta or {})
            for v in (s.get(Version, r.version_id) for r in rows)
            if v is not None
        }
    return [
        RestoreEntry(
            r.relative_path, r.version_id, r.blob_hash, r.file_size, metas.get(r.version_id, {})
        )
        for r in rows
        if _under(r.relative_path, prefix)
    ]
