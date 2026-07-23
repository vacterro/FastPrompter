"""Ctrl+E must produce what its settings page promises.

The header block used to be hardcoded in main.py - always a ---, always two
blank lines, always "• " - and the settings dialog could only reword the
title. Now core/header.build_block() is the single source, and this file
runs the real editor to prove the preview is not fiction.

    uv run pytest tests_smoke/test_header_settings.py -q
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication

import fastprompter.core.state as state_mod
from fastprompter.core import header as header_core
from fastprompter.main import FastPrompter

_app = QApplication.instance() or QApplication([])
_tmpdir = tempfile.mkdtemp(prefix="fastprompter_hdr_")


@pytest.fixture(scope="module")
def win():
    state_mod.get_db_path = lambda profile_id=1: os.path.join(_tmpdir, f"h_{profile_id}.db")
    state_mod.run_portable_backup = lambda data: None
    FastPrompter.setup_single_instance_server = lambda self: None
    FastPrompter.register_all_hotkeys = lambda self: None
    FastPrompter.unregister_all_hotkeys = lambda self: None
    w = FastPrompter()
    yield w
    w.auto_save_timer.stop()
    w.topmost_timer.stop()
    w._cache_timer.stop()
    w.state.conn = None
    w.conn = None
    w.close()


def _set(win, **kw):
    """Write the Ctrl+E settings the way the dialog's OK button does."""
    for k, v in kw.items():
        win.data[f"ctrl_e_{k}"] = v


def _press(win, line="Design notes"):
    """Type one line, put the caret on it, press Ctrl+E, return the doc."""
    win.text_area.setPlainText(line)
    cur = win.text_area.textCursor()
    cur.setPosition(len(line))
    win.text_area.setTextCursor(cur)
    win.apply_header_timestamp()
    return win.text_area.toPlainText()


def _shape(text):
    """The document with the volatile stamp removed - shape only."""
    lines = text.split("\n")
    if lines and lines[0].startswith("# "):
        lines[0] = "# TITLE"
    return lines


# ── the settings actually reach the editor ──


def test_rule_can_be_switched_off(win):
    _set(win, rule="False", gap_after="2", bullet="True", bullet_char="•")
    lines = _shape(_press(win))
    assert "---" not in lines
    assert lines[0] == "# TITLE"


def test_rule_on_puts_it_under_the_title(win):
    _set(win, rule="True", gap_after="2", bullet="True", bullet_char="•")
    lines = _shape(_press(win))
    assert lines[1] == "---"


def test_gap_is_the_number_of_empty_lines(win):
    for gap in (0, 1, 4):
        _set(win, rule="True", gap_after=str(gap), bullet="True", bullet_char="•")
        lines = _shape(_press(win))
        blanks = lines[2:2 + gap]
        assert blanks == [""] * gap, (gap, lines)
        assert lines[2 + gap] == "• "


def test_bullet_can_be_switched_off_and_changed(win):
    _set(win, rule="True", gap_after="1", bullet="False")
    assert not any(line.startswith("• ") for line in _shape(_press(win)))

    _set(win, rule="True", gap_after="1", bullet="True", bullet_char="→")
    assert _shape(_press(win))[-1] == "→ "


def test_caret_lands_on_the_bullet(win):
    _set(win, rule="True", gap_after="2", bullet="True", bullet_char="•")
    _press(win)
    cur = win.text_area.textCursor()
    assert cur.block().text() == "• "
    assert cur.atBlockEnd()


def test_alignment_reaches_the_title_block(win):
    for word, flag in (("center", Qt.AlignmentFlag.AlignCenter),
                       ("right", Qt.AlignmentFlag.AlignRight),
                       ("justify", Qt.AlignmentFlag.AlignJustify)):
        _set(win, align=word, rule="True", gap_after="1", bullet="True", bullet_char="•")
        _press(win)
        first = win.text_area.document().firstBlock()
        assert first.blockFormat().alignment() & flag, word
    _set(win, align="left")


def test_the_footer_checkbox_still_drives_the_alignment(win):
    """It writes only the old boolean; read_settings prefers ctrl_e_align."""
    win._on_ctrl_e_center_toggled(True)
    assert header_core.read_settings(win.data)["align"] == "center"
    win._on_ctrl_e_center_toggled(False)
    assert header_core.read_settings(win.data)["align"] == "left"


def test_old_centre_flag_is_honoured_when_no_alignment_was_ever_stored(win):
    d = {"ctrl_e_center": "True"}
    assert header_core.read_settings(d)["align"] == "center"
    d = {"ctrl_e_center": "False"}
    assert header_core.read_settings(d)["align"] == "left"


# ── the preview equals the editor ──


@pytest.mark.parametrize("rule,gap,bullet,char", [
    (True, 2, True, "•"),
    (False, 0, True, "-"),
    (True, 4, False, "•"),
    (False, 1, False, "•"),
])
def test_preview_block_matches_the_document(win, rule, gap, bullet, char):
    _set(win, rule="True" if rule else "False", gap_after=str(gap),
         bullet="True" if bullet else "False", bullet_char=char)
    cfg = header_core.read_settings(win.data)
    expected = header_core.build_block(cfg, "# TITLE")
    assert _shape(_press(win)) == expected


# ── Ctrl+E remains its own undo ──


def test_second_press_takes_the_header_off(win):
    _set(win, rule="True", gap_after="2", bullet="True", bullet_char="•")
    _press(win, "Journal")
    cur = win.text_area.textCursor()
    cur.setPosition(0)
    win.text_area.setTextCursor(cur)
    win.apply_header_timestamp()
    assert win.text_area.document().firstBlock().text() == "Journal"


def test_second_press_reverses_even_with_the_rule_off(win):
    """It used to insert a --- here instead of undoing - the toggle died."""
    _set(win, rule="False", gap_after="1", bullet="False")
    _press(win, "Journal")
    cur = win.text_area.textCursor()
    cur.setPosition(0)
    win.text_area.setTextCursor(cur)
    win.apply_header_timestamp()
    assert win.text_area.document().firstBlock().text() == "Journal"
