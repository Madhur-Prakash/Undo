"""undo snapshot ..."""

from __future__ import annotations

from pathlib import Path

import typer
from rich.table import Table
from rich.text import Text

from undo_cli import sorting
from undo_cli.commands.common import EXIT_CONFLICT, call, resolve_root, session
from undo_cli.output import render

snapshot_app = typer.Typer(help="Named, manual snapshots of a root.", no_args_is_help=True)


@snapshot_app.command("create")
def create(
    ctx: typer.Context,
    name: str = typer.Option(..., "--name", help="Unique name, e.g. before-upgrade"),
    root: str | None = typer.Option(
        None, "--root", help="Root id or path (optional with one root)"
    ),
    description: str | None = typer.Option(None, "--description", "-d"),
    no_scan: bool = typer.Option(
        False, "--no-scan", help="Skip the consistency scan before snapshotting"
    ),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Record the current state of every file in a root."""
    with session(ctx) as b:
        root_id = resolve_root(b, root)
        with render.console.status("Scanning and creating snapshot ..."):
            snap = b.call(
                "create_snapshot",
                name=name,
                root=root_id,
                description=description,
                scan=not no_scan,
            )
    if json_out:
        render.print_json(snap)
    else:
        render.success(
            f"Snapshot {snap['id']} '{snap['name']}': {snap['file_count']} files, {render.size(snap['total_size'])}"
        )


@snapshot_app.command("list")
def list_cmd(
    ctx: typer.Context,
    root: str | None = typer.Option(None, "--root"),
    sort: str = typer.Option(
        "created", "--sort", "-s", help=sorting.choices(sorting.SNAPSHOT_SORTS)
    ),
    reverse: bool = typer.Option(
        False, "--reverse", "-r", help="Flip the order (e.g. oldest first)"
    ),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """List snapshots."""
    if sort not in sorting.SNAPSHOT_SORTS:
        raise typer.BadParameter(
            f"choose one of: {sorting.choices(sorting.SNAPSHOT_SORTS)}", param_hint="--sort"
        )
    with session(ctx) as b:
        data = b.call("list_snapshots", root=resolve_root(b, root))
    data = sorting.sort_rows(data, sorting.SNAPSHOT_SORTS, sort, reverse)
    if json_out:
        render.print_json(data)
    elif not data:
        render.console.print(
            "No snapshots yet. Create one with [bold]undo snapshot create --name NAME[/bold]."
        )
    else:
        render.console.print(render.snapshots_table(data))


@snapshot_app.command("show")
def show(
    ctx: typer.Context,
    snapshot: str = typer.Argument(..., help="Snapshot id or name"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Show the files recorded in a snapshot."""
    data = call(ctx, "get_snapshot", ref=snapshot)
    if json_out:
        render.print_json(data)
        return
    s = data["snapshot"]
    render.console.print(
        render.kv_panel(
            f"Snapshot {s['id']}: {s['name']}",
            [
                ("created", render.when(s["created_at"])),
                ("root", s["root_path"]),
                ("files", s["file_count"]),
                ("size", render.size(s["total_size"])),
                ("description", s.get("description") or "-"),
            ],
        )
    )
    t = Table()
    for col in ("Path", "Version", "Size", "Hash"):
        t.add_column(col)
    for e in data["entries"]:
        t.add_row(
            e["relative_path"],
            str(e["version_id"]),
            render.size(e["file_size"]),
            render.short_hash(e["blob_hash"]),
        )
    render.console.print(t)


@snapshot_app.command("diff")
def diff(
    ctx: typer.Context,
    snapshot_a: str = typer.Argument(...),
    snapshot_b: str = typer.Argument(...),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Compare two snapshots."""
    d = call(ctx, "diff_snapshots", a=snapshot_a, b=snapshot_b)
    if json_out:
        render.print_json(d)
        return
    render.console.print(
        f"[bold]{d['a']['name']}[/bold] -> [bold]{d['b']['name']}[/bold]: "
        f"{len(d['added'])} added, {len(d['removed'])} removed, {len(d['modified'])} modified, {d['unchanged']} unchanged"
    )
    for label, items, style in (
        ("+", d["added"], "green"),
        ("-", d["removed"], "red"),
        ("~", d["modified"], "cyan"),
    ):
        for c in items:
            render.console.print(Text(f" {label} {c['relative_path']}", style=style))


@snapshot_app.command("restore")
def restore(
    ctx: typer.Context,
    snapshot: str = typer.Argument(...),
    to: str | None = typer.Option(
        None, "--to", help="Restore into this directory instead of the root"
    ),
    path: str | None = typer.Option(
        None, "--path", help="Only restore this sub-directory (relative to the root)"
    ),
    overwrite: bool = typer.Option(False, "--overwrite"),
    dry_run: bool = typer.Option(False, "--dry-run", "-n"),
    yes: bool = typer.Option(False, "--yes", "-y"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Restore the files of a snapshot. Files not in the snapshot are left alone."""
    args = dict(
        ref=snapshot,
        destination=str(Path(to).absolute()) if to else None,
        prefix=path or "",
        overwrite=overwrite,
    )
    with session(ctx) as b:
        if overwrite and not dry_run and not yes and not json_out:
            plan = b.call("restore_snapshot", dry_run=True, **args)
            render.restore_result(plan)
            if plan["overwritten"] and not typer.confirm(
                f"Overwrite {plan['overwritten']} existing file(s)?"
            ):
                raise typer.Abort()
        with render.console.status("Restoring snapshot ..."):
            result = b.call("restore_snapshot", dry_run=dry_run, **args)
    if json_out:
        render.print_json(result)
    else:
        render.restore_result(result)
    if result["errors"]:
        raise typer.Exit(1)
    if result["conflicts"]:
        raise typer.Exit(EXIT_CONFLICT)


@snapshot_app.command("delete")
def delete(
    ctx: typer.Context,
    snapshot: str = typer.Argument(...),
    yes: bool = typer.Option(False, "--yes", "-y"),
) -> None:
    """Delete a snapshot (file versions remain; unreferenced data is reclaimed by gc)."""
    if not yes:
        typer.confirm(f"Delete snapshot {snapshot}?", abort=True)
    info = call(ctx, "delete_snapshot", ref=snapshot)
    render.success(f"Deleted snapshot {info['id']} '{info['name']}'")
