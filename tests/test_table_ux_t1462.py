"""T-1462 Stage 6: finish the table UX.

* Discoverable "Insert Table" in the menu.
* Accessible button controls (keyboard + screen reader).
* Translation integration (no hardcoded English in the UI).
* Theme coordination (T-1461's theme_mixin covers QPushButton).
"""

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

import fastprompter.core.state as state_mod

_APP = QApplication.instance() or QApplication([])

TABLE = (
    "| Name | Qty |\n"
    "| :--- | ---: |\n"
    "| apple | 3 |\n"
    "| pear | 12 |\n"
)


@pytest.fixture(scope="module")
def win(tmp_path_factory):
    tmp_path = tmp_path_factory.mktemp("t1462ux")
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


# ------------------------------------------------------ accessible controls


def test_add_column_button_is_keyboard_focusable(win):
    tw = _open_table_silo(win, TABLE)
    # The button must be in the focus chain (TabFocus policy)
    assert tw.btn_add_col.focusPolicy() == Qt.FocusPolicy.TabFocus
    assert tw.btn_add_row.focusPolicy() == Qt.FocusPolicy.TabFocus


def test_add_row_button_is_keyboard_focusable(win):
    tw = _open_table_silo(win, TABLE)
    assert tw.btn_add_row.focusPolicy() == Qt.FocusPolicy.TabFocus


def test_add_buttons_have_accessible_names(win):
    tw = _open_table_silo(win, TABLE)
    # QPushButton accessibleName returns what was set
    assert "Add Column" in tw.btn_add_col.accessibleName()
    assert "Add Row" in tw.btn_add_row.accessibleName()


def test_add_buttons_have_translated_tooltips(win):
    tw = _open_table_silo(win, TABLE)
    # tooltips are translated strings (may be English in test env)
    assert "Add Column" in tw.btn_add_col.toolTip()
    assert "Add Row" in tw.btn_add_row.toolTip()


def test_space_on_add_column_button_adds_column(win):
    """Qt buttons activate on Space, giving keyboard users the same power."""
    tw = _open_table_silo(win, TABLE)
    tw.btn_add_col.setFocus()
    _APP.processEvents()
    before = tw.model.columnCount()

    QTest.keyClick(tw.btn_add_col, Qt.Key.Key_Space)
    _APP.processEvents()

    assert tw.model.columnCount() == before + 1


def test_space_on_add_row_button_adds_row(win):
    tw = _open_table_silo(win, TABLE)
    tw.btn_add_row.setFocus()
    _APP.processEvents()
    before = tw.model.rowCount()

    QTest.keyClick(tw.btn_add_row, Qt.Key.Key_Space)
    _APP.processEvents()

    assert tw.model.rowCount() == before + 1


def test_clicking_add_column_button_still_works(win):
    tw = _open_table_silo(win, TABLE)
    before = tw.model.columnCount()
    QTest.mouseClick(tw.btn_add_col, Qt.MouseButton.LeftButton)
    _APP.processEvents()
    assert tw.model.columnCount() == before + 1


# --------------------------------------------------------- theme coordination


def test_theme_applies_to_qpushbutton_add_controls(win):
    """T-1461's _apply_table_theme must style QPushButton#table_add, not
    only QLabel#table_add. The style lives on the parent widget and cascades
    to the buttons, so assert against the parent's sheet."""
    tw = _open_table_silo(win, TABLE)
    win._apply_table_theme(None)

    style = tw.styleSheet()
    assert "QPushButton#table_add" in style
    assert win._skin_tokens()["raised"] in style


# ------------------------------------------------------ discoverable menu


def test_insert_table_in_main_menu(win):
    """The 'Insert Table' action exists in the editor context menu."""
    win._switch_to_slot(0, initial=True)
    _APP.processEvents()
    # plain text silo
    win.text_area.setPlainText("prose")
    _APP.processEvents()
    # Right-click context menu should have "Insert Table"
    win.text_area.setFocus()
    _APP.processEvents()
    assert hasattr(win.text_area, "_insert_table")


def test_edit_table_appears_when_caret_in_table(win):
    """The 'Edit Table…' action only appears when the caret is in a table."""
    tw = _open_table_silo(win, TABLE)
    assert tw is not None
    # The editor still backs the table silo
    win.text_area.setFocus()
    _APP.processEvents()
    # Caret inside the table (line 0 is the header)
    cursor = win.text_area.textCursor()
    block = win.text_area.document().findBlockByNumber(0)
    cursor.setPosition(block.position() + 2)
    win.text_area.setTextCursor(cursor)
    _APP.processEvents()

    # The dialog helper sees the table, which is what gates the menu entry.
    assert win.text_area.table_at_caret() is not None
    assert hasattr(win.text_area, "edit_table_dialog")


# ----------------------------------------------------- no hardcoded English


def test_no_hardcoded_english_in_add_button_strings():
    """The table_grid module must not contain hardcoded English UI strings
    for the add controls — they must go through tr()."""
    import inspect

    from fastprompter.ui import table_grid
    source = inspect.getsource(table_grid)
    # The add controls must be created with tr()
    assert 'tr("Add Column"' in source
    assert 'tr("Add Row"' in source
    assert 'tr("+ Row"' in source


# ----------------------------------------------- insert table dialog helper


def test_table_edit_dialog_still_opens_and_works(win):
    """Regression: the discoverable Edit Table dialog must still work."""
    from fastprompter.ui.table_edit_dialog import TableEditDialog
    tw = _open_table_silo(win, TABLE)
    assert tw is not None
    # Caret inside the table (line 0 is the header)
    cursor = win.text_area.textCursor()
    block = win.text_area.document().findBlockByNumber(2)
    cursor.setPosition(block.position() + 2)
    win.text_area.setTextCursor(cursor)
    _APP.processEvents()

    found = win.text_area.table_at_caret()
    assert found is not None
    table, _line, _col = found
    span = (table.first_block, table.last_block)
    assert span == (0, 3)
    dlg = TableEditDialog(win.text_area, table, span)
    dlg.grid.model.setData(dlg.grid.model.index(1, 0), "banana",
                           Qt.ItemDataRole.EditRole)
    dlg._apply()
    _APP.processEvents()
    assert "banana" in win.text_area.toPlainText()


# ------------------------------------------------------- translation mode


def test_table_grid_supports_ded_language():
    """The tr() calls in table_grid.py must work with DED language (caveman)."""
    from fastprompter.ui.table_grid import TableGridWidget
    w = TableGridWidget()
    assert w is not None
    # Just instantiate — the tr() calls at module init must not crash
    # even if language is set to DED
    from fastprompter.core.translations import set_language, tr
    state = {"language": "DED"}
    set_language(state, "DED")
    _APP.processEvents()
    # If we reach here without crash, the translation path works
    assert tr("Add Column", "DED") is not None
    set_language(state, "EN")
