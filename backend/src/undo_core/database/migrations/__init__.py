"""Minimal ordered migration runner.

Each migration module ``mNNNN_name.py`` exposes ``upgrade(conn)``. Applied
migrations are recorded in ``schema_migrations``. Migrations run inside a
single write transaction each, so a failed migration leaves the schema intact.
"""

from __future__ import annotations

import importlib
import pkgutil
from collections.abc import Callable
from typing import Any, cast

from sqlalchemy import Engine, text

from undo_core.utils.timeutil import utcnow


def _discover() -> list[tuple[str, Callable[[Any], None]]]:
    found: list[tuple[str, Callable[[Any], None]]] = []
    for info in pkgutil.iter_modules(__path__):
        if info.name.startswith("m") and info.name[1:5].isdigit():
            module = importlib.import_module(f"{__name__}.{info.name}")
            found.append((info.name, cast(Callable[[Any], None], module.upgrade)))
    return sorted(found)


def run_migrations(engine: Engine) -> list[str]:
    applied: list[str] = []
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE IF NOT EXISTS schema_migrations ("
                "name TEXT PRIMARY KEY, applied_at TIMESTAMP NOT NULL)"
            )
        )
        done = {row[0] for row in conn.execute(text("SELECT name FROM schema_migrations"))}
    for name, upgrade in _discover():
        if name in done:
            continue
        with engine.begin() as conn:
            upgrade(conn)
            conn.execute(
                text("INSERT INTO schema_migrations (name, applied_at) VALUES (:n, :t)"),
                {"n": name, "t": utcnow().isoformat(sep=" ")},
            )
        applied.append(name)
    return applied


def current_version(engine: Engine) -> str | None:
    with engine.connect() as conn:
        try:
            row = conn.execute(
                text("SELECT name FROM schema_migrations ORDER BY name DESC LIMIT 1")
            ).first()
        except Exception:
            return None
    return row[0] if row else None
