"""Event processor and watcher behaviour (debounce, overflow/backpressure, polling fallback)."""

from __future__ import annotations

import time
from pathlib import Path

from helpers import write
from undo_core.context import UndoContext
from undo_core.daemon.health import HealthState
from undo_core.database.repositories import FileRepository, VersionRepository
from undo_core.filesystem.adapters.base import PlatformAdapter
from undo_core.filesystem.event_processor import EventProcessor, RawEvent
from undo_core.filesystem.watcher import WatcherManager
from undo_core.versioning.capture import RootRef


def _processor(
    ctx: UndoContext, root: RootRef, requests: list[tuple[int, str]], queue_size: int | None = None
) -> EventProcessor:
    if queue_size:
        ctx.settings_store.update({"monitor": {"event_queue_size": queue_size}})
    return EventProcessor(
        db=ctx.db,
        capture=ctx.capture,
        settings=lambda: ctx.settings,
        roots=lambda rid: root if rid == root.id else None,
        matcher_for=ctx.matcher_for,
        request_reconcile=lambda rid, prefix: requests.append((rid, prefix)),
        health=HealthState(),
    )


def _versions(ctx: UndoContext, root: RootRef, rel: str) -> list[str]:
    with ctx.db.read() as s:
        f = FileRepository(s).by_path_any(root.id, rel)
        return [v.operation for v in VersionRepository(s).for_file(f.id)] if f else []


def _wait(cond, timeout: float = 10) -> None:  # type: ignore[no-untyped-def]
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return
        time.sleep(0.05)
    raise AssertionError("timeout")


def test_repeated_events_are_debounced_into_one_version(ctx: UndoContext, tracked: RootRef) -> None:
    proc = _processor(ctx, tracked, [])
    proc.start()
    try:
        f = tracked.path / "busy.txt"
        for i in range(30):
            write(f, f"edit {i}")
            proc.submit(RawEvent("modified", str(f), None, False, tracked.id))
        _wait(lambda: proc.idle() and _versions(ctx, tracked, "busy.txt"))
        assert _versions(ctx, tracked, "busy.txt") == ["CREATE"]
        assert f.read_text() == "edit 29"
    finally:
        proc.stop()


def test_queue_overflow_applies_backpressure_and_requests_reconcile(
    ctx: UndoContext, tracked: RootRef
) -> None:
    requests: list[tuple[int, str]] = []
    proc = _processor(
        ctx, tracked, requests, queue_size=100
    )  # not started: nothing drains the queue
    accepted = sum(
        proc.submit(RawEvent("modified", str(tracked.path / f"{i}.txt"), None, False, tracked.id))
        for i in range(250)
    )
    assert accepted == 100
    assert proc.health.events_dropped == 150
    assert (tracked.id, "") in requests
    proc.stop()


def test_move_and_delete_events(ctx: UndoContext, tracked: RootRef) -> None:
    proc = _processor(ctx, tracked, [])
    proc.start()
    try:
        f = write(tracked.path / "a.txt", "x")
        proc.submit(RawEvent("created", str(f), None, False, tracked.id))
        _wait(lambda: proc.idle() and _versions(ctx, tracked, "a.txt"))
        new = tracked.path / "b.txt"
        f.rename(new)
        proc.submit(RawEvent("moved", str(f), str(new), False, tracked.id))
        _wait(lambda: proc.idle() and _versions(ctx, tracked, "b.txt")[:1] == ["RENAME"])
        new.unlink()
        proc.submit(RawEvent("deleted", str(new), None, False, tracked.id))
        _wait(lambda: proc.idle() and _versions(ctx, tracked, "b.txt")[:1] == ["DELETE"])
        # a directory appearing triggers a subtree reconcile request
        requests: list[tuple[int, str]] = []
        proc._request_reconcile = lambda rid, p: requests.append((rid, p))  # type: ignore[method-assign]
        (tracked.path / "newdir").mkdir()
        proc.submit(RawEvent("created", str(tracked.path / "newdir"), None, True, tracked.id))
        _wait(lambda: requests == [(tracked.id, "newdir")])
    finally:
        proc.stop()


def test_excluded_and_outside_events_ignored(
    ctx: UndoContext, tracked: RootRef, tmp_path: Path
) -> None:
    proc = _processor(ctx, tracked, [])
    proc.start()
    try:
        ex = write(tracked.path / ".git" / "objects" / "x", "blob")
        outside = write(tmp_path / "elsewhere.txt", "x")
        proc.submit(RawEvent("modified", str(ex), None, False, tracked.id))
        proc.submit(RawEvent("modified", str(outside), None, False, tracked.id))
        time.sleep(0.8)
        _wait(proc.idle)
        with ctx.db.read() as s:
            assert FileRepository(s).active_for_root(tracked.id) == []
    finally:
        proc.stop()


class _PollingOnly(PlatformAdapter):
    native_backend = "native-broken"

    def create_native_observer(self):  # type: ignore[no-untyped-def]
        raise OSError(28, "No space left on device (inotify watch limit)")


def test_polling_fallback_when_native_unavailable(ctx: UndoContext, tracked: RootRef) -> None:
    ctx.settings_store.update({"monitor": {"polling_interval_seconds": 0.5}})
    health = HealthState()
    proc = _processor(ctx, tracked, [])
    proc.start()
    mgr = WatcherManager(
        adapter=_PollingOnly(),
        processor=proc,
        settings=lambda: ctx.settings,
        health=health,
        data_dir=ctx.paths.data_dir,
        request_reconcile=lambda *_: None,
    )
    try:
        info = mgr.add_root(tracked)
        assert info.mode == "polling"
        assert any("native filesystem monitoring unavailable" in e for e in health.recent_errors)
        time.sleep(1.0)
        write(tracked.path / "polled.txt", "seen by polling")
        _wait(lambda: _versions(ctx, tracked, "polled.txt") == ["CREATE"], timeout=15)
    finally:
        mgr.stop()
        proc.stop()
