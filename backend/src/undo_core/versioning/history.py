"""Read-side queries: file listings, history, activity log and search."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from undo_core.database.models import (
    Blob,
    BlobChunk,
    File,
    PathHistory,
    Root,
    SnapshotEntry,
    Version,
)
from undo_core.database.repositories import FileRepository, SkipRepository, VersionRepository
from undo_core.domain import (
    BlobInfo,
    FileHistory,
    FileInfo,
    FilePage,
    PathHistoryInfo,
    SearchHit,
    SkipInfo,
    VersionInfo,
)
from undo_core.utils.errors import NotFoundError
from undo_core.utils.timeutil import to_aware


def root_paths(session: Session) -> dict[int, str]:
    return {r.id: r.absolute_path for r in session.scalars(select(Root))}


def absolute_of(root_path: str, rel: str) -> str:
    return str(Path(root_path) / Path(*rel.split("/"))) if rel else root_path


def file_info(file: File, root_path: str, latest: Version | None) -> FileInfo:
    mtime_ns = None
    if latest is not None and latest.meta:
        mtime_ns = latest.meta.get("mtime_ns")
    if file.last_mtime_ns is not None:
        mtime_ns = file.last_mtime_ns
    last_modified = datetime.fromtimestamp(mtime_ns / 1e9, UTC) if mtime_ns else None
    size = file.last_size
    if size is None and latest is not None:
        size = latest.file_size
    return FileInfo(
        id=file.id,
        root_id=file.root_id,
        root_path=root_path,
        relative_path=file.relative_path,
        absolute_path=absolute_of(root_path, file.relative_path),
        name=file.relative_path.rsplit("/", 1)[-1],
        file_type=file.file_type,
        size=size,
        created_at=to_aware(file.created_at),  # type: ignore[arg-type]
        last_seen_at=to_aware(file.last_seen_at),  # type: ignore[arg-type]
        deleted_at=to_aware(file.deleted_at),
        is_deleted=file.deleted_at is not None,
        latest_version_id=file.latest_version_id,
        version_count=file.version_count,
        last_modified=last_modified,
        latest_operation=latest.operation if latest else None,
        latest_timestamp=to_aware(latest.timestamp) if latest else None,
    )


def version_info(version: Version, root_id: int, root_path: str) -> VersionInfo:
    return VersionInfo(
        id=version.id,
        file_id=version.file_id,
        root_id=root_id,
        relative_path=version.relative_path,
        absolute_path=absolute_of(root_path, version.relative_path),
        operation=version.operation,
        timestamp=to_aware(version.timestamp),  # type: ignore[arg-type]
        file_size=version.file_size,
        blob_hash=version.blob_hash,
        parent_version_id=version.parent_version_id,
        snapshot_id=version.snapshot_id,
        metadata=dict(version.meta or {}),
    )


def blob_info(session: Session, blob: Blob) -> BlobInfo:
    chunk_count = (
        session.scalar(
            select(func.count()).select_from(BlobChunk).where(BlobChunk.blob_hash == blob.hash)
        )
        or 0
    )
    refs = (
        session.scalar(
            select(func.count()).select_from(Version).where(Version.blob_hash == blob.hash)
        )
        or 0
    )
    refs += (
        session.scalar(
            select(func.count())
            .select_from(SnapshotEntry)
            .where(SnapshotEntry.blob_hash == blob.hash)
        )
        or 0
    )
    return BlobInfo(
        hash=blob.hash,
        original_size=blob.original_size,
        compressed_size=blob.compressed_size,
        compression_algorithm=blob.compression_algorithm,
        compression_level=blob.compression_level,
        storage_kind=blob.storage_kind,
        storage_path=blob.storage_path,
        status=blob.status,
        verified_at=to_aware(blob.verified_at),
        created_at=to_aware(blob.created_at),  # type: ignore[arg-type]
        chunk_count=int(chunk_count),
        reference_count=int(refs),
    )


def _latest_map(session: Session, files: list[File]) -> dict[int, Version]:
    ids = [f.latest_version_id for f in files if f.latest_version_id]
    if not ids:
        return {}
    out: dict[int, Version] = {}
    for i in range(0, len(ids), 500):
        for v in session.scalars(select(Version).where(Version.id.in_(ids[i : i + 500]))):
            out[v.id] = v
    return out


def files_to_info(session: Session, files: list[File]) -> list[FileInfo]:
    roots = root_paths(session)
    latest = _latest_map(session, files)
    return [
        file_info(f, roots.get(f.root_id, "?"), latest.get(f.latest_version_id or -1))
        for f in files
    ]


def get_file_info(session: Session, file_id: int) -> FileInfo:
    file = FileRepository(session).get(file_id)
    if file is None:
        raise NotFoundError(f"File {file_id} not found")
    return files_to_info(session, [file])[0]


def list_files(
    session: Session,
    *,
    root_id: int | None,
    query: str | None,
    include_deleted: bool,
    deleted_only: bool,
    prefix: str | None,
    limit: int,
    offset: int,
) -> FilePage:
    rows, total = FileRepository(session).query(
        root_id=root_id,
        text_query=query,
        include_deleted=include_deleted,
        deleted_only=deleted_only,
        prefix=prefix,
        limit=limit,
        offset=offset,
    )
    return FilePage(
        items=files_to_info(session, list(rows)), total=total, limit=limit, offset=offset
    )


def file_history(session: Session, file_id: int, limit: int | None = None) -> FileHistory:
    file = FileRepository(session).get(file_id)
    if file is None:
        raise NotFoundError(f"File {file_id} not found")
    info = files_to_info(session, [file])[0]
    versions = VersionRepository(session).for_file(file_id, limit)
    paths = session.scalars(
        select(PathHistory).where(PathHistory.file_id == file_id).order_by(PathHistory.valid_from)
    ).all()
    return FileHistory(
        file=info,
        versions=[version_info(v, file.root_id, info.root_path) for v in versions],
        paths=[
            PathHistoryInfo(
                relative_path=p.relative_path,
                valid_from=to_aware(p.valid_from),  # type: ignore[arg-type]
                valid_to=to_aware(p.valid_to),
            )
            for p in paths
        ],
    )


def activity(
    session: Session, *, limit: int, root_id: int | None, since: datetime | None
) -> list[VersionInfo]:
    roots = root_paths(session)
    rows = VersionRepository(session).recent(limit=limit, root_id=root_id, since=since)
    return [version_info(v, f.root_id, roots.get(f.root_id, "?")) for v, f in rows]


def search(session: Session, query: str, limit: int) -> list[SearchHit]:
    files_repo = FileRepository(session)
    current, _ = files_repo.query(
        root_id=None, text_query=query, include_deleted=True, prefix=None, limit=limit, offset=0
    )
    hits: dict[int, SearchHit] = {}
    for info in files_to_info(session, list(current)):
        hits[info.id] = SearchHit(file=info, matched_path=info.relative_path, historical=False)
    historical = files_repo.search_history(query, limit)
    hist_files = [f for f, _p in historical if f.id not in hits]
    infos = {i.id: i for i in files_to_info(session, hist_files)}
    for f, p in historical:
        if f.id in hits or f.id not in infos:
            continue
        hits[f.id] = SearchHit(file=infos[f.id], matched_path=p.relative_path, historical=True)
    return list(hits.values())[:limit]


def skipped(session: Session, root_id: int | None, limit: int = 1000) -> list[SkipInfo]:
    return [
        SkipInfo(
            root_id=r.root_id,
            relative_path=r.relative_path,
            reason=r.reason,
            detail=r.detail,
            first_seen=to_aware(r.first_seen),  # type: ignore[arg-type]
            last_seen=to_aware(r.last_seen),  # type: ignore[arg-type]
            count=r.count,
        )
        for r in SkipRepository(session).list(root_id, limit)
    ]


def neighbours(session: Session, version: Version) -> tuple[int | None, int | None]:
    prev_id = session.scalar(
        select(Version.id)
        .where(Version.file_id == version.file_id, Version.id < version.id)
        .order_by(Version.id.desc())
        .limit(1)
    )
    next_id = session.scalar(
        select(Version.id)
        .where(Version.file_id == version.file_id, Version.id > version.id)
        .order_by(Version.id)
        .limit(1)
    )
    return prev_id, next_id


__all__ = ["absolute_of", "activity", "file_history", "list_files", "search"]
