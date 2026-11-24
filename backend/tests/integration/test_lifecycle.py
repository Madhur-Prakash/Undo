"""End-to-end behaviour through the service layer (what the CLI, TUI and GUI use)."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest
from helpers import write
from undo_core.service import UndoService
from undo_core.utils.errors import ConflictError, InvalidInputError
from undo_core.utils.timeutil import utcnow
from undo_core.versioning.capture import RootRef

pytestmark = pytest.mark.integration


def _ops(service: UndoService, path: Path) -> list[str]:
    return [v.operation for v in service.file_history(path=str(path)).versions]


def test_create_modify_delete_rename_move(service: UndoService, tracked: RootRef) -> None:
    root = tracked.path
    a = write(root / "a.txt", "1")
    service.scan()
    write(a, "2")
    service.scan()
    assert _ops(service, a) == ["MODIFY", "CREATE"]

    os.rename(a, root / "renamed.txt")
    rep = service.scan()[0]
    assert rep.renamed == 1 and rep.deleted == 0 and rep.new == 0
    assert _ops(service, root / "renamed.txt") == ["RENAME", "MODIFY", "CREATE"]

    (root / "sub").mkdir()
    shutil.move(str(root / "renamed.txt"), str(root / "sub" / "moved.txt"))
    service.scan()
    hist = service.file_history(path=str(root / "sub" / "moved.txt"))
    assert hist.versions[0].operation == "MOVE"
    assert [p.relative_path for p in hist.paths] == ["a.txt", "renamed.txt", "sub/moved.txt"]
    # search finds the file by any historical name
    assert service.search("renamed")[0].file.relative_path == "sub/moved.txt"

    (root / "sub" / "moved.txt").unlink()
    rep = service.scan()[0]
    assert rep.deleted == 1
    assert service.deleted_files()[0].relative_path == "sub/moved.txt"


def test_recover_deleted_file(service: UndoService, tracked: RootRef) -> None:
    f = write(tracked.path / "important.docx.txt", "precious")
    service.scan()
    f.unlink()
    service.scan()
    result = service.recover(str(f))
    assert result.created == 1
    assert f.read_text() == "precious"


def test_restore_previous_version(service: UndoService, tracked: RootRef) -> None:
    f = write(tracked.path / "notes.md", "draft 1")
    service.scan()
    write(f, "draft 2 (overwritten by mistake)")
    service.scan()
    old = service.file_history(path=str(f)).versions[-1]
    service.restore(str(f), version_id=old.id, overwrite=True)
    assert f.read_text() == "draft 1"


def test_directory_restore_to_point_in_time(
    service: UndoService, tracked: RootRef, tmp_path: Path
) -> None:
    root = tracked.path
    write(root / "proj" / "a.txt", "a1")
    write(root / "proj" / "b.txt", "b1")
    write(root / "other.txt", "unrelated")
    service.scan()
    checkpoint = utcnow()
    write(root / "proj" / "a.txt", "a2")
    (root / "proj" / "b.txt").unlink()
    write(root / "proj" / "c.txt", "new file")
    write(root / "other.txt", "unrelated changed")
    service.scan()

    plan = service.restore(str(root / "proj"), at=checkpoint, dry_run=True)
    actions = {Path(i.destination).name: i.action for i in plan.items}
    assert actions == {"a.txt": "conflict", "b.txt": "create"}

    result = service.restore(str(root / "proj"), at=checkpoint, overwrite=True)
    assert result.created == 1 and result.overwritten == 1
    assert (root / "proj" / "a.txt").read_text() == "a1"
    assert (root / "proj" / "b.txt").read_text() == "b1"
    assert (root / "proj" / "c.txt").exists()  # files that did not exist then are left alone
    assert (root / "other.txt").read_text() == "unrelated changed"  # unrelated files untouched

    out = tmp_path / "copy"
    service.restore(str(root / "proj"), at=checkpoint, destination=str(out))
    assert sorted(p.name for p in out.iterdir()) == ["a.txt", "b.txt"]


def test_snapshots(service: UndoService, tracked: RootRef, tmp_path: Path) -> None:
    root = tracked.path
    write(root / "x.txt", "x1")
    write(root / "y.txt", "y1")
    s1 = service.create_snapshot(name="before-upgrade", root=tracked.id, description="baseline")
    assert s1.file_count == 2
    with pytest.raises(ConflictError):
        service.create_snapshot(name="before-upgrade", root=tracked.id)
    write(root / "x.txt", "x2")
    (root / "y.txt").unlink()
    write(root / "z.txt", "z1")
    s2 = service.create_snapshot(name="after-upgrade", root=str(root))
    diff = service.diff_snapshots(s1.id, "after-upgrade")
    assert [c.relative_path for c in diff.added] == ["z.txt"]
    assert [c.relative_path for c in diff.removed] == ["y.txt"]
    assert [c.relative_path for c in diff.modified] == ["x.txt"]
    assert service.get_snapshot("before-upgrade").snapshot.id == s1.id
    assert {s.name for s in service.list_snapshots()} == {"before-upgrade", "after-upgrade"}

    res = service.restore_snapshot(s1.id, overwrite=True)
    assert res.errors == 0
    assert (root / "x.txt").read_text() == "x1" and (root / "y.txt").read_text() == "y1"
    assert (root / "z.txt").exists()  # not part of the snapshot: untouched

    out = tmp_path / "snapcopy"
    service.restore_snapshot(s2.id, destination=str(out))
    assert sorted(p.name for p in out.iterdir()) == ["x.txt", "z.txt"]
    service.delete_snapshot(s2.id)
    assert [s.name for s in service.list_snapshots()] == ["before-upgrade"]


def test_reconcile_catches_offline_changes(service: UndoService, tracked: RootRef) -> None:
    root = tracked.path
    for i in range(20):
        write(root / "d" / f"f{i}.txt", f"v{i}")
    service.scan()
    # "daemon offline": change things behind Undo's back
    write(root / "d" / "f0.txt", "changed while offline")
    (root / "d" / "f1.txt").unlink()
    os.rename(root / "d" / "f2.txt", root / "d" / "f2-renamed.txt")
    write(root / "d" / "brand-new.txt", "hi")
    rep = service.scan()[0]
    assert (rep.new, rep.modified, rep.deleted, rep.renamed) == (1, 1, 1, 1)
    deep = service.scan(deep=True)[0]
    assert deep.modified == 0 and deep.new == 0  # nothing missed


def test_scan_with_unavailable_root_records_no_deletions(
    service: UndoService, tracked: RootRef, tmp_path: Path
) -> None:
    write(tracked.path / "a.txt", "a")
    service.scan()
    moved_away = tmp_path / "unmounted"
    os.rename(tracked.path, moved_away)
    rep = service.scan()[0]
    assert rep.errors and rep.deleted == 0
    os.rename(moved_away, tracked.path)
    assert service.list_files().total == 1


def test_roots_management(service: UndoService, tracked: RootRef, tmp_path: Path) -> None:
    with pytest.raises(ConflictError):
        service.add_root(str(tracked.path))
    with pytest.raises(ConflictError):
        service.add_root(
            str(tracked.path / "nested") if (tracked.path / "nested").mkdir() is None else ""
        )
    with pytest.raises(InvalidInputError):
        service.add_root(str(service.ctx.paths.data_dir))
    write(tracked.path / "a.txt", "a")
    service.scan()
    service.remove_root(tracked.id)  # keeps history
    assert not service.list_roots()[0].enabled
    assert service.list_files().total == 1
    service.remove_root(tracked.id, purge=True)
    assert service.list_roots() == [] and service.list_files(include_deleted=True).total == 0
    assert service.garbage_collect(dry_run=False).deleted_blobs == 1


def test_exclusions_and_settings(service: UndoService, tracked: RootRef) -> None:
    write(tracked.path / "keep.txt", "k")
    write(tracked.path / "build" / "out.o", "o")
    write(tracked.path / "debug.log", "l")
    write(tracked.path / "node_modules" / "x.js", "x")
    service.add_exclusion("build/")
    service.add_exclusion("*.log", root=tracked.id)
    rep = service.scan()[0]
    names = {f.relative_path for f in service.list_files().items}
    assert names == {"keep.txt"}
    assert rep.skip_reasons.get("excluded", 0) >= 3
    sources = {e.pattern: e.source for e in service.list_exclusions()}
    assert sources["build/"] == "user" and sources[".git/"] == "default"
    service.remove_exclusion("node_modules/")  # a default pattern
    service.remove_exclusion("build/")
    service.scan()
    names = {f.relative_path for f in service.list_files().items}
    assert names == {"keep.txt", "build/out.o", "node_modules/x.js"}
    data = service.set_setting("compression.level", "9")
    assert data["compression"]["level"] == 9


def test_storage_stats_reflect_dedup_and_compression(
    service: UndoService, tracked: RootRef
) -> None:
    text = "the same paragraph repeated " * 2000
    for i in range(3):
        write(tracked.path / f"copy{i}.txt", text)
    service.scan()
    stats = service.storage_stats()
    assert stats.blob_count == 1 and stats.version_count == 3
    assert stats.dedup_savings_bytes == 2 * len(text)
    assert stats.compression_savings_bytes > 0
    assert stats.stored_bytes < len(text)
    report = service.verify_storage()
    assert report.healthy and report.checked_blobs == 1
