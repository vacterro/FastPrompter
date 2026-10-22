"""T-1462 Stage 3: model / document undo consistency for the table silo.

The defect: with focus on the child QTableView the window-level Ctrl+Z
shortcut fires `_smart_undo`, which reverts the QTextDocument but leaves the
grid's MODEL holding the pre-undo table for up to 300 ms (the rebuild timer).
Inside that window the stale model either writes the undone edit straight back
into the document, or refuses the next real edit as a "stale source" and the
user's keystroke is silently dropped.

These tests drive a REAL FastPrompter window: a real QTextEdit, a real
QTableView, real key events. Nothing here mocks `_smart_undo` or
`_on_visual_widget_changed`, because the defect is the wiring between them.
"""

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QTextCursor
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

import fastprompter.core.state as state_mod

_APP = QApplication.instance() or QApplication([])

TABLE_DOC = (
    "# Title\n"
    "\n"
    "Notes above.\n"
    "\n"
    "| Name | Qty |\n"
    "| :--- | ---: |\n"
    "| apple | 3 |\n"
    "\n"
    "Footer.\n"
)


@pytest.fixture(scope="module")
def win(tmp_path_factory):
    tmp_path = tmp_path_factory.mktemp("t1462undo")
    original_db_path = state_mod.get_db_path
    state_mod.get_db_path = (
        lambda profile_id=1: str(tmp_path / f"t1462u_{profile_id}.db"))
    import fastprompter.utils.portable_backup as backup_mod
    original_backup = backup_mod.run_portable_backup
    backup_mod.run_portable_backup = lambda data, profile_id=1, **_kw: None

    from fastprompter.main import FastPrompter
    originals = {
        name: getattr(FastPrompter, name)
        for name in ("setup_single_instance_server", "register_all_hotkeys",
                     "unregister_all_hotkeys")
    }
    FastPrompter.setup_single_instance_server = lambda self: None
    FastPrompter.register_all_hotkeys = lambda self: None
    FastPrompter.unregister_all_hotkeys = lambda self: None
    w = FastPrompter()
    for _ in range(5):
        _APP.processEvents()
    w._initializing_ui = False
    w._suspend_temp_sync = False
    w.show()
    _APP.processEvents()
    try:
        yield w
    finally:
        for name in ("auto_save_timer", "topmost_timer", "_cache_timer"):
            timer = getattr(w, name, None)
            if timer is not None:
                timer.stop()
        service = getattr(w, "limit_service", None)
        if service is not None:
            service.shutdown()
        for name, handler in originals.items():
            setattr(FastPrompter, name, handler)
        state_mod.get_db_path = original_db_path
        backup_mod.run_portable_backup = original_backup


def _open_table_silo(w, text, slot=0):
    w.data["temp_presets"][:] = ["", "", "", "", "", "", "", "", "", ""]
    w.data["temp_presets"][slot] = text
    w.data.setdefault("silo_types", {})[str(slot)] = "table"
    w.silo_docs[:] = []
    w._switch_to_slot(slot, initial=True)
    _APP.processEvents()
    return getattr(w, "table_widget", None)


def _commit(w, tw):
    """Write the grid's table into the document the way the 500 ms timer
    would, as ONE undo step."""
    w._on_visual_widget_changed(tw.serialize(), tw)
    _APP.processEvents()


def _focus_view(tw):
    tw.view.setFocus()
    _APP.processEvents()
    assert tw.view.hasFocus()


def _press(mod, key, target=None):
    QTest.keyClick(target, key, mod)
    _APP.processEvents()


# ---------------------------------------------------------------- dispatch


def test_ctrl_z_with_focus_on_the_tableview_undoes_the_table_edit(win):
    tw = _open_table_silo(win, TABLE_DOC)
    _focus_view(tw)
    tw.model.setData(tw.model.index(1, 0), "CHANGED",
                    Qt.ItemDataRole.EditRole)
    _commit(win, tw)
    assert "CHANGED" in win.text_area.toPlainText()

    _focus_view(tw)
    _press(Qt.KeyboardModifier.ControlModifier, Qt.Key.Key_Z)

    out = win.text_area.toPlainText()
    assert "CHANGED" not in out
    assert "apple" in out
    assert out == TABLE_DOC


