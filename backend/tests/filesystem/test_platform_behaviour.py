"""Cross-platform differences: symlinks, case sensitivity, locks, permissions, identities.

Tests adapt to what the running platform/filesystem supports instead of assuming a feature.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from helpers import write
from undo_core.context import UndoContext
from undo_core.filesystem.identity import file_identity
from undo_core.platform.paths import CASE_INSENSITIVE
from undo_core.service import UndoService
from undo_core.utils.atomic import rename_no_clobber
from undo_core.versioning.capture import CaptureStatus, RootRef


def _can_symlink(tmp: Path) -> bool:
    try:
        os.symlink(tmp / "nowhere", tmp / "probe-link")
        os.unlink(tmp / "probe-link")
        return True
    except (OSError, NotImplementedError):
        return False


def test_symlinks_not_followed_outside_root(
    ctx: UndoContext, service: UndoService, tracked: RootRef, tmp_path: Path
) -> None:
    if not _can_symlink(tmp_path):
        pytest.skip("symlinks not permitted on this system (Windows without Developer Mode?)")
    outside = write(tmp_path / "secret" / "outside.txt", "outside data")
    os.symlink(outside, tracked.path / "link-to-outside.txt")
    os.symlink(tmp_path / "secret", tracked.path / "dirlink", target_is_directory=True)
    os.symlink(tracked.path, tracked.path / "loop", target_is_directory=True)
    rep = service.scan()[0]
    assert rep.new == 0
    reasons = {s.relative_path: s.reason for s in service.skipped_files()}
    assert reasons["link-to-outside.txt"] == "symlink_not_followed"
    ctx.settings_store.update({"monitor": {"follow_symlinks": True}})
    write(tracked.path / "inside.txt", "in")
    os.symlink(tracked.path / "inside.txt", tracked.path / "link-inside.txt")
    rep = service.scan()[0]  # must terminate despite the loop
    names = {f.relative_path for f in service.list_files().items}
    assert "inside.txt" in names and "link-to-outside.txt" not in names


def test_case_sensitivity(ctx: UndoContext, service: UndoService, tracked: RootRef) -> None:
    write(tracked.path / "Readme.TXT", "v1")
    service.scan()
    if CASE_INSENSITIVE:
        # Same file regardless of spelling; a case-only rename keeps history.
        assert service.resolve_file(str(tracked.path / "readme.txt")).relative_path == "Readme.TXT"
        os.rename(tracked.path / "Readme.TXT", tracked.path / "README.txt")
        service.scan()
        f = service.resolve_file(str(tracked.path / "README.txt"))
        assert f.version_count >= 1 and service.list_files().total == 1
    else:
        write(tracked.path / "readme.txt", "different file")
        service.scan()
        assert service.list_files().total == 2


@pytest.mark.skipif(sys.platform != "win32", reason="mandatory file locks are a Windows behaviour")
def test_locked_file_reported_as_temporarily_unavailable(
    ctx: UndoContext, tracked: RootRef
) -> None:
    import msvcrt

    f = write(tracked.path / "locked.db", "x" * 1000)
    with open(f, "r+b") as fh:
        msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1000)
        try:
            result = ctx.capture.capture(tracked, f)
        finally:
            fh.seek(0)
            msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1000)
    assert result.status in (CaptureStatus.UNAVAILABLE, CaptureStatus.PERMISSION_DENIED)
    assert ctx.capture.capture(tracked, f).status == CaptureStatus.CAPTURED  # works once released


@pytest.mark.skipif(
    sys.platform == "win32" or (hasattr(os, "geteuid") and os.geteuid() == 0),
    reason="POSIX permission bits; root bypasses them",
)
def test_permission_denied_is_recorded(
    ctx: UndoContext, service: UndoService, tracked: RootRef
) -> None:
    f = write(tracked.path / "private.txt", "no access")
    os.chmod(f, 0)
    try:
        service.scan()
        reasons = {s.relative_path: s.reason for s in service.skipped_files()}
        assert reasons["private.txt"] == "permission_denied"
    finally:
        os.chmod(f, 0o644)


def test_atomic_no_clobber_rename(tmp_path: Path) -> None:
    a, b = write(tmp_path / "a", "A"), write(tmp_path / "b", "B")
    assert rename_no_clobber(a, b) is False
    assert b.read_text() == "B" and a.exists()
    c = tmp_path / "c"
    assert rename_no_clobber(a, c) is True
    assert c.read_text() == "A" and not a.exists()


def test_filesystem_identity_is_optional(tmp_path: Path) -> None:
    p = write(tmp_path / "x", "x")
    ident = file_identity(os.stat(p))
    assert ident is None or ":" in ident  # some filesystems report no inode numbers


def test_paths_with_spaces_and_unicode(
    service: UndoService, tracked: RootRef, tmp_path: Path
) -> None:
    f = write(tracked.path / "dossier été" / "résumé final (2).txt", "unicode ✓")
    service.scan()
    f.unlink()
    service.scan()
    service.recover(str(f))
    assert f.read_text(encoding="utf-8") == "unicode ✓"
