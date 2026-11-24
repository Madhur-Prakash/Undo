"""Install the Undo Windows service (run from an elevated prompt).

    python services/windows/install_service.py --data-dir "C:\\Users\\me\\AppData\\Local\\Undo"
    python services/windows/install_service.py --data-dir D:\\Undo --user .\\me --password ***

Requires: pip install "undo-core[windows-service]" (pywin32), then once
``python -m pywin32_postinstall -install`` if pywin32's DLLs are not registered.
For per-user use without administrator rights prefer ``undo service install``.
"""

from __future__ import annotations

import argparse
import os
import sys
import winreg
from pathlib import Path

import win32service  # type: ignore[import-not-found]
import win32serviceutil  # type: ignore[import-not-found]

sys.path.insert(0, str(Path(__file__).resolve().parent))
from service_wrapper import DESCRIPTION, DISPLAY_NAME, SERVICE_NAME


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--data-dir", required=True, help="Undo data directory the service should own"
    )
    parser.add_argument("--user", help="Run the service as this account (e.g. .\\alice)")
    parser.add_argument("--password", help="Password for --user")
    parser.add_argument("--manual", action="store_true", help="Manual start instead of automatic")
    args = parser.parse_args()

    data_dir = str(Path(args.data_dir).expanduser().resolve())
    if not (Path(data_dir) / "config.json").exists():
        print(
            f'{data_dir} is not initialised; run `undo --data-dir "{data_dir}" init` first',
            file=sys.stderr,
        )
        return 3

    wrapper = Path(__file__).resolve().parent / "service_wrapper.py"
    win32serviceutil.InstallService(
        pythonClassString=f"{wrapper.with_suffix('')}.UndoService",
        serviceName=SERVICE_NAME,
        displayName=DISPLAY_NAME,
        description=DESCRIPTION,
        startType=win32service.SERVICE_DEMAND_START
        if args.manual
        else win32service.SERVICE_AUTO_START,
        userName=args.user,
        password=args.password,
        exeName=sys.executable,
        exeArgs=f'"{wrapper}"',
    )
    key = winreg.CreateKey(
        winreg.HKEY_LOCAL_MACHINE, rf"SYSTEM\CurrentControlSet\Services\{SERVICE_NAME}\Parameters"
    )
    winreg.SetValueEx(key, "DataDir", 0, winreg.REG_SZ, data_dir)
    winreg.CloseKey(key)
    os.environ.setdefault("UNDO_HOME", data_dir)
    win32serviceutil.StartService(SERVICE_NAME)
    print(f"Service {SERVICE_NAME} installed and started for {data_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
