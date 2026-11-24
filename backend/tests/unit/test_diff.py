"""Side-by-side diff: pairing, intraline spans, line-ending handling."""

from __future__ import annotations

from undo_core.versioning.diff import line_ending_note, side_by_side, unified_diff


def test_rows_pair_changes_and_mark_characters() -> None:
    a = b"title\nkeep\nold value = 1\nremove me\nsame\n"
    b = b"title\nkeep\nnew value = 2\nsame\nadded\n"
    result = side_by_side(a, b)
    rows = [r for h in result.hunks for r in h.rows]
    kinds = [r.kind for r in rows]
    assert kinds == ["equal", "equal", "change", "delete", "equal", "insert"]
    change = rows[2]
    assert (change.a_no, change.b_no) == (3, 3)
    assert change.a_spans and change.b_spans
    assert change.a_text is not None and change.a_text[slice(*change.a_spans[0])] == "old"
    assert (result.added, result.removed) == (2, 2)


def test_line_endings_alone_are_not_a_change() -> None:
    lf, crlf = b"one\ntwo\n", b"one\r\ntwo\r\n"
    assert side_by_side(lf, crlf).hunks == []
    assert line_ending_note(lf, crlf) == "line endings changed: LF -> CRLF"
    text, _ = unified_diff(lf, crlf, "a", "b")
    assert text == ""


def test_context_limits_hunks() -> None:
    a = b"".join(f"line {i}\n".encode() for i in range(100))
    b = a.replace(b"line 50\n", b"LINE 50\n")
    (hunk,) = side_by_side(a, b).hunks
    assert len(hunk.rows) == 7  # 3 context + change + 3 context
    assert hunk.a_start == 48 and hunk.b_start == 48
