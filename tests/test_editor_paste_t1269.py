"""T-1269C: Ctrl+V must actually paste, not merely play the paste sound.

The operator report that opened this wave was "Ctrl+V plays the paste sound
but no text appears". Sound and mutation are two separate stages of
``VaultTextEdit.keyPressEvent``: the built-in key-sound routing fires for
``Key_V`` and falls through, and the paste branch further down calls
``self.paste()``. A green sound therefore proves only that the key-event path
was reached -- it says nothing about whether the document changed.

SCOPE: these are UNIT-level tests of the handler CONTRACT, not end-to-end
keyboard proof. ``_direct_key`` below hands a ``QKeyEvent`` straight to
``VaultTextEdit.keyPressEvent``; that bypasses QApplication event routing,
application event filters, ``LayoutIndependentShortcuts``, QShortcut
conflict resolution, focus routing and Windows native key metadata. What it
does pin is the decision table inside the handler (caret/selection text,
non-BMP text, the layout-normalized editing keys, Ctrl+Z/Ctrl+Y, the
read-only refusal) -- each of which would otherwise need a live window.

This module therefore CANNOT establish that a real Ctrl+V reaches the editor
on the operator's machine, and must not be read as if it did. That claim
belongs to ``tests/test_editor_paste_live_t1269.py``, which builds a real
``FastPrompter`` window and drives it with ``QTest.keyClick``. Keeping both
is the point: the two suites fail for different reasons.

Clipboard hygiene: this module WRITES the machine's clipboard. Every test
runs inside a snapshot/restore fixture -- a leaked clipboard is a real bug
for whoever is using the machine, and the shipped profile seeds new silos
from the clipboard, so a leak also poisons unrelated suites.
"""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

import pytest
from PyQt6.QtCore import QEvent, Qt
from PyQt6.QtGui import QKeyEvent, QTextCursor
from PyQt6.QtWidgets import QApplication

from fastprompter.ui.editor import VaultTextEdit

EMOJI = "\U0001F600"
FAMILY = "\U0001F468‍\U0001F469‍\U0001F467‍\U0001F466"

# Windows set-1 scan codes: the PHYSICAL key, which does not move with the
# keyboard layout. Mirrors editor._SCAN_TO_KEY.
SCAN_A, SCAN_C, SCAN_V, SCAN_X = 0x1E, 0x2E, 0x2F, 0x2D


@pytest.fixture(autouse=True)
def _own_the_clipboard(qapp):
    clip = QApplication.clipboard()
    before = clip.text()
    try:
        yield
    finally:
        if before:
            clip.setText(before)
        else:
            clip.clear()


class _Owner:
    """Weak-referenceable stand-in for the FastPrompter window.

    ``SimpleNamespace`` is not: ``qt_lifetime.weak_qt_callback`` takes a
    ``weakref.ref`` to the owner on the Ctrl+C path and a namespace blows up
    there, which is a harness artefact and not the behaviour under test.
    """

    highlighter = None
    _LARGE_DOC_THRESHOLD = 500_000
    _LARGE_DOC_BLOCK_THRESHOLD = 2000
    cb_ctrl_c = None

    def __init__(self, sounds):
        self.data = {"sound_ui": "True", "sound_typewriter": "False",
                     "auto_bullet": "False", "bullet_double_line": "False",
                     "ctrl_c_closes": "False"}
        self.play_sound = sounds.append


def _make_editor(qapp, played=None):
    """A real VaultTextEdit with the owner attributes the key path reads."""
    sounds = played if played is not None else []
    main = _Owner(sounds)
    ed = VaultTextEdit(main)
    # Undo/redo in the editor is routed through the owner window; wire it to
    # the document so the Ctrl+Z/Ctrl+Y handler branches can be driven here.
    main._smart_undo = ed.undo
    main._smart_redo = ed.redo
    ed.show()
    ed.setFocus()
    return ed, main, sounds


def _direct_key(ed, key, mods=Qt.KeyboardModifier.ControlModifier, scan=0, text=""):
    """Feed one QKeyEvent to ``keyPressEvent`` -- NOT a real key press.

    Named for what it does. Qt is never involved: no routing, no filters, no
    shortcut arbitration, no focus. Every test using this helper is a unit
    test of the handler's decision table. For the live route see
    ``test_editor_paste_live_t1269``.
    """
    ev = QKeyEvent(QEvent.Type.KeyPress, key, mods, scan, 0, 0, text)
    ed.keyPressEvent(ev)
    return ev


def _direct_ctrl_v(ed, scan=SCAN_V):
    return _direct_key(ed, Qt.Key.Key_V, scan=scan, text="\x16")


def _set_caret(ed, pos):
    cur = ed.textCursor()
    cur.setPosition(pos)
    ed.setTextCursor(cur)


