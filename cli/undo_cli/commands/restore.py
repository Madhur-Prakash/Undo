"""restore, recover."""

from __future__ import annotations

from pathlib import Path

import typer

from undo_cli.commands.common import EXIT_CONFLICT, resolve_root, session
from undo_cli.output import render


def _finish(result: dict, json_out: bool) -> None:
    if json_out:
        render.print_json(result)
    else:
        render.restore_result(result)
    if result["errors"]:
        raise typer.Exit(1)
    if result["conflicts"]:
        raise typer.Exit(EXIT_CONFLICT)


def register(app: typer.Typer) -> None:
    @app.command()
    def restore(
        ctx: typer.Context,
        path: str = typer.Argument(..., help="File or directory (current or former path)"),
        version: int | None = typer.Option(None, "--version", "-v", help="Restore this version id"),
        at: str | None = typer.Option(
            None, "--at", help="State at a time: ISO (2024-05-01T13:00) or relative (2h, 3d)"
        ),
        before: int | None = typer.Option(
            None, "--before", help="Restore the version before this version id"
        ),
        to: str | None = typer.Option(
            None, "--to", help="Restore into this directory/file instead of the original location"
        ),
        overwrite: bool = typer.Option(
            False, "--overwrite", help="Replace existing files (their content is versioned first)"
        ),
        dry_run: bool = typer.Option(False, "--dry-run", "-n", help="Only show what would happen"),
        yes: bool = typer.Option(False, "--yes", "-y", help="Do not ask before overwriting"),
        json_out: bool = typer.Option(False, "--json"),
    ) -> None:
        """Restore a file or directory. Existing files are never overwritten without --overwrite."""
        args = dict(
            path=str(Path(path).absolute()),
            version_id=version,
            at=at,
            before_version_id=before,
            destination=str(Path(to).absolute()) + ("/" if to.endswith(("/", "\\")) else "")
            if to
            else None,
            overwrite=overwrite,
        )
        with session(ctx) as b:
            if overwrite and not dry_run and not yes and not json_out:
                plan = b.call("restore", dry_run=True, **args)
                render.restore_result(plan)
                n = plan["overwritten"]
                if n and not typer.confirm(f"Overwrite {n} existing file(s)?"):
                    raise typer.Abort()
            with render.console.status("Restoring ..." if not dry_run else "Planning ..."):
                result = b.call("restore", dry_run=dry_run, **args)
        _finish(result, json_out)

    @app.command()
    def recover(
        ctx: typer.Context,
        path: str | None = typer.Argument(
            None, help="Deleted file, or directory to recover deleted files from"
        ),
        root: str | None = typer.Option(None, "--root", help="Limit the listing to a root"),
        to: str | None = typer.Option(None, "--to", help="Recover into this directory"),
        overwrite: bool = typer.Option(False, "--overwrite"),
        dry_run: bool = typer.Option(False, "--dry-run", "-n"),
        json_out: bool = typer.Option(False, "--json"),
    ) -> None:
        """List deleted files, or recover one file / all deleted files below a directory."""
        with session(ctx) as b:
            if path is None:
                data = b.call("deleted_files", root_id=resolve_root(b, root))
                if json_out:
                    render.print_json(data)
                elif not data:
                    render.console.print("No deleted files with recoverable content.")
                else:
                    render.console.print(render.files_table(data, "Deleted files"))
                    render.console.print(
                        "Recover with [bold]undo recover PATH[/bold] (add --to DIR to recover elsewhere)."
                    )
                return
            result = b.call(
                "recover",
                path=str(Path(path).absolute()),
                destination=str(Path(to).absolute()) if to else None,
                overwrite=overwrite,
                dry_run=dry_run,
            )
        _finish(result, json_out)
