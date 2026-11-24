"""Crash recovery: interrupted captures, killed processes, missing/corrupt objects."""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
import time
from pathlib import Path

from helpers import write
from sqlalchemy import select
from undo_core.context import UndoContext
from undo_core.daemon.lifecycle import startup_recovery
from undo_core.database.models import Blob, BlobStatus, File
from undo_core.service import UndoService
from undo_core.storage.content_addressing import object_relpath
from undo_core.versioning.capture import RootRef


def test_startup_recovery_cleans_and_flags(
    ctx: UndoContext, service: UndoService, tracked: RootRef
) -> None:
    f = write(tracked.path / "a.txt", "content a")
    service.scan()
    # leftovers of a crash
    (ctx.paths.staging_dir / "obj-123.part").write_bytes(b"partial")
    orphan_hash = "ab" * 32
    orphan = ctx.store.abs_path(object_relpath("blobs", orphan_hash, ".zst"))
    orphan.parent.mkdir(parents=True, exist_ok=True)
    orphan.write_bytes(b"published but never committed")
    # a referenced object disappears
    digest = service.resolve_file(str(f)).latest_version_id
    blob_hash = service.get_version(digest).version.blob_hash  # type: ignore[arg-type]
    with ctx.db.read() as s:
        ctx.store.abs_path(s.get(Blob, blob_hash).storage_path).unlink()  # type: ignore[union-attr]
    # a broken latest pointer
    with ctx.db.write() as s:
        s.get(File, service.resolve_file(str(f)).id).latest_version_id = None  # type: ignore[union-attr]

    info = startup_recovery(ctx)
    assert info.staging_removed == 1
    assert info.orphan_objects_removed == 1 and not orphan.exists()
    assert info.missing_blobs == [blob_hash]
    assert info.fixed_latest_pointers == 1
    assert not info.ok
    with ctx.db.read() as s:
        assert s.get(Blob, blob_hash).status == BlobStatus.MISSING  # type: ignore[union-attr]
    # verification repairs the blob from the unchanged live file
    report = service.verify_storage()
    assert report.repaired == [blob_hash] and report.healthy
    assert ctx.store.read_bytes(blob_hash) == b"content a"  # type: ignore[arg-type]


def test_killed_process_during_blob_creation(
    ctx: UndoContext, tracked: RootRef, tmp_path: Path
) -> None:
    big = tracked.path / "big.bin"
    big.write_bytes(os.urandom(1024 * 1024) * 40)  # 40 MiB, compressible
    script = textwrap.dedent(
        f"""
        import os, sys
        from pathlib import Path
        from undo_core.context import UndoContext
        from undo_core.versioning.capture import RootRef
        ctx = UndoContext.open(r"{ctx.paths.data_dir}")
        print("ready", flush=True)
        ctx.capture.capture(RootRef({tracked.id}, Path(r"{tracked.path}")), Path(r"{big}"))
        print("done", flush=True)
        """
    )
    proc = subprocess.Popen([sys.executable, "-c", script], stdout=subprocess.PIPE, text=True)
    assert proc.stdout is not None
    assert proc.stdout.readline().strip() == "ready"
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline and not any(ctx.paths.staging_dir.iterdir()):
        time.sleep(0.01)
    proc.kill()
    proc.wait(30)

    info = startup_recovery(ctx)
    assert info.ok
    assert not list(ctx.paths.staging_dir.iterdir())
    assert ctx.db.quick_check() == []
    with ctx.db.read() as s:
        files = list(s.scalars(select(File)))
        blobs = list(s.scalars(select(Blob)))
    # Either nothing was recorded, or a complete, verifiable version was.
    for blob in blobs:
        assert ctx.store.verify_blob(blob.hash) is None
    assert len(files) <= 1
    # Capture works normally afterwards.
    result = ctx.capture.capture(tracked, big)
    assert result.status.value in ("captured", "already_stored", "unchanged")
    assert UndoService(ctx).verify_storage().healthy


def test_database_survives_concurrent_readers_and_writer(
    ctx: UndoContext, service: UndoService, tracked: RootRef
) -> None:
    import threading

    errors: list[BaseException] = []
    stop = threading.Event()

    def reader() -> None:
        while not stop.is_set():
            try:
                service.status()
                service.list_files(limit=50)
            except BaseException as exc:  # pragma: no cover - reported below
                errors.append(exc)

    threads = [threading.Thread(target=reader) for _ in range(3)]
    for t in threads:
        t.start()
    for i in range(60):
        ctx.capture.capture(tracked, write(tracked.path / f"f{i % 10}.txt", f"v{i}"))
    stop.set()
    for t in threads:
        t.join()
    assert not errors
    assert ctx.db.quick_check() == []
