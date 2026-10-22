"""T-1462 Stage 2: dynamic table-span ownership.

A table widget records the whole-line region it owns when it loads. That
record goes STALE the moment a structural edit changes how many lines the
table occupies: the user adds a row, the table is now one line taller, but the
widget still carries the range it captured at load. The next write-back then
slices the rendered table against the OLD range and silently drops the last
row — or duplicates it.

The fix is ownership that follows the table: a stable identity, a revision
counter, and one place (`note_write_back`) where the caller tells the widget
what it actually wrote. A widget that owns a region never falls back to
replacing the whole document.

These run on a REAL FastPrompter window with a REAL QTextEdit, because the
defect only exists where the widget's cached range meets the live document.
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
)


@pytest.fixture(scope="module")
def win(tmp_path_factory):
    tmp_path = tmp_path_factory.mktemp("t1462own")
    original_db_path = state_mod.get_db_path
    state_mod.get_db_path = (
        lambda profile_id=1: str(tmp_path / f"t1462o_{profile_id}.db"))
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


def _flush(w, tw):
    """One write-back cycle, exactly as the coalescing timer would deliver."""
    w._on_visual_widget_changed(tw.serialize(), tw)
    _APP.processEvents()


# ---- A: identity ---------------------------------------------------------

def test_a_identity_is_stable_and_unique(win):
    tw = _open_table_silo(win, DOC)
    first = tw.identity()
    assert first is not None
    tw.cells[1][0].setText("x")
    _flush(win, tw)
    assert tw.identity() == first, "identity survives an edit"

    tw2 = _open_table_silo(win, DOC, slot=1)
    assert tw2 is not None
    assert tw2.identity() != first, "two widgets never share an identity"


# ---- B: revision ---------------------------------------------------------

def test_b_revision_counts_landed_writes(win):
    tw = _open_table_silo(win, DOC)
    assert tw.revision() == 0
    tw.cells[1][0].setText("a")
    _flush(win, tw)
    assert tw.revision() == 1
    tw.cells[1][1].setText("9")
    _flush(win, tw)
    assert tw.revision() == 2


# ---- C: note_write_back --------------------------------------------------

def test_c_note_write_back_rederives_the_span(win):
    tw = _open_table_silo(win, DOC)
    assert tw._visual_span == (4, 6)
    tw._add_row()                     # table is now 4 lines, not 3
    _flush(win, tw)
    # the caller told the widget what it wrote: span grew by exactly one line
    assert tw._visual_span == (4, 7)


# ---- D: the drop-the-last-row defect ------------------------------------

def test_d_two_sequential_row_adds_both_survive(win):
    """The Stage 2 defect: without a span refresh the SECOND add slices the
    rendered table against the stale 3-line range and drops the new row."""
    tw = _open_table_silo(win, DOC)
    tw._add_row()
    _flush(win, tw)
    # Ownership followed the table: 3 lines -> 4, and one landed write.
    assert tw._visual_span == (4, 7), tw._visual_span
    assert tw.revision() == 1
    tw._add_row()
    _flush(win, tw)
    assert tw._visual_span == (4, 8), tw._visual_span
    assert tw.revision() == 2
    out = win.text_area.toPlainText()
    # header + two body rows + two added = 5 table lines
    from fastprompter.ui import silo_table as st
    lines = out.split("\n")
    table = st.parse(lines, 4)
    assert table is not None
    assert table.last_block - table.first_block + 1 == 5, out
    assert "Notes above." in out and "Footer." in out


# ---- E: columns ----------------------------------------------------------

def test_e_two_sequential_column_adds_both_survive(win):
    tw = _open_table_silo(win, DOC)
    tw._add_column()
    _flush(win, tw)
    # A column does not change the line count, but it IS a landed write.
    assert tw._visual_span == (4, 6), tw._visual_span
    assert tw.revision() == 1
    tw._add_column()
    _flush(win, tw)
    assert tw.revision() == 2
    out = win.text_area.toPlainText()
    from fastprompter.ui import silo_table as st
    table = st.parse(out.split("\n"), 4)
    assert table is not None
    assert len(table.aligns) == 4, out


# ---- F: add then delete --------------------------------------------------

def test_f_an_add_then_a_delete_stays_consistent(win):
    tw = _open_table_silo(win, DOC)
    tw._add_row()
    _flush(win, tw)
    assert tw._visual_span == (4, 7), tw._visual_span
    assert tw.revision() == 1
    # delete the row we just added (last one)
    last = len(tw.model.rows) - 1
    assert tw.delete_row((last, 0)) is True
    _flush(win, tw)
    # Ownership shrank back with the table: two landed writes, span back to 3.
    assert tw._visual_span == (4, 6), tw._visual_span
    assert tw.revision() == 2
    out = win.text_area.toPlainText()
    from fastprompter.ui import silo_table as st
    table = st.parse(out.split("\n"), 4)
    assert table is not None
    assert table.last_block - table.first_block + 1 == 3, out


# ---- G: a refused write changes nothing ---------------------------------

def test_g_a_stale_write_leaves_identity_and_revision_untouched(win):
    tw = _open_table_silo(win, DOC)
    before_id = tw.identity()
    # the document moves under the widget
    cur = win.text_area.textCursor()
    cur.movePosition(cur.MoveOperation.End)
    win.text_area.setTextCursor(cur)
    win.text_area.insertPlainText("ADDED\n")
    _APP.processEvents()
    snapshot = win.text_area.toPlainText()

    win._on_visual_widget_changed(tw.serialize(), tw)
    _APP.processEvents()
    assert win.text_area.toPlainText() == snapshot
    assert tw.identity() == before_id
    assert tw.revision() == 0, "a refused write is not a revision"


# ---- H: no whole-document fallback --------------------------------------

def test_h_a_region_owning_widget_never_replaces_the_whole_document(win):
    """The old fallback selected the ENTIRE document and inserted a rebuilt
    copy, so one refusal threw away every concurrent edit."""
    tw = _open_table_silo(win, DOC)
    # force the refusal path: a span the live document cannot honour
    tw._visual_span = (400, 402)
    marker = win.text_area.toPlainText()
    win._on_visual_widget_changed(tw.serialize(), tw)
    _APP.processEvents()
    assert win.text_area.toPlainText() == marker


# ---- I: source tracking --------------------------------------------------

def test_i_a_landed_write_updates_the_widget_source(win):
    tw = _open_table_silo(win, DOC)
    tw.cells[1][0].setText("banana")
    _flush(win, tw)
    assert tw._visual_source == win.text_area.toPlainText()


# ---- J: two tables -------------------------------------------------------

def test_j_the_owned_table_moves_and_the_other_does_not(win):
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
    assert tw._visual_span == (2, 4)
    tw._add_row()
    _flush(win, tw)
    # The owned table moved; the other table and the prose did not.
    assert tw._visual_span == (2, 5), tw._visual_span
    assert tw.revision() == 1
    tw._add_row()
    _flush(win, tw)
    assert tw._visual_span == (2, 6), tw._visual_span
    assert tw.revision() == 2
    out = win.text_area.toPlainText()
    assert "| X | Y |" in out and "| 7 | 8 |" in out
    assert "More prose." in out and out.startswith("Prose.")
    from fastprompter.ui import silo_table as st
    first = st.parse(out.split("\n"), 2)
    assert first.last_block - first.first_block + 1 == 5


# ---- K: sustained growth -------------------------------------------------

def test_k_sustained_growth_never_drops_a_row(win):
    tw = _open_table_silo(win, DOC)
    for _ in range(10):
        tw._add_row()
        _flush(win, tw)
    out = win.text_area.toPlainText()
    from fastprompter.ui import silo_table as st
    table = st.parse(out.split("\n"), 4)
    assert table is not None
    assert table.last_block - table.first_block + 1 == 13, out
    assert tw.revision() == 10
    assert "Footer." in out
