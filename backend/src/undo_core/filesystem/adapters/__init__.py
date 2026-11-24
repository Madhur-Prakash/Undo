"""Platform adapters for filesystem monitoring."""

from __future__ import annotations

from undo_core.filesystem.adapters.base import PlatformAdapter
from undo_core.platform.paths import IS_LINUX, IS_WINDOWS


def get_adapter() -> PlatformAdapter:
    if IS_WINDOWS:
        from undo_core.filesystem.adapters.windows import WindowsAdapter

        return WindowsAdapter()
    if IS_LINUX:
        from undo_core.filesystem.adapters.linux import LinuxAdapter

        return LinuxAdapter()
    return PlatformAdapter()


__all__ = ["PlatformAdapter", "get_adapter"]
