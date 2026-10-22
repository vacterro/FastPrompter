"""T-1462 Stage 7: one header, not two.

The frame painted the markdown header row (`rows[0]`) into the Qt horizontal
header band while row 0 was ALSO a normal, editable model row. The result was
the header text shown twice — once as chrome the user cannot edit and once as a
real row — and editing a cell in that row silently renamed a column label that
looked like it was owned by the framework.

Option A of the two filed: the horizontal header carries spreadsheet-style
column identifiers (A, B, ... Z, AA) and the markdown header row stays a real
row. No view-row-to-model-row offset anywhere, so single-cell editing, drag
selection, Ctrl+C/Ctrl+V rectangles and the structural guards keep working on
plain indices: model row == markdown line inside the table region.
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


def _model(text=TABLE):
    from fastprompter.ui.table_model import TableCellsModel
    m = TableCellsModel()
    m.load_markdown(text)
    return m


H = Qt.Orientation.Horizontal
V = Qt.Orientation.Vertical


# -------------------------------------------------------------- no duplicate


def test_the_horizontal_header_names_columns_not_header_cells():
    m = _model()
    labels = [m.headerData(c, H, Qt.ItemDataRole.DisplayRole) for c in range(3)]
    assert labels == ["A", "B", "C"]
    # the markdown header row is NOT painted into the header band
    assert "Name" not in labels and "Qty" not in labels


def test_the_header_row_is_still_visible_and_editable():
    """Row 0 is the markdown header and behaves as the row it is."""
    m = _model()
    assert [m.data(m.index(0, c), Qt.ItemDataRole.DisplayRole)
            for c in range(3)] == ["Name", "Qty", "Note"]
    assert m.setData(m.index(0, 1), "Count", Qt.ItemDataRole.EditRole) is True
    assert m.rows[0][1] == "Count"
    # ...and the header band did not follow the edit: it is not chrome.
    assert m.headerData(1, H, Qt.ItemDataRole.DisplayRole) == "B"


def test_the_header_row_deletion_is_still_refused():
    m = _model()
    assert m.remove_rows(0) is False
    assert m.rows[0] == ["Name", "Qty", "Note"]


def test_the_header_font_marks_which_row_is_the_header():
    m = _model()
    bold = m.data(m.index(0, 0), Qt.ItemDataRole.FontRole)
    assert bold is not None and bold.bold() is True
    assert m.data(m.index(1, 0), Qt.ItemDataRole.FontRole) is None


# --------------------------------------------------------- index arithmetic


def test_vertical_row_numbers_match_the_markdown_lines():
    m = _model()
    assert [m.headerData(r, V, Qt.ItemDataRole.DisplayRole)
            for r in range(m.rowCount())] == ["1", "2", "3"]


def test_column_labels_continue_past_z():
    m = _model()
    assert [m.column_label(i) for i in (0, 25, 26, 27, 51, 52)] == [
        "A", "Z", "AA", "AB", "AZ", "BA"]


def test_clipboard_mapping_is_unshifted():
    """Ctrl+C on row 0 copies the markdown header cells themselves."""
    m = _model()
    assert m.clipboard_range([m.index(0, 0), m.index(0, 1)]) == "Name\tQty"
    assert m.clipboard_range([m.index(1, 1), m.index(2, 1)]) == "3\n12"


def test_copy_of_an_expanded_rectangular_selection_includes_row_zero():
    m = _model()
    indexes = [m.index(r, c) for r in range(3) for c in range(2)]
    assert m.clipboard_range(indexes) == "Name\tQty\napple\t3\npear\t12"


def test_paste_over_the_header_row_writes_the_header_row():
    m = _model()
    rows, cols = m.paste_tsv(0, 0, "Key\tValue\nA\t1")
    assert (rows, cols) == (2, 2)
    assert m.rows[0][:2] == ["Key", "Value"]


def test_serialization_is_unchanged_by_the_header_labels():
    m = _model()
    before = m.table_lines()
    [m.headerData(c, H, Qt.ItemDataRole.DisplayRole) for c in range(3)]
    [m.headerData(c, H, Qt.ItemDataRole.AccessibleTextRole) for c in range(3)]
    assert m.table_lines() == before


def test_accessible_text_names_the_column_and_the_row():
    m = _model()
    assert m.headerData(0, H, Qt.ItemDataRole.AccessibleTextRole) == "A"
    assert m.headerData(2, H, Qt.ItemDataRole.AccessibleTextRole) == "C"
    assert m.headerData(0, V, Qt.ItemDataRole.AccessibleTextRole) == "1"
    assert m.headerData(2, V, Qt.ItemDataRole.AccessibleTextRole) == "3"


def test_a_headerless_table_still_labels_its_columns_and_bolds_nothing():
    m = _model()
    m.has_header = False
    assert m.headerData(0, H, Qt.ItemDataRole.DisplayRole) == "A"
    assert m.data(m.index(0, 0), Qt.ItemDataRole.FontRole) is None
