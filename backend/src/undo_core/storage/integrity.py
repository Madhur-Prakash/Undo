"""Storage verification and repair."""

from __future__ import annotations

import os
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import select

from undo_core.database.engine import Database
from undo_core.database.models import Blob, BlobStatus, Chunk, File, Root, Version
from undo_core.database.repositories import BlobRepository, MetaRepository
from undo_core.platform.paths import safe_join
from undo_core.storage.blob_store import BlobStore
from undo_core.storage.compression import iter_decompressed
from undo_core.storage.content_addressing import hash_file, new_hasher
from undo_core.utils.logging import get_logger
from undo_core.utils.timeutil import utcnow

log = get_logger(__name__)


@dataclass
class VerifyOutcome:
    checked_blobs: int = 0
    checked_chunks: int = 0
    ok: int = 0
    missing: list[str] = field(default_factory=list)
    corrupt: list[str] = field(default_factory=list)
    repaired: list[str] = field(default_factory=list)
    orphan_files: list[str] = field(default_factory=list)
    database_problems: list[str] = field(default_factory=list)
    full: bool = True
    duration_seconds: float = 0.0

    @property
    def healthy(self) -> bool:
        unrepaired = (set(self.missing) | set(self.corrupt)) - set(self.repaired)
        return not unrepaired and not self.database_problems


def _verify_chunk(store: BlobStore, chunk: Chunk) -> str | None:
    path = store.abs_path(chunk.storage_path)
    if not path.exists():
        return BlobStatus.MISSING
    try:
        hasher = new_hasher()
        for block in iter_decompressed(path, chunk.compression_algorithm):
            hasher.update(block)
    except Exception:
        return BlobStatus.CORRUPT
    return None if hasher.hexdigest() == chunk.hash else BlobStatus.CORRUPT


def try_repair_blob(db: Database, store: BlobStore, digest: str) -> bool:
    """Re-store a damaged blob from a live file whose current content has that hash."""
    with db.read() as s:
        candidates = s.execute(
            select(Root.absolute_path, File.relative_path)
            .join(File, File.root_id == Root.id)
            .join(Version, Version.id == File.latest_version_id)
            .where(Version.blob_hash == digest, File.deleted_at.is_(None))
        ).all()
    for root_path, rel in candidates:
        try:
            path = safe_join(Path(root_path), rel)
            st = os.stat(path)
            actual, _ = hash_file(path)
        except OSError:
            continue
        if actual != digest:
            continue
        try:
            with db.write() as s:
                BlobRepository(s).mark_status(digest, BlobStatus.MISSING)
            store.ingest_file(path, st)
            if store.verify_blob(digest) is None:
                log.info("repaired blob from live file", extra={"hash": digest, "path": str(path)})
                return True
        except Exception as exc:
            log.warning("blob repair failed", extra={"hash": digest, "error": str(exc)})
    return False


def verify_storage(
    db: Database,
    store: BlobStore,
    *,
    full: bool = True,
    repair: bool = True,
    progress: Callable[[int, int], None] | None = None,
) -> VerifyOutcome:
    """Check every blob/chunk. ``full`` decompresses and re-hashes, otherwise only existence."""
    started = time.monotonic()
    outcome = VerifyOutcome(full=full)
    outcome.database_problems = db.quick_check()
    with db.read() as s:
        blobs = [(b.hash, b.storage_kind, b.storage_path) for b in s.scalars(select(Blob))]
        chunks = list(s.scalars(select(Chunk)))
    total = len(blobs) + len(chunks)
    done = 0
    bad_chunks: set[str] = set()
    for chunk in chunks:
        outcome.checked_chunks += 1
        if full:
            status = _verify_chunk(store, chunk)
        else:
            status = None if store.abs_path(chunk.storage_path).exists() else BlobStatus.MISSING
        with db.write() as s:
            row = s.get(Chunk, chunk.hash)
            if row is not None:
                row.status = status or BlobStatus.OK
                row.verified_at = utcnow()
        if status:
            bad_chunks.add(chunk.hash)
        done += 1
        if progress:
            progress(done, total)
    for digest, kind, rel in blobs:
        outcome.checked_blobs += 1
        if full:
            status = store.verify_blob(digest)
        elif kind == "whole":
            status = None if rel and store.abs_path(rel).exists() else BlobStatus.MISSING
        else:
            with db.read() as s:
                hashes = [c.hash for _bc, c in BlobRepository(s).chunks_for(digest)]
            status = BlobStatus.MISSING if bad_chunks.intersection(hashes) else None
        with db.write() as s:
            BlobRepository(s).mark_status(digest, BlobStatus(status) if status else BlobStatus.OK)
        if status == BlobStatus.MISSING:
            outcome.missing.append(digest)
        elif status == BlobStatus.CORRUPT:
            outcome.corrupt.append(digest)
        else:
            outcome.ok += 1
        if status and repair and try_repair_blob(db, store, digest):
            outcome.repaired.append(digest)
        done += 1
        if progress:
            progress(done, total)
    known_blobs = {b[0] for b in blobs}
    known_chunks = {c.hash for c in chunks}
    for kind, digest, path in store.iter_object_files():
        known = known_blobs if kind == "blobs" else known_chunks
        if digest not in known:
            outcome.orphan_files.append(str(path))
    outcome.duration_seconds = round(time.monotonic() - started, 3)
    with db.write() as s:
        meta = MetaRepository(s)
        meta.set("last_verify_at", utcnow().isoformat())
        meta.set("last_verify_ok", outcome.healthy)
        meta.set("last_verify_full", full)
    return outcome
