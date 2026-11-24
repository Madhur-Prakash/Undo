"""Version comparison (unified text diff for text content)."""

from __future__ import annotations

import codecs
import difflib

MAX_DIFF_BYTES = 2 * 1024 * 1024
MAX_DIFF_LINES = 5000
TEXT_SAMPLE = 8192


def is_probably_text(sample: bytes) -> bool:
    if not sample:
        return True
    if b"\x00" in sample:
        return False
    decoder = codecs.getincrementaldecoder("utf-8")()
    try:
        decoder.decode(sample, final=False)
        return True
    except UnicodeDecodeError:
        pass
    # Latin-1 style text: mostly printable bytes
    printable = sum(1 for b in sample if b in (9, 10, 13) or 32 <= b < 127 or b >= 160)
    return printable / len(sample) > 0.95


def decode_text(data: bytes) -> str:
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("latin-1")


def unified_diff(
    a: bytes, b: bytes, a_label: str, b_label: str, *, max_lines: int = MAX_DIFF_LINES
) -> tuple[str, bool]:
    lines = list(
        difflib.unified_diff(
            decode_text(a).splitlines(keepends=True),
            decode_text(b).splitlines(keepends=True),
            fromfile=a_label,
            tofile=b_label,
        )
    )
    truncated = len(lines) > max_lines
    if truncated:
        lines = lines[:max_lines]
    text = "".join(line if line.endswith("\n") else line + "\n" for line in lines)
    return text, truncated
