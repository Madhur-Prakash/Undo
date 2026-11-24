"""Zstandard compression policy and streaming codecs."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

import zstandard

from undo_core.config.defaults import READ_BUFFER
from undo_core.config.settings import CompressionSettings

ZSTD = "zstd"
NONE = "none"
SUFFIX = {ZSTD: ".zst", NONE: ".raw"}


@dataclass(frozen=True)
class CompressionChoice:
    algorithm: str
    level: int | None


def choose_compression(name: str, size: int, settings: CompressionSettings) -> CompressionChoice:
    """Decide how to store content before reading it.

    Skips compression when disabled, for tiny files and for formats that are
    already compressed. The caller additionally falls back to raw storage when
    the compressed output turns out not to be smaller.
    """
    if not settings.enabled or size < settings.min_size:
        return CompressionChoice(NONE, None)
    suffix = Path(name).suffix.lower()
    if suffix and suffix in settings.skip_extensions:
        return CompressionChoice(NONE, None)
    return CompressionChoice(ZSTD, settings.level)


class StreamCompressor:
    """Writes compressed (or raw) data to an open binary handle."""

    def __init__(self, dst: BinaryIO, choice: CompressionChoice) -> None:
        self.dst = dst
        self.choice = choice
        self._writer: zstandard.ZstdCompressionWriter | None = None
        if choice.algorithm == ZSTD:
            cctx = zstandard.ZstdCompressor(level=choice.level or 3, write_checksum=True)
            self._writer = cctx.stream_writer(dst, closefd=False)

    def write(self, block: bytes) -> None:
        if self._writer is not None:
            self._writer.write(block)
        else:
            self.dst.write(block)

    def finish(self) -> None:
        if self._writer is not None:
            self._writer.close()  # ends the frame; dst stays open (closefd=False)
            self._writer = None
        self.dst.flush()


def compress_bytes(data: bytes, level: int) -> bytes:
    return zstandard.ZstdCompressor(level=level, write_checksum=True).compress(data)


def decompress_bytes(data: bytes, algorithm: str) -> bytes:
    if algorithm == NONE:
        return data
    if algorithm == ZSTD:
        dctx = zstandard.ZstdDecompressor()
        with dctx.stream_reader(data, read_across_frames=True) as reader:
            return reader.read()
    raise ValueError(f"Unknown compression algorithm {algorithm!r}")


def iter_decompressed(path: Path, algorithm: str, bufsize: int = READ_BUFFER) -> Iterator[bytes]:
    """Stream original content out of a stored object without loading it whole."""
    with open(path, "rb") as fh:
        if algorithm == NONE:
            while block := fh.read(bufsize):
                yield block
            return
        if algorithm != ZSTD:
            raise ValueError(f"Unknown compression algorithm {algorithm!r}")
        dctx = zstandard.ZstdDecompressor()
        with dctx.stream_reader(fh, read_across_frames=True, closefd=False) as reader:
            while block := reader.read(bufsize):
                yield block
