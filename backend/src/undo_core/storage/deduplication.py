"""Deduplication accounting.

Whole-file deduplication happens in :class:`BlobStore` (identical content ->
same BLAKE3 address -> stored once). Optional fixed-size chunking
(``chunking.enabled``) additionally deduplicates identical chunks across
different files; see ``BlobStore._ingest_chunked``. This module computes the
numbers that explain how much each mechanism saves.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from undo_core.database.models import Blob, BlobChunk, Chunk, Version


@dataclass(frozen=True)
class StorageAccounting:
    logical_bytes: int  # sum of sizes of every captured version (what naive copies would cost)
    unique_bytes: (
        int  # sum of distinct contents (after whole-file + chunk dedup, before compression)
    )
    stored_bytes: int  # bytes actually occupied by stored objects
    blob_count: int
    chunk_count: int
    chunked_blob_count: int
    by_algorithm: dict[str, int]

    @property
    def dedup_savings(self) -> int:
        return max(self.logical_bytes - self.unique_bytes, 0)

    @property
    def compression_savings(self) -> int:
        return max(self.unique_bytes - self.stored_bytes, 0)

    @property
    def total_savings(self) -> int:
        return max(self.logical_bytes - self.stored_bytes, 0)


def compute_accounting(session: Session) -> StorageAccounting:
    logical = (
        session.scalar(
            select(func.coalesce(func.sum(Version.file_size), 0)).where(
                Version.blob_hash.is_not(None)
            )
        )
        or 0
    )
    whole_unique = (
        session.scalar(
            select(func.coalesce(func.sum(Blob.original_size), 0)).where(
                Blob.storage_kind == "whole"
            )
        )
        or 0
    )
    whole_stored = (
        session.scalar(
            select(func.coalesce(func.sum(Blob.compressed_size), 0)).where(
                Blob.storage_kind == "whole"
            )
        )
        or 0
    )
    chunk_unique = session.scalar(select(func.coalesce(func.sum(Chunk.size), 0))) or 0
    chunk_stored = session.scalar(select(func.coalesce(func.sum(Chunk.compressed_size), 0))) or 0
    blob_count = session.scalar(select(func.count()).select_from(Blob)) or 0
    chunk_count = session.scalar(select(func.count()).select_from(Chunk)) or 0
    chunked = (
        session.scalar(select(func.count()).select_from(Blob).where(Blob.storage_kind == "chunked"))
        or 0
    )
    by_alg = {
        str(alg): int(cnt)
        for alg, cnt in session.execute(
            select(Blob.compression_algorithm, func.count()).group_by(Blob.compression_algorithm)
        ).all()
    }
    return StorageAccounting(
        logical_bytes=int(logical),
        unique_bytes=int(whole_unique + chunk_unique),
        stored_bytes=int(whole_stored + chunk_stored),
        blob_count=int(blob_count),
        chunk_count=int(chunk_count),
        chunked_blob_count=int(chunked),
        by_algorithm=by_alg,
    )


def chunk_reference_counts(session: Session) -> dict[str, int]:
    rows = session.execute(
        select(BlobChunk.chunk_hash, func.count()).group_by(BlobChunk.chunk_hash)
    ).all()
    return {r[0]: int(r[1]) for r in rows}
