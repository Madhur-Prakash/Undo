"""Autostart integration.

Linux:   systemd unit (``--user`` by default, no root needed; ``system`` scope
         installs ``undo@.service`` running as a named user).
Windows: a per-user Scheduled Task that starts the daemon at logon (no admin
         needed), or a real Windows service via pywin32 (``services/windows``),
         which requires administrator rights.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from undo_core.platform.paths import IS_LINUX, IS_WINDOWS, UndoPaths
from undo_core.utils.errors import UndoError

TASK_NAME = "Undo Daemon"
UNIT_NAME = "undo.service"


@dataclass(frozen=True)
class ServiceResult:
    ok: bool
    message: str
    path: str | None = None


def _run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=60,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if IS_WINDOWS else 0,
    )


def daemon_command(paths: UndoPaths) -> list[str]:
    """The command that runs the daemon in the foreground.

    In a frozen build (the Windows installer) the daemon is the windowless
    ``undo-daemon`` executable next to ``undo``; otherwise it is this Python
    running ``-m undo_core.daemon`` (``pythonw`` on Windows, so no console opens).
    """
    if getattr(sys, "frozen", False):
        name = "undo-daemon.exe" if IS_WINDOWS else "undo-daemon"
        return [str(Path(sys.executable).with_name(name)), "--data-dir", str(paths.data_dir)]
    exe = sys.executable
    if IS_WINDOWS:
        pythonw = Path(exe).with_name("pythonw.exe")
        if pythonw.exists():
            exe = str(pythonw)
    return [exe, "-m", "undo_core.daemon", "--data-dir", str(paths.data_dir)]


# --------------------------------------------------------------------------- systemd
def systemd_unit(paths: UndoPaths, *, system: bool = False, user: str | None = None) -> str:
    cmd = " ".join(f'"{c}"' if " " in c else c for c in daemon_command(paths))
    lines = [
        "[Unit]",
        "Description=Undo file version history daemon",
        "After=local-fs.target",
        "",
        "[Service]",
        "Type=simple",
        f"ExecStart={cmd}",
        "Restart=on-failure",
        "RestartSec=5",
        "Nice=10",
        "IOSchedulingClass=idle",
        "TimeoutStopSec=60",
        f"Environment=UNDO_HOME={paths.data_dir}",
    ]
    if system and user:
        lines.insert(lines.index("[Service]") + 1, f"User={user}")
    lines += [
        "",
        "[Install]",
        f"WantedBy={'multi-user.target' if system else 'default.target'}",
        "",
    ]
    return "\n".join(lines)


def _install_systemd(paths: UndoPaths, system: bool) -> ServiceResult:
    if shutil.which("systemctl") is None:
        raise UndoError("systemctl not found; run `undo start` from your init system instead")
    if system:
        if os.geteuid() != 0:  # type: ignore[attr-defined]
            raise UndoError("System-wide installation requires root (sudo)")
        user = os.environ.get("SUDO_USER") or "root"
        unit_path = Path("/etc/systemd/system") / UNIT_NAME
        unit_path.write_text(systemd_unit(paths, system=True, user=user), encoding="utf-8")
        base = ["systemctl"]
    else:
        unit_dir = (
            Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "systemd" / "user"
        )
        unit_dir.mkdir(parents=True, exist_ok=True)
        unit_path = unit_dir / UNIT_NAME
        unit_path.write_text(systemd_unit(paths), encoding="utf-8")
        base = ["systemctl", "--user"]
    for args in (["daemon-reload"], ["enable", "--now", UNIT_NAME]):
        result = _run(base + args)
        if result.returncode != 0:
            return ServiceResult(
                False, f"{' '.join(base + args)} failed: {result.stderr.strip()}", str(unit_path)
            )
    hint = "" if system else " (run `loginctl enable-linger $USER` to keep it running after logout)"
    return ServiceResult(True, f"systemd unit installed and started{hint}", str(unit_path))


def _uninstall_systemd(system: bool) -> ServiceResult:
    if system:
        unit_path = Path("/etc/systemd/system") / UNIT_NAME
        base = ["systemctl"]
    else:
        unit_path = (
            Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
            / "systemd"
            / "user"
            / UNIT_NAME
        )
        base = ["systemctl", "--user"]
    _run([*base, "disable", "--now", UNIT_NAME])
    if unit_path.exists():
        unit_path.unlink()
    _run([*base, "daemon-reload"])
    return ServiceResult(True, "systemd unit removed", str(unit_path))


# --------------------------------------------------------------------------- Windows
def _install_task(paths: UndoPaths) -> ServiceResult:
    cmd = daemon_command(paths)
    tr = " ".join(f'"{c}"' for c in cmd)
    result = _run(
        [
            "schtasks",
            "/Create",
            "/F",
            "/SC",
            "ONLOGON",
            "/RL",
            "LIMITED",
            "/TN",
            TASK_NAME,
            "/TR",
            tr,
        ]
    )
    if result.returncode != 0:
        return ServiceResult(
            False, f"schtasks failed: {result.stderr.strip() or result.stdout.strip()}"
        )
    _run(["schtasks", "/Run", "/TN", TASK_NAME])
    return ServiceResult(
        True, f"Scheduled task '{TASK_NAME}' created (starts at logon) and started"
    )


def _uninstall_task() -> ServiceResult:
    result = _run(["schtasks", "/Delete", "/F", "/TN", TASK_NAME])
    if result.returncode != 0:
        return ServiceResult(
            False, f"schtasks failed: {result.stderr.strip() or result.stdout.strip()}"
        )
    return ServiceResult(True, f"Scheduled task '{TASK_NAME}' removed")


def install_autostart(paths: UndoPaths, *, system: bool = False) -> ServiceResult:
    if IS_LINUX:
        return _install_systemd(paths, system)
    if IS_WINDOWS:
        if system:
            raise UndoError(
                "For a machine-wide Windows service run (as administrator): "
                "python services/windows/install_service.py --data-dir <dir>"
            )
        return _install_task(paths)
    raise UndoError("Autostart installation is supported on Linux and Windows")


def uninstall_autostart(*, system: bool = False) -> ServiceResult:
    if IS_LINUX:
        return _uninstall_systemd(system)
    if IS_WINDOWS:
        return _uninstall_task()
    raise UndoError("Autostart installation is supported on Linux and Windows")


def autostart_status() -> str:
    if IS_LINUX and shutil.which("systemctl"):
        r = _run(["systemctl", "--user", "is-enabled", UNIT_NAME])
        return f"systemd --user: {r.stdout.strip() or r.stderr.strip()}"
    if IS_WINDOWS:
        r = _run(["schtasks", "/Query", "/TN", TASK_NAME])
        return "scheduled task: installed" if r.returncode == 0 else "scheduled task: not installed"
    return "unsupported platform"
