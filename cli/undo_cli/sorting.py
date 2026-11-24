"""Sort orders shared by the CLI and the TUI.

Each key has a natural direction: names and paths A to Z, times newest first, sizes and
counts largest first. ``reverse`` flips it. Files are sorted by the backend (the list is
paged there); activity and snapshots are sorted here, over the rows already fetched.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

Row = dict[str, Any]

# key -> (label, natural order is descending)
FILE_SORTS: dict[str, tuple[str, bool]] = {
    "path": ("Path", False),
    "modified": ("Last modified", True),
    "size": ("Size", True),
    "version": ("Latest change", True),
    "versions": ("Number of versions", True),
}

# key -> (label, natural order is descending, sort key)
ACTIVITY_SORTS: dict[str, tuple[str, bool, Callable[[Row], Any]]] = {
    "time": ("Time", True, lambda v: (v["timestamp"], v["id"])),
    "path": ("Path", False, lambda v: v["absolute_path"].lower()),
    "size": ("Size", True, lambda v: v["file_size"] if v.get("blob_hash") else -1),
    "operation": ("Operation", False, lambda v: v["operation"]),
}

SNAPSHOT_SORTS: dict[str, tuple[str, bool, Callable[[Row], Any]]] = {
    "created": ("Created", True, lambda s: (s["created_at"], s["id"])),
    "name": ("Name", False, lambda s: s["name"].lower()),
    "root": ("Root", False, lambda s: s["root_path"].lower()),
    "files": ("Files", True, lambda s: s["file_count"]),
    "size": ("Size", True, lambda s: s["total_size"]),
}


def file_sort_args(key: str, reverse: bool = False) -> dict[str, Any]:
    """Arguments for the ``list_files`` call."""
    _, natural_desc = FILE_SORTS[key]
    return {"sort": key, "descending": natural_desc != reverse}


def sort_rows(
    rows: list[Row],
    table: dict[str, tuple[str, bool, Callable[[Row], Any]]],
    key: str,
    reverse: bool = False,
) -> list[Row]:
    _, natural_desc, func = table[key]
    return sorted(rows, key=func, reverse=natural_desc != reverse)


def choices(table: Mapping[str, object]) -> str:
    return ", ".join(table)
