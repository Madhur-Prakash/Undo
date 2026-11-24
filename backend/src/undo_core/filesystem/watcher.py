"""Watchdog integration: one native observer, one polling observer, per-root watches.

Native monitoring (inotify / ReadDirectoryChangesW) is tried first; if a root
cannot be watched natively (watch limits, unsupported filesystem) it falls back
to polling and the mode is shown in ``undo status``. A dead observer thread is
detected by the health check, restarted, and its roots reconciled.
"""

from __future__ import annotations

import os
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers.api import BaseObserver, ObservedWatch

from undo_core.config.settings import Settings
from undo_core.daemon.health import HealthState
from undo_core.domain import WatcherInfo
from undo_core.filesystem.adapters.base import PlatformAdapter
from undo_core.filesystem.event_processor import EventProcessor, RawEvent
from undo_core.platform.paths import is_within
from undo_core.recovery.restore_safety import RESTORE_TMP_PREFIX
from undo_core.utils.logging import get_logger
from undo_core.versioning.capture import RootRef

log = get_logger(__name__)


class _Handler(FileSystemEventHandler):
    def __init__(self, root_id: int, processor: EventProcessor, data_dir: Path) -> None:
        super().__init__()
        self.root_id = root_id
        self.processor = processor
        self.data_dir = data_dir

    def _ignored(self, path: str) -> bool:
        return os.path.basename(path).startswith(RESTORE_TMP_PREFIX) or is_within(
            path, self.data_dir
        )

    def on_any_event(self, event: FileSystemEvent) -> None:
        kind = event.event_type
        if kind == "closed":
            kind = "modified"  # IN_CLOSE_WRITE: the writer finished
        if kind not in ("created", "modified", "deleted", "moved"):
            return
        src = os.fsdecode(event.src_path)
        dest_raw = getattr(event, "dest_path", "") or ""
        dest = os.fsdecode(dest_raw) if dest_raw else None
        if self._ignored(src) and (dest is None or self._ignored(dest)):
            return
        if kind == "moved" and self._ignored(src) and dest:
            kind, src, dest = "created", dest, None  # e.g. our temp file renamed into place
        self.processor.submit(RawEvent(kind, src, dest, bool(event.is_directory), self.root_id))


class WatcherManager:
    def __init__(
        self,
        *,
        adapter: PlatformAdapter,
        processor: EventProcessor,
        settings: Callable[[], Settings],
        health: HealthState,
        data_dir: Path,
        request_reconcile: Callable[[int, str], None],
    ) -> None:
        self.adapter = adapter
        self.processor = processor
        self._settings = settings
        self.health = health
        self.data_dir = data_dir
        self._request_reconcile = request_reconcile
        self._lock = threading.RLock()
        self._native: BaseObserver | None = None
        self._polling: BaseObserver | None = None
        self._watches: dict[int, tuple[str, ObservedWatch, RootRef]] = {}

    def _ensure_native(self) -> BaseObserver | None:
        if self._native is None:
            try:
                obs = self.adapter.create_native_observer()
                obs.daemon = True
                obs.start()
                self._native = obs
            except Exception as exc:
                log.error("native observer unavailable", extra={"error": str(exc)})
                self.health.error(f"native filesystem monitoring unavailable: {exc}")
                return None
        return self._native

    def _ensure_polling(self) -> BaseObserver:
        if self._polling is None:
            obs = self.adapter.create_polling_observer(
                self._settings().monitor.polling_interval_seconds
            )
            obs.daemon = True
            obs.start()
            self._polling = obs
        return self._polling

    def add_root(self, root: RootRef) -> WatcherInfo:
        with self._lock:
            if root.id in self._watches:
                self.remove_root(root.id)
            handler = _Handler(root.id, self.processor, self.data_dir)
            error: str | None = None
            if not root.path.is_dir():
                info = WatcherInfo(
                    root_id=root.id,
                    path=str(root.path),
                    mode="unavailable",
                    healthy=False,
                    error="root directory not accessible",
                )
                self.health.set_watcher(info)
                return info
            mode = "polling"
            if not self._settings().monitor.force_polling:
                native = self._ensure_native()
                if native is not None:
                    try:
                        watch = native.schedule(handler, str(root.path), recursive=True)
                        self._watches[root.id] = ("native", watch, root)
                        mode = self.adapter.native_backend
                    except Exception as exc:
                        error = (
                            self.adapter.capacity_hint(root.path)
                            if self.adapter.is_capacity_error(exc)
                            else str(exc)
                        )
                        log.warning(
                            "native watch failed; falling back to polling",
                            extra={"root": str(root.path), "error": str(exc)},
                        )
                        self.health.error(f"{root.path}: {error}")
            if root.id not in self._watches:
                watch = self._ensure_polling().schedule(handler, str(root.path), recursive=True)
                self._watches[root.id] = ("polling", watch, root)
                mode = "polling"
            info = WatcherInfo(
                root_id=root.id, path=str(root.path), mode=mode, healthy=True, error=error
            )
            self.health.set_watcher(info)
            log.info("watching root", extra={"root": str(root.path), "mode": mode})
            return info

    def remove_root(self, root_id: int) -> None:
        with self._lock:
            entry = self._watches.pop(root_id, None)
            self.health.remove_watcher(root_id)
            if entry is None:
                return
            kind, watch, _root = entry
            observer = self._native if kind == "native" else self._polling
            if observer is not None:
                try:
                    observer.unschedule(watch)
                except Exception as exc:
                    log.warning("unschedule failed", extra={"error": str(exc)})

    def sync(self, roots: list[RootRef]) -> None:
        with self._lock:
            wanted = {r.id: r for r in roots}
            for root_id in list(self._watches):
                if root_id not in wanted or self._watches[root_id][2].path != wanted[root_id].path:
                    self.remove_root(root_id)
            for root_id, root in wanted.items():
                if root_id not in self._watches:
                    self.add_root(root)

    def mode_of(self, root_id: int) -> str | None:
        with self._lock:
            entry = self._watches.get(root_id)
            if entry is None:
                return None
            return self.adapter.native_backend if entry[0] == "native" else "polling"

    def check(self) -> None:
        """Restart a dead observer and reconcile the roots it was watching."""
        with self._lock:
            for kind in ("native", "polling"):
                observer = self._native if kind == "native" else self._polling
                if observer is None or observer.is_alive():
                    continue
                log.error("observer thread died; restarting", extra={"kind": kind})
                self.health.error(f"{kind} observer stopped unexpectedly; restarted")
                affected = [r for (k, _w, r) in self._watches.values() if k == kind]
                if kind == "native":
                    self._native = None
                else:
                    self._polling = None
                for root in affected:
                    self._watches.pop(root.id, None)
                    self.add_root(root)
                    self._request_reconcile(root.id, "")

    def stop(self) -> None:
        with self._lock:
            for observer in (self._native, self._polling):
                if observer is not None:
                    try:
                        observer.stop()
                        observer.join(timeout=5)
                    except Exception as exc:
                        log.warning("observer stop failed", extra={"error": str(exc)})
            self._native = None
            self._polling = None
            self._watches.clear()

    def info(self) -> dict[str, Any]:
        return self.adapter.info()
