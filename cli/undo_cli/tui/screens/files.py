"""File browser with search; Enter opens a file's history."""

from __future__ import annotations

from typing import Any

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Checkbox, DataTable, Input, Label

from undo_cli.output.render import size, when
from undo_cli.tui.screens.history import FileHistoryScreen
from undo_cli.tui.widgets.common import DataPane


class FilesPane(DataPane):
    DEFAULT_CSS = """
    FilesPane Horizontal { height: 3; }
    FilesPane Input { width: 1fr; }
    FilesPane DataTable { height: 1fr; }
    """

    def compose(self) -> ComposeResult:
        yield Label("[bold]Files[/bold]  [dim]type to search · Enter opens history[/dim]")
        with Horizontal():
            yield Input(placeholder="Search path ...", id="q")
            yield Checkbox("Include deleted", id="deleted")
        yield DataTable(id="files", cursor_type="row", zebra_stripes=True)
        yield Label("", id="count", classes="pane-status")

    def on_mount(self) -> None:
        self.query_one(DataTable).add_columns(
            "ID", "Path", "Size", "Modified", "Versions", "Latest", "State"
        )
        super().on_mount()

    def fetch(self) -> Any:
        q = self.query_one("#q", Input).value.strip() or None
        include_deleted = self.query_one("#deleted", Checkbox).value
        return self.backend.call("list_files", query=q, include_deleted=include_deleted, limit=500)

    def show(self, page: dict[str, Any]) -> None:
        table = self.query_one(DataTable)
        table.clear()
        for f in page["items"]:
            table.add_row(
                str(f["id"]),
                f["absolute_path"],
                size(f.get("size")),
                when(f.get("last_modified")),
                str(f["version_count"]),
                f.get("latest_operation") or "-",
                "deleted" if f["is_deleted"] else "live",
                key=str(f["id"]),
            )
        self.query_one("#count", Label).update(f"{len(page['items'])} of {page['total']} files")

    def on_input_changed(self, _event: Input.Changed) -> None:
        self.reload()

    def on_checkbox_changed(self, _event: Checkbox.Changed) -> None:
        self.reload()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.row_key.value:
            self.app.push_screen(FileHistoryScreen(int(event.row_key.value)))
