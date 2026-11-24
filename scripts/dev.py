"""Cross-platform development task runner (used by Makefile and make.sh).

    python scripts/dev.py <task> [args...]

Tasks: init install backend cli tui gui test test-unit test-integration test-stress
       lint format typecheck build clean docs
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GUI = ROOT / "gui" / "undo_desktop"
DEV_HOME = ROOT / ".dev-home"


def run(*cmd: str, cwd: Path = ROOT, env: dict[str, str] | None = None, check: bool = True) -> int:
    print("+", " ".join(cmd), flush=True)
    exe = shutil.which(cmd[0]) or cmd[0]
    result = subprocess.run([exe, *cmd[1:]], cwd=cwd, env={**os.environ, **(env or {})})
    if check and result.returncode != 0:
        raise SystemExit(result.returncode)
    return result.returncode


def uv(*args: str, **kw: object) -> int:
    return run("uv", *args, **kw)  # type: ignore[arg-type]


def dev_env() -> dict[str, str]:
    """`make dev` and friends use an isolated data directory inside the repo."""
    return {"UNDO_HOME": os.environ.get("UNDO_HOME", str(DEV_HOME))}


def task_init() -> None:
    uv("sync", "--all-packages")
    uv("run", "undo", "init", env=dev_env())
    if shutil.which("flutter"):
        run("flutter", "pub", "get", cwd=GUI)
    else:
        print("flutter not found: skipping GUI dependencies")


def task_install() -> None:
    """Install the `undo` command for the current user (uv tool)."""
    uv(
        "tool",
        "install",
        "--force",
        "--editable",
        str(ROOT / "cli"),
        "--with-editable",
        str(ROOT / "backend"),
    )


def task_backend() -> None:
    uv("run", "undo", "init", env=dev_env())
    uv("run", "python", "-m", "undo_core.daemon", "--console-log", env=dev_env())


def task_cli(*args: str) -> None:
    uv("run", "undo", *(args or ("--help",)), env=dev_env())


def task_tui() -> None:
    uv("run", "undo", "tui", env=dev_env())


def task_gui() -> None:
    target = "windows" if os.name == "nt" else "linux"
    run("flutter", "run", "-d", target, cwd=GUI, env=dev_env())


def _pytest(*args: str) -> None:
    uv("run", "pytest", *args)


def task_test() -> None:
    _pytest("backend/tests", "-m", "not stress")


def task_test_unit() -> None:
    _pytest("backend/tests/unit")


def task_test_integration() -> None:
    _pytest("backend/tests/integration", "backend/tests/filesystem", "backend/tests/recovery")


def task_test_stress() -> None:
    _pytest("backend/tests/stress", "-m", "stress")


def task_lint() -> None:
    uv("run", "ruff", "check", "backend", "cli", "scripts", "services")
    if shutil.which("flutter"):
        run("flutter", "analyze", cwd=GUI)


def task_format() -> None:
    uv("run", "ruff", "format", "backend", "cli", "scripts", "services")
    uv("run", "ruff", "check", "--fix", "backend", "cli", "scripts", "services")
    if shutil.which("dart"):
        run("dart", "format", "lib", "test", cwd=GUI)


def task_typecheck() -> None:
    uv("run", "mypy", "backend/src/undo_core", "cli/undo_cli")


def task_build() -> None:
    run(sys.executable, str(ROOT / "scripts" / "build.py"))


def task_clean() -> None:
    for pattern in (
        "**/__pycache__",
        "**/.pytest_cache",
        "**/.mypy_cache",
        "**/.ruff_cache",
        "dist",
        "build",
    ):
        for path in ROOT.glob(pattern):
            if ".venv" in path.parts or "gui" in path.parts:
                continue
            shutil.rmtree(path, ignore_errors=True)
    if shutil.which("flutter"):
        run("flutter", "clean", cwd=GUI, check=False)


def task_docs() -> None:
    """Regenerate docs/API_OPENAPI.json from the FastAPI app (docs/*.md are hand-written)."""
    code = (
        "import json,pathlib;"
        "from undo_core.api.app import create_app;"
        "app=create_app(None, token='x');"  # type: ignore[arg-type]
        "pathlib.Path('docs/API_OPENAPI.json').write_text(json.dumps(app.openapi(), indent=2))"
    )
    uv("run", "python", "-c", code)
    print("Wrote docs/API_OPENAPI.json")


TASKS = {
    name[5:].replace("_", "-"): fn for name, fn in globals().items() if name.startswith("task_")
}


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] not in TASKS:
        print(__doc__)
        print("Available:", ", ".join(sorted(TASKS)))
        raise SystemExit(2)
    TASKS[sys.argv[1]](*sys.argv[2:])


if __name__ == "__main__":
    main()
