"""Autostart integration.

Linux:   systemd unit (``--user`` by default, no root needed; ``system`` scope
         installs ``undo@.service`` running as a named user).
Windows: a value named "Undo" in the per-user Run key (``RUN_KEY`` under HKEY_CURRENT_USER) that starts the
         windowless daemon at sign-in. No administrator rights are needed (a scheduled
         task with a logon trigger would need them). A real Windows service via pywin32
         (``services/windows``) is the machine-wide alternative and needs administrator rights.
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

TASK_NAME = "Undo Daemon"  # logon task of earlier builds; removed when found
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
# Autostart at sign-in through the per-user Run key. Unlike a scheduled task with a logon
# trigger (which Windows only lets administrators create), this needs no elevation, and it
# is what the Windows "Startup apps" settings page lists and can switch off.
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_VALUE = "Undo"


def _run_key_get() -> str | None:
    if sys.platform != "win32":
        return None
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            value, _kind = winreg.QueryValueEx(key, RUN_VALUE)
    except OSError:
        return None
    return str(value)


def _run_key_set(command: str) -> None:
    if sys.platform != "win32":
        raise UndoError("The Run key exists only on Windows")
    import winreg

    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
        winreg.SetValueEx(key, RUN_VALUE, 0, winreg.REG_SZ, command)


def _run_key_delete() -> bool:
    if sys.platform != "win32":
        return False
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, RUN_VALUE)
    except FileNotFoundError:
        return False
    return True


def _remove_legacy_task() -> None:
    """Remove the logon task earlier builds tried to create (needs no rights if it exists)."""
    if _run(["schtasks", "/Query", "/TN", TASK_NAME]).returncode == 0:
        _run(["schtasks", "/Delete", "/F", "/TN", TASK_NAME])


def _install_task(paths: UndoPaths, *, start_now: bool = True) -> ServiceResult:
    command = subprocess.list2cmdline(daemon_command(paths))
    try:
        _run_key_set(command)
    except OSError as exc:
        return ServiceResult(False, f"Could not write the Run key: {exc}")
    _remove_legacy_task()
    started = ""
    if start_now:
        from undo_core.daemon.lifecycle import start_background  # avoid an import cycle

        try:
            info = start_background(paths)
            started = f"; daemon running (pid {info.pid})"
        except UndoError as exc:
            started = f"; could not start it now: {exc.message}"
    return ServiceResult(
        True,
        f"The daemon starts when you sign in (HKCU\\{RUN_KEY}\\{RUN_VALUE}){started}",
    )


def _uninstall_task() -> ServiceResult:
    removed = _run_key_delete()
    _remove_legacy_task()
    if not removed:
        return ServiceResult(True, "Autostart was not installed")
    return ServiceResult(True, "Autostart removed (the running daemon keeps running until stopped)")


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
        command = _run_key_get()
        if command:
            return f"autostart at sign-in: installed\n  {command}"
        return "autostart at sign-in: not installed (run `undo service install`)"
    return "unsupported platform"
