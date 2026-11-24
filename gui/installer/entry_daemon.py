"""PyInstaller entry point for ``undo-daemon.exe``: the daemon, without a console window.

A windowed executable has no stdout/stderr (they are None); libraries that write to
them or ask ``isatty()`` (uvicorn's log formatter does) would fail, so point them at
the null device. The daemon's own log goes to ``<data dir>/logs``.
"""

import os
import sys

if sys.stdout is None:
    sys.stdout = open(os.devnull, "w", encoding="utf-8")  # noqa: SIM115
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w", encoding="utf-8")  # noqa: SIM115

from undo_core.daemon.manager import main

if __name__ == "__main__":
    raise SystemExit(main())
