"""undo exclude ... / undo settings ..."""

from __future__ import annotations

import typer
from rich.table import Table

from undo_cli.commands.common import call, resolve_root, session
from undo_cli.output import render

exclude_app = typer.Typer(help="Manage exclusion patterns.", no_args_is_help=True)
settings_app = typer.Typer(help="Show and change settings.", no_args_is_help=True)


@exclude_app.command("add")
def exclude_add(
    ctx: typer.Context,
    pattern: str = typer.Argument(..., help="e.g. 'build/', '*.log', 'docs/drafts', '/abs/path'"),
    root: str | None = typer.Option(None, "--root", help="Only for this root (default: all roots)"),
) -> None:
    """Add an exclusion pattern."""
    with session(ctx) as b:
        info = b.call("add_exclusion", pattern=pattern, root=resolve_root(b, root))
    render.success(
        f"Excluding {info['pattern']}"
        + (f" in root {info['root_id']}" if info.get("root_id") else "")
    )
    render.console.print("[dim]Already captured history of matching files is kept.[/dim]")


@exclude_app.command("remove")
def exclude_remove(
    ctx: typer.Context,
    pattern: str = typer.Argument(...),
    root: str | None = typer.Option(None, "--root"),
) -> None:
    """Remove a user or default exclusion pattern."""
    with session(ctx) as b:
        info = b.call("remove_exclusion", pattern=pattern, root=resolve_root(b, root))
    render.success(
        f"Removed {info['source']} exclusion {info['pattern']}. Run `undo scan` to capture now-included files."
    )


@exclude_app.command("list")
def exclude_list(
    ctx: typer.Context,
    root: str | None = typer.Option(None, "--root"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """List every active exclusion and where it comes from."""
    with session(ctx) as b:
        data = b.call("list_exclusions", root=resolve_root(b, root))
    if json_out:
        render.print_json(data)
        return
    t = Table(title="Exclusions")
    for col in ("Pattern", "Source", "Scope"):
        t.add_column(col)
    for e in data:
        t.add_row(
            e["pattern"], e["source"], f"root {e['root_id']}" if e.get("root_id") else "all roots"
        )
    render.console.print(t)
    render.console.print(
        "[dim]builtin: always applied; default: from the exclusions.defaults setting; user: added by you.[/dim]"
    )


@settings_app.command("show")
def settings_show(
    ctx: typer.Context,
    key: str | None = typer.Argument(None, help="Show only this section or key"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Show settings."""
    data = call(ctx, "get_settings")
    info = data.pop("_info", {})
    if key:
        section, _, name = key.partition(".")
        if section not in data or (name and name not in data[section]):
            render.error(f"Unknown setting {key}")
            raise typer.Exit(2)
        data = {section: data[section]} if not name else {key: data[section][name]}
    if json_out:
        render.print_json(data)
        return
    t = Table(title=f"Settings ({info.get('config_path', '')})")
    t.add_column("Key", style="bold")
    t.add_column("Value")
    for section, values in data.items():
        if isinstance(values, dict):
            for k, v in values.items():
                if isinstance(v, list) and len(v) > 6:
                    v = ", ".join(map(str, v[:6])) + f", ... ({len(v)} items)"
                t.add_row(f"{section}.{k}", str(v))
        else:
            t.add_row(section, str(values))
    render.console.print(t)


@settings_app.command("set")
def settings_set(
    ctx: typer.Context,
    key: str = typer.Argument(..., help="section.name, e.g. compression.level"),
    value: str = typer.Argument(
        ..., help="Value; sizes like 500MB are accepted; lists as JSON or comma-separated"
    ),
) -> None:
    """Change a setting (validated; applied live by a running daemon)."""
    data = call(ctx, "set_setting", key=key, value=value)
    section, _, name = key.partition(".")
    render.success(f"{key} = {data[section][name]}")
    if section == "api":
        render.warn("API changes take effect after `undo restart`.")
