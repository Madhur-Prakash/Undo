"""Dependency injection: the service instance and bearer-token authentication."""

from __future__ import annotations

import secrets
from collections.abc import Callable

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from undo_core.service import UndoService
from undo_core.utils.errors import AuthenticationError

_bearer = HTTPBearer(auto_error=False)


def get_service(request: Request) -> UndoService:
    return request.app.state.service  # type: ignore[no-any-return]


def get_shutdown(request: Request) -> Callable[[], None]:
    return request.app.state.on_shutdown  # type: ignore[no-any-return]


def require_token(
    request: Request, credentials: HTTPAuthorizationCredentials | None = Depends(_bearer)
) -> None:
    expected: str = request.app.state.token
    supplied = credentials.credentials if credentials else request.headers.get("X-Undo-Token", "")
    if not supplied or not secrets.compare_digest(supplied.encode(), expected.encode()):
        raise AuthenticationError("Missing or invalid API token")
