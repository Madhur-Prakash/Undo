"""Daemon lifecycle helpers: startup recovery, discovery file, background start/stop."""

from __future__ import annotations

import contextlib
import json
import os
import subprocess
import time
from dataclasses import asdict, dataclass
from typing import Any

import httpx
from sqlalchemy import select

from undo_core import __version__
from undo_core.config.token import read_token
from undo_core.context import UndoContext
from undo_core.daemon.locking import is_locked
from undo_core.database.models import Blob, BlobStatus, File, Version
from undo_core.domain import RecoveryInfo
from undo_core.platform.paths import IS_WINDOWS, UndoPaths
from undo_core.platform.service import daemon_command
from undo_core.utils.atomic import atomic_write_text
from undo_core.utils.errors import DaemonNotRunningError, UndoError
from undo_core.utils.logging import get_logger

log = get_logger(__name__)


# --------------------------------------------------------------------------- recovery
def startup_recovery(ctx: UndoContext) -> RecoveryInfo:
    """Repair what a crash may have left behind. Caller must hold the process lock."""
    info = RecoveryInfo()
    paths = ctx.paths
    # 1. Incomplete staging files: no other writer can be active, so all are leftovers.
    if paths.staging_dir.exists():
        for item in paths.staging_dir.iterdir():
            # Windows may keep a killed process's handle open for a moment: retry briefly.
            for attempt in range(10):
                try:
                    item.unlink()
                    info.staging_removed += 1
                    break
                except FileNotFoundError:
                    break
                except OSError as exc:
                    if attempt == 9:
                        info.issues.append(f"could not remove staging file {item.name}: {exc}")
                    else:
                        time.sleep(0.2)
    # 1b. Garbage-collection trash: restore objects whose deletion was rolled back, drop the rest.
    trash = paths.data_dir / "trash"
    if trash.exists():
        from undo_core.database.models import Chunk as _Chunk

        with ctx.db.read() as s:
            live = {b.hash: b.storage_path for b in s.scalars(select(Blob)) if b.storage_path}
            live.update({c.hash: c.storage_path for c in s.scalars(select(_Chunk))})
        for item in trash.iterdir():
            digest = item.name.split(".", 1)[0]
            rel = live.get(digest)
            try:
                if rel and not ctx.store.abs_path(rel).exists():
                    ctx.store.abs_path(rel).parent.mkdir(parents=True, exist_ok=True)
                    os.replace(item, ctx.store.abs_path(rel))
                    info.issues.append(
                        f"restored object {digest[:12]} from interrupted garbage collection"
                    )
                else:
                    item.unlink()
            except OSError as exc:
                info.issues.append(f"could not process trash file {item.name}: {exc}")
    # 2. Database consistency.
    info.database_problems = ctx.db.quick_check()
    # 3. Missing referenced objects (cheap existence check) and orphan object files.
    with ctx.db.read() as s:
        whole = {
            b.hash: b.storage_path
            for b in s.scalars(select(Blob).where(Blob.storage_kind == "whole"))
        }
        known_all = set(s.scalars(select(Blob.hash)))
        from undo_core.database.models import Chunk

        known_chunks = {c.hash: c.storage_path for c in s.scalars(select(Chunk))}
    for digest, rel in whole.items():
        if not rel or not ctx.store.abs_path(rel).exists():
            info.missing_blobs.append(digest)
    for digest, rel in known_chunks.items():
        if not ctx.store.abs_path(rel).exists():
            info.issues.append(f"chunk {digest} is missing")
    if info.missing_blobs:
        with ctx.db.write() as s:
            for digest in info.missing_blobs:
                row = s.get(Blob, digest)
                if row is not None:
                    row.status = BlobStatus.MISSING
    for kind, digest, path in ctx.store.iter_object_files():
        known = known_all if kind == "blobs" else set(known_chunks)
        if digest not in known:
            # Published but never recorded (crash between publish and commit): unreferenced.
            with contextlib.suppress(OSError):
                path.unlink()
                info.orphan_objects_removed += 1
    # 4. latest_version_id pointers that do not match the newest version.
    with ctx.db.write() as s:
        from sqlalchemy import func

        newest = dict(
            s.execute(select(Version.file_id, func.max(Version.id)).group_by(Version.file_id)).all()
        )
        for file in s.scalars(select(File)):
            want = newest.get(file.id)
            if file.latest_version_id != want:
                file.latest_version_id = want
                info.fixed_latest_pointers += 1
    if info.missing_blobs:
        info.issues.append(
            f"{len(info.missing_blobs)} stored object(s) missing; run `undo storage verify` to attempt repair"
        )
    info.ok = not info.database_problems and not info.missing_blobs
    log.info("startup recovery complete", extra=info.model_dump())
    return info


