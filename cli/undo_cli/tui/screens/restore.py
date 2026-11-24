"""Restore dialog: preview (dry run) first, then restore; overwriting needs an explicit checkbox."""

from __future__ import annotations

from typing import Any

from textual import work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Checkbox, DataTable, Input, Label, Static
from undo_core.utils.errors import UndoError

from undo_cli.output.render import size


class RestoreModal(ModalScreen[dict[str, Any] | None]):
    DEFAULT_CSS = """
    RestoreModal { align: center middle; }
    RestoreModal > Vertical { width: 95%; height: 85%; border: thick $primary; background: $surface; padding: 1 2; }
    RestoreModal DataTable { height: 1fr; }
    RestoreModal #summary { height: auto; margin: 1 0; }
    RestoreModal Horizontal { height: auto; align-horizontal: right; }
    RestoreModal Button { margin-left: 1; }
    """
    BINDINGS = [("escape", "close", "Close")]

    def __init__(
        self, title: str, op: str, base: dict[str, Any], default_destination: str = ""
    ) -> None:
        super().__init__()
        self.title_text = title
        self.op = op
        self.base = base
        self.default_destination = default_destination
        self.planned = False

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label(f"[bold]{self.title_text}[/bold]")
            yield Label("Destination (empty = original location):")
            yield Input(
                value=self.default_destination,
                id="dest",
                placeholder="e.g. /tmp/restored or C:\\restored",
            )
            yield Checkbox(
                "Overwrite existing files (their current content is versioned first)",
                id="overwrite",
            )
            yield Static("Press Preview to see exactly what will happen.", id="summary")
            yield DataTable(id="plan", zebra_stripes=True)
            with Horizontal():
                yield Button("Close", id="close")
                yield Button("Preview", id="preview", variant="primary")
                yield Button("Restore", id="restore", variant="warning", disabled=True)

    def on_mount(self) -> None:
        table = self.query_one(DataTable)
        table.add_columns("Action", "Destination", "Version", "Size", "Detail")

    def _args(self, dry_run: bool) -> dict[str, Any]:
        dest = self.query_one("#dest", Input).value.strip() or None
        return {
            **self.base,
            "destination": dest,
            "overwrite": self.query_one("#overwrite", Checkbox).value,
            "dry_run": dry_run,
        }

    def on_input_changed(self, _event: Input.Changed) -> None:
        self.query_one("#restore", Button).disabled = True

    def on_checkbox_changed(self, _event: Checkbox.Changed) -> None:
        self.query_one("#restore", Button).disabled = True

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "close":
            self.dismiss(None)
        elif event.button.id == "preview":
            self.run_op(True)
        elif event.button.id == "restore":
            self.run_op(False)

    @work(thread=True, exclusive=True)
    def run_op(self, dry_run: bool) -> None:
        try:
            result = self.app.backend.call(self.op, **self._args(dry_run))  # type: ignore[attr-defined]
        except UndoError as exc:
            self.app.call_from_thread(self.app.notify, exc.message, severity="error")
            return
        self.app.call_from_thread(self.show_result, result)

    def show_result(self, res: dict[str, Any]) -> None:
        table = self.query_one(DataTable)
        table.clear()
        for item in res["items"]:
            table.add_row(
                item["action"],
                item["destination"],
                str(item.get("version_id") or "-"),
                size(item["size"]),
                item.get("detail") or "",
            )
        prefix = "Preview: would " if res["dry_run"] else "Done: "
        text = (
            f"{prefix}create {res['created']}, overwrite {res['overwritten']}, identical {res['identical']}, "
            f"conflicts {res['conflicts']}, errors {res['errors']}"
        )
        if res["conflicts"]:
            text += "\n[yellow]Conflicts are left untouched: tick 'Overwrite' or choose another destination.[/yellow]"
        if not res["dry_run"] and res.get("metadata_not_restored"):
            text += f"\n[dim]Not restored: {', '.join(res['metadata_not_restored'])}[/dim]"
        self.query_one("#summary", Static).update(text)
        restore_btn = self.query_one("#restore", Button)
        if res["dry_run"]:
            restore_btn.disabled = (res["created"] + res["overwritten"]) == 0
        else:
            restore_btn.disabled = True
            self.app.notify(
                "Restore finished" if not res["errors"] else "Restore finished with errors",
                severity="information" if not res["errors"] else "error",
            )

    def action_close(self) -> None:
        self.dismiss(None)
