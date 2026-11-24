from __future__ import annotations

from datetime import timedelta

from helpers import write
from sqlalchemy import select, update
from undo_core.context import UndoContext
from undo_core.database.models import Blob, Version
from undo_core.database.repositories import FileRepository, VersionRepository
from undo_core.service import UndoService
from undo_core.utils.timeutil import utcnow
from undo_core.versioning.capture import RootRef


def _make_versions(ctx: UndoContext, root: RootRef, name: str, n: int) -> list[str]:
    contents = [f"{name} version {i}" for i in range(n)]
    for c in contents:
        ctx.capture.capture(root, write(root.path / name, c))
    return contents


def _versions(ctx: UndoContext, root: RootRef, name: str) -> list[Version]:
    with ctx.db.read() as s:
        f = FileRepository(s).by_path_any(root.id, name)
        return list(VersionRepository(s).for_file(f.id))  # type: ignore[union-attr]


def test_keep_all_removes_nothing(ctx: UndoContext, service: UndoService, tracked: RootRef) -> None:
    _make_versions(ctx, tracked, "a.txt", 5)
    report = service.apply_retention(dry_run=False)
    assert report.versions_removed == 0
    assert len(_versions(ctx, tracked, "a.txt")) == 5


def test_keep_last_n_and_parent_relinking(
    ctx: UndoContext, service: UndoService, tracked: RootRef
) -> None:
    _make_versions(ctx, tracked, "a.txt", 6)
    ctx.settings_store.update({"retention": {"keep_all": False, "keep_last": 2}})
    dry = service.apply_retention(dry_run=True)
    assert dry.versions_removed == 4
    assert len(_versions(ctx, tracked, "a.txt")) == 6  # dry run changes nothing
    service.apply_retention(dry_run=False)
    kept = _versions(ctx, tracked, "a.txt")
    assert len(kept) == 2
    assert kept[0].parent_version_id == kept[1].id
    assert kept[1].parent_version_id is None


def test_latest_content_of_deleted_file_always_kept(
    ctx: UndoContext, service: UndoService, tracked: RootRef
) -> None:
    contents = _make_versions(ctx, tracked, "gone.txt", 4)
    (tracked.path / "gone.txt").unlink()
    service.scan()
    ctx.settings_store.update({"retention": {"keep_all": False, "keep_last": 1}})
    service.apply_retention(dry_run=False)
    ops = [v.operation for v in _versions(ctx, tracked, "gone.txt")]
    assert ops == ["DELETE", "MODIFY"]
    service.recover(str(tracked.path / "gone.txt"))
    assert (tracked.path / "gone.txt").read_text() == contents[-1]


def test_snapshot_versions_are_protected(
    ctx: UndoContext, service: UndoService, tracked: RootRef
) -> None:
    _make_versions(ctx, tracked, "a.txt", 2)
    snap = service.create_snapshot(name="keep-me", root=tracked.id)
    _make_versions(ctx, tracked, "a.txt", 3)
    ctx.settings_store.update({"retention": {"keep_all": False, "keep_last": 1}})
    service.apply_retention(dry_run=False)
    detail = service.get_snapshot(snap.id)
    remaining = {v.id for v in _versions(ctx, tracked, "a.txt")}
    assert all(e.version_id in remaining for e in detail.entries)


def test_keep_days_rule(ctx: UndoContext, service: UndoService, tracked: RootRef) -> None:
    _make_versions(ctx, tracked, "a.txt", 4)
    old_ids = [v.id for v in _versions(ctx, tracked, "a.txt")][2:]
    with ctx.db.write() as s:
        s.execute(
            update(Version)
            .where(Version.id.in_(old_ids))
            .values(timestamp=utcnow() - timedelta(days=30))
        )
    ctx.settings_store.update({"retention": {"keep_all": False, "keep_days": 7}})
    service.apply_retention(dry_run=False)
    assert {v.id for v in _versions(ctx, tracked, "a.txt")}.isdisjoint(old_ids)


def test_gc_only_deletes_unreferenced(
    ctx: UndoContext, service: UndoService, tracked: RootRef
) -> None:
    contents = _make_versions(ctx, tracked, "a.txt", 4)
    ctx.settings_store.update({"retention": {"keep_all": False, "keep_last": 1}})
    service.apply_retention(dry_run=False)
    dry = service.garbage_collect(dry_run=True)
    assert dry.candidate_blobs == 3 and dry.deleted_blobs == 0
    with ctx.db.read() as s:
        assert len(list(s.scalars(select(Blob)))) == 4
    real = service.garbage_collect(dry_run=False)
    assert real.deleted_blobs == 3 and real.reclaimed_bytes > 0
    with ctx.db.read() as s:
        hashes = list(s.scalars(select(Blob.hash)))
    assert len(hashes) == 1
    assert ctx.store.read_bytes(hashes[0]).decode() == contents[-1]
    assert service.verify_storage().healthy


def test_gc_respects_grace_period_and_pins(
    ctx: UndoContext, service: UndoService, tracked: RootRef
) -> None:
    _make_versions(ctx, tracked, "a.txt", 2)
    ctx.settings_store.update({"retention": {"keep_all": False, "keep_last": 1}})
    service.apply_retention(dry_run=False)
    protected = service.garbage_collect(dry_run=True, grace_seconds=3600)
    assert protected.candidate_blobs == 0 and protected.protected_by_grace == 1
    with ctx.db.read() as s:
        orphan = [
            h
            for h in s.scalars(select(Blob.hash))
            if h not in {v.blob_hash for v in s.scalars(select(Version))}
        ]
    with ctx.store.pin(orphan, "test"):
        assert service.garbage_collect(dry_run=False).deleted_blobs == 0
    assert service.garbage_collect(dry_run=False).deleted_blobs == 1


def test_storage_quota(ctx: UndoContext, service: UndoService, tracked: RootRef) -> None:
    for i in range(5):
        ctx.capture.capture(
            tracked, write(tracked.path / "big.bin", bytes([i]) * 50_000 + b"x" * i)
        )
    ctx.settings_store.update({"compression": {"enabled": False}})
    stats = service.storage_stats()
    ctx.settings_store.update(
        {"retention": {"keep_all": True, "max_storage_bytes": stats.stored_bytes // 2}}
    )
    report = service.apply_retention(dry_run=False)
    assert report.versions_removed >= 1
    assert len(_versions(ctx, tracked, "big.bin")) >= 1
