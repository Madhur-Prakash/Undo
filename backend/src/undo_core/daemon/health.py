"""Thread-safe daemon health counters."""

from __future__ import annotations

import threading
import time
from collections import deque
from datetime import datetime
from typing import Any

from undo_core.domain import RecoveryInfo, WatcherInfo
from undo_core.utils.timeutil import utcnow


class HealthState:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.started_at = utcnow()
        self._started_mono = time.monotonic()
        self.events_received = 0
        self.events_dropped = 0
        self.overflow_count = 0
        self.last_reconcile_at: datetime | None = None
        self.reconciling = False
        self.recent_errors: deque[str] = deque(maxlen=50)
        self.watchers: dict[int, WatcherInfo] = {}
        self.jobs: dict[str, dict[str, Any]] = {}
        self.recovery: RecoveryInfo | None = None

    def uptime(self) -> float:
        return time.monotonic() - self._started_mono

    def event_received(self) -> None:
        with self._lock:
            self.events_received += 1

    def event_dropped(self) -> None:
        with self._lock:
            self.events_dropped += 1

    def overflow(self) -> None:
        with self._lock:
            self.overflow_count += 1

    def error(self, message: str) -> None:
        with self._lock:
            self.recent_errors.append(f"{utcnow().isoformat(timespec='seconds')}Z {message}")

    def set_watcher(self, info: WatcherInfo) -> None:
        with self._lock:
            self.watchers[info.root_id] = info

    def remove_watcher(self, root_id: int) -> None:
        with self._lock:
            self.watchers.pop(root_id, None)

    def job_ran(self, name: str, ok: bool, detail: str | None = None) -> None:
        with self._lock:
            self.jobs[name] = {"last_run": utcnow().isoformat(), "ok": ok, "detail": detail}

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "events_received": self.events_received,
                "events_dropped": self.events_dropped,
                "overflow_count": self.overflow_count,
                "last_reconcile_at": self.last_reconcile_at,
                "reconciling": self.reconciling,
                "recent_errors": list(self.recent_errors),
                "watchers": list(self.watchers.values()),
                "jobs": dict(self.jobs),
                "recovery": self.recovery,
            }
