"""Merge editor for the TUI: resolve a restore like a merge conflict (same rules as the app).

For each difference between the file on disk (left) and a stored version (right) choose keep
disk / use version / both, or edit the merged result by hand, then save it to the file (its
current content is saved as a version first). Unfinished work can be saved and resumed.
"""

from __future__ import annotations

from typing import Any

from rich.text import Text
from textual import work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen, Screen
from textual.widgets import Button, DataTable, Footer, Header, Label, Static, TextArea
from undo_core.recovery.merge import compose_result
from undo_core.utils.errors import UndoError

from undo_cli.output import render
from undo_cli.tui.widgets.common import ConfirmModal

LABELS = {"disk": "Keep disk", "version": "Use version", "both": "Both"}


class UnsavedModal(ModalScreen[str]):
    """Leaving with unsaved changes: save progress, discard, or keep editing."""

    DEFAULT_CSS = """
    UnsavedModal { align: center middle; }
    UnsavedModal > Vertical { width: 70; height: auto; border: thick $warning; background: $surface; padding: 1 2; }
    UnsavedModal Horizontal { height: auto; margin-top: 1; align-horizontal: right; }
    UnsavedModal Button { margin-left: 1; }
    """
    BINDINGS = [("escape", "keep", "Keep editing")]

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label("[bold]Unsaved changes[/bold]")
            yield Label("Save your progress to resume this merge later, or discard the changes?")
            with Horizontal():
                yield Button("Keep editing", id="keep")
                yield Button("Discard", id="discard", variant="error")
                yield Button("Save progress", id="save", variant="primary")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id or "keep")

    def action_keep(self) -> None:
        self.dismiss("keep")


