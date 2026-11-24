"""Remove history on purpose from the TUI: a file's or folder's whole history, or older versions.

Same rules as `undo forget` and the app: preview (dry run) first, then confirm. Files are never
touched, snapshot versions are kept, and `before` always keeps each file's latest version.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from textual.widget import Widget
from undo_core.utils.errors import UndoError

from undo_cli.tui.widgets.common import ConfirmModal, PromptModal


def _summary(r: dict[str, Any]) -> str:
    if r["versions_removed"] == 0:
        kept = r.get("versions_kept_in_snapshots") or 0
        return "Nothing to remove." + (
            f" {kept} version(s) are kept (in a snapshot)." if kept else ""
        )
    parts = [
        f"{r['versions_removed']} version(s) of {r['files_affected']} file(s) will be removed."
    ]
    if r.get("files_removed"):
        parts.append(f"{r['files_removed']} file(s) will have no history left.")
    if r.get("versions_kept_in_snapshots"):
        parts.append(f"{r['versions_kept_in_snapshots']} version(s) are kept (in a snapshot).")
    parts.append("Your files are not touched. This cannot be undone.")
    return "\n".join(parts)


def start_forget(
    widget: Widget,
    path: str,
    *,
    title: str,
    ask_path: bool = False,
    on_done: Callable[[dict[str, Any]], object] | None = None,
) -> None:
    """Ask what to remove, preview it, confirm, then remove. Runs backend calls in a thread."""
    app = widget.app
    backend = app.backend  # type: ignore[attr-defined]

    fields = []
    if ask_path:
        fields.append(("path", "Folder (the tracked folder, or a folder inside it)", path))
    fields.append(
        (
            "before",
            "Only versions older than (e.g. 30d, 2w, 2026-10-01). Leave empty to remove ALL history.",
            "",
        )
    )

    def asked(values: dict[str, str] | None) -> None:
        if values is None:
            return
        target = (values.get("path") or path).strip()
        before = values["before"].strip() or None
        widget.run_worker(lambda: preview(target, before), thread=True, group="forget")

    def preview(target: str, before: str | None) -> None:
        try:
            plan = backend.call("forget", path=target, before=before, dry_run=True)
        except UndoError as exc:
            app.call_from_thread(app.notify, exc.message, severity="error")
            return
        if plan["versions_removed"] == 0:
            app.call_from_thread(app.notify, _summary(plan), severity="warning")
            return
        scope = f"older than {before}" if before else "ALL history"
        app.call_from_thread(
            app.push_screen,
            ConfirmModal(f"Delete {scope} of\n{target}?\n\n{_summary(plan)}", "Delete", "error"),
            lambda ok: confirmed(ok, target, before),
        )

    def confirmed(ok: bool | None, target: str, before: str | None) -> None:
        if ok:
            widget.run_worker(lambda: apply(target, before), thread=True, group="forget")

    def apply(target: str, before: str | None) -> None:
        try:
            result = backend.call("forget", path=target, before=before, dry_run=False)
        except UndoError as exc:
            app.call_from_thread(app.notify, exc.message, severity="error")
            return
        message = f"Removed {result['versions_removed']} version(s)."
        if result.get("note"):
            message += f" {result['note']}."
        app.call_from_thread(app.notify, message)
        if on_done is not None:
            app.call_from_thread(on_done, result)

    app.push_screen(PromptModal(title, fields, "Preview"), asked)


def start_delete_version(
    widget: Widget, version: dict[str, Any], *, on_done: Callable[[], object] | None = None
) -> None:
    """Confirm, then delete one version (the backend refuses the latest and snapshot versions)."""
    app = widget.app
    backend = app.backend  # type: ignore[attr-defined]

    def confirmed(ok: bool | None) -> None:
        if ok:
            widget.run_worker(run, thread=True, group="forget")

    def run() -> None:
        try:
            backend.call("delete_versions", version_ids=[version["id"]], dry_run=False)
        except UndoError as exc:
            app.call_from_thread(app.notify, exc.message, severity="error")
            return
        app.call_from_thread(
            app.notify,
            f"Version {version['id']} deleted. Run GC on the Storage tab to free the space.",
        )
        if on_done is not None:
            app.call_from_thread(on_done)

    app.push_screen(
        ConfirmModal(
            f"Delete version {version['id']} of {version['relative_path']}?\n"
            "It can no longer be restored. Your file is not touched.",
            "Delete version",
            "error",
        ),
        confirmed,
    )
