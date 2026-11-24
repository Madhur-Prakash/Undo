"""Initial schema."""

from __future__ import annotations

from typing import Any

from undo_core.database.models import Base


def upgrade(conn: Any) -> None:
    Base.metadata.create_all(conn)