def _select(ed, start, end):
    cur = ed.textCursor()
    cur.setPosition(start)
    cur.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
    ed.setTextCursor(cur)


# --------------------------------------------------------------------------
# the mandatory reproduction
# --------------------------------------------------------------------------

def test_ctrl_v_inserts_clipboard_text_at_caret(qapp):
    """Handler contract: the Ctrl+V event -> exact text at the exact caret.

    Unit coverage of ``keyPressEvent``, not proof that a real Ctrl+V lands on
    the operator's machine (see the module docstring).
    """
    ed, _main, _sounds = _make_editor(qapp)
    ed.setPlainText("hello world")
    _set_caret(ed, 5)
    QApplication.clipboard().setText("XYZ")
    _direct_ctrl_v(ed)
    assert ed.toPlainText() == "helloXYZ world"
    assert ed.textCursor().position() == 8  # caret after the inserted text
    ed.deleteLater()


def test_ctrl_v_sound_is_not_evidence_of_a_paste(qapp):
    """Sound AND mutation, asserted separately in one press."""
    ed, _main, sounds = _make_editor(qapp)
    ed.setPlainText("ab")
    _set_caret(ed, 2)
    QApplication.clipboard().setText("c")
    _direct_ctrl_v(ed)
    assert sounds.count("paste") == 1, sounds
    assert ed.toPlainText() == "abc", "sound played but the document did not change"
    ed.deleteLater()


def test_ctrl_v_into_empty_editor(qapp):
    ed, _main, _sounds = _make_editor(qapp)
    ed.setPlainText("")
    QApplication.clipboard().setText("seeded")
    _direct_ctrl_v(ed)
    assert ed.toPlainText() == "seeded"
    ed.deleteLater()


def test_ctrl_v_replaces_the_selected_range(qapp):
    ed, _main, _sounds = _make_editor(qapp)
    ed.setPlainText("keep DROP keep")
    _select(ed, 5, 9)
    QApplication.clipboard().setText("NEW")
    _direct_ctrl_v(ed)
    assert ed.toPlainText() == "keep NEW keep"
    ed.deleteLater()


def test_ctrl_v_multiline_clipboard_text(qapp):
    ed, _main, _sounds = _make_editor(qapp)
    ed.setPlainText("startend")
    _set_caret(ed, 5)
    QApplication.clipboard().setText("one\ntwo\nthree")
    _direct_ctrl_v(ed)
    assert ed.toPlainText() == "startone\ntwo\nthreeend"
    assert ed.document().blockCount() == 3
    ed.deleteLater()


def test_ctrl_v_cyrillic_clipboard_text(qapp):
    ed, _main, _sounds = _make_editor(qapp)
    ed.setPlainText("[]")
    _set_caret(ed, 1)
    QApplication.clipboard().setText("Привет мир")
    _direct_ctrl_v(ed)
    assert ed.toPlainText() == "[Привет мир]"
    ed.deleteLater()


def test_ctrl_v_non_bmp_clipboard_text(qapp):
    """Non-BMP paste must survive intact -- the T-1269 defect class."""
    ed, _main, _sounds = _make_editor(qapp)
    ed.setPlainText("AB")
    _set_caret(ed, 1)
    QApplication.clipboard().setText(EMOJI + FAMILY)
    _direct_ctrl_v(ed)
    assert ed.toPlainText() == "A" + EMOJI + FAMILY + "B"
    ed.deleteLater()


def test_repeated_ctrl_v_appends_each_time(qapp):
    ed, _main, sounds = _make_editor(qapp)
    ed.setPlainText("")
    QApplication.clipboard().setText("ab")
    for _ in range(3):
        _direct_ctrl_v(ed)
    assert ed.toPlainText() == "ababab"
    assert sounds.count("paste") == 3, sounds
    ed.deleteLater()


def test_ctrl_z_reverses_exactly_one_paste_and_ctrl_y_reapplies(qapp):
    """Ctrl+Z removes the pasted text and NOTHING else; Ctrl+Y puts it back."""
    ed, _main, _sounds = _make_editor(qapp)
    ed.setPlainText("base")
    _set_caret(ed, 4)
    QApplication.clipboard().setText("-one")
    _direct_ctrl_v(ed)
    assert ed.toPlainText() == "base-one"

    _direct_key(ed, Qt.Key.Key_Z, scan=0x2C)
    assert ed.toPlainText() == "base", "Ctrl+Z must reverse the paste exactly"

    _direct_key(ed, Qt.Key.Key_Y, scan=0x15)
    assert ed.toPlainText() == "base-one"
    ed.deleteLater()


