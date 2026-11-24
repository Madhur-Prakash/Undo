"""history, versions, log, search, show, diff, cat."""

from __future__ import annotations

from pathlib import Path

import typer
from rich.syntax import Syntax
from rich.table import Table

from undo_cli.commands.common import call, resolve_root, session
from undo_cli.output import render


def _abs(path: str) -> str:
    return str(Path(path).absolute())


def register(app: typer.Typer) -> None:
    @app.command()
    def history(
        ctx: typer.Context,
        path: str = typer.Argument(..., help="Current or former path of a file"),
        limit: int | None = typer.Option(None, "--limit", "-n"),
        json_out: bool = typer.Option(False, "--json"),
    ) -> None:
        """Full history of a file: versions, operations and path changes."""
        data = call(ctx, "file_history", path=_abs(path), limit=limit)
        if json_out:
            render.print_json(data)
            return
        f = data["file"]
        rows = [
            ("file", f["absolute_path"]),
            ("state", "deleted " + render.when(f["deleted_at"]) if f["is_deleted"] else "live"),
            ("size", render.size(f.get("size"))),
            ("versions", f["version_count"]),
            ("tracked since", render.when(f["created_at"])),
        ]
        if len(data["paths"]) > 1:
            rows.append(("former paths", ", ".join(p["relative_path"] for p in data["paths"][:-1])))
        render.console.print(render.kv_panel(f"History of {f['name']} (file {f['id']})", rows))
        render.console.print(render.versions_table(data["versions"]))

    @app.command()
    def versions(
        ctx: typer.Context,
        path: str = typer.Argument(...),
        json_out: bool = typer.Option(False, "--json"),
    ) -> None:
        """Compact list of a file's versions (ids for `undo restore --version`)."""
        data = call(ctx, "file_history", path=_abs(path))
        if json_out:
            render.print_json(data["versions"])
            return
        t = Table(title=data["file"]["absolute_path"])
        for col in ("Version", "Time", "Op", "Size", "Hash"):
            t.add_column(col)
        for v in data["versions"]:
            t.add_row(
                str(v["id"]),
                render.when(v["timestamp"]),
                render.op_text(v["operation"]),
                render.size(v["file_size"]) if v["blob_hash"] else "-",
                render.short_hash(v["blob_hash"]),
            )
        render.console.print(t)

    @app.command("log")
    def log_cmd(
        ctx: typer.Context,
        limit: int = typer.Option(50, "--limit", "-n"),
        since: str | None = typer.Option(None, "--since", help="ISO time or relative (2h, 3d)"),
        root: str | None = typer.Option(None, "--root"),
        json_out: bool = typer.Option(False, "--json"),
    ) -> None:
        """Recent changes across all tracked roots."""
        with session(ctx) as b:
            data = b.call("activity", limit=limit, since=since, root_id=resolve_root(b, root))
        if json_out:
            render.print_json(data)
        elif not data:
            render.console.print("No activity recorded yet.")
        else:
            render.console.print(render.activity_table(data))

    @app.command()
    def search(
        ctx: typer.Context,
        query: str = typer.Argument(..., help="Part of a current or historical path"),
        limit: int = typer.Option(100, "--limit", "-n"),
        json_out: bool = typer.Option(False, "--json"),
    ) -> None:
        """Find files by current or historical path."""
        data = call(ctx, "search", query=query, limit=limit)
        if json_out:
            render.print_json(data)
            return
        if not data:
            render.console.print("No matches.")
            return
        t = Table(title=f"Search: {query}")
        for col in ("File", "Path", "Matched", "State", "Versions"):
            t.add_column(col)
        for hit in data:
            f = hit["file"]
            t.add_row(
                str(f["id"]),
                f["absolute_path"],
                hit["matched_path"] + (" (former path)" if hit["historical"] else ""),
                "deleted" if f["is_deleted"] else "live",
                str(f["version_count"]),
            )
        render.console.print(t)

    @app.command()
    def show(
        ctx: typer.Context,
        version_id: int = typer.Argument(...),
        json_out: bool = typer.Option(False, "--json"),
    ) -> None:
        """Details of one version (hash, compression, neighbours)."""
        d = call(ctx, "get_version", version_id=version_id)
        if json_out:
            render.print_json(d)
            return
        v, b = d["version"], d.get("blob")
        rows = [
            ("file", v["absolute_path"]),
            ("operation", render.op_text(v["operation"])),
            ("time", render.when(v["timestamp"])),
            ("size", render.size(v["file_size"]) if v["blob_hash"] else "-"),
            ("hash (BLAKE3)", v["blob_hash"] or "-"),
            (
                "previous / next",
                f"{d.get('previous_version_id') or '-'} / {d.get('next_version_id') or '-'}",
            ),
        ]
        if b:
            rows += [
                (
                    "storage",
                    f"{b['storage_kind']}, {b['compression_algorithm']}"
                    + (f" level {b['compression_level']}" if b.get("compression_level") else ""),
                ),
                (
                    "stored size",
                    f"{render.size(b['compressed_size'])} of {render.size(b['original_size'])}",
                ),
                ("blob status", b["status"]),
                ("references", b["reference_count"]),
            ]
        if v["metadata"].get("from_path"):
            rows.append(("moved from", v["metadata"]["from_path"]))
        render.console.print(render.kv_panel(f"Version {v['id']}", rows))

    @app.command()
    def diff(
        ctx: typer.Context,
        version_a: int = typer.Argument(...),
        version_b: int = typer.Argument(...),
        unified: bool = typer.Option(
            False, "--unified", "-u", help="Classic unified diff instead of side by side"
        ),
        json_out: bool = typer.Option(False, "--json"),
    ) -> None:
        """Compare two versions side by side (old left, new right), like an editor's diff.

        Narrow terminals (under 100 columns) and --unified get a unified diff instead.
        Line-ending changes (CRLF/LF) are ignored and reported in the summary.
        """
        d = call(ctx, "diff_versions", a=version_a, b=version_b)
        if json_out:
            render.print_json(d)
            return
        if d.get("hunks") and not unified and render.console.width >= 100:
            render.console.print(render.side_by_side_diff(d))
        elif d.get("diff"):
            render.console.print(Syntax(d["diff"], "diff", theme="ansi_dark", word_wrap=True))
        render.console.print(render.diff_summary(d))

    @app.command()
    def cat(ctx: typer.Context, version_id: int = typer.Argument(...)) -> None:
        """Print the text content of a version."""
        d = call(ctx, "version_content", version_id=version_id, max_bytes=8 * 1024 * 1024)
        if not d["is_text"]:
            render.error(
                "Binary content; restore it with `undo restore PATH --version ID --to DIR`."
            )
            raise typer.Exit(1)
        typer.echo(d["text"], nl=False)
        if d["truncated"]:
            render.warn("output truncated")
