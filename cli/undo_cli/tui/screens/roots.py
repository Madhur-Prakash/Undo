"""Tracked roots: add, scan, enable/disable, untrack."""

from __future__ import annotations

from typing import Any

from textual import work
from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Button, DataTable, Label
from undo_core.utils.errors import UndoError

from undo_cli.output.render import when
from undo_cli.tui.screens.forget import start_forget
from undo_cli.tui.widgets.common import ConfirmModal, DataPane, PromptModal


class RootsPane(DataPane):
    DEFAULT_CSS = """
    RootsPane Horizontal { height: 3; }
    RootsPane DataTable { height: 1fr; }
    """
    BINDINGS = [
        ("a", "add", "Add root"),
        ("s", "scan", "Scan"),
        ("e", "toggle_root", "Enable/disable"),
        ("x", "untrack", "Untrack"),
        ("f", "forget", "Delete history"),
    ]

    def compose(self) -> ComposeResult:
        yield Label(
            "[bold]Tracked roots[/bold]  [dim]a add · s scan · e enable/disable · x untrack[/dim]"
        )
        with Horizontal():
            yield Button("Add", id="add", variant="primary")
            yield Button("Scan", id="scan")
            yield Button("Deep scan", id="deep")
            yield Button("Enable/disable", id="toggle")
            yield Button("Untrack", id="untrack", variant="error")
        yield DataTable(id="roots", cursor_type="row", zebra_stripes=True)

    def on_mount(self) -> None:
        self.query_one(DataTable).add_columns(
            "ID", "Path", "State", "Files", "Deleted", "Versions", "Last scan", "Monitor"
        )
        super().on_mount()

    def fetch(self) -> Any:
        return self.backend.call("list_roots")

    def show(self, roots: list[dict[str, Any]]) -> None:
        table = self.query_one(DataTable)
        table.clear()
        self._roots = {str(r["id"]): r for r in roots}
        for r in roots:
            table.add_row(
                str(r["id"]),
                r["path"],
                "enabled" if r["enabled"] else "disabled",
                str(r["file_count"]),
                str(r["deleted_file_count"]),
                str(r["version_count"]),
                when(r.get("last_scan_at")),
                r.get("watch_mode") or "-",
                key=str(r["id"]),
            )

    def _selected(self) -> dict[str, Any] | None:
        table = self.query_one(DataTable)
        if table.row_count == 0:
            return None
        key = table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value
        return getattr(self, "_roots", {}).get(key)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        handler = {
            "add": self.action_add,
            "scan": self.action_scan,
            "deep": lambda: self.action_scan(True),
            "toggle": self.action_toggle_root,
            "untrack": self.action_untrack,
        }.get(event.button.id or "")
        if handler:
            handler()

    def action_add(self) -> None:
        def done(values: dict[str, str] | None) -> None:
            if values and values["path"].strip():
                self.run_op(
                    "add_root", f"Tracking {values['path']}", path=values["path"].strip(), scan=True
                )

        self.app.push_screen(
            PromptModal("Track a directory", [("path", "Directory path", "")], "Track"), done
        )

    def action_scan(self, deep: bool = False) -> None:
        root = self._selected()
        if root:
            self.run_op("scan", f"Scanning {root['path']} ...", target=root["id"], deep=deep)

    def action_toggle_root(self) -> None:
        root = self._selected()
        if root:
            self.run_op("set_root_enabled", "Updated", ref=root["id"], enabled=not root["enabled"])

    def action_untrack(self) -> None:
        root = self._selected()
        if not root:
            return

        def done(ok: bool | None) -> None:
            if ok:
                self.run_op(
                    "remove_root", "Stopped tracking (history kept)", ref=root["id"], purge=False
                )

        self.app.push_screen(
            ConfirmModal(
                f"Stop monitoring {root['path']}?\nIts history is kept and can still be restored.",
                "Untrack",
            ),
            done,
        )

    def action_forget(self) -> None:
        root = self._selected()
        if root:
            start_forget(
                self,
                root["path"],
                title=f"Delete history in {root['path']}",
                ask_path=True,
                on_done=lambda _r: self.reload(),
            )

    @work(thread=True, group="roots-op")
    def run_op(self, op: str, message: str, **kwargs: Any) -> None:
        self.app.call_from_thread(self.app.notify, message)
        try:
            result = self.backend.call(op, **kwargs)
        except UndoError as exc:
            self.app.call_from_thread(self.app.notify, exc.message, severity="error")
            return
        if op == "scan" and result:
            r = result[0]
            self.app.call_from_thread(
                self.app.notify,
                f"Scan finished: {r['new']} new, {r['modified']} modified, {r['deleted']} deleted, {r['renamed']} moved",
            )
        self.app.call_from_thread(self.reload)
