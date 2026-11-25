"""`undo tui`: interactive terminal dashboard (Textual)."""

from __future__ import annotations

from textual.app import App, ComposeResult
from textual.widgets import Footer, Header, TabbedContent, TabPane

from undo_cli.commands.common import State
from undo_cli.tui.screens.dashboard import DashboardPane
from undo_cli.tui.screens.files import FilesPane
from undo_cli.tui.screens.history import ActivityPane
from undo_cli.tui.screens.roots import RootsPane
from undo_cli.tui.screens.settings import SettingsPane
from undo_cli.tui.screens.snapshots import SnapshotsPane
from undo_cli.tui.screens.storage import StoragePane
from undo_cli.tui.services.backend import TuiBackend
from undo_cli.tui.widgets.common import DataPane

TABS = [
    ("dashboard", "Dashboard", DashboardPane),
    ("roots", "Roots", RootsPane),
    ("files", "Files", FilesPane),
    ("history", "History", ActivityPane),
    ("snapshots", "Snapshots", SnapshotsPane),
    ("storage", "Storage", StoragePane),
    ("settings", "Settings", SettingsPane),
]


class UndoTUI(App[None]):
    TITLE = "Undo"
    SUB_TITLE = "file version history"
    CSS = """
    TabPane { padding: 0 1; }
    """
    BINDINGS = [
        ("q", "quit", "Quit"),
        ("f5", "refresh", "Refresh"),
        ("ctrl+r", "refresh", "Refresh"),
        ("u", "drafts", "Unfinished merges"),
        *[
            (str(i + 1), f"show_tab('{tab_id}')", title)
            for i, (tab_id, title, _cls) in enumerate(TABS)
        ],
    ]

    def __init__(self, state: State) -> None:
        super().__init__()
        self.backend = TuiBackend(state)

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with TabbedContent(initial="dashboard"):
            for tab_id, title, cls in TABS:
                with TabPane(title, id=tab_id):
                    yield cls(id=f"pane-{tab_id}")
        yield Footer()

    def on_mount(self) -> None:
        try:
            self.sub_title = self.backend.description
        except Exception as exc:
            self.notify(str(exc), severity="error")
        self.set_interval(10, self._refresh_dashboard)

    def _refresh_dashboard(self) -> None:
        active = self.query_one(TabbedContent).active
        if active == "dashboard":
            self.query_one("#pane-dashboard", DataPane).reload()

    def action_drafts(self) -> None:
        from undo_cli.tui.screens.merge import DraftsModal

        self.push_screen(DraftsModal())

    def action_show_tab(self, tab: str) -> None:
        self.query_one(TabbedContent).active = tab

    def action_refresh(self) -> None:
        active = self.query_one(TabbedContent).active
        self.query_one(f"#pane-{active}", DataPane).reload()
        self.sub_title = self.backend.description

    def on_tabbed_content_tab_activated(self, event: TabbedContent.TabActivated) -> None:
        pane_id = event.pane.id if event.pane else None
        if pane_id:
            self.query_one(f"#pane-{pane_id}", DataPane).reload()

    def on_unmount(self) -> None:
        self.backend.close()
