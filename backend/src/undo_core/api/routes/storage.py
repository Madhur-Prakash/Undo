from __future__ import annotations

from fastapi import APIRouter, Depends

from undo_core.api.dependencies import get_service
from undo_core.api.schemas import DryRunRequest, VerifyRequest
from undo_core.domain import GCReport, RetentionReport, StorageStats, VerifyReport
from undo_core.service import UndoService

router = APIRouter(tags=["storage"])


@router.get("/storage/stats", response_model=StorageStats)
def stats(service: UndoService = Depends(get_service)) -> StorageStats:
    return service.storage_stats()


@router.post("/storage/verify", response_model=VerifyReport)
def verify(body: VerifyRequest, service: UndoService = Depends(get_service)) -> VerifyReport:
    return service.verify_storage(full=body.full, repair=body.repair)


@router.post("/storage/gc", response_model=GCReport)
def gc(body: DryRunRequest, service: UndoService = Depends(get_service)) -> GCReport:
    return service.garbage_collect(dry_run=body.dry_run)


@router.post("/storage/retention", response_model=RetentionReport)
def retention(body: DryRunRequest, service: UndoService = Depends(get_service)) -> RetentionReport:
    return service.apply_retention(dry_run=body.dry_run)
