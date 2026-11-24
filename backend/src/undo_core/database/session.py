"""Session factories with explicit read and write transaction semantics."""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker


class SessionManager:
    """Hands out sessions.

    * ``read()`` uses a deferred transaction on the read engine (WAL readers never block writers).
    * ``write()`` serialises writers inside this process with a lock and uses
      ``BEGIN IMMEDIATE`` so writers in other processes are serialised by SQLite.
      Callers must not do slow I/O (reading/compressing files) inside ``write()``.
    """

    def __init__(self, read_engine: Engine, write_engine: Engine) -> None:
        self._read = sessionmaker(read_engine, expire_on_commit=False)
        self._write = sessionmaker(write_engine, expire_on_commit=False)
        self._write_lock = threading.RLock()

    @contextmanager
    def read(self) -> Iterator[Session]:
        session = self._read()
        try:
            yield session
        finally:
            # close() ends the read transaction and detaches objects *without*
            # expiring them, so loaded rows remain usable after the block.
            session.close()

    @contextmanager
    def write(self) -> Iterator[Session]:
        with self._write_lock:
            session = self._write()
            try:
                with session.begin():
                    yield session
            finally:
                session.close()
