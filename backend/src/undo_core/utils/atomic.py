"""Atomic filesystem helpers used by storage and restore."""

from __future__ import annotations

import contextlib
import errno
import os
import tempfile
from pathlib import Path
from typing import BinaryIO

IS_WINDOWS = os.name == "nt"


def fsync_file(handle: BinaryIO) -> None:
    """Flush Python buffers and ask the OS to persist the file."""
    handle.flush()
    os.fsync(handle.fileno())


def fsync_dir(path: Path) -> None:
    """Persist a directory entry change (POSIX only; a no-op on Windows)."""
    if IS_WINDOWS:
        return
    try:
        fd = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def atomic_write_bytes(path: Path, data: bytes, *, mode: int | None = None) -> None:
    """Write ``data`` to ``path`` atomically (temp file + fsync + replace)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            fsync_file(handle)
        if mode is not None and not IS_WINDOWS:
            os.chmod(tmp, mode)
        os.replace(tmp, path)
        fsync_dir(path.parent)
    except BaseException:
        with contextlib.suppress(OSError):
            tmp.unlink()
        raise


def atomic_write_text(path: Path, text: str, *, mode: int | None = None) -> None:
    atomic_write_bytes(path, text.encode("utf-8"), mode=mode)


def rename_no_clobber(src: Path, dst: Path) -> bool:
    """Move ``src`` to ``dst`` only if ``dst`` does not exist.

    Returns True when the move happened, False when ``dst`` already existed
    (in which case ``src`` is left untouched). On Windows ``os.rename`` refuses
    to overwrite. On POSIX a hard link is used to get an atomic no-clobber
    publish, with a guarded rename fallback for filesystems without links.
    """
    if IS_WINDOWS:
        try:
            os.rename(src, dst)
            return True
        except FileExistsError:
            return False
        except PermissionError:
            if dst.exists():
                return False
            raise
    try:
        os.link(src, dst)
    except FileExistsError:
        return False
    except OSError as exc:
        if exc.errno not in (
            errno.EPERM,
            errno.ENOTSUP,
            errno.EXDEV,
            errno.EMLINK,
            errno.EOPNOTSUPP,
        ):
            raise
        if dst.exists():
            return False
        os.rename(src, dst)
        return True
    with contextlib.suppress(FileNotFoundError):
        os.unlink(src)
    return True


def remove_quietly(path: Path) -> bool:
    try:
        path.unlink()
        return True
    except FileNotFoundError:
        return False
    except OSError:
        return False
