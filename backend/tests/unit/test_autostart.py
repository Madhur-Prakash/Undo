"""Windows autostart: the per-user Run key (no administrator rights needed)."""

from __future__ import annotations

import sys
import uuid
from pathlib import Path

import pytest
from undo_core.platform import service
from undo_core.platform.paths import UndoPaths

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows Run key")


def test_install_status_uninstall_without_admin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A throwaway value name, so the real "Undo" entry is never touched.
    monkeypatch.setattr(service, "RUN_VALUE", f"Undo test {uuid.uuid4().hex[:8]}")
    paths = UndoPaths.resolve(tmp_path / "data")
    try:
        result = service._install_task(paths, start_now=False)
        assert result.ok, result.message
        command = service._run_key_get()
        assert command is not None and "--data-dir" in command and str(paths.data_dir) in command
        assert "installed" in service.autostart_status()
        assert service._uninstall_task().ok
        assert service._run_key_get() is None
        assert "not installed" in service.autostart_status()
        assert service._uninstall_task().message == "Autostart was not installed"
    finally:
        service._run_key_delete()
