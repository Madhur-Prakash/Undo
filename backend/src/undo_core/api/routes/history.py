from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse

from undo_core.api.dependencies import get_service
from undo_core.api.schemas import (
    DeleteVersionsRequest,
    ForgetRequest,
    MergeDraftRequest,
    MergeWriteRequest,
)
from undo_core.domain import (
    FileDiff,
    FileHistory,
    ForgetResult,
    MergeDraft,
    MergeSource,
    MergeWriteResult,
    VersionContent,
    VersionDetail,
    VersionDiff,
    VersionInfo,
)
from undo_core.service import UndoService

router = APIRouter(tags=["history"])


@router.get("/history/files/{file_id}", response_model=FileHistory)
def file_history(
    file_id: int, limit: int | None = Query(None, ge=1), service: UndoService = Depends(get_service)
) -> FileHistory:
    return service.file_history(file_id=file_id, limit=limit)


@router.get("/history/path", response_model=FileHistory)
def history_by_path(
    path: str, limit: int | None = Query(None, ge=1), service: UndoService = Depends(get_service)
) -> FileHistory:
    return service.file_history(path=path, limit=limit)


@router.get("/history/log", response_model=list[VersionInfo])
def activity(
    limit: int = Query(100, ge=1, le=5000),
    root_id: int | None = None,
    since: str | None = None,
    service: UndoService = Depends(get_service),
) -> list[VersionInfo]:
    return service.activity(limit=limit, root_id=root_id, since=since)


@router.post("/history/forget", response_model=ForgetResult)
def forget(body: ForgetRequest, service: UndoService = Depends(get_service)) -> ForgetResult:
    """Remove the history of a file or a folder (optionally only versions older than `before`)."""
    return service.forget(body.path, before=body.before, dry_run=body.dry_run)


@router.post("/versions/delete", response_model=ForgetResult)
def delete_versions(
    body: DeleteVersionsRequest, service: UndoService = Depends(get_service)
) -> ForgetResult:
    """Delete individual versions (not a file's latest version, not snapshot versions)."""
    return service.delete_versions(body.version_ids, dry_run=body.dry_run)


@router.get("/versions/diff", response_model=VersionDiff)
def diff(a: int, b: int, service: UndoService = Depends(get_service)) -> VersionDiff:
    return service.diff_versions(a, b)


@router.get("/versions/{version_id}/diff-file", response_model=FileDiff)
def diff_with_file(
    version_id: int, path: str | None = None, service: UndoService = Depends(get_service)
) -> FileDiff:
    """Compare a stored version with a file on disk (default: the file's current location)."""
    return service.diff_version_with_file(version_id, path)


@router.get("/versions/{version_id}/merge-source", response_model=MergeSource)
def merge_source(
    version_id: int, path: str | None = None, service: UndoService = Depends(get_service)
) -> MergeSource:
    """Both sides for a merge editor: the file on disk now and the stored version."""
    return service.merge_source(version_id, path)


@router.post("/merge/write", response_model=MergeWriteResult)
def merge_write(
    body: MergeWriteRequest, service: UndoService = Depends(get_service)
) -> MergeWriteResult:
    """Write a merged result; the file's current content is saved as a version first."""
    return service.merge_write(
        path=body.path, text=body.text, version_id=body.version_id, expected_hash=body.expected_hash
    )


@router.get("/merge/drafts", response_model=list[MergeDraft])
def merge_drafts(service: UndoService = Depends(get_service)) -> list[MergeDraft]:
    return service.list_merge_drafts()


@router.put("/merge/draft", response_model=MergeDraft)
def save_merge_draft(
    body: MergeDraftRequest, service: UndoService = Depends(get_service)
) -> MergeDraft:
    return service.save_merge_draft(
        path=body.path,
        version_id=body.version_id,
        text=body.text,
        choices=body.choices,
        edited=body.edited,
    )


@router.delete("/merge/draft")
def delete_merge_draft(path: str, service: UndoService = Depends(get_service)) -> dict[str, int]:
    return {"deleted": service.delete_merge_draft(path)}


@router.get("/versions/{version_id}", response_model=VersionDetail)
def version(version_id: int, service: UndoService = Depends(get_service)) -> VersionDetail:
    return service.get_version(version_id)


@router.get("/versions/{version_id}/preview", response_model=VersionContent)
def preview(
    version_id: int,
    max_bytes: int = Query(256 * 1024, ge=1, le=8 * 1024 * 1024),
    service: UndoService = Depends(get_service),
) -> VersionContent:
    return service.version_content(version_id, max_bytes=max_bytes)


@router.get("/versions/{version_id}/content")
def content(version_id: int, service: UndoService = Depends(get_service)) -> StreamingResponse:
    """Raw content stream. Integrity is verified on restore; use restore for guaranteed copies."""
    detail, blocks = service.iter_version_bytes(version_id)
    name = detail.file.name
    return StreamingResponse(
        blocks,
        media_type="application/octet-stream",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(name)}"},
    )