def test_the_model_matches_the_document_immediately_after_undo(win):
    """No 300 ms divergence window: the reconciliation is synchronous."""
    tw = _open_table_silo(win, TABLE_DOC)
    _focus_view(tw)
    tw.model.setData(tw.model.index(1, 0), "FIRST",
                    Qt.ItemDataRole.EditRole)
    _commit(win, tw)

    _focus_view(tw)
    _press(Qt.KeyboardModifier.ControlModifier, Qt.Key.Key_Z)

    # The model must NOT retain the undone edit — this is the exact assertion
    # the old code failed inside the coalescing window.
    assert tw.model.data(tw.model.index(1, 0)) == "apple"
    assert "FIRST" not in win.text_area.toPlainText()


def test_an_edit_made_right_after_undo_is_not_dropped(win):
    """The T-1459 stale-source guard must not swallow the next real edit:
    inside the old 300 ms window the model was stale and the write refused,
    so the user's SECOND edit silently vanished."""
    tw = _open_table_silo(win, TABLE_DOC)
    _focus_view(tw)
    tw.model.setData(tw.model.index(1, 0), "FIRST",
                    Qt.ItemDataRole.EditRole)
    _commit(win, tw)

    _focus_view(tw)
    _press(Qt.KeyboardModifier.ControlModifier, Qt.Key.Key_Z)

    # Immediate re-edit in the same cell, no timer wait.
    tw.model.setData(tw.model.index(1, 0), "SECOND",
                    Qt.ItemDataRole.EditRole)
    _commit(win, tw)

    out = win.text_area.toPlainText()
    assert "SECOND" in out
    assert "FIRST" not in out
    assert "apple" not in out


def test_one_ctrl_z_undoes_exactly_one_step_not_two(win):
    """The grid emits `undoRequested` into `_smart_undo` and the window
    shortcut also routes there; the re-entry guard must keep it one step."""
    tw = _open_table_silo(win, TABLE_DOC)
    _focus_view(tw)
    tw.model.setData(tw.model.index(1, 0), "STEP1",
                    Qt.ItemDataRole.EditRole)
    _commit(win, tw)
    tw.model.setData(tw.model.index(1, 1), "STEP2",
                    Qt.ItemDataRole.EditRole)
    _commit(win, tw)
    assert "STEP1" in win.text_area.toPlainText()
    assert "STEP2" in win.text_area.toPlainText()

    _focus_view(tw)
    _press(Qt.KeyboardModifier.ControlModifier, Qt.Key.Key_Z)

    out = win.text_area.toPlainText()
    # Exactly one transaction reversed: STEP2 back to the original, STEP1 kept.
    assert "STEP2" not in out
    assert "STEP1" in out


def test_ctrl_y_redoes_the_undone_table_edit(win):
    tw = _open_table_silo(win, TABLE_DOC)
    _focus_view(tw)
    tw.model.setData(tw.model.index(1, 0), "REDO_ME",
                    Qt.ItemDataRole.EditRole)
    _commit(win, tw)

    _focus_view(tw)
    _press(Qt.KeyboardModifier.ControlModifier, Qt.Key.Key_Z)
    assert "REDO_ME" not in win.text_area.toPlainText()

    _focus_view(tw)
    _press(Qt.KeyboardModifier.ControlModifier, Qt.Key.Key_Y)

    assert "REDO_ME" in win.text_area.toPlainText()
    assert tw.model.data(tw.model.index(1, 0)) == "REDO_ME"


def test_ctrl_shift_z_also_redoes(win):
    tw = _open_table_silo(win, TABLE_DOC)
    _focus_view(tw)
    tw.model.setData(tw.model.index(1, 0), "SHIFTZ",
                    Qt.ItemDataRole.EditRole)
    _commit(win, tw)

    _focus_view(tw)
    _press(Qt.KeyboardModifier.ControlModifier, Qt.Key.Key_Z)
    assert "SHIFTZ" not in win.text_area.toPlainText()

    _focus_view(tw)
    _press(Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier,
           Qt.Key.Key_Z)

    assert "SHIFTZ" in win.text_area.toPlainText()


