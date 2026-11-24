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

# Default exclusion patterns. Trailing "/" means "directory with this name".
# These are deliberately limited to tool caches and VCS internals; users can
# remove any of them with `undo settings set exclusions.defaults ...`.
DEFAULT_EXCLUSIONS: list[str] = [
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