# --------------------------------------------------------------------------- discovery
@dataclass
class DaemonInfo:
    pid: int
    host: str
    port: int
    started_at: float
    version: str
    data_dir: str

    @property
    def base_url(self) -> str:
        host = f"[{self.host}]" if ":" in self.host else self.host
        return f"http://{host}:{self.port}/api/v1"


def write_daemon_info(paths: UndoPaths, host: str, port: int) -> DaemonInfo:
    info = DaemonInfo(os.getpid(), host, port, time.time(), __version__, str(paths.data_dir))
    atomic_write_text(paths.daemon_info_path, json.dumps(asdict(info), indent=2))
    return info


def read_daemon_info(paths: UndoPaths) -> DaemonInfo | None:
    try:
        data = json.loads(paths.daemon_info_path.read_text(encoding="utf-8"))
        return DaemonInfo(**{k: data[k] for k in DaemonInfo.__dataclass_fields__})
    except (OSError, ValueError, KeyError, TypeError):
        return None


def remove_daemon_info(paths: UndoPaths) -> None:
    info = read_daemon_info(paths)
    if info is not None and info.pid == os.getpid():
        with contextlib.suppress(OSError):
            paths.daemon_info_path.unlink()


def ping(info: DaemonInfo, timeout: float = 2.0) -> bool:
    try:
        r = httpx.get(f"{info.base_url}/ping", timeout=timeout)
        return r.status_code == 200 and r.json().get("app") == "undo"
    except (httpx.HTTPError, ValueError):
        return False


def discover(paths: UndoPaths) -> tuple[DaemonInfo, str] | None:
    """Return (info, token) when a healthy daemon owns this data directory."""
    info = read_daemon_info(paths)
    if info is None or not is_locked(paths.lock_path):
        return None
    if not ping(info):
        return None
    try:
        token = read_token(paths.token_path)
    except UndoError:
        return None
    return info, token


# --------------------------------------------------------------------------- start / stop
def start_background(paths: UndoPaths, *, timeout: float = 20.0) -> DaemonInfo:
    """Launch a detached daemon process and wait until it answers."""
    existing = discover(paths)
    if existing:
        return existing[0]
    if is_locked(paths.lock_path):
        raise UndoError(
            "The data directory is locked by another process but no daemon answers. "
            "Wait for the other `undo` command to finish, or check `undo logs`."
        )
    cmd = daemon_command(paths)
    kwargs: dict[str, Any] = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "close_fds": True,
        "cwd": str(paths.data_dir),
    }
    if IS_WINDOWS:
        flags = 0
        for name in ("DETACHED_PROCESS", "CREATE_NEW_PROCESS_GROUP", "CREATE_NO_WINDOW"):
            flags |= getattr(subprocess, name, 0)
        kwargs["creationflags"] = flags
    else:
        kwargs["start_new_session"] = True
    proc = subprocess.Popen(cmd, **kwargs)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        found = discover(paths)
        if found:
            return found[0]
        if proc.poll() is not None:
            raise UndoError(
                f"Daemon exited during startup (code {proc.returncode}); see `undo logs`."
            )
        time.sleep(0.25)
    raise UndoError("Daemon did not become ready in time; see `undo logs`.")


def stop_daemon(paths: UndoPaths, *, timeout: float = 30.0) -> bool:
    """Ask the daemon to shut down gracefully. Returns False if it was not running."""
    found = discover(paths)
    if not found:
        if is_locked(paths.lock_path):
            raise DaemonNotRunningError(
                "Lock is held but the daemon API does not answer; cannot stop it safely."
            )
        return False
    info, token = found
    try:
        httpx.post(
            f"{info.base_url}/daemon/shutdown",
            headers={"Authorization": f"Bearer {token}"},
            timeout=5,
        )
    except httpx.HTTPError:
        pass
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not is_locked(paths.lock_path):
            return True
        time.sleep(0.25)
    raise UndoError("Daemon did not stop within the timeout")
