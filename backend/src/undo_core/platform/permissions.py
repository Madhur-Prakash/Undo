"""Restricting access to secrets (API token) and checking file accessibility."""

from __future__ import annotations

import getpass
import os
import stat
import subprocess
from pathlib import Path

from undo_core.platform.paths import IS_WINDOWS
from undo_core.utils.logging import get_logger

log = get_logger(__name__)


def secure_file(path: Path) -> bool:
    """Make ``path`` readable/writable only by the current user. Returns True on success."""
    if not IS_WINDOWS:
        try:
            os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
            return True
        except OSError as exc:
            log.warning("could not chmod secret file", extra={"path": str(path), "error": str(exc)})
            return False
    try:
        user = os.environ.get("USERNAME") or getpass.getuser()
        domain = os.environ.get("USERDOMAIN")
        principal = f"{domain}\\{user}" if domain else user
        result = subprocess.run(
            ["icacls", str(path), "/inheritance:r", "/grant:r", f"{principal}:F"],
            capture_output=True,
            text=True,
            timeout=30,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if result.returncode != 0:
            log.warning(
                "icacls failed to restrict token file",
                extra={"path": str(path), "stderr": result.stderr.strip()},
            )
            return False
        return True
    except (OSError, subprocess.SubprocessError) as exc:
        log.warning("could not restrict token ACL", extra={"path": str(path), "error": str(exc)})
        return False


def secure_dir(path: Path) -> None:
    if not IS_WINDOWS:
        try:
            os.chmod(path, stat.S_IRWXU)
        except OSError as exc:
            log.warning("could not chmod data dir", extra={"path": str(path), "error": str(exc)})


def describe_permissions(path: Path) -> str:
    try:
        st = path.stat()
    except OSError as exc:
        return f"unavailable ({exc.strerror})"
    if IS_WINDOWS:
        return "ACL (see icacls)"
    return oct(stat.S_IMODE(st.st_mode))


def can_read(path: Path) -> bool:
    return os.access(path, os.R_OK)
