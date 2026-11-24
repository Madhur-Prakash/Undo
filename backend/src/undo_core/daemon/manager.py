"""The Undo daemon: owns the data directory, monitors roots and serves the local API."""

from __future__ import annotations

import argparse
import contextlib
import socket
import sys
import threading
from collections.abc import Callable
from datetime import timedelta
from pathlib import Path

import uvicorn

from undo_core import API_VERSION, __version__
from undo_core.config.token import ensure_token
from undo_core.context import UndoContext
from undo_core.daemon.health import HealthState
from undo_core.daemon.lifecycle import remove_daemon_info, startup_recovery, write_daemon_info
from undo_core.daemon.locking import ProcessLock
from undo_core.daemon.scheduler import Scheduler
from undo_core.database.repositories import PinRepository, RootRepository
from undo_core.domain import HealthInfo
from undo_core.filesystem.adapters import get_adapter
from undo_core.filesystem.event_processor import EventProcessor
from undo_core.filesystem.watcher import WatcherManager
from undo_core.platform.paths import UndoPaths
from undo_core.roots import root_ref
from undo_core.service import UndoService
from undo_core.utils.errors import NotInitializedError, UndoError
from undo_core.utils.logging import get_logger, setup_logging
from undo_core.utils.timeutil import to_aware, utcnow
from undo_core.versioning.capture import RootRef

log = get_logger(__name__)


