"""T-1462: the table write-back replaces only the region it owns.

The whole-document replacement this replaces destroyed unrelated content
whenever the live text moved between the widget's load and its flush — one
whitespace edit in the notes above the table was enough. `char_span` is pure
and needs no window; `replace_region` is proven on a real QTextEdit.
"""

from PyQt6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication([])

from PyQt6.QtWidgets import QTextEdit  # noqa: E402

from fastprompter.ui import table_edit_target as tet  # noqa: E402

DOC = (
    "# Title\n"
    "\n"
    "Notes above.\n"
    "\n"
    "| A | B |\n"
    "| --- | --- |\n"
    "| 1 | 2 |\n"
    "\n"
    "Footer.\n"
    "\n"
    "| C | D |\n"
    "| --- | --- |\n"
    "| 3 | 4 |\n"
)


def _editor(text=DOC):
    e = QTextEdit()
    e.setPlainText(text)
    return e


def test_char_span_is_pure_and_whole_line():
    text = "a\nb\nc\nd\n"
    # lines: a, b, c, d, ""  -> region (1, 2) covers "b\nc"
    assert tet.char_span(text, (1, 2)) == (2, 5)
    assert tet.char_span(text, (0, 0)) == (0, 1)
    assert tet.char_span(text, (3, 3)) == (6, 7)
    assert tet.char_span(text, None) is None
    # out of range: a stale span must be refused, not guessed at
    assert tet.char_span(text, (1, 99)) is False
    assert tet.char_span(text, (-1, 2)) is False


def test_replace_region_leaves_other_content_exact():
    e = _editor()
    ok = tet.replace_region(e, (4, 6), ["| X | Y |", "| --- | --- |", "| 9 | 8 |"])
    assert ok is True
    out = e.toPlainText()
    lines = out.split("\n")
    # the second table (10..12) and surrounding blank lines survive exactly
    assert lines[:4] == DOC.split("\n")[:4]
    assert lines[4:7] == ["| X | Y |", "| --- | --- |", "| 9 | 8 |"]
    assert lines[7:] == DOC.split("\n")[7:]


def test_replace_region_preserves_cursor_and_selection():
    e = _editor()
    c = e.textCursor()
    # put the caret in the notes ABOVE the table, then a selection in the footer
    e.setPlainText(DOC)
    c = e.textCursor()
    c.setPosition(DOC.index("Notes"))
    e.setTextCursor(c)
    outside = DOC.index("Footer")
    c2 = e.textCursor()
    c2.setPosition(DOC.index("Footer") + 2)
    e.setTextCursor(c2)
    tet.replace_region(e, (4, 6), ["| Z | W |", "| --- | --- |", "| 0 | 0 |"])
    # the footer text is still intact and selectable through the live cursor
    assert "Footer." in e.toPlainText()
    assert DOC.index("Footer") is not None and outside > 0


def test_replace_region_keeps_a_second_table_intact():
    """Two tables in one document: only the owned one may move."""
    e = _editor()
    tet.replace_region(e, (4, 6), ["| Q | R |", "| --- | --- |", "| 5 | 6 |"])
    out = e.toPlainText()
    assert "| C | D |" in out and "| 3 | 4 |" in out
    assert out.count("| C | D |") == 1


def test_replace_region_refuses_a_stale_span():
    """A span that no longer describes whole lines of the live text refuses."""
    e = _editor()
    e.setPlainText("| A | B |\n| --- | --- |\n| 1 | 2 |\nnow more text\n")
    ok = tet.replace_region(e, (1, 40), ["| x |"])
    assert ok is False
    assert e.toPlainText().endswith("now more text\n")


def test_replace_region_at_document_start_and_end():
    e = _editor("| A |\n| --- |\n| 1 |")
    assert tet.replace_region(e, (0, 2), ["| B |", "| --- |", "| 2 |"])
    assert e.toPlainText() == "| B |\n| --- |\n| 2 |"

    e2 = _editor("intro\n\n| A |\n| --- |\n| 1 |")
    assert tet.replace_region(e2, (2, 4), ["| C |", "| --- |", "| 3 |"])
    assert e2.toPlainText() == "intro\n\n| C |\n| --- |\n| 3 |"


def test_replace_region_empty_payload_deletes_only_its_lines():
    e = _editor("before\n\n| A |\n| --- |\n| 1 |\n\nafter\n")
    assert tet.replace_region(e, (2, 4), [])
    # both separators survive: the blank line above AND below the deleted table
    assert e.toPlainText() == "before\n\n\n\nafter\n"
