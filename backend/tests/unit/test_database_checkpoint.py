"""The daemon's periodic WAL checkpoint must run outside a transaction."""

from __future__ import annotations

from pathlib import Path

from helpers import write
from undo_core.context import UndoContext
from undo_core.versioning.capture import RootRef


def test_checkpoint_truncates_wal(ctx: UndoContext, tracked: RootRef) -> None:
    ctx.capture.capture(tracked, write(tracked.path / "a.txt", "content"))
    result = ctx.db.checkpoint()  # raised "database table is locked" before the fix
    assert result is not None and result[0] == 0
    wal = Path(str(ctx.paths.db_path) + "-wal")
    assert not wal.exists() or wal.stat().st_size == 0


def test_program_folder_is_refused_in_installed_build(
    ctx: UndoContext, tmp_path: Path, monkeypatch
) -> None:
    import sys

    import pytest
    from undo_core.service import UndoService
    from undo_core.utils.errors import InvalidInputError

    app = tmp_path / "Programs" / "Undo"
    (app / "backend").mkdir(parents=True)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(app / "backend" / "undo.exe"))
    with pytest.raises(InvalidInputError):
        UndoService(ctx).add_root(str(app), scan=False)