class ReconcileQueue:
    """Deduplicating queue of (root_id, prefix) reconciliation requests with one worker."""

    def __init__(self, run: Callable[[int, str], None], health: HealthState) -> None:
        self._run = run
        self.state = health
        self._items: dict[int, set[str]] = {}
        self._cond = threading.Condition()
        self._stop = False
        self._thread = threading.Thread(target=self._loop, name="undo-reconcile", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def request(self, root_id: int, prefix: str = "") -> None:
        with self._cond:
            prefixes = self._items.setdefault(root_id, set())
            if prefix == "" or "" not in prefixes:
                if prefix == "":
                    prefixes.clear()
                prefixes.add(prefix)
            self._cond.notify()

    def pending(self) -> int:
        with self._cond:
            return sum(len(v) for v in self._items.values())

    def stop(self, timeout: float = 30.0) -> None:
        with self._cond:
            self._stop = True
            self._cond.notify_all()
        self._thread.join(timeout)

    def _loop(self) -> None:
        while True:
            with self._cond:
                while not self._items and not self._stop:
                    self._cond.wait()
                if self._stop:
                    return
                root_id = next(iter(self._items))
                prefixes = sorted(self._items.pop(root_id))
            for prefix in prefixes:
                self.state.reconciling = True
                try:
                    self._run(root_id, prefix)
                except Exception as exc:
                    log.exception("reconcile failed", extra={"root_id": root_id, "prefix": prefix})
                    self.state.error(f"reconcile of root {root_id} failed: {exc}")
                finally:
                    self.state.reconciling = False
                    if prefix == "":
                        self.state.last_reconcile_at = utcnow()


class DaemonManager:
    """Implements :class:`undo_core.service.DaemonHooks`."""

    def __init__(self, data_dir: str | Path | None = None, *, console_log: bool = False) -> None:
        self.paths = UndoPaths.resolve(data_dir)
        self.console_log = console_log
        self.state = HealthState()
        self.lock = ProcessLock(self.paths.lock_path)
        self.ctx: UndoContext | None = None
        self.service: UndoService | None = None
        self.processor: EventProcessor | None = None
        self.watchers: WatcherManager | None = None
        self.reconcile_queue: ReconcileQueue | None = None
        self.scheduler: Scheduler | None = None
        self.server: uvicorn.Server | None = None
        self.api_url: str | None = None
        self._stop_requested = threading.Event()
        self._started = threading.Event()

    # ------------------------------------------------------------------ hooks
    def _enabled_roots(self) -> list[RootRef]:
        assert self.ctx is not None
        with self.ctx.db.read() as s:
            return [root_ref(r) for r in RootRepository(s).all(enabled_only=True)]

    def _root_by_id(self, root_id: int) -> RootRef | None:
        assert self.ctx is not None
        with self.ctx.db.read() as s:
            root = RootRepository(s).get(root_id)
            return root_ref(root) if root is not None and root.enabled else None

    def on_roots_changed(self) -> None:
        if self.watchers is not None:
            self.watchers.sync(self._enabled_roots())

    def request_reconcile(self, root_id: int, prefix: str = "") -> None:
        if self.reconcile_queue is not None:
            self.reconcile_queue.request(root_id, prefix)

    def watch_mode(self, root_id: int) -> str | None:
        return self.watchers.mode_of(root_id) if self.watchers else None

    def health(self) -> HealthInfo:
        h = self.state.snapshot()
        settings = self.ctx.settings if self.ctx else None
        import os

        return HealthInfo(
            running=True,
            pid=os.getpid(),
            version=__version__,
            api_version=API_VERSION,
            started_at=to_aware(self.state.started_at),  # type: ignore[arg-type]
            uptime_seconds=round(self.state.uptime(), 1),
            data_dir=str(self.paths.data_dir),
            api_url=self.api_url,
            watchers=h["watchers"],
            queue_depth=self.processor.queue.qsize() if self.processor else 0,
            queue_capacity=settings.monitor.event_queue_size if settings else 0,
            pending_captures=(self.processor.pending_count + self.processor.inflight)
            if self.processor
            else 0,
            events_received=h["events_received"],
            events_dropped=h["events_dropped"],
            overflow_count=h["overflow_count"],
            captures=self.ctx.capture.stats.snapshot() if self.ctx else {},
            last_reconcile_at=to_aware(h["last_reconcile_at"]),
            reconciling=h["reconciling"]
            or bool(self.reconcile_queue and self.reconcile_queue.pending()),
            jobs={
                "schedule": self.scheduler.describe() if self.scheduler else {},
                "last": h["jobs"],
            },
            recent_errors=h["recent_errors"],
            recovery=h["recovery"],
        )

    # ------------------------------------------------------------------ lifecycle
    def request_stop(self) -> None:
        self._stop_requested.set()
        if self.server is not None:
            self.server.should_exit = True

    def _bind(self, host: str, port: int) -> socket.socket:
        family = socket.AF_INET6 if ":" in host else socket.AF_INET
        sock = socket.socket(family, socket.SOCK_STREAM)
        if sys.platform != "win32":
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, port))
        except OSError:
            log.warning("API port busy; using a random port", extra={"port": port})
            sock.close()
            sock = socket.socket(family, socket.SOCK_STREAM)
            sock.bind((host, 0))
        sock.listen(64)
        sock.set_inheritable(True)
        return sock

    def _start_components(self) -> None:
        ctx = self.ctx
        assert ctx is not None
        self.reconcile_queue = ReconcileQueue(self._reconcile_one, self.state)
        self.processor = EventProcessor(
            db=ctx.db,
            capture=ctx.capture,
            settings=lambda: ctx.settings,
            roots=self._root_by_id,
            matcher_for=ctx.matcher_for,
            request_reconcile=self.request_reconcile,
            health=self.state,
        )
        self.watchers = WatcherManager(
            adapter=get_adapter(),
            processor=self.processor,
            settings=lambda: ctx.settings,
            health=self.state,
            data_dir=self.paths.data_dir,
            request_reconcile=self.request_reconcile,
        )
        self.reconcile_queue.start()
        self.processor.start()
        self.watchers.sync(self._enabled_roots())
        if ctx.settings.monitor.initial_scan:
            for root in self._enabled_roots():
                self.request_reconcile(root.id, "")
        self.scheduler = Scheduler(self.state)
        self._schedule_jobs()
        self.scheduler.start()

    def _reconcile_one(self, root_id: int, prefix: str) -> None:
        assert self.ctx is not None
        root = self._root_by_id(root_id)
        if root is None:
            return
        report = self.ctx.reconciler.reconcile(root, prefix=prefix)
        for err in report.errors[:5]:
            self.state.error(err)

    def _schedule_jobs(self) -> None:
        ctx, service, sched = self.ctx, self.service, self.scheduler
        assert ctx is not None and service is not None and sched is not None

        def reconcile_all() -> None:
            for root in self._enabled_roots():
                self.request_reconcile(root.id, "")

        def retention() -> None:
            policy = ctx.settings.retention
            if policy.keep_all and policy.max_storage_bytes is None:
                return
            report = service.apply_retention(dry_run=False)
            if report.versions_removed:
                service.garbage_collect(dry_run=False)

        def maintenance() -> None:
            assert self.watchers is not None
            self.watchers.check()
            self.watchers.sync(self._enabled_roots())
            with ctx.db.write() as s:
                PinRepository(s).purge_older_than(utcnow() - timedelta(hours=6))

        s = ctx.settings
        sched.add(
            "reconcile", lambda: ctx.settings.monitor.reconcile_interval_seconds, reconcile_all
        )
        sched.add(
            "retention",
            lambda: ctx.settings.retention.interval_seconds,
            retention,
            initial_delay=min(600, s.retention.interval_seconds),
        )
        sched.add(
            "gc",
            lambda: ctx.settings.daemon.gc_interval_seconds,
            lambda: service.garbage_collect(dry_run=False),
        )
        sched.add(
            "verify",
            lambda: ctx.settings.daemon.verify_interval_seconds,
            lambda: service.verify_storage(full=True),
        )
        sched.add("maintenance", lambda: 30.0, maintenance)
        sched.add("checkpoint", lambda: 600.0, ctx.db.checkpoint)

    def _stop_components(self) -> None:
        components: list[tuple[str, Callable[[], None] | None]] = [
            ("scheduler", self.scheduler.stop if self.scheduler else None),
            ("watchers", self.watchers.stop if self.watchers else None),
            ("processor", self.processor.stop if self.processor else None),
            ("reconcile", self.reconcile_queue.stop if self.reconcile_queue else None),
        ]
        for name, stop in components:
            if stop is None:
                continue
            try:
                stop()
            except Exception as exc:
                log.error("error stopping component", extra={"component": name, "error": str(exc)})

    def run(self) -> int:
        if not self.paths.is_initialized():
            raise NotInitializedError(
                f"Undo is not initialised in {self.paths.data_dir}; run `undo init`"
            )
        self.lock.acquire(purpose="daemon")
        try:
            self.ctx = UndoContext.open(self.paths.data_dir)
            settings = self.ctx.settings
            setup_logging(
                self.paths.logs_dir, level=settings.daemon.log_level, console=self.console_log
            )
            log.info(
                "daemon starting",
                extra={"data_dir": str(self.paths.data_dir), "version": __version__},
            )
            self.state.recovery = startup_recovery(self.ctx)
            self.service = UndoService(self.ctx, hooks=self)
            token = ensure_token(self.paths.token_path)
            self._start_components()
            from undo_core.api.app import create_app

            app = create_app(self.service, token=token, on_shutdown=self.request_stop)
            sock = self._bind(settings.api.host, settings.api.port)
            host, port = sock.getsockname()[:2]
            config = uvicorn.Config(app, log_level="warning", access_log=False, lifespan="off")
            self.server = uvicorn.Server(config)
            info = write_daemon_info(self.paths, str(host), int(port))
            self.api_url = info.base_url
            log.info("API listening", extra={"url": info.base_url})
            self._started.set()
            if self._stop_requested.is_set():
                self.server.should_exit = True
            self.server.run(sockets=[sock])
            return 0
        finally:
            log.info("daemon stopping")
            self._stop_components()
            remove_daemon_info(self.paths)
            if self.ctx is not None:
                with contextlib.suppress(Exception):
                    self.ctx.db.checkpoint()
                self.ctx.close()
            self.lock.release()
            log.info("daemon stopped")

    def wait_started(self, timeout: float = 30.0) -> bool:
        return self._started.wait(timeout)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="undo-daemon", description="Run the Undo daemon in the foreground."
    )
    parser.add_argument(
        "--data-dir",
        default=None,
        help="Undo data directory (default: platform location or UNDO_HOME)",
    )
    parser.add_argument("--console-log", action="store_true", help="Also log to stderr")
    parser.add_argument(
        "--init",
        action="store_true",
        help="Initialise the data directory first if it is not initialised yet",
    )
    args = parser.parse_args(argv)
    try:
        if args.init:
            from undo_core.context import UndoContext

            ctx = UndoContext.open(args.data_dir, require_initialized=False)
            try:
                if not ctx.paths.is_initialized():
                    ctx.initialize()
            finally:
                ctx.close()
        return DaemonManager(args.data_dir, console_log=args.console_log).run()
    except UndoError as exc:
        print(f"undo-daemon: {exc.message}", file=sys.stderr)
        return exc.exit_code
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
