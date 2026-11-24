"""Safe restore primitives.

* Never silently overwrite: an existing different file is a conflict unless
  ``overwrite`` was requested explicitly.
* Data goes to a temporary file in the destination directory first, is
  verified against its BLAKE3 hash while being written, fsynced, and only
  then atomically moved into place.
* Metadata is restored where the platform allows it, and the result says
  exactly which metadata was and was not restored.
"""

from __future__ import annotations

import contextlib
import os
import stat
import sys
import tempfile
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

from undo_core.platform.paths import IS_WINDOWS
from undo_core.storage.blob_store import BlobStore
from undo_core.storage.content_addressing import hash_file
from undo_core.utils.atomic import fsync_dir, fsync_file, remove_quietly, rename_no_clobber
from undo_core.utils.errors import ConflictError

RESTORE_TMP_PREFIX = ".undo-restore-"


class RestoreAction(StrEnum):
    CREATE = "create"
    OVERWRITE = "overwrite"
    IDENTICAL = "identical"
    CONFLICT = "conflict"
    ERROR = "error"


@dataclass
class MetadataReport:
    restored: list[str] = field(default_factory=list)
    not_restored: list[str] = field(default_factory=list)


def plan_target(
    dest: Path, blob_hash: str, expected_size: int, *, overwrite: bool
) -> tuple[RestoreAction, str | None]:
    """Decide what restoring ``blob_hash`` to ``dest`` would do, without changing anything."""
    parent = dest.parent
    while not parent.exists():
        if parent == parent.parent:
            break
        parent = parent.parent
    if parent.exists() and not parent.is_dir():
        return RestoreAction.ERROR, f"{parent} exists and is not a directory"
    if not os.path.lexists(dest):
        return RestoreAction.CREATE, None
    if dest.is_symlink():
        if overwrite:
            return (
                RestoreAction.OVERWRITE,
                "destination is a symlink; the link itself will be replaced",
            )
        return RestoreAction.CONFLICT, "destination is a symlink"
    if dest.is_dir():
        return RestoreAction.CONFLICT, "destination is a directory"
    try:
        if dest.stat().st_size == expected_size and hash_file(dest)[0] == blob_hash:
            return RestoreAction.IDENTICAL, "destination already has this content"
    except OSError as exc:
        return RestoreAction.ERROR, f"cannot read destination: {exc}"
    if overwrite:
        return RestoreAction.OVERWRITE, None
    return RestoreAction.CONFLICT, "destination exists with different content (use overwrite)"


def _apply_metadata(path: Path, meta: dict[str, Any]) -> MetadataReport:
    report = MetadataReport()
    mode = meta.get("mode")
    if isinstance(mode, int):
        try:
            if IS_WINDOWS:
                # Only the read-only bit is meaningful on Windows; apply it after the move.
                report.restored.append("read-only flag")
            else:
                os.chmod(path, stat.S_IMODE(mode))
                report.restored.append("permissions")
        except OSError:
            report.not_restored.append("permissions")
    else:
        report.not_restored.append("permissions (not recorded)")
    mtime_ns = meta.get("mtime_ns")
    atime_ns = meta.get("atime_ns") or mtime_ns
    if isinstance(mtime_ns, int):
        try:
            os.utime(path, ns=(int(atime_ns) if isinstance(atime_ns, int) else mtime_ns, mtime_ns))
            report.restored.append("modification time")
        except OSError:
            report.not_restored.append("modification time")
    uid, gid = meta.get("uid"), meta.get("gid")
    if sys.platform != "win32" and isinstance(uid, int) and isinstance(gid, int):
        if os.geteuid() == 0:
            try:
                os.chown(path, uid, gid)
                report.restored.append("ownership")
            except OSError:
                report.not_restored.append("ownership")
        elif uid == os.geteuid():
            report.restored.append("ownership (unchanged: current user)")
        else:
            report.not_restored.append("ownership (requires root)")
    elif IS_WINDOWS:
        report.not_restored.append("owner/ACL (Windows ACLs are not captured)")
    report.not_restored.append("extended attributes / ACLs (not captured)")
    return report


def write_verified(
    store: BlobStore, blob_hash: str, dest: Path, meta: dict[str, Any], *, allow_replace: bool
) -> MetadataReport:
    """Reconstruct ``blob_hash`` into ``dest`` via a verified temp file and an atomic move."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=RESTORE_TMP_PREFIX, suffix=".tmp", dir=dest.parent)
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            store.export_to(blob_hash, handle)  # raises StorageIntegrityError on mismatch
            fsync_file(handle)
        report = _apply_metadata(tmp, meta)
        if allow_replace:
            if IS_WINDOWS and os.path.exists(dest):
                with contextlib.suppress(OSError):
                    os.chmod(dest, stat.S_IWRITE | stat.S_IREAD)
            os.replace(tmp, dest)
        elif not rename_no_clobber(tmp, dest):
            raise ConflictError(f"{dest} appeared while restoring; not overwritten")
        mode = meta.get("mode")
        if IS_WINDOWS and isinstance(mode, int) and not (mode & stat.S_IWRITE):
            with contextlib.suppress(OSError):
                os.chmod(dest, stat.S_IREAD)
        fsync_dir(dest.parent)
        return report
    finally:
        remove_quietly(tmp)
