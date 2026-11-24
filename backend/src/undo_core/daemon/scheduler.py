"""Tiny periodic job scheduler (one thread; intervals re-read every cycle so settings apply live)."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

from undo_core.daemon.health import HealthState
from undo_core.utils.logging import get_logger

log = get_logger(__name__)


@dataclass
class Job:
    name: str
    interval: Callable[[], float]  # seconds; <= 0 disables the job
    fn: Callable[[], object]
    next_run: float


class Scheduler:
    def __init__(self, health: HealthState) -> None:
        self.health = health
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread: threading.Thread | None = None

    def add(
        self,
        name: str,
        interval: Callable[[], float],
        fn: Callable[[], object],
        *,
        initial_delay: float | None = None,
    ) -> None:
        delay = interval() if initial_delay is None else initial_delay
        with self._lock:
            self._jobs[name] = Job(name, interval, fn, time.monotonic() + max(delay, 0))

    def run_soon(self, name: str) -> None:
        with self._lock:
            if name in self._jobs:
                self._jobs[name].next_run = 0
        self._wake.set()

    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, name="undo-scheduler", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 30.0) -> None:
        self._stop.set()
        self._wake.set()
        if self._thread:
            self._thread.join(timeout)

    def _loop(self) -> None:
        while not self._stop.is_set():
            now = time.monotonic()
            with self._lock:
                due = [j for j in self._jobs.values() if j.next_run <= now and j.interval() > 0]
            for job in due:
                if self._stop.is_set():
                    return
                try:
                    job.fn()
                    self.health.job_ran(job.name, True)
                except Exception as exc:
                    log.exception("scheduled job failed", extra={"job": job.name})
                    self.health.job_ran(job.name, False, str(exc))
                    self.health.error(f"job {job.name} failed: {exc}")
                with self._lock:
                    job.next_run = time.monotonic() + max(job.interval(), 1.0)
            self._wake.wait(1.0)
            self._wake.clear()

    def describe(self) -> dict[str, dict[str, float]]:
        now = time.monotonic()
        with self._lock:
            return {
                j.name: {
                    "interval_seconds": j.interval(),
                    "next_run_in_seconds": round(max(j.next_run - now, 0), 1),
                }
                for j in self._jobs.values()
            }
