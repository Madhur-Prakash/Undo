"""Activity log pane and per-file version history screen."""

from __future__ import annotations

from typing import Any

from rich.console import Group
from textual import work
from textual.app import ComposeResult
from textual.containers import Vertical, VerticalScroll
from textual.screen import ModalScreen, Screen
from textual.widgets import Checkbox, DataTable, Footer, Header, Label, Select, Static
from undo_core.utils.errors import UndoError

from undo_cli import sorting
from undo_cli.output import render
from undo_cli.output.render import short_hash, size, when
from undo_cli.tui.screens.forget import start_delete_version, start_forget
from undo_cli.tui.screens.restore import RestoreModal
from undo_cli.tui.widgets.common import DataPane, SortBar


class ActivityPane(DataPane):
    DEFAULT_CSS = "ActivityPane DataTable { height: 1fr; }"

    def compose(self) -> ComposeResult:
        yield Label(
            "[bold]History[/bold]  [dim]the last 500 recorded changes · Enter opens the file's history[/dim]"
        )
        yield SortBar(sorting.ACTIVITY_SORTS, "time", id="sortbar")
        yield DataTable(id="log", cursor_type="row", zebra_stripes=True)

    def on_mount(self) -> None:
        self.query_one(DataTable).add_columns(
            "Time", "Operation", "Version", "Previous", "Size", "Path"
        )
        super().on_mount()

    def fetch(self) -> Any:
        return self.backend.call("activity", limit=500)

    def show(self, versions: list[dict[str, Any]]) -> None:
        self._rows = versions
        bar = self.query_one("#sortbar", SortBar)
        table = self.query_one(DataTable)
        table.clear()
        for v in sorting.sort_rows(versions, sorting.ACTIVITY_SORTS, bar.key, bar.reverse):
            table.add_row(
                when(v["timestamp"]),
                v["operation"],
                str(v["id"]),
                str(v.get("parent_version_id") or "-"),
                size(v["file_size"]) if v["blob_hash"] else "-",
                v["absolute_path"],
                key=f"{v['file_id']}:{v['id']}",
            )

    def _resort(self) -> None:
        if hasattr(self, "_rows"):
            self.show(self._rows)

    def on_select_changed(self, _event: Select.Changed) -> None:
        self._resort()

    def on_checkbox_changed(self, _event: Checkbox.Changed) -> None:
        self._resort()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.row_key.value:
            self.app.push_screen(FileHistoryScreen(int(event.row_key.value.split(":")[0])))


class TextModal(ModalScreen[None]):
    DEFAULT_CSS = """
    TextModal { align: center middle; }
    TextModal > Vertical { width: 95%; height: 90%; border: thick $primary; background: $surface; padding: 0 1; }
    """
    BINDINGS = [("escape", "dismiss_modal", "Close"), ("q", "dismiss_modal", "Close")]

    def __init__(self, title: str, body: Any) -> None:
        super().__init__()
        self.title_text = title
        self.body = body

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label(f"[bold]{self.title_text}[/bold]  [dim]Esc to close[/dim]")
            with VerticalScroll():
                yield Static(self.body)

    def action_dismiss_modal(self) -> None:
        self.dismiss(None)


