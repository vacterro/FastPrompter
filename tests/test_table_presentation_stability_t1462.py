"""T-1462 Stage 6: the grid stops re-fitting what the user sized by hand.

The defect: every structural command called `resizeColumnsToContents()` /
`resizeRowsToContents()`, which re-fits ALL sections. So one inserted row —
or one TSV paste — silently threw away every column width and row height the
user had dragged, and the grid looked like it had forgotten the layout.

These tests pin the distinction the fix rests on: an AUTOMATIC section is
sized to content and may be re-fitted at any time; a MANUAL section is the
user's and no structural command touches it. The distinction is persisted
with the layout, renumbered with the sections, and only an explicit Auto-fit
or Reset Size can clear it.
"""

from PyQt6.QtWidgets import QApplication

_APP = QApplication.instance() or QApplication([])

TABLE = (
    "| Name | Qty | Note |\n"
    "| :--- | ---: | :---: |\n"
    "| apple | 3 | red |\n"
    "| pear | 12 | green |\n"
)


def _grid(text=TABLE):
    from fastprompter.ui.table_grid import TableGridWidget
    g = TableGridWidget()
    g.load_markdown(text)
    return g


def _drag_column(g, col, width):
    """A user drag on a column handle: the resize signal is the same one."""
    g.view.horizontalHeader().resizeSection(col, width)


def _drag_row(g, row, height):
    g.view.verticalHeader().resizeSection(row, height)


# -------------------------------------------- manual vs automatic dimensions


def test_a_dragged_column_is_remembered_as_manual():
    g = _grid()
    assert g._manual_cols == set()
    _drag_column(g, 0, 240)
    assert g._manual_cols == {0}


def test_manual_column_width_survives_a_row_insertion():
    g = _grid()
    _drag_column(g, 0, 240)
    g.insert_row((1, 0), +1)
    assert g.view.horizontalHeader().sectionSize(0) == 240


def test_manual_row_height_survives_a_column_insertion():
    g = _grid()
    _drag_row(g, 1, 61)
    g.insert_col((1, 0), +1)
    assert g.view.verticalHeader().sectionSize(1) == 61


def test_row_insertion_does_not_resize_unrelated_columns():
    g = _grid()
    _drag_column(g, 1, 260)
    g.model.setData(g.model.index(1, 0), "a considerably longer cell value")
    before = [g.view.horizontalHeader().sectionSize(c)
              for c in range(g.model.columnCount())]
    g.insert_row((1, 0), +1)
    after = [g.view.horizontalHeader().sectionSize(c)
             for c in range(g.model.columnCount())]
    assert after == before


def test_autofit_does_not_shrink_a_manual_column():
    g = _grid()
    _drag_column(g, 2, 300)
    g._autofit()
    assert g.view.horizontalHeader().sectionSize(2) == 300
    # the automatic neighbours were re-fitted without touching the manual one
    assert g._manual_cols == {2}


def test_paste_preserves_a_manual_column_width():
    g = _grid()
    _drag_column(g, 0, 215)
    QApplication.clipboard().setText("A\tB\nC\tD")
    g.view.setCurrentIndex(g.model.index(1, 0))
    g.paste_cells()
    assert g.view.horizontalHeader().sectionSize(0) == 215


# ------------------------------------------------------ persistence / remap


def test_manual_flags_survive_capture_and_apply():
    g = _grid()
    _drag_column(g, 0, 190)
    _drag_row(g, 2, 58)
    layout = g.capture_presentation()
    assert layout["manual_cols"] == [0] and layout["manual_rows"] == [2]

    g2 = _grid()
    assert g2.apply_presentation(layout) is True
    assert g2._manual_cols == {0} and g2._manual_rows == {2}
    # and the protection is live on the rebuilt widget, not just recorded
    g2.insert_row((1, 0), +1)
    assert g2.view.horizontalHeader().sectionSize(0) == 190


def test_a_layout_without_manual_flags_applies_as_fully_automatic():
    """Backward compatibility: an old layout restores its sizes and nothing
    is protected, exactly as it behaved before the distinction existed."""
    g = _grid()
    g.apply_presentation({"cols": [150, 150, 150], "rows": [20, 20, 20]})
    assert g._manual_cols == set() and g._manual_rows == set()
    assert g.view.horizontalHeader().sectionSize(0) == 150


def test_manual_flag_follows_its_section_after_a_column_delete():
    g = _grid()
    _drag_column(g, 0, 111)
    _drag_column(g, 2, 222)
    assert g._manual_cols == {0, 2}
    g.model.remove_columns(1)
    # column 2 became column 1 and kept ITS flag; column 0 is untouched and
    # keeps its own. The flag follows the section, not the index.
    assert g._manual_cols == {0, 1}
    assert g.view.horizontalHeader().sectionSize(1) == 222


def test_deleting_a_manual_column_forgets_only_that_column():
    g = _grid()
    _drag_column(g, 1, 133)
    g.model.remove_columns(1)
    assert g._manual_cols == set()


# --------------------------------------------------------- the explicit out


def test_autofit_all_refits_a_manual_column():
    g = _grid()
    _drag_column(g, 0, 320)
    g.autofit_all()
    assert g._manual_cols == set()
    assert g.view.horizontalHeader().sectionSize(0) != 320


def test_reset_size_makes_every_section_uniform():
    g = _grid()
    _drag_column(g, 0, 320)
    g.reset_size()
    hh = g.view.horizontalHeader()
    d = hh.defaultSectionSize()
    assert g._manual_cols == set()
    assert [hh.sectionSize(c) for c in range(g.model.columnCount())] == [d] * 3
    vh = g.view.verticalHeader()
    dv = vh.defaultSectionSize()
    assert [vh.sectionSize(r) for r in range(g.model.rowCount())] == [dv] * 3


def test_presentation_commands_never_rewrite_the_markdown():
    g = _grid()
    before = g.serialize()
    _drag_column(g, 0, 250)
    g.autofit_all()
    g.reset_size()
    assert g.serialize() == before
