"""Thread-safe backend holder for the TUI (reconnects when the daemon starts or stops)."""

from __future__ import annotations

import threading
from typing import Any

from undo_core.daemon.lifecycle import discover, start_background, stop_daemon
from undo_core.utils.errors import DaemonNotRunningError

from undo_cli.client import Backend, RemoteBackend, get_backend
from undo_cli.commands.common import State


class TuiBackend:
    def __init__(self, state: State) -> None:
        self.state = state
        self._lock = threading.RLock()
        self._backend: Backend | None = None

    def _get(self) -> Backend:
        if self._backend is None:
            self._backend = get_backend(self.state.data_dir, local_only=self.state.local_only)
        return self._backend

    def reconnect(self) -> None:
        with self._lock:
            if self._backend is not None:
                self._backend.close()
            self._backend = None

    @property
    def mode(self) -> str:
        with self._lock:
            return self._get().mode

    @property
    def description(self) -> str:
        with self._lock:
            return self._get().description

    def call(self, op: str, **kwargs: Any) -> Any:
        with self._lock:
            backend = self._get()
            # A daemon that appeared since we connected locally takes precedence.
            if backend.mode == "local" and not self.state.local_only and discover(self.state.paths):
                self.reconnect()
                backend = self._get()
            try:
                return backend.call(op, **kwargs)
            except DaemonNotRunningError:
                if isinstance(backend, RemoteBackend):
                    self.reconnect()
                    return self._get().call(op, **kwargs)
                raise

    def start_daemon(self) -> str:
        info = start_background(self.state.paths)
        self.reconnect()
        return f"Daemon running (pid {info.pid})"

    def stop_daemon(self) -> str:
        self.reconnect()
        stopped = stop_daemon(self.state.paths)
        self.reconnect()
        return "Daemon stopped" if stopped else "Daemon was not running"

    def close(self) -> None:
        self.reconnect()
