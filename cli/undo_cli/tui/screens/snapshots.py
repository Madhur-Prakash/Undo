"""Snapshot browser: create, compare, restore, delete."""

from __future__ import annotations

from typing import Any

from rich.text import Text
from textual import work
from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Button, Checkbox, DataTable, Label, Select
from undo_core.utils.errors import UndoError

from undo_cli import sorting
from undo_cli.output.render import size, when
from undo_cli.tui.screens.history import TextModal
from undo_cli.tui.screens.restore import RestoreModal
from undo_cli.tui.widgets.common import ConfirmModal, DataPane, PromptModal, SortBar


class SnapshotsPane(DataPane):
    DEFAULT_CSS = """
    SnapshotsPane Horizontal { height: 3; }
    SnapshotsPane DataTable { height: 1fr; }
    """
    BINDINGS = [
        ("c", "create", "Create"),
        ("d", "diff", "Compare"),
        ("r", "restore", "Restore"),
        ("x", "delete", "Delete"),
        ("n", "rename", "Rename"),
    ]

    def compose(self) -> ComposeResult:
        yield Label(
            "[bold]Snapshots[/bold]  [dim]c create · d compare · r restore · n rename · x delete[/dim]"
        )
        with Horizontal():
            yield Button("Create", id="create", variant="primary")
            yield Button("Compare", id="diff")
            yield Button("Restore", id="restore", variant="warning")
            yield Button("Rename", id="rename")
            yield Button("Delete", id="delete", variant="error")
            yield SortBar(sorting.SNAPSHOT_SORTS, "created", id="sortbar")
        yield DataTable(id="snaps", cursor_type="row", zebra_stripes=True)

    def on_mount(self) -> None:
        self.query_one(DataTable).add_columns(
            "ID", "Name", "Created", "Root", "Files", "Size", "Description"
        )
        super().on_mount()

    def fetch(self) -> Any:
        return self.backend.call("list_snapshots")

    def show(self, snaps: list[dict[str, Any]]) -> None:
        self._rows = snaps
        self._snaps = {str(s["id"]): s for s in snaps}
        bar = self.query_one("#sortbar", SortBar)
        table = self.query_one(DataTable)
        table.clear()
        for s in sorting.sort_rows(snaps, sorting.SNAPSHOT_SORTS, bar.key, bar.reverse):
            table.add_row(
                str(s["id"]),
                s["name"],
                when(s["created_at"]),
                s["root_path"],
                str(s["file_count"]),
                size(s["total_size"]),
                s.get("description") or "",
                key=str(s["id"]),
            )

    def _selected(self) -> dict[str, Any] | None:
        table = self.query_one(DataTable)
        if table.row_count == 0:
            return None
        return getattr(self, "_snaps", {}).get(
            table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value
        )

    def _resort(self) -> None:
        if hasattr(self, "_rows"):
            self.show(self._rows)

    def on_select_changed(self, _event: Select.Changed) -> None:
        self._resort()

    def on_checkbox_changed(self, _event: Checkbox.Changed) -> None:
        self._resort()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        getattr(self, f"action_{event.button.id}", lambda: None)()

    def action_create(self) -> None:
        def done(values: dict[str, str] | None) -> None:
            if values and values["name"].strip():
                self.run_create(values)

        self.app.push_screen(
            PromptModal(
                "Create snapshot",
                [
                    ("name", "Name", ""),
                    ("description", "Description (optional)", ""),
                    ("root", "Root id or path (optional when one root is tracked)", ""),
                ],
                "Create",
            ),
            done,
        )

    @work(thread=True, group="snap-op")
    def run_create(self, values: dict[str, str]) -> None:
        self.app.call_from_thread(self.app.notify, "Scanning and creating snapshot ...")
        try:
            snap = self.backend.call(
                "create_snapshot",
                name=values["name"].strip(),
                description=values["description"].strip() or None,
                root=values["root"].strip() or None,
                scan=True,
            )
        except UndoError as exc:
            self.app.call_from_thread(self.app.notify, exc.message, severity="error")
            return
        self.app.call_from_thread(
            self.app.notify, f"Snapshot '{snap['name']}' created ({snap['file_count']} files)"
        )
        self.app.call_from_thread(self.reload)

    def action_diff(self) -> None:
        snap = self._selected()
        if not snap:
            return

        def done(values: dict[str, str] | None) -> None:
            if values and values["other"].strip():
                self.run_diff(values["other"].strip(), str(snap["id"]))

        self.app.push_screen(
            PromptModal(
                f"Compare '{snap['name']}' with ...",
                [("other", "Older snapshot id or name", "")],
                "Compare",
            ),
            done,
        )

    @work(thread=True, group="snap-op")
    def run_diff(self, a: str, b: str) -> None:
        try:
            d = self.backend.call("diff_snapshots", a=a, b=b)
        except UndoError as exc:
            self.app.call_from_thread(self.app.notify, exc.message, severity="error")
            return
        text = Text(
            f"{d['a']['name']} -> {d['b']['name']}: {len(d['added'])} added, {len(d['removed'])} removed, "
            f"{len(d['modified'])} modified, {d['unchanged']} unchanged\n\n"
        )
        for label, items, style in (
            ("+", d["added"], "green"),
            ("-", d["removed"], "red"),
            ("~", d["modified"], "cyan"),
        ):
            for c in items:
                text.append(f"{label} {c['relative_path']}\n", style=style)
        self.app.call_from_thread(self.app.push_screen, TextModal("Snapshot comparison", text))

    def action_restore(self) -> None:
        snap = self._selected()
        if snap:
            self.app.push_screen(
                RestoreModal(
                    f"Restore snapshot '{snap['name']}' ({snap['file_count']} files)",
                    "restore_snapshot",
                    {"ref": str(snap["id"])},
                )
            )

    def action_rename(self) -> None:
        snap = self._selected()
        if not snap:
            return

        def done(values: dict[str, str] | None) -> None:
            if not values:
                return
            name = values["name"].strip()
            description = values["description"].strip()
            changes: dict[str, str] = {}
            if name and name != snap["name"]:
                changes["name"] = name
            if description != (snap.get("description") or ""):
                changes["description"] = description
            if changes:
                self.run_rename(str(snap["id"]), changes)

        self.app.push_screen(
            PromptModal(
                f"Rename snapshot '{snap['name']}'",
                [
                    ("name", "Name", snap["name"]),
                    ("description", "Description (empty to clear)", snap.get("description") or ""),
                ],
                "Rename",
            ),
            done,
        )

    @work(thread=True, group="snap-op")
    def run_rename(self, ref: str, changes: dict[str, str]) -> None:
        try:
            info = self.backend.call("rename_snapshot", ref=ref, **changes)
        except UndoError as exc:
            self.app.call_from_thread(self.app.notify, exc.message, severity="error")
            return
        self.app.call_from_thread(self.app.notify, f"Snapshot is now '{info['name']}'")
        self.app.call_from_thread(self.reload)

    def action_delete(self) -> None:
        snap = self._selected()
        if not snap:
            return

        def done(ok: bool | None) -> None:
            if ok:
                self.run_delete(str(snap["id"]))

        self.app.push_screen(
            ConfirmModal(
                f"Delete snapshot '{snap['name']}'? File versions are kept.", "Delete", "error"
            ),
            done,
        )

    @work(thread=True, group="snap-op")
    def run_delete(self, ref: str) -> None:
        try:
            self.backend.call("delete_snapshot", ref=ref)
        except UndoError as exc:
            self.app.call_from_thread(self.app.notify, exc.message, severity="error")
            return
        self.app.call_from_thread(self.app.notify, "Snapshot deleted")
        self.app.call_from_thread(self.reload)
