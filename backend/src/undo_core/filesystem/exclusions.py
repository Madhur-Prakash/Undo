"""Exclusion rules.

Pattern syntax (matching is case-insensitive on Windows/macOS):

* ``name/``      - any directory called ``name`` (glob allowed: ``build-*/``)
* ``*.ext``      - any file or directory whose name matches the glob
* ``a/b/c``      - a path relative to the root (glob allowed); also excludes
                   everything below it
* ``/abs/path``  - an absolute path (and everything below it)

Rules come from three sources, all inspectable with ``undo exclude list``:
``builtin`` (non-removable, Undo's own temp files), ``default`` (the
``exclusions.defaults`` setting) and ``user`` (stored in the database).
Undo's own data directory is always excluded so it is never monitored
recursively.
"""

from __future__ import annotations

import fnmatch
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path

from undo_core.platform.paths import CASE_INSENSITIVE, IS_WINDOWS, is_within

FILE_ATTRIBUTE_HIDDEN = 0x2


class SkipReason:
    EXCLUDED = "excluded"
    UNDO_STORAGE = "undo_storage"
    HIDDEN = "hidden"
    TOO_LARGE = "too_large"
    PERMISSION_DENIED = "permission_denied"
    SYMLINK = "symlink_not_followed"
    SPECIAL = "special_file"
    UNAVAILABLE = "temporarily_unavailable"
    FAILED = "capture_failed"


@dataclass(frozen=True)
class ExclusionRule:
    pattern: str
    source: str  # builtin | default | user
    root_id: int | None = None
    id: int | None = None


def _fold(text: str) -> str:
    return text.casefold() if CASE_INSENSITIVE else text


@dataclass(frozen=True)
class _Compiled:
    rule: ExclusionRule
    kind: str  # dir | name | path | abs
    regex: re.Pattern[str] | None
    abs_path: str | None


def _compile(rule: ExclusionRule) -> _Compiled:
    pat = rule.pattern.strip().replace("\\", "/")
    if os.path.isabs(rule.pattern.strip()) or (IS_WINDOWS and re.match(r"^[A-Za-z]:/", pat)):
        return _Compiled(rule, "abs", None, os.path.normpath(rule.pattern.strip()))
    if pat.endswith("/"):
        return _Compiled(rule, "dir", re.compile(fnmatch.translate(_fold(pat.rstrip("/")))), None)
    if "/" in pat:
        return _Compiled(rule, "path", re.compile(fnmatch.translate(_fold(pat.strip("/")))), None)
    return _Compiled(rule, "name", re.compile(fnmatch.translate(_fold(pat))), None)


class ExclusionMatcher:
    def __init__(
        self,
        rules: list[ExclusionRule],
        *,
        root_path: Path,
        protected_dirs: list[Path],
        exclude_hidden: bool = False,
    ) -> None:
        self.rules = rules
        self.root_path = root_path
        self.protected_dirs = protected_dirs
        self.exclude_hidden = exclude_hidden
        self._compiled = [_compile(r) for r in rules]

    def _abs(self, rel: str) -> Path:
        return self.root_path / Path(*rel.split("/")) if rel else self.root_path

    def _protected(self, rel: str) -> bool:
        absolute = self._abs(rel)
        return any(is_within(absolute, p) for p in self.protected_dirs)

    def _match_component(self, name: str, *, is_dir: bool) -> ExclusionRule | None:
        folded = _fold(name)
        for c in self._compiled:
            if c.regex is None:
                continue
            if (c.kind == "dir" and is_dir) or c.kind == "name":
                if c.regex.match(folded):
                    return c.rule
        return None

    def _match_path(self, rel: str) -> ExclusionRule | None:
        folded = _fold(rel)
        absolute = None
        for c in self._compiled:
            if c.kind == "path" and c.regex is not None:
                parts = folded.split("/")
                for i in range(1, len(parts) + 1):
                    if c.regex.match("/".join(parts[:i])):
                        return c.rule
            elif c.kind == "abs" and c.abs_path is not None:
                absolute = absolute or self._abs(rel)
                if is_within(absolute, c.abs_path):
                    return c.rule
        return None

    def check(self, rel: str, *, is_dir: bool, st: os.stat_result | None = None) -> str | None:
        """Return a skip reason (``excluded:<pattern>``, ``undo_storage``, ``hidden``) or None.

        Ancestor directories are checked too, so a file event deep inside an
        excluded directory is rejected without a filesystem walk.
        """
        if not rel:
            return None
        if self._protected(rel):
            return SkipReason.UNDO_STORAGE
        parts = rel.split("/")
        for i, part in enumerate(parts):
            last = i == len(parts) - 1
            component_is_dir = is_dir if last else True
            rule = self._match_component(part, is_dir=component_is_dir)
            if rule is not None:
                return f"{SkipReason.EXCLUDED}:{rule.pattern}"
            if self.exclude_hidden and part.startswith("."):
                return SkipReason.HIDDEN
        rule = self._match_path(rel)
        if rule is not None:
            return f"{SkipReason.EXCLUDED}:{rule.pattern}"
        if self.exclude_hidden and st is not None and IS_WINDOWS:
            attrs = getattr(st, "st_file_attributes", 0)
            if attrs & FILE_ATTRIBUTE_HIDDEN:
                return SkipReason.HIDDEN
        return None


def is_regular(st: os.stat_result) -> bool:
    return stat.S_ISREG(st.st_mode)
