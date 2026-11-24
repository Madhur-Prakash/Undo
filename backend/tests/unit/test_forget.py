"""Removing history on purpose: whole file, older versions, folders, single versions."""

from __future__ import annotations

from datetime import timedelta

import pytest
from helpers import write
from sqlalchemy import select
from undo_core.context import UndoContext
from undo_core.database.models import File, Version
from undo_core.service import UndoService
from undo_core.utils.errors import ConflictError, InvalidInputError
from undo_core.utils.timeutil import utcnow
from undo_core.versioning.capture import RootRef


def _three_versions(ctx: UndoContext, tracked: RootRef, name: str = "doc.txt") -> list[int]:
    f = write(tracked.path / name, "one")
    ids = [ctx.capture.capture(tracked, f).version_id]
    write(f, "two")
    ids.append(ctx.capture.capture(tracked, f).version_id)
    write(f, "three")
    ids.append(ctx.capture.capture(tracked, f).version_id)
    return ids  # type: ignore[return-value]


def test_forget_whole_file(ctx: UndoContext, service: UndoService, tracked: RootRef) -> None:
    _three_versions(ctx, tracked)
    preview = service.forget(str(tracked.path / "doc.txt"), dry_run=True)
    assert preview.dry_run and preview.versions_removed == 3 and preview.files_removed == 1
    result = service.forget(str(tracked.path / "doc.txt"))
    assert result.versions_removed == 3 and result.files_removed == 1
    with ctx.db.read() as s:
        assert s.scalars(select(Version)).first() is None
        assert s.scalars(select(File)).first() is None
    assert (tracked.path / "doc.txt").read_text() == "three"  # the file itself is untouched


def test_forget_before_keeps_latest(
    ctx: UndoContext, service: UndoService, tracked: RootRef
) -> None:
    ids = _three_versions(ctx, tracked)
    result = service.forget(str(tracked.path / "doc.txt"), before=utcnow() + timedelta(days=1))
    assert result.versions_removed == 2  # everything older, but never the latest
    with ctx.db.read() as s:
        remaining = list(s.scalars(select(Version.id)))
        file = s.scalars(select(File)).one()
    assert remaining == [ids[-1]] and file.latest_version_id == ids[-1] and file.version_count == 1


def test_forget_folder_only_touches_that_folder(
    ctx: UndoContext, service: UndoService, tracked: RootRef
) -> None:
    _three_versions(ctx, tracked, "keep/a.txt")
    _three_versions(ctx, tracked, "drop/b.txt")
    result = service.forget(str(tracked.path / "drop"))
    assert result.versions_removed == 3 and result.files_affected == 1
    with ctx.db.read() as s:
        paths = {f.relative_path for f in s.scalars(select(File))}
    assert paths == {"keep/a.txt"}


def test_delete_single_versions(ctx: UndoContext, service: UndoService, tracked: RootRef) -> None:
    ids = _three_versions(ctx, tracked)
    result = service.delete_versions([ids[1]])
    assert result.versions_removed == 1
    with ctx.db.read() as s:
        rows = {v.id: v.parent_version_id for v in s.scalars(select(Version))}
    assert set(rows) == {ids[0], ids[2]}
    assert rows[ids[2]] == ids[0]  # re-linked to the nearest kept ancestor
    with pytest.raises(InvalidInputError):
        service.delete_versions([ids[2]])  # the latest version keeps the file restorable


def test_snapshot_versions_are_kept(
    ctx: UndoContext, service: UndoService, tracked: RootRef
) -> None:
    ids = _three_versions(ctx, tracked)
    service.create_snapshot(name="pin", root=tracked.id, scan=False)  # pins ids[-1]
    f = write(tracked.path / "doc.txt", "four")
    newest = ctx.capture.capture(tracked, f).version_id
    with pytest.raises(ConflictError):
        service.delete_versions([ids[-1]])  # not the latest any more, but in the snapshot
    result = service.forget(str(tracked.path / "doc.txt"))
    assert result.versions_kept_in_snapshots == 1 and result.versions_removed == 3
    with ctx.db.read() as s:
        assert list(s.scalars(select(Version.id))) == [ids[-1]]
    assert newest not in ids
