"""Event processing: bounded queue -> debounce -> bounded capture workers.

* The queue is bounded (``monitor.event_queue_size``). When full, events are
  dropped, counted, and a reconciliation of the affected root is requested:
  backpressure without unbounded memory growth and without losing changes.
* Repeated events for one path collapse into one pending capture whose
  deadline slides by ``capture.debounce_seconds`` (capped, so files that are
  written continuously are still captured periodically).
* At most ``capture.max_concurrent`` captures run at a time; further due
  captures wait in the pending map.
"""

from __future__ import annotations

import os
import queue
import threading
import time
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from undo_core.config.settings import Settings
from undo_core.daemon.health import HealthState
from undo_core.database.engine import Database
from undo_core.filesystem.exclusions import ExclusionMatcher
from undo_core.platform.paths import is_within, normalize_path, to_relative
from undo_core.utils.errors import PathOutsideRootError
from undo_core.utils.logging import get_logger
from undo_core.versioning.capture import CaptureEngine, CaptureResult, RootRef
from undo_core.versioning.version_manager import record_delete, record_move

log = get_logger(__name__)

MAX_DEBOUNCE_HOLD = 30.0


@dataclass(frozen=True)
class RawEvent:
    kind: str  # created | modified | deleted | moved
    src: str
    dest: str | None
    is_dir: bool
    root_id: int


@dataclass
class _Pending:
    root: RootRef
    path: Path
    deadline: float
    first_seen: float


