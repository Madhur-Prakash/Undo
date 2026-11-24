from __future__ import annotations

import os
from pathlib import Path

import pytest
from undo_core.config.settings import Settings, SettingsStore
from undo_core.filesystem.exclusions import ExclusionMatcher, ExclusionRule
from undo_core.platform.paths import (
    CASE_INSENSITIVE,
    is_within,
    path_key,
    safe_join,
    to_relative,
    validate_relative,
)
from undo_core.utils.errors import InvalidInputError, PathOutsideRootError, UnsafePathError
from undo_core.utils.sizes import format_size, parse_size
from undo_core.utils.timeutil import parse_timestamp, utcnow


def test_to_relative_and_containment(tmp_path: Path) -> None:
    root = tmp_path / "root"
    assert to_relative(root, root / "a" / "b.txt") == "a/b.txt"
    assert to_relative(root, root) == ""
    with pytest.raises(PathOutsideRootError):
        to_relative(root, tmp_path / "rootless" / "x")  # prefix but not inside
    with pytest.raises(PathOutsideRootError):
        to_relative(root, root / ".." / "escape.txt")
    assert is_within(root / "x", root)
    assert not is_within(tmp_path / "root2", root)


@pytest.mark.parametrize("bad", ["", "/etc/passwd", "../x", "a/../../b", "a//b", "./a", "a/./b"])
def test_validate_relative_rejects_traversal(bad: str) -> None:
    with pytest.raises(UnsafePathError):
        validate_relative(bad)


def test_safe_join_stays_inside(tmp_path: Path) -> None:
    assert safe_join(tmp_path, "a/b.txt") == tmp_path / "a" / "b.txt"
    with pytest.raises(UnsafePathError):
        safe_join(tmp_path, "../outside")


def test_path_key_case_rules() -> None:
    if CASE_INSENSITIVE:
        assert path_key("Docs/A.TXT") == path_key("docs/a.txt")
    else:
        assert path_key("Docs/A.TXT") != path_key("docs/a.txt")


def _matcher(tmp_path: Path, patterns: list[str], hidden: bool = False) -> ExclusionMatcher:
    return ExclusionMatcher(
        [ExclusionRule(p, "user") for p in patterns],
        root_path=tmp_path,
        protected_dirs=[tmp_path / "undo-data"],
        exclude_hidden=hidden,
    )


def test_exclusion_pattern_kinds(tmp_path: Path) -> None:
    m = _matcher(tmp_path, ["node_modules/", "*.log", "docs/drafts", str(tmp_path / "abs")])
    assert m.check("node_modules", is_dir=True)
    assert m.check("src/node_modules/pkg/index.js", is_dir=False)  # ancestor dir excluded
    assert m.check("node_modules", is_dir=False) is None  # a *file* named node_modules is kept
    assert m.check("app/debug.log", is_dir=False)
    assert m.check("docs/drafts/x.md", is_dir=False)
    assert m.check("docs/final/x.md", is_dir=False) is None
    assert m.check("abs/file.txt", is_dir=False)
    assert m.check("undo-data/blobs/x", is_dir=False) == "undo_storage"
    assert m.check("notes.txt", is_dir=False) is None


def test_hidden_files_only_excluded_when_configured(tmp_path: Path) -> None:
    assert _matcher(tmp_path, []).check(".config/x", is_dir=False) is None
    assert _matcher(tmp_path, [], hidden=True).check(".config/x", is_dir=False) == "hidden"


def test_settings_store_validation(tmp_path: Path) -> None:
    store = SettingsStore(tmp_path / "config.json")
    store.save(Settings())
    store.set_value("capture.max_file_size", "500MB")
    assert store.current.capture.max_file_size == 500 * 1024 * 1024
    store.set_value("compression.level", "7")
    assert SettingsStore(tmp_path / "config.json").current.compression.level == 7  # persisted
    store.set_value("retention.keep_last", "none")
    assert store.current.retention.keep_last is None
    with pytest.raises(InvalidInputError):
        store.set_value("compression.level", "99")
    with pytest.raises(InvalidInputError):
        store.set_value("api.host", "0.0.0.0")  # loopback only unless allow_remote
    with pytest.raises(InvalidInputError):
        store.set_value("nope.key", "1")
    store.set_value("exclusions.defaults", "a/,*.b")
    assert store.current.exclusions.defaults == ["a/", "*.b"]
    # A list the user edited is never refilled with removed defaults.
    assert SettingsStore(tmp_path / "config.json").current.exclusions.defaults == ["a/", "*.b"]


def test_upgrade_adds_new_default_exclusions_once(tmp_path: Path) -> None:
    import json

    from undo_core.config import defaults as d

    # A config saved by 1.0.0: no defaults_version, the user removed "*.tmp".
    added = {p for patterns in d.DEFAULT_EXCLUSIONS_ADDED.values() for p in patterns}
    old = [p for p in d.DEFAULT_EXCLUSIONS if p not in added]
    old.remove("*.tmp")
    (tmp_path / "config.json").write_text(json.dumps({"exclusions": {"defaults": old}}))
    current = SettingsStore(tmp_path / "config.json").current.exclusions
    assert current.defaults_version == d.DEFAULT_EXCLUSIONS_VERSION
    assert "*.whl" in current.defaults and "target/" in current.defaults
    assert "*.log" in current.defaults  # added by version 3
    assert "*.tmp" not in current.defaults  # removed by the user: stays removed
    assert len(current.defaults) == len(set(current.defaults))


def test_package_directories_and_wheels_are_excluded(tmp_path: Path) -> None:
    from undo_core.config import defaults as d
    from undo_core.filesystem.exclusions import ExclusionMatcher, ExclusionRule

    m = ExclusionMatcher(
        [ExclusionRule(p, "default") for p in d.DEFAULT_EXCLUSIONS],
        root_path=tmp_path,
        protected_dirs=[],
    )
    for rel in (
        "dist/undo-1.0.0-py3-none-any.whl",
        "app/.venv/Lib/site-packages/x.py",
        "venv/lib/python3.12/site-packages/pkg/__init__.py",
        "pkg.egg-info/PKG-INFO",
        "web/node_modules/react/index.js",
        "web/.pnpm-store/v3/files/00/abc",
        "crate/target/debug/app.exe",
        "home/.cargo/registry/cache/serde-1.0.0.crate",
    ):
        assert m.check(rel, is_dir=False), rel
    for rel in ("src/main.rs", "notes/report.docx", "web/package.json", "Cargo.toml"):
        assert m.check(rel, is_dir=False) is None, rel


def test_sizes_and_times() -> None:
    assert parse_size("1.5KiB") == 1536
    assert parse_size("2gb") == 2 * 1024**3
    assert format_size(2048) == "2.0 KiB"
    with pytest.raises(InvalidInputError):
        parse_size("lots")
    t = parse_timestamp("2h")
    assert 7100 < (utcnow() - t).total_seconds() < 7300
    assert parse_timestamp("2024-05-01T10:00:00+00:00").hour == 10
    with pytest.raises(InvalidInputError):
        parse_timestamp("yesterday-ish")


def test_token_file_permissions(tmp_path: Path) -> None:
    from undo_core.config.token import ensure_token

    p = tmp_path / "api_token"
    token = ensure_token(p)
    assert len(token) > 30 and ensure_token(p) == token
    if os.name != "nt":
        assert p.stat().st_mode & 0o077 == 0