def test_ctrl_v_does_not_move_focus(qapp):
    """Pasting must not hand focus anywhere else.

    Asserted as "focus is unchanged" rather than "the editor has focus":
    offscreen, whichever widget a sibling module left focused is the one Qt
    reports, and that is not what this test is about.
    """
    ed, _main, _sounds = _make_editor(qapp)
    ed.setPlainText("x")
    _set_caret(ed, 1)
    qapp.processEvents()
    before = QApplication.focusWidget()
    QApplication.clipboard().setText("y")
    _direct_ctrl_v(ed)
    assert ed.toPlainText() == "xy"
    assert QApplication.focusWidget() is before
    ed.deleteLater()


def test_read_only_editor_does_not_mutate(qapp):
    ed, _main, _sounds = _make_editor(qapp)
    ed.setPlainText("frozen")
    ed.setReadOnly(True)
    QApplication.clipboard().setText("INTRUDER")
    _direct_ctrl_v(ed)
    assert ed.toPlainText() == "frozen"
    ed.deleteLater()


# --------------------------------------------------------------------------
# keyboard-layout audit: the standard editing shortcuts
# --------------------------------------------------------------------------

def test_standard_shortcuts_english_layout(qapp):
    """Ctrl+A / Ctrl+C / Ctrl+X / Ctrl+V on a Latin layout."""
    ed, _main, sounds = _make_editor(qapp)
    ed.setPlainText("abcdef")

    _select(ed, 0, 3)
    _direct_key(ed, Qt.Key.Key_C, scan=SCAN_C)
    assert QApplication.clipboard().text() == "abc"
    assert sounds.count("copy") == 1

    _select(ed, 0, 3)
    _direct_key(ed, Qt.Key.Key_X, scan=SCAN_X, text="\x18")
    assert ed.toPlainText() == "def"
    assert QApplication.clipboard().text() == "abc"
    assert sounds.count("cut") == 1

    _direct_key(ed, Qt.Key.Key_A, scan=SCAN_A, text="\x01")
    assert ed.textCursor().selectedText() == "def"
    assert sounds.count("select_all") == 1

    _direct_ctrl_v(ed)
    assert ed.toPlainText() == "abc"
    assert sounds.count("paste") == 1
    ed.deleteLater()


def test_ctrl_c_with_no_selection_copies_the_whole_document(qapp):
    """The toolbar contract ("Copy all text") -- unchanged by T-1269."""
    ed, main, _sounds = _make_editor(qapp)
    main.cb_ctrl_c = None
    main.data["ctrl_c_closes"] = "False"
    ed.setPlainText("everything")
    _set_caret(ed, 0)
    _direct_key(ed, Qt.Key.Key_C, scan=SCAN_C)
    assert QApplication.clipboard().text() == "everything"
    ed.deleteLater()


@pytest.mark.skipif(sys.platform != "win32",
                    reason="scan-code normalization is the Windows set-1 map")
def test_ctrl_v_under_a_non_latin_layout(qapp):
    """Physical V with a Cyrillic ``key()``.

    ``event.key()`` follows the ACTIVE LAYOUT, so on a Russian keyboard the
    physical V reports a Cyrillic letter. T-735 normalized the CONFIGURABLE
    hotkeys through ``nativeScanCode`` but left the standard editing four on
    the raw key, so Ctrl+A/C/V/X were silently dead there -- no sound, no
    editing. T-1269C routes them through the same normalized key.
    """
    ed, _main, sounds = _make_editor(qapp)
    ed.setPlainText("ab")
    _set_caret(ed, 2)
    QApplication.clipboard().setText("!")
    _direct_key(ed, Qt.Key.Key_M, scan=SCAN_V, text="м")   # physical V, RU layout
    assert ed.toPlainText() == "ab!"
    assert sounds.count("paste") == 1, sounds
    ed.deleteLater()


@pytest.mark.skipif(sys.platform != "win32",
                    reason="scan-code normalization is the Windows set-1 map")
def test_standard_shortcuts_under_a_non_latin_layout(qapp):
    """Ctrl+A / Ctrl+C / Ctrl+X on physical keys with Cyrillic ``key()``."""
    ed, _main, sounds = _make_editor(qapp)
    ed.setPlainText("abcdef")

    _select(ed, 0, 3)
    _direct_key(ed, Qt.Key.Key_S, scan=SCAN_C, text="с")        # physical C
    assert QApplication.clipboard().text() == "abc"
    assert sounds.count("copy") == 1

    _select(ed, 0, 3)
    _direct_key(ed, Qt.Key.Key_CapsLock, scan=SCAN_X, text="ч")  # physical X
    assert ed.toPlainText() == "def"
    assert QApplication.clipboard().text() == "abc"
    assert sounds.count("cut") == 1

    _direct_key(ed, Qt.Key.Key_F, scan=SCAN_A, text="ф")         # physical A
    assert ed.textCursor().selectedText() == "def"
    assert sounds.count("select_all") == 1
    ed.deleteLater()
