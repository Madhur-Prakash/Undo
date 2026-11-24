"""undo storage ..."""

from __future__ import annotations

import typer
from rich.text import Text

from undo_cli.commands.common import call
from undo_cli.output import render

storage_app = typer.Typer(
    help="Storage statistics, verification and garbage collection.", no_args_is_help=True
)


@storage_app.command("stats")
def stats(ctx: typer.Context, json_out: bool = typer.Option(False, "--json")) -> None:
    """Show storage usage and savings."""
    data = call(ctx, "storage_stats")
    if json_out:
        render.print_json(data)
    else:
        render.console.print(render.storage_stats(data))


@storage_app.command("verify")
def verify(
    ctx: typer.Context,
    quick: bool = typer.Option(
        False, "--quick", help="Only check that objects exist (no decompression)"
    ),
    no_repair: bool = typer.Option(
        False, "--no-repair", help="Do not re-store damaged blobs from live files"
    ),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Verify every stored object against its BLAKE3 hash."""
    rep = call(
        ctx, "verify_storage", spinner="Verifying storage ...", full=not quick, repair=not no_repair
    )
    if json_out:
        render.print_json(rep)
    else:
        rows = [
            ("mode", "full (decompress + hash)" if rep["full"] else "quick (existence)"),
            ("blobs / chunks checked", f"{rep['checked_blobs']} / {rep['checked_chunks']}"),
            ("ok", rep["ok"]),
            ("missing", Text(str(len(rep["missing"])), style="red" if rep["missing"] else "")),
            ("corrupt", Text(str(len(rep["corrupt"])), style="red" if rep["corrupt"] else "")),
            ("repaired", len(rep["repaired"])),
            ("orphan files", len(rep["orphan_files"])),
            ("database", "; ".join(rep["database_problems"]) or "ok"),
            ("duration", f"{rep['duration_seconds']}s"),
            (
                "result",
                Text("healthy", style="green")
                if rep["healthy"]
                else Text("PROBLEMS FOUND", style="bold red"),
            ),
        ]
        render.console.print(
            render.kv_panel("Verification", rows, "green" if rep["healthy"] else "red")
        )
        for h in (set(rep["missing"]) | set(rep["corrupt"])) - set(rep["repaired"]):
            render.console.print(f"  [red]damaged blob {h}[/red]")
    if not rep["healthy"]:
        raise typer.Exit(8)


@storage_app.command("gc")
def gc(
    ctx: typer.Context,
    dry_run: bool = typer.Option(
        False, "--dry-run", "-n", help="Only report what would be deleted"
    ),
    retention: bool = typer.Option(False, "--retention", help="Apply the retention policy first"),
    yes: bool = typer.Option(False, "--yes", "-y"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Delete stored data no longer referenced by any version or snapshot."""
    out: dict = {}
    if retention:
        out["retention"] = call(
            ctx, "apply_retention", spinner="Applying retention ...", dry_run=dry_run
        )
    if not dry_run and not yes and not json_out:
        preview = call(ctx, "garbage_collect", dry_run=True)
        render.console.print(
            f"Would reclaim {render.size(preview['reclaimable_bytes'] + preview['orphan_bytes'])} "
            f"({preview['candidate_blobs']} blobs, {preview['candidate_chunks']} chunks, {preview['orphan_files']} orphan files)"
        )
        if not typer.confirm("Proceed?"):
            raise typer.Abort()
    out["gc"] = call(ctx, "garbage_collect", spinner="Collecting garbage ...", dry_run=dry_run)
    if json_out:
        render.print_json(out)
        return
    if "retention" in out:
        r = out["retention"]
        render.console.print(
            f"Retention: {r['versions_removed']} of {r['versions_examined']} versions "
            f"{'would be ' if dry_run else ''}removed across {r['files_affected']} files"
        )
    g = out["gc"]
    rows = [
        ("unreferenced blobs", g["candidate_blobs"]),
        ("unreferenced chunks", g["candidate_chunks"]),
        ("protected (grace period)", g["protected_by_grace"]),
        ("orphan files", g["orphan_files"]),
        (
            "reclaimable" if dry_run else "reclaimed",
            render.size(
                g["reclaimable_bytes"] + g["orphan_bytes"] if dry_run else g["reclaimed_bytes"]
            ),
        ),
    ]
    for e in g["errors"]:
        rows.append(("error", Text(e, style="red")))
    render.console.print(
        render.kv_panel("Garbage collection" + (" (dry run)" if dry_run else ""), rows)
    )


@storage_app.command("retention")
def retention_cmd(
    ctx: typer.Context,
    dry_run: bool = typer.Option(False, "--dry-run", "-n"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Apply the configured retention policy (removes version records; run gc to free space)."""
    r = call(ctx, "apply_retention", spinner="Applying retention ...", dry_run=dry_run)
    if json_out:
        render.print_json(r)
        return
    render.console.print(
        f"{r['versions_removed']} of {r['versions_examined']} versions {'would be ' if dry_run else ''}removed "
        f"across {r['files_affected']} files; ~{render.size(r['estimated_reclaim_bytes'])} reclaimable by gc"
    )