def test_redo_does_not_reopen_the_divergence_window(win):
    tw = _open_table_silo(win, TABLE_DOC)
    _focus_view(tw)
    tw.model.setData(tw.model.index(1, 0), "REDO2",
                    Qt.ItemDataRole.EditRole)
    _commit(win, tw)
    _focus_view(tw)
    _press(Qt.KeyboardModifier.ControlModifier, Qt.Key.Key_Z)
    _press(Qt.KeyboardModifier.ControlModifier, Qt.Key.Key_Y)

    assert tw.model.data(tw.model.index(1, 0)) == "REDO2"


# ---------------------------------------------------------------- delegate


def test_ctrl_z_while_a_delegate_edits_a_cell_still_undoes_the_table(win):
    """A delegate editor has focus inside the view; the window shortcut must
    still reach `_smart_undo` and revert the transaction."""
    tw = _open_table_silo(win, TABLE_DOC)
    _focus_view(tw)
    tw.model.setData(tw.model.index(1, 0), "DELEGATED",
                    Qt.ItemDataRole.EditRole)
    _commit(win, tw)
    assert "DELEGATED" in win.text_area.toPlainText()

    # Open a delegate editor on the cell, then fire the shortcut.
    tw.view.setCurrentIndex(tw.model.index(1, 0))
    _press(Qt.KeyboardModifier.ControlModifier, Qt.Key.Key_Z)

    out = win.text_area.toPlainText()
    assert "DELEGATED" not in out
    assert "apple" in out


# ------------------------------------------------------- pending 500 ms sync


def test_undo_with_a_pending_500ms_serialization_lands_one_step(win):
    """A cell edit still parked in the grid's 500 ms timer when Ctrl+Z fires
    must be the step that is reversed — and NOTHING else.

    The old version of this test accepted either outcome ("committed and then
    undone, or discarded") and asserted only that the document did not keep the
    new value. That passes for the wrong reason: without the flush the parked
    edit was never in the document, so Ctrl+Z reversed the transaction BELOW it
    — the earlier text edit — and the user's cell change simply vanished with
    the undo, which looks identical on this narrow assertion. These are the
    nine steps that tell the two apart.
    """
    tw = _open_table_silo(win, TABLE_DOC)
    _focus_view(tw)

    # 1. an EARLIER, unrelated text transaction (real keystrokes)
    win.text_area.setFocus()
    _APP.processEvents()
    cur = win.text_area.textCursor()
    cur.movePosition(QTextCursor.MoveOperation.End)
    win.text_area.setTextCursor(cur)
    QTest.keyClicks(win.text_area, "Unrelated note.")
    _APP.processEvents()
    QTest.qWait(400)          # let the 300 ms pane rebuild settle
    _APP.processEvents()
    with_note = win.text_area.toPlainText()
    assert with_note.endswith("Unrelated note.")
    assert tw._visual_source == with_note
    assert not tw._sync_timer.isActive()          # no grid edit yet

    # 2. a cell edit, left parked in the coalescing timer
    tw.model.setData(tw.model.index(1, 0), "PENDING",
                     Qt.ItemDataRole.EditRole)
    assert tw._sync_timer.isActive()

    # 3. Ctrl+Z BEFORE the 500 ms sync delay
    _focus_view(tw)
    _press(Qt.KeyboardModifier.ControlModifier, Qt.Key.Key_Z)

    # 4. only the LATEST action is reversed: the cell edit. The earlier
    #    transaction is intact — this is the assertion the old test lacked.
    out = win.text_area.toPlainText()
    assert "PENDING" not in out
    assert out == with_note
    assert "Unrelated note." in out
    assert tw.model.data(tw.model.index(1, 0)) == "apple"

    # 5. Ctrl+Y puts that same step back
    _focus_view(tw)
    _press(Qt.KeyboardModifier.ControlModifier, Qt.Key.Key_Y)
    assert "PENDING" in win.text_area.toPlainText()

    # 6. the model and the document agree, with no coalescing window left open
    assert tw.model.data(tw.model.index(1, 0)) == "PENDING"
    assert not tw._sync_timer.isActive()


