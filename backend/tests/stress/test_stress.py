"""Stress tests (`pytest -m stress`). Sizes are chosen to run in about a minute on a laptop."""

from __future__ import annotations

import os
import threading
import tracemalloc
from pathlib import Path

import pytest
from helpers import write
from undo_core.context import UndoContext
from undo_core.database.repositories import FileRepository, VersionRepository
from undo_core.service import UndoService
from undo_core.versioning.capture import CaptureStatus, RootRef

pytestmark = pytest.mark.stress


def test_thousands_of_files_and_large_directories(service: UndoService, tracked: RootRef) -> None:
    for d in range(20):
        for i in range(150):
            write(tracked.path / f"dir{d:02d}" / f"file{i:04d}.txt", f"{d}-{i}")
    rep = service.scan()[0]
    assert rep.new == 3000 and rep.failed == 0
    again = service.scan()[0]
    assert again.unchanged == 3000 and again.new == 0 and again.modified == 0
    assert service.list_files(limit=1).total == 3000


def test_duplicate_files_share_storage(service: UndoService, tracked: RootRef) -> None:
    payload = os.urandom(256 * 1024)
    for i in range(200):
        write(tracked.path / "dups" / f"copy{i}.bin", payload)
    service.scan()
    stats = service.storage_stats()
    assert stats.blob_count == 1 and stats.version_count == 200
    assert stats.dedup_savings_bytes == 199 * len(payload)


def test_many_repeated_modifications(ctx: UndoContext, tracked: RootRef) -> None:
    f = tracked.path / "hot.txt"
    for i in range(300):
        ctx.capture.capture(tracked, write(f, f"revision {i} " * (1 + i % 7)))
    with ctx.db.read() as s:
        versions = VersionRepository(s).for_file(
            FileRepository(s).active_by_path(tracked.id, "hot.txt").id
        )  # type: ignore[union-attr]
    assert len(versions) == 300
    assert ctx.store.read_bytes(versions[0].blob_hash).decode().startswith("revision 299")  # type: ignore[arg-type]


def test_concurrent_writes_and_captures(
    ctx: UndoContext, service: UndoService, tracked: RootRef
) -> None:
    errors: list[BaseException] = []

    def worker(n: int) -> None:
        try:
            for i in range(40):
                p = write(tracked.path / f"t{n}" / f"f{i % 5}.txt", f"thread {n} write {i}")
                r = ctx.capture.capture(tracked, p)
                assert r.status in (
                    CaptureStatus.CAPTURED,
                    CaptureStatus.ALREADY_STORED,
                    CaptureStatus.UNCHANGED,
                )
        except BaseException as exc:
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors, errors
    assert ctx.db.quick_check() == []
    assert service.verify_storage().healthy
    for n in range(6):
        for i in range(5):
            latest = service.resolve_file(str(tracked.path / f"t{n}" / f"f{i}.txt"))
            content = ctx.store.read_bytes(
                service.get_version(latest.latest_version_id).version.blob_hash
            )  # type: ignore[arg-type]
            assert content == (tracked.path / f"t{n}" / f"f{i}.txt").read_bytes()


def test_large_file_is_streamed(ctx: UndoContext, tracked: RootRef, tmp_path: Path) -> None:
    big = tracked.path / "large.bin"
    block = os.urandom(1024 * 1024)
    with open(big, "wb") as fh:
        for i in range(96):  # 96 MiB
            fh.write(block if i % 2 else block[::-1])
    tracemalloc.start()
    result = ctx.capture.capture(tracked, big)
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert result.status == CaptureStatus.CAPTURED
    assert peak < 32 * 1024 * 1024, f"peak Python allocation {peak} bytes: file was not streamed"
    out = tmp_path / "restored.bin"
    UndoService(ctx).restore(str(big), destination=str(out))
    assert out.stat().st_size == big.stat().st_size
    assert out.read_bytes()[:4096] == big.read_bytes()[:4096]


def test_simultaneous_restore_and_capture(
    ctx: UndoContext, service: UndoService, tracked: RootRef, tmp_path: Path
) -> None:
    for i in range(30):
        write(tracked.path / "src" / f"f{i}.txt", f"original {i}")
    service.scan()
    snap = service.create_snapshot(name="base", root=tracked.id)
    errors: list[BaseException] = []

    def mutate() -> None:
        try:
            for round_ in range(5):
                for i in range(30):
                    ctx.capture.capture(
                        tracked, write(tracked.path / "src" / f"f{i}.txt", f"r{round_} {i}")
                    )
        except BaseException as exc:
            errors.append(exc)

    def restore() -> None:
        try:
            for n in range(3):
                res = service.restore_snapshot(snap.id, destination=str(tmp_path / f"out{n}"))
                assert res.errors == 0
        except BaseException as exc:
            errors.append(exc)

    threads = [threading.Thread(target=mutate), threading.Thread(target=restore)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors, errors
    for n in range(3):
        assert (tmp_path / f"out{n}" / "src" / "f7.txt").read_text() == "original 7"
    assert service.verify_storage().healthy


def test_gc_during_activity_never_breaks_references(
    ctx: UndoContext, service: UndoService, tracked: RootRef
) -> None:
    ctx.settings_store.update({"retention": {"keep_all": False, "keep_last": 2}})
    errors: list[BaseException] = []
    stop = threading.Event()

    def collector() -> None:
        try:
            while not stop.is_set():
                service.apply_retention(dry_run=False)
                service.garbage_collect(dry_run=False, grace_seconds=0)
        except BaseException as exc:
            errors.append(exc)

    t = threading.Thread(target=collector)
    t.start()
    try:
        for i in range(150):
            ctx.capture.capture(tracked, write(tracked.path / f"g{i % 3}.txt", f"value {i % 7}"))
    finally:
        stop.set()
        t.join()
    assert not errors, errors
    report = service.verify_storage(repair=False)
    assert report.healthy, report
    for f in service.list_files().items:
        v = service.get_version(f.latest_version_id)  # type: ignore[arg-type]
        assert ctx.store.read_bytes(v.version.blob_hash) == Path(f.absolute_path).read_bytes()  # type: ignore[arg-type]
