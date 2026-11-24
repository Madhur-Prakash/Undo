"""Query helpers. All functions take an open Session; transaction scope belongs to the caller."""

from __future__ import annotations

import os
from collections.abc import Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.orm import Session

from undo_core.database.models import (
    Blob,
    BlobChunk,
    BlobPin,
    BlobStatus,
    Chunk,
    Exclusion,
    File,
    MetaKV,
    Operation,
    PathHistory,
    Root,
    SkipRecord,
    Snapshot,
    SnapshotEntry,
    Version,
)
from undo_core.platform.paths import path_key
from undo_core.utils.timeutil import utcnow

# Sort keys accepted by FileRepository.query (and GET /files?sort=...).
FILE_SORT_COLUMNS = {
    "path": File.path_key,
    "size": File.last_size,
    "modified": File.last_mtime_ns,
    "version": File.latest_version_id,
    "versions": File.version_count,
}


def _like_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


class RootRepository:
    def __init__(self, session: Session) -> None:
        self.s = session

    def all(self, *, enabled_only: bool = False) -> Sequence[Root]:
        stmt = select(Root).order_by(Root.id)
        if enabled_only:
            stmt = stmt.where(Root.enabled.is_(True))
        return self.s.scalars(stmt).all()

    def get(self, root_id: int) -> Root | None:
        return self.s.get(Root, root_id)

    def by_key(self, key: str) -> Root | None:
        return self.s.scalar(select(Root).where(Root.path_key == key))


