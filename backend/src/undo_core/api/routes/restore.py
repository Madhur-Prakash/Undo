from __future__ import annotations

from fastapi import APIRouter, Depends

from undo_core.api.dependencies import get_service
from undo_core.api.schemas import RecoverRequest, RestoreRequest, RestoreVersionRequest
from undo_core.domain import RestoreResult
from undo_core.service import UndoService
from undo_core.utils.errors import InvalidInputError

router = APIRouter(tags=["restore"])


@router.post("/restore", response_model=RestoreResult)
def restore(body: RestoreRequest, service: UndoService = Depends(get_service)) -> RestoreResult:
    if not body.path:
        raise InvalidInputError("path is required")
    return service.restore(
        body.path,
        version_id=body.version_id,
        at=body.at,
        before_version_id=body.before_version_id,
        destination=body.destination,
        overwrite=body.overwrite,
        dry_run=body.dry_run,
    )


@router.post("/restore/version", response_model=RestoreResult)
def restore_version(
    body: RestoreVersionRequest, service: UndoService = Depends(get_service)
) -> RestoreResult:
    return service.restore_version(
        body.version_id,
        destination=body.destination,
        overwrite=body.overwrite,
        dry_run=body.dry_run,
    )


@router.post("/restore/recover", response_model=RestoreResult)
def recover(body: RecoverRequest, service: UndoService = Depends(get_service)) -> RestoreResult:
    return service.recover(
        body.path, destination=body.destination, overwrite=body.overwrite, dry_run=body.dry_run
    )
