"""Stop and remove the Undo Windows service (run from an elevated prompt). History is not touched."""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pywintypes  # type: ignore[import-not-found]
import win32serviceutil  # type: ignore[import-not-found]

sys.path.insert(0, str(Path(__file__).resolve().parent))
from service_wrapper import SERVICE_NAME


def main() -> int:
    try:
        win32serviceutil.StopService(SERVICE_NAME)
        time.sleep(3)
    except pywintypes.error:
        pass  # not running
    try:
        win32serviceutil.RemoveService(SERVICE_NAME)
    except pywintypes.error as exc:
        print(f"Could not remove service: {exc}", file=sys.stderr)
        return 1
    print(f"Service {SERVICE_NAME} removed. Your Undo data directory was left untouched.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
