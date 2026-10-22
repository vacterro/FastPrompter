"""T-1462 Stage 4: the clipboard budget is enforced BEFORE the parse.

The earlier safety work put the ceiling on the RESULT, which still let the
payload be materialised first: `paste_tsv` split every line into a list of
cell strings and only then compared the shape against the budget, so a
100k x 100k clipboard allocated 10^10 strings before it was refused.

These tests pin the order of operations instead: the raw character budget is
O(1) and runs first, rows and columns are counted incrementally with no
per-cell list, the total resulting-cell budget includes the existing table
and the destination offset, and a refusal leaves the model, the selection,
the layout and the document exactly as they were.
"""

from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QTextEdit

_APP = QApplication.instance() or QApplication([])

TABLE = (
    "| Name | Qty |\n"
    "| :--- | ---: |\n"
    "| apple | 3 |\n"
    "| pear | 12 |\n"
)

DOC = (
    "# Title\n"
    "\n"
    "Notes above.\n"
    "\n"
    "| Name | Qty |\n"
    "| :--- | ---: |\n"
    "| apple | 3 |\n"
    "| pear | 12 |\n"
    "\n"
    "Footer.\n"
)


def _model():
    from fastprompter.ui.table_model import TableCellsModel
    m = TableCellsModel()
    m.load_markdown(TABLE)
    return m


def _grid(text=TABLE):
    from fastprompter.ui.table_grid import TableGridWidget
    g = TableGridWidget()
    g.load_markdown(text)
    return g


def _editor(text=DOC):
    e = QTextEdit()
    e.setPlainText(text)
    return e


# --------------------------------------------------------------- the 9 cases


def test_huge_single_cell_payload_is_refused_before_parsing():
    m = _model()
    before = [list(r) for r in m.rows]
    payload = "x" * (m._PASTE_MAX_CHARS + 1)
    assert m.paste_tsv(1, 0, payload) == (0, 0)
    assert m.rows == before
    assert m.rowCount() == 3 and m.columnCount() == 2
    assert m.paste_refusal  # the reason is reported, not swallowed


def test_very_wide_row_is_refused():
    m = _model()
    before = [list(r) for r in m.rows]
    payload = "\t".join(f"c{i}" for i in range(m._PASTE_MAX_COLS + 1))
    assert m.paste_tsv(1, 0, payload) == (0, 0)
    assert m.rows == before
    assert m.columnCount() == 2
    assert m.paste_refusal


def test_very_tall_payload_is_refused():
    m = _model()
    before = [list(r) for r in m.rows]
    payload = "\n".join(f"r{i}" for i in range(m._PASTE_MAX_ROWS + 1))
    assert m.paste_tsv(1, 0, payload) == (0, 0)
    assert m.rows == before
    assert m.rowCount() == 3
    assert m.paste_refusal


def test_large_but_valid_table_plus_small_paste_is_accepted():
    m = _model()
    m.insert_rows(3, 297)          # 300 rows
    m.insert_columns(2, 38)        # 40 columns
    assert (m.rowCount(), m.columnCount()) == (300, 40)
    rows, cols = m.paste_tsv(10, 10, "a\tb\nc\td")
    assert (rows, cols) == (2, 2)
    assert m.rows[10][10:12] == ["a", "b"]
    assert m.rows[11][10:12] == ["c", "d"]
    assert m.paste_refusal == ""


def test_paste_near_the_last_valid_row_and_column():
    m = _model()
    rows, cols = m.paste_tsv(len(m.rows) - 1, m._width() - 1, "x\ty\nz\tw")
    assert (rows, cols) == (2, 2)
    assert m.rowCount() == 4 and m.columnCount() == 3
    assert m.rows[2][1:3] == ["x", "y"]
    assert m.rows[3][1:3] == ["z", "w"]


def test_combined_row_and_column_expansion():
    m = _model()
    rows, cols = m.paste_tsv(2, 1, "a\tb\tc\nd\te\tf\ng\th\ti")
    assert (rows, cols) == (3, 3)
    assert m.rowCount() == 5 and m.columnCount() == 4
    # the paste grows the table to fit; the two fresh rows were appended by
    # the write itself
    assert m.rows[2] == ["pear", "a", "b", "c"]
    assert m.rows[4][1:] == ["g", "h", "i"]


