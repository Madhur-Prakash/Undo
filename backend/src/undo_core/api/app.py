"""FastAPI application factory. Bound to loopback by the daemon; every route except /ping needs the token."""

from __future__ import annotations

from collections.abc import Callable

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from undo_core import API_VERSION, __version__
from undo_core.api.dependencies import require_token
from undo_core.api.routes import (
    files,
    health,
    history,
    restore,
    roots,
    settings,
    snapshots,
    storage,
)
from undo_core.service import UndoService
from undo_core.utils.errors import UndoError
from undo_core.utils.logging import get_logger

log = get_logger(__name__)
PREFIX = f"/api/{API_VERSION}"


def create_app(
    service: UndoService, *, token: str, on_shutdown: Callable[[], None] | None = None
) -> FastAPI:
    app = FastAPI(
        title="Undo local API",
        version=__version__,
        description="Local, token-protected API of the Undo daemon.",
        openapi_url=f"{PREFIX}/openapi.json",
        docs_url=f"{PREFIX}/docs",
        redoc_url=None,
    )
    app.state.service = service
    app.state.token = token
    app.state.on_shutdown = on_shutdown or (lambda: None)

    @app.exception_handler(UndoError)
    async def _undo_error(_request: Request, exc: UndoError) -> JSONResponse:
        return JSONResponse(status_code=exc.status, content={"error": exc.to_dict()})

    @app.exception_handler(RequestValidationError)
    async def _validation(_request: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "invalid_input",
                    "message": "Invalid request",
                    "details": {"errors": exc.errors()},
                }
            },
        )

    @app.exception_handler(Exception)
    async def _unexpected(_request: Request, exc: Exception) -> JSONResponse:
        log.exception("unhandled API error")
        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "code": "internal_error",
                    "message": f"{type(exc).__name__}: {exc}",
                    "details": {},
                }
            },
        )

    @app.get(f"{PREFIX}/ping", tags=["health"])
    def ping() -> dict[str, str]:
        """Unauthenticated liveness probe used for discovery (reveals no data)."""
        return {"app": "undo", "version": __version__, "api_version": API_VERSION}

    auth = [Depends(require_token)]
    for module in (health, roots, files, history, restore, snapshots, storage, settings):
        app.include_router(module.router, prefix=PREFIX, dependencies=auth)
    return app
