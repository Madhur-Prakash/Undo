"""Shared fixtures: an initialised, isolated Undo data directory and a tracked folder."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from helpers import write  # noqa: F401  (re-exported for convenience)
from undo_core.context import UndoContext
from undo_core.service import UndoService
from undo_core.versioning.capture import RootRef


@pytest.fixture
def ctx(tmp_path: Path) -> Iterator[UndoContext]:
    context = UndoContext.open(tmp_path / "undo-data", require_initialized=False)
    context.initialize()
    context.settings_store.update(
        {
            "capture": {
                "stable_seconds": 0,
                "debounce_seconds": 0.2,
                "retry_seconds": 0.05,
                "max_retries": 3,
            },
            "daemon": {"gc_grace_seconds": 0},
            "api": {"port": 0},
        }
    )
    yield context
    context.close()


@pytest.fixture
def service(ctx: UndoContext) -> UndoService:
    return UndoService(ctx)


@pytest.fixture
def work(tmp_path: Path) -> Path:
    d = tmp_path / "work"
    d.mkdir()
    return d


@pytest.fixture
def tracked(service: UndoService, work: Path) -> RootRef:
    result = service.add_root(str(work), scan=True)
    return RootRef(result.root.id, Path(result.root.path))
