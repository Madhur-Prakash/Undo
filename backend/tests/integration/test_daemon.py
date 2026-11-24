"""Real daemon: watcher events, local API, authentication, single ownership, restart recovery."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from helpers import write
from undo_core.context import UndoContext
from undo_core.daemon.lifecycle import discover, read_daemon_info
from undo_core.daemon.locking import ProcessLock, is_locked
from undo_core.daemon.manager import DaemonManager
from undo_core.platform.paths import UndoPaths
from undo_core.utils.errors import LockedError

pytestmark = pytest.mark.integration


def wait_for(predicate: Callable[[], Any], timeout: float = 20.0, interval: float = 0.2) -> Any:
    deadline = time.monotonic() + timeout
    last: Any = None
    while time.monotonic() < deadline:
        try:
            last = predicate()
            if last:
                return last
        except Exception:
            pass
        time.sleep(interval)
    raise AssertionError(f"condition not met within {timeout}s (last={last!r})")


class RunningDaemon:
    def __init__(self, data_dir: Path) -> None:
        self.manager = DaemonManager(data_dir)
        self.thread = threading.Thread(target=self.manager.run, daemon=True)

    def start(self) -> RunningDaemon:
        self.thread.start()
        assert self.manager.wait_started(30), "daemon did not start"
        return self

    def stop(self) -> None:
        self.manager.request_stop()
        self.thread.join(30)
        assert not self.thread.is_alive()

    def client(self) -> httpx.Client:
        found = discover(self.manager.paths)
        assert found, "daemon not discoverable"
        info, token = found
        return httpx.Client(
            base_url=info.base_url, headers={"Authorization": f"Bearer {token}"}, timeout=60
        )


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    d = tmp_path / "data"
    ctx = UndoContext.open(d, require_initialized=False)
    ctx.initialize()
    ctx.settings_store.update(
        {
            "capture": {"stable_seconds": 0.1, "debounce_seconds": 0.3, "retry_seconds": 0.1},
            "api": {"port": 0},
            "monitor": {"polling_interval_seconds": 1.0},
        }
    )
    ctx.close()
    return d


@pytest.fixture
def daemon(data_dir: Path) -> Iterator[RunningDaemon]:
    d = RunningDaemon(data_dir).start()
    yield d
    if d.thread.is_alive():
        d.stop()


def _history_ops(client: httpx.Client, path: Path) -> list[str]:
    r = client.get("/history/path", params={"path": str(path)})
    return [v["operation"] for v in r.json()["versions"]] if r.status_code == 200 else []


def test_api_requires_token_and_is_loopback(daemon: RunningDaemon) -> None:
    info = read_daemon_info(daemon.manager.paths)
    assert info is not None and info.host in ("127.0.0.1", "::1")
    assert httpx.get(f"{info.base_url}/ping").json()["app"] == "undo"
    assert httpx.get(f"{info.base_url}/status").status_code == 401
    bad = httpx.get(f"{info.base_url}/status", headers={"Authorization": "Bearer wrong"})
    assert bad.status_code == 401 and bad.json()["error"]["code"] == "unauthorized"
    with daemon.client() as c:
        status = c.get("/status").json()
        assert status["daemon_running"] and status["daemon"]["pid"] > 0
        err = c.get("/files/999999")
        assert err.status_code == 404 and err.json()["error"]["code"] == "not_found"
        assert c.post("/roots", json={}).status_code == 422


def test_single_daemon_ownership(daemon: RunningDaemon) -> None:
    assert is_locked(daemon.manager.paths.lock_path)
    with pytest.raises(LockedError):
        ProcessLock(daemon.manager.paths.lock_path).acquire()
    with pytest.raises(LockedError):
        DaemonManager(daemon.manager.paths.data_dir).run()


def test_watcher_captures_live_changes(daemon: RunningDaemon, tmp_path: Path) -> None:
    root = tmp_path / "watched"
    root.mkdir()
    with daemon.client() as c:
        assert c.post("/roots", json={"path": str(root), "scan": True}).status_code == 201
        wait_for(lambda: c.get("/roots").json()[0]["last_scan_at"])
        f = root / "live.txt"
        f.write_text("first")
        wait_for(lambda: _history_ops(c, f) == ["CREATE"])
        time.sleep(0.3)
        f.write_text("second, longer")
        wait_for(lambda: _history_ops(c, f) == ["MODIFY", "CREATE"])
        f.rename(root / "renamed.txt")
        wait_for(lambda: _history_ops(c, root / "renamed.txt")[:1] == ["RENAME"])
        (root / "renamed.txt").unlink()
        wait_for(lambda: c.get("/files/deleted").json())
        r = c.post("/restore/recover", json={"path": str(root / "renamed.txt")}).json()
        assert r["created"] == 1
        assert (root / "renamed.txt").read_text() == "second, longer"
        health = c.get("/health").json()
        assert health["watchers"][0]["healthy"]


def test_restart_reconciles_changes_made_while_stopped(data_dir: Path, tmp_path: Path) -> None:
    root = tmp_path / "watched"
    root.mkdir()
    write(root / "a.txt", "v1")
    d1 = RunningDaemon(data_dir).start()
    with d1.client() as c:
        c.post("/roots", json={"path": str(root), "scan": True})
        wait_for(lambda: _history_ops(c, root / "a.txt") == ["CREATE"])
    d1.stop()
    assert not is_locked(UndoPaths.resolve(data_dir).lock_path)
    assert read_daemon_info(UndoPaths.resolve(data_dir)) is None  # discovery file removed

    write(root / "a.txt", "v2 written while daemon was down")
    write(root / "b.txt", "new while down")
    (root / "staging-leftover").write_text("noise")
    (UndoPaths.resolve(data_dir).staging_dir / "obj-crashed.part").write_bytes(b"half written")

    d2 = RunningDaemon(data_dir).start()
    try:
        with d2.client() as c:
            wait_for(lambda: _history_ops(c, root / "a.txt") == ["MODIFY", "CREATE"])
            wait_for(lambda: _history_ops(c, root / "b.txt") == ["CREATE"])
            recovery = c.get("/health").json()["recovery"]
            assert recovery["staging_removed"] == 1
            assert not list(UndoPaths.resolve(data_dir).staging_dir.iterdir())
    finally:
        d2.stop()


def test_cli_uses_daemon_when_running(daemon: RunningDaemon, tmp_path: Path) -> None:
    from typer.testing import CliRunner
    from undo_cli.main import app

    root = tmp_path / "cli-root"
    root.mkdir()
    write(root / "f.txt", "hello")
    runner = CliRunner()
    base = ["--data-dir", str(daemon.manager.paths.data_dir)]
    r = runner.invoke(app, [*base, "track", str(root), "--json"])
    assert r.exit_code == 0, r.output
    r = runner.invoke(app, [*base, "status", "--json"])
    assert r.exit_code == 0 and '"daemon_running": true' in r.output
    with daemon.client() as c:
        wait_for(lambda: _history_ops(c, root / "f.txt") == ["CREATE"])
    r = runner.invoke(app, [*base, "history", str(root / "f.txt"), "--json"])
    assert r.exit_code == 0 and '"CREATE"' in r.output
