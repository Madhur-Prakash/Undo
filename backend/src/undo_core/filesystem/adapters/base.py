"""Generic adapter: watchdog's best native observer with a polling fallback."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from watchdog.observers import Observer
from watchdog.observers.api import BaseObserver
from watchdog.observers.polling import PollingObserver


class PlatformAdapter:
    name = "generic"
    native_backend = "watchdog-default"

    def create_native_observer(self) -> BaseObserver:
        return Observer()

    def create_polling_observer(self, interval: float) -> BaseObserver:
        return PollingObserver(timeout=interval)

    def is_capacity_error(self, exc: BaseException) -> bool:
        """True if scheduling failed because of a kernel resource limit."""
        return False

    def capacity_hint(self, root: Path) -> str | None:
        return None

    def info(self) -> dict[str, Any]:
        return {"adapter": self.name, "native_backend": self.native_backend}
