"""start, stop, restart, status, logs, service."""

from __future__ import annotations

import json
import time
from collections import deque
from pathlib import Path

import typer
from rich.text import Text
from undo_core.daemon.lifecycle import discover, start_background, stop_daemon
from undo_core.daemon.manager import DaemonManager
from undo_core.platform.service import autostart_status, install_autostart, uninstall_autostart
from undo_core.utils.errors import NotInitializedError
from undo_core.utils.logging import LOG_FILE_NAME

from undo_cli.commands.common import handle_errors, state
from undo_cli.output import render

service_app = typer.Typer(
    help="Install or remove automatic daemon startup (systemd / Windows).", no_args_is_help=True
)


def _status_payload(ctx: typer.Context) -> dict:
    from undo_cli.client import Backend, LocalBackend, RemoteBackend

    st = state(ctx)
    paths = st.paths
    if not paths.is_initialized():
        raise NotInitializedError(f"Undo is not initialised in {paths.data_dir}")
    found = discover(paths)
    backend: Backend
    if found:
        backend = RemoteBackend(*found)
    else:
        backend = LocalBackend(paths)
    try:
        status = backend.call("status")
    finally:
        backend.close()
    status["daemon_running"] = found is not None
    return status


def register(app: typer.Typer) -> None:
    @app.command()
    def start(
        ctx: typer.Context,
        foreground: bool = typer.Option(
            False, "--foreground", "-f", help="Run in this terminal (Ctrl+C stops)"
        ),
    ) -> None:
        """Start the background daemon."""
        st = state(ctx)
        with handle_errors():
            if not st.paths.is_initialized():
                raise NotInitializedError(f"Undo is not initialised in {st.paths.data_dir}")
            if foreground:
                render.console.print(
                    f"Running daemon in the foreground for {st.paths.data_dir} (Ctrl+C to stop)"
                )
                raise typer.Exit(DaemonManager(st.paths.data_dir, console_log=True).run())
            found = discover(st.paths)
            if found:
                render.success(f"Daemon already running (pid {found[0].pid}, {found[0].base_url})")
                return
            with render.console.status("Starting daemon ..."):
                info = start_background(st.paths)
        render.success(f"Daemon started (pid {info.pid}, {info.base_url})")

    @app.command()
    def stop(ctx: typer.Context) -> None:
        """Stop the daemon gracefully."""
        st = state(ctx)
        with handle_errors(), render.console.status("Stopping daemon ..."):
            stopped = stop_daemon(st.paths)
        if stopped:
            render.success("Daemon stopped")
        else:
            render.console.print("Daemon was not running.")

    @app.command()
    def restart(ctx: typer.Context) -> None:
        """Restart the daemon."""
        st = state(ctx)
        with handle_errors():
            with render.console.status("Stopping daemon ..."):
                stop_daemon(st.paths)
            with render.console.status("Starting daemon ..."):
                info = start_background(st.paths)
        render.success(f"Daemon restarted (pid {info.pid}, {info.base_url})")

    @app.command()
    def status(ctx: typer.Context, json_out: bool = typer.Option(False, "--json")) -> None:
        """Show daemon state and a summary of what is protected."""
        with handle_errors():
            data = _status_payload(ctx)
        if json_out:
            render.print_json(data)
            return
        d = data.get("daemon")
        rows: list[tuple[str, object]] = [
            (
                "daemon",
                Text("running", style="green")
                if data["daemon_running"]
                else Text("stopped", style="yellow"),
            ),
        ]
        if d:
            rows += [
                ("pid / uptime", f"{d['pid']} / {int(d['uptime_seconds'])}s"),
                ("api", d.get("api_url") or "-"),
                (
                    "event queue",
                    f"{d['queue_depth']}/{d['queue_capacity']} (dropped {d['events_dropped']})",
                ),
                ("pending captures", d["pending_captures"]),
                ("reconciling", "yes" if d["reconciling"] else "no"),
                ("last full reconcile", render.when(d.get("last_reconcile_at"))),
                (
                    "captures",
                    ", ".join(f"{k}={v}" for k, v in sorted(d["captures"].items())) or "-",
                ),
            ]
            for w in d["watchers"]:
                rows.append(
                    (
                        f"watch #{w['root_id']}",
                        f"{w['mode']}{' - ' + w['error'] if w.get('error') else ''}  {w['path']}",
                    )
                )
        rows += [
            ("data directory", data["data_dir"]),
            (
                "roots / files / deleted",
                f"{data['root_count']} / {data['file_count']} / {data['deleted_file_count']}",
            ),
            ("versions / snapshots", f"{data['version_count']} / {data['snapshot_count']}"),
            (
                "stored / original",
                f"{render.size(data['stored_bytes'])} / {render.size(data['logical_bytes'])}",
            ),
            ("skipped files", data["skipped_count"]),
        ]
        render.console.print(
            render.kv_panel("Undo status", rows, "green" if data["daemon_running"] else "yellow")
        )
        if d and d.get("recent_errors"):
            render.console.print("[bold]Recent errors[/bold]")
            for e in d["recent_errors"][-5:]:
                render.console.print(f"  [red]{e}[/red]")

    @app.command()
    def logs(
        ctx: typer.Context,
        lines: int = typer.Option(50, "--lines", "-n"),
        follow: bool = typer.Option(False, "--follow", "-f"),
        raw: bool = typer.Option(False, "--raw", help="Print JSON lines unchanged"),
    ) -> None:
        """Show the daemon log."""
        path: Path = state(ctx).paths.logs_dir / LOG_FILE_NAME
        if not path.exists():
            render.console.print(f"No log file yet at {path}")
            return

        def show(line: str) -> None:
            if raw:
                typer.echo(line.rstrip("\n"))
                return
            try:
                rec = json.loads(line)
            except ValueError:
                typer.echo(line.rstrip("\n"))
                return
            style = {"ERROR": "red", "WARNING": "yellow", "DEBUG": "dim"}.get(
                rec.get("level", ""), ""
            )
            extra = {
                k: v for k, v in rec.items() if k not in ("ts", "level", "logger", "msg", "exc")
            }
            text = Text(
                f"{rec.get('ts', '')} {rec.get('level', ''):<7} {rec.get('logger', '')}: {rec.get('msg', '')}",
                style=style,
            )
            if extra:
                text.append("  " + " ".join(f"{k}={v}" for k, v in extra.items()), style="dim")
            render.console.print(text)
            if rec.get("exc"):
                render.console.print(Text(rec["exc"], style="red dim"))

        with open(path, encoding="utf-8", errors="replace") as fh:
            for line in deque(fh, maxlen=lines):
                show(line)
            if follow:
                try:
                    while True:
                        line = fh.readline()
                        if line:
                            show(line)
                        else:
                            time.sleep(0.5)
                except KeyboardInterrupt:
                    return

    @service_app.command("install")
    def service_install(
        ctx: typer.Context,
        system: bool = typer.Option(False, "--system", help="System-wide (Linux: needs root)"),
    ) -> None:
        """Start the daemon automatically (systemd user unit / Windows logon task)."""
        with handle_errors():
            result = install_autostart(state(ctx).paths, system=system)
        (render.success if result.ok else render.error)(
            result.message + (f" ({result.path})" if result.path else "")
        )
        if not result.ok:
            raise typer.Exit(1)

    @service_app.command("uninstall")
    def service_uninstall(
        ctx: typer.Context, system: bool = typer.Option(False, "--system")
    ) -> None:
        """Remove automatic startup."""
        with handle_errors():
            result = uninstall_autostart(system=system)
        (render.success if result.ok else render.error)(result.message)

    @service_app.command("status")
    def service_status() -> None:
        """Show whether automatic startup is installed."""
        render.console.print(autostart_status())

    app.add_typer(service_app, name="service")
