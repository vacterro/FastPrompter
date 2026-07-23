"""Sending a selection to another silo or the archive.

Data-safety rules this pins down:
  the source keeps its text - these copy, never cut
  an append never overwrites what was already in the target
  the target's cached QTextDocument moves with the string list, or the
  stale document writes the append straight back out again

    uv run pytest tests_smoke/test_send_selection.py -q
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtGui import QTextCursor
from PyQt6.QtWidgets import QApplication

import fastprompter.core.state as state_mod
from fastprompter.main import FastPrompter
from fastprompter.ui.send_selection_mixin import silo_label

_app = QApplication.instance() or QApplication([])
_tmpdir = tempfile.mkdtemp(prefix="fastprompter_send_")


@pytest.fixture(scope="module")
def win():
    state_mod.get_db_path = lambda profile_id=1: os.path.join(_tmpdir, f"s_{profile_id}.db")
    state_mod.run_portable_backup = lambda data: None
    FastPrompter.setup_single_instance_server = lambda self: None
    FastPrompter.register_all_hotkeys = lambda self: None
    FastPrompter.unregister_all_hotkeys = lambda self: None
    w = FastPrompter()
    w._files_root = lambda: os.path.join(_tmpdir, "files")
    yield w
    w.auto_save_timer.stop()
    w.topmost_timer.stop()
    w._cache_timer.stop()
    w.state.conn = None
    w.conn = None
    w.close()


def _fresh(win, text="alpha\nbeta\ngamma"):
    """One silo holding `text`, with the caret in it and nothing selected."""
    win.cat_combo.setCurrentIndex(0)
    win.on_tab_changed(0)
    win.data["temp_presets"][:] = [text, "", ""]
    win.data["archive_temp_presets"][:] = []
    win.data["silo_children"].clear()
    win.silo_docs[:] = []
    win.archive_docs[:] = []
    win.active_is_archive = False
    win._switch_to_slot(0, initial=True)
    return text


def _seed(win, idx, text):
    """Put `text` in silo `idx` AND materialise its cached document.

    silo_docs is grown lazily, so a slot that has never been opened has no
    document at all - the test has to open it to get one, the same way a
    user would.
    """
    win.data["temp_presets"][idx] = text
    win._switch_to_slot(idx, initial=True)
    win._switch_to_slot(0, initial=True)


def _select(win, needle):
    """Select the first occurrence of `needle` in the open editor."""
    doc_text = win.text_area.toPlainText()
    start = doc_text.index(needle)
    cur = win.text_area.textCursor()
    cur.setPosition(start)
    cur.setPosition(start + len(needle), QTextCursor.MoveMode.KeepAnchor)
    win.text_area.setTextCursor(cur)


# ── reading the selection ──


def test_no_selection_means_no_destination_does_anything(win):
    _fresh(win)
    cur = win.text_area.textCursor()
    cur.clearSelection()
    win.text_area.setTextCursor(cur)
    assert win.selected_text() == ""
    assert win.selection_to_new_silo() is False
    assert win.selection_to_new_child_silo() is False
    assert win.selection_to_new_archive() is False
    assert win.selection_to_silo(1) is False


def test_a_multi_line_selection_keeps_its_line_breaks(win):
    """Qt hands back U+2029 for those breaks; untranslated it arrives as
    one unbroken line."""
    _fresh(win)
    _select(win, "alpha\nbeta")
    assert win.selected_text() == "alpha\nbeta"


# ── new silo ──


def test_selection_to_a_new_silo_leaves_the_source_alone(win):
    src = _fresh(win)
    _select(win, "beta")
    assert win.selection_to_new_silo() is True
    assert win.data["temp_presets"][0] == src, "this copies, it must not cut"
    assert "beta" in win.data["temp_presets"][win.active_temp_slot]


def test_selection_to_a_new_child_silo_nests_it(win):
    _fresh(win)
    _select(win, "gamma")
    assert win.selection_to_new_child_silo() is True
    new_idx = win.active_temp_slot
    assert win.data["temp_presets"][new_idx].strip() == "gamma"
    kids = [v for k, v in win.data["silo_children"].items() if str(k) == "0"]
    assert kids and new_idx in kids[0], win.data["silo_children"]


# ── appending ──


def test_appending_keeps_what_was_already_there(win):
    _fresh(win)
    _seed(win, 1, "existing note")
    _select(win, "beta")
    assert win.selection_to_silo(1) is True
    assert win.data["temp_presets"][1] == "existing note\n\nbeta"


def test_appending_updates_the_cached_document_too(win):
    """Left stale, reopening the silo writes the old text back over it."""
    _fresh(win)
    _seed(win, 1, "existing note")
    _select(win, "beta")
    win.selection_to_silo(1)
    assert win.silo_docs[1].toPlainText() == "existing note\n\nbeta"
    win._switch_to_slot(1, initial=True)
    assert win.text_area.toPlainText() == "existing note\n\nbeta"


def test_appending_into_an_empty_silo_adds_no_leading_blank_lines(win):
    _fresh(win)
    _select(win, "beta")
    win.selection_to_silo(1)
    assert win.data["temp_presets"][1] == "beta"


def test_an_out_of_range_target_changes_nothing(win):
    src = _fresh(win)
    _select(win, "beta")
    assert win.selection_to_silo(99) is False
    assert win.data["temp_presets"][0] == src


# ── archive ──


def test_selection_to_a_new_archive_entry(win):
    src = _fresh(win)
    _select(win, "alpha")
    assert win.selection_to_new_archive() is True
    assert win.data["archive_temp_presets"][0] == "alpha"
    assert win.archive_docs[0].toPlainText() == "alpha"
    assert win.data["temp_presets"][0] == src


def test_selection_appended_to_an_existing_archive_entry(win):
    _fresh(win)
    win.data["archive_temp_presets"][:] = ["old entry"]
    from PyQt6.QtGui import QTextDocument
    d = QTextDocument()
    d.setPlainText("old entry")
    win.archive_docs[:] = [d]
    _select(win, "gamma")
    assert win.selection_to_archive(0) is True
    assert win.data["archive_temp_presets"][0] == "old entry\n\ngamma"
    assert win.archive_docs[0].toPlainText() == "old entry\n\ngamma"


def test_a_child_silo_asked_for_inside_the_archive_becomes_an_entry(win):
    """The archive is flat - there is nothing to nest into."""
    _fresh(win)
    win.data["archive_temp_presets"][:] = ["something"]
    from PyQt6.QtGui import QTextDocument
    d = QTextDocument()
    d.setPlainText("something")
    win.archive_docs[:] = [d]
    _select(win, "beta")
    win.active_is_archive = True
    try:
        assert win.selection_to_new_child_silo() is True
        assert win.data["archive_temp_presets"][0] == "beta"
    finally:
        win.active_is_archive = False


# ── the menu and the labels ──


def test_the_submenu_is_disabled_without_a_selection(win):
    from PyQt6.QtWidgets import QMenu

    _fresh(win)
    cur = win.text_area.textCursor()
    cur.clearSelection()
    win.text_area.setTextCursor(cur)
    menu = QMenu()
    sub = win.build_send_selection_menu(menu)
    assert sub.isEnabled() is False
    assert len(sub.actions()) >= 5

    _select(win, "beta")
    menu2 = QMenu()
    assert win.build_send_selection_menu(menu2).isEnabled() is True


def test_picker_labels_name_the_slot_and_its_first_real_line():
    assert silo_label(2, "# Design notes\n\nbody") == "3 — Design notes"
    assert silo_label(0, "\n\n   \nlate start") == "1 — late start"
    assert silo_label(0, "") == "1 — (empty)"
    assert silo_label(0, "x" * 80).endswith("…")
