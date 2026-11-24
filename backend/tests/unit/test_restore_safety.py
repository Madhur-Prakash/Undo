from __future__ import annotations

from pathlib import Path

from helpers import write
from sqlalchemy import select
from undo_core.context import UndoContext
from undo_core.database.models import Blob
from undo_core.recovery.restore_safety import RESTORE_TMP_PREFIX
from undo_core.service import UndoService
from undo_core.versioning.capture import RootRef


def _setup(ctx: UndoContext, tracked: RootRef) -> tuple[Path, int, int]:
    f = write(tracked.path / "doc.txt", "original")
    v1 = ctx.capture.capture(tracked, f).version_id
    write(f, "edited")
    v2 = ctx.capture.capture(tracked, f).version_id
    return f, v1, v2  # type: ignore[return-value]


def test_existing_file_is_never_silently_overwritten(
    ctx: UndoContext, service: UndoService, tracked: RootRef
) -> None:
    f, v1, _ = _setup(ctx, tracked)
    result = service.restore(str(f), version_id=v1)
    assert result.conflicts == 1 and result.created == 0
    assert f.read_text() == "edited"


def test_dry_run_changes_nothing(ctx: UndoContext, service: UndoService, tracked: RootRef) -> None:
    f, v1, _ = _setup(ctx, tracked)
    plan = service.restore(str(f), version_id=v1, overwrite=True, dry_run=True)
    assert plan.dry_run and plan.overwritten == 1
    assert f.read_text() == "edited"


def test_overwrite_preserves_current_content_first(
    ctx: UndoContext, service: UndoService, tracked: RootRef
) -> None:
    f, v1, _ = _setup(ctx, tracked)
    write(f, "unsaved work not yet captured")
    result = service.restore(str(f), version_id=v1, overwrite=True)
    assert result.overwritten == 1 and result.errors == 0
    assert f.read_text() == "original"
    assert result.pre_restore_versions, "current content must be versioned before overwrite"
    pre = service.get_version(result.pre_restore_versions[0])
    assert ctx.store.read_bytes(pre.version.blob_hash).decode() == "unsaved work not yet captured"  # type: ignore[arg-type]
    assert not [p for p in f.parent.iterdir() if p.name.startswith(RESTORE_TMP_PREFIX)]


def test_identical_destination_is_skipped(
    ctx: UndoContext, service: UndoService, tracked: RootRef
) -> None:
    f, _, v2 = _setup(ctx, tracked)
    assert service.restore(str(f), version_id=v2).identical == 1


def test_restore_to_alternate_directory(
    ctx: UndoContext, service: UndoService, tracked: RootRef, tmp_path: Path
) -> None:
    f, v1, _ = _setup(ctx, tracked)
    out = tmp_path / "out"
    out.mkdir()
    result = service.restore(str(f), version_id=v1, destination=str(out))
    assert result.created == 1
    assert (out / "doc.txt").read_text() == "original"
    assert f.read_text() == "edited"
    assert "modification time" in result.metadata_restored


def test_restore_at_time_and_before(
    ctx: UndoContext, service: UndoService, tracked: RootRef, tmp_path: Path
) -> None:
    f, v1, v2 = _setup(ctx, tracked)
    t1 = service.get_version(v1).version.timestamp
    res = service.restore(str(f), at=t1, destination=str(tmp_path / "at.txt"))
    assert (tmp_path / "at.txt").read_text() == "original" and res.items[0].version_id == v1
    service.restore(str(f), before_version_id=v2, destination=str(tmp_path / "before.txt"))
    assert (tmp_path / "before.txt").read_text() == "original"


def test_corrupt_blob_never_reaches_destination(
    ctx: UndoContext, service: UndoService, tracked: RootRef, tmp_path: Path
) -> None:
    f, v1, _ = _setup(ctx, tracked)
    digest = service.get_version(v1).version.blob_hash
    with ctx.db.read() as s:
        obj = ctx.store.abs_path(s.get(Blob, digest).storage_path)  # type: ignore[union-attr]
    data = bytearray(obj.read_bytes())
    data[-1] ^= 0x55
    obj.write_bytes(bytes(data))
    dest = tmp_path / "restore-here"
    dest.mkdir()
    result = service.restore(str(f), version_id=v1, destination=str(dest))
    assert result.errors == 1 and "verification" in (result.items[0].detail or "")
    assert list(dest.iterdir()) == []  # no partial file, no temp file left behind


def test_restore_unknown_path_is_rejected(
    service: UndoService, tracked: RootRef, tmp_path: Path
) -> None:
    import pytest
    from undo_core.utils.errors import NotFoundError, PathOutsideRootError

    with pytest.raises(PathOutsideRootError):
        service.restore(str(tmp_path / "not-tracked.txt"))
    with pytest.raises(NotFoundError):
        service.restore(str(tracked.path / "never-existed.txt"))
    _ = select