def test_rapid_sequential_cell_edits_undo_as_one_coalesced_step(win):
    """Three edits inside one coalescing window are ONE write-back and ONE
    undo step — the same granularity the user sees for any 500 ms burst."""
    tw = _open_table_silo(win, TABLE_DOC)
    _focus_view(tw)
    for value in ("A1", "A2", "A3"):
        tw.model.setData(tw.model.index(1, 0), value,
                         Qt.ItemDataRole.EditRole)
    assert tw._sync_timer.isActive()

    _focus_view(tw)
    _press(Qt.KeyboardModifier.ControlModifier, Qt.Key.Key_Z)

    out = win.text_area.toPlainText()
    assert out == TABLE_DOC
    assert tw.model.data(tw.model.index(1, 0)) == "apple"

    _focus_view(tw)
    _press(Qt.KeyboardModifier.ControlModifier, Qt.Key.Key_Y)
    assert "A3" in win.text_area.toPlainText()
    assert tw.model.data(tw.model.index(1, 0)) == "A3"


def test_a_parked_edit_committed_by_a_silo_switch_still_undoes(win):
    """A silo switch flushes the outgoing grid (T-1459). The committed cell
    edit must still be the step Ctrl+Z reverses, back in the original silo."""
    tw = _open_table_silo(win, TABLE_DOC)
    _focus_view(tw)
    tw.model.setData(tw.model.index(1, 0), "SWITCHED",
                     Qt.ItemDataRole.EditRole)
    assert tw._sync_timer.isActive()

    win.data["temp_presets"][1] = "other silo prose\n"
    win.data["silo_types"]["1"] = "text"
    win._switch_to_slot(1, initial=True)
    _APP.processEvents()
    win._switch_to_slot(0, initial=True)
    _APP.processEvents()

    assert "SWITCHED" in win.text_area.toPlainText()
    tw2 = win.table_widget
    _focus_view(tw2)
    _press(Qt.KeyboardModifier.ControlModifier, Qt.Key.Key_Z)

    out = win.text_area.toPlainText()
    assert "SWITCHED" not in out
    assert out == TABLE_DOC
    assert tw2.model.data(tw2.model.index(1, 0)) == "apple"


def test_the_pending_timer_does_not_write_stale_content_after_undo(win):
    """Regression half of the 500 ms race: the queued `changed` from a
    pre-undo edit must never land after the undo and resurrect the old value."""
    tw = _open_table_silo(win, TABLE_DOC)
    _focus_view(tw)
    tw.model.setData(tw.model.index(1, 0), "GHOST",
                    Qt.ItemDataRole.EditRole)
    assert tw._sync_timer.isActive()

    _focus_view(tw)
    _press(Qt.KeyboardModifier.ControlModifier, Qt.Key.Key_Z)

    # Let the queued timer fire if it is still around.
    _APP.processEvents()
    QTest.qWait(700)
    _APP.processEvents()

    assert "GHOST" not in win.text_area.toPlainText()


# ----------------------------------------------------------- unrelated data


def test_undo_preserves_unrelated_document_text(win):
    doc = TABLE_DOC + "\nExtra paragraph after the table.\n"
    tw = _open_table_silo(win, doc)
    _focus_view(tw)
    tw.model.setData(tw.model.index(1, 0), "KEEPME",
                    Qt.ItemDataRole.EditRole)
    _commit(win, tw)

    _focus_view(tw)
    _press(Qt.KeyboardModifier.ControlModifier, Qt.Key.Key_Z)

    out = win.text_area.toPlainText()
    assert out == doc
    assert "Extra paragraph after the table." in out


def test_the_other_table_in_the_silo_is_untouched_by_undo(win):
    doc = (
        "| A | B |\n"
        "| --- | --- |\n"
        "| 1 | 2 |\n"
        "\n"
        "| C | D |\n"
        "| --- | --- |\n"
        "| 3 | 4 |\n"
    )
    tw = _open_table_silo(win, doc)
    _focus_view(tw)
    tw.model.setData(tw.model.index(1, 0), "EDITED",
                    Qt.ItemDataRole.EditRole)
    _commit(win, tw)

    _focus_view(tw)
    _press(Qt.KeyboardModifier.ControlModifier, Qt.Key.Key_Z)

    out = win.text_area.toPlainText()
    assert out == doc
    assert "| C | D |" in out and "| 3 | 4 |" in out


