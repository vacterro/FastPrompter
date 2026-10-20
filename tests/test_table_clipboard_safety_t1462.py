"""T-1462 Stage 4: clipboard safety and keyboard ownership.

Two defects:
1. `paste_tsv` grew the table without bound — a 100k x 100k clipboard would
   OOM the process. A hard ceiling refuses the paste cleanly.
2. The grid's Ctrl+C/X/V must reach the grid's clipboard ops (not the window's
   text copy) when the grid has focus, and Ctrl+Z/Y must route to the single
   smart-undo owner (not a second stack).
"""

from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

_APP = QApplication.instance() or QApplication([])

TABLE = (
    "| Name | Qty |\n"
    "| :--- | ---: |\n"
    "| apple | 3 |\n"
    "| pear | 12 |\n"
)


def _model():
    from fastprompter.ui.table_model import TableCellsModel
    m = TableCellsModel()
    m.load_markdown(TABLE)
    return m


# --------------------------------------------------------------- paste budget


def test_paste_within_budget_grows_the_table():
    m = _model()
    rows, cols = m.paste_tsv(1, 0, "x\ty\nz\tw")
    assert (rows, cols) == (2, 2)
    assert m.rows[1][:2] == ["x", "y"]
    assert m.rows[2][:2] == ["z", "w"]


def test_paste_exceeding_row_budget_is_refused_entirely():
    m = _model()
    before = [list(r) for r in m.rows]
    payload = "\n".join(f"r{i}" for i in range(m._PASTE_MAX_ROWS + 1))
    rows, cols = m.paste_tsv(1, 0, payload)
    assert (rows, cols) == (0, 0)
    # nothing grew, nothing was written
    assert m.rows == before
    assert m.rowCount() == 3


def test_paste_exceeding_column_budget_is_refused_entirely():
    m = _model()
    before = [list(r) for r in m.rows]
    payload = "\t".join(f"c{i}" for i in range(m._PASTE_MAX_COLS + 1))
    rows, cols = m.paste_tsv(1, 0, payload)
    assert (rows, cols) == (0, 0)
    assert m.rows == before
    assert m.columnCount() == 2


def test_paste_at_the_budget_boundary_is_accepted():
    m = _model()
    payload = "\n".join(f"r{i}" for i in range(m._PASTE_MAX_ROWS))
    rows, cols = m.paste_tsv(1, 0, payload)
    assert rows == m._PASTE_MAX_ROWS
    assert m.rowCount() == 1 + m._PASTE_MAX_ROWS


def test_a_refused_paste_emits_no_data_changed_signal():
    m = _model()
    events = []
    m.dataChanged.connect(lambda *a: events.append(a))
    payload = "\n".join(f"r{i}" for i in range(m._PASTE_MAX_ROWS + 1))
    m.paste_tsv(1, 0, payload)
    assert events == []


def test_empty_and_whitespace_pastes_are_noops():
    m = _model()
    assert m.paste_tsv(1, 0, "") == (0, 0)
    assert m.paste_tsv(1, 0, "\n\n\n") == (0, 0)
    assert m.rowCount() == 3


# ------------------------------------------------------- keyboard ownership


def _grid(text=TABLE):
    from fastprompter.ui.table_grid import TableGridWidget
    g = TableGridWidget()
    g.load_markdown(text)
    return g


def test_ctrl_c_from_the_grid_copies_the_selection_as_tsv():
    g = _grid()
    sm = g.view.selectionModel()
    for r, c in ((1, 0), (1, 1)):
        sm.select(g.model.index(r, c), sm.SelectionFlag.Select)
    g.view.setFocus()
    _APP.processEvents()
    QTest.keyClick(g.view, Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier)
    _APP.processEvents()
    assert QApplication.clipboard().text() == "apple\t3"


def test_ctrl_x_cuts_the_selection():
    g = _grid()
    sm = g.view.selectionModel()
    for r, c in ((1, 0), (1, 1)):
        sm.select(g.model.index(r, c), sm.SelectionFlag.Select)
    g.view.setFocus()
    _APP.processEvents()
    QTest.keyClick(g.view, Qt.Key.Key_X, Qt.KeyboardModifier.ControlModifier)
    _APP.processEvents()
    assert g.model.rows[1][0] == "" and g.model.rows[1][1] == ""
    # the row still exists
    assert g.model.rowCount() == 3


def test_ctrl_v_pastes_tsv_into_the_grid():
    g = _grid()
    QApplication.clipboard().setText("A\tB\nC\tD")
    g.view.setCurrentIndex(g.model.index(1, 0))
    g.view.setFocus()
    _APP.processEvents()
    QTest.keyClick(g.view, Qt.Key.Key_V, Qt.KeyboardModifier.ControlModifier)
    _APP.processEvents()
    assert g.model.rows[1][:2] == ["A", "B"]
    assert g.model.rows[2][:2] == ["C", "D"]


def test_ctrl_a_selects_all_cells():
    g = _grid()
    g.view.setFocus()
    _APP.processEvents()
    QTest.keyClick(g.view, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
    _APP.processEvents()
    sel = g.view.selectionModel().selectedIndexes()
    assert len(sel) == g.model.rowCount() * g.model.columnCount()


def test_ctrl_z_emits_undo_not_a_second_undo_stack():
    """The grid must ask the window's smart undo, not run its own history."""
    g = _grid()
    fired = []
    g.undoRequested.connect(lambda: fired.append("undo"))
    g.redoRequested.connect(lambda: fired.append("redo"))
    g.view.setFocus()
    _APP.processEvents()
    QTest.keyClick(g.view, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
    _APP.processEvents()
    assert fired == ["undo"]


def test_ctrl_y_emits_redo():
    g = _grid()
    fired = []
    g.undoRequested.connect(lambda: fired.append("undo"))
    g.redoRequested.connect(lambda: fired.append("redo"))
    g.view.setFocus()
    _APP.processEvents()
    QTest.keyClick(g.view, Qt.Key.Key_Y, Qt.KeyboardModifier.ControlModifier)
    _APP.processEvents()
    assert fired == ["redo"]


def test_ctrl_shift_z_emits_redo():
    g = _grid()
    fired = []
    g.undoRequested.connect(lambda: fired.append("undo"))
    g.redoRequested.connect(lambda: fired.append("redo"))
    g.view.setFocus()
    _APP.processEvents()
    QTest.keyClick(g.view, Qt.Key.Key_Z,
                   Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier)
    _APP.processEvents()
    assert fired == ["redo"]


def test_ctrl_z_without_shift_emits_undo_not_redo():
    g = _grid()
    fired = []
    g.undoRequested.connect(lambda: fired.append("undo"))
    g.redoRequested.connect(lambda: fired.append("redo"))
    g.view.setFocus()
    _APP.processEvents()
    QTest.keyClick(g.view, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
    _APP.processEvents()
    assert "redo" not in fired
