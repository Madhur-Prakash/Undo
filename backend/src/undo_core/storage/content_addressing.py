"""BLAKE3-256 content addressing and object path layout."""

from __future__ import annotations

import re
from collections.abc import Iterable
from pathlib import Path

from blake3 import blake3

from undo_core.config.defaults import READ_BUFFER
from undo_core.utils.errors import InvalidInputError

HASH_RE = re.compile(r"^[0-9a-f]{64}$")


def new_hasher() -> blake3:
    return blake3()


def hash_bytes(data: bytes) -> str:
    return blake3(data).hexdigest()


def hash_iter(blocks: Iterable[bytes]) -> tuple[str, int]:
    hasher = blake3()
    size = 0
    for block in blocks:
        hasher.update(block)
        size += len(block)
    return hasher.hexdigest(), size


def iter_file(path: Path, bufsize: int = READ_BUFFER) -> Iterable[bytes]:
    with open(path, "rb") as handle:
        while True:
            block = handle.read(bufsize)
            if not block:
                return
            yield block


def hash_file(path: Path, bufsize: int = READ_BUFFER) -> tuple[str, int]:
    """Stream ``path`` through BLAKE3. Returns (hex digest, bytes read)."""
    return hash_iter(iter_file(path, bufsize))


def is_valid_hash(value: str) -> bool:
    return bool(HASH_RE.match(value))


def validate_hash(value: str) -> str:
    if not is_valid_hash(value):
        raise InvalidInputError(f"Invalid content hash {value!r}")
    return value


def object_relpath(kind: str, digest: str, suffix: str) -> str:
    """Relative storage path such as ``blobs/0a/0a92....zst``."""
    validate_hash(digest)
    return f"{kind}/{digest[:2]}/{digest}{suffix}"
