from __future__ import annotations

import io
import os
from pathlib import Path

import pytest
from undo_core.config.settings import CompressionSettings
from undo_core.storage.compression import (
    NONE,
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
    object_relpath,
)
from undo_core.utils.errors import InvalidInputError


def test_blake3_known_vector() -> None:
    # Official BLAKE3 test vector for the empty input.
    assert hash_bytes(b"") == "af1349b9f5f9a1a6a0404dea36dcc9499bcb25c9adc112b7cc9a93cae41f3262"


def test_hash_file_streams_and_matches_bytes(tmp_path: Path) -> None:
    data = os.urandom(3 * 1024 * 1024 + 17)
    p = tmp_path / "f.bin"
    p.write_bytes(data)
    digest, size = hash_file(p, bufsize=64 * 1024)
    assert size == len(data)
    assert digest == hash_bytes(data)
    assert is_valid_hash(digest)


def test_object_path_is_sharded() -> None:
    h = "ab" + "0" * 62
    assert object_relpath("blobs", h, ".zst") == f"blobs/ab/{h}.zst"
    with pytest.raises(InvalidInputError):
        object_relpath("blobs", "../../etc/passwd", ".zst")


def test_compression_roundtrip_levels() -> None:
    data = b"hello undo " * 5000
    for level in (1, 3, 19):
        packed = compress_bytes(data, level)
        assert len(packed) < len(data)
        assert decompress_bytes(packed, ZSTD) == data
    assert decompress_bytes(data, NONE) == data


def test_stream_compressor_and_decompressor(tmp_path: Path) -> None:
    data = os.urandom(1000) * 3000  # compressible, multi-MB
    out = tmp_path / "x.zst"
    with open(out, "wb") as fh:
        comp = StreamCompressor(fh, CompressionChoice(ZSTD, 3))
        for i in range(0, len(data), 65536):
            comp.write(data[i : i + 65536])
        comp.finish()
    assert out.stat().st_size < len(data)
    restored = io.BytesIO()
    for block in iter_decompressed(out, ZSTD, bufsize=4096):
        restored.write(block)
    assert restored.getvalue() == data


def test_choose_compression_policy() -> None:
    settings = CompressionSettings()
    assert choose_compression("a.txt", 10_000, settings).algorithm == ZSTD
    assert choose_compression("photo.JPG", 10_000, settings).algorithm == NONE  # already compressed
    assert choose_compression("tiny.txt", 10, settings).algorithm == NONE  # below min_size
    disabled = CompressionSettings(enabled=False)
    assert choose_compression("a.txt", 10_000, disabled).algorithm == NONE
    assert choose_compression("a.txt", 10_000, CompressionSettings(level=19)).level == 19
