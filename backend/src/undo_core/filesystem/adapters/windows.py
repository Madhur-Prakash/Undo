"""Windows adapter: ReadDirectoryChangesW via watchdog, optional USN journal probe.

ReadDirectoryChangesW buffers can overflow under heavy load (watchdog then
loses events silently); periodic reconciliation covers that gap.

USN journal: :func:`query_usn_journal` probes whether the NTFS change journal
is enabled and readable for a volume. Opening a volume handle normally needs
administrator rights, so this is reported as an optional capability only.
Reconciliation does not depend on it; it uses directory scanning, which works
on every filesystem (NTFS, ReFS, FAT, network shares).
"""

from __future__ import annotations

import ctypes
import os
from pathlib import Path
from typing import Any

from undo_core.filesystem.adapters.base import PlatformAdapter

FSCTL_QUERY_USN_JOURNAL = 0x000900F4
GENERIC_READ = 0x80000000
FILE_SHARE_READ = 0x1
FILE_SHARE_WRITE = 0x2
OPEN_EXISTING = 3
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value


class _USN_JOURNAL_DATA_V0(ctypes.Structure):
    _fields_ = [
        ("UsnJournalID", ctypes.c_ulonglong),
        ("FirstUsn", ctypes.c_longlong),
        ("NextUsn", ctypes.c_longlong),
        ("LowestValidUsn", ctypes.c_longlong),
        ("MaxUsn", ctypes.c_longlong),
        ("MaximumSize", ctypes.c_ulonglong),
        ("AllocationDelta", ctypes.c_ulonglong),
    ]


def query_usn_journal(path: Path) -> dict[str, Any] | None:
    """Return USN journal info for the volume containing ``path``, or None if unavailable."""
    if os.name != "nt":
        return None
    drive = os.path.splitdrive(str(path))[0]
    if not drive or not drive.endswith(":"):
        return None
    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined]
        kernel32.CreateFileW.restype = ctypes.c_void_p
        handle = kernel32.CreateFileW(
            f"\\\\.\\{drive}",
            GENERIC_READ,
            FILE_SHARE_READ | FILE_SHARE_WRITE,
            None,
            OPEN_EXISTING,
            0,
            None,
        )
        if handle in (None, INVALID_HANDLE_VALUE):
            return None
        try:
            data = _USN_JOURNAL_DATA_V0()
            returned = ctypes.c_ulong(0)
            ok = kernel32.DeviceIoControl(
                ctypes.c_void_p(handle),
                FSCTL_QUERY_USN_JOURNAL,
                None,
                0,
                ctypes.byref(data),
                ctypes.sizeof(data),
                ctypes.byref(returned),
                None,
            )
            if not ok:
                return None
            return {
                "journal_id": int(data.UsnJournalID),
                "next_usn": int(data.NextUsn),
                "max_size": int(data.MaximumSize),
            }
        finally:
            kernel32.CloseHandle(ctypes.c_void_p(handle))
    except (OSError, AttributeError):
        return None


class WindowsAdapter(PlatformAdapter):
    name = "windows"
    native_backend = "ReadDirectoryChangesW"

    def is_capacity_error(self, exc: BaseException) -> bool:
        return isinstance(exc, OSError) and getattr(exc, "winerror", None) in (8, 1450)

    def capacity_hint(self, root: Path) -> str | None:
        return "insufficient system resources for directory monitoring; using polling for this root"

    def info(self) -> dict[str, Any]:
        system_drive = Path(os.environ.get("SYSTEMDRIVE", "C:") + "\\")
        usn = query_usn_journal(system_drive)
        return {
            **super().info(),
            "usn_journal_available": usn is not None,
            "usn_journal_note": "USN probing needs administrator rights; reconciliation uses scanning",
        }
