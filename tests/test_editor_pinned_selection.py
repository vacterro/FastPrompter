"""Ctrl+click persistent word selection in the editor."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from types import SimpleNamespace

from PyQt6.QtCore import QPointF, Qt
from PyQt6.QtGui import QMouseEvent, QTextDocument
from PyQt6.QtWidgets import QApplication

from fastprompter.ui.editor import VaultTextEdit

# Module-level, so the QApplication is never garbage-collected mid-test.
_APP = QApplication.instance() or QApplication([])


def _stub():
    s = SimpleNamespace()
    s.data = {
        "show_line_numbers": "False",
        "code_auto_gutter": "False",
        "line_heat_minutes": "1440",
        "line_heat_strength": "18",
        "line_heat_palette": "warm",
        "hover_line": "True",
        "hover_line_opacity": "10",
        "hover_line_color": "auto",
    }
    s.highlighter = None
    s._get_custom_colors = lambda: {}
    return s


def _app():
    return _APP


def _editor_with(text):
    ed = VaultTextEdit(_stub())
    doc = QTextDocument()
    doc.setPlainText(text)
    ed.set_active_document(doc)
    ed.resize(600, 200)
    ed.show()
    _app().processEvents()
    return ed


def _ctrl_click(ed, pos):
    ev = QMouseEvent(
        QMouseEvent.Type.MouseButtonPress,
        QPointF(pos),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.ControlModifier,
    )
    ed.mousePressEvent(ev)
    _app().processEvents()


def _word_pos(ed, start):
    cur = ed.textCursor()
    cur.setPosition(start)
    return ed.cursorRect(cur).center()


def _close(ed):
    # NOTE: no processEvents() after close — a deferred _apply_extra_selections
    # can fire on the destroyed document and fast-fail Qt.
    ed.close()


def test_ctrl_click_pins_and_toggles_word():
    ed = _editor_with("hello world")
    pos = _word_pos(ed, 0)
    _ctrl_click(ed, pos)
    assert ed._pinned_selections == [(0, 5)]
    _ctrl_click(ed, pos)
    assert ed._pinned_selections == []
    _ctrl_click(ed, _word_pos(ed, 6))
    assert ed._pinned_selections == [(6, 11)]
    _close(ed)


def test_ctrl_triple_click_in_press_path_clears_all():
    """Qt never sends a triple-click event, so the third press must clear."""
    ed = _editor_with("hello world beyond")
    _ctrl_click(ed, _word_pos(ed, 0))
    _ctrl_click(ed, _word_pos(ed, 12))
    assert len(ed._pinned_selections) == 2
    same = _word_pos(ed, 12)
    _ctrl_click(ed, same)    # 2nd consecutive click here
    _ctrl_click(ed, same)    # 3rd -> clear all
    assert ed._pinned_selections == []
    _close(ed)


def test_pins_survive_a_document_swap_and_stay_per_document():
    """A pin is a focus mark: switching silos must not drop it."""
    ed = _editor_with("hello world")
    first = ed.document()
    _ctrl_click(ed, _word_pos(ed, 0))
    assert ed._pinned_selections == [(0, 5)]

    other = QTextDocument()
    other.setPlainText("second silo text")
    ed.set_active_document(other)
    _app().processEvents()
    # the pin still exists, but belongs to the other document, so nothing
    # is painted here
    assert ed._pinned_extra_selections(other) == []
    assert ed._pinned_selections == [(0, 5)]

    ed.set_active_document(first)
    _app().processEvents()
    assert len(ed._pinned_extra_selections(first)) == 1
    _close(ed)


def test_triple_click_ctrl_clears_all():
    ed = _editor_with("hello world")
    _ctrl_click(ed, _word_pos(ed, 0))
    _ctrl_click(ed, _word_pos(ed, 6))
    assert len(ed._pinned_selections) == 2
    ev = QMouseEvent(
        QMouseEvent.Type.MouseButtonDblClick,
        QPointF(_word_pos(ed, 0)),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.ControlModifier,
    )
    ed.mouseTripleClickEvent(ev)
    assert ed._pinned_selections == []
    _close(ed)


def test_text_change_keeps_pinned_ranges_alive():
    """A pinned word is a focus mark: editing nearby text must not clear it.

    The QTextCursor adjusts with the document, so inserting a character just
    before/inside the word extends the pinned range instead of dropping it.
    """
    ed = _editor_with("hello world")
    _ctrl_click(ed, _word_pos(ed, 0))
    assert ed._pinned_selections == [(0, 5)]
    cursor = ed.textCursor()
    cursor.setPosition(5)
    cursor.insertText("!")
    _app().processEvents()
    assert ed._pinned_selections == [(0, 6)]  # cursor followed the edit
    _close(ed)


def test_rendered_as_extra_selections():
    ed = _editor_with("hello world")
    _ctrl_click(ed, _word_pos(ed, 0))
    sel = ed._pinned_extra_selections(ed.document())
    assert len(sel) == 1
    cur = sel[0].cursor
    assert (cur.selectionStart(), cur.selectionEnd()) == (0, 5)
    assert sel[0].format.background().color().isValid()
    _close(ed)
