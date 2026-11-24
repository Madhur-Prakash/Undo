# PyInstaller spec for Undo's backend: build\dist\backend\ holds
#   undo.exe         the command line (and `undo tui`), with a console
#   undo-daemon.exe  the daemon, windowless, started by the app, `undo start` and the logon task
# Both share one _internal folder. Undo.iss runs this; by hand (from the repository root):
#   uv run --all-packages --with "pyinstaller>=6.10" pyinstaller gui/installer/Undo.spec

import os

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

HERE = SPECPATH  # noqa: F821 - defined by PyInstaller
ICON = os.path.join(HERE, "..", "assets", "undo.ico")

# Imported by name at run time, so the analysis cannot see them.
hidden = (
    collect_submodules("undo_core")  # migrations are discovered with pkgutil
    + collect_submodules("undo_cli")
    + collect_submodules("uvicorn")  # loops, protocols and lifespan picked by "auto"
    + collect_submodules("watchdog.observers")
    + collect_submodules("textual.widgets")  # loaded lazily by name
    + collect_submodules("rich._unicode_data")
    + collect_submodules("sqlalchemy.dialects.sqlite")
)
datas = collect_data_files("textual")  # built-in CSS


def analysis(script):
    return Analysis(  # noqa: F821
        [os.path.join(HERE, script)],
        hiddenimports=hidden,
        datas=datas,
        excludes=["tkinter", "pytest", "mypy", "ruff"],
        noarchive=False,
    )


cli = analysis("entry_cli.py")
daemon = analysis("entry_daemon.py")

cli_exe = EXE(  # noqa: F821
    PYZ(cli.pure),  # noqa: F821
    cli.scripts,
    exclude_binaries=True,
    name="undo",
    console=True,
    icon=ICON,
    upx=False,
)
daemon_exe = EXE(  # noqa: F821
    PYZ(daemon.pure),  # noqa: F821
    daemon.scripts,
    exclude_binaries=True,
    name="undo-daemon",
    console=False,
    icon=ICON,
    upx=False,
)
COLLECT(  # noqa: F821
    cli_exe,
    cli.binaries,
    cli.datas,
    daemon_exe,
    daemon.binaries,
    daemon.datas,
    name="backend",
    upx=False,
)
