"""Version bookkeeping, capture statuses and repositories."""

from __future__ import annotations

import os

from helpers import write
from sqlalchemy import select
from undo_core.context import UndoContext
from undo_core.database.models import File, Operation, Version
from undo_core.database.repositories import FileRepository, VersionRepository
from undo_core.service import UndoService
from undo_core.versioning.capture import CaptureStatus, RootRef
from undo_core.versioning.version_manager import record_content, record_delete, record_move


def test_capture_creates_versions_only_on_change(ctx: UndoContext, tracked: RootRef) -> None:
    f = write(tracked.path / "a.txt", "one")
    r1 = ctx.capture.capture(tracked, f)
    assert r1.status == CaptureStatus.CAPTURED and r1.operation == "CREATE"
    assert ctx.capture.capture(tracked, f).status == CaptureStatus.UNCHANGED  # metadata fast path
    assert (
        ctx.capture.capture(tracked, f, force_hash=True).status == CaptureStatus.UNCHANGED
    )  # same hash
    write(f, "two")
    r2 = ctx.capture.capture(tracked, f)
    assert r2.status == CaptureStatus.CAPTURED and r2.operation == "MODIFY"
    with ctx.db.read() as s:
        versions = VersionRepository(s).for_file(
            FileRepository(s).active_by_path(tracked.id, "a.txt").id
        )  # type: ignore[union-attr]
    assert [v.operation for v in versions] == ["MODIFY", "CREATE"]
    assert versions[0].parent_version_id == versions[1].id


def test_capture_statuses_are_explicit(ctx: UndoContext, tracked: RootRef) -> None:
    ctx.settings_store.set_value("capture.max_file_size", "10")
    big = write(tracked.path / "big.txt", "x" * 100)
    assert ctx.capture.capture(tracked, big).status == CaptureStatus.TOO_LARGE
    excluded = write(tracked.path / "node_modules" / "m.js", "x")
    assert ctx.capture.capture(tracked, excluded).status == CaptureStatus.EXCLUDED
    assert (
        ctx.capture.capture(tracked, tracked.path / "missing.txt").status == CaptureStatus.NOT_FOUND
    )
    dup1 = write(tracked.path / "d1.txt", "same")
    dup2 = write(tracked.path / "d2.txt", "same")
    assert ctx.capture.capture(tracked, dup1).status == CaptureStatus.CAPTURED
    assert ctx.capture.capture(tracked, dup2).status == CaptureStatus.ALREADY_STORED
    skipped = {s.relative_path: s.reason for s in UndoService(ctx).skipped_files()}
    assert skipped["big.txt"] == "too_large"


def test_delete_and_recreate_continue_history(ctx: UndoContext, tracked: RootRef) -> None:
    f = write(tracked.path / "a.txt", "v1")
    ctx.capture.capture(tracked, f)
    with ctx.db.write() as s:
        assert len(record_delete(s, tracked.id, "a.txt")) == 1
    with ctx.db.read() as s:
        deleted = FileRepository(s).latest_deleted_by_path(tracked.id, "a.txt")
        assert deleted is not None and deleted.deleted_at is not None
        file_id = deleted.id
    write(f, "v2")
    r = ctx.capture.capture(tracked, f)
    assert r.operation == "CREATE"
    with ctx.db.read() as s:
        live = FileRepository(s).active_by_path(tracked.id, "a.txt")
        assert live is not None and live.id == file_id  # same history
        ops = [v.operation for v in VersionRepository(s).for_file(file_id)]
    assert ops == ["CREATE", "DELETE", "CREATE"]


def test_rename_reuses_blob_and_records_path_history(ctx: UndoContext, tracked: RootRef) -> None:
    f = write(tracked.path / "old.txt", "content")
    ctx.capture.capture(tracked, f)
    with ctx.db.write() as s:
        moved = record_move(s, tracked.id, "old.txt", "dir/new.txt")
    assert moved[0].operation == "MOVE"
    with ctx.db.read() as s:
        file = s.get(File, moved[0].file_id)
        versions = VersionRepository(s).for_file(file.id)  # type: ignore[union-attr]
        assert file.relative_path == "dir/new.txt"  # type: ignore[union-attr]
        assert versions[0].blob_hash == versions[1].blob_hash  # no content duplicated
        assert versions[0].meta["from_path"] == "old.txt"
        assert FileRepository(s).by_historical_path(tracked.id, "old.txt").id == file.id  # type: ignore[union-attr]


def test_directory_move_and_delete(ctx: UndoContext, tracked: RootRef) -> None:
    for name in ("a", "b", "c"):
        ctx.capture.capture(tracked, write(tracked.path / "src" / f"{name}.txt", name))
    with ctx.db.write() as s:
        assert len(record_move(s, tracked.id, "src", "lib")) == 3
    with ctx.db.read() as s:
        paths = sorted(f.relative_path for f in FileRepository(s).active_for_root(tracked.id))
    assert paths == ["lib/a.txt", "lib/b.txt", "lib/c.txt"]
    with ctx.db.write() as s:
        assert len(record_delete(s, tracked.id, "lib")) == 3
    with ctx.db.read() as s:
        assert FileRepository(s).active_for_root(tracked.id) == []


def test_record_content_unchanged_returns_existing(ctx: UndoContext, tracked: RootRef) -> None:
    f = write(tracked.path / "x.txt", "hello")
    first = ctx.capture.capture(tracked, f)
    st = os.stat(f)
    with ctx.db.write() as s:
        again = record_content(s, tracked.id, "x.txt", blob_hash=first.blob_hash, size=5, st=st)  # type: ignore[arg-type]
    assert not again.created and again.version_id == first.version_id
    with ctx.db.read() as s:
        assert len(list(s.scalars(select(Version)))) == 1
    assert Operation.DELETE == "DELETE"


def test_interrupted_capture_leaves_previous_versions(
    ctx: UndoContext, tracked: RootRef, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    f = write(tracked.path / "keep.txt", "good version")
    first = ctx.capture.capture(tracked, f)
    write(f, "new version that fails to store")

    def boom(*_a: object, **_k: object) -> None:
        raise OSError("disk full (simulated)")

    monkeypatch.setattr(ctx.store, "_publish", boom)
    result = ctx.capture.capture(tracked, f)
    assert result.status == CaptureStatus.UNAVAILABLE
    assert list(ctx.paths.staging_dir.iterdir()) == []
    with ctx.db.read() as s:
        file = FileRepository(s).active_by_path(tracked.id, "keep.txt")
        assert file is not None and file.latest_version_id == first.version_id
    assert ctx.store.read_bytes(first.blob_hash) == b"good version"  # type: ignore[arg-type]
