"""Release helper: bump the version everywhere, then build.

    python scripts/release.py 0.2.0 [--no-build]

Updates backend/pyproject.toml, cli/pyproject.toml, undo_core/__init__.py,
undo_cli/__init__.py and the Flutter pubspec. It does not commit or tag;
review the diff and do that yourself.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SEMVER = re.compile(r"^\d+\.\d+\.\d+([.-][0-9A-Za-z.]+)?$")

FILES = [
    (ROOT / "backend" / "pyproject.toml", r'(?m)^version = "[^"]+"', 'version = "{v}"'),
    (ROOT / "cli" / "pyproject.toml", r'(?m)^version = "[^"]+"', 'version = "{v}"'),
    (ROOT / "pyproject.toml", r'(?m)^version = "[^"]+"', 'version = "{v}"'),
    (
        ROOT / "backend" / "src" / "undo_core" / "__init__.py",
        r'__version__ = "[^"]+"',
        '__version__ = "{v}"',
    ),
    (ROOT / "cli" / "undo_cli" / "__init__.py", r'__version__ = "[^"]+"', '__version__ = "{v}"'),
    (ROOT / "gui" / "undo_desktop" / "pubspec.yaml", r"(?m)^version: [^\n]+", "version: {v}+1"),
]


def main() -> None:
    if len(sys.argv) < 2 or not SEMVER.match(sys.argv[1]):
        print(__doc__)
        raise SystemExit(2)
    version = sys.argv[1]
    for path, pattern, repl in FILES:
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        new, n = re.subn(pattern, repl.format(v=version), text, count=1)
        if n:
            path.write_text(new, encoding="utf-8")
            print(f"updated {path.relative_to(ROOT)}")
    if "--no-build" not in sys.argv:
        subprocess.run([sys.executable, str(ROOT / "scripts" / "build.py")], check=True)


if __name__ == "__main__":
    main()
