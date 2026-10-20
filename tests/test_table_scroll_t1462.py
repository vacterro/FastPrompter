"""T-1462 Stage 7: scroll and viewport regressions.

The table grid is a QTableView inside a QStackedWidget. When the table is
rebuilt (undo, cell edit, silo switch), the scroll position must survive —
otherwise the user loses their place in a large table.
"""

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

import fastprompter.core.state as state_mod

_APP = QApplication.instance() or QApplication([])

BIG_TABLE = "| A | B |\n| --- | --- |\n" + "\n".join(
    f"| row{i} | val{i} |" for i in range(50)
) + "\n"


@pytest.fixture(scope="module")
def win(tmp_path_factory):
    tmp_path = tmp_path_factory.mktemp("t1462scroll")
    original_db_path = state_mod.get_db_path
    state_mod.get_db_path = (
        lambda profile_id=1: str(tmp_path / f"t1462s_{profile_id}.db"))
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


def test_scroll_position_survives_a_cell_edit(win):
    """Editing a cell must not reset the scroll position."""
    tw = _open_table_silo(win, BIG_TABLE)
    assert tw is not None

    # Scroll down
    scrollbar = tw.view.verticalScrollBar()
    scrollbar.setValue(200)
    _APP.processEvents()
    pos_before = scrollbar.value()
    assert pos_before > 0

    # Edit a cell
    tw.model.setData(tw.model.index(1, 0), "EDITED",
                    Qt.ItemDataRole.EditRole)
    win._on_visual_widget_changed(tw.serialize(), tw)
    _APP.processEvents()

    # Scroll position should be preserved (or at least not reset to 0)
    assert scrollbar.value() == pos_before


def test_scroll_position_survives_undo(win):
    """Ctrl+Z must not reset the scroll position."""
    tw = _open_table_silo(win, BIG_TABLE)
    assert tw is not None

    scrollbar = tw.view.verticalScrollBar()
    scrollbar.setValue(200)
    _APP.processEvents()
    pos_before = scrollbar.value()

    # Edit + undo
    tw.model.setData(tw.model.index(1, 0), "TEMP",
                    Qt.ItemDataRole.EditRole)
    win._on_visual_widget_changed(tw.serialize(), tw)
    _APP.processEvents()

    tw.view.setFocus()
    _APP.processEvents()
    QTest.keyClick(tw.view, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
    _APP.processEvents()

    # Scroll should be preserved
    assert scrollbar.value() == pos_before


def test_scroll_position_survives_silo_switch(win):
    """Switching away and back must restore the scroll position."""
    tw = _open_table_silo(win, BIG_TABLE)
    assert tw is not None

    scrollbar = tw.view.verticalScrollBar()
    scrollbar.setValue(200)
    _APP.processEvents()
    pos_before = scrollbar.value()

    # Switch to a text silo and back
    win.data["temp_presets"][1] = "prose"
    win.data["silo_types"]["1"] = "text"
    win._switch_to_slot(1, initial=True)
    _APP.processEvents()

    win._switch_to_slot(0, initial=True)
    _APP.processEvents()

    tw2 = win.table_widget
    assert tw2 is not None
    # The scroll position is restored exactly, not merely non-zero.
    assert tw2.view.verticalScrollBar().value() == pos_before


def test_viewport_updates_after_model_change(win):
    """The viewport must repaint after a model change."""
    tw = _open_table_silo(win, BIG_TABLE)
    assert tw is not None

    # This should not crash
    tw.model.setData(tw.model.index(1, 0, ), "NEW",
                    Qt.ItemDataRole.EditRole)
    _APP.processEvents()
    # Force a repaint
    tw.view.viewport().update()
    _APP.processEvents()


def test_horizontal_scroll_survives_rebuild(win):
    """Horizontal scroll position must survive a rebuild."""
    tw = _open_table_silo(win, BIG_TABLE)
    assert tw is not None

    hscroll = tw.view.horizontalScrollBar()
    hscroll.setValue(50)
    _APP.processEvents()
    pos_before = hscroll.value()

    # Trigger a rebuild via cell edit
    tw.model.setData(tw.model.index(1, 0), "X",
                    Qt.ItemDataRole.EditRole)
    win._on_visual_widget_changed(tw.serialize(), tw)
    _APP.processEvents()

    assert hscroll.value() == pos_before
