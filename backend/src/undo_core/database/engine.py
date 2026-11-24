"""SQLite engine configuration (WAL, foreign keys, busy timeout) and the Database facade."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import QueuePool

from undo_core.database.migrations import run_migrations
from undo_core.database.session import SessionManager

BUSY_TIMEOUT_MS = 30_000


def _make_engine(db_path: Path, *, immediate: bool) -> Engine:
    engine = create_engine(
        f"sqlite:///{db_path.as_posix()}",
        connect_args={"check_same_thread": False, "timeout": BUSY_TIMEOUT_MS / 1000},
        poolclass=QueuePool,
        pool_size=4 if immediate else 8,
        max_overflow=4,
        pool_pre_ping=False,
    )

    @event.listens_for(engine, "connect")
    def _on_connect(dbapi_conn: Any, _record: Any) -> None:
        # Take control of transactions ourselves so BEGIN IMMEDIATE can be issued.
        dbapi_conn.isolation_level = None
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
        cur.execute("PRAGMA synchronous=NORMAL")
        cur.execute("PRAGMA temp_store=MEMORY")
        cur.close()

    @event.listens_for(engine, "begin")
    def _on_begin(conn: Any) -> None:
        conn.exec_driver_sql("BEGIN IMMEDIATE" if immediate else "BEGIN")

    return engine


class Database:
    def __init__(self, db_path: Path) -> None:
        self.path = db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.write_engine = _make_engine(db_path, immediate=True)
        self.read_engine = _make_engine(db_path, immediate=False)
        self.sessions = SessionManager(self.read_engine, self.write_engine)

    def initialize(self) -> list[str]:
        """Apply pending migrations. Returns the names of migrations applied."""
        return run_migrations(self.write_engine)

    @contextmanager
    def read(self) -> Iterator[Session]:
        with self.sessions.read() as session:
            yield session

    @contextmanager
    def write(self) -> Iterator[Session]:
        with self.sessions.write() as session:
            yield session

    def size_bytes(self) -> int:
        total = 0
        for suffix in ("", "-wal", "-shm"):
            p = Path(str(self.path) + suffix)
            if p.exists():
                total += p.stat().st_size
        return total

    def quick_check(self) -> list[str]:
        problems: list[str] = []
        with self.write_engine.connect() as conn:
            rows = conn.execute(text("PRAGMA quick_check")).fetchall()
            for (msg,) in rows:
                if msg != "ok":
                    problems.append(f"quick_check: {msg}")
            for row in conn.execute(text("PRAGMA foreign_key_check")).fetchall():
                problems.append(f"foreign_key_check: {tuple(row)}")
        return problems

    def checkpoint(self) -> None:
        with self.write_engine.connect() as conn:
            conn.exec_driver_sql("PRAGMA wal_checkpoint(TRUNCATE)")

    def close(self) -> None:
        self.write_engine.dispose()
        self.read_engine.dispose()
