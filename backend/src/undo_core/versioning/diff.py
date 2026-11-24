"""Version comparison for text content.

Two views of the same comparison:

* :func:`side_by_side` - hunks of paired rows (old line | new line), with the changed characters
  inside a modified line marked, like a side-by-side git diff in an editor. The GUI, the CLI
  and the TUI render this.
* :func:`unified_diff` - classic ``diff -u`` text, for scripts and ``--unified``.

Lines are compared **without their line endings**: a file whose only change is CRLF -> LF shows
no line changes, and :func:`line_ending_note` says what happened instead.
"""

from __future__ import annotations

import codecs
import difflib
from dataclasses import dataclass, field

MAX_DIFF_BYTES = 2 * 1024 * 1024
MAX_DIFF_LINES = 5000
MAX_DIFF_ROWS = 5000
CONTEXT_LINES = 3
INTRALINE_MAX = 2000  # longer lines are marked as changed as a whole
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


def split_lines(text: str) -> list[str]:
    """Lines without their endings (CRLF, LF and CR are all line breaks)."""
    return text.splitlines()


def line_ending_style(data: bytes) -> str:
    crlf = data.count(b"\r\n")
    lf = data.count(b"\n") - crlf
    if crlf and lf:
        return "mixed"
    if crlf:
        return "CRLF"
    if lf:
        return "LF"
    return "none"


def line_ending_note(a: bytes, b: bytes) -> str | None:
    """A note when the line-ending style changed (the diff itself ignores line endings)."""
    sa, sb = line_ending_style(a), line_ending_style(b)
    if sa != sb and "none" not in (sa, sb):
        return f"line endings changed: {sa} -> {sb}"
    return None


def unified_diff(
    a: bytes, b: bytes, a_label: str, b_label: str, *, max_lines: int = MAX_DIFF_LINES
) -> tuple[str, bool]:
    lines = list(
        difflib.unified_diff(
            split_lines(decode_text(a)),
            split_lines(decode_text(b)),
            fromfile=a_label,
            tofile=b_label,
            lineterm="",
        )
    )
    truncated = len(lines) > max_lines
    if truncated:
        lines = lines[:max_lines]
    return "".join(line + "\n" for line in lines), truncated


# --------------------------------------------------------------------------- side by side
@dataclass
class Row:
    kind: str  # equal | delete | insert | change
    a_no: int | None = None
    a_text: str | None = None
    b_no: int | None = None
    b_text: str | None = None
    # Character ranges [start, end) that differ inside a changed line, per side.
    a_spans: list[tuple[int, int]] = field(default_factory=list)
    b_spans: list[tuple[int, int]] = field(default_factory=list)


@dataclass
class Hunk:
    a_start: int
    a_count: int
    b_start: int
    b_count: int
    rows: list[Row]


@dataclass
class SideBySide:
    hunks: list[Hunk]
    added: int
    removed: int
    truncated: bool


def _intraline(a: str, b: str) -> tuple[list[tuple[int, int]], list[tuple[int, int]]]:
    if len(a) > INTRALINE_MAX or len(b) > INTRALINE_MAX:
        return [(0, len(a))] if a else [], [(0, len(b))] if b else []
    a_spans: list[tuple[int, int]] = []
    b_spans: list[tuple[int, int]] = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if tag == "equal":
            continue
        if i2 > i1:
            a_spans.append((i1, i2))
        if j2 > j1:
            b_spans.append((j1, j2))
    return a_spans, b_spans


def side_by_side(
    a: bytes,
    b: bytes,
    *,
    context: int = CONTEXT_LINES,
    max_rows: int = MAX_DIFF_ROWS,
) -> SideBySide:
    a_lines = split_lines(decode_text(a))
    b_lines = split_lines(decode_text(b))
    matcher = difflib.SequenceMatcher(None, a_lines, b_lines, autojunk=False)
    hunks: list[Hunk] = []
    added = removed = rows_total = 0
    truncated = False
    for group in matcher.get_grouped_opcodes(context):
        rows: list[Row] = []
        for tag, i1, i2, j1, j2 in group:
            if tag == "equal":
                for k in range(i2 - i1):
                    rows.append(
                        Row("equal", i1 + k + 1, a_lines[i1 + k], j1 + k + 1, b_lines[j1 + k])
                    )
                continue
            removed += i2 - i1
            added += j2 - j1
            if tag == "delete":
                rows += [Row("delete", i + 1, a_lines[i]) for i in range(i1, i2)]
            elif tag == "insert":
                rows += [Row("insert", b_no=j + 1, b_text=b_lines[j]) for j in range(j1, j2)]
            else:  # replace: pair the lines; any extra lines are plain deletes or inserts
                for k in range(max(i2 - i1, j2 - j1)):
                    i, j = i1 + k, j1 + k
                    if i < i2 and j < j2:
                        a_spans, b_spans = _intraline(a_lines[i], b_lines[j])
                        rows.append(
                            Row("change", i + 1, a_lines[i], j + 1, b_lines[j], a_spans, b_spans)
                        )
                    elif i < i2:
                        rows.append(Row("delete", i + 1, a_lines[i]))
                    else:
                        rows.append(Row("insert", b_no=j + 1, b_text=b_lines[j]))
        first, last = group[0], group[-1]
        hunks.append(
            Hunk(
                a_start=first[1] + 1,
                a_count=last[2] - first[1],
                b_start=first[3] + 1,
                b_count=last[4] - first[3],
                rows=rows,
            )
        )
        rows_total += len(rows)
        if rows_total >= max_rows:
            truncated = True
            break
    return SideBySide(hunks=hunks, added=added, removed=removed, truncated=truncated)