# -------------------------------------------------------------- no redo leak


def test_undo_without_a_table_edit_reaches_the_document_history(win):
    """Ctrl+Z in a table silo with no table edit must still undo whatever the
    document holds — the grid must not swallow the key."""
    tw = _open_table_silo(win, TABLE_DOC)
    _focus_view(tw)
    win.text_area.setPlainText("plain text, no table\n")
    _APP.processEvents()
    win.text_area.insertPlainText("MORE\n")
    _APP.processEvents()
    assert "MORE" in win.text_area.toPlainText()

    win.text_area.setFocus()
    _APP.processEvents()
    _press(Qt.KeyboardModifier.ControlModifier, Qt.Key.Key_Z, win.text_area)

    assert "MORE" not in win.text_area.toPlainText()


# --------------------------------------------------- real paste undo / redo (T-1464)


def test_real_paste_undo_redo_before_500ms_sync(win):
    """Stage 5: Real paste transaction undone before the 500 ms timer fires."""
    tw = _open_table_silo(win, TABLE_DOC)
    _focus_view(tw)

    # 1. Create an unrelated text transaction
    win.text_area.setFocus()
    _APP.processEvents()
    cur = win.text_area.textCursor()
    cur.movePosition(QTextCursor.MoveOperation.End)
    win.text_area.setTextCursor(cur)
    QTest.keyClicks(win.text_area, "Unrelated note.")
    _APP.processEvents()
    QTest.qWait(400)
    _APP.processEvents()
    with_note = win.text_area.toPlainText()
    assert with_note.endswith("Unrelated note.")

    # 2. Paste a rectangular cell range
    _focus_view(tw)
    tw.view.setCurrentIndex(tw.model.index(1, 0))
    paste_text = "orange\t7"
    from PyQt6.QtGui import QGuiApplication
    QGuiApplication.clipboard().setText(paste_text)
    tw.paste_cells()
    _APP.processEvents()
    assert tw.model.data(tw.model.index(1, 0)) == "orange"
    assert tw.model.data(tw.model.index(1, 1)) == "7"
    assert tw._sync_timer.isActive()

    # 3. Press Ctrl+Z with actual QTableView focus BEFORE 500 ms
    _focus_view(tw)
    _press(Qt.KeyboardModifier.ControlModifier, Qt.Key.Key_Z)

    # 4. Verify only the paste is undone
    out = win.text_area.toPlainText()
    assert "orange" not in out
    # 5. Verify the earlier text transaction remains
    assert "Unrelated note." in out
    assert out == with_note
    assert tw.model.data(tw.model.index(1, 0)) == "apple"

    # 6. Press Ctrl+Y
    _focus_view(tw)
    _press(Qt.KeyboardModifier.ControlModifier, Qt.Key.Key_Y)

    # 7. Verify the exact range is restored
    out_redone = win.text_area.toPlainText()
    assert "orange" in out_redone
    # 8. Confirm model/document agreement
    assert tw.model.data(tw.model.index(1, 0)) == "orange"
    assert tw.model.data(tw.model.index(1, 1)) == "7"

    # 9. Switch silos
    win.data["temp_presets"][1] = "other silo prose\n"
    win.data["silo_types"]["1"] = "text"
    win._switch_to_slot(1)
    _APP.processEvents()
    QTest.qWait(600)
    _APP.processEvents()

    # 10. Return
    win._switch_to_slot(0)
    _APP.processEvents()

    # 11. Verify no stale delayed write-back occurs
    assert "orange" in win.text_area.toPlainText()
    assert "Unrelated note." in win.text_area.toPlainText()
    tw_returned = win.table_widget
    assert tw_returned.model.data(tw_returned.model.index(1, 0)) == "orange"


