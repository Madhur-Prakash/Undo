"""Settings editor and exclusion list."""

from __future__ import annotations

import json
from typing import Any

from textual import work
from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Button, DataTable, Label
from undo_core.utils.errors import UndoError

from undo_cli.tui.widgets.common import DataPane, PromptModal


class SettingsPane(DataPane):
    DEFAULT_CSS = """
    SettingsPane #settings { height: 2fr; }
    SettingsPane #exclusions { height: 1fr; }
    SettingsPane Horizontal { height: 3; }
    """

    def compose(self) -> ComposeResult:
        yield Label(
            "[bold]Settings[/bold]  [dim]Enter edits the selected setting (validated by the backend)[/dim]"
        )
        yield DataTable(id="settings", cursor_type="row", zebra_stripes=True)
        with Horizontal():
            yield Label("[bold]Exclusions[/bold] ", classes="pane-status")
            yield Button("Add exclusion", id="ex-add", variant="primary")
            yield Button("Remove selected", id="ex-remove", variant="error")
        yield DataTable(id="exclusions", cursor_type="row", zebra_stripes=True)

    def on_mount(self) -> None:
        self.query_one("#settings", DataTable).add_columns("Key", "Value")
        self.query_one("#exclusions", DataTable).add_columns("Pattern", "Source", "Scope")
        super().on_mount()

    def fetch(self) -> Any:
        return {
            "settings": self.backend.call("get_settings"),
            "exclusions": self.backend.call("list_exclusions"),
        }

    def show(self, data: dict[str, Any]) -> None:
        settings = data["settings"]
        info = settings.pop("_info", {})
        table = self.query_one("#settings", DataTable)
        table.clear()
        table.add_row("(data directory)", info.get("data_dir", ""), key="_data_dir")
        self._values: dict[str, Any] = {}
        for section, values in settings.items():
            for name, value in values.items():
                key = f"{section}.{name}"
                self._values[key] = value
                shown = json.dumps(value) if isinstance(value, list | dict) else str(value)
                table.add_row(key, shown if len(shown) < 120 else shown[:117] + "...", key=key)
        ex = self.query_one("#exclusions", DataTable)
        ex.clear()
        self._exclusions = data["exclusions"]
        for i, e in enumerate(data["exclusions"]):
            ex.add_row(
                e["pattern"],
                e["source"],
                f"root {e['root_id']}" if e.get("root_id") else "all roots",
                key=str(i),
            )

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if (
            event.data_table.id != "settings"
            or not event.row_key.value
            or event.row_key.value.startswith("_")
        ):
            return
        key = event.row_key.value
        value = self._values.get(key)
        current = (
            json.dumps(value)
            if isinstance(value, list | dict)
            else ("" if value is None else str(value))
        )

        def done(values: dict[str, str] | None) -> None:
            if values is not None:
                self.run_op("set_setting", f"{key} updated", key=key, value=values["value"])

        self.app.push_screen(
            PromptModal(
                f"Set {key}",
                [("value", "New value (sizes like 500MB accepted; 'none' clears)", current)],
                "Save",
            ),
            done,
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "ex-add":

            def done(values: dict[str, str] | None) -> None:
                if values and values["pattern"].strip():
                    self.run_op(
                        "add_exclusion",
                        "Exclusion added",
                        pattern=values["pattern"].strip(),
                        root=values["root"].strip() or None,
                    )

            self.app.push_screen(
                PromptModal(
                    "Add exclusion",
                    [
                        ("pattern", "Pattern (build/, *.log, docs/drafts, /abs/path)", ""),
                        ("root", "Root id (empty = all roots)", ""),
                    ],
                    "Add",
                ),
                done,
            )
        elif event.button.id == "ex-remove":
            table = self.query_one("#exclusions", DataTable)
            if table.row_count == 0:
                return
            idx = int(table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value or 0)
            e = self._exclusions[idx]
            if e["source"] == "builtin":
                self.app.notify("Built-in exclusions cannot be removed", severity="warning")
                return
            self.run_op(
                "remove_exclusion", "Exclusion removed", pattern=e["pattern"], root=e.get("root_id")
            )

    @work(thread=True, group="settings-op")
    def run_op(self, op: str, message: str, **kwargs: Any) -> None:
        try:
            self.backend.call(op, **kwargs)
        except UndoError as exc:
            self.app.call_from_thread(self.app.notify, exc.message, severity="error")
            return
        self.app.call_from_thread(self.app.notify, message)
        self.app.call_from_thread(self.reload)