class FileRepository:
    def __init__(self, session: Session) -> None:
        self.s = session

    def get(self, file_id: int) -> File | None:
        return self.s.get(File, file_id)

    def active_by_path(self, root_id: int, relative_path: str) -> File | None:
        return self.s.scalar(
            select(File).where(
                File.root_id == root_id,
                File.path_key == path_key(relative_path),
                File.deleted_at.is_(None),
            )
        )

    def latest_deleted_by_path(self, root_id: int, relative_path: str) -> File | None:
        return self.s.scalar(
            select(File)
            .where(
                File.root_id == root_id,
                File.path_key == path_key(relative_path),
                File.deleted_at.is_not(None),
            )
            .order_by(File.deleted_at.desc())
            .limit(1)
        )

    def by_path_any(self, root_id: int, relative_path: str) -> File | None:
        return self.active_by_path(root_id, relative_path) or self.latest_deleted_by_path(
            root_id, relative_path
        )

    def by_historical_path(self, root_id: int, relative_path: str) -> File | None:
        return self.s.scalar(
            select(File)
            .join(PathHistory, PathHistory.file_id == File.id)
            .where(File.root_id == root_id, PathHistory.path_key == path_key(relative_path))
            .order_by(PathHistory.valid_from.desc())
            .limit(1)
        )

    def _prefix_clause(self, prefix: str) -> Any:
        key = path_key(prefix.rstrip("/")) + "/"
        return File.path_key.like(_like_escape(key) + "%", escape="\\")

    def active_under(self, root_id: int, prefix: str) -> Sequence[File]:
        stmt = select(File).where(File.root_id == root_id, File.deleted_at.is_(None))
        if prefix:
            stmt = stmt.where(self._prefix_clause(prefix))
        return self.s.scalars(stmt).all()

    def all_under(self, root_id: int, prefix: str) -> Sequence[File]:
        stmt = select(File).where(File.root_id == root_id)
        if prefix:
            stmt = stmt.where(
                or_(self._prefix_clause(prefix), File.path_key == path_key(prefix.rstrip("/")))
            )
        return self.s.scalars(stmt).all()

    def active_for_root(self, root_id: int) -> Sequence[File]:
        return self.s.scalars(
            select(File).where(File.root_id == root_id, File.deleted_at.is_(None))
        ).all()

    def query(
        self,
        *,
        root_id: int | None,
        text_query: str | None,
        include_deleted: bool,
        deleted_only: bool = False,
        prefix: str | None,
        limit: int,
        offset: int,
        sort: str = "path",
        descending: bool = False,
    ) -> tuple[Sequence[File], int]:
        stmt = select(File)
        if root_id is not None:
            stmt = stmt.where(File.root_id == root_id)
        if deleted_only:
            stmt = stmt.where(File.deleted_at.is_not(None))
        elif not include_deleted:
            stmt = stmt.where(File.deleted_at.is_(None))
        if prefix:
            stmt = stmt.where(self._prefix_clause(prefix))
        if text_query:
            pattern = "%" + _like_escape(path_key(text_query)) + "%"
            stmt = stmt.where(File.path_key.like(pattern, escape="\\"))
        total = self.s.scalar(select(func.count()).select_from(stmt.subquery())) or 0
        column = FILE_SORT_COLUMNS.get(sort, File.path_key)
        primary = column.desc() if descending else column.asc()
        # Files with no size or time yet go last whichever way the list is sorted.
        order: list[Any] = [primary.nulls_last()] if column is not File.path_key else [primary]
        if column is not File.path_key:
            order.append(File.path_key)
        order.append(File.id)
        rows = self.s.scalars(stmt.order_by(*order).limit(limit).offset(offset)).all()
        return rows, total

    def search_history(self, text_query: str, limit: int) -> Sequence[tuple[File, PathHistory]]:
        pattern = "%" + _like_escape(path_key(text_query)) + "%"
        stmt = (
            select(File, PathHistory)
            .join(PathHistory, PathHistory.file_id == File.id)
            .where(PathHistory.path_key.like(pattern, escape="\\"))
            .order_by(PathHistory.valid_from.desc())
            .limit(limit)
        )
        return [(row[0], row[1]) for row in self.s.execute(stmt).all()]

    def counts(self) -> tuple[int, int]:
        active = self.s.scalar(select(func.count()).where(File.deleted_at.is_(None))) or 0
        deleted = self.s.scalar(select(func.count()).where(File.deleted_at.is_not(None))) or 0
        return active, deleted

    def counts_by_root(self) -> dict[int, tuple[int, int]]:
        rows = self.s.execute(
            select(
                File.root_id,
                func.sum(func.iif(File.deleted_at.is_(None), 1, 0)),
                func.sum(func.iif(File.deleted_at.is_not(None), 1, 0)),
            ).group_by(File.root_id)
        ).all()
        return {r[0]: (int(r[1] or 0), int(r[2] or 0)) for r in rows}

    def by_identity(self, root_id: int, identity: str) -> File | None:
        return self.s.scalar(
            select(File).where(
                File.root_id == root_id,
                File.filesystem_identity == identity,
                File.deleted_at.is_(None),
            )
        )


