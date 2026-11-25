"""Backend access for the CLI and TUI.

* :class:`RemoteBackend` talks to a running daemon over the authenticated local API.
* :class:`LocalBackend` runs :class:`UndoService` in-process when no daemon runs.
  Write operations take the data-directory process lock first, so a CLI command
  can never write concurrently with a daemon or another CLI process.

Both expose ``call(op, **kwargs)`` with the service method names and return
plain JSON-compatible data, so rendering code is identical in both modes.
"""

from __future__ import annotations

import re
from typing import Any

import httpx
from pydantic import BaseModel
from undo_core.context import UndoContext
from undo_core.daemon.lifecycle import DaemonInfo, discover
from undo_core.daemon.locking import ProcessLock
from undo_core.platform.paths import UndoPaths
from undo_core.service import UndoService
from undo_core.utils import errors as E

# op -> (HTTP method, path template, where non-path kwargs go)
OPS: dict[str, tuple[str, str, str]] = {
    "status": ("GET", "/status", "query"),
    "health": ("GET", "/health", "query"),
    "doctor": ("GET", "/doctor", "query"),
    "list_roots": ("GET", "/roots", "query"),
    "get_root": ("GET", "/roots/{root_ref_}", "query"),
    "add_root": ("POST", "/roots", "body"),
    "set_root_enabled": ("PATCH", "/roots/{ref}", "body"),
    "remove_root": ("DELETE", "/roots/{ref}", "query"),
    "scan": ("POST", "/scan", "body"),
    "list_files": ("GET", "/files", "query"),
    "deleted_files": ("GET", "/files/deleted", "query"),
    "skipped_files": ("GET", "/files/skipped", "query"),
    "resolve_file": ("GET", "/files/resolve", "query"),
    "search": ("GET", "/files/search", "query"),
    "get_file": ("GET", "/files/{file_id}", "query"),
    "file_history": ("GET", "/history/path", "query"),
    "activity": ("GET", "/history/log", "query"),
    "get_version": ("GET", "/versions/{version_id}", "query"),
    "version_content": ("GET", "/versions/{version_id}/preview", "query"),
    "diff_versions": ("GET", "/versions/diff", "query"),
    "diff_version_with_file": ("GET", "/versions/{version_id}/diff-file", "query"),
    "merge_source": ("GET", "/versions/{version_id}/merge-source", "query"),
    "merge_write": ("POST", "/merge/write", "body"),
    "list_merge_drafts": ("GET", "/merge/drafts", "query"),
    "save_merge_draft": ("PUT", "/merge/draft", "body"),
    "save_merge_resolution": ("PUT", "/merge/resolution", "body"),
    "delete_merge_draft": ("DELETE", "/merge/draft", "query"),
    "restore": ("POST", "/restore", "body"),
    "restore_version": ("POST", "/restore/version", "body"),
    "recover": ("POST", "/restore/recover", "body"),
    "create_snapshot": ("POST", "/snapshots", "body"),
    "list_snapshots": ("GET", "/snapshots", "query"),
    "get_snapshot": ("GET", "/snapshots/{ref}", "query"),
    "diff_snapshots": ("GET", "/snapshots/{a}/diff/{b}", "query"),
    "restore_snapshot": ("POST", "/snapshots/{ref}/restore", "body"),
    "delete_snapshot": ("DELETE", "/snapshots/{ref}", "query"),
    "rename_snapshot": ("PATCH", "/snapshots/{ref}", "body"),
    "storage_stats": ("GET", "/storage/stats", "query"),
    "verify_storage": ("POST", "/storage/verify", "body"),
    "garbage_collect": ("POST", "/storage/gc", "body"),
    "apply_retention": ("POST", "/storage/retention", "body"),
    "forget": ("POST", "/history/forget", "body"),
    "delete_versions": ("POST", "/versions/delete", "body"),
    "list_exclusions": ("GET", "/exclusions", "query"),
    "add_exclusion": ("POST", "/exclusions", "body"),
    "remove_exclusion": ("POST", "/exclusions/remove", "body"),
    "get_settings": ("GET", "/settings", "query"),
    "set_setting": ("PUT", "/settings", "body"),
    "update_settings": ("PATCH", "/settings", "raw"),
}

