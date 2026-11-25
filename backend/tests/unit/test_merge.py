"""Resolving a restore like a merge conflict, comparing with the disk, drafts, snapshot names."""

from __future__ import annotations

import pytest
from helpers import write
from undo_core.context import UndoContext
from undo_core.service import UndoService
from undo_core.utils.errors import ConflictError, PathOutsideRootError
from undo_core.versioning.capture import RootRef


def _old_and_new(ctx: UndoContext, tracked: RootRef) -> tuple[int, int]:
    f = tracked.path / "notes.txt"
    f.write_bytes(b"title\r\nkeep\r\nold line\r\n")
    old = ctx.capture.capture(tracked, f, force_hash=True).version_id
    f.write_bytes(b"title\r\nkeep\r\nnew line\r\nadded\r\n")
    new = ctx.capture.capture(tracked, f, force_hash=True).version_id
    return old, new  # type: ignore[return-value]


def test_diff_with_file_compares_disk_and_version(
    ctx: UndoContext, service: UndoService, tracked: RootRef
) -> None:
    old, _ = _old_and_new(ctx, tracked)
    d = service.diff_version_with_file(old)
    assert d.exists and not d.identical and d.hunks
    assert (d.added, d.removed) == (1, 2)  # restoring `old` adds 1 line and removes 2


def test_merge_source_lines_and_hunks(
    ctx: UndoContext, service: UndoService, tracked: RootRef
) -> None:
    old, _ = _old_and_new(ctx, tracked)
    src = service.merge_source(old)
    assert src.current_lines == ["title", "keep", "new line", "added"]
    assert src.version_lines == ["title", "keep", "old line"]
    assert src.line_ending == "CRLF" and src.hunks and not src.identical


def test_merge_write_keeps_line_endings_and_saves_current_first(
    ctx: UndoContext, service: UndoService, tracked: RootRef
) -> None:
    old, new = _old_and_new(ctx, tracked)
    src = service.merge_source(old)
    result = service.merge_write(
        path=src.path,
        text="title\nkeep\nold line\nadded",
        version_id=old,
        expected_hash=src.current_hash,
    )
    assert (tracked.path / "notes.txt").read_bytes() == b"title\r\nkeep\r\nold line\r\nadded\r\n"
    assert result.pre_restore_version_id == new  # the replaced content is a version
    assert result.version_id is not None and result.version_id != new


def test_merge_write_refuses_if_file_changed(
    ctx: UndoContext, service: UndoService, tracked: RootRef
) -> None:
    old, _ = _old_and_new(ctx, tracked)
    src = service.merge_source(old)
    write(tracked.path / "notes.txt", "someone else edited this")
    with pytest.raises(ConflictError):
        service.merge_write(path=src.path, text="x", version_id=old, expected_hash=src.current_hash)


def test_merge_outside_tracked_folder_is_refused(
    ctx: UndoContext, service: UndoService, tracked: RootRef, tmp_path
) -> None:  # type: ignore[no-untyped-def]
    old, _ = _old_and_new(ctx, tracked)
    with pytest.raises(PathOutsideRootError):
        service.merge_source(old, str(tmp_path / "elsewhere.txt"))


def test_drafts_save_resume_and_clear_on_restore(
    ctx: UndoContext, service: UndoService, tracked: RootRef
) -> None:
    old, _ = _old_and_new(ctx, tracked)
    path = str(tracked.path / "notes.txt")
    service.save_merge_draft(
        path=path, version_id=old, text="half done", choices={"0": "version"}, edited=True
    )
    assert service.merge_source(old).draft is not None
    assert [d.path for d in service.list_merge_drafts()] == [path]
    service.restore_version(old, overwrite=True)  # restoring the file clears its draft
    assert service.list_merge_drafts() == []


def test_snapshot_names_match_loosely(
    ctx: UndoContext, service: UndoService, tracked: RootRef
) -> None:
    _old_and_new(ctx, tracked)
    service.create_snapshot(name="try 1", root=tracked.id, scan=False)
    for ref in ("try 1", "try1", "TRY-1", "1"):
        assert service.get_snapshot(ref).snapshot.name == "try 1"


def test_rename_snapshot(ctx: UndoContext, service: UndoService, tracked: RootRef) -> None:
    _old_and_new(ctx, tracked)
    service.create_snapshot(name="try 1", root=tracked.id, scan=False)
    service.create_snapshot(name="other", root=tracked.id, scan=False)
    info = service.rename_snapshot("try1", name="before refactor", description="safe point")
    assert info.name == "before refactor" and info.description == "safe point"
    assert service.get_snapshot("before refactor").snapshot.id == info.id
    with pytest.raises(ConflictError):
        service.rename_snapshot(info.id, name="other")  # names are unique per folder
