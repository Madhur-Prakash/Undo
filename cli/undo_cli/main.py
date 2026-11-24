"""`undo` command entry point."""

from __future__ import annotations

import typer

from undo_cli import __version__
from undo_cli.commands import daemon, history, restore, setup, tracking
from undo_cli.commands.common import State, handle_errors, state
from undo_cli.commands.settings import exclude_app, settings_app
from undo_cli.commands.snapshots import snapshot_app
from undo_cli.commands.storage import storage_app

app = typer.Typer(
    name="undo",
    help="Undo - automatic, local file version history. Recover overwritten and deleted files.",
    no_args_is_help=True,
    add_completion=True,
    rich_markup_mode="rich",
    pretty_exceptions_show_locals=False,
)


def _version(value: bool) -> None:
    if value:
        typer.echo(f"undo {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    ctx: typer.Context,
    data_dir: str | None = typer.Option(
        None,
        "--data-dir",
        envvar="UNDO_HOME",
        help="Undo data directory (default: platform location)",
    ),
    local: bool = typer.Option(
        False,
        "--local",
        help="Never use the daemon API (requires the daemon to be stopped for writes)",
    ),
    version: bool = typer.Option(
        False, "--version", callback=_version, is_eager=True, help="Show version"
    ),
) -> None:
    ctx.obj = State(data_dir=data_dir, local_only=local)


setup.register(app)
tracking.register(app)
daemon.register(app)
history.register(app)
restore.register(app)
app.add_typer(snapshot_app, name="snapshot")
app.add_typer(storage_app, name="storage")
app.add_typer(exclude_app, name="exclude")
app.add_typer(settings_app, name="settings")


@app.command()
def tui(ctx: typer.Context) -> None:
    """Interactive terminal dashboard."""
    from undo_cli.tui.app import UndoTUI

    st = state(ctx)
    with handle_errors():
        UndoTUI(st).run()


def run() -> None:
    app()


if __name__ == "__main__":
    run()