class FileHistoryScreen(Screen[None]):
    BINDINGS = [
        ("escape", "app.pop_screen", "Back"),
        ("r", "restore", "Restore version"),
        ("d", "diff", "Diff with previous"),
        ("v", "view", "View content"),
        ("i", "info", "Version details"),
        ("x", "delete_version", "Delete version"),
        ("f", "forget", "Delete history"),
        ("c", "compare_disk", "Compare with disk"),
        ("m", "merge", "Merge into file"),
    ]
    DEFAULT_CSS = """
    FileHistoryScreen #summary { height: auto; padding: 1; }
    FileHistoryScreen DataTable { height: 1fr; }
    """

    def __init__(self, file_id: int) -> None:
        super().__init__()
        self.file_id = file_id
        self.data: dict[str, Any] | None = None

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static("Loading ...", id="summary")
        yield DataTable(id="versions", cursor_type="row", zebra_stripes=True)
        yield Footer()

    def on_mount(self) -> None:
        self.query_one(DataTable).add_columns(
            "Version", "Time", "Operation", "Size", "Hash", "Path"
        )
        self.load()

    @work(thread=True, exclusive=True)
    def load(self) -> None:
        try:
            data = self.app.backend.call("file_history", file_id=self.file_id)  # type: ignore[attr-defined]
        except UndoError as exc:
            self.app.call_from_thread(self.app.notify, exc.message, severity="error")
            return
        self.app.call_from_thread(self.show, data)

    def show(self, data: dict[str, Any]) -> None:
        self.data = data
        f = data["file"]
        former = [p["relative_path"] for p in data["paths"][:-1]]
        self.query_one("#summary", Static).update(
            f"[bold]{f['absolute_path']}[/bold]\n"
            f"{'[red]deleted ' + when(f['deleted_at']) + '[/red]' if f['is_deleted'] else '[green]live[/green]'} · "
            f"{f['version_count']} versions · size {size(f.get('size'))}"
            + (f"\n[dim]former paths: {', '.join(former)}[/dim]" if former else "")
            + "\n[dim]r restore · d diff with previous · v view · i details · "
            "x delete version · f delete history · c compare with disk · m merge into file · "
            "Esc back[/dim]"
        )
        table = self.query_one(DataTable)
        table.clear()
        for v in data["versions"]:
            table.add_row(
                str(v["id"]),
                when(v["timestamp"]),
                v["operation"],
                size(v["file_size"]) if v["blob_hash"] else "-",
                short_hash(v["blob_hash"]),
                v["relative_path"],
                key=str(v["id"]),
            )

    def _selected(self) -> dict[str, Any] | None:
        table = self.query_one(DataTable)
        if not self.data or table.row_count == 0:
            return None
        key = table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value
        return next((v for v in self.data["versions"] if str(v["id"]) == key), None)

    def action_restore(self) -> None:
        v = self._selected()
        if not v:
            return
        if not v["blob_hash"]:
            self.app.notify(
                "This entry records a deletion; pick an earlier version.", severity="warning"
            )
            return
        self.app.push_screen(
            RestoreModal(
                f"Restore version {v['id']} of {v['relative_path']}",
                "restore_version",
                {"version_id": v["id"]},
            ),
            self._after_restore,
        )

    def _after_restore(self, _result: dict[str, Any] | None) -> None:
        self.load()

    def action_diff(self) -> None:
        v = self._selected()
        if not v or not self.data:
            return
        versions = self.data["versions"]
        idx = next(i for i, x in enumerate(versions) if x["id"] == v["id"])
        older = next((x for x in versions[idx + 1 :] if x["blob_hash"]), None)
        if older is None or not v["blob_hash"]:
            self.app.notify("No earlier content version to compare with", severity="warning")
            return
        self.fetch_diff(older["id"], v["id"])

    @work(thread=True)
    def fetch_diff(self, a: int, b: int) -> None:
        try:
            d = self.app.backend.call("diff_versions", a=a, b=b)  # type: ignore[attr-defined]
        except UndoError as exc:
            self.app.call_from_thread(self.app.notify, exc.message, severity="error")
            return
        body: Any = (
            Group(render.side_by_side_diff(d), render.diff_summary(d))
            if d.get("hunks")
            else render.diff_summary(d)
        )
        self.app.call_from_thread(self.app.push_screen, TextModal(f"Compare v{a} -> v{b}", body))

    def action_view(self) -> None:
        v = self._selected()
        if v and v["blob_hash"]:
            self.fetch_content(v["id"])

    @work(thread=True)
    def fetch_content(self, version_id: int) -> None:
        try:
            c = self.app.backend.call("version_content", version_id=version_id)  # type: ignore[attr-defined]
        except UndoError as exc:
            self.app.call_from_thread(self.app.notify, exc.message, severity="error")
            return
        body = (
            c["text"]
            if c["is_text"]
            else f"Binary content ({size(c['size'])}). Use restore to get a copy."
        )
        if c["truncated"] and c["is_text"]:
            body += "\n\n[... truncated ...]"
        from rich.text import Text

        self.app.call_from_thread(
            self.app.push_screen, TextModal(f"Version {version_id}", Text(body))
        )

    def action_compare_disk(self) -> None:
        v = self._selected()
        if v and v["blob_hash"]:
            self.fetch_compare_disk(v["id"])

    @work(thread=True)
    def fetch_compare_disk(self, version_id: int) -> None:
        try:
            d = self.app.backend.call("diff_version_with_file", version_id=version_id)  # type: ignore[attr-defined]
        except UndoError as exc:
            self.app.call_from_thread(self.app.notify, exc.message, severity="error")
            return
        body: Any = (
            Group(render.side_by_side_diff(d), render.diff_summary(d))
            if d.get("hunks")
            else render.diff_summary(d)
        )
        self.app.call_from_thread(
            self.app.push_screen, TextModal(f"Disk vs version {version_id} (m to merge)", body)
        )

    def action_merge(self) -> None:
        v = self._selected()
        if not v or not v["blob_hash"]:
            return
        from undo_cli.tui.screens.merge import MergeScreen

        def done(written: bool | None) -> None:
            if written:
                self.load()

        self.app.push_screen(MergeScreen(v["id"]), done)

    def action_delete_version(self) -> None:
        v = self._selected()
        if not v or not self.data:
            return
        if v["id"] == self.data["versions"][0]["id"]:
            self.app.notify(
                "The latest version keeps the file restorable. Use f (Delete history) to remove it.",
                severity="warning",
            )
            return
        start_delete_version(self, v, on_done=self.load)

    def action_forget(self) -> None:
        if not self.data:
            return
        f = self.data["file"]

        def done(result: dict[str, Any]) -> None:
            if result.get("files_removed"):
                self.app.pop_screen()  # no history left for this file
            else:
                self.load()

        start_forget(self, f["absolute_path"], title=f"Delete history of {f['name']}", on_done=done)

    def action_info(self) -> None:
        v = self._selected()
        if v:
            self.fetch_info(v["id"])

    @work(thread=True)
    def fetch_info(self, version_id: int) -> None:
        try:
            d = self.app.backend.call("get_version", version_id=version_id)  # type: ignore[attr-defined]
        except UndoError as exc:
            self.app.call_from_thread(self.app.notify, exc.message, severity="error")
            return
        v, b = d["version"], d.get("blob")
        lines = [
            f"Version     {v['id']} ({v['operation']})",
            f"Time        {when(v['timestamp'])}",
            f"Path        {v['absolute_path']}",
            f"Size        {size(v['file_size'])}",
            f"Hash        {v['blob_hash'] or '-'}",
            f"Previous    {d.get('previous_version_id') or '-'}   Next {d.get('next_version_id') or '-'}",
        ]
        if b:
            lines += [
                f"Storage     {b['storage_kind']} / {b['compression_algorithm']}"
                + (f" level {b['compression_level']}" if b.get("compression_level") else ""),
                f"Stored      {size(b['compressed_size'])} of {size(b['original_size'])}",
                f"Status      {b['status']}   references {b['reference_count']}",
            ]
        from rich.text import Text

        self.app.call_from_thread(
            self.app.push_screen, TextModal("Version details", Text("\n".join(lines)))
        )
