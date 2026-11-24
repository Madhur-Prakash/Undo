"""Linux adapter: inotify via watchdog, watch-limit awareness, polling fallback.

inotify needs one watch per directory. When ``fs.inotify.max_user_watches``
(or ``max_user_instances``) is exhausted, scheduling fails with ENOSPC/EMFILE;
the watcher then falls back to polling for that root and reports it in
``undo status``. Raise the limit with::

    echo fs.inotify.max_user_watches=524288 | sudo tee /etc/sysctl.d/90-undo.conf
    sudo sysctl --system

Kernel queue overflows (IN_Q_OVERFLOW) are not surfaced individually by
watchdog; Undo's bounded event queue counts its own overflows and every
overflow schedules a reconciliation of the affected root.
"""

from __future__ import annotations

import errno
from pathlib import Path
from typing import Any

from undo_core.filesystem.adapters.base import PlatformAdapter

_PROC = Path("/proc/sys/fs/inotify")


def _read_int(name: str) -> int | None:
    try:
        return int((_PROC / name).read_text().strip())
    except (OSError, ValueError):
        return None


class LinuxAdapter(PlatformAdapter):
    name = "linux"
    native_backend = "inotify"

    def max_user_watches(self) -> int | None:
        return _read_int("max_user_watches")

    def is_capacity_error(self, exc: BaseException) -> bool:
        return isinstance(exc, OSError) and exc.errno in (errno.ENOSPC, errno.EMFILE)

    def capacity_hint(self, root: Path) -> str | None:
        limit = self.max_user_watches()
        return (
            f"inotify watch limit reached (fs.inotify.max_user_watches={limit}); "
            "using polling for this root. Increase the limit to restore native monitoring."
        )

    def info(self) -> dict[str, Any]:
        return {
            **super().info(),
            "max_user_watches": self.max_user_watches(),
            "max_user_instances": _read_int("max_user_instances"),
            "max_queued_events": _read_int("max_queued_events"),
        }
