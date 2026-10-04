"""Tests for ephemeral selection interaction undo/redo (T-1426).

Covers all 14 required verification cases:
1. selection_deselect_ctrl_z_restores_selection
2. selection_deselect_ctrl_y_reapplies_deselection
3. text_after_deselect_undoes_before_selection
4. data_action_after_deselect_undoes_before_selection
5. selection_after_data_action_undoes_before_data
6. plain_caret_clicks_do_not_fill_undo_history
7. selection_drag_is_one_logical_interaction
8. text_replacement_does_not_create_duplicate_selection_step
9. delete_selection_is_content_undo
10. cross_silo_selection_history_isolated
11. stale_document_interaction_is_refused
12. redo_branch_invalidated_by_new_interaction
13. directed_selection_roundtrip
14. ctrlz_editor_dispatch_still_fires_once
"""

import os
import sys
import tempfile
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../tests_smoke")))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QEvent, QPointF, Qt
from PyQt6.QtGui import QKeyEvent, QMouseEvent, QTextCursor
from PyQt6.QtWidgets import QApplication

from _smoke_support import SmokeEnv, SmokeWindowFactory
from fastprompter.ui.interaction_undo import (
    CursorSelectionState,
    get_document_interaction_history,
)

_app = QApplication.instance() or QApplication([])


@pytest.fixture(scope="module")
def win():
    tmp = tempfile.mkdtemp(prefix="fp_interaction_undo_")
    env = SmokeEnv(root=tmp)
    factory = SmokeWindowFactory(env)
    w = factory.create(show=True, size=(960, 540))
    _app.processEvents()
    yield w
    factory.retire(w)
    env.finalize()


