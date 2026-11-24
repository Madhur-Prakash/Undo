"""Content-addressed blob store.

Capture flow (``ingest_file``):

1. Stream the source through BLAKE3 (pass 1) and confirm it did not change.
2. If a healthy blob with that hash exists, reuse it (deduplication).
3. Otherwise stream the source again into a staging file, compressing and
   re-hashing as it goes (pass 2). A mismatch between the two passes, or a
   metadata change, means the file changed during capture -> retry.
4. Fall back to raw storage when compression does not help.
5. fsync, then verify the staged object by decompressing and hashing it.
6. Publish it atomically without ever overwriting an existing object.
7. Record blob metadata in SQLite (short write transaction).
"""

from __future__ import annotations

import contextlib
import os
import tempfile
import threading
from collections import Counter
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from sqlalchemy import delete
from sqlalchemy.exc import IntegrityError as SAIntegrityError

from undo_core.config.defaults import READ_BUFFER
from undo_core.config.settings import Settings
from undo_core.database.engine import Database
from undo_core.database.models import Blob, BlobChunk, BlobStatus, Chunk
from undo_core.database.repositories import BlobRepository, PinRepository
from undo_core.platform.paths import UndoPaths
from undo_core.storage.compression import (
    NONE,
    SUFFIX,
    ZSTD,
    CompressionChoice,
    StreamCompressor,
    choose_compression,
    compress_bytes,
    decompress_bytes,
    iter_decompressed,
)
from undo_core.storage.content_addressing import (
    hash_bytes,
    hash_file,
    is_valid_hash,
    new_hasher,
    object_relpath,
)
from undo_core.utils.atomic import fsync_dir, fsync_file, remove_quietly, rename_no_clobber
from undo_core.utils.errors import FileChangedDuringCapture, NotFoundError, StorageIntegrityError
from undo_core.utils.logging import get_logger
from undo_core.utils.timeutil import utcnow

log = get_logger(__name__)


@dataclass(frozen=True)
class IngestResult:
    hash: str
    size: int
    created: bool
    algorithm: str
    stored_size: int


@dataclass(frozen=True)
class _BlobLocation:
    hash: str
    kind: str
    algorithm: str
    storage_path: str | None
    original_size: int
    chunks: tuple[tuple[str, str, str, int], ...]  # (chunk_hash, algorithm, storage_path, size)


def same_stat(a: os.stat_result, b: os.stat_result) -> bool:
    return a.st_size == b.st_size and a.st_mtime_ns == b.st_mtime_ns


