from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends

from undo_core.api.dependencies import get_service
from undo_core.api.schemas import ExclusionRequest, SettingRequest
from undo_core.domain import ExclusionInfo
from undo_core.service import UndoService

router = APIRouter(tags=["settings"])


@router.get("/settings")
def get_settings(service: UndoService = Depends(get_service)) -> dict[str, Any]:
    return service.get_settings()


@router.put("/settings")
def set_setting(
    body: SettingRequest, service: UndoService = Depends(get_service)
) -> dict[str, Any]:
    return service.set_setting(body.key, body.value)


@router.patch("/settings")
def update_settings(
    values: dict[str, Any] = Body(...), service: UndoService = Depends(get_service)
) -> dict[str, Any]:
    return service.update_settings(values)


@router.get("/exclusions", response_model=list[ExclusionInfo])
def list_exclusions(
    root: str | None = None, service: UndoService = Depends(get_service)
) -> list[ExclusionInfo]:
    return service.list_exclusions(root=root)


@router.post("/exclusions", response_model=ExclusionInfo, status_code=201)
def add_exclusion(
    body: ExclusionRequest, service: UndoService = Depends(get_service)
) -> ExclusionInfo:
    return service.add_exclusion(body.pattern, root=body.root)


@router.post("/exclusions/remove", response_model=ExclusionInfo)
def remove_exclusion(
    body: ExclusionRequest, service: UndoService = Depends(get_service)
) -> ExclusionInfo:
    return service.remove_exclusion(body.pattern, root=body.root)
