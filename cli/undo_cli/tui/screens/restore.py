"""Restore dialog: preview (dry run) first, then restore; overwriting needs an explicit checkbox."""

from __future__ import annotations

from typing import Any

from rich.console import Group
from textual import work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Checkbox, DataTable, Input, Label, Static
from undo_core.utils.errors import UndoError

from undo_cli.output import render
from undo_cli.output.render import size

# Preview order: what needs attention first.
ACTION_ORDER = {
    "conflict": 0,
    "error": 1,
    "missing_blob": 2,
    "overwrite": 3,
    "create": 4,
    "identical": 5,
}
FILTERS = ["all", "conflict", "error", "overwrite", "create", "identical"]


class RestoreModal(ModalScreen[dict[str, Any] | None]):
    DEFAULT_CSS = """
    RestoreModal { align: center middle; }
    RestoreModal > Vertical { width: 95%; height: 85%; border: thick $primary; background: $surface; padding: 1 2; }
    RestoreModal DataTable { height: 1fr; }
    RestoreModal #summary { height: auto; margin: 1 0; }
    RestoreModal Horizontal { height: auto; align-horizontal: right; }
    RestoreModal Button { margin-left: 1; }
    """
    BINDINGS = [
        ("escape", "close", "Close"),
        ("c", "compare", "Compare with disk"),
        ("t", "next_filter", "Filter by outcome"),
        ("m", "merge", "Resolve (merge)"),
    ]

    def __init__(
        self, title: str, op: str, base: dict[str, Any], default_destination: str = ""
    ) -> None:
        super().__init__()
        self.title_text = title
        self.op = op
        self.base = base
        self.default_destination = default_destination
        self.planned = False
        self.result: dict[str, Any] | None = None
        self.filter = "all"
        self.rows: list[dict[str, Any]] = []

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

    def fill_table(self) -> None:
        """Rows sorted with conflicts and errors first, limited to the chosen outcome."""
        table = self.query_one(DataTable)
        table.clear()
        items = (self.result or {}).get("items", [])
        self.rows = sorted(
            (i for i in items if self.filter == "all" or i["action"] == self.filter),
            key=lambda i: (ACTION_ORDER.get(i["action"], 9), i["destination"]),
        )
        for item in self.rows:
            table.add_row(
                item["action"],
                item["destination"],
                str(item.get("version_id") or "-"),
                size(item["size"]),
                item.get("detail") or "",
            )

    def action_next_filter(self) -> None:
        if self.result is None:
            return
        self.filter = FILTERS[(FILTERS.index(self.filter) + 1) % len(FILTERS)]
        self.fill_table()
        self.app.notify(f"Showing: {self.filter} ({len(self.rows)})")

    def action_merge(self) -> None:
        table = self.query_one(DataTable)
        if not self.rows or table.row_count == 0:
            return
        item = self.rows[table.cursor_row]
        if not item.get("version_id") or item["action"] == "identical":
            self.app.notify("Nothing to resolve for this item", severity="warning")
            return
        from undo_cli.tui.screens.merge import MergeScreen

        def done(written: bool | None) -> None:
            if written:
                self.run_op(True)  # preview again with the merged file

        self.app.push_screen(MergeScreen(item["version_id"], item["destination"]), done)

    def action_compare(self) -> None:
        table = self.query_one(DataTable)
        if not self.rows or table.row_count == 0:
            return
        item = self.rows[table.cursor_row]
        if not item.get("version_id"):
            self.app.notify("This item has no stored version to compare", severity="warning")
            return
        self.fetch_compare(item["version_id"], item["destination"])

    @work(thread=True, group="compare")
    def fetch_compare(self, version_id: int, path: str) -> None:
        try:
            d = self.app.backend.call(  # type: ignore[attr-defined]
                "diff_version_with_file", version_id=version_id, path=path
            )
        except UndoError as exc:
            self.app.call_from_thread(self.app.notify, exc.message, severity="error")
            return
        from undo_cli.tui.screens.history import TextModal

        body: Any = (
            Group(render.side_by_side_diff(d), render.diff_summary(d))
            if d.get("hunks")
            else render.diff_summary(d)
        )
        self.app.call_from_thread(
            self.app.push_screen, TextModal(f"Disk vs version {version_id}", body)
        )

    def show_result(self, res: dict[str, Any]) -> None:
        self.result = res
        self.fill_table()
        prefix = "Preview: would " if res["dry_run"] else "Done: "
        text = (
            f"{prefix}create {res['created']}, overwrite {res['overwritten']}, identical {res['identical']}, "
            f"conflicts {res['conflicts']}, errors {res['errors']}"
        )
        if res["conflicts"]:
            text += "\n[yellow]Conflicts are left untouched: tick 'Overwrite' or choose another destination.[/yellow]"
        text += "\n[dim]c compare with the disk · m resolve (merge) · t filter by outcome[/dim]"
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
