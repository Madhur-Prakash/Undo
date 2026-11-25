"""history, versions, log, search, show, diff, cat."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

import click
import typer
from rich.syntax import Syntax
from rich.table import Table

from undo_cli import sorting
from undo_cli.commands.common import call, resolve_root, session
from undo_cli.output import render


def _check_sort(key: str, table: Mapping[str, object]) -> str:
    if key not in table:
        raise typer.BadParameter(f"choose one of: {sorting.choices(table)}", param_hint="--sort")
    return key


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
    def forget(
        ctx: typer.Context,
        path: str = typer.Argument(
            ..., help="A file (current or former path) or a folder in a tracked root"
        ),
        before: str | None = typer.Option(
            None,
            "--before",
            help="Only remove versions older than this: ISO (2026-10-01) or relative (30d, 2w). "
            "Each file's latest version is kept.",
        ),
        dry_run: bool = typer.Option(
            False, "--dry-run", "-n", help="Only show what would be removed"
        ),
        yes: bool = typer.Option(False, "--yes", "-y", help="Do not ask for confirmation"),
        json_out: bool = typer.Option(False, "--json"),
    ) -> None:
        """Remove the history of one file or one folder (or only its older versions).

        Your files are not touched. Snapshot versions are kept. Without --before the file's whole
        history goes; if the file still exists it is captured again as a new file.
        """
        target = _abs(path)
        plan = call(ctx, "forget", path=target, before=before, dry_run=True)
        if json_out and dry_run:
            render.print_json(plan)
            return
        render.console.print(render.forget_result(plan))
        if dry_run or plan["versions_removed"] == 0:
            return
        if not yes:
            typer.confirm(
                f"Permanently remove {plan['versions_removed']} version(s) of {plan['files_affected']} file(s)?",
                abort=True,
            )
        result = call(ctx, "forget", path=target, before=before, dry_run=False)
        if json_out:
            render.print_json(result)
            return
        render.console.print(render.forget_result(result))

    @app.command("delete-versions")
    def delete_versions(
        ctx: typer.Context,
        version_ids: list[int] = typer.Argument(
            ..., help="Version ids (from `undo versions PATH`)"
        ),
        yes: bool = typer.Option(False, "--yes", "-y", help="Do not ask for confirmation"),
        json_out: bool = typer.Option(False, "--json"),
    ) -> None:
        """Delete individual versions of a file.

        A file's latest version cannot be deleted this way (use `undo forget PATH`), and versions in
        a snapshot are refused until the snapshot is deleted.
        """
        plan = call(ctx, "delete_versions", version_ids=version_ids, dry_run=True)
        if not yes:
            typer.confirm(f"Permanently delete {plan['target']}?", abort=True)
        result = call(ctx, "delete_versions", version_ids=version_ids, dry_run=False)
        if json_out:
            render.print_json(result)
            return
        render.console.print(render.forget_result(result))

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
        sort: str = typer.Option(
            "time",
            "--sort",
            "-s",
            help=f"{sorting.choices(sorting.ACTIVITY_SORTS)} (applies to the --limit newest events)",
        ),
        reverse: bool = typer.Option(
            False, "--reverse", "-r", help="Flip the order (e.g. oldest first)"
        ),
        json_out: bool = typer.Option(False, "--json"),
    ) -> None:
        """Recent changes across all tracked roots."""
        _check_sort(sort, sorting.ACTIVITY_SORTS)
        with session(ctx) as b:
            data = b.call("activity", limit=limit, since=since, root_id=resolve_root(b, root))
        data = sorting.sort_rows(data, sorting.ACTIVITY_SORTS, sort, reverse)
        if json_out:
            render.print_json(data)
        elif not data:
            render.console.print("No activity recorded yet.")
        else:
            render.console.print(render.activity_table(data))

    @app.command()
    def files(
        ctx: typer.Context,
        query: str | None = typer.Argument(None, help="Only paths containing this text"),
        root: str | None = typer.Option(None, "--root"),
        deleted: bool = typer.Option(False, "--deleted", "-d", help="Include deleted files"),
        sort: str = typer.Option("path", "--sort", "-s", help=sorting.choices(sorting.FILE_SORTS)),
        reverse: bool = typer.Option(
            False, "--reverse", "-r", help="Flip the order (Z to A, smallest or oldest first)"
        ),
        limit: int = typer.Option(100, "--limit", "-n"),
        json_out: bool = typer.Option(False, "--json"),
    ) -> None:
        """List tracked files, sorted by path, last modified, size or history."""
        _check_sort(sort, sorting.FILE_SORTS)
        with session(ctx) as b:
            data = b.call(
                "list_files",
                query=query,
                root_id=resolve_root(b, root),
                include_deleted=deleted,
                limit=limit,
                **sorting.file_sort_args(sort, reverse),
            )
        if json_out:
            render.print_json(data)
        elif not data["items"]:
            render.console.print("No tracked files match." if query else "No tracked files yet.")
        else:
            title = f"Files ({len(data['items'])} of {data['total']}, by {sorting.FILE_SORTS[sort][0].lower()})"
            render.console.print(render.files_table(data["items"], title=title))

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
    def merge(
        ctx: typer.Context,
        version_id: int = typer.Argument(..., help="Stored version id (from `undo versions PATH`)"),
        path: str | None = typer.Argument(
            None, help="File to merge into (default: the version's file at its current location)"
        ),
        all_choice: str | None = typer.Option(
            None, "--all", help="Answer every difference: disk or version (no questions)"
        ),
        yes: bool = typer.Option(False, "--yes", "-y", help="With --all: write without asking"),
    ) -> None:
        """Resolve a restore like a merge conflict, interactively (same rules as the app and TUI).

        For each difference between the file on disk (left) and the version (right) choose
        [d]isk, [v]ersion or [b]oth. Then write the result to the file (its current content is
        saved as a version first), edit it in your editor, save progress to resume later, or
        discard. Only files inside tracked folders.
        """
        from undo_core.recovery.merge import compose_result

        if all_choice not in (None, "disk", "version"):
            raise typer.BadParameter("--all must be disk or version")
        src = call(ctx, "merge_source", version_id=version_id, path=_abs(path) if path else None)
        if src["identical"]:
            render.console.print(
                "[green]Identical:[/green] the file already has this version's content."
            )
            return
        hunks = src["hunks"]
        choices: dict[int, str] = {i: "disk" for i in range(len(hunks))}
        text: str | None = None
        edited = False
        draft = src.get("draft")
        if draft and draft.get("version_id") == version_id and all_choice is None:
            if typer.confirm(
                f"Resume the unfinished merge saved {render.when(draft.get('updated_at'))}?",
                default=True,
            ):
                for key, value in (draft.get("choices") or {}).items():
                    if str(key).isdigit() and value in ("disk", "version", "both"):
                        choices[int(key)] = value
                text, edited = draft["text"], bool(draft.get("edited"))

        render.console.print(
            f"[bold]Resolve {src['path']}[/bold]: left = on disk now, right = version {version_id}"
        )
        if all_choice is not None:
            choices = {i: all_choice for i in range(len(hunks))}
        elif text is None:
            answers = {"d": "disk", "v": "version", "b": "both"}
            for i, hunk in enumerate(hunks):
                view = {**src, "hunks": [hunk]}
                render.console.print(f"\n[bold]Difference {i + 1} of {len(hunks)}[/bold]")
                render.console.print(render.side_by_side_diff(view))
                answer = (
                    typer.prompt("[d]isk / [v]ersion / [b]oth / [q] stop choosing", default="d")
                    .strip()
                    .lower()[:1]
                )
                if answer == "q":
                    break
                choices[i] = answers.get(answer, "disk")
        if text is None:
            text = compose_result(src["current_lines"], hunks, choices)

        def write_file() -> bool:
            call(
                ctx,
                "merge_write",
                path=src["path"],
                text=text,
                version_id=version_id,
                expected_hash=src["current_hash"],
            )
            render.success(
                f"Merged result saved to {src['path']} (its previous content is a version)"
            )
            return True

        if all_choice is not None and yes:
            write_file()
            return
        while True:
            summary = ", ".join(f"{i + 1}: {choices[i]}" for i in sorted(choices))
            render.console.print(
                f"\n[bold]Result[/bold] ({len(text.splitlines())} lines{', edited by hand' if edited else ''}) · {summary}"
            )
            action = (
                typer.prompt(
                    "[w]rite to file / [s]how result / [e]dit in editor / [p] save progress / [x] discard",
                    default="w",
                )
                .strip()
                .lower()[:1]
            )
            if action == "w":
                if typer.confirm(f"Write the merged result to {src['path']}?", default=True):
                    write_file()
                    return
            elif action == "s":
                render.console.print(Syntax(text, "text", line_numbers=True, word_wrap=True))
            elif action == "e":
                changed = click.edit(text)
                if changed is not None and changed.rstrip("\n") != text:
                    text, edited = changed.rstrip("\n"), True
            elif action == "p":
                call(
                    ctx,
                    "save_merge_draft",
                    path=src["path"],
                    version_id=version_id,
                    text=text,
                    choices={str(k): v for k, v in choices.items()},
                    edited=edited,
                )
                render.success(f"Progress saved. Resume with: undo merge {version_id}")
                return
            elif action == "x":
                if typer.confirm("Discard this merge? The file is not touched.", default=False):
                    return

    @app.command("merge-drafts")
    def merge_drafts(
        ctx: typer.Context,
        discard: str | None = typer.Option(
            None, "--discard", help="Delete the saved progress of this file"
        ),
        json_out: bool = typer.Option(False, "--json"),
    ) -> None:
        """List unfinished merges saved with "save progress" (resume with `undo merge VERSION`)."""
        if discard:
            call(ctx, "delete_merge_draft", path=_abs(discard))
            render.success(f"Discarded the unfinished merge of {_abs(discard)}")
            return
        drafts = call(ctx, "list_merge_drafts")
        if json_out:
            render.print_json(drafts)
            return
        if not drafts:
            render.console.print("No unfinished merges.")
            return
        t = Table(title="Unfinished merges")
        for col in ("File", "Version", "Saved", "Resume with"):
            t.add_column(col)
        for d in drafts:
            t.add_row(
                d["path"],
                str(d["version_id"]),
                render.when(d.get("updated_at")),
                f"undo merge {d['version_id']}",
            )
        render.console.print(t)

    @app.command("diff-file")
    def diff_file(
        ctx: typer.Context,
        version_id: int = typer.Argument(..., help="Stored version id (from `undo versions PATH`)"),
        path: str | None = typer.Argument(
            None, help="File on disk to compare with (default: the file's current location)"
        ),
        unified: bool = typer.Option(False, "--unified", "-u", help="Unified diff instead"),
        json_out: bool = typer.Option(False, "--json"),
    ) -> None:
        """Compare a stored version with the file on disk: what restoring it would change.

        Left is the file now, right is the version. Only files inside tracked folders can be
        compared.
        """
        d = call(
            ctx,
            "diff_version_with_file",
            version_id=version_id,
            path=_abs(path) if path else None,
        )
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
