"""Path normalisation, containment checks and the Undo data directory layout."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from undo_core.utils.errors import PathOutsideRootError, UnsafePathError

IS_WINDOWS = os.name == "nt"
IS_LINUX = sys.platform.startswith("linux")
IS_MAC = sys.platform == "darwin"
CASE_INSENSITIVE = IS_WINDOWS or IS_MAC
PLATFORM_NAME = "windows" if IS_WINDOWS else ("linux" if IS_LINUX else sys.platform)
ENV_HOME = "UNDO_HOME"


def default_data_dir() -> Path:
    """Platform default location of the Undo data directory (overridable with UNDO_HOME)."""
    env = os.environ.get(ENV_HOME)
    if env:
        return Path(env).expanduser().absolute()
    if IS_WINDOWS:
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / "Undo"
    if IS_MAC:
        return Path.home() / "Library" / "Application Support" / "Undo"
    xdg = os.environ.get("XDG_DATA_HOME")
    return (Path(xdg) if xdg else Path.home() / ".local" / "share") / "undo"


@dataclass(frozen=True)
class UndoPaths:
    """All well-known locations inside a data directory."""

    data_dir: Path

    @property
    def db_path(self) -> Path:
        return self.data_dir / "undo.db"

    @property
    def blobs_dir(self) -> Path:
        return self.data_dir / "blobs"

    @property
    def chunks_dir(self) -> Path:
        return self.data_dir / "chunks"

    @property
    def staging_dir(self) -> Path:
        return self.data_dir / "staging"

    @property
    def quarantine_dir(self) -> Path:
        return self.data_dir / "quarantine"

    @property
    def logs_dir(self) -> Path:
        return self.data_dir / "logs"

    @property
    def token_path(self) -> Path:
        return self.data_dir / "api_token"

    @property
    def lock_path(self) -> Path:
        return self.data_dir / "undo.lock"

    @property
    def daemon_info_path(self) -> Path:
        return self.data_dir / "daemon.json"

    @property
    def config_path(self) -> Path:
        return self.data_dir / "config.json"

    def ensure(self) -> None:
        for directory in (
            self.data_dir,
            self.blobs_dir,
            self.chunks_dir,
            self.staging_dir,
            self.quarantine_dir,
            self.logs_dir,
        ):
            directory.mkdir(parents=True, exist_ok=True)

    def is_initialized(self) -> bool:
        return self.config_path.exists() and self.db_path.exists()

    @classmethod
    def resolve(cls, data_dir: str | Path | None = None) -> UndoPaths:
        base = Path(data_dir).expanduser() if data_dir else default_data_dir()
        return cls(Path(os.path.abspath(base)))


def normalize_path(path: str | os.PathLike[str]) -> Path:
    """Absolute, normalised path without resolving symlinks of the final component."""
    return Path(os.path.normpath(os.path.abspath(os.path.expanduser(os.fspath(path)))))


def resolve_root_path(path: str | os.PathLike[str]) -> Path:
    """Canonical path for a tracked root (symlinks in the root path itself are resolved)."""
    return Path(os.path.realpath(normalize_path(path)))


def _cmp(path: Path | str) -> str:
    text = os.path.normpath(str(path))
    return os.path.normcase(text) if IS_WINDOWS else text


def is_within(child: Path | str, parent: Path | str) -> bool:
    """True if ``child`` equals or is inside ``parent`` (path-wise, no symlink resolution)."""
    c, p = _cmp(child), _cmp(parent)
    if c == p:
        return True
    if not p.endswith(os.sep):
        p += os.sep
    return c.startswith(p)


def path_key(relative_path: str) -> str:
    """Comparison key for a relative path, respecting platform case sensitivity."""
    return relative_path.casefold() if CASE_INSENSITIVE else relative_path


def to_relative(root: Path, absolute: Path | str) -> str:
    """POSIX-style relative path of ``absolute`` inside ``root``."""
    absolute = normalize_path(absolute)
    if not is_within(absolute, root):
        raise PathOutsideRootError(f"{absolute} is not inside tracked root {root}")
    rel = os.path.relpath(absolute, root)
    if rel == ".":
        return ""
    rel_posix = PurePosixPath(*Path(rel).parts).as_posix()
    if rel_posix.startswith("../") or rel_posix == "..":
        raise PathOutsideRootError(f"{absolute} is not inside tracked root {root}")
    return rel_posix


def validate_relative(relative: str) -> str:
    """Reject absolute paths, drive letters, empty segments and parent traversal."""
    if not relative or relative.startswith(("/", "\\")):
        raise UnsafePathError(f"Unsafe relative path: {relative!r}")
    if "\x00" in relative:
        raise UnsafePathError("Path contains NUL byte")
    parts = relative.replace("\\", "/").split("/")
    for part in parts:
        if part in ("", ".", ".."):
            raise UnsafePathError(f"Unsafe relative path: {relative!r}")
        if IS_WINDOWS and (":" in part):
            raise UnsafePathError(f"Unsafe relative path: {relative!r}")
    return "/".join(parts)


def safe_join(base: Path, relative: str) -> Path:
    """Join a stored relative path to a base directory, guaranteeing containment."""
    clean = validate_relative(relative)
    candidate = normalize_path(base / Path(*clean.split("/")))
    if not is_within(candidate, base):
        raise UnsafePathError(f"Path {relative!r} escapes {base}")
    return candidate


def join_relative(*parts: str) -> str:
    return "/".join(p.strip("/") for p in parts if p and p.strip("/"))


def parent_of(relative: str) -> str:
    return relative.rsplit("/", 1)[0] if "/" in relative else ""


def name_of(relative: str) -> str:
    return relative.rsplit("/", 1)[-1]
