"""Iterative directory scanner (no recursion limit, symlink-loop safe)."""

from __future__ import annotations

import os
import stat
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from undo_core.filesystem.exclusions import ExclusionMatcher, SkipReason
from undo_core.platform.paths import is_within


@dataclass(frozen=True)
class ScanEntry:
    relative_path: str
    absolute_path: Path
    stat: os.stat_result


@dataclass(frozen=True)
class ScanSkip:
    relative_path: str
    reason: str
    detail: str | None = None
    is_dir: bool = False


def scan_tree(
    root: Path,
    matcher: ExclusionMatcher,
    *,
    start: str = "",
    follow_symlinks: bool = False,
    max_file_size: int | None = None,
) -> Iterator[ScanEntry | ScanSkip]:
    """Yield every regular file under ``root/start`` plus a record for everything skipped.

    * Symlinks are not followed by default. With ``follow_symlinks`` only links
      whose target stays inside ``root`` are followed, and visited directories
      are tracked by (device, inode) to break loops.
    * Excluded directories are pruned without descending into them.
    * Permission errors are reported as skips instead of aborting the scan.
    """
    visited: set[tuple[int, int]] = set()
    stack: list[str] = [start.strip("/")]
    try:
        root_st = os.stat(root / start) if start else os.stat(root)
        visited.add((root_st.st_dev, root_st.st_ino))
    except OSError as exc:
        yield ScanSkip(
            start,
            SkipReason.PERMISSION_DENIED
            if isinstance(exc, PermissionError)
            else SkipReason.UNAVAILABLE,
            str(exc),
            True,
        )
        return
    while stack:
        rel_dir = stack.pop()
        abs_dir = root / Path(*rel_dir.split("/")) if rel_dir else root
        try:
            iterator = os.scandir(abs_dir)
        except PermissionError as exc:
            yield ScanSkip(rel_dir, SkipReason.PERMISSION_DENIED, exc.strerror, True)
            continue
        except FileNotFoundError:
            continue
        except OSError as exc:
            yield ScanSkip(rel_dir, SkipReason.UNAVAILABLE, str(exc), True)
            continue
        with iterator:
            for entry in iterator:
                rel = f"{rel_dir}/{entry.name}" if rel_dir else entry.name
                try:
                    is_link = entry.is_symlink()
                    lst = entry.stat(follow_symlinks=False)
                except OSError as exc:
                    yield ScanSkip(rel, SkipReason.UNAVAILABLE, str(exc))
                    continue
                is_dir_entry = stat.S_ISDIR(lst.st_mode)
                if is_link:
                    if not follow_symlinks:
                        yield ScanSkip(rel, SkipReason.SYMLINK, None)
                        continue
                    try:
                        target = Path(os.path.realpath(entry.path))
                        st = os.stat(entry.path)
                    except OSError as exc:
                        yield ScanSkip(rel, SkipReason.SYMLINK, f"broken link: {exc}")
                        continue
                    if not is_within(target, root):
                        yield ScanSkip(rel, SkipReason.SYMLINK, "target outside tracked root")
                        continue
                    is_dir_entry = stat.S_ISDIR(st.st_mode)
                    lst = st
                reason = matcher.check(rel, is_dir=is_dir_entry, st=lst)
                if reason:
                    yield ScanSkip(rel, reason, None, is_dir_entry)
                    continue
                if is_dir_entry:
                    key = (lst.st_dev, lst.st_ino)
                    if key in visited and lst.st_ino:
                        yield ScanSkip(rel, SkipReason.SYMLINK, "directory loop", True)
                        continue
                    visited.add(key)
                    stack.append(rel)
                    continue
                if not stat.S_ISREG(lst.st_mode):
                    yield ScanSkip(rel, SkipReason.SPECIAL, None)
                    continue
                if max_file_size is not None and lst.st_size > max_file_size:
                    yield ScanSkip(rel, SkipReason.TOO_LARGE, f"{lst.st_size} bytes")
                    continue
                yield ScanEntry(rel, Path(entry.path), lst)
