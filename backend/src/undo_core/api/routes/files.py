from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from undo_core.api.dependencies import get_service
from undo_core.domain import FileInfo, FilePage, SearchHit, SkipInfo
from undo_core.service import UndoService

router = APIRouter(tags=["files"])


@router.get("/files", response_model=FilePage)
def list_files(
    root_id: int | None = None,
    query: str | None = None,
    include_deleted: bool = False,
    deleted_only: bool = False,
    prefix: str | None = None,
    limit: int = Query(200, ge=1, le=5000),
    offset: int = Query(0, ge=0),
    service: UndoService = Depends(get_service),
) -> FilePage:
    return service.list_files(
        root_id=root_id,
        query=query,
        include_deleted=include_deleted,
        deleted_only=deleted_only,
        prefix=prefix,
        limit=limit,
        offset=offset,
    )


@router.get("/files/deleted", response_model=list[FileInfo])
def deleted_files(
    root_id: int | None = None,
    path: str | None = None,
    limit: int = Query(1000, ge=1, le=100000),
    service: UndoService = Depends(get_service),
) -> list[FileInfo]:
    return service.deleted_files(root_id=root_id, path=path, limit=limit)


@router.get("/files/skipped", response_model=list[SkipInfo])
def skipped_files(
    root_id: int | None = None,
    limit: int = Query(1000, ge=1, le=100000),
    service: UndoService = Depends(get_service),
) -> list[SkipInfo]:
    return service.skipped_files(root_id=root_id, limit=limit)


@router.get("/files/resolve", response_model=FileInfo)
def resolve(path: str, service: UndoService = Depends(get_service)) -> FileInfo:
    return service.resolve_file(path)


@router.get("/files/search", response_model=list[SearchHit])
def search(
    query: str, limit: int = Query(100, ge=1, le=1000), service: UndoService = Depends(get_service)
) -> list[SearchHit]:
    return service.search(query, limit=limit)


@router.get("/files/{file_id}", response_model=FileInfo)
def get_file(file_id: int, service: UndoService = Depends(get_service)) -> FileInfo:
    return service.get_file(file_id)
