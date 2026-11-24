"""Ownership locking.

* :class:`ProcessLock` - OS-level exclusive lock (``fcntl.flock`` / ``msvcrt.locking``)
  on ``undo.lock``. Held by the daemon for its lifetime and by CLI commands that
  write while no daemon runs. The kernel drops the lock when the process dies,
  so a stale PID file can never block startup. The PID is written to a separate
  info file purely for display.
* :class:`KeyedLocks` - per-file in-process locks so concurrent watcher events
  for one file never produce conflicting captures.
"""

from __future__ import annotations

import contextlib
import json
import os
import sys
import threading
from collections.abc import Hashable, Iterator
from pathlib import Path
from typing import IO, Any

from undo_core.utils.errors import LockedError

IS_WINDOWS = sys.platform == "win32"

if sys.platform == "win32":
    import msvcrt
else:
    import fcntl


class ProcessLock:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._handle: IO[bytes] | None = None
        self._guard = threading.Lock()

    @property
    def held(self) -> bool:
        return self._handle is not None

    def acquire(self, *, purpose: str = "undo") -> None:
        with self._guard:
            if self._handle is not None:
                return
            self.path.parent.mkdir(parents=True, exist_ok=True)
            handle = open(self.path, "a+b")  # noqa: SIM115 - kept open while locked
            try:
                if sys.platform == "win32":
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                handle.close()
                holder = read_lock_owner(self.path)
                raise LockedError(
                    "The Undo data directory is in use by another process"
                    + (f" ({holder.get('purpose')}, pid {holder.get('pid')})" if holder else ""),
                    details={"holder": holder},
                ) from exc
            self._handle = handle
            _write_owner(self.path, purpose)

    def release(self) -> None:
        with self._guard:
            if self._handle is None:
                return
            try:
                if sys.platform == "win32":
                    self._handle.seek(0)
                    with contextlib.suppress(OSError):
                        msvcrt.locking(self._handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)
            finally:
                self._handle.close()
                self._handle = None
                with contextlib.suppress(OSError):
                    _owner_path(self.path).unlink()

    def __enter__(self) -> ProcessLock:
        self.acquire()
        return self

    def __exit__(self, *exc: object) -> None:
        self.release()


def _owner_path(lock_path: Path) -> Path:
    return lock_path.with_suffix(".owner")


def _write_owner(lock_path: Path, purpose: str) -> None:
    with contextlib.suppress(OSError):
        _owner_path(lock_path).write_text(
            json.dumps({"pid": os.getpid(), "purpose": purpose}), encoding="utf-8"
        )


def read_lock_owner(lock_path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(_owner_path(lock_path).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def is_locked(lock_path: Path) -> bool:
    """True if some process currently holds the lock (probe without keeping it)."""
    probe = ProcessLock(lock_path)
    try:
        probe.acquire(purpose="probe")
    except LockedError:
        return True
    # We got it: nobody holds it. Release without deleting a real owner file.
    with probe._guard:
        handle = probe._handle
        probe._handle = None
    if handle is not None:
        try:
            if sys.platform == "win32":
                handle.seek(0)
                with contextlib.suppress(OSError):
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()
    with contextlib.suppress(OSError):
        _owner_path(lock_path).unlink()
    return False


class KeyedLocks:
    """Reference-counted per-key re-entrant locks."""

    def __init__(self) -> None:
        self._guard = threading.Lock()
        self._locks: dict[Hashable, tuple[threading.RLock, int]] = {}

    @contextlib.contextmanager
    def hold(self, key: Hashable) -> Iterator[None]:
        with self._guard:
            lock, count = self._locks.get(key, (threading.RLock(), 0))
            self._locks[key] = (lock, count + 1)
        lock.acquire()
        try:
            yield
        finally:
            lock.release()
            with self._guard:
                lock2, count2 = self._locks[key]
                if count2 <= 1:
                    del self._locks[key]
                else:
                    self._locks[key] = (lock2, count2 - 1)

    def active(self) -> int:
        with self._guard:
            return len(self._locks)