class MergeScreen(Screen[bool]):
    """Returns True when the merged result was written to the file."""

    DEFAULT_CSS = """
    MergeScreen #info { height: auto; padding: 0 1; }
    MergeScreen #hunk { height: 1fr; border: round $primary; }
    MergeScreen #result { height: 1fr; }
    MergeScreen #result-label { height: auto; padding: 0 1; }
    """
    BINDINGS = [
        ("n", "next", "Next difference"),
        ("p", "prev", "Previous"),
        ("1", "choose('disk')", "Keep disk"),
        ("2", "choose('version')", "Use version"),
        ("3", "choose('both')", "Both"),
        ("a", "choose_all('disk')", "All: disk"),
        ("v", "choose_all('version')", "All: version"),
        ("e", "edit", "Edit result"),
        ("q", "close", "Close"),
        ("escape", "back", "Back"),
        ("ctrl+s", "write", "Save to file"),
        ("ctrl+d", "save_draft", "Save progress"),
    ]

    def __init__(self, version_id: int, path: str | None = None) -> None:
        super().__init__()
        self.version_id = version_id
        self.path = path
        self.source: dict[str, Any] | None = None
        self.choices: dict[int, str] = {}
        self.current = 0
        self.edited = False
        self.dirty = False
        self._setting = False

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static("Loading ...", id="info")
        with VerticalScroll(id="hunk"):
            yield Static(id="hunk-view")
        yield Static(id="result-label")
        yield TextArea(id="result", soft_wrap=False, show_line_numbers=True)
        yield Footer()

    def on_mount(self) -> None:
        self.load()

    # ------------------------------------------------------------------ loading
    @work(thread=True, exclusive=True)
    def load(self) -> None:
        try:
            src = self.app.backend.call(  # type: ignore[attr-defined]
                "merge_source", version_id=self.version_id, path=self.path
            )
        except UndoError as exc:
            self.app.call_from_thread(self.app.notify, exc.message, severity="error")
            self.app.call_from_thread(self.dismiss, False)
            return
        self.app.call_from_thread(self.loaded, src)

    def loaded(self, src: dict[str, Any]) -> None:
        if src["identical"]:
            self.app.notify("Identical: the file already has this version's content.")
            self.dismiss(False)
            return
        self.source = src
        self.choices = {i: "disk" for i in range(len(src["hunks"]))}
        self._set_result(self._merged_text())
        self.dirty = False
        self.refresh_view()
        self.query_one("#hunk", VerticalScroll).focus()
        draft = src.get("draft")
        if draft and draft.get("version_id") == self.version_id:

            def resume(ok: bool | None) -> None:
                if ok:
                    for key, value in (draft.get("choices") or {}).items():
                        if str(key).isdigit() and value in LABELS:
                            self.choices[int(key)] = value
                    self._set_result(draft["text"])
                    self.edited = bool(draft.get("edited"))
                    self.dirty = False
                    self.refresh_view()

            self.app.push_screen(
                ConfirmModal(
                    f"You saved an unfinished merge of this file ({render.when(draft.get('updated_at'))}).\n"
                    "Resume it?",
                    "Resume",
                    "primary",
                ),
                resume,
            )

    # ------------------------------------------------------------------ result
    def _merged_text(self) -> str:
        assert self.source is not None
        return compose_result(self.source["current_lines"], self.source["hunks"], self.choices)

    def _set_result(self, text: str) -> None:
        self._setting = True
        self.query_one("#result", TextArea).text = text
        self._setting = False

    def on_text_area_changed(self, _event: TextArea.Changed) -> None:
        if self._setting:
            return
        self.edited = True
        self.dirty = True
        self.refresh_labels()

    # ------------------------------------------------------------------ view
    def refresh_labels(self) -> None:
        if self.source is None:
            return
        n = len(self.source["hunks"])
        choice = LABELS[self.choices.get(self.current, "disk")]
        state = "[red]unsaved changes[/red]" if self.dirty else "[dim]no unsaved changes[/dim]"
        self.query_one("#info", Static).update(
            f"[bold]Resolve {self.source['path']}[/bold]  ·  left: on disk now  ·  right: version "
            f"{self.version_id}\nDifference {self.current + 1} of {n}: [b]{choice}[/b]  ·  {state}\n"
            "[dim]n/p move · 1 keep disk · 2 use version · 3 both · a/v all · e edit result "
            "(Esc back) · Ctrl+S save to file · Ctrl+D save progress · q close[/dim]"
        )
        self.query_one("#result-label", Static).update(
            "[bold]Result[/bold] "
            + (
                "[yellow](edited by hand)[/yellow]"
                if self.edited
                else "[dim](from your choices; editable)[/dim]"
            )
        )

    def refresh_view(self) -> None:
        if self.source is None:
            return
        hunks = self.source["hunks"]
        if hunks:
            view = {
                "version": self.source["version"],
                "path": self.source["path"],
                "exists": self.source["exists"],
                "hunks": [hunks[self.current]],
            }
            self.query_one("#hunk-view", Static).update(render.side_by_side_diff(view))
        else:
            self.query_one("#hunk-view", Static).update(Text("No line differences."))
        self.refresh_labels()

    # ------------------------------------------------------------------ actions
    def action_next(self) -> None:
        if self.source and self.current < len(self.source["hunks"]) - 1:
            self.current += 1
            self.refresh_view()

    def action_prev(self) -> None:
        if self.source and self.current > 0:
            self.current -= 1
            self.refresh_view()

    def _apply(self, picks: dict[int, str]) -> None:
        def go(ok: bool | None = True) -> None:
            if not ok:
                return
            self.choices.update(picks)
            self.edited = False
            self.dirty = True
            self._set_result(self._merged_text())
            self.refresh_view()

        if self.edited:
            self.app.push_screen(
                ConfirmModal(
                    "You edited the result by hand. Rebuild it from the choices and replace "
                    "those edits?",
                    "Replace edits",
                    "error",
                ),
                go,
            )
        else:
            go()

    def action_choose(self, choice: str) -> None:
        if self.source and self.source["hunks"]:
            self._apply({self.current: choice})

    def action_choose_all(self, choice: str) -> None:
        if self.source:
            self._apply({i: choice for i in range(len(self.source["hunks"]))})

    def action_edit(self) -> None:
        self.query_one("#result", TextArea).focus()

    def action_back(self) -> None:
        if self.focused is self.query_one("#result", TextArea):
            self.query_one("#hunk", VerticalScroll).focus()
        else:
            self.action_close()

    def action_close(self) -> None:
        if not self.dirty:
            self.dismiss(False)
            return

        def decided(choice: str | None) -> None:
            if choice == "save":
                self.save_draft(close_after=True)
            elif choice == "discard":
                self.dismiss(False)

        self.app.push_screen(UnsavedModal(), decided)

    def action_save_draft(self) -> None:
        self.save_draft(close_after=False)

    @work(thread=True, group="merge-op")
    def save_draft(self, close_after: bool) -> None:
        if self.source is None:
            return
        text = self.app.call_from_thread(lambda: self.query_one("#result", TextArea).text)
        try:
            self.app.backend.call(  # type: ignore[attr-defined]
                "save_merge_draft",
                path=self.source["path"],
                version_id=self.version_id,
                text=text,
                choices={str(k): v for k, v in self.choices.items()},
                edited=self.edited,
            )
        except UndoError as exc:
            self.app.call_from_thread(self.app.notify, exc.message, severity="error")
            return

        def done() -> None:
            self.dirty = False
            self.refresh_labels()
            self.app.notify("Progress saved. Open this file's merge again to resume.")
            if close_after:
                self.dismiss(False)

        self.app.call_from_thread(done)

    def action_write(self) -> None:
        if self.source is None:
            return
        exists = self.source["exists"]

        def confirmed(ok: bool | None) -> None:
            if ok:
                self.write()

        self.app.push_screen(
            ConfirmModal(
                f"Save the merged result to\n{self.source['path']}?\n"
                + (
                    "Its current content is saved as a version first, so this can be undone."
                    if exists
                    else "The file is created."
                ),
                "Save to file",
                "primary",
            ),
            confirmed,
        )

    @work(thread=True, group="merge-op")
    def write(self) -> None:
        if self.source is None:
            return
        text = self.app.call_from_thread(lambda: self.query_one("#result", TextArea).text)
        try:
            self.app.backend.call(  # type: ignore[attr-defined]
                "merge_write",
                path=self.source["path"],
                text=text,
                version_id=self.version_id,
                expected_hash=self.source["current_hash"],
            )
        except UndoError as exc:
            self.app.call_from_thread(self.app.notify, exc.message, severity="error")
            return
        self.app.call_from_thread(self.app.notify, f"Merged result saved to {self.source['path']}")
        self.app.call_from_thread(self.dismiss, True)


