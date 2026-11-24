"""track, untrack, roots, scan, skipped."""

from __future__ import annotations

from pathlib import Path

import typer
from rich.table import Table

from undo_cli.commands.common import call, resolve_root, session
from undo_cli.output import render


def register(app: typer.Typer) -> None:
    @app.command()
    def track(
        ctx: typer.Context,
        path: Path = typer.Argument(..., help="Directory to protect"),
        no_scan: bool = typer.Option(False, "--no-scan", help="Do not run the initial scan now"),
        json_out: bool = typer.Option(False, "--json"),
    ) -> None:
        """Start tracking a directory (captures its current state)."""
        # Resolve here: the daemon has its own working directory, so "." or a relative path
        # sent as typed would name a different folder there.
        target = path.expanduser().resolve()
        with session(ctx) as b:
            with render.console.status(f"Tracking {target} ..."):
                result = b.call("add_root", path=str(target), scan=not no_scan)
            mode = b.mode
        if json_out:
            render.print_json(result)
            return
        render.success(f"Tracking {result['root']['path']} (root {result['root']['id']})")
        if result.get("scan"):
            render.console.print(render.scan_report(result["scan"]))
        elif not no_scan and mode == "daemon":
            render.console.print(
                "[dim]The daemon is running the initial scan in the background.[/dim]"
            )
        if mode == "local":
            render.console.print(
                "[dim]Start the daemon (`undo start`) for continuous monitoring.[/dim]"
            )

    @app.command()
    def untrack(
        ctx: typer.Context,
        path: str = typer.Argument(..., help="Root path or id"),
        purge: bool = typer.Option(
            False, "--purge", help="Also delete all recorded history of this root"
        ),
        yes: bool = typer.Option(False, "--yes", "-y", help="Do not ask for confirmation"),
        json_out: bool = typer.Option(False, "--json"),
    ) -> None:
        """Stop tracking a directory. History is kept unless --purge is given."""
        if purge and not yes:
            typer.confirm(
                f"Delete ALL history for {path}? Stored data becomes eligible for garbage collection.",
                abort=True,
            )
        with session(ctx) as b:
            root_id = resolve_root(b, path)
            result = b.call("remove_root", ref=root_id, purge=purge)
        if json_out:
            render.print_json(result)
        else:
            render.success(
                f"{'Purged' if purge else 'Stopped tracking (history kept)'}: {result['path']}"
            )

    @app.command()
    def roots(ctx: typer.Context, json_out: bool = typer.Option(False, "--json")) -> None:
        """List tracked roots."""
        data = call(ctx, "list_roots")
        if json_out:
            render.print_json(data)
        elif not data:
            render.console.print("No roots tracked yet. Use [bold]undo track PATH[/bold].")
        else:
            render.console.print(render.roots_table(data))

    @app.command()
    def scan(
        ctx: typer.Context,
        path: str | None = typer.Argument(
            None, help="Root, directory inside a root, or omit for all roots"
        ),
        deep: bool = typer.Option(
            False, "--deep", help="Re-hash every file instead of trusting size+mtime"
        ),
        json_out: bool = typer.Option(False, "--json"),
    ) -> None:
        """Reconcile the database with the filesystem (finds missed changes)."""
        target = str(Path(path).absolute()) if path and not path.isdigit() else path
        reports = call(ctx, "scan", spinner="Scanning ...", target=target, deep=deep)
        if json_out:
            render.print_json(reports)
            return
        if not reports:
            render.console.print("No enabled roots to scan.")
        for rep in reports:
            render.console.print(render.scan_report(rep))
        if any(r["failed"] for r in reports):
            raise typer.Exit(1)

    @app.command()
    def skipped(
        ctx: typer.Context,
        root: str | None = typer.Option(None, "--root", help="Root id or path"),
        limit: int = typer.Option(200, "--limit", "-n"),
        json_out: bool = typer.Option(False, "--json"),
    ) -> None:
        """Show files that were not captured, and why."""
        with session(ctx) as b:
            data = b.call("skipped_files", root_id=resolve_root(b, root), limit=limit)
        if json_out:
            render.print_json(data)
            return
        if not data:
            render.console.print("Nothing skipped.")
            return
        t = Table(title="Skipped files")
        for col in ("Root", "Path", "Reason", "Detail", "Last seen", "Count"):
            t.add_column(col)
        for s in data:
            t.add_row(
                str(s["root_id"]),
                s["relative_path"],
                s["reason"],
                s.get("detail") or "",
                render.when(s["last_seen"]),
                str(s["count"]),
            )
        render.console.print(t)
