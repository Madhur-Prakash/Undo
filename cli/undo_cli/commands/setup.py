"""init, config, doctor."""

from __future__ import annotations

import typer
from rich.table import Table
from rich.text import Text
from undo_core.context import UndoContext
from undo_core.daemon.lifecycle import discover
from undo_core.platform.service import autostart_status

from undo_cli.commands.common import call, handle_errors, state
from undo_cli.output import render


def register(app: typer.Typer) -> None:
    @app.command()
    def init(
        ctx: typer.Context,
        json_out: bool = typer.Option(False, "--json", help="Machine-readable output"),
    ) -> None:
        """Create the data directory, database, settings and API token."""
        st = state(ctx)
        with handle_errors():
            context = UndoContext.open(st.data_dir, require_initialized=False)
            already = context.paths.is_initialized()
            applied = context.initialize()
            context.close()
        if json_out:
            render.print_json(
                {
                    "data_dir": str(st.paths.data_dir),
                    "already_initialized": already,
                    "migrations": applied,
                }
            )
            return
        render.success(
            ("Already initialised" if already else "Initialised") + f" in {st.paths.data_dir}"
        )
        if applied:
            render.console.print(f"[dim]Applied migrations: {', '.join(applied)}[/dim]")
        render.console.print("Next: [bold]undo track PATH[/bold] then [bold]undo start[/bold]")

    @app.command()
    def config(
        ctx: typer.Context,
        path: bool = typer.Option(False, "--path", help="Print only the settings file path"),
        json_out: bool = typer.Option(False, "--json"),
    ) -> None:
        """Show where Undo keeps its data and how it is configured."""
        st = state(ctx)
        paths = st.paths
        if path:
            typer.echo(str(paths.config_path))
            return
        found = discover(paths) if paths.is_initialized() else None
        info = {
            "data_dir": str(paths.data_dir),
            "settings_file": str(paths.config_path),
            "database": str(paths.db_path),
            "blobs": str(paths.blobs_dir),
            "logs": str(paths.logs_dir / "undo.log"),
            "api_token_file": str(paths.token_path),
            "initialized": paths.is_initialized(),
            "daemon": found[0].base_url if found else None,
            "autostart": autostart_status(),
        }
        if json_out:
            render.print_json(info)
            return
        render.console.print(
            render.kv_panel(
                "Configuration", [(k, v if v is not None else "-") for k, v in info.items()]
            )
        )
        render.console.print(
            "[dim]Change settings with `undo settings set KEY VALUE` (see `undo settings show`).[/dim]"
        )

    @app.command()
    def doctor(ctx: typer.Context, json_out: bool = typer.Option(False, "--json")) -> None:
        """Check the installation, database, storage and monitoring prerequisites."""
        checks = call(ctx, "doctor", spinner="Running checks...")
        if json_out:
            render.print_json(checks)
        else:
            t = Table(title="Undo doctor", show_lines=False)
            t.add_column("")
            t.add_column("Check")
            t.add_column("Detail")
            for c in checks:
                mark = (
                    Text("ok", style="green")
                    if c["ok"]
                    else Text(
                        "warn" if c["severity"] == "warning" else "FAIL",
                        style="yellow" if c["severity"] == "warning" else "bold red",
                    )
                )
                t.add_row(mark, c["name"], c["detail"])
            render.console.print(t)
        if any(not c["ok"] and c["severity"] == "error" for c in checks):
            raise typer.Exit(1)
