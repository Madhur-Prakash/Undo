"""Test helpers importable from every test module (pytest pythonpath = backend/tests)."""

from __future__ import annotations

import itertools
import os
import time
from pathlib import Path

_tick = itertools.count(1)


def write(path: Path, data: bytes | str) -> Path:
    """Write content and give it a unique mtime so size+mtime change detection is deterministic."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = data.encode() if isinstance(data, str) else data
    path.write_bytes(payload)
    ns = time.time_ns() - 10_000_000_000 + next(_tick) * 1_000_000
    os.utime(path, ns=(ns, ns))
    return path
