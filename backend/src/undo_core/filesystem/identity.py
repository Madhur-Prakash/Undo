"""Filesystem identity (device + inode / NTFS file index).

Used as a *hint* for rename detection. It is never the only source of truth:
some filesystems (FAT, network shares, some FUSE mounts) report zero or
unstable inode numbers, and identities are reused after deletion.
"""

from __future__ import annotations

import os


def file_identity(st: os.stat_result) -> str | None:
    ino = getattr(st, "st_ino", 0)
    dev = getattr(st, "st_dev", 0)
    if not ino:
        return None
    return f"{dev}:{ino}"


def stat_metadata(st: os.stat_result) -> dict[str, int | float | None]:
    """Metadata stored with each version so it can be re-applied on restore."""
    return {
        "mtime_ns": st.st_mtime_ns,
        "atime_ns": st.st_atime_ns,
        "mode": st.st_mode & 0o7777,
        "uid": getattr(st, "st_uid", None) if os.name != "nt" else None,
        "gid": getattr(st, "st_gid", None) if os.name != "nt" else None,
        "attributes": getattr(st, "st_file_attributes", None),
    }
