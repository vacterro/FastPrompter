"""T-1462 Stage 5: table presentation persists apart from the Markdown.

The silo text owns CONTENT (what the cells say). The column widths and row
heights the user drags are LAYOUT — a separate concern that must survive a
reload, and must never be baked into the Markdown (the markdown is the source
of truth for content, and a presentation choice must not corrupt it).

The saved layout is keyed by the same silo identity that owns the document and
is verified against the table's shape on restore: a layout whose column count
no longer matches is refused, so inserting a column never distorts.
"""

import pytest
from PyQt6.QtWidgets import QApplication

import fastprompter.core.state as state_mod

_APP = QApplication.instance() or QApplication([])

TABLE = (
    "| Name | Qty | Note |\n"
    "| :--- | ---: | :---: |\n"
    "| apple | 3 | red |\n"
    "| pear | 12 | green |\n"
)


def _widget():
    from fastprompter.ui.table_grid import TableGridWidget
    w = TableGridWidget()
    w.load_markdown(TABLE)
    return w


# ------------------------------------------------------- capture / apply


def test_capture_returns_column_and_row_sizes():
    w = _widget()
    layout = w.capture_presentation()
    # T-1462 Stage 6 added the manual flags alongside the sizes: they say
    # WHICH of these sizes the user chose and must keep across a reload.
    assert {"cols", "rows", "manual_cols", "manual_rows"} <= set(layout)
    assert len(layout["cols"]) == w.model.columnCount() == 3
    assert len(layout["rows"]) == w.model.rowCount() == 3
    assert all(isinstance(x, int) and x > 0 for x in layout["cols"])
    assert all(isinstance(x, int) and x > 0 for x in layout["rows"])
    assert layout["manual_cols"] == [] and layout["manual_rows"] == []


def test_apply_restores_a_resized_column():
    w = _widget()
    hh = w.view.horizontalHeader()
    before = hh.sectionSize(0)
    hh.resizeSection(0, 220)
    layout = w.capture_presentation()

    # a fresh widget with default (autofit) widths
    w2 = _widget()
    assert w2.view.horizontalHeader().sectionSize(0) == before
    assert w2.apply_presentation(layout) is True
    assert w2.view.horizontalHeader().sectionSize(0) == 220


def test_apply_restores_a_resized_row():
    w = _widget()
    vh = w.view.verticalHeader()
    vh.resizeSection(1, 64)
    layout = w.capture_presentation()

    w2 = _widget()
    w2.apply_presentation(layout)
    assert w2.view.verticalHeader().sectionSize(1) == 64


def test_apply_refuses_a_layout_with_a_stale_column_count():
    """The user inserted a column since the layout was saved: refuse rather
    than stretch a width onto the wrong column."""
    w = _widget()
    w.model.insert_columns(2)  # 3 -> 4 columns
    layout = w.capture_presentation()
    assert len(layout["cols"]) == 4

    w2 = _widget()  # a fresh 3-column table, autofit widths
    autofit_width = w2.view.horizontalHeader().sectionSize(0)
    assert w2.apply_presentation(layout) is False
    # nothing was applied — the width is still the autofit one
    assert w2.view.horizontalHeader().sectionSize(0) == autofit_width
    assert w2.model.columnCount() == 3


def test_apply_refuses_garbage():
    w = _widget()
    assert w.apply_presentation(None) is False
    assert w.apply_presentation({}) is False
    assert w.apply_presentation({"cols": "nope", "rows": []}) is False
    assert w.apply_presentation({"cols": [10, 20, 30]}) is False  # no rows key


def test_apply_ignores_non_positive_sizes():
    w = _widget()
    layout = {"cols": [0, -5, 300], "rows": [10, 10, 10]}
    assert w.apply_presentation(layout) is True
    # the invalid entries are skipped, the valid one applied
    assert w.view.horizontalHeader().sectionSize(2) == 300


# ------------------------------------------------- persistence round trip


def test_presentation_survives_a_widget_rebuild():
    """The widget is re-created from the same document (a silo switch away
    and back); the presentation must come back with it."""
    w = _widget()
    hh = w.view.horizontalHeader()
    hh.resizeSection(0, 190)
    saved = w.capture_presentation()

    w2 = _widget()
    assert w2.apply_presentation(saved) is True
    assert w2.view.horizontalHeader().sectionSize(0) == 190


def test_presentation_is_not_written_into_the_markdown():
    """Layout is separate from content: the serialized markdown must be
    byte-identical whether or not a column was resized."""
    w = _widget()
    before = w.serialize()
    w.view.horizontalHeader().resizeSection(0, 250)
    after = w.serialize()
    assert before == after


# ------------------------------------------------------- window integration


@pytest.fixture(scope="module")
def win(tmp_path_factory):
    tmp_path = tmp_path_factory.mktemp("t1462pres")
    original_db_path = state_mod.get_db_path
    state_mod.get_db_path = (
        lambda profile_id=1: str(tmp_path / f"t1462p_{profile_id}.db"))
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


def test_presentation_is_captured_into_the_silo_state(win):
    tw = _open_table_silo(win, TABLE)
    assert tw is not None
    tw.view.horizontalHeader().resizeSection(0, 210)
    win.capture_silo_state()
    cat, key = win._silo_state_key()
    entry = win._silo_state_map().get(cat, {}).get(key, {})
    assert "table_presentation" in entry
    assert entry["table_presentation"]["cols"][0] == 210


def test_presentation_is_restored_on_silo_switch(win):
    """Switch away and back: the layout the user set must return."""
    tw = _open_table_silo(win, TABLE)
    tw.view.horizontalHeader().resizeSection(0, 175)
    win.capture_silo_state()

    # switch to a plain-text silo and back
    w_text = "just some prose\n"
    win.data["temp_presets"][1] = w_text
    win.data["silo_types"]["1"] = "text"
    win._switch_to_slot(1, initial=True)
    _APP.processEvents()

    win._switch_to_slot(0, initial=True)
    _APP.processEvents()
    tw2 = win.table_widget
    assert tw2 is not None
    assert tw2.view.horizontalHeader().sectionSize(0) == 175


def test_a_layout_from_a_different_table_shape_is_refused(win):
    """Capture on a 3-column table, then the document gains a column: the
    restore must refuse, not misalign."""
    tw = _open_table_silo(win, TABLE)
    tw.view.horizontalHeader().resizeSection(0, 200)
    win.capture_silo_state()

    # same silo identity, but the table now has 4 columns
    bigger = (
        "| Name | Qty | Note | Extra |\n"
        "| :--- | ---: | :---: | --- |\n"
        "| apple | 3 | red | x |\n"
        "| pear | 12 | green | y |\n"
    )
    win.data["temp_presets"][0] = bigger
    win._switch_to_slot(0, initial=True)
    _APP.processEvents()

    tw2 = win.table_widget
    assert tw2 is not None
    # refused: the 3-column layout was not forced onto the 4-column table.
    # T-1462 Stage 6 sharpens the outcome: the user's own manual width for
    # column 0 — the same column before and after the change — survives the
    # switch instead of being swallowed by a blanket autofit.
    assert tw2.model.columnCount() == 4
    assert tw2._manual_cols == {0}
    assert tw2.view.horizontalHeader().sectionSize(0) == 200
