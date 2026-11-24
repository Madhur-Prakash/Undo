"""Composition root: wires settings, database, storage and engines for one data directory."""

from __future__ import annotations

import threading
import time
from pathlib import Path

from undo_core.config.defaults import BUILTIN_EXCLUSIONS
from undo_core.config.settings import Settings, SettingsStore
from undo_core.config.token import ensure_token
from undo_core.daemon.locking import KeyedLocks
from undo_core.database.engine import Database
from undo_core.database.repositories import ExclusionRepository
from undo_core.filesystem.exclusions import ExclusionMatcher, ExclusionRule
from undo_core.filesystem.reconciler import Reconciler
from undo_core.platform.paths import UndoPaths
from undo_core.platform.permissions import secure_dir
from undo_core.recovery.restore import RestoreEngine
from undo_core.storage.blob_store import BlobStore
from undo_core.utils.errors import NotInitializedError
from undo_core.versioning.capture import CaptureEngine, RootRef

MATCHER_TTL = 30.0


class UndoContext:
    def __init__(self, paths: UndoPaths) -> None:
        self.paths = paths
        self.settings_store = SettingsStore(paths.config_path)
        self.db = Database(paths.db_path)
        self.store = BlobStore(paths, self.db, lambda: self.settings)
        self.locks = KeyedLocks()
        self.capture = CaptureEngine(
            self.db, self.store, lambda: self.settings, self.matcher_for, self.locks
        )
        self.reconciler = Reconciler(self.db, self.capture, self.matcher_for, lambda: self.settings)
        self.restore = RestoreEngine(self.db, self.store, self.capture)
        self._matchers: dict[int, tuple[float, tuple[object, ...], ExclusionMatcher]] = {}
        self._matcher_lock = threading.Lock()

    # ------------------------------------------------------------------ factory
    @classmethod
    def open(
        cls, data_dir: str | Path | None = None, *, require_initialized: bool = True
    ) -> UndoContext:
        paths = UndoPaths.resolve(data_dir)
        if require_initialized and not paths.is_initialized():
            raise NotInitializedError(
                f"Undo is not initialised in {paths.data_dir}. Run `undo init` first."
            )
        ctx = cls(paths)
        if paths.is_initialized():
            ctx.db.initialize()  # apply pending migrations
        return ctx

    def initialize(self) -> list[str]:
        """Create the data directory, settings, database schema and API token (idempotent)."""
        self.paths.ensure()
        secure_dir(self.paths.data_dir)
        if not self.paths.config_path.exists():
            self.settings_store.save(Settings())
        applied = self.db.initialize()
        ensure_token(self.paths.token_path)
        return applied

    @property
    def settings(self) -> Settings:
        return self.settings_store.current

    # ------------------------------------------------------------------ exclusions
    def exclusion_rules(self, root_id: int | None) -> list[ExclusionRule]:
        rules = [ExclusionRule(p, "builtin") for p in BUILTIN_EXCLUSIONS]
        rules += [ExclusionRule(p, "default") for p in self.settings.exclusions.defaults]
        with self.db.read() as s:
            for ex in ExclusionRepository(s).for_root(root_id):
                rules.append(ExclusionRule(ex.pattern, "user", ex.root_id, ex.id))
        return rules

    def matcher_for(self, root: RootRef) -> ExclusionMatcher:
        settings = self.settings
        signature = (
            tuple(settings.exclusions.defaults),
            settings.monitor.exclude_hidden,
            str(root.path),
        )
        now = time.monotonic()
        with self._matcher_lock:
            cached = self._matchers.get(root.id)
            if cached and cached[1] == signature and now - cached[0] < MATCHER_TTL:
                return cached[2]
        matcher = ExclusionMatcher(
            self.exclusion_rules(root.id),
            root_path=root.path,
            protected_dirs=[self.paths.data_dir],
            exclude_hidden=settings.monitor.exclude_hidden,
        )
        with self._matcher_lock:
            self._matchers[root.id] = (now, signature, matcher)
        return matcher

    def invalidate_exclusions(self) -> None:
        with self._matcher_lock:
            self._matchers.clear()

    def close(self) -> None:
        self.db.close()
