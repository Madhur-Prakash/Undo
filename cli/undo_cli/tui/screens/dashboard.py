"""Dashboard: daemon status, totals, recent activity and snapshots."""

from __future__ import annotations

from typing import Any

from textual import work
from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Button, DataTable, Label, Static
from undo_core.utils.errors import UndoError

from undo_cli.output.render import size, when
from undo_cli.tui.widgets.common import DataPane, StatCard


class DashboardPane(DataPane):
    DEFAULT_CSS = """
    DashboardPane Horizontal.cards { height: 5; }
    DashboardPane Horizontal.actions { height: 3; }
    DashboardPane #daemon-detail { height: auto; margin: 1 0; }
    DashboardPane DataTable { height: 1fr; }
    """

    def compose(self) -> ComposeResult:
        with Horizontal(classes="cards"):
            yield StatCard("Daemon", id="c-daemon")
            yield StatCard("Roots", id="c-roots")
            yield StatCard("Files", id="c-files")
            yield StatCard("Versions", id="c-versions")
            yield StatCard("Original data", id="c-original")
            yield StatCard("Stored", id="c-stored")
        with Horizontal(classes="actions"):
            yield Button("Start daemon", id="start", variant="success")
            yield Button("Stop daemon", id="stop", variant="error")
            yield Button("Scan all roots", id="scan")
        yield Static(id="daemon-detail")
        yield Label("[bold]Recent changes[/bold]")
        yield DataTable(id="activity", zebra_stripes=True, cursor_type="row")
        yield Label("[bold]Recent snapshots[/bold]")
        yield DataTable(id="snaps", zebra_stripes=True, cursor_type="row")

    def on_mount(self) -> None:
        self.query_one("#activity", DataTable).add_columns(
            "Time", "Operation", "Version", "Size", "Path"
        )
        self.query_one("#snaps", DataTable).add_columns("ID", "Name", "Created", "Files", "Size")
        super().on_mount()

    def fetch(self) -> Any:
        b = self.backend
        return {
            "status": b.call("status"),
            "activity": b.call("activity", limit=25),
            "snapshots": b.call("list_snapshots")[:8],
            "mode": b.mode,
        }

    def show(self, data: dict[str, Any]) -> None:
        st = data["status"]
        d = st.get("daemon")
        running = data["mode"] == "daemon"
        self.query_one("#c-daemon", StatCard).set_value(
            "[green]running[/green]" if running else "[yellow]stopped[/yellow]",
            f"pid {d['pid']}" if d else "local mode",
        )
        self.query_one("#c-roots", StatCard).set_value(str(st["root_count"]))
        self.query_one("#c-files", StatCard).set_value(
            str(st["file_count"]), f"{st['deleted_file_count']} deleted"
        )
        self.query_one("#c-versions", StatCard).set_value(
            str(st["version_count"]), f"{st['snapshot_count']} snapshots"
        )
        self.query_one("#c-original", StatCard).set_value(size(st["logical_bytes"]))
        saved = st["logical_bytes"] - st["stored_bytes"]
        self.query_one("#c-stored", StatCard).set_value(
            size(st["stored_bytes"]), f"saved {size(max(saved, 0))}"
        )
        self.query_one("#start", Button).disabled = running
        self.query_one("#stop", Button).disabled = not running
        if d:
            watchers = ", ".join(f"#{w['root_id']} {w['mode']}" for w in d["watchers"]) or "none"
            errors = d["recent_errors"][-3:]
            detail = (
                f"Uptime {int(d['uptime_seconds'])}s · queue {d['queue_depth']}/{d['queue_capacity']} · "
                f"pending captures {d['pending_captures']} · dropped events {d['events_dropped']} · "
                f"last reconcile {when(d.get('last_reconcile_at'))} · watchers: {watchers}"
            )
            if errors:
                detail += "\n[red]" + "\n".join(errors) + "[/red]"
        else:
            detail = "[yellow]Daemon not running: changes are only recorded when you scan. Press 'Start daemon'.[/yellow]"
        self.query_one("#daemon-detail", Static).update(detail)
        act = self.query_one("#activity", DataTable)
        act.clear()
        for v in data["activity"]:
            act.add_row(
                when(v["timestamp"]),
                v["operation"],
                str(v["id"]),
                size(v["file_size"]) if v["blob_hash"] else "-",
                v["absolute_path"],
            )
        snaps = self.query_one("#snaps", DataTable)
        snaps.clear()
        for s in data["snapshots"]:
            snaps.add_row(
                str(s["id"]),
                s["name"],
                when(s["created_at"]),
                str(s["file_count"]),
                size(s["total_size"]),
            )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.do_action(event.button.id or "")

    @work(thread=True, exclusive=True, group="dashboard-action")
    def do_action(self, action: str) -> None:
        b = self.backend
        try:
            if action == "start":
                msg = b.start_daemon()
            elif action == "stop":
                msg = b.stop_daemon()
            elif action == "scan":
                self.app.call_from_thread(self.app.notify, "Scanning all roots ...")
                reports = b.call("scan")
                msg = (
                    "Scan: "
                    + "; ".join(
                        f"{r['root_path']}: +{r['new']} ~{r['modified']} -{r['deleted']}"
                        for r in reports
                    )
                    if reports
                    else "No roots to scan"
                )
            else:
                return
        except UndoError as exc:
            self.app.call_from_thread(self.app.notify, exc.message, severity="error")
            return
        self.app.call_from_thread(self.app.notify, msg)
        self.app.call_from_thread(self.reload)
