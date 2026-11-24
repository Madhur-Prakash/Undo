"""Storage statistics, verification and garbage collection."""

from __future__ import annotations

from typing import Any

from textual import work
from textual.app import ComposeResult
from textual.containers import Horizontal, VerticalScroll
from textual.widgets import Button, Label, Static
from undo_core.utils.errors import UndoError
from undo_core.utils.sizes import format_size

from undo_cli.output.render import storage_stats
from undo_cli.tui.widgets.common import ConfirmModal, DataPane


class StoragePane(DataPane):
    DEFAULT_CSS = "StoragePane Horizontal { height: 3; }"

    def compose(self) -> ComposeResult:
        yield Label("[bold]Storage[/bold]")
        with Horizontal():
            yield Button("Refresh", id="refresh")
            yield Button("Verify", id="verify", variant="primary")
            yield Button("GC preview", id="gc-preview")
            yield Button("Run GC", id="gc", variant="warning")
            yield Button("Retention preview", id="retention")
            yield Button("Apply retention", id="retention-apply", variant="error")
        with VerticalScroll():
            yield Static(id="stats")
            yield Static(id="result")

    def fetch(self) -> Any:
        return self.backend.call("storage_stats")

    def show(self, data: dict[str, Any]) -> None:
        self.query_one("#stats", Static).update(storage_stats(data))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id
        if bid == "refresh":
            self.reload()
        elif bid == "verify":
            self.run("verify_storage", full=True)
        elif bid == "gc-preview":
            self.run("garbage_collect", dry_run=True)
        elif bid == "retention":
            self.run("apply_retention", dry_run=True)
        elif bid == "retention-apply":

            def apply(ok: bool | None) -> None:
                if ok:
                    self.apply_retention_now()

            self.app.push_screen(
                ConfirmModal(
                    "Remove old versions now, according to the retention policy, and free the space?\n"
                    "The latest version of every file, deleted files' last content and snapshot "
                    "versions are always kept. Use 'Retention preview' first to see the counts.",
                    "Apply retention",
                    "error",
                ),
                apply,
            )
        elif bid == "gc":

            def confirmed(ok: bool | None) -> None:
                if ok:
                    self.run("garbage_collect", dry_run=False)

            self.app.push_screen(
                ConfirmModal(
                    "Delete stored data that no version or snapshot references?", "Run GC"
                ),
                confirmed,
            )

    @work(thread=True, group="storage-op")
    def apply_retention_now(self) -> None:
        self.app.call_from_thread(self.app.notify, "Applying retention ...")
        try:
            r = self.backend.call("apply_retention", dry_run=False)
            g = self.backend.call("garbage_collect", dry_run=False)
        except UndoError as exc:
            self.app.call_from_thread(self.app.notify, exc.message, severity="error")
            return
        text = (
            f"[bold]Retention[/bold]: removed {r['versions_removed']} versions of "
            f"{r['files_affected']} files · garbage collection freed {format_size(g['reclaimed_bytes'])}"
        )
        self.app.call_from_thread(self.query_one("#result", Static).update, text)
        self.app.call_from_thread(self.reload)

    @work(thread=True, group="storage-op")
    def run(self, op: str, **kwargs: Any) -> None:
        self.app.call_from_thread(self.app.notify, "Working ...")
        try:
            r = self.backend.call(op, **kwargs)
        except UndoError as exc:
            self.app.call_from_thread(self.app.notify, exc.message, severity="error")
            return
        if op == "verify_storage":
            text = (
                f"[bold]Verification[/bold]: {'[green]healthy[/green]' if r['healthy'] else '[red]problems found[/red]'}\n"
                f"checked {r['checked_blobs']} blobs, {r['checked_chunks']} chunks · missing {len(r['missing'])} · "
                f"corrupt {len(r['corrupt'])} · repaired {len(r['repaired'])} · orphans {len(r['orphan_files'])} · {r['duration_seconds']}s"
            )
        elif op == "garbage_collect":
            amount = (
                r["reclaimable_bytes"] + r["orphan_bytes"] if r["dry_run"] else r["reclaimed_bytes"]
            )
            text = (
                f"[bold]Garbage collection{' preview' if r['dry_run'] else ''}[/bold]: "
                f"{r['candidate_blobs']} blobs, {r['candidate_chunks']} chunks, {r['orphan_files']} orphan files · "
                f"{'reclaimable' if r['dry_run'] else 'reclaimed'} {format_size(amount)} · "
                f"{r['protected_by_grace']} protected by grace period"
            )
        else:
            text = (
                f"[bold]Retention preview[/bold]: {r['versions_removed']} of {r['versions_examined']} versions would be "
                f"removed across {r['files_affected']} files (~{format_size(r['estimated_reclaim_bytes'])})"
            )
        self.app.call_from_thread(self.query_one("#result", Static).update, text)
        self.app.call_from_thread(self.reload)
