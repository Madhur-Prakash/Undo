from __future__ import annotations

from fastapi import APIRouter, Depends

from undo_core.api.dependencies import get_service
from undo_core.api.schemas import CreateSnapshotRequest, SnapshotRestoreRequest
from undo_core.domain import RestoreResult, SnapshotDetail, SnapshotDiff, SnapshotInfo
from undo_core.service import UndoService

router = APIRouter(tags=["snapshots"])


@router.get("/snapshots", response_model=list[SnapshotInfo])
def list_snapshots(
    root: str | None = None, service: UndoService = Depends(get_service)
) -> list[SnapshotInfo]:
    return service.list_snapshots(root=root)


@router.post("/snapshots", response_model=SnapshotInfo, status_code=201)
def create_snapshot(
    body: CreateSnapshotRequest, service: UndoService = Depends(get_service)
) -> SnapshotInfo:
    return service.create_snapshot(
        name=body.name, root=body.root, description=body.description, scan=body.scan
    )


@router.get("/snapshots/{a}/diff/{b}", response_model=SnapshotDiff)
def diff_snapshots(a: str, b: str, service: UndoService = Depends(get_service)) -> SnapshotDiff:
    return service.diff_snapshots(a, b)


@router.get("/snapshots/{ref}", response_model=SnapshotDetail)
def get_snapshot(ref: str, service: UndoService = Depends(get_service)) -> SnapshotDetail:
    return service.get_snapshot(ref)


@router.post("/snapshots/{ref}/restore", response_model=RestoreResult)
def restore_snapshot(
    ref: str, body: SnapshotRestoreRequest, service: UndoService = Depends(get_service)
) -> RestoreResult:
    return service.restore_snapshot(
        ref,
        destination=body.destination,
        prefix=body.prefix,
        overwrite=body.overwrite,
        dry_run=body.dry_run,
    )


@router.delete("/snapshots/{ref}", response_model=SnapshotInfo)
def delete_snapshot(ref: str, service: UndoService = Depends(get_service)) -> SnapshotInfo:
    return service.delete_snapshot(ref)
