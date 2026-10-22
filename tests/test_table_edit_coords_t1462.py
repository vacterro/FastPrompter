"""T-1462 Stage 1: the table write-back must speak Qt's coordinate system.

`char_span` computes whole-line offsets over the Python string returned by
`toPlainText()`, so its offsets are in PYTHON code points. `QTextCursor`
positions are UTF-16 code units. The two are equal only while the document is
BMP-only; one emoji anywhere in the document (before, inside or after the
table) makes every later Qt position one larger than the Python index, and a
raw `setPosition` then splices one character short — eating the table's leading
pipe or the newline that separates it from the prose.

These tests are INTEGRATION tests on a real `QTextEdit`, because the defect is
exactly at the boundary: `char_span` can be perfectly correct and the splice
still lands wrong. Each case asserts that every character outside the owned
region survives byte-for-byte.
"""

import pytest
from PyQt6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication([])

from PyQt6.QtWidgets import QTextEdit  # noqa: E402

from fastprompter.ui import table_edit_target as tet  # noqa: E402
from fastprompter.ui.qt_text_coords import py_to_qt, qt_units  # noqa: E402


def _editor(text):
    e = QTextEdit()
    e.setPlainText(text)
    return e


def _assert_only_region_changed(before, after, old_lines, new_lines):
    """The text before and after the owned whole-line region is untouched."""
    b = before.split("\n")
    a = after.split("\n")
    i = next(k for k, ln in enumerate(b) if ln == old_lines[0])
    # the replaced run starts at i and covers exactly len(old_lines) lines
    assert a[:i] == b[:i], "prefix changed"
    assert a[i:i + len(new_lines)] == new_lines, "region not written"
    assert a[i + len(new_lines):] == b[i + len(old_lines):], "suffix changed"


# --------------------------------------------------------------- the bridge

def test_char_span_is_python_codepoints_not_qt_units():
    """The contract that makes the conversion necessary: for text with an
    astral character the two systems differ by one per astral char."""
    text = "\U0001F600\n| A |\n| --- |\n| 1 |"
    assert qt_units(text) == len(text) + 1  # one astral char = two units
    start, end = tet.char_span(text, (1, 3))
    assert (start, end) == (2, len(text))  # python offsets, ends at text end


def test_py_to_qt_is_the_conversion_used():
    text = "\U0001F600x\n| A |"
    # index 3 in python ("|") is position 4 in Qt
    assert py_to_qt(text, 3) == 4
    assert qt_units(text) == len(text) + 1


# --------------------------------------------------------------- integration

def test_emoji_before_the_table_does_not_shift_the_splice():
    before = "\U0001F600 emoji above\n\n| A | B |\n| --- | --- |\n| 1 | 2 |\n\nfooter\n"
    e = _editor(before)
    assert tet.replace_region(
        e, (2, 4), ["| A | B |", "| --- | --- |", "| 9 | 8 |"]) is True
    out = e.toPlainText()
    _assert_only_region_changed(
        before, out,
        ["| A | B |", "| --- | --- |", "| 1 | 2 |"],
        ["| A | B |", "| --- | --- |", "| 9 | 8 |"])
    assert out.startswith("\U0001F600 emoji above\n\n")
    assert out.endswith("\n\nfooter\n")


def test_emoji_inside_the_table_does_not_shift_the_splice():
    before = "notes\n\n| A | B |\n| --- | --- |\n| \U0001F600 | 2 |\n\nafter\n"
    e = _editor(before)
    assert tet.replace_region(
        e, (2, 4), ["| A | B |", "| --- | --- |", "| \U0001F984 | 2 |"]) is True
    out = e.toPlainText()
    assert "| \U0001F984 | 2 |" in out
    assert out.startswith("notes\n\n")
    assert out.endswith("\n\nafter\n")


def test_emoji_after_the_table_does_not_shift_the_splice():
    before = "notes\n\n| A | B |\n| --- | --- |\n| 1 | 2 |\n\n\U0001F600 tail\n"
    e = _editor(before)
    assert tet.replace_region(
        e, (2, 4), ["| A | B |", "| --- | --- |", "| 7 | 8 |"]) is True
    out = e.toPlainText()
    assert out.startswith("notes\n\n")
    assert out.endswith("\n\n\U0001F600 tail\n")
    assert "| 7 | 8 |" in out


