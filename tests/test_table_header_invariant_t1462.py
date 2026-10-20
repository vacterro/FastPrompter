"""T-1462 Stage 1: the header invariant lives in the MODEL.

The defect: `TableCellsModel.remove_rows(0)` returned True and deleted the
markdown header, and `insert_rows(0)` returned True and created a row above
it. The widget wrappers partially protected the header, but the context menu
calls the model methods directly, so the invariant had to move into the model
where no caller can break it.

Every assertion here drives the MODEL directly — the callers are not part of
the oracle. A rejected mutation must leave the model byte-identical: same rows,
same alignments, same serialized markdown, and no row-count notification.
"""

_APP = None


def _qapp():
    global _APP
    from PyQt6.QtWidgets import QApplication
    _APP = QApplication.instance() or QApplication([])
    return _APP


TABLE = (
    "| Name | Qty |\n"
    "| :--- | ---: |\n"
    "| apple | 3 |\n"
    "| pear | 12 |\n"
)


def _model(text=TABLE):
    _qapp()
    from fastprompter.ui.table_model import TableCellsModel
    m = TableCellsModel()
    m.load_markdown(text)
    return m


def _snapshot(m):
    return (list(map(list, m.rows)), list(m.aligns), m.has_header)


# --------------------------------------------------------------- row zero

def test_direct_remove_rows_zero_is_refused():
    """The confirmed defect, at the model, exactly as filed."""
    m = _model()
    before = _snapshot(m)
    assert m.remove_rows(0) is False
    assert _snapshot(m) == before
    assert m.rows[0] == ["Name", "Qty"]


def test_direct_insert_rows_zero_is_refused():
    m = _model()
    before = _snapshot(m)
    assert m.insert_rows(0) is False
    assert _snapshot(m) == before
    assert m.rows[0] == ["Name", "Qty"]


def test_a_multi_row_removal_spanning_row_zero_is_refused_whole():
    """A rejected batch must not delete its permitted subset silently."""
    m = _model("| A | B |\n| --- | --- |\n| 1 | 2 |\n| 3 | 4 |\n| 5 | 6 |\n")
    before = _snapshot(m)
    assert m.remove_rows(0, 2) is False
    assert _snapshot(m) == before
    # the body rows the batch would have covered are all still present
    assert [r[0] for r in m.rows] == ["A", "1", "3", "5"]


def test_the_refused_mutations_emit_no_row_notifications():
    """A refusal is not a mutation: no begin/end signal may fire."""
    m = _model()
    events = []
    m.rowsInserted.connect(lambda *a: events.append("ins"))
    m.rowsRemoved.connect(lambda *a: events.append("rem"))
    assert m.remove_rows(0) is False
    assert m.insert_rows(0) is False
    assert events == []


def test_the_serialized_markdown_is_unchanged_after_a_refusal():
    m = _model()
    before = m.table_lines()
    m.remove_rows(0)
    m.insert_rows(0)
    assert m.table_lines() == before


# --------------------------------------------------------------- body rows

def test_body_rows_can_still_be_removed_and_inserted():
    m = _model()
    assert m.remove_rows(1) is True
    assert [r[0] for r in m.rows] == ["Name", "pear"]
    assert m.insert_rows(1) is True
    assert [r[0] for r in m.rows] == ["Name", "", "pear"]


def test_multi_row_body_removal_is_one_contiguous_operation():
    m = _model("| H |\n| --- |\n| a |\n| b |\n| c |\n| d |\n")
    assert m.remove_rows(1, 2) is True
    assert [r[0] for r in m.rows] == ["H", "c", "d"]


def test_the_final_body_row_cannot_be_removed():
    """A table is never emptied: the parse would drop the region next load."""
    m = _model("| H |\n| --- |\n| only |\n")
    before = _snapshot(m)
    assert m.remove_rows(1) is False
    assert _snapshot(m) == before


def test_repeated_insert_and_remove_keeps_the_header_first():
    m = _model()
    for _ in range(8):
        assert m.insert_rows(1) is True
    assert len(m.rows) == 11
    for _ in range(8):
        assert m.remove_rows(1) is True
    assert m.rows[0] == ["Name", "Qty"]
    assert m.has_header is True
    assert [r[0] for r in m.rows] == ["Name", "apple", "pear"]


def test_alignments_stay_synchronized_through_row_edits():
    m = _model()
    m.insert_rows(1, 3)
    assert m.aligns == ["left", "right"]
    m.remove_rows(1, 3)
    assert m.aligns == ["left", "right"]


def test_a_headerless_model_may_remove_row_zero():
    """The invariant is conditional on has_header, not a blanket ban."""
    m = _model()
    m.has_header = False
    m.rows = [["a"], ["b"], ["c"]]
    assert m.remove_rows(0) is True
    assert [r[0] for r in m.rows] == ["b", "c"]


def test_save_reload_markdown_stays_valid_after_the_guard():
    """The rendered table must still parse back to the same shape."""
    from fastprompter.ui import silo_table as st
    m = _model()
    m.remove_rows(0)          # refused
    m.insert_rows(0)          # refused
    m.insert_rows(len(m.rows))  # allowed
    lines = m.table_lines()
    reparsed = st.parse(lines, 0)
    assert reparsed is not None
    assert reparsed.has_header is True
    assert reparsed.rows[0] == ["Name", "Qty"]
