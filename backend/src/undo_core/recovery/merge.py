"""Resolve a restore like a merge conflict: combine the file on disk with a stored version.

* :func:`line_pair` loads both sides as lines (the file now, and the version) for an editor.
* :func:`write_merged` writes the merged text to the file. Like an overwriting restore, the
  file's current content is captured as a version first, so the merge itself can be undone.
  The write is refused if the file changed since the editor loaded it.
* Drafts ("save progress") are small JSON files in ``<data dir>/merge-drafts``, one per file,
  so an unfinished merge can be resumed later. They are deleted once the file is merged or
  restored.
* A *resolution* is a draft marked ``resolved``: the finished merge, kept by Undo without
  touching the file. The next restore of that file and version writes the resolution instead
  of the stored version (see :func:`resolution_for`), unless the file changed after it was
  resolved.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

from undo_core.platform.paths import path_key
from undo_core.recovery.restore_safety import RESTORE_TMP_PREFIX
from undo_core.utils.atomic import fsync_dir, fsync_file
from undo_core.utils.errors import ConflictError, InvalidInputError
from undo_core.utils.timeutil import utcnow
from undo_core.versioning.diff import decode_text, line_ending_style, split_lines

DRAFTS_DIR = "merge-drafts"


def content_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def detect_line_ending(*samples: bytes) -> str:
    """The line ending to write: the file's own style, else the version's, else the platform's."""
    for data in samples:
        style = line_ending_style(data)
        if style in ("CRLF", "LF"):
            return style
    return "CRLF" if os.name == "nt" else "LF"


def encode_text(text: str, line_ending: str, *, final_newline: bool) -> bytes:
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    if lines and lines[-1] == "":
        lines.pop()  # a trailing newline is decided by `final_newline`, not by the editor
    sep = "\r\n" if line_ending == "CRLF" else "\n"
    body = sep.join(lines)
    if final_newline and lines:
        body += sep
    return body.encode("utf-8")


def line_pair(current: bytes, stored: bytes) -> tuple[list[str], list[str]]:
    """Both sides as lines, split exactly like the diff, so hunk line numbers match."""
    return split_lines(decode_text(current)), split_lines(decode_text(stored))


