"""Shared CLI state, error handling and backend access."""

from __future__ import annotations

import contextlib
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

import typer
from undo_core.platform.paths import UndoPaths
from undo_core.utils.errors import LockedError, NotInitializedError, UndoError

from undo_cli.client import Backend, get_backend
from undo_cli.output import render

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_CONFLICT = 5


@dataclass
class State:
    data_dir: str | None = None
    local_only: bool = False

    @property
    def paths(self) -> UndoPaths:
        return UndoPaths.resolve(self.data_dir)

    def backend(self) -> Backend:
        return get_backend(self.data_dir, local_only=self.local_only)


def state(ctx: typer.Context) -> State:
    obj = ctx.find_root().obj
    if not isinstance(obj, State):
        obj = State()
        ctx.find_root().obj = obj
    return obj


_HINTS: dict[type[UndoError], str] = {
    NotInitializedError: "Run `undo init` to create the data directory.",
    LockedError: "Another Undo process holds the data directory. If it is the daemon, wait until it is ready.",
}


@contextlib.contextmanager
def handle_errors() -> Iterator[None]:
    try:
        yield
    except UndoError as exc:
        hint = next((h for cls, h in _HINTS.items() if isinstance(exc, cls)), None)
        render.error(exc.message, hint)
        raise typer.Exit(exc.exit_code) from None
    except KeyboardInterrupt:
        render.err_console.print("[yellow]Interrupted[/yellow]")
        raise typer.Exit(130) from None


@contextlib.contextmanager
def session(ctx: typer.Context) -> Iterator[Backend]:
    with handle_errors():
        backend = state(ctx).backend()
        try:
            yield backend
        finally:
            backend.close()


def call(ctx: typer.Context, op: str, *, spinner: str | None = None, **kwargs: Any) -> Any:
    """Run one backend operation with error handling (and an optional spinner)."""
    with session(ctx) as backend:
        if spinner:
            with render.console.status(spinner):
                return backend.call(op, **kwargs)
        return backend.call(op, **kwargs)


def resolve_root(backend: Backend, ref: str | None) -> int | None:
    """Turn a root id or path into a root id (None when ref is None)."""
    if ref is None:
        return None
    if ref.isdigit():
        return int(ref)
    from undo_core.platform.paths import is_within, path_key, resolve_root_path

    target = resolve_root_path(ref)
    roots = backend.call("list_roots")
    exact = [r for r in roots if path_key(r["path"]) == path_key(str(target))]
    if exact:
        return int(exact[0]["id"])
    inside = [r for r in roots if is_within(str(target), r["path"])]
    if inside:
        return int(max(inside, key=lambda r: len(r["path"]))["id"])
    raise UndoError(f"{ref} is not a tracked root (see `undo roots`)")