class VersionRepository:
    def __init__(self, session: Session) -> None:
        self.s = session

    def get(self, version_id: int) -> Version | None:
        return self.s.get(Version, version_id)

    def for_file(self, file_id: int, limit: int | None = None) -> Sequence[Version]:
        stmt = (
            select(Version)
            .where(Version.file_id == file_id)
            .order_by(Version.timestamp.desc(), Version.id.desc())
        )
        if limit:
            stmt = stmt.limit(limit)
        return self.s.scalars(stmt).all()

    def latest_content(self, file_id: int, at: datetime | None = None) -> Version | None:
        stmt = select(Version).where(Version.file_id == file_id, Version.blob_hash.is_not(None))
        if at is not None:
            stmt = stmt.where(Version.timestamp <= at)
        return self.s.scalar(stmt.order_by(Version.timestamp.desc(), Version.id.desc()).limit(1))

    def at_time(self, file_id: int, at: datetime) -> Version | None:
        return self.s.scalar(
            select(Version)
            .where(Version.file_id == file_id, Version.timestamp <= at)
            .order_by(Version.timestamp.desc(), Version.id.desc())
            .limit(1)
        )

    def state_at(self, root_id: int, at: datetime) -> Sequence[Version]:
        """Latest version (<= at) of every file of a root; caller filters DELETE."""
        latest = (
            select(Version.file_id, func.max(Version.id).label("vid"))
            .join(File, File.id == Version.file_id)
            .where(File.root_id == root_id, Version.timestamp <= at)
            .group_by(Version.file_id)
            .subquery()
        )
        return self.s.scalars(select(Version).join(latest, latest.c.vid == Version.id)).all()

    def recent(
        self, *, limit: int, root_id: int | None = None, since: datetime | None = None
    ) -> Sequence[tuple[Version, File]]:
        stmt = select(Version, File).join(File, File.id == Version.file_id)
        if root_id is not None:
            stmt = stmt.where(File.root_id == root_id)
        if since is not None:
            stmt = stmt.where(Version.timestamp >= since)
        stmt = stmt.order_by(Version.timestamp.desc(), Version.id.desc()).limit(limit)
        return [(r[0], r[1]) for r in self.s.execute(stmt).all()]

    def count(self) -> int:
        return self.s.scalar(select(func.count()).select_from(Version)) or 0

    def count_by_root(self) -> dict[int, int]:
        rows = self.s.execute(
            select(File.root_id, func.count(Version.id))
            .join(File, File.id == Version.file_id)
            .group_by(File.root_id)
        ).all()
        return {r[0]: int(r[1]) for r in rows}


class BlobRepository:
    def __init__(self, session: Session) -> None:
        self.s = session

    def get(self, blob_hash: str) -> Blob | None:
        return self.s.get(Blob, blob_hash)

    def chunks_for(self, blob_hash: str) -> Sequence[tuple[BlobChunk, Chunk]]:
        rows = self.s.execute(
            select(BlobChunk, Chunk)
            .join(Chunk, Chunk.hash == BlobChunk.chunk_hash)
            .where(BlobChunk.blob_hash == blob_hash)
            .order_by(BlobChunk.seq)
        ).all()
        return [(r[0], r[1]) for r in rows]

    def referenced_hashes(self) -> set[str]:
        refs = set(self.s.scalars(select(Version.blob_hash).where(Version.blob_hash.is_not(None))))
        refs |= set(self.s.scalars(select(SnapshotEntry.blob_hash)))
        refs |= set(self.s.scalars(select(BlobPin.blob_hash)))
        return {r for r in refs if r}

    def mark_status(self, blob_hash: str, status: BlobStatus) -> None:
        self.s.execute(
            update(Blob).where(Blob.hash == blob_hash).values(status=status, verified_at=utcnow())
        )


class SnapshotRepository:
    def __init__(self, session: Session) -> None:
        self.s = session

    def get(self, snapshot_id: int) -> Snapshot | None:
        return self.s.get(Snapshot, snapshot_id)

    def list(self, root_id: int | None = None) -> Sequence[Snapshot]:
        stmt = select(Snapshot).order_by(Snapshot.created_at.desc(), Snapshot.id.desc())
        if root_id is not None:
            stmt = stmt.where(Snapshot.root_id == root_id)
        return self.s.scalars(stmt).all()

    def entries(self, snapshot_id: int) -> Sequence[SnapshotEntry]:
        return self.s.scalars(
            select(SnapshotEntry)
            .where(SnapshotEntry.snapshot_id == snapshot_id)
            .order_by(SnapshotEntry.relative_path)
        ).all()

    def protected_version_ids(self) -> set[int]:
        return set(self.s.scalars(select(SnapshotEntry.version_id).distinct()))