class TestSelectionInteractionUndo:

    def test_selection_deselect_ctrl_z_restores_selection(self, win):
        """1. User selects text -> clicks elsewhere / deselects -> Ctrl+Z restores selection."""
        ed = win.text_area
        ed.setPlainText("Hello World and Universe")
        _app.processEvents()

        cur = ed.textCursor()
        cur.setPosition(6, QTextCursor.MoveMode.MoveAnchor)
        cur.setPosition(11, QTextCursor.MoveMode.KeepAnchor)
        pre = ed._capture_cursor_state()
        ed.setTextCursor(cur)
        post = ed._capture_cursor_state()
        ed._record_selection_interaction_if_meaningful(pre, post)

        cur.setPosition(0, QTextCursor.MoveMode.MoveAnchor)
        pre2 = ed._capture_cursor_state()
        ed.setTextCursor(cur)
        post2 = ed._capture_cursor_state()
        ed._record_selection_interaction_if_meaningful(pre2, post2)

        assert not ed.textCursor().hasSelection()
        assert ed.textCursor().position() == 0

        win._smart_undo()
        _app.processEvents()

        cur_restored = ed.textCursor()
        assert cur_restored.hasSelection()
        assert cur_restored.anchor() == 6
        assert cur_restored.position() == 11
        assert cur_restored.selectedText() == "World"

    def test_selection_deselect_ctrl_y_reapplies_deselection(self, win):
        """2. After restoring selection with Ctrl+Z, Ctrl+Y reapplies the deselection."""
        ed = win.text_area
        ed.setPlainText("Hello World and Universe")
        _app.processEvents()

        cur = ed.textCursor()
        cur.setPosition(6, QTextCursor.MoveMode.MoveAnchor)
        cur.setPosition(11, QTextCursor.MoveMode.KeepAnchor)
        pre = ed._capture_cursor_state()
        ed.setTextCursor(cur)
        post = ed._capture_cursor_state()
        ed._record_selection_interaction_if_meaningful(pre, post)

        cur.setPosition(0, QTextCursor.MoveMode.MoveAnchor)
        pre2 = ed._capture_cursor_state()
        ed.setTextCursor(cur)
        post2 = ed._capture_cursor_state()
        ed._record_selection_interaction_if_meaningful(pre2, post2)

        win._smart_undo()
        assert ed.textCursor().hasSelection()

        win._smart_redo()
        _app.processEvents()
        assert not ed.textCursor().hasSelection()
        assert ed.textCursor().position() == 0

    def test_text_after_deselect_undoes_before_selection(self, win):
        """3. Select -> deselect -> type 'X' -> Ctrl+Z undoes 'X' -> Ctrl+Z restores selection."""
        ed = win.text_area
        ed.setPlainText("Hello World")
        _app.processEvents()

        cur = ed.textCursor()
        cur.setPosition(0, QTextCursor.MoveMode.MoveAnchor)
        cur.setPosition(5, QTextCursor.MoveMode.KeepAnchor)
        pre = ed._capture_cursor_state()
        ed.setTextCursor(cur)
        post = ed._capture_cursor_state()
        ed._record_selection_interaction_if_meaningful(pre, post)

        cur.setPosition(11, QTextCursor.MoveMode.MoveAnchor)
        pre2 = ed._capture_cursor_state()
        ed.setTextCursor(cur)
        post2 = ed._capture_cursor_state()
        ed._record_selection_interaction_if_meaningful(pre2, post2)

        ed.textCursor().insertText("!")
        _app.processEvents()
        assert ed.toPlainText() == "Hello World!"

        win._smart_undo()
        _app.processEvents()
        assert ed.toPlainText() == "Hello World"

        win._smart_undo()
        _app.processEvents()
        assert ed.textCursor().hasSelection()
        assert ed.textCursor().anchor() == 0
        assert ed.textCursor().position() == 5
        assert ed.textCursor().selectedText() == "Hello"

    def test_data_action_after_deselect_undoes_before_selection(self, win):
        """4. Select -> deselect -> data action -> Ctrl+Z undoes data -> Ctrl+Z restores selection."""
        ed = win.text_area
        ed.setPlainText("Sample text for data undo test")
        _app.processEvents()

        cur = ed.textCursor()
        cur.setPosition(0, QTextCursor.MoveMode.MoveAnchor)
        cur.setPosition(6, QTextCursor.MoveMode.KeepAnchor)
        pre = ed._capture_cursor_state()
        ed.setTextCursor(cur)
        post = ed._capture_cursor_state()
        ed._record_selection_interaction_if_meaningful(pre, post)

        cur.setPosition(10, QTextCursor.MoveMode.MoveAnchor)
        pre2 = ed._capture_cursor_state()
        ed.setTextCursor(cur)
        post2 = ed._capture_cursor_state()
        ed._record_selection_interaction_if_meaningful(pre2, post2)

        snap = win._stamp_snapshot({
            "_compact": "tick",
            "coords": 0,
            "old": True,
            "new": False,
            "category": win.get_current_category(),
        })
        win.data_undo_stack.append(snap)
        win._push_undo_state(snap)

        kinds = win._undo_kinds()
        win._smart_undo()
        _app.processEvents()
        assert "data" in kinds or len(win.data_undo_stack) == 0

        win._smart_undo()
        _app.processEvents()
        assert ed.textCursor().hasSelection()
        assert ed.textCursor().anchor() == 0
        assert ed.textCursor().position() == 6

    def test_selection_after_data_action_undoes_before_data(self, win):
        """5. Data action -> select -> deselect -> Ctrl+Z restores selection -> Ctrl+Z undoes data."""
        ed = win.text_area
        ed.setPlainText("Text before data action")
        _app.processEvents()

        snap = win._stamp_snapshot({
            "_compact": "tick",
            "coords": 0,
            "old": True,
            "new": False,
            "category": win.get_current_category(),
        })
        win.data_undo_stack.append(snap)
        win._push_undo_state(snap)

        cur = ed.textCursor()
        cur.setPosition(0, QTextCursor.MoveMode.MoveAnchor)
        cur.setPosition(4, QTextCursor.MoveMode.KeepAnchor)
        pre = ed._capture_cursor_state()
        ed.setTextCursor(cur)
        post = ed._capture_cursor_state()
        ed._record_selection_interaction_if_meaningful(pre, post)

        cur.setPosition(10, QTextCursor.MoveMode.MoveAnchor)
        pre2 = ed._capture_cursor_state()
        ed.setTextCursor(cur)
        post2 = ed._capture_cursor_state()
        ed._record_selection_interaction_if_meaningful(pre2, post2)

        # First Ctrl+Z restores selection (newer than data action)
        win._smart_undo()
        _app.processEvents()
        assert ed.textCursor().hasSelection()
        assert ed.textCursor().anchor() == 0
        assert ed.textCursor().position() == 4

        # Second Ctrl+Z reverses selection creation (back to no selection)
        win._smart_undo()
        _app.processEvents()
        assert not ed.textCursor().hasSelection()

        # Third Ctrl+Z undoes data action
        win._smart_undo()
        _app.processEvents()
        assert len(win.data_undo_stack) == 0

    def test_plain_caret_clicks_do_not_fill_undo_history(self, win):
        """6. Moving caret between positions with NO selection does NOT record undo steps."""
        ed = win.text_area
        ed.setPlainText("Simple text line")
        _app.processEvents()
        history = get_document_interaction_history(ed.document())
        history.clear()

        cur = ed.textCursor()
        cur.setPosition(0)
        ed.setTextCursor(cur)
        pre1 = ed._capture_cursor_state()
        cur.setPosition(5)
        ed.setTextCursor(cur)
        post1 = ed._capture_cursor_state()
        recorded = ed._record_selection_interaction_if_meaningful(pre1, post1)
        assert not recorded
        assert not history.can_undo()

        pre2 = ed._capture_cursor_state()
        cur.setPosition(10)
        ed.setTextCursor(cur)
        post2 = ed._capture_cursor_state()
        recorded2 = ed._record_selection_interaction_if_meaningful(pre2, post2)
        assert not recorded2
        assert not history.can_undo()

    def test_selection_drag_is_one_logical_interaction(self, win):
        """7. Mouse drag selection creates at most ONE logical interaction record."""
        ed = win.text_area
        ed.setPlainText("Testing mouse drag selection gesture")
        _app.processEvents()
        history = get_document_interaction_history(ed.document())
        history.clear()

        cur = ed.textCursor()
        cur.setPosition(0)
        ed.setTextCursor(cur)

        press_ev = QMouseEvent(QEvent.Type.MouseButtonPress, QPointF(5, 5), Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        ed.mousePressEvent(press_ev)

        cur.setPosition(0, QTextCursor.MoveMode.MoveAnchor)
        cur.setPosition(15, QTextCursor.MoveMode.KeepAnchor)
        ed.setTextCursor(cur)

        rel_ev = QMouseEvent(QEvent.Type.MouseButtonRelease, QPointF(50, 5), Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier)
        ed.mouseReleaseEvent(rel_ev)
        _app.processEvents()

        assert len(history.undo_stack) == 1
        assert history.undo_stack[0].before.anchor == 0
        assert history.undo_stack[0].before.position == 0
        assert history.undo_stack[0].after.anchor == 0
        assert history.undo_stack[0].after.position == 15

    def test_text_replacement_does_not_create_duplicate_selection_step(self, win):
        """8. Typing over selected text is content undo, not separate selection interaction."""
        ed = win.text_area
        ed.setPlainText("Replace me please")
        _app.processEvents()
        history = get_document_interaction_history(ed.document())
        history.clear()

        cur = ed.textCursor()
        cur.setPosition(0, QTextCursor.MoveMode.MoveAnchor)
        cur.setPosition(7, QTextCursor.MoveMode.KeepAnchor)
        ed.setTextCursor(cur)

        key_ev = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_F, Qt.KeyboardModifier.NoModifier, "F")
        ed.keyPressEvent(key_ev)
        _app.processEvents()

        assert history.undo_stack == []

        win._smart_undo()
        _app.processEvents()
        assert "Replace" in ed.toPlainText()

    def test_delete_selection_is_content_undo(self, win):
        """9. Delete key over selection is content undo."""
        ed = win.text_area
        ed.setPlainText("Delete this portion now")
        _app.processEvents()
        history = get_document_interaction_history(ed.document())
        history.clear()

        cur = ed.textCursor()
        cur.setPosition(0, QTextCursor.MoveMode.MoveAnchor)
        cur.setPosition(6, QTextCursor.MoveMode.KeepAnchor)
        ed.setTextCursor(cur)

        del_ev = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Delete, Qt.KeyboardModifier.NoModifier)
        ed.keyPressEvent(del_ev)
        _app.processEvents()

        assert history.undo_stack == []
        assert not ed.toPlainText().startswith("Delete")

        win._smart_undo()
        _app.processEvents()
        assert ed.toPlainText().startswith("Delete")

    def test_cross_silo_selection_history_isolated(self, win):
        """10. Selection history does not cross silo document boundaries."""
        win._switch_to_slot(0)
        _app.processEvents()
        ed = win.text_area
        ed.setPlainText("Silo Zero Text Content")
        _app.processEvents()

        cur = ed.textCursor()
        cur.setPosition(0, QTextCursor.MoveMode.MoveAnchor)
        cur.setPosition(4, QTextCursor.MoveMode.KeepAnchor)
        pre = ed._capture_cursor_state()
        ed.setTextCursor(cur)
        post = ed._capture_cursor_state()
        ed._record_selection_interaction_if_meaningful(pre, post)

        cur.setPosition(10, QTextCursor.MoveMode.MoveAnchor)
        pre2 = ed._capture_cursor_state()
        ed.setTextCursor(cur)
        post2 = ed._capture_cursor_state()
        ed._record_selection_interaction_if_meaningful(pre2, post2)

        win._switch_to_slot(1)
        _app.processEvents()
        ed.setPlainText("Silo One Text Content")
        _app.processEvents()

        win._smart_undo()
        _app.processEvents()
        assert not ed.textCursor().hasSelection()

        win._switch_to_slot(0)
        _app.processEvents()
        win._smart_undo()
        _app.processEvents()
        assert win.text_area.textCursor().hasSelection()
        assert win.text_area.textCursor().selectedText() == "Silo"

    def test_stale_document_interaction_is_refused(self, win):
        """11. Stale interaction records tied to replaced document generation are safely refused."""
        ed = win.text_area
        ed.setPlainText("Original generation text")
        _app.processEvents()

        cur = ed.textCursor()
        cur.setPosition(0, QTextCursor.MoveMode.MoveAnchor)
        cur.setPosition(8, QTextCursor.MoveMode.KeepAnchor)
        pre = ed._capture_cursor_state()
        ed.setTextCursor(cur)
        post = ed._capture_cursor_state()
        ed._record_selection_interaction_if_meaningful(pre, post)

        cur.setPosition(12, QTextCursor.MoveMode.MoveAnchor)
        pre2 = ed._capture_cursor_state()
        ed.setTextCursor(cur)
        post2 = ed._capture_cursor_state()
        ed._record_selection_interaction_if_meaningful(pre2, post2)

        win._set_plain_text_clean(ed, "Short")
        _app.processEvents()

        win._smart_undo()
        _app.processEvents()
        assert not ed.textCursor().hasSelection()

    def test_redo_branch_invalidated_by_new_interaction(self, win):
        """12. A fresh selection interaction invalidates interaction redo branch."""
        ed = win.text_area
        ed.setPlainText("Branch invalidation testing string")
        _app.processEvents()

        cur = ed.textCursor()
        cur.setPosition(0, QTextCursor.MoveMode.MoveAnchor)
        cur.setPosition(6, QTextCursor.MoveMode.KeepAnchor)
        pre = ed._capture_cursor_state()
        ed.setTextCursor(cur)
        post = ed._capture_cursor_state()
        ed._record_selection_interaction_if_meaningful(pre, post)

        cur.setPosition(10, QTextCursor.MoveMode.MoveAnchor)
        pre2 = ed._capture_cursor_state()
        ed.setTextCursor(cur)
        post2 = ed._capture_cursor_state()
        ed._record_selection_interaction_if_meaningful(pre2, post2)

        win._smart_undo()
        assert ed.textCursor().hasSelection()
        history = get_document_interaction_history(ed.document())
        assert history.can_redo()

        cur.setPosition(15, QTextCursor.MoveMode.MoveAnchor)
        cur.setPosition(20, QTextCursor.MoveMode.KeepAnchor)
        pre3 = ed._capture_cursor_state()
        ed.setTextCursor(cur)
        post3 = ed._capture_cursor_state()
        ed._record_selection_interaction_if_meaningful(pre3, post3)

        assert not history.can_redo()
        assert "interaction" not in win._undo_kinds()

    def test_directed_selection_roundtrip(self, win):
        """13. Directed backward selection preserves exact anchor and position on undo and redo."""
        ed = win.text_area
        ed.setPlainText("Directed selection test text")
        _app.processEvents()

        cur = ed.textCursor()
        cur.setPosition(18, QTextCursor.MoveMode.MoveAnchor)
        cur.setPosition(9, QTextCursor.MoveMode.KeepAnchor)
        pre = ed._capture_cursor_state()
        ed.setTextCursor(cur)
        post = ed._capture_cursor_state()
        assert post.anchor == 18
        assert post.position == 9
        assert not post.is_forward
        ed._record_selection_interaction_if_meaningful(pre, post)

        cur.setPosition(0, QTextCursor.MoveMode.MoveAnchor)
        pre2 = ed._capture_cursor_state()
        ed.setTextCursor(cur)
        post2 = ed._capture_cursor_state()
        ed._record_selection_interaction_if_meaningful(pre2, post2)

        win._smart_undo()
        _app.processEvents()
        c_undo = ed.textCursor()
        assert c_undo.anchor() == 18
        assert c_undo.position() == 9

        win._smart_redo()
        _app.processEvents()
        c_redo = ed.textCursor()
        assert not c_redo.hasSelection()
        assert c_redo.position() == 0

    def test_ctrlz_editor_dispatch_still_fires_once(self, win):
        """14. Ctrl+Z through editor keyPressEvent dispatches exactly once without duplicates."""
        ed = win.text_area
        ed.setPlainText("Single dispatch test")
        _app.processEvents()

        cur = ed.textCursor()
        cur.setPosition(0, QTextCursor.MoveMode.MoveAnchor)
        cur.setPosition(6, QTextCursor.MoveMode.KeepAnchor)
        pre = ed._capture_cursor_state()
        ed.setTextCursor(cur)
        post = ed._capture_cursor_state()
        ed._record_selection_interaction_if_meaningful(pre, post)

        cur.setPosition(10, QTextCursor.MoveMode.MoveAnchor)
        pre2 = ed._capture_cursor_state()
        ed.setTextCursor(cur)
        post2 = ed._capture_cursor_state()
        ed._record_selection_interaction_if_meaningful(pre2, post2)

        key_ev = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier, "z")
        ed.keyPressEvent(key_ev)
        _app.processEvents()

        assert ed.textCursor().hasSelection()
        assert ed.textCursor().anchor() == 0
        assert ed.textCursor().position() == 6
        assert win.isVisible()
