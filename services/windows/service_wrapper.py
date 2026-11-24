"""Windows service wrapper for the Undo daemon (requires pywin32).

Runs :class:`undo_core.daemon.manager.DaemonManager` inside the service
process. The data directory is read from the service's registry parameters
(``HKLM\\SYSTEM\\CurrentControlSet\\Services\\UndoDaemon\\Parameters\\DataDir``),
written by ``install_service.py``. Note: a service running as LocalSystem
can only read files that LocalSystem can access; for per-user folders prefer
``undo service install`` (starts at sign-in, no admin needed) or configure the service to run as
that user (``install_service.py --user``).
"""

from __future__ import annotations

import sys
import threading
import winreg

import servicemanager  # type: ignore[import-not-found]
import win32event  # type: ignore[import-not-found]
import win32service  # type: ignore[import-not-found]
import win32serviceutil  # type: ignore[import-not-found]

SERVICE_NAME = "UndoDaemon"
DISPLAY_NAME = "Undo file version history"
DESCRIPTION = "Monitors tracked folders and keeps local, content-addressed file version history."


def _data_dir() -> str | None:
    try:
        key = winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            rf"SYSTEM\CurrentControlSet\Services\{SERVICE_NAME}\Parameters",
        )
        value, _ = winreg.QueryValueEx(key, "DataDir")
        return str(value)
    except OSError:
        return None


class UndoService(win32serviceutil.ServiceFramework):
    _svc_name_ = SERVICE_NAME
    _svc_display_name_ = DISPLAY_NAME
    _svc_description_ = DESCRIPTION

    def __init__(self, args: list[str]) -> None:
        super().__init__(args)
        self.stop_event = win32event.CreateEvent(None, 0, 0, None)
        self.manager = None
        self.thread: threading.Thread | None = None

    def SvcStop(self) -> None:
        self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
        if self.manager is not None:
            self.manager.request_stop()
        win32event.SetEvent(self.stop_event)

    def SvcDoRun(self) -> None:
        from undo_core.daemon.manager import DaemonManager

        servicemanager.LogMsg(
            servicemanager.EVENTLOG_INFORMATION_TYPE,
            servicemanager.PYS_SERVICE_STARTED,
            (self._svc_name_, ""),
        )
        self.manager = DaemonManager(_data_dir())
        self.thread = threading.Thread(target=self._run, name="undo-daemon", daemon=True)
        self.thread.start()
        win32event.WaitForSingleObject(self.stop_event, win32event.INFINITE)
        if self.thread:
            self.thread.join(timeout=60)
        servicemanager.LogMsg(
            servicemanager.EVENTLOG_INFORMATION_TYPE,
            servicemanager.PYS_SERVICE_STOPPED,
            (self._svc_name_, ""),
        )

    def _run(self) -> None:
        try:
            assert self.manager is not None
            self.manager.run()
        except Exception as exc:  # report and stop the service
            servicemanager.LogErrorMsg(f"Undo daemon failed: {exc}")
        finally:
            win32event.SetEvent(self.stop_event)


if __name__ == "__main__":
    if len(sys.argv) == 1:
        servicemanager.Initialize()
        servicemanager.PrepareToHostSingle(UndoService)
        servicemanager.StartServiceCtrlDispatcher()
    else:
        win32serviceutil.HandleCommandLine(UndoService)
