"""Rich rendering helpers. All inputs are the JSON dicts returned by the backend."""

from __future__ import annotations

import json
import sys
from datetime import datetime
from typing import Any

from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from undo_core.utils.sizes import format_size


def _tolerant_streams() -> None:
    """Never crash on a character the console cannot encode (spinners, box lines, "·").

    A legacy Windows console or a pipe may use a code page such as cp1252; those characters
    then print as "?" instead of raising UnicodeEncodeError after the work is already done.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(errors="replace")
            except (ValueError, OSError):
                pass


_tolerant_streams()
console = Console()
err_console = Console(stderr=True)

OP_STYLE = {
    "CREATE": "green",
    "MODIFY": "cyan",
    "DELETE": "red",
    "RENAME": "magenta",
    "MOVE": "magenta",
}
ACTION_STYLE = {
    "create": "green",
    "overwrite": "yellow",
    "identical": "dim",
    "conflict": "bold red",
    "error": "bold red",
}


def print_json(data: Any) -> None:
    console.print_json(json.dumps(data, default=str))


def size(n: int | None) -> str:
    return format_size(n)


def when(value: str | None, *, seconds: bool = True) -> str:
    if not value:
        return "-"
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return value
    local = dt.astimezone() if dt.tzinfo else dt
    return local.strftime("%Y-%m-%d %H:%M:%S" if seconds else "%Y-%m-%d %H:%M")


def short_hash(h: str | None) -> str:
    return h[:12] if h else "-"


def op_text(op: str | None) -> Text:
    return Text(op or "-", style=OP_STYLE.get(op or "", ""))


def error(message: str, hint: str | None = None) -> None:
    body = Text(message, style="bold")
    if hint:
        body.append(f"\n{hint}", style="dim")
    err_console.print(Panel(body, title="error", border_style="red", expand=False))


def success(message: str) -> None:
    console.print(f"[green]OK[/green] {message}")


def warn(message: str) -> None:
    console.print(f"[yellow]![/yellow] {message}")


def kv_panel(title: str, rows: list[tuple[str, Any]], style: str = "blue") -> Panel:
    table = Table.grid(padding=(0, 2))
    table.add_column(style="bold")
    table.add_column()
    for k, v in rows:
        table.add_row(k, v if isinstance(v, Text) else str(v))
    return Panel(table, title=title, border_style=style, expand=False)


# --------------------------------------------------------------------------- domain renderers
def roots_table(roots: list[dict[str, Any]]) -> Table:
    t = Table(box=box.SIMPLE_HEAD, title="Tracked roots")
    for col in ("ID", "Path", "State", "Files", "Deleted", "Versions", "Last scan", "Monitor"):
        t.add_column(
            col, justify="right" if col in ("ID", "Files", "Deleted", "Versions") else "left"
        )
    for r in roots:
        t.add_row(
            str(r["id"]),
            r["path"],
            Text("enabled", style="green") if r["enabled"] else Text("disabled", style="yellow"),
            str(r["file_count"]),
            str(r["deleted_file_count"]),
            str(r["version_count"]),
            when(r.get("last_scan_at")),
            r.get("watch_mode") or "-",
        )
    return t


def scan_report(rep: dict[str, Any]) -> Panel:
    rows = [
        ("root", rep["root_path"] + (f"/{rep['prefix']}" if rep.get("prefix") else "")),
        ("scanned", rep["scanned"]),
        ("new", Text(str(rep["new"]), style="green")),
        ("modified", Text(str(rep["modified"]), style="cyan")),
        ("deleted", Text(str(rep["deleted"]), style="red")),
        ("renamed/moved", rep["renamed"]),
        ("deduplicated", rep["deduplicated"]),
        ("unchanged", rep["unchanged"]),
        ("skipped", rep["skipped"]),
        ("failed", Text(str(rep["failed"]), style="red" if rep["failed"] else "")),
        ("new data stored", size(rep["stored_bytes"])),
        ("duration", f"{rep['duration_seconds']}s"),
    ]
    if rep.get("skip_reasons"):
        rows.append(
            ("skip reasons", ", ".join(f"{k}={v}" for k, v in sorted(rep["skip_reasons"].items())))
        )
    for e in rep.get("errors", [])[:10]:
        rows.append(("error", Text(e, style="red")))
    return kv_panel(
        "Scan" + (" (deep)" if rep.get("deep") else ""),
        rows,
        "green" if not rep["errors"] else "yellow",
    )


def versions_table(versions: list[dict[str, Any]], title: str = "Versions") -> Table:
    t = Table(box=box.SIMPLE_HEAD, title=title)
    t.add_column("Version", justify="right")
    t.add_column("Time")
    t.add_column("Operation")
    t.add_column("Size", justify="right")
    t.add_column("Hash")
    t.add_column("Path")
    for v in versions:
        extra = ""
        if v["metadata"].get("from_path"):
            extra = f"  (from {v['metadata']['from_path']})"
        t.add_row(
            str(v["id"]),
            when(v["timestamp"]),
            op_text(v["operation"]),
            size(v["file_size"]) if v["blob_hash"] else "-",
            short_hash(v["blob_hash"]),
            v["relative_path"] + extra,
        )
    return t


def activity_table(versions: list[dict[str, Any]]) -> Table:
    t = Table(box=box.SIMPLE_HEAD, title="Recent activity")
    for col in ("Time", "Operation", "Version", "Size", "Path"):
        t.add_column(col, justify="right" if col in ("Version", "Size") else "left")
    for v in versions:
        t.add_row(
            when(v["timestamp"]),
            op_text(v["operation"]),
            str(v["id"]),
            size(v["file_size"]) if v["blob_hash"] else "-",
            v["absolute_path"],
        )
    return t


def files_table(files: list[dict[str, Any]], title: str = "Files") -> Table:
    t = Table(box=box.SIMPLE_HEAD, title=title)
    for col in ("ID", "Path", "Size", "Modified", "Versions", "Latest", "State"):
        t.add_column(col, justify="right" if col in ("ID", "Size", "Versions") else "left")
    for f in files:
        state = (
            Text("deleted " + when(f.get("deleted_at"), seconds=False), style="red")
            if f["is_deleted"]
            else Text("live", style="green")
        )
        t.add_row(
            str(f["id"]),
            f["absolute_path"],
            size(f.get("size")),
            when(f.get("last_modified")),
            str(f["version_count"]),
            op_text(f.get("latest_operation")),
            state,
        )
    return t


def restore_result(res: dict[str, Any]) -> None:
    t = Table(box=box.SIMPLE_HEAD, title="Restore plan" if res["dry_run"] else "Restore result")
    for col in ("Action", "Destination", "Version", "Size", "Detail"):
        t.add_column(col)
    for item in res["items"]:
        t.add_row(
            Text(item["action"], style=ACTION_STYLE.get(item["action"], "")),
            item["destination"],
            str(item.get("version_id") or "-"),
            size(item["size"]),
            item.get("detail") or "",
        )
    console.print(t)
    summary = (
        f"created {res['created']}, overwritten {res['overwritten']}, identical {res['identical']}, "
        f"conflicts {res['conflicts']}, errors {res['errors']}"
    )
    style = "green" if not res["conflicts"] and not res["errors"] else "yellow"
    console.print(Text(("Dry run: would have " if res["dry_run"] else "") + summary, style=style))
    if res.get("pre_restore_versions"):
        console.print(
            f"[dim]Previous contents preserved as versions {', '.join(map(str, res['pre_restore_versions']))}[/dim]"
        )
    if not res["dry_run"] and (res.get("metadata_restored") or res.get("metadata_not_restored")):
        console.print(
            f"[dim]Metadata restored: {', '.join(res['metadata_restored']) or 'none'}[/dim]"
        )
        console.print(
            f"[dim]Not restored: {', '.join(res['metadata_not_restored']) or 'none'}[/dim]"
        )
    if res["conflicts"]:
        console.print(
            "[yellow]Conflicting destinations were left untouched. Use --overwrite or --to DIR.[/yellow]"
        )


def snapshots_table(snaps: list[dict[str, Any]]) -> Table:
    t = Table(box=box.SIMPLE_HEAD, title="Snapshots")
    for col in ("ID", "Name", "Created", "Root", "Files", "Size", "Description"):
        t.add_column(col, justify="right" if col in ("ID", "Files", "Size") else "left")
    for s in snaps:
        t.add_row(
            str(s["id"]),
            s["name"],
            when(s["created_at"]),
            s["root_path"],
            str(s["file_count"]),
            size(s["total_size"]),
            s.get("description") or "",
        )
    return t


def storage_stats(st: dict[str, Any]) -> Panel:
    logical = st["logical_bytes"] or 0
    ratio = f" ({(st['total_savings_bytes'] / logical * 100):.1f}% saved)" if logical else ""
    rows = [
        ("data directory", st["data_dir"]),
        (
            "roots / files / deleted",
            f"{st['root_count']} / {st['file_count']} / {st['deleted_file_count']}",
        ),
        ("versions / snapshots", f"{st['version_count']} / {st['snapshot_count']}"),
        ("blobs / chunks", f"{st['blob_count']} / {st['chunk_count']}"),
        ("original data (all versions)", size(logical)),
        ("unique content", size(st["unique_bytes"])),
        ("stored (compressed)", size(st["stored_bytes"]) + ratio),
        ("blob files on disk", size(st["blob_disk_bytes"])),
        ("database", size(st["database_bytes"])),
        ("deduplication savings", Text(size(st["dedup_savings_bytes"]), style="green")),
        ("compression savings", Text(size(st["compression_savings_bytes"]), style="green")),
        (
            "compression",
            ", ".join(f"{k}: {v}" for k, v in st["compression_algorithms"].items()) or "-",
        ),
        (
            "unhealthy blobs",
            Text(str(st["unhealthy_blobs"]), style="red" if st["unhealthy_blobs"] else "green"),
        ),
        ("skipped files", st["skipped_files"]),
        (
            "last verify",
            f"{when(st.get('last_verify_at'))} ({'ok' if st.get('last_verify_ok') else 'problems' if st.get('last_verify_ok') is False else 'never'})",
        ),
        ("last gc", when(st.get("last_gc_at"))),
        ("last retention", when(st.get("last_retention_at"))),
    ]
    return kv_panel("Storage", rows)


# --------------------------------------------------------------------------- diffs
DIFF_DEL = "on #3b1219"
DIFF_DEL_STRONG = "bold on #8a2433"
DIFF_ADD = "on #12321d"
DIFF_ADD_STRONG = "bold on #1f7a3f"
DIFF_EMPTY = "on grey11"


def _diff_cell(text: str | None, kind: str, side: str, spans: list[Any]) -> Text:
    if text is None:
        return Text("", style=DIFF_EMPTY)
    base, strong = (DIFF_DEL, DIFF_DEL_STRONG) if side == "a" else (DIFF_ADD, DIFF_ADD_STRONG)
    line = Text(text)
    if kind == "equal":
        pass
    elif kind == "change":
        line.stylize(base)
        for start, end in spans:
            line.stylize(strong, start, end)
    else:  # delete (left) or insert (right)
        line.stylize(base)
    line.expand_tabs(4)
    return line


def _diff_no(n: int | None, kind: str, side: str) -> Text:
    if n is None:
        return Text("", style=DIFF_EMPTY)
    style = "dim"
    if kind != "equal":
        style = "red" if side == "a" else "green"
    return Text(str(n), style=style)


def side_by_side_diff(d: dict[str, Any]) -> Table:
    """The comparison as two columns, old on the left and new on the right (like an editor)."""
    a, b = d["a"], d["b"]
    t = Table(box=box.SIMPLE_HEAD, expand=True, show_edge=False, pad_edge=False, padding=(0, 1))
    t.add_column("", justify="right", style="dim", no_wrap=True, width=5)
    t.add_column(
        f"v{a['id']}  {a['relative_path']}  ({when(a['timestamp'])})",
        ratio=1,
        overflow="fold",
        header_style="bold red",
    )
    t.add_column("", justify="right", style="dim", no_wrap=True, width=5)
    t.add_column(
        f"v{b['id']}  {b['relative_path']}  ({when(b['timestamp'])})",
        ratio=1,
        overflow="fold",
        header_style="bold green",
    )
    for i, hunk in enumerate(d.get("hunks") or []):
        if i:
            t.add_section()
        header = f"@@ -{hunk['a_start']},{hunk['a_count']} +{hunk['b_start']},{hunk['b_count']} @@"
        t.add_row("", Text(header, style="cyan"), "", Text(header, style="cyan"))
        for row in hunk["rows"]:
            kind = row["kind"]
            t.add_row(
                _diff_no(row.get("a_no"), kind, "a"),
                _diff_cell(row.get("a_text"), kind, "a", row.get("a_spans") or []),
                _diff_no(row.get("b_no"), kind, "b"),
                _diff_cell(row.get("b_text"), kind, "b", row.get("b_spans") or []),
            )
    return t


def diff_summary(d: dict[str, Any]) -> Text:
    out = Text()
    out.append(f"+{d.get('added', 0)}", style="green")
    out.append(" ")
    out.append(f"-{d.get('removed', 0)}", style="red")
    out.append(f" lines · size change {d['size_delta']:+d} bytes", style="dim")
    if d.get("truncated"):
        out.append(" · diff truncated", style="yellow")
    if d.get("note"):
        out.append(f" · {d['note']}", style="dim")
    return out


def forget_result(r: dict[str, Any]) -> Panel:
    rows: list[tuple[str, Any]] = [
        ("target", r["target"]),
        ("versions removed" if not r["dry_run"] else "versions to remove", r["versions_removed"]),
        ("files affected", r["files_affected"]),
    ]
    if r.get("before"):
        rows.append(("older than", when(r["before"])))
    if r.get("files_removed"):
        rows.append(("files with no history left", r["files_removed"]))
    if r.get("versions_kept_in_snapshots"):
        rows.append(("kept (in a snapshot)", r["versions_kept_in_snapshots"]))
    if r.get("note"):
        rows.append(("note", r["note"]))
    title = "Forget (dry run)" if r["dry_run"] else "Forget"
    return kv_panel(title, rows, style="yellow" if r["dry_run"] else "red")
