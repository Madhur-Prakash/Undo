from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from undo_core.api.dependencies import get_service
from undo_core.api.schemas import AddRootRequest, ScanRequest, UpdateRootRequest
from undo_core.domain import AddRootResult, ReconcileReport, RootInfo
from undo_core.service import UndoService

router = APIRouter(tags=["roots"])


@router.get("/roots", response_model=list[RootInfo])
def list_roots(service: UndoService = Depends(get_service)) -> list[RootInfo]:
    return service.list_roots()


@router.post("/roots", response_model=AddRootResult, status_code=201)
def add_root(body: AddRootRequest, service: UndoService = Depends(get_service)) -> AddRootResult:
    return service.add_root(body.path, scan=body.scan)


@router.get("/roots/{root_id}", response_model=RootInfo)
def get_root(root_id: int, service: UndoService = Depends(get_service)) -> RootInfo:
    return service.get_root(root_id)


@router.patch("/roots/{root_id}", response_model=RootInfo)
def update_root(
    root_id: int, body: UpdateRootRequest, service: UndoService = Depends(get_service)
) -> RootInfo:
    return service.set_root_enabled(root_id, body.enabled)


@router.delete("/roots/{root_id}", response_model=RootInfo)
def remove_root(
    root_id: int, purge: bool = Query(False), service: UndoService = Depends(get_service)
) -> RootInfo:
    return service.remove_root(root_id, purge=purge)


@router.post("/scan", response_model=list[ReconcileReport])
def scan(body: ScanRequest, service: UndoService = Depends(get_service)) -> list[ReconcileReport]:
    return service.scan(body.target, deep=body.deep)
