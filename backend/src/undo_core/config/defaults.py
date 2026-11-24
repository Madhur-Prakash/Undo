"""Default values. Everything here is visible through `undo settings show` / `undo exclude list`."""

from __future__ import annotations

DEFAULT_API_HOST = "127.0.0.1"
DEFAULT_API_PORT = 47821

KIB = 1024
MIB = 1024 * KIB
GIB = 1024 * MIB

DEFAULT_COMPRESSION_LEVEL = 3
DEFAULT_CHUNK_SIZE = 4 * MIB
DEFAULT_MAX_FILE_SIZE = 4 * GIB
READ_BUFFER = 1 * MIB

# Default exclusion patterns. Trailing "/" means "directory with this name" (anywhere in a
# tracked folder, with everything below it); other patterns match file or directory names.
# They cover version-control internals, tool caches, temporary files and installed packages:
# things that are regenerated, change constantly and are not your work. Remove any of them
# with `undo exclude remove PATTERN` (or `undo settings set exclusions.defaults ...`).
#
# Version 1 is the original list. Each later version lists only the patterns it adds;
# existing installs get those once on upgrade (see ExclusionSettings), and a pattern the
# user removed is never added back.
_DEFAULT_EXCLUSIONS_V1: list[str] = [
    ".git/",
    ".hg/",
    ".svn/",
    "node_modules/",
    "__pycache__/",
    ".venv/",
    ".mypy_cache/",
    ".pytest_cache/",
    ".ruff_cache/",
    ".tox/",
    "*.tmp",
    "*.temp",
    "*.swp",
    "*.swx",
    "*~",
    "~$*",
    ".~lock.*#",
    ".DS_Store",
    "Thumbs.db",
]

DEFAULT_EXCLUSIONS_ADDED: dict[int, list[str]] = {
    2: [
        # Python and pip: built and downloaded packages, installed environments
        "*.whl",
        "*.egg",
        "*.egg-info/",
        ".eggs/",
        "pip-wheel-metadata/",
        "site-packages/",
        "__pypackages__/",
        "venv/",
        ".nox/",
        "*.pyc",
        "*.pyo",
        # Node: package-manager stores and installed packages (node_modules/ is in v1)
        ".npm/",
        ".pnpm-store/",
        ".yarn/",
        "bower_components/",
        "jspm_packages/",
        # Rust: Cargo build output and the Cargo/rustup homes (registry, toolchains)
        "target/",
        ".cargo/",
        ".rustup/",
        "*.crate",
    ],
}
DEFAULT_EXCLUSIONS_VERSION: int = max(DEFAULT_EXCLUSIONS_ADDED)
DEFAULT_EXCLUSIONS: list[str] = _DEFAULT_EXCLUSIONS_V1 + [
    p for v in sorted(DEFAULT_EXCLUSIONS_ADDED) for p in DEFAULT_EXCLUSIONS_ADDED[v]
]

# Built-in, non-removable exclusions: Undo's own temporary restore files.
BUILTIN_EXCLUSIONS: list[str] = [".undo-restore-*"]

# Formats that are already compressed; zstd rarely helps and wastes CPU.
INCOMPRESSIBLE_EXTENSIONS: list[str] = [
    ".7z",
    ".zip",
    ".gz",
    ".tgz",
    ".bz2",
    ".xz",
    ".zst",
    ".rar",
    ".lz4",
    ".br",
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".webp",
    ".heic",
    ".avif",
    ".mp3",
    ".aac",
    ".ogg",
    ".opus",
    ".flac",
    ".m4a",
    ".mp4",
    ".mkv",
    ".mov",
    ".avi",
    ".webm",
    ".m4v",
    ".docx",
    ".xlsx",
    ".pptx",
    ".odt",
    ".ods",
    ".odp",
    ".epub",
    ".jar",
    ".apk",
    ".woff",
    ".woff2",
]
