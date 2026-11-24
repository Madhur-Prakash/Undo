"""Error hierarchy shared by the service layer, API and CLI."""

from __future__ import annotations

from typing import Any


class UndoError(Exception):
    """Base class for all expected Undo errors.

    ``code`` is a stable machine-readable identifier, ``status`` the HTTP status
    used by the API and ``exit_code`` the CLI process exit code.
    """

    code = "undo_error"
    status = 400
    exit_code = 1

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "details": self.details}


class NotInitializedError(UndoError):
    code = "not_initialized"
    status = 409
    exit_code = 3


class NotFoundError(UndoError):
    code = "not_found"
    status = 404
    exit_code = 4


class ConflictError(UndoError):
    code = "conflict"
    status = 409
    exit_code = 5


class InvalidInputError(UndoError):
    code = "invalid_input"
    status = 422
    exit_code = 2


class PathOutsideRootError(InvalidInputError):
    code = "path_outside_root"


class UnsafePathError(InvalidInputError):
    code = "unsafe_path"


class LockedError(UndoError):
    code = "locked"
    status = 423
    exit_code = 6


class DaemonNotRunningError(UndoError):
    code = "daemon_not_running"
    status = 503
    exit_code = 7


class StorageIntegrityError(UndoError):
    code = "storage_integrity"
    status = 500
    exit_code = 8


class FileChangedDuringCapture(UndoError):
    code = "file_changed_during_capture"
    status = 409


class AuthenticationError(UndoError):
    code = "unauthorized"
    status = 401
    exit_code = 9