class DraftsModal(ModalScreen[None]):
    """Unfinished merges: Enter resumes, x discards."""

    DEFAULT_CSS = """
    DraftsModal { align: center middle; }
    DraftsModal > Vertical { width: 90%; height: 70%; border: thick $primary; background: $surface; padding: 1 2; }
    DraftsModal DataTable { height: 1fr; }
    """
    BINDINGS = [
        ("escape", "close", "Close"),
        ("x", "discard", "Discard"),
        ("enter", "resume", "Resume"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.drafts: list[dict[str, Any]] = []

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label(
                "[bold]Unfinished merges[/bold]  [dim]Enter resume · x discard · Esc close[/dim]"
            )
            yield DataTable(id="drafts", cursor_type="row", zebra_stripes=True)

    def on_mount(self) -> None:
        self.query_one(DataTable).add_columns("File", "Version", "Saved")
        self.load()

    @work(thread=True, exclusive=True)
    def load(self) -> None:
        try:
            drafts = self.app.backend.call("list_merge_drafts")  # type: ignore[attr-defined]
        except UndoError as exc:
            self.app.call_from_thread(self.app.notify, exc.message, severity="error")
            return
        self.app.call_from_thread(self.show, drafts)

    def show(self, drafts: list[dict[str, Any]]) -> None:
        self.drafts = drafts
        table = self.query_one(DataTable)
        table.clear()
        for d in drafts:
            table.add_row(d["path"], str(d["version_id"]), render.when(d.get("updated_at")))
        if not drafts:
            self.app.notify("No unfinished merges.")

    def _selected(self) -> dict[str, Any] | None:
        table = self.query_one(DataTable)
        if not self.drafts or table.row_count == 0:
            return None
        return self.drafts[table.cursor_row]

    def on_data_table_row_selected(self, _event: DataTable.RowSelected) -> None:
        self.action_resume()

    def action_resume(self) -> None:
        d = self._selected()
        if d:

            def reload(_written: bool | None) -> None:
                self.load()

            self.app.push_screen(MergeScreen(d["version_id"], d["path"]), reload)

    def action_discard(self) -> None:
        d = self._selected()
        if not d:
            return

        def confirmed(ok: bool | None) -> None:
            if ok:
                self.discard(d["path"])

        self.app.push_screen(
            ConfirmModal(f"Discard the unfinished merge of\n{d['path']}?", "Discard", "error"),
            confirmed,
        )

    @work(thread=True, group="drafts-op")
    def discard(self, path: str) -> None:
        try:
            self.app.backend.call("delete_merge_draft", path=path)  # type: ignore[attr-defined]
        except UndoError as exc:
            self.app.call_from_thread(self.app.notify, exc.message, severity="error")
            return
        self.app.call_from_thread(self.load)

    def action_close(self) -> None:
        self.dismiss(None)
