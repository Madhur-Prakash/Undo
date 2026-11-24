"""Request bodies for the local API. Responses use the models in :mod:`undo_core.domain`."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from undo_core.domain import *  # noqa: F403  (re-export response models)


class AddRootRequest(BaseModel):
    path: str
    scan: bool = True


class UpdateRootRequest(BaseModel):
    enabled: bool


class ScanRequest(BaseModel):
    target: str | int | None = None
    deep: bool = False


class RestoreRequest(BaseModel):
    path: str | None = Field(None, description="Current or historical path of a file or directory")
    version_id: int | None = None
    at: str | None = Field(None, description="ISO time or relative (2h, 3d)")
    before_version_id: int | None = None
    destination: str | None = None
    overwrite: bool = False
    dry_run: bool = False


class RestoreVersionRequest(BaseModel):
    version_id: int
    destination: str | None = None
    overwrite: bool = False
    dry_run: bool = False


class RecoverRequest(BaseModel):
    path: str
    destination: str | None = None
    overwrite: bool = False
    dry_run: bool = False


class CreateSnapshotRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    root: str | int | None = None
    description: str | None = None
    scan: bool = True


class SnapshotRestoreRequest(BaseModel):
    destination: str | None = None
    prefix: str = ""
    overwrite: bool = False
    dry_run: bool = False


class VerifyRequest(BaseModel):
    full: bool = True
    repair: bool = True


class DryRunRequest(BaseModel):
    dry_run: bool = True


class ExclusionRequest(BaseModel):
    pattern: str
    root: str | int | None = None


class SettingRequest(BaseModel):
    key: str
    value: Any


class ErrorBody(BaseModel):
    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class ErrorResponse(BaseModel):
    error: ErrorBody
