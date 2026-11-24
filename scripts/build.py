"""Build distributable artifacts into dist/.

* Python wheels + sdists for undo-core and undo-cli (uv build)
* Flutter desktop release build for the current OS (if flutter is installed)
* Linux only: dist/undo-linux.tar.gz, a release archive with the wheels, the desktop
  bundle, the systemd files and installer/install.sh (see docs/INSTALLATION.md)

Windows ships as Undo-Setup-<version>.exe instead: compile gui/installer/Undo.iss.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"
GUI = ROOT / "gui" / "undo_desktop"
IS_WINDOWS = os.name == "nt"


def run(*cmd: str, cwd: Path = ROOT) -> None:
    print("+", " ".join(cmd), flush=True)
    exe = shutil.which(cmd[0]) or cmd[0]
    subprocess.run([exe, *cmd[1:]], cwd=cwd, check=True)


def build_python() -> None:
    for pkg in ("backend", "cli"):
        run(
            "uv",
            "build",
            "--package",
            "undo-core" if pkg == "backend" else "undo-cli",
            "--out-dir",
            str(DIST / "python"),
        )


def build_gui() -> Path | None:
    if shutil.which("flutter") is None:
        print("flutter not found; skipping desktop build")
        return None
    target = "windows" if IS_WINDOWS else "linux"
    try:
        run("flutter", "build", target, "--release", cwd=GUI)
    except subprocess.CalledProcessError as exc:
        print(f"desktop build failed ({exc}); continuing without GUI bundle", file=sys.stderr)
        return None
    if IS_WINDOWS:
        bundle = GUI / "build" / "windows" / "x64" / "runner" / "Release"
    else:
        bundle = next((GUI / "build" / "linux").glob("*/release/bundle"), GUI / "build" / "linux")
    out = DIST / f"undo-desktop-{target}"
    shutil.rmtree(out, ignore_errors=True)
    shutil.copytree(bundle, out)
    return out


def assemble() -> Path:
    """The Linux release archive (Windows uses the Inno Setup installer)."""
    platform = "linux"
    stage = DIST / f"undo-{platform}"
    shutil.rmtree(stage, ignore_errors=True)
    stage.mkdir(parents=True)
    shutil.copytree(DIST / "python", stage / "python")
    if (DIST / f"undo-desktop-{platform}").exists():
        shutil.copytree(DIST / f"undo-desktop-{platform}", stage / "desktop")
    shutil.copytree(ROOT / "services" / platform, stage / "services")
    shutil.copytree(ROOT / "packaging" / platform, stage / "installer")
    shutil.copy2(ROOT / "gui" / "assets" / "undo.png", stage / "installer" / "undo.png")
    for doc in ("README.md", "LICENSE"):
        shutil.copy2(ROOT / doc, stage / doc)
    shutil.copytree(ROOT / "docs", stage / "docs")
    archive = shutil.make_archive(str(stage), "gztar", DIST, stage.name)
    return Path(archive)


def main() -> None:
    DIST.mkdir(exist_ok=True)
    build_python()
    build_gui()
    if IS_WINDOWS:
        print(
            f"\nArtifacts in {DIST}\n"
            "For the Windows installer compile gui/installer/Undo.iss with Inno Setup 7."
        )
        return
    archive = assemble()
    print(f"\nArtifacts in {DIST}\nRelease archive: {archive}")


if __name__ == "__main__":
    main()
