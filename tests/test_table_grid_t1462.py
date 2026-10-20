"""T-1462 Stage 3: the interactive table grid is a real QTableView.

The old grid was a QGridLayout of QLineEdits: no rectangular selection, no
column resizing, no range clipboard, no drag-select. Every one of those is
now Qt's, so these tests exercise the MODEL/VIEW behaviours directly — the
selection model, the header, the clipboard roles, the shape commands and the
round trip through the document — rather than the old per-cell widget API.

No formulas, macros or spreadsheet engine: a cell is text, and the markdown is
the source of truth.
"""

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication

_APP = QApplication.instance() or QApplication([])

TABLE = (
    "| Name | Qty | Note |\n"
    "| :--- | ---: | :---: |\n"
    "| apple | 3 | red |\n"
    "| pear | 12 | green |\n"
)


def _grid(text=TABLE):
    from fastprompter.ui.table_widget import TableGridWidget
    g = TableGridWidget()
    g.load_markdown(text)
    return g


# --------------------------------------------------------------- model/view

def test_it_is_a_qtableview_over_a_model():
    from PyQt6.QtWidgets import QTableView
    g = _grid()
    assert isinstance(g.view, QTableView)
    assert g.view.model() is g.model
    assert g.model.rowCount() == 3
    assert g.model.columnCount() == 3


def test_single_cell_editing_round_trips():
    g = _grid()
    idx = g.model.index(1, 0)
    assert g.model.setData(idx, "banana", Qt.ItemDataRole.EditRole)
    assert g.model.data(idx) == "banana"
    out = g.serialize()
    assert "| banana |" in out
    # reload -> same value
    from fastprompter.ui import silo_table as st
    parsed = st.parse(out.split("\n"), 0)
    assert parsed.rows[1][0] == "banana"


def test_column_alignment_is_carried_from_the_separator_row():
    g = _grid()
    assert g.model.aligns == ["left", "right", "center"]
    # and the model reports it for painting
    left = g.model.data(g.model.index(1, 0), Qt.ItemDataRole.TextAlignmentRole)
    right = g.model.data(g.model.index(1, 1), Qt.ItemDataRole.TextAlignmentRole)
    assert left != right


def test_rectangular_selection_reports_the_bounding_box():
    g = _grid()
    sm = g.view.selectionModel()
    # a 2x2 rectangle
    for r, c in ((1, 0), (1, 1), (2, 0), (2, 1)):
        sm.select(g.model.index(r, c), sm.SelectionFlag.Select)
    tsv = g.model.clipboard_range(sm.selectedIndexes())
    assert tsv.split("\n") == ["apple\t3", "pear\t12"]


# --------------------------------------------------------------- clipboard

def test_copy_writes_tsv_for_the_selection():
    g = _grid()
    sm = g.view.selectionModel()
    for r, c in ((1, 0), (1, 1), (2, 0), (2, 1)):
        sm.select(g.model.index(r, c), sm.SelectionFlag.Select)
    g.copy_cells()
    assert QApplication.clipboard().text() == "apple\t3\npear\t12"


def test_paste_tsv_fills_a_rectangle():
    g = _grid()
    QApplication.clipboard().setText("A\tB\nC\tD")
    g.view.setCurrentIndex(g.model.index(1, 0))
    g.paste_cells()
    assert g.model.rows[1][:2] == ["A", "B"]
    assert g.model.rows[2][:2] == ["C", "D"]
    # the header and the third column are untouched
    assert g.model.rows[0] == ["Name", "Qty", "Note"]
    assert g.model.rows[1][2] == "red"


def test_paste_grows_the_table_rather_than_dropping_data():
    g = _grid("| A |\n| --- |\n| 1 |")
    QApplication.clipboard().setText("x\ty\nz\tw")
    g.view.setCurrentIndex(g.model.index(1, 0))
    g.paste_cells()
    assert g.model.columnCount() >= 2
    assert g.model.rows[1][0] == "x" and g.model.rows[1][1] == "y"
    assert g.model.rows[2][0] == "z" and g.model.rows[2][1] == "w"


def test_cut_clears_the_selection():
    g = _grid()
    sm = g.view.selectionModel()
    for r, c in ((1, 0), (1, 1)):
        sm.select(g.model.index(r, c), sm.SelectionFlag.Select)
    g.cut_cells()
    assert g.model.rows[1][0] == "" and g.model.rows[1][1] == ""
    # the row still exists (a table is not allowed to empty itself)
    assert len(g.model.rows) == 3


# --------------------------------------------------------------- shape edits

def test_insert_and_delete_row():
    g = _grid()
    g.insert_row((1, 0), 1)
    assert g.model.rowCount() == 4
    assert g.model.rows[2] == ["", "", ""]
    g.delete_row((1, 0))
    assert g.model.rowCount() == 3


