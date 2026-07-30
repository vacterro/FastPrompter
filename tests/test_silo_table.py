"""SiloTable: markdown in, markdown out. No Qt, so it runs with the unit suite."""

from fastprompter.ui import silo_table as st

SAMPLE = [
    "notes above",
    "| Name | Qty | Price |",
    "| :--- | ---: | :---: |",
    "| apple | 3 | 1.50 |",
    "| pear | 12 | 0.90 |",
    "after",
]


def test_row_detection():
    assert st.is_table_row("| a | b |")
    assert st.is_table_row("   | a |   ")
    assert not st.is_table_row("a | b")
    assert not st.is_table_row("")
    assert st.is_separator_row("| :--- | ---: |")
    assert st.is_separator_row("|---|---|")
    assert not st.is_separator_row("| a | b |")
    assert not st.is_separator_row("| :: | -- |")


def test_split_keeps_escaped_pipes():
    assert st.split_row("| a | b |") == ["a", "b"]
    assert st.split_row(r"| grep a\|b | x |") == [r"grep a\|b", "x"]
    assert st.split_row("| | |") == ["", ""]


def test_parse_finds_the_whole_table_from_any_line():
    for i in (1, 2, 3, 4):
        t = st.parse(SAMPLE, i)
        assert t is not None, i
        assert (t.first_block, t.last_block) == (1, 4)
        assert t.has_header
        assert t.aligns == [st.ALIGN_LEFT, st.ALIGN_RIGHT, st.ALIGN_CENTER]
        assert t.rows[0] == ["Name", "Qty", "Price"]
        assert t.rows[2] == ["pear", "12", "0.90"]
    assert st.parse(SAMPLE, 0) is None
    assert st.parse(SAMPLE, 5) is None


def test_render_aligns_every_pipe():
    t = st.parse(SAMPLE, 1)
    out = st.render(t)
    widths = {len(line) for line in out}
    assert len(widths) == 1, out
    assert out[1].startswith("| :---")
    assert st.parse(out, 0).rows == t.rows        # round trips


def test_render_respects_alignment():
    t = st.parse(["| a | b | c |", "| :--- | ---: | :---: |",
                  "| x | y | z |"], 0)
    body = st.render(t)[2]
    cells = body.split("|")[1:-1]
    assert cells[0].strip() == "x" and cells[0].startswith(" x")
    assert cells[1].rstrip().endswith("y")


def test_ragged_rows_are_padded_not_dropped():
    t = st.parse(["| a | b | c |", "|---|---|---|", "| x |"], 0)
    assert st.parse(st.render(t), 0).rows[1] == ["x", "", ""]


def test_cell_index_and_span():
    row = "| apple | 3 | 1.50 |"
    assert st.cell_index(row, row.index("apple")) == 0
    assert st.cell_index(row, row.index("3")) == 1
    assert st.cell_index(row, row.index("1.50")) == 2
    start, end = st.cell_span(row, 1)
    assert row[start:end] == "3"
    start, end = st.cell_span(row, 0)
    assert row[start:end] == "apple"


def test_cell_span_of_an_empty_cell_is_collapsed():
    row = "| a |    | c |"
    start, end = st.cell_span(row, 1)
    assert start == end, "an empty cell has no content to select"
    assert row[:start].endswith("| ")


def test_add_and_remove_rows():
    t = st.parse(SAMPLE, 1)
    bigger = st.with_row(t, 1)
    assert len(bigger.rows) == len(t.rows) + 1
    assert bigger.rows[2] == ["", "", ""]
    smaller = st.without_row(bigger, 2)
    assert smaller.rows == t.rows


def test_the_header_row_cannot_be_deleted():
    t = st.parse(SAMPLE, 1)
    assert st.without_row(t, 0).rows == t.rows


def test_last_body_row_cannot_be_deleted():
    t = st.parse(["| a |", "|---|", "| x |"], 0)
    assert st.without_row(t, 1).rows == t.rows


def test_add_and_remove_columns():
    t = st.parse(SAMPLE, 1)
    wide = st.with_column(t, 0)
    assert wide.columns == t.columns + 1
    assert len(wide.aligns) == len(t.aligns) + 1
    assert wide.rows[0] == ["Name", "", "Qty", "Price"]
    narrow = st.without_column(wide, 1)
    assert narrow.rows == t.rows
    assert narrow.aligns == t.aligns


def test_the_last_column_cannot_be_deleted():
    t = st.parse(["| a |", "|---|", "| x |"], 0)
    assert st.without_column(t, 0).rows == t.rows


def test_set_align_survives_a_render_round_trip():
    t = st.set_align(st.parse(SAMPLE, 1), 0, st.ALIGN_CENTER)
    again = st.parse(st.render(t), 0)
    assert again.aligns[0] == st.ALIGN_CENTER


def test_new_table_leaves_the_body_empty():
    t = st.new_table(2, 3)
    assert t.rows[0] == ["Column 1", "Column 2", "Column 3"]
    assert t.rows[1:] == [["", "", ""], ["", "", ""]]
    lines = st.render(t)
    assert len(lines) == 4                       # header + separator + 2 rows
    assert st.parse(lines, 0).columns == 3
