"""Garbage collection of unreferenced blobs and chunks.

A blob is only deleted when *all* of the following hold, re-checked inside a
single ``BEGIN IMMEDIATE`` transaction:

* no version references it,
* no snapshot entry references it,
* no blob pin (active restore / capture, any process) references it,
* it is not pinned in this process,
* it is older than the grace period (protects captures in other processes
  that stored the blob but have not yet committed the version).

Foreign keys (``ON DELETE RESTRICT``) are a second line of defence: SQLite
refuses to delete a blob row that a version or snapshot still references.
Object files are moved to ``trash/`` *inside* that write transaction and only
unlinked after it commits (moved back if it rolls back). Captures check that
their object file exists inside their own write transaction before recording
it, so a capture can never record a blob whose file GC is removing. A crash
can only leave an orphan or trash file (cleaned up later), never a dangling
reference.
"""

from __future__ import annotations

import contextlib
import os
import time
import uuid
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path

from sqlalchemy import delete, select

from undo_core.database.engine import Database
from undo_core.database.models import Blob, BlobChunk, BlobPin, Chunk, SnapshotEntry, Version
from undo_core.database.repositories import MetaRepository, PinRepository
from undo_core.storage.blob_store import BlobStore
from undo_core.utils.logging import get_logger
from undo_core.utils.timeutil import utcnow

log = get_logger(__name__)
STALE_PIN_SECONDS = 6 * 3600


@dataclass
class GCOutcome:
    dry_run: bool
    candidate_blobs: int = 0
    candidate_chunks: int = 0
    reclaimable_bytes: int = 0
    deleted_blobs: int = 0
    deleted_chunks: int = 0
    reclaimed_bytes: int = 0
    protected_by_grace: int = 0
    orphan_files: int = 0
    orphan_bytes: int = 0
    staging_files: int = 0
    errors: list[str] = field(default_factory=list)
    duration_seconds: float = 0.0


def _referenced(session: object) -> set[str]:
    from sqlalchemy.orm import Session

    assert isinstance(session, Session)
    refs = set(session.scalars(select(Version.blob_hash).where(Version.blob_hash.is_not(None))))
    refs |= set(session.scalars(select(SnapshotEntry.blob_hash)))
    refs |= set(session.scalars(select(BlobPin.blob_hash)))
    return {r for r in refs if r}


def collect_garbage(
    db: Database, store: BlobStore, *, dry_run: bool = True, grace_seconds: int = 3600
) -> GCOutcome:
    started = time.monotonic()
    out = GCOutcome(dry_run=dry_run)
    cutoff = utcnow() - timedelta(seconds=grace_seconds)
    pinned_local = store.pinned_in_process()

    if not dry_run:
        with db.write() as s:
            PinRepository(s).purge_older_than(utcnow() - timedelta(seconds=STALE_PIN_SECONDS))

    def plan(session: object) -> tuple[list[Blob], list[Chunk]]:
        from sqlalchemy.orm import Session

        assert isinstance(session, Session)
        refs = _referenced(session) | pinned_local
        blobs = [b for b in session.scalars(select(Blob)) if b.hash not in refs]
        young = [b for b in blobs if b.created_at > cutoff]
        out.protected_by_grace = len(young)
        doomed = [b for b in blobs if b.created_at <= cutoff]
        doomed_hashes = {b.hash for b in doomed}
        live_chunk_refs = {
            row.chunk_hash
            for row in session.scalars(select(BlobChunk))
            if row.blob_hash not in doomed_hashes
        }
        chunks = [
            c
            for c in session.scalars(select(Chunk))
            if c.hash not in live_chunk_refs and c.created_at <= cutoff
        ]
        return doomed, chunks

    trash = store.paths.data_dir / "trash"
    trashed: list[tuple[Path, Path, int]] = []  # (original, trash location, size)

    def to_trash(path: Path) -> None:
        """Move an object aside *inside* the GC write transaction (see module docstring)."""
        try:
            size = path.stat().st_size
        except FileNotFoundError:
            return
        trash.mkdir(parents=True, exist_ok=True)
        target = trash / f"{path.name}.{uuid.uuid4().hex}"
        os.replace(path, target)
        trashed.append((path, target, size))

    if dry_run:
        with db.read() as s:
            blobs, chunks = plan(s)
            out.candidate_blobs = len(blobs)
            out.candidate_chunks = len(chunks)
            out.reclaimable_bytes = sum(
                b.compressed_size for b in blobs if b.storage_kind == "whole"
            )
            out.reclaimable_bytes += sum(c.compressed_size for c in chunks)
    else:
        try:
            with db.write() as s:
                blobs, chunks = plan(s)
                out.candidate_blobs = len(blobs)
                out.candidate_chunks = len(chunks)
                for blob in blobs:
                    s.execute(delete(BlobChunk).where(BlobChunk.blob_hash == blob.hash))
                    s.delete(blob)
                    if blob.storage_kind == "whole" and blob.storage_path:
                        out.reclaimable_bytes += blob.compressed_size
                    out.deleted_blobs += 1
                s.flush()
                for chunk in chunks:
                    s.delete(chunk)
                    out.reclaimable_bytes += chunk.compressed_size
                    out.deleted_chunks += 1
                s.flush()  # raises (FK RESTRICT) before any file is touched if still referenced
                for blob in blobs:
                    if blob.storage_kind == "whole" and blob.storage_path:
                        to_trash(store.abs_path(blob.storage_path))
                for chunk in chunks:
                    to_trash(store.abs_path(chunk.storage_path))
                MetaRepository(s).set("last_gc_at", utcnow().isoformat())
        except BaseException:
            for original, target, _size in trashed:  # transaction rolled back: put files back
                with contextlib.suppress(OSError):
                    os.replace(target, original)
            raise
        for _original, target, size in trashed:
            try:
                target.unlink()
                out.reclaimed_bytes += size
            except OSError as exc:
                out.errors.append(f"{target.name}: {exc}")

    # Orphan object files (on disk, unknown to the database) older than the grace period.
    cutoff_ts = time.time() - grace_seconds
    candidates: list[tuple[str, str, Path, int]] = []
    for kind, digest, path in store.iter_object_files():
        try:
            st = path.stat()
        except OSError:
            continue
        if st.st_mtime <= cutoff_ts:
            candidates.append((kind, digest, path, st.st_size))
    if candidates:
        with db.write() if not dry_run else db.read() as s:
            known_blobs = set(s.scalars(select(Blob.hash)))
            known_chunks = set(s.scalars(select(Chunk.hash)))
            for kind, digest, path, size in candidates:
                if digest in (known_blobs if kind == "blobs" else known_chunks):
                    continue
                out.orphan_files += 1
                out.orphan_bytes += size
                if not dry_run:
                    with contextlib.suppress(OSError):
                        path.unlink()
                        out.reclaimed_bytes += size

    staging = store.paths.staging_dir
    if staging.exists():
        for item in staging.iterdir():
            try:
                if item.stat().st_mtime <= cutoff_ts:
                    out.staging_files += 1
                    if not dry_run:
                        os.unlink(item)
            except OSError:
                continue
    out.duration_seconds = round(time.monotonic() - started, 3)
    log.info(
        "garbage collection finished",
        extra={
            "dry_run": dry_run,
            "deleted_blobs": out.deleted_blobs,
            "reclaimed": out.reclaimed_bytes,
        },
    )
    return out
