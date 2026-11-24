"""Resolving user-supplied paths to tracked roots and files."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from undo_core.database.models import File, PathHistory, Root, Version
from undo_core.database.repositories import FileRepository
from undo_core.platform.paths import (
    is_within,
    normalize_path,
    path_key,
    resolve_root_path,
    to_relative,
)
from undo_core.utils.errors import NotFoundError, PathOutsideRootError
from undo_core.versioning.capture import RootRef


def root_ref(root: Root) -> RootRef:
    return RootRef(root.id, Path(root.absolute_path))


def find_root_for_path(session: Session, path: Path) -> Root | None:
    """Most specific tracked root containing ``path`` (tries the literal and resolved path)."""
    candidates = [normalize_path(path)]
    try:
        resolved = resolve_root_path(path)
        if resolved != candidates[0]:
            candidates.append(resolved)
    except OSError:
        pass
    roots = list(session.scalars(select(Root)))
    for candidate in candidates:
        matching = [r for r in roots if is_within(candidate, r.absolute_path)]
        if matching:
            return max(matching, key=lambda r: len(r.absolute_path))
    return None


@dataclass(frozen=True)
class PathTarget:
    root: RootRef
    relative_path: str
    file_id: int | None  # set when the path names a (current, deleted or historical) file
    is_directory: bool


def _relative_in(root: Root, path: Path) -> str:
    for candidate in (normalize_path(path), resolve_root_path(path)):
        try:
            return to_relative(Path(root.absolute_path), candidate)
        except PathOutsideRootError:
            continue
    raise PathOutsideRootError(f"{path} is not inside tracked root {root.absolute_path}")


def resolve_path(session: Session, path: str | Path) -> PathTarget:
    """Find what a path refers to: a file (live, deleted or by historical name) or a directory."""
    p = Path(path)
    root = find_root_for_path(session, p)
    if root is None:
        raise PathOutsideRootError(f"{path} is not inside any tracked root (see `undo roots`)")
    rel = _relative_in(root, p)
    ref = root_ref(root)
    if not rel:
        return PathTarget(ref, "", None, True)
    files = FileRepository(session)
    file = files.by_path_any(root.id, rel) or files.by_historical_path(root.id, rel)
    if file is not None:
        return PathTarget(ref, rel, file.id, False)
    key = path_key(rel).rstrip("/") + "/"
    has_children = (
        session.scalar(
            select(File.id)
            .where(File.root_id == root.id, File.path_key.startswith(key, autoescape=True))
            .limit(1)
        )
        or session.scalar(
            select(Version.id)
            .join(File, File.id == Version.file_id)
            .where(
                File.root_id == root.id,
                Version.relative_path.startswith(rel.rstrip("/") + "/", autoescape=True),
            )
            .limit(1)
        )
        or session.scalar(
            select(PathHistory.id)
            .join(File, File.id == PathHistory.file_id)
            .where(File.root_id == root.id, PathHistory.path_key.startswith(key, autoescape=True))
            .limit(1)
        )
    )
    if has_children or normalize_path(p).is_dir():
        return PathTarget(ref, rel, None, True)
    raise NotFoundError(f"No history for {path}")