def test_header_row_is_never_deleted_or_split():
    g = _grid()
    assert g.delete_row((0, 0)) is False
    assert g.model.rowCount() == 3
    # inserting above the header is refused, so a second table cannot start
    g.insert_row((0, 0), -1)
    assert g.model.rows[0] == ["Name", "Qty", "Note"]


def test_insert_and_delete_column():
    g = _grid()
    g.insert_col((0, 1), 1)
    assert g.model.columnCount() == 4
    assert g.model.aligns[2] == "left"  # new column default
    g.delete_col((0, 1))
    assert g.model.columnCount() == 3


def test_delete_column_keeps_the_alignments_aligned():
    g = _grid()
    g.delete_col((0, 0))  # remove the left-aligned first column
    assert g.model.aligns == ["right", "center"]


def test_delete_column_keeps_at_least_one():
    g = _grid("| only |\n| --- |\n| x |")
    assert g.delete_col((0, 0)) is False
    assert g.model.columnCount() == 1


def test_swap_columns_moves_text_and_alignment_together():
    g = _grid()
    g.swap_col_left((0, 1))
    assert g.model.rows[0] == ["Qty", "Name", "Note"]
    assert g.model.aligns == ["right", "left", "center"]


# --------------------------------------------------------------- markdown

def test_serialize_is_column_aligned_markdown():
    g = _grid()
    lines = g.model.table_lines()
    # every line is the same width -> pipes line up
    assert len({len(ln) for ln in lines}) == 1
    assert all(ln.startswith("|") and ln.endswith("|") for ln in lines)


def test_the_escaped_pipe_is_content_not_a_delimiter():
    g = _grid("| cmd | n |\n| --- | --- |\n| a\\|b | 1 |")
    assert g.model.rows[1][0] == "a|b"
    assert g.model.columnCount() == 2
    out = g.serialize()
    from fastprompter.ui import silo_table as st
    assert len(st.split_row(out.split("\n")[2])) == 2


def test_a_model_reset_does_not_arm_the_sync_timer():
    """A rebuild from the document must not schedule a write back: load is
    the text->visual direction, and echoing it would fight the plain-text
    path. Only a real cell change (setData) arms the coalescing timer."""
    g = _grid()
    assert not g._sync_timer.isActive(), "load must stay silent"
    g.model.setData(g.model.index(1, 0), "x", Qt.ItemDataRole.EditRole)
    assert g._sync_timer.isActive(), "a cell change must schedule the sync"


def test_loading_a_fresh_document_is_silent():
    g = _grid()
    g._sync_timer.stop()
    g.load_markdown(TABLE.replace("apple", "apricot"))
    assert not g._sync_timer.isActive()


def test_setting_the_same_value_is_not_a_change():
    g = _grid()
    idx = g.model.index(1, 0)
    assert g.model.setData(idx, "apple", Qt.ItemDataRole.EditRole) is False


# --------------------------------------------------------------- scale

def test_a_large_table_loads_and_edits_without_quadratic_slowdown():
    """A 200x20 table must load and edit in a bounded time. The old grid
    created one QLineEdit PER CELL and re-added every widget on every shape
    change; a model/view keeps it linear."""
    import time
    rows = "\n".join(f"| r{r} | " + " | ".join(str(r * 100 + c)
                     for c in range(19)) + " |" for r in range(200))
    text = "| c0 | " + " | ".join(f"c{c}" for c in range(1, 20)) + " |\n" \
           + "| " + " | ".join("---" for _ in range(20)) + " |\n" + rows
    t0 = time.perf_counter()
    g = _grid(text)
    load_s = time.perf_counter() - t0
    assert g.model.rowCount() == 201
    assert g.model.columnCount() == 20
    assert load_s < 5.0, f"load took {load_s:.2f}s"

    t0 = time.perf_counter()
    for r in range(1, 200):
        g.model.setData(g.model.index(r, 0), f"x{r}",
                        Qt.ItemDataRole.EditRole)
    edit_s = time.perf_counter() - t0
    assert edit_s < 2.0, f"200 edits took {edit_s:.2f}s"


def test_a_large_document_write_back_only_touches_the_table_lines():
    """The region write-back is whole-line, so the size of the SURROUNDING
    document does not matter: no unrelated line is even visited."""
    from PyQt6.QtWidgets import QTextEdit

    from fastprompter.ui import table_edit_target
    prose = "\n".join(f"line {i}" for i in range(2000))
    doc = f"{prose}\n\n| A | B |\n| --- | --- |\n| 1 | 2 |\n\n{prose}\n"
    ed = QTextEdit()
    ed.setPlainText(doc)
    span = (2000, 2002)
    assert table_edit_target.replace_region(
        ed, span, ["| A | B |", "| --- | --- |", "| 9 | 8 |"]) is True
    out = ed.toPlainText()
    assert "| 9 | 8 |" in out
    assert out.startswith("line 0\n")
    assert out.count("line 1999") == 2
    ed.deleteLater()
