from __future__ import annotations

from collections.abc import Callable

from fastapi import APIRouter, Depends

from undo_core.api.dependencies import get_service, get_shutdown
from undo_core.domain import DoctorCheck, HealthInfo, StatusInfo
from undo_core.service import UndoService
from undo_core.utils.errors import DaemonNotRunningError

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthInfo)
def health(service: UndoService = Depends(get_service)) -> HealthInfo:
    info = service.health()
    if info is None:
        raise DaemonNotRunningError("No daemon hooks attached")
    return info


@router.get("/status", response_model=StatusInfo)
def status(service: UndoService = Depends(get_service)) -> StatusInfo:
    return service.status()


@router.get("/doctor", response_model=list[DoctorCheck])
def doctor(service: UndoService = Depends(get_service)) -> list[DoctorCheck]:
    return service.doctor()


@router.post("/daemon/shutdown")
def shutdown(stop: Callable[[], None] = Depends(get_shutdown)) -> dict[str, str]:
    stop()
    return {"status": "stopping"}