def test_real_paste_undo_redo_after_500ms_sync(win):
    """Stage 5: Real paste transaction undone AFTER the 500 ms timer fires."""
    tw = _open_table_silo(win, TABLE_DOC)
    _focus_view(tw)

    # 1. Create an unrelated text transaction
    win.text_area.setFocus()
    _APP.processEvents()
    cur = win.text_area.textCursor()
    cur.movePosition(QTextCursor.MoveOperation.End)
    win.text_area.setTextCursor(cur)
    QTest.keyClicks(win.text_area, "Earlier text.")
    _APP.processEvents()
    QTest.qWait(400)
    _APP.processEvents()
    with_earlier = win.text_area.toPlainText()
    assert with_earlier.endswith("Earlier text.")

    # 2. Paste a rectangular cell range
    _focus_view(tw)
    tw.view.setCurrentIndex(tw.model.index(1, 0))
    from PyQt6.QtGui import QGuiApplication
    QGuiApplication.clipboard().setText("mango\t99")
    tw.paste_cells()
    _APP.processEvents()

    # Wait past the 500 ms synchronization timer
    QTest.qWait(600)
    _APP.processEvents()
    assert not tw._sync_timer.isActive()
    assert "mango" in win.text_area.toPlainText()

    # 3. Press Ctrl+Z with actual QTableView focus
    _focus_view(tw)
    _press(Qt.KeyboardModifier.ControlModifier, Qt.Key.Key_Z)

    # 4. Verify only the paste is undone
    out = win.text_area.toPlainText()
    assert "mango" not in out
    # 5. Verify the earlier text transaction remains
    assert "Earlier text." in out
    assert out == with_earlier
    assert tw.model.data(tw.model.index(1, 0)) == "apple"

    # 6. Press Ctrl+Y
    _focus_view(tw)
    _press(Qt.KeyboardModifier.ControlModifier, Qt.Key.Key_Y)

    # 7. Verify the exact range is restored
    assert "mango" in win.text_area.toPlainText()
    # 8. Confirm model/document agreement
    assert tw.model.data(tw.model.index(1, 0)) == "mango"
    assert tw.model.data(tw.model.index(1, 1)) == "99"

    # 9. Switch silos and 10. Return
    win.data["temp_presets"][1] = "other silo prose\n"
    win.data["silo_types"]["1"] = "text"
    win._switch_to_slot(1)
    _APP.processEvents()
    QTest.qWait(600)
    _APP.processEvents()
    win._switch_to_slot(0)
    _APP.processEvents()

    # 11. Verify no stale delayed write-back occurs
    assert "mango" in win.text_area.toPlainText()
    assert "Earlier text." in win.text_area.toPlainText()
    tw_returned = win.table_widget
    assert tw_returned.model.data(tw_returned.model.index(1, 0)) == "mango"
    assert tw_returned.model.data(tw_returned.model.index(1, 1)) == "99"


def test_real_paste_undo_redo_with_trailing_empty_cells(win):
    """Stage 5: Real paste with trailing empty selected cells undoes and redoes cleanly."""
    from fastprompter.ui import clipboard_tsv as codec
    tw = _open_table_silo(win, TABLE_DOC)
    _focus_view(tw)

    # Rectangular range with trailing empty cells
    grid = [["peach", ""], ["", ""]]
    tsv = codec.encode_grid(grid)

    from PyQt6.QtGui import QGuiApplication
    QGuiApplication.clipboard().setText(tsv)
    tw.view.setCurrentIndex(tw.model.index(1, 0))
    tw.paste_cells()
    _APP.processEvents()

    assert tw.model.data(tw.model.index(1, 0)) == "peach"
    assert tw.model.data(tw.model.index(1, 1)) == ""

    # Undo
    _focus_view(tw)
    _press(Qt.KeyboardModifier.ControlModifier, Qt.Key.Key_Z)
    assert tw.model.data(tw.model.index(1, 0)) == "apple"
    assert tw.model.data(tw.model.index(1, 1)) == "3"

    # Redo
    _focus_view(tw)
    _press(Qt.KeyboardModifier.ControlModifier, Qt.Key.Key_Y)
    assert tw.model.data(tw.model.index(1, 0)) == "peach"
    assert tw.model.data(tw.model.index(1, 1)) == ""