def write_merged(path: Path, data: bytes) -> None:
    """Atomically replace ``path`` with ``data``.

    The temporary file uses Undo's restore prefix, so the watcher ignores it.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=RESTORE_TMP_PREFIX, suffix=".tmp", dir=path.parent)
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            fsync_file(handle)
        if path.exists():
            with contextlib.suppress(OSError):
                os.chmod(tmp, path.stat().st_mode & 0o7777)
        os.replace(tmp, path)
        fsync_dir(path.parent)
    except BaseException:
        with contextlib.suppress(OSError):
            tmp.unlink()
        raise


def check_unchanged(path: Path, expected_hash: str | None) -> bytes:
    """Current bytes of ``path``; refuses if they differ from what the editor loaded."""
    current = path.read_bytes() if path.is_file() else b""
    if expected_hash is not None and content_hash(current) != expected_hash:
        raise ConflictError(
            f"{path} changed since the merge editor opened it. Reload the merge to see the "
            "latest content (your draft can be saved first)."
        )
    return current


# --------------------------------------------------------------------------- composing
CHOICES = ("disk", "version", "both")


def _get(obj: Any, name: str) -> Any:
    return obj[name] if isinstance(obj, dict) else getattr(obj, name)


def _take(out: list[str], disk: list[str], version: list[str], choice: str) -> None:
    """Append one block of changed lines according to the choice, then reset the block."""
    if choice != "version":
        out.extend(disk)
    if choice != "disk":
        out.extend(version)
    disk.clear()
    version.clear()


def compose_result(current_lines: list[str], hunks: list[Any], choices: dict[int, str]) -> str:
    """The merged text: the file's lines, with each difference taken from disk, version or both.

    ``hunks`` are side-by-side hunks (models or their JSON dicts). ``choices`` maps a hunk index
    to "disk", "version" or "both"; a missing index means "disk". Within a difference, "both"
    puts the disk's lines first, then the version's. The desktop app uses the same algorithm.
    """
    out: list[str] = []
    pos = 0
    for index, hunk in enumerate(hunks):
        start = max(0, _get(hunk, "a_start") - 1)
        while pos < start and pos < len(current_lines):
            out.append(current_lines[pos])
            pos += 1
        choice = choices.get(index, "disk")
        pending_a: list[str] = []
        pending_b: list[str] = []
        for row in _get(hunk, "rows"):
            if _get(row, "kind") == "equal":
                _take(out, pending_a, pending_b, choice)
                out.append(_get(row, "a_text") or "")
                continue
            if _get(row, "a_text") is not None:
                pending_a.append(_get(row, "a_text"))
            if _get(row, "b_text") is not None:
                pending_b.append(_get(row, "b_text"))
        _take(out, pending_a, pending_b, choice)
        pos = start + _get(hunk, "a_count")
    out.extend(current_lines[pos:])
    return "\n".join(out)


# --------------------------------------------------------------------------- drafts
def _drafts_dir(data_dir: Path) -> Path:
    return data_dir / DRAFTS_DIR


def _draft_file(data_dir: Path, path: str) -> Path:
    digest = hashlib.sha256(path_key(str(Path(path))).encode("utf-8")).hexdigest()[:32]
    return _drafts_dir(data_dir) / f"{digest}.json"


def save_draft(
    data_dir: Path,
    *,
    path: str,
    version_id: int,
    text: str,
    choices: dict[str, str],
    edited: bool,
    resolution: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Save progress, or with ``resolution`` (current_hash, line_ending, final_newline) a
    finished resolution that the next restore applies."""
    if len(text.encode("utf-8")) > 16 * 1024 * 1024:
        raise InvalidInputError("Draft is too large to save")
    draft: dict[str, Any] = {
        "path": str(Path(path)),
        "version_id": version_id,
        "text": text,
        "choices": choices,
        "edited": edited,
        "resolved": resolution is not None,
        "updated_at": utcnow().isoformat(),
    }
    if resolution is not None:
        draft.update(resolution)
    target = _draft_file(data_dir, path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".tmp")
    tmp.write_text(json.dumps(draft), encoding="utf-8")
    os.replace(tmp, target)
    return draft


def load_draft(data_dir: Path, path: str) -> dict[str, Any] | None:
    target = _draft_file(data_dir, path)
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def list_drafts(data_dir: Path) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    folder = _drafts_dir(data_dir)
    if not folder.is_dir():
        return out
    for f in sorted(folder.glob("*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(data, dict):
            out.append(data)
    out.sort(key=lambda d: d.get("updated_at") or "", reverse=True)
    return out


def resolution_for(data_dir: Path, dest: Path, version_id: int) -> tuple[bytes, str | None] | None:
    """The saved resolution for restoring ``version_id`` to ``dest``: (bytes to write, hash the
    file had when it was resolved). None if there is no resolution for that version."""
    draft = load_draft(data_dir, str(dest))
    if not draft or not draft.get("resolved") or draft.get("version_id") != version_id:
        return None
    data = encode_text(
        str(draft.get("text") or ""),
        str(draft.get("line_ending") or ("CRLF" if os.name == "nt" else "LF")),
        final_newline=bool(draft.get("final_newline", True)),
    )
    expected = draft.get("current_hash")
    return data, expected if isinstance(expected, str) else None


def delete_drafts(data_dir: Path, paths: list[str]) -> int:
    removed = 0
    for path in paths:
        with contextlib.suppress(FileNotFoundError):
            _draft_file(data_dir, path).unlink()
            removed += 1
    return removed


def parse_updated(value: str | None) -> datetime | None:
    try:
        return datetime.fromisoformat(value) if value else None
    except ValueError:
        return None


__all__ = [
    "CHOICES",
    "check_unchanged",
    "compose_result",
    "content_hash",
    "delete_drafts",
    "detect_line_ending",
    "encode_text",
    "line_pair",
    "list_drafts",
    "load_draft",
    "resolution_for",
    "save_draft",
    "write_merged",
]
