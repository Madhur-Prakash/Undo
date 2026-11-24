from __future__ import annotations

import io
import os
from pathlib import Path

import pytest
from sqlalchemy import select
from undo_core.context import UndoContext
from undo_core.database.models import Blob, BlobStatus, Chunk
from undo_core.storage.content_addressing import hash_bytes
from undo_core.utils.errors import FileChangedDuringCapture, StorageIntegrityError


def _ingest(ctx: UndoContext, path: Path):  # type: ignore[no-untyped-def]
    return ctx.store.ingest_file(path, os.stat(path))


def test_ingest_stores_compressed_and_verifies(ctx: UndoContext, tmp_path: Path) -> None:
    p = tmp_path / "doc.txt"
    p.write_bytes(b"lorem ipsum " * 10_000)
    result = _ingest(ctx, p)
    assert result.created and result.algorithm == "zstd"
    assert result.stored_size < result.size
    buf = io.BytesIO()
    assert ctx.store.export_to(result.hash, buf) == p.stat().st_size
    assert buf.getvalue() == p.read_bytes()
    with ctx.db.read() as s:
        blob = s.get(Blob, result.hash)
        assert blob is not None and blob.status == BlobStatus.OK
        assert blob.storage_path == f"blobs/{result.hash[:2]}/{result.hash}.zst"
    assert list(ctx.paths.staging_dir.iterdir()) == []


def test_identical_content_is_deduplicated(ctx: UndoContext, tmp_path: Path) -> None:
    a, b = tmp_path / "a.txt", tmp_path / "b.txt"
    a.write_bytes(b"same content" * 100)
    b.write_bytes(b"same content" * 100)
    first, second = _ingest(ctx, a), _ingest(ctx, b)
    assert first.hash == second.hash
    assert first.created and not second.created
    with ctx.db.read() as s:
        assert len(list(s.scalars(select(Blob)))) == 1
    assert len(list(ctx.store.iter_object_files())) == 1


def test_incompressible_data_stored_raw(ctx: UndoContext, tmp_path: Path) -> None:
    p = tmp_path / "random.bin"
    p.write_bytes(os.urandom(200_000))
    result = _ingest(ctx, p)
    assert result.algorithm == "none"
    assert result.stored_size == 200_000
    assert ctx.store.verify_blob(result.hash) is None


def test_corruption_is_detected_not_assumed(ctx: UndoContext, tmp_path: Path) -> None:
    p = tmp_path / "x.txt"
    p.write_bytes(b"important data " * 2000)
    result = _ingest(ctx, p)
    with ctx.db.read() as s:
        rel = s.get(Blob, result.hash).storage_path  # type: ignore[union-attr]
    obj = ctx.store.abs_path(rel)
    raw = bytearray(obj.read_bytes())
    raw[len(raw) // 2] ^= 0xFF
    obj.write_bytes(bytes(raw))
    with pytest.raises(StorageIntegrityError):
        ctx.store.export_to(result.hash, io.BytesIO())
    assert ctx.store.verify_blob(result.hash) == BlobStatus.CORRUPT
    with ctx.db.read() as s:
        assert s.get(Blob, result.hash).status == BlobStatus.CORRUPT  # type: ignore[union-attr]


def test_raw_blob_silent_corruption_detected(ctx: UndoContext, tmp_path: Path) -> None:
    p = tmp_path / "r.bin"
    p.write_bytes(os.urandom(5000))
    result = _ingest(ctx, p)
    with ctx.db.read() as s:
        obj = ctx.store.abs_path(s.get(Blob, result.hash).storage_path)  # type: ignore[union-attr]
    data = bytearray(obj.read_bytes())
    data[0] ^= 1
    obj.write_bytes(bytes(data))
    assert ctx.store.verify_blob(result.hash) == BlobStatus.CORRUPT


def test_reingest_repairs_damaged_blob(ctx: UndoContext, tmp_path: Path) -> None:
    p = tmp_path / "x.txt"
    p.write_bytes(b"repair me " * 500)
    result = _ingest(ctx, p)
    with ctx.db.read() as s:
        obj = ctx.store.abs_path(s.get(Blob, result.hash).storage_path)  # type: ignore[union-attr]
    obj.unlink()
    assert ctx.store.verify_blob(result.hash) == BlobStatus.MISSING
    again = _ingest(ctx, p)
    assert again.created
    assert ctx.store.verify_blob(result.hash) is None


def test_change_during_capture_detected(ctx: UndoContext, tmp_path: Path) -> None:
    p = tmp_path / "busy.txt"
    p.write_bytes(b"v1")
    stale = os.stat(p)
    p.write_bytes(b"version two")
    with pytest.raises(FileChangedDuringCapture):
        ctx.store.ingest_file(p, stale)
    assert list(ctx.paths.staging_dir.iterdir()) == []


def test_chunked_storage_dedups_chunks(ctx: UndoContext, tmp_path: Path) -> None:
    ctx.settings_store.update(
        {"chunking": {"enabled": True, "chunk_size": 65536, "min_file_size": 0}}
    )
    shared = os.urandom(65536 * 3)
    a, b = tmp_path / "a.bin", tmp_path / "b.bin"
    a.write_bytes(shared + b"tail-a")
    b.write_bytes(shared + b"tail-b-different")
    ra, rb = _ingest(ctx, a), _ingest(ctx, b)
    assert ra.algorithm == "chunked" and rb.algorithm == "chunked"
    with ctx.db.read() as s:
        chunks = list(s.scalars(select(Chunk)))
    assert len(chunks) == 5  # 3 shared + 2 distinct tails
    for path, res in ((a, ra), (b, rb)):
        buf = io.BytesIO()
        ctx.store.export_to(res.hash, buf)
        assert buf.getvalue() == path.read_bytes()
        assert hash_bytes(buf.getvalue()) == res.hash


def test_publish_never_overwrites_existing_good_object(ctx: UndoContext, tmp_path: Path) -> None:
    p = tmp_path / "x.txt"
    p.write_bytes(b"stable" * 1000)
    result = _ingest(ctx, p)
    with ctx.db.read() as s:
        obj = ctx.store.abs_path(s.get(Blob, result.hash).storage_path)  # type: ignore[union-attr]
    before = obj.stat().st_mtime_ns
    staged = ctx.paths.staging_dir / "dup.part"
    staged.write_bytes(obj.read_bytes())
    ctx.store._publish(staged, obj.relative_to(ctx.paths.data_dir).as_posix(), "zstd", result.hash)
    assert obj.stat().st_mtime_ns == before
