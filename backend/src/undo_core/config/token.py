"""Local API token: generated at init, stored with owner-only permissions."""

from __future__ import annotations

import secrets
from pathlib import Path

from undo_core.platform.permissions import secure_file
from undo_core.utils.atomic import atomic_write_text
from undo_core.utils.errors import NotInitializedError


def ensure_token(path: Path) -> str:
    if path.exists():
        token = path.read_text(encoding="utf-8").strip()
        if token:
            return token
    token = secrets.token_urlsafe(32)
    atomic_write_text(path, token, mode=0o600)
    secure_file(path)
    return token


def read_token(path: Path) -> str:
    try:
        token = path.read_text(encoding="utf-8").strip()
    except FileNotFoundError as exc:
        raise NotInitializedError("API token missing; run `undo init`") from exc
    if not token:
        raise NotInitializedError("API token file is empty; run `undo init`")
    return token


def rotate_token(path: Path) -> str:
    path.unlink(missing_ok=True)
    return ensure_token(path)
