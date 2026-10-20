"""T-1462: the table widget's write-back replaces only its own region.

Proven on a REAL FastPrompter window with a REAL QTextEdit, because the
defect is an integration defect: `serialize()` always produced correct text;
what consumed the silo was the whole-document selection it was written into.

The pre-existing subprocess contracts (test_silo_home.py) assert cursor and
scrollbar numbers. These assert what a stale or mis-scoped write actually
costs: unrelated paragraphs, other tables, fenced code.
"""

import pytest
from PyQt6.QtWidgets import QApplication

import fastprompter.core.state as state_mod

_APP = QApplication.instance() or QApplication([])

DOC = (
    "# Title\n"
    "\n"
    "Notes above.\n"
    "\n"
    "| Name | Qty |\n"
    "| :--- | ---: |\n"
    "| apple | 3 |\n"
    "\n"
    "Footer.\n"
    "\n"
    "| C | D |\n"
    "| --- | --- |\n"
    "| 3 | 4 |\n"
)


@pytest.fixture(scope="module")
def win(tmp_path_factory):
    tmp_path = tmp_path_factory.mktemp("t1462writeback")
    original_db_path = state_mod.get_db_path
    state_mod.get_db_path = (
        lambda profile_id=1: str(tmp_path / f"t1462w_{profile_id}.db"))
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


def test_a_cell_edit_writes_back_into_the_region_only(win):
    tw = _open_table_silo(win, DOC)
    assert tw is not None
    assert tw._visual_span == (4, 6)
    tw.cells[1][0].setText("pear")
    new_text = tw.serialize()
    win._on_visual_widget_changed(new_text, tw)
    _APP.processEvents()
    out = win.text_area.toPlainText()

    assert "| pear |" in out
    assert "Notes above." in out
    assert "Footer." in out
    assert out.startswith("# Title")
    # the OTHER table in the same silo is untouched, exactly once
    assert "| C | D |" in out and "| 3 | 4 |" in out
    assert out.count("| C | D |") == 1
    # and one undo restores the whole silo, table included
    win.text_area.undo()
    _APP.processEvents()
    assert win.text_area.toPlainText() == DOC


def test_a_stale_write_is_refused_not_applied(win):
    """Text changed after the load: the cached region must not overwrite it."""
    tw = _open_table_silo(win, DOC)
    cursor = win.text_area.textCursor()
    cursor.movePosition(cursor.MoveOperation.End)
    win.text_area.setTextCursor(cursor)
    win.text_area.insertPlainText("\nADDED_BY_HAND\n")
    _APP.processEvents()
    before = win.text_area.toPlainText()
    assert "ADDED_BY_HAND" in before

    # the widget's cached document no longer matches the live one
    assert tw._visual_source != before
    win._on_visual_widget_changed(tw.serialize(), tw)
    _APP.processEvents()

    assert win.text_area.toPlainText() == before


def test_a_foreign_widget_cannot_write_into_the_active_silo(win):
    """A queued edit from the kanban widget must not touch the table silo."""
    _open_table_silo(win, DOC)
    before = win.text_area.toPlainText()
    foreign = getattr(win, "kanban_widget", None)
    win._on_visual_widget_changed("not the live silo at all", foreign)
    _APP.processEvents()
    assert win.text_area.toPlainText() == before


def test_the_first_table_is_not_rewritten_when_another_is_selected(win):
    """Two tables: the widget owns ONE span, so the other never moves."""
    two = (
        "Prose.\n"
        "\n"
        "| A | B |\n"
        "| --- | --- |\n"
        "| 1 | 2 |\n"
        "\n"
        "More prose.\n"
        "\n"
        "| X | Y |\n"
        "| --- | --- |\n"
        "| 7 | 8 |\n"
    )
    tw = _open_table_silo(win, two)
    assert tw is not None
    assert tw._visual_span == (2, 4)
    tw.cells[1][0].setText("changed")
    win._on_visual_widget_changed(tw.serialize(), tw)
    _APP.processEvents()
    out = win.text_area.toPlainText()
    # the second table lines are byte-identical, and the prose survived
    assert "| X | Y |" in out and "| 7 | 8 |" in out
    assert "More prose." in out and out.startswith("Prose.")


def test_a_backslash_pipe_cell_survives_the_visual_round_trip(win):
    """The T-1462 P1 defect, proven through the real widget this time.

    Markdown `x\\|y` is a cell whose logical value is `x|y`: the escaped pipe
    is CONTENT. Before the parity fix, escape() turned that value into
    `x\\\\|y` — an even backslash run, which split_row then reads as a
    delimiter, so the cell came back as two columns.
    """
    doc = (
        "| cmd | note |\n"
        "| --- | --- |\n"
        r"| x\|y | plain |"
    )
    tw = _open_table_silo(win, doc)
    assert tw is not None
    assert len(tw.cells[1]) == 2, "the escaped pipe must stay content"
    assert tw.cells[1][0].text() == "x|y"

    # save it back unchanged
    win._on_visual_widget_changed(tw.serialize(), tw)
    _APP.processEvents()
    out = win.text_area.toPlainText()

    from fastprompter.ui import silo_table as st
    lines = out.split("\n")
    idx = next(i for i, line in enumerate(lines)
               if "y" in line and "|" in line and "plain" in line)
    assert len(st.split_row(lines[idx])) == 2, lines[idx]
    assert st.unescape(st.split_row(lines[idx])[0]) == "x|y"
    # and re-loading it gives the same two-column cell back
    tw2 = _open_table_silo(win, out)
    assert tw2 is not None
    assert tw2.cells[1][0].text() == "x|y"
    assert len(tw2.cells[1]) == 2