def test_crlf_and_unicode_paste_round_trip():
    m = _model()
    # Non-ASCII cell text written as escapes: tests_smoke forbids Cyrillic
    # literals anywhere in the tree, and this case is about non-ASCII
    # survival, not about any one script.
    cyr = "\u041a\u0456\u043b\u044c\u0442\u0438\u043d\u043a\u0430"
    payload = f"{cyr}\t\u041a\u0438\r\n\U0001f34e\temoji\r\n"
    rows, cols = m.paste_tsv(1, 0, payload)
    assert (rows, cols) == (2, 2)
    assert m.rows[1][:2] == [cyr, "\u041a\u0438"]
    assert m.rows[2][:2] == ["\U0001f34e", "emoji"]


def test_rejected_paste_leaves_model_selection_layout_and_document_unchanged():
    g = _grid(DOC)
    e = _editor()
    written = []
    g.changed.connect(lambda md: written.append(md))
    g.view.setCurrentIndex(g.model.index(1, 0))
    g.view.setFocus()
    _APP.processEvents()
    sel_before = sorted((i.row(), i.column())
                        for i in g.view.selectionModel().selectedIndexes())
    layout_before = g.capture_presentation()
    doc_before = e.toPlainText()

    QApplication.clipboard().setText(
        "\n".join(f"r{i}" for i in range(g.model._PASTE_MAX_ROWS + 1)))
    QTest.keyClick(g.view, Qt.Key.Key_V, Qt.KeyboardModifier.ControlModifier)
    _APP.processEvents()

    assert written == []                       # no write-back was scheduled
    assert not g._sync_timer.isActive()        # and no timer was armed
    assert g.model.paste_refusal               # the refusal is reported
    assert g.model.rows[1][:2] == ["apple", "3"]
    assert g.model.rowCount() == 3
    assert sorted((i.row(), i.column())
                  for i in g.view.selectionModel().selectedIndexes()) == sel_before
    assert g.capture_presentation() == layout_before   # no autofit happened
    assert e.toPlainText() == doc_before


def test_accepted_paste_is_exactly_one_coherent_undo_transaction():
    g = _grid(DOC)
    e = _editor()
    from fastprompter.ui import table_edit_target as tet
    written = []
    g.changed.connect(
        lambda md, w=g: written.append(
            tet.replace_region(e, w._visual_span, w._table_lines())))
    g.view.setCurrentIndex(g.model.index(1, 0))
    g.view.setFocus()
    _APP.processEvents()

    QApplication.clipboard().setText("A\tB\nC\tD")
    QTest.keyClick(g.view, Qt.Key.Key_V, Qt.KeyboardModifier.ControlModifier)
    _APP.processEvents()
    QTest.qWait(700)          # let the 500 ms coalescing timer fire
    _APP.processEvents()

    # ONE write-back, carrying the whole table (padding is markdown alignment).
    assert len(written) == 1 and written[0] is True
    text = e.toPlainText()
    assert "A" in text and "C" in text and "D" in text
    assert "apple" not in text

    # One Ctrl+Z reverts the paste and nothing else.
    e.undo()
    _APP.processEvents()
    assert e.toPlainText() == DOC


# ------------------------------------------------------- budget arithmetic


def test_total_cell_budget_counts_the_existing_table_and_the_offset():
    """A paste that is legal on each axis can still be refused on the total."""
    m = _model()
    m.insert_rows(3, 1997)      # 2000 rows
    m.insert_columns(2, 1998)   # 2000 columns -> already 4M cells
    assert m.rowCount() * m.columnCount() == m._PASTE_MAX_CELLS
    before = [list(r) for r in m.rows]
    # 1 row x 1 column: every axis is fine on its own, but growing the result
    # past the total budget is refused before a single cell is allocated.
    assert m.paste_tsv(len(m.rows), 0, "x") == (0, 0)
    assert m.rows == before
    assert m.paste_refusal


def test_refusal_reason_is_cleared_on_the_next_accepted_paste():
    m = _model()
    m.paste_tsv(1, 0, "x" * (m._PASTE_MAX_CHARS + 1))
    assert m.paste_refusal
    m.paste_tsv(1, 0, "ok")
    assert m.paste_refusal == ""


def test_empty_and_whitespace_pastes_are_noops_not_refusals():
    m = _model()
    # Empty payloads and blank-line rows remain safe no-ops
    assert m.paste_tsv(1, 0, "") == (0, 0)
    assert m.paste_tsv(1, 0, "\n\n\n") == (0, 0)
    assert m.paste_refusal == ""
    assert m.rowCount() == 3

    # Meaningful whitespace is preserved as cell content (Stage 3)
    assert m.paste_tsv(1, 0, "   ") == (1, 1)
    assert m.rows[1][0] == "   "
    assert m.paste_refusal == ""