class BlobStore:
    def __init__(self, paths: UndoPaths, db: Database, settings: Callable[[], Settings]) -> None:
        self.paths = paths
        self.db = db
        self._settings = settings
        self._pins: Counter[str] = Counter()
        self._pin_lock = threading.Lock()
        self._chunk_locks: dict[str, threading.Lock] = {}
        self._chunk_locks_guard = threading.Lock()

    # ------------------------------------------------------------------ helpers
    def abs_path(self, rel: str) -> Path:
        return self.paths.data_dir / Path(*rel.split("/"))

    def blob_available(self, digest: str) -> bool:
        with self.db.read() as s:
            blob = s.get(Blob, digest)
            return blob is not None and blob.status == BlobStatus.OK

    def _staging_file(self) -> tuple[BinaryIO, Path]:
        self.paths.staging_dir.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(prefix="obj-", suffix=".part", dir=self.paths.staging_dir)
        return os.fdopen(fd, "wb"), Path(name)

    # ------------------------------------------------------------------ ingest
    def ingest_file(self, path: Path, pre_stat: os.stat_result) -> IngestResult:
        digest, size = hash_file(path)
        if size != pre_stat.st_size or not same_stat(pre_stat, os.stat(path)):
            raise FileChangedDuringCapture(f"{path} changed while hashing")
        # Serialise concurrent captures of identical content so it is stored once.
        with self._chunk_lock("blob:" + digest):
            with self.db.read() as s:
                blob = s.get(Blob, digest)
                if blob is not None and blob.status == BlobStatus.OK:
                    return IngestResult(
                        digest, size, False, blob.compression_algorithm, blob.compressed_size
                    )
            settings = self._settings()
            if settings.chunking.enabled and size >= settings.chunking.min_file_size:
                return self._ingest_chunked(path, digest, size, pre_stat)
            choice = choose_compression(path.name, size, settings.compression)
            return self._ingest_whole(path, digest, size, pre_stat, choice)

    def ingest_bytes(self, data: bytes, name: str = "") -> IngestResult:
        """Store in-memory content (used for small payloads and tests)."""
        digest = hash_bytes(data)
        with self.db.read() as s:
            blob = s.get(Blob, digest)
            if blob is not None and blob.status == BlobStatus.OK:
                return IngestResult(
                    digest, len(data), False, blob.compression_algorithm, blob.compressed_size
                )
        choice = choose_compression(name, len(data), self._settings().compression)
        payload = compress_bytes(data, choice.level or 3) if choice.algorithm == ZSTD else data
        if choice.algorithm == ZSTD and len(payload) >= len(data):
            choice, payload = CompressionChoice(NONE, None), data
        if hash_bytes(decompress_bytes(payload, choice.algorithm)) != digest:
            raise StorageIntegrityError("in-memory compression verification failed")
        handle, tmp = self._staging_file()
        try:
            with handle:
                handle.write(payload)
                fsync_file(handle)
            rel = object_relpath("blobs", digest, SUFFIX[choice.algorithm])
            self._publish(tmp, rel, choice.algorithm, digest)
        finally:
            remove_quietly(tmp)
        self._record_whole_blob(digest, len(data), len(payload), choice, rel)
        return IngestResult(digest, len(data), True, choice.algorithm, len(payload))

    def _copy_to_staging(self, path: Path, choice: CompressionChoice) -> tuple[Path, str, int, int]:
        handle, tmp = self._staging_file()
        hasher = new_hasher()
        size = 0
        try:
            with handle, open(path, "rb") as src:
                comp = StreamCompressor(handle, choice)
                while block := src.read(READ_BUFFER):
                    hasher.update(block)
                    size += len(block)
                    comp.write(block)
                comp.finish()
                fsync_file(handle)
                stored = handle.tell()
        except BaseException:
            remove_quietly(tmp)
            raise
        return tmp, hasher.hexdigest(), size, stored

    def _ingest_whole(
        self,
        path: Path,
        digest: str,
        size: int,
        pre_stat: os.stat_result,
        choice: CompressionChoice,
    ) -> IngestResult:
        tmp, digest2, size2, stored = self._copy_to_staging(path, choice)
        try:
            if digest2 != digest or size2 != size or not same_stat(pre_stat, os.stat(path)):
                raise FileChangedDuringCapture(f"{path} changed while being stored")
            if choice.algorithm == ZSTD and stored >= size:
                remove_quietly(tmp)
                choice = CompressionChoice(NONE, None)
                tmp, digest2, size2, stored = self._copy_to_staging(path, choice)
                if digest2 != digest or size2 != size or not same_stat(pre_stat, os.stat(path)):
                    raise FileChangedDuringCapture(f"{path} changed while being stored")
            self._verify_object(tmp, choice.algorithm, digest)
            rel = object_relpath("blobs", digest, SUFFIX[choice.algorithm])
            self._publish(tmp, rel, choice.algorithm, digest)
        finally:
            remove_quietly(tmp)
        self._record_whole_blob(digest, size, stored, choice, rel)
        return IngestResult(digest, size, True, choice.algorithm, stored)

    def _record_whole_blob(
        self, digest: str, size: int, stored: int, choice: CompressionChoice, rel: str
    ) -> None:
        with self.db.write() as s:
            self._require_object(rel, digest)
            blob = s.get(Blob, digest)
            if blob is None:
                s.add(
                    Blob(
                        hash=digest,
                        original_size=size,
                        compressed_size=stored,
                        compression_algorithm=choice.algorithm,
                        compression_level=choice.level,
                        storage_kind="whole",
                        storage_path=rel,
                        status=BlobStatus.OK,
                        verified_at=utcnow(),
                        created_at=utcnow(),
                    )
                )
            else:
                s.execute(delete(BlobChunk).where(BlobChunk.blob_hash == digest))
                blob.original_size = size
                blob.compressed_size = stored
                blob.compression_algorithm = choice.algorithm
                blob.compression_level = choice.level
                blob.storage_kind = "whole"
                blob.storage_path = rel
                blob.status = BlobStatus.OK
                blob.verified_at = utcnow()

    def _require_object(self, rel: str, digest: str) -> None:
        """Called inside a write transaction: garbage collection removes files only inside
        its own write transaction, so this check cannot race with it."""
        if not self.abs_path(rel).exists():
            raise FileChangedDuringCapture(
                f"stored object for {digest[:12]} was removed concurrently by garbage collection; retrying"
            )

    def _verify_object(self, obj: Path, algorithm: str, digest: str) -> None:
        hasher = new_hasher()
        for block in iter_decompressed(obj, algorithm):
            hasher.update(block)
        if hasher.hexdigest() != digest:
            raise StorageIntegrityError(f"staged object for {digest} failed verification")

    def _publish(self, tmp: Path, rel: str, algorithm: str, digest: str) -> None:
        final = self.abs_path(rel)
        final.parent.mkdir(parents=True, exist_ok=True)
        if rename_no_clobber(tmp, final):
            fsync_dir(final.parent)
            return
        # An object already exists at that address. Never overwrite a good one.
        try:
            self._verify_object(final, algorithm, digest)
            return
        except Exception as exc:  # corrupt or unreadable object
            log.warning("replacing corrupt object", extra={"hash": digest, "error": str(exc)})
        self.paths.quarantine_dir.mkdir(parents=True, exist_ok=True)
        quarantined = self.paths.quarantine_dir / f"{final.name}.{int(utcnow().timestamp())}"
        os.replace(final, quarantined)
        if not rename_no_clobber(tmp, final):
            raise StorageIntegrityError(f"could not publish object {rel}")
        fsync_dir(final.parent)

    # ------------------------------------------------------------------ chunked
    def _chunk_lock(self, digest: str) -> threading.Lock:
        with self._chunk_locks_guard:
            lock = self._chunk_locks.get(digest)
            if lock is None:
                if len(self._chunk_locks) > 4096:
                    self._chunk_locks.clear()
                lock = self._chunk_locks[digest] = threading.Lock()
            return lock

    def _store_chunk(self, digest: str, data: bytes, name: str) -> int:
        with self._chunk_lock(digest):
            with self.db.read() as s:
                existing = s.get(Chunk, digest)
                if existing is not None and existing.status == BlobStatus.OK:
                    return existing.compressed_size
            choice = choose_compression(name, len(data), self._settings().compression)
            payload = compress_bytes(data, choice.level or 3) if choice.algorithm == ZSTD else data
            if choice.algorithm == ZSTD and len(payload) >= len(data):
                choice, payload = CompressionChoice(NONE, None), data
            if hash_bytes(decompress_bytes(payload, choice.algorithm)) != digest:
                raise StorageIntegrityError("chunk compression verification failed")
            handle, tmp = self._staging_file()
            try:
                with handle:
                    handle.write(payload)
                    fsync_file(handle)
                rel = object_relpath("chunks", digest, SUFFIX[choice.algorithm])
                self._publish(tmp, rel, choice.algorithm, digest)
            finally:
                remove_quietly(tmp)
            with self.db.write() as s:
                self._require_object(rel, digest)
                chunk = s.get(Chunk, digest)
                if chunk is None:
                    s.add(
                        Chunk(
                            hash=digest,
                            size=len(data),
                            compressed_size=len(payload),
                            compression_algorithm=choice.algorithm,
                            storage_path=rel,
                            status=BlobStatus.OK,
                            verified_at=utcnow(),
                            created_at=utcnow(),
                        )
                    )
                else:
                    chunk.compressed_size = len(payload)
                    chunk.compression_algorithm = choice.algorithm
                    chunk.storage_path = rel
                    chunk.status = BlobStatus.OK
                    chunk.verified_at = utcnow()
            return len(payload)

    def _ingest_chunked(
        self, path: Path, digest: str, size: int, pre_stat: os.stat_result
    ) -> IngestResult:
        chunk_size = self._settings().chunking.chunk_size
        whole = new_hasher()
        manifest: list[tuple[int, str, int, int]] = []
        stored = 0
        offset = 0
        with open(path, "rb") as fh:
            seq = 0
            while data := fh.read(chunk_size):
                whole.update(data)
                chunk_hash = hash_bytes(data)
                stored += self._store_chunk(chunk_hash, data, path.name)
                manifest.append((seq, chunk_hash, offset, len(data)))
                offset += len(data)
                seq += 1
        if whole.hexdigest() != digest or offset != size or not same_stat(pre_stat, os.stat(path)):
            raise FileChangedDuringCapture(f"{path} changed while being chunked")
        try:
            self._record_chunked_blob(digest, size, stored, manifest)
        except SAIntegrityError as exc:  # a chunk was garbage-collected meanwhile
            raise FileChangedDuringCapture(
                f"chunk removed concurrently; retrying ({exc.orig})"
            ) from exc
        return IngestResult(digest, size, True, "chunked", stored)

    def _record_chunked_blob(
        self, digest: str, size: int, stored: int, manifest: list[tuple[int, str, int, int]]
    ) -> None:
        with self.db.write() as s:
            for _seq, chunk_hash, _off, _len in manifest:
                chunk = s.get(Chunk, chunk_hash)
                if chunk is None or not self.abs_path(chunk.storage_path).exists():
                    raise FileChangedDuringCapture(
                        "chunk removed concurrently by garbage collection; retrying"
                    )
            blob = s.get(Blob, digest)
            s.execute(delete(BlobChunk).where(BlobChunk.blob_hash == digest))
            if blob is None:
                blob = Blob(
                    hash=digest,
                    original_size=size,
                    compressed_size=stored,
                    compression_algorithm="chunked",
                    compression_level=self._settings().compression.level,
                    storage_kind="chunked",
                    storage_path=None,
                    status=BlobStatus.OK,
                    verified_at=utcnow(),
                    created_at=utcnow(),
                )
                s.add(blob)
            else:
                blob.storage_kind = "chunked"
                blob.storage_path = None
                blob.compression_algorithm = "chunked"
                blob.compressed_size = stored
                blob.status = BlobStatus.OK
                blob.verified_at = utcnow()
            s.flush()
            for seq, chunk_hash, off, length in manifest:
                s.add(
                    BlobChunk(
                        blob_hash=digest, seq=seq, chunk_hash=chunk_hash, offset=off, size=length
                    )
                )

    # ------------------------------------------------------------------ reading
    def _locate(self, digest: str) -> _BlobLocation:
        with self.db.read() as s:
            blob = s.get(Blob, digest)
            if blob is None:
                raise NotFoundError(f"Blob {digest} is not in the store")
            chunks: tuple[tuple[str, str, str, int], ...] = ()
            if blob.storage_kind == "chunked":
                chunks = tuple(
                    (c.hash, c.compression_algorithm, c.storage_path, c.size)
                    for _bc, c in BlobRepository(s).chunks_for(digest)
                )
            return _BlobLocation(
                digest,
                blob.storage_kind,
                blob.compression_algorithm,
                blob.storage_path,
                blob.original_size,
                chunks,
            )

    def iter_content(self, digest: str) -> Iterator[bytes]:
        """Yield original content. Integrity is checked by ``export_to``/``read_bytes``."""
        loc = self._locate(digest)
        try:
            if loc.kind == "whole":
                assert loc.storage_path is not None
                yield from iter_decompressed(self.abs_path(loc.storage_path), loc.algorithm)
                return
            for chunk_hash, algorithm, rel, _size in loc.chunks:
                data = decompress_bytes(self.abs_path(rel).read_bytes(), algorithm)
                if hash_bytes(data) != chunk_hash:
                    raise StorageIntegrityError(f"chunk {chunk_hash} of blob {digest} is corrupt")
                yield data
        except FileNotFoundError as exc:
            self._mark(digest, BlobStatus.MISSING)
            raise StorageIntegrityError(f"Stored object for blob {digest} is missing") from exc

    def export_to(self, digest: str, dst: BinaryIO) -> int:
        """Write verified original content to ``dst``. Raises on any mismatch."""
        hasher = new_hasher()
        size = 0
        try:
            for block in self.iter_content(digest):
                hasher.update(block)
                size += len(block)
                dst.write(block)
        except StorageIntegrityError:
            raise
        except Exception as exc:  # zstd errors etc.
            self._mark(digest, BlobStatus.CORRUPT)
            raise StorageIntegrityError(f"Blob {digest} could not be decoded: {exc}") from exc
        if hasher.hexdigest() != digest:
            self._mark(digest, BlobStatus.CORRUPT)
            raise StorageIntegrityError(f"Blob {digest} failed hash verification")
        return size

    def read_bytes(self, digest: str, max_size: int | None = None) -> bytes:
        loc = self._locate(digest)
        if max_size is not None and loc.original_size > max_size:
            raise StorageIntegrityError(f"Blob {digest} is larger than {max_size} bytes")
        import io

        buf = io.BytesIO()
        self.export_to(digest, buf)
        return buf.getvalue()

    def verify_blob(self, digest: str) -> str | None:
        """Return None when the blob decodes to its hash, else a status string."""
        try:
            hasher = new_hasher()
            for block in self.iter_content(digest):
                hasher.update(block)
        except StorageIntegrityError as exc:
            return BlobStatus.MISSING if "missing" in str(exc) else BlobStatus.CORRUPT
        except NotFoundError:
            return BlobStatus.MISSING
        except Exception:
            return BlobStatus.CORRUPT
        return None if hasher.hexdigest() == digest else BlobStatus.CORRUPT

    def _mark(self, digest: str, status: BlobStatus) -> None:
        try:
            with self.db.write() as s:
                BlobRepository(s).mark_status(digest, status)
        except Exception as exc:
            log.error("could not mark blob status", extra={"hash": digest, "error": str(exc)})

    # ------------------------------------------------------------------ pins
    @contextlib.contextmanager
    def pin(self, digests: list[str] | str, owner: str) -> Iterator[None]:
        """Protect blobs from garbage collection while in use (in- and cross-process)."""
        items = [digests] if isinstance(digests, str) else list(digests)
        with self._pin_lock:
            self._pins.update(items)
        pin_ids: list[int] = []
        try:
            with self.db.write() as s:
                repo = PinRepository(s)
                pin_ids = [repo.add(d, owner) for d in items]
            yield
        finally:
            with self._pin_lock:
                self._pins.subtract(items)
                self._pins += Counter()  # drop zero counts
            if pin_ids:
                try:
                    with self.db.write() as s:
                        repo = PinRepository(s)
                        for pin_id in pin_ids:
                            repo.remove(pin_id)
                except Exception as exc:
                    log.warning("failed to release blob pins", extra={"error": str(exc)})

    def pinned_in_process(self) -> set[str]:
        with self._pin_lock:
            return {k for k, v in self._pins.items() if v > 0}

    # ------------------------------------------------------------------ inventory
    def iter_object_files(self) -> Iterator[tuple[str, str, Path]]:
        """Yield (kind, hash, path) for every object file on disk."""
        for kind, base in (("blobs", self.paths.blobs_dir), ("chunks", self.paths.chunks_dir)):
            if not base.exists():
                continue
            for shard in base.iterdir():
                if not shard.is_dir():
                    continue
                for obj in shard.iterdir():
                    digest = obj.name.split(".", 1)[0]
                    if is_valid_hash(digest):
                        yield kind, digest, obj

    def disk_usage(self) -> int:
        total = 0
        for _kind, _digest, path in self.iter_object_files():
            with contextlib.suppress(OSError):
                total += path.stat().st_size
        return total
