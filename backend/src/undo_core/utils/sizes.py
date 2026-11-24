"""Human readable size parsing/formatting."""

from __future__ import annotations

import re

from undo_core.utils.errors import InvalidInputError

_UNITS = {
    "": 1,
    "b": 1,
    "k": 1024,
    "kb": 1024,
    "kib": 1024,
    "m": 1024**2,
    "mb": 1024**2,
    "mib": 1024**2,
    "g": 1024**3,
    "gb": 1024**3,
    "gib": 1024**3,
    "t": 1024**4,
    "tb": 1024**4,
    "tib": 1024**4,
}
_SIZE_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*([a-zA-Z]*)\s*$")


def parse_size(text: str | int) -> int:
    if isinstance(text, int):
        return text
    match = _SIZE_RE.match(str(text))
    if not match:
        raise InvalidInputError(f"Invalid size {text!r}; use e.g. 500MB, 2GiB, 1048576")
    number, unit = match.groups()
    factor = _UNITS.get(unit.lower())
    if factor is None:
        raise InvalidInputError(f"Unknown size unit {unit!r}")
    return int(float(number) * factor)


def format_size(num: int | float | None) -> str:
    if num is None:
        return "-"
    value = float(num)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if abs(value) < 1024 or unit == "TiB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} TiB"