class ExclusionRepository:
    def __init__(self, session: Session) -> None:
        self.s = session

    def for_root(self, root_id: int | None) -> Sequence[Exclusion]:
        stmt = select(Exclusion)
        if root_id is None:
            stmt = stmt.where(Exclusion.root_id.is_(None))
        else:
            stmt = stmt.where(or_(Exclusion.root_id.is_(None), Exclusion.root_id == root_id))
        return self.s.scalars(stmt.order_by(Exclusion.id)).all()

    def all(self) -> Sequence[Exclusion]:
        return self.s.scalars(select(Exclusion).order_by(Exclusion.id)).all()

    def find(self, pattern: str, root_id: int | None) -> Exclusion | None:
        stmt = select(Exclusion).where(Exclusion.pattern == pattern)
        stmt = stmt.where(
            Exclusion.root_id.is_(None) if root_id is None else Exclusion.root_id == root_id
        )
        return self.s.scalar(stmt)


class SkipRepository:
    def __init__(self, session: Session) -> None:
        self.s = session

    def record(self, root_id: int, relative_path: str, reason: str, detail: str | None) -> None:
        key = path_key(relative_path)
        existing = self.s.scalar(
            select(SkipRecord).where(SkipRecord.root_id == root_id, SkipRecord.path_key == key)
        )
        now = utcnow()
        if existing:
            existing.reason = reason
            existing.detail = detail
            existing.last_seen = now
            existing.count += 1
            existing.relative_path = relative_path
        else:
            self.s.add(
                SkipRecord(
                    root_id=root_id,
                    relative_path=relative_path,
                    path_key=key,
                    reason=reason,
                    detail=detail,
                    first_seen=now,
                    last_seen=now,
                )
            )

    def clear(self, root_id: int, relative_path: str) -> None:
        self.s.execute(
            delete(SkipRecord).where(
                SkipRecord.root_id == root_id, SkipRecord.path_key == path_key(relative_path)
            )
        )

    def clear_root(self, root_id: int, prefix: str = "") -> None:
        stmt = delete(SkipRecord).where(SkipRecord.root_id == root_id)
        if prefix:
            key = path_key(prefix.rstrip("/")) + "/"
            stmt = stmt.where(SkipRecord.path_key.like(_like_escape(key) + "%", escape="\\"))
        self.s.execute(stmt)

    def list(self, root_id: int | None, limit: int = 1000) -> Sequence[SkipRecord]:
        stmt = select(SkipRecord).order_by(SkipRecord.last_seen.desc()).limit(limit)
        if root_id is not None:
            stmt = stmt.where(SkipRecord.root_id == root_id)
        return self.s.scalars(stmt).all()

    def count(self) -> int:
        return self.s.scalar(select(func.count()).select_from(SkipRecord)) or 0


class MetaRepository:
    def __init__(self, session: Session) -> None:
        self.s = session

    def get(self, key: str, default: Any = None) -> Any:
        row = self.s.get(MetaKV, key)
        return row.value if row else default

    def set(self, key: str, value: Any) -> None:
        row = self.s.get(MetaKV, key)
        if row:
            row.value = value
            row.updated_at = utcnow()
        else:
            self.s.add(MetaKV(key=key, value=value, updated_at=utcnow()))


class PinRepository:
    def __init__(self, session: Session) -> None:
        self.s = session

    def add(self, blob_hash: str, owner: str) -> int:
        pin = BlobPin(blob_hash=blob_hash, owner=owner, pid=os.getpid(), created_at=utcnow())
        self.s.add(pin)
        self.s.flush()
        return pin.id

    def remove(self, pin_id: int) -> None:
        self.s.execute(delete(BlobPin).where(BlobPin.id == pin_id))

    def purge_older_than(self, cutoff: datetime) -> int:
        result = self.s.execute(delete(BlobPin).where(BlobPin.created_at < cutoff))
        return int(getattr(result, "rowcount", 0) or 0)


def latest_version_for_file(session: Session, file: File) -> Version | None:
    if file.latest_version_id is None:
        return None
    return session.get(Version, file.latest_version_id)


__all__ = [
    "BlobRepository",
    "ExclusionRepository",
    "FileRepository",
    "MetaRepository",
    "Operation",
    "PinRepository",
    "RootRepository",
    "SkipRepository",
    "SnapshotRepository",
    "VersionRepository",
    "latest_version_for_file",
]