class EventProcessor:
    def __init__(
        self,
        *,
        db: Database,
        capture: CaptureEngine,
        settings: Callable[[], Settings],
        roots: Callable[[int], RootRef | None],
        matcher_for: Callable[[RootRef], ExclusionMatcher],
        request_reconcile: Callable[[int, str], None],
        health: HealthState,
    ) -> None:
        self.db = db
        self.capture = capture
        self._settings = settings
        self._roots = roots
        self._matcher_for = matcher_for
        self._request_reconcile = request_reconcile
        self.health = health
        cfg = settings()
        self.queue: queue.Queue[RawEvent] = queue.Queue(maxsize=cfg.monitor.event_queue_size)
        self._pending: dict[tuple[int, str], _Pending] = {}
        self._pending_lock = threading.Lock()
        self._inflight = 0
        self._inflight_lock = threading.Lock()
        self._max_workers = cfg.capture.max_concurrent
        self._executor = ThreadPoolExecutor(
            max_workers=self._max_workers, thread_name_prefix="undo-capture"
        )
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []

    # ---------------------------------------------------------------- lifecycle
    def start(self) -> None:
        for target, name in (
            (self._dispatch_loop, "undo-dispatch"),
            (self._flush_loop, "undo-debounce"),
        ):
            t = threading.Thread(target=target, name=name, daemon=True)
            t.start()
            self._threads.append(t)

    def stop(self, timeout: float = 10.0) -> None:
        self._stop.set()
        for t in self._threads:
            t.join(timeout)
        self._executor.shutdown(wait=True, cancel_futures=True)

    # ---------------------------------------------------------------- ingress
    def submit(self, event: RawEvent) -> bool:
        self.health.event_received()
        try:
            self.queue.put_nowait(event)
            return True
        except queue.Full:
            self.health.event_dropped()
            if self.health.events_dropped % 1000 == 1:
                self.health.overflow()
                log.warning(
                    "event queue full; dropping events and scheduling reconciliation",
                    extra={"root_id": event.root_id},
                )
                self.health.error(
                    f"event queue overflow for root {event.root_id}; reconciliation scheduled"
                )
            self._request_reconcile(event.root_id, "")
            return False

    @property
    def pending_count(self) -> int:
        with self._pending_lock:
            return len(self._pending)

    @property
    def inflight(self) -> int:
        with self._inflight_lock:
            return self._inflight

    def idle(self) -> bool:
        return self.queue.empty() and self.pending_count == 0 and self.inflight == 0

    # ---------------------------------------------------------------- dispatch
    def _dispatch_loop(self) -> None:
        while not self._stop.is_set():
            try:
                event = self.queue.get(timeout=0.25)
            except queue.Empty:
                continue
            try:
                self._handle(event)
            except Exception as exc:
                log.exception("event handling failed", extra={"src": event.src, "kind": event.kind})
                self.health.error(f"event handling failed for {event.src}: {exc}")
                self._request_reconcile(event.root_id, "")

    def _rel(self, root: RootRef, path: str) -> str | None:
        try:
            return to_relative(root.path, path)
        except PathOutsideRootError:
            return None

    def _schedule(self, root: RootRef, path: Path) -> None:
        settings = self._settings()
        now = time.monotonic()
        key = (root.id, os.path.normcase(str(path)))
        with self._pending_lock:
            item = self._pending.get(key)
            if item is None:
                self._pending[key] = _Pending(
                    root, path, now + settings.capture.debounce_seconds, now
                )
            else:
                hold = max(MAX_DEBOUNCE_HOLD, settings.capture.debounce_seconds * 10)
                item.deadline = min(now + settings.capture.debounce_seconds, item.first_seen + hold)

    def _cancel(self, root: RootRef, path: str, is_dir: bool) -> None:
        norm = os.path.normcase(str(normalize_path(path)))
        with self._pending_lock:
            if is_dir:
                prefix = norm.rstrip(os.sep) + os.sep
                for key in [
                    k
                    for k in self._pending
                    if k[0] == root.id and (k[1] == norm or k[1].startswith(prefix))
                ]:
                    del self._pending[key]
            else:
                self._pending.pop((root.id, norm), None)

    def _handle(self, event: RawEvent) -> None:
        root = self._roots(event.root_id)
        if root is None:
            return
        matcher = self._matcher_for(root)
        src_rel = self._rel(root, event.src)
        if event.kind == "moved":
            self._handle_move(root, matcher, event, src_rel)
            return
        if src_rel is None or src_rel == "":
            return
        if matcher.check(src_rel, is_dir=event.is_dir):
            return
        if event.kind in ("created", "modified"):
            if event.is_dir:
                if event.kind == "created":
                    # Files inside a directory that appeared (e.g. moved in or extracted)
                    # may not produce their own events: scan the subtree.
                    self._request_reconcile(root.id, src_rel)
                return
            self._schedule(root, normalize_path(event.src))
        elif event.kind == "deleted":
            self._cancel(root, event.src, event.is_dir)
            if os.path.lexists(event.src):
                return  # replaced already (e.g. atomic save); the create/modify event follows
            with self.db.write() as s:
                record_delete(s, root.id, src_rel, reason="event")

    def _handle_move(
        self, root: RootRef, matcher: ExclusionMatcher, event: RawEvent, src_rel: str | None
    ) -> None:
        dest = event.dest or ""
        dest_rel = self._rel(root, dest) if dest else None
        dest_excluded = (
            dest_rel is None or dest_rel == "" or bool(matcher.check(dest_rel, is_dir=event.is_dir))
        )
        if src_rel:
            self._cancel(root, event.src, event.is_dir)
        if src_rel and dest_rel and not dest_excluded:
            with self.db.write() as s:
                moved = record_move(s, root.id, src_rel, dest_rel)
            if event.is_dir:
                # Reconcile the destination to catch files the database did not know yet.
                self._request_reconcile(root.id, dest_rel)
            elif moved:
                self._schedule(root, normalize_path(dest))  # quick no-op if content unchanged
            else:
                self._schedule(root, normalize_path(dest))
            return
        if src_rel and (dest_excluded or dest_rel is None):
            # Moved out of the root (or into an excluded location): a deletion here.
            if not os.path.lexists(event.src):
                with self.db.write() as s:
                    record_delete(s, root.id, src_rel, reason="moved out of tracked area")
        if dest_rel and not dest_excluded:
            if event.is_dir:
                self._request_reconcile(root.id, dest_rel)
            else:
                self._schedule(root, normalize_path(dest))

    # ---------------------------------------------------------------- flushing
    def _flush_loop(self) -> None:
        while not self._stop.wait(0.1):
            now = time.monotonic()
            due: list[_Pending] = []
            with self._pending_lock:
                capacity = self._max_workers * 2 - self.inflight
                if capacity <= 0:
                    continue
                for key, item in list(self._pending.items()):
                    if item.deadline <= now:
                        due.append(item)
                        del self._pending[key]
                        if len(due) >= capacity:
                            break
            for item in due:
                self._run_capture(item)

    def _run_capture(self, item: _Pending) -> None:
        with self._inflight_lock:
            self._inflight += 1
        try:
            future = self._executor.submit(self.capture.capture, item.root, item.path)
        except RuntimeError:  # executor shut down
            with self._inflight_lock:
                self._inflight -= 1
            return
        future.add_done_callback(self._capture_done)

    def _capture_done(self, future: Future[CaptureResult]) -> None:
        with self._inflight_lock:
            self._inflight -= 1
        if future.cancelled():
            return
        exc = future.exception()
        if exc is not None:
            log.error("capture crashed", extra={"error": str(exc)})
            self.health.error(f"capture crashed: {exc}")


def event_within_root(path: str, root: RootRef) -> bool:
    return is_within(path, root.path)
