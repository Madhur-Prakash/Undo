"""CLI commands in local mode (no daemon), including JSON output and exit codes."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from helpers import write
from typer.testing import CliRunner
from undo_cli.main import app

pytestmark = pytest.mark.integration


@pytest.fixture
def cli(tmp_path: Path):  # type: ignore[no-untyped-def]
    runner = CliRunner()
    data = tmp_path / "data"

    def invoke(*args: str, ok: bool = True):  # type: ignore[no-untyped-def]
        result = runner.invoke(app, ["--data-dir", str(data), *args])
        if ok:
            assert result.exit_code == 0, f"{args}: {result.output}"
        return result

    return invoke


def _json(result) -> object:  # type: ignore[no-untyped-def]
    return json.loads(result.output)


def test_full_cli_flow(cli, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    work = tmp_path / "work"
    write(work / "doc.txt", "v1")
    write(work / "sub" / "data.csv", "a,b")

    assert cli("status", ok=False).exit_code == 3  # not initialised
    cli("init")
    cli("settings", "set", "capture.stable_seconds", "0")
    tracked = _json(cli("track", str(work), "--json"))
    assert tracked["scan"]["new"] == 2  # type: ignore[index]

    write(work / "doc.txt", "v2")
    scan = _json(cli("scan", "--json"))
    assert scan[0]["modified"] == 1  # type: ignore[index]

    history = _json(cli("history", str(work / "doc.txt"), "--json"))
    versions = history["versions"]  # type: ignore[index]
    assert [v["operation"] for v in versions] == ["MODIFY", "CREATE"]
    first_id = versions[-1]["id"]

    conflict = cli("restore", str(work / "doc.txt"), "--version", str(first_id), ok=False)
    assert conflict.exit_code == 5
    restored = _json(
        cli(
            "restore",
            str(work / "doc.txt"),
            "--version",
            str(first_id),
            "--overwrite",
            "--yes",
            "--json",
        )
    )
    assert restored["overwritten"] == 1  # type: ignore[index]
    assert (work / "doc.txt").read_text() == "v1"

    (work / "sub" / "data.csv").unlink()
    cli("scan")
    deleted = _json(cli("recover", "--json"))
    assert deleted[0]["relative_path"] == "sub/data.csv"  # type: ignore[index]
    cli("recover", str(work / "sub" / "data.csv"))
    assert (work / "sub" / "data.csv").read_text() == "a,b"

    cli("snapshot", "create", "--name", "s1")
    snaps = _json(cli("snapshot", "list", "--json"))
    assert snaps[0]["name"] == "s1"  # type: ignore[index]
    write(work / "doc.txt", "v3")
    cli("snapshot", "create", "--name", "s2")
    diff = _json(cli("snapshot", "diff", "s1", "s2", "--json"))
    assert len(diff["modified"]) == 1  # type: ignore[index]
    cli("snapshot", "restore", "s1", "--to", str(tmp_path / "out"))
    assert (tmp_path / "out" / "doc.txt").read_text() == "v1"

    cli("exclude", "add", "*.tmp")
    patterns = [e["pattern"] for e in _json(cli("exclude", "list", "--json"))]  # type: ignore[union-attr]
    assert "*.tmp" in patterns
    cli("exclude", "remove", "*.tmp")

    log = _json(cli("log", "--json"))
    assert len(log) >= 5  # type: ignore[arg-type]
    hits = _json(cli("search", "data", "--json"))
    assert hits[0]["file"]["relative_path"] == "sub/data.csv"  # type: ignore[index]

    stats = _json(cli("storage", "stats", "--json"))
    assert stats["blob_count"] >= 3  # type: ignore[index]
    verify = _json(cli("storage", "verify", "--json"))
    assert verify["healthy"]  # type: ignore[index]
    gc = _json(cli("storage", "gc", "--dry-run", "--json"))
    assert gc["gc"]["dry_run"]  # type: ignore[index]

    settings = _json(cli("settings", "show", "compression", "--json"))
    assert settings["compression"]["level"] == 3  # type: ignore[index]
    assert cli("settings", "set", "compression.level", "99", ok=False).exit_code == 2
    doctor = _json(cli("doctor", "--json"))
    assert any(c["name"] == "database integrity" and c["ok"] for c in doctor)  # type: ignore[union-attr]
    roots = _json(cli("roots", "--json"))
    assert roots[0]["file_count"] == 2  # type: ignore[index]
    cli("untrack", str(work))
    assert not _json(cli("roots", "--json"))[0]["enabled"]  # type: ignore[index]
    assert "undo" in cli("--version").output


def test_cli_sorting(cli, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    work = tmp_path / "work"
    write(work / "b.txt", "xx")
    write(work / "a.txt", "xxxxxx")
    write(work / "c.txt", "x")
    cli("init")
    cli("settings", "set", "capture.stable_seconds", "0")
    cli("track", str(work))

    def names(*args: str) -> list[str]:
        page = _json(cli("files", *args, "--json"))
        return [f["name"] for f in page["items"]]  # type: ignore[index]

    assert names() == ["a.txt", "b.txt", "c.txt"]
    assert names("--reverse") == ["c.txt", "b.txt", "a.txt"]
    assert names("--sort", "size") == ["a.txt", "b.txt", "c.txt"]  # largest first
    assert names("--sort", "size", "-r") == ["c.txt", "b.txt", "a.txt"]
    assert cli("files", "--sort", "nope", ok=False).exit_code != 0

    log = _json(cli("log", "--sort", "path", "--json"))
    assert [v["relative_path"] for v in log] == ["a.txt", "b.txt", "c.txt"]  # type: ignore[union-attr,index]
    log = _json(cli("log", "--sort", "size", "--json"))
    assert log[0]["relative_path"] == "a.txt"  # type: ignore[index]

    cli("snapshot", "create", "--name", "zeta")
    cli("snapshot", "create", "--name", "alpha")
    snaps = _json(cli("snapshot", "list", "--sort", "name", "--json"))
    assert [s["name"] for s in snaps] == ["alpha", "zeta"]  # type: ignore[union-attr,index]
    snaps = _json(cli("snapshot", "list", "--json"))
    assert snaps[0]["name"] == "alpha"  # newest first  # type: ignore[index]