@pytest.mark.parametrize("emoji", [
    "\U0001F600",                 # single supplementary-plane emoji
    "\U0001F600\U0001F600",       # two emoji
    "\U0001F469\u200D\U0001F4BB",  # ZWJ sequence (woman technologist)
    "\U0001F1EA\U0001F1EA",       # regional-indicator flag pair (EE)
    "\U00020000",                 # CJK extension B (supplementary plane)
])
def test_every_astral_shape_is_offset_correct(emoji):
    before = f"{emoji} prose\n\n| A |\n| --- |\n| 1 |\n\n{emoji} tail\n"
    e = _editor(before)
    assert tet.replace_region(
        e, (2, 4), ["| A |", "| --- |", "| 5 |"]) is True
    out = e.toPlainText()
    assert out.startswith(f"{emoji} prose\n\n")
    assert out.endswith(f"\n\n{emoji} tail\n")
    assert "| 5 |" in out
    assert "| 1 |" not in out


@pytest.mark.parametrize("prose", [
    "Tere, maailm",           # Estonian
    "\u041f\u0440\u0438\u0432\u0435\u0442",  # Cyrillic (all BMP)
    "\u3053\u3093\u306b\u3061\u306f",        # Japanese (all BMP)
])
def test_bmp_multibyte_scripts_still_use_the_same_bridge(prose):
    """BMP non-ASCII is one UTF-16 unit each, so offsets coincide — but the
    conversion must be a no-op, not a corruption."""
    before = f"{prose}\n\n| A |\n| --- |\n| 1 |\n\nend\n"
    e = _editor(before)
    assert tet.replace_region(
        e, (2, 4), ["| A |", "| --- |", "| 2 |"]) is True
    out = e.toPlainText()
    assert out.startswith(f"{prose}\n\n")
    assert out.endswith("\n\nend\n")
    assert "| 2 |" in out


# --------------------------------------------------------------- boundaries

def test_table_at_the_very_start_with_an_emoji_later():
    before = "| A |\n| --- |\n| 1 |\n\n\U0001F600 tail\n"
    e = _editor(before)
    assert tet.replace_region(e, (0, 2), ["| A |", "| --- |", "| 3 |"]) is True
    assert e.toPlainText() == "| A |\n| --- |\n| 3 |\n\n\U0001F600 tail\n"


def test_table_at_the_very_end_with_an_emoji_earlier():
    before = "\U0001F600 head\n\n| A |\n| --- |\n| 1 |"
    e = _editor(before)
    assert tet.replace_region(e, (2, 4), ["| A |", "| --- |", "| 4 |"]) is True
    assert e.toPlainText() == "\U0001F600 head\n\n| A |\n| --- |\n| 4 |"


def test_two_tables_with_an_emoji_between_them():
    before = ("| A |\n| --- |\n| 1 |\n\n\U0001F600\n\n"
              "| B |\n| --- |\n| 2 |\n")
    e = _editor(before)
    assert tet.replace_region(e, (0, 2), ["| A |", "| --- |", "| 9 |"]) is True
    out = e.toPlainText()
    assert "| 9 |" in out
    # the second table, the emoji separator and everything else survive
    assert "| B |\n| --- |\n| 2 |" in out
    assert "\U0001F600" in out


def test_the_undo_step_is_whole_with_an_emoji_present():
    before = "\U0001F600 note\n\n| A |\n| --- |\n| 1 |\n"
    e = _editor(before)
    assert tet.replace_region(e, (2, 4), ["| A |", "| --- |", "| 2 |"]) is True
    assert "| 2 |" in e.toPlainText()
    e.undo()
    _app.processEvents()
    assert e.toPlainText() == before


def test_a_stale_span_is_still_refused_with_an_emoji_present():
    before = "\U0001F600\n| A |\n| --- |\n| 1 |\nnow more text\n"
    e = _editor(before)
    assert tet.replace_region(e, (1, 40), ["| x |"]) is False
    assert e.toPlainText() == before