WRITE_OPS = {
    "add_root",
    "set_root_enabled",
    "remove_root",
    "scan",
    "restore",
    "restore_version",
    "recover",
    "create_snapshot",
    "restore_snapshot",
    "delete_snapshot",
    "rename_snapshot",
    "verify_storage",
    "garbage_collect",
    "apply_retention",
    "forget",
    "delete_versions",
    "merge_write",
    "save_merge_draft",
    "save_merge_resolution",
    "delete_merge_draft",
    "add_exclusion",
    "remove_exclusion",
    "set_setting",
    "update_settings",
}
# Dry runs only read, so they do not need the lock in local mode.
_DRY_RUN_CAPABLE = {
    "restore",
    "restore_version",
    "recover",
    "restore_snapshot",
    "garbage_collect",
    "apply_retention",
    "forget",
    "delete_versions",
}

_ERRORS: dict[str, type[E.UndoError]] = {
    cls.code: cls
    for cls in (
        E.NotInitializedError,
        E.NotFoundError,
        E.ConflictError,
        E.InvalidInputError,
        E.PathOutsideRootError,
        E.UnsafePathError,
        E.LockedError,
        E.DaemonNotRunningError,
        E.StorageIntegrityError,
        E.AuthenticationError,
    )
}


def jsonable(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, list):
        return [jsonable(v) for v in value]
    if isinstance(value, dict):
        return {k: jsonable(v) for k, v in value.items()}
    return value


class Backend:
    mode = "unknown"
    description = ""

    def call(self, op: str, **kwargs: Any) -> Any:
        raise NotImplementedError

    def close(self) -> None:
        return None

    def __enter__(self) -> Backend:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


class LocalBackend(Backend):
    mode = "local"

    def __init__(self, paths: UndoPaths) -> None:
        self.paths = paths
        self.ctx = UndoContext.open(paths.data_dir)
        self.service = UndoService(self.ctx)
        self.lock = ProcessLock(paths.lock_path)
        self.description = f"in-process (daemon not running), data: {paths.data_dir}"

    def call(self, op: str, **kwargs: Any) -> Any:
        if op not in OPS:
            raise E.InvalidInputError(f"Unknown operation {op}")
        if op == "health":
            return None
        needs_lock = op in WRITE_OPS and not (op in _DRY_RUN_CAPABLE and kwargs.get("dry_run"))
        if needs_lock and not self.lock.held:
            self.lock.acquire(purpose="undo-cli")
        method = getattr(self.service, op)
        return jsonable(
            method(**{k: v for k, v in kwargs.items() if v is not None or k == "value"})
        )

    def close(self) -> None:
        self.lock.release()
        self.ctx.close()


class RemoteError(E.UndoError):
    pass


class RemoteBackend(Backend):
    mode = "daemon"

    def __init__(self, info: DaemonInfo, token: str, timeout: float | None = None) -> None:
        self.info = info
        self.client = httpx.Client(
            base_url=info.base_url,
            headers={"Authorization": f"Bearer {token}"},
            timeout=httpx.Timeout(timeout, connect=5.0),
        )
        self.description = f"daemon pid {info.pid} at {info.base_url}"

    def call(self, op: str, **kwargs: Any) -> Any:
        if op not in OPS:
            raise E.InvalidInputError(f"Unknown operation {op}")
        method, template, placement = OPS[op]
        if op == "file_history" and kwargs.get("file_id") is not None:
            template = "/history/files/{file_id}"
        names = re.findall(r"{(\w+)}", template)
        path = template.format(**{n: kwargs.pop(n) for n in names})
        payload = {k: v for k, v in kwargs.items() if v is not None}
        if op == "file_history":
            payload.pop("file_id", None)
        try:
            if placement == "raw":
                resp = self.client.request(method, path, json=kwargs.get("values", {}))
            elif placement == "body":
                resp = self.client.request(method, path, json=payload)
            else:
                params = {
                    k: (str(v).lower() if isinstance(v, bool) else v) for k, v in payload.items()
                }
                resp = self.client.request(method, path, params=params)
        except httpx.HTTPError as exc:
            raise E.DaemonNotRunningError(f"Lost connection to the daemon: {exc}") from exc
        if resp.status_code >= 400:
            try:
                err = resp.json()["error"]
            except (ValueError, KeyError, TypeError):
                err = {"code": "http_error", "message": resp.text[:500], "details": {}}
            cls = _ERRORS.get(err.get("code", ""), RemoteError)
            error = cls(err.get("message", "error"), details=err.get("details"))
            error.status = resp.status_code
            raise error
        return resp.json()

    def close(self) -> None:
        self.client.close()


def get_backend(data_dir: str | None = None, *, local_only: bool = False) -> Backend:
    paths = UndoPaths.resolve(data_dir)
    if not paths.is_initialized():
        raise E.NotInitializedError(
            f"Undo is not initialised in {paths.data_dir}. Run `undo init`."
        )
    if not local_only:
        found = discover(paths)
        if found:
            return RemoteBackend(*found)
    return LocalBackend(paths)
