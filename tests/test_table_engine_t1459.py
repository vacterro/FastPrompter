"""Queue 2: one safe table engine — strict recognition, exact splice, round trip.

No Qt: everything here is pure text in, text out, so it runs with the unit
suite rather than the (slower) smoke suite.
"""

from fastprompter.ui import silo_region as sr
from fastprompter.ui import silo_table as st

# ---------------------------------------------------------------- strictness

def test_a_pipe_run_without_a_separator_is_not_a_table():
    """Prose that happens to contain pipes must never reach the table widget,
    which serialises over everything it claims."""
    lines = ["Some prose.", "| has a | pair of pipes |", "| still prose |"]
    assert st.parse(lines, 1) is None
    assert sr.table_region(lines) is None


def test_a_separated_table_is_recognised():
    lines = ["notes above", "| Name | Qty |", "| :--- | ---: |",
             "| apple | 3 |", "after"]
    assert sr.table_region(lines) == (1, 3)


def test_table_rows_inside_a_code_fence_are_never_claimed():
    lines = [
        "Example:",
        "```",
        "| Name | Qty |",
        "| :--- | ---: |",
        "| apple | 3 |",
        "```",
    ]
    assert sr.table_region(lines) is None
    assert st.parse(lines, 2) is None
    assert st.parse(lines, 4) is None


def test_a_fence_does_not_cut_a_real_table_that_follows_it():
    lines = [
        "```",
        "| not | a table |",
        "```",
        "| real | table |",
        "| --- | --- |",
        "| a | b |",
    ]
    span = sr.table_region(lines)
    assert span == (3, 5)


def test_fence_mask_is_only_the_interior():
    lines = ["a", "```", "inside", "```", "b"]
    assert st.fenced_mask(lines) == [False, False, True, False, False]


def test_an_unclosed_fence_masks_to_the_end():
    lines = ["```", "x", "y"]
    assert st.fenced_mask(lines) == [False, True, True]


def test_two_tables_are_distinct_regions():
    """The two tables are separate blocks — the widget must not merge them
    into one giant table."""
    lines = [
        "| A |", "| --- |", "| 1 |",
        "",
        "| B |", "| --- |", "| 2 |",
    ]
    first = sr.table_region(lines)
    assert first == (0, 2)
    second = st.parse(lines, 5)
    assert second is not None
    assert (second.first_block, second.last_block) == (4, 6)


# ------------------------------------------------------------------- splice

def test_split_then_splice_is_the_identity():
    documents = [
        "# Title\n\n| A | B |\n| --- | --- |\n| 1 | 2 |",
        "| A |\n| --- |\n| 1 |\n\nNotes below.",
        "# Title\n\n| A |\n| --- |\n| 1 |\n\nFooter line.\n",
        "| A |\n| --- |\n| 1 |",
        "# Nothing but a heading",
        "",
    ]
    for text in documents:
        lines = text.split("\n")
        parts = sr.split(lines, sr.table_region(lines))
        assert sr.splice(*parts) == text, text


def test_splice_pops_nothing_at_the_seams():
    """The old splice trimmed blank lines at both seams and injected exactly
    one, so a silo that opened and saved drifted on every round trip."""
    prefix = ["# Title", "", ""]
    region = ["| A |", "| --- |", "| 1 |"]
    suffix = ["", "", "Footer.", ""]

    out = sr.splice(prefix, region, suffix)
    assert out.split("\n") == prefix + region + suffix
    assert sr.splice(*sr.split(out.split("\n"),
                               sr.table_region(out.split("\n")))) == out


def test_an_empty_silo_stays_empty():
    assert sr.splice([""], [], []) == ""
    assert sr.splice([], [], []) == ""


# --------------------------------------------------------------- round trips

def test_parse_render_parse_preserves_rows_and_alignment():
    source = [
        "| Name | Qty | Price |",
        "| :--- | ---: | :---: |",
        "| apple | 3 | 1.50 |",
        "| pear | 12 | 0.90 |",
    ]
    once = st.parse(source, 0)
    assert once is not None
    twice = st.parse(st.render(once), 0)
    assert twice.rows == once.rows
    assert twice.aligns == once.aligns
    assert twice.has_header is True
    assert st.parse(st.render(twice), 0).rows == once.rows   # stable


def test_escaped_pipes_survive_a_round_trip():
    source = ["| a | grep a\\|b | x \\| y |",
              "| --- | --- | --- |",
              "| 1 | 2 | 3 |"]
    table = st.parse(source, 0)
    # rows[0] is the header, rows[1] the first body row
    assert table.rows[0][1] == r"grep a\|b"
    assert table.rows[0][2] == r"x \| y"
    out = st.render(table)
    again = st.parse(out, 0)
    assert again.rows == table.rows


def test_backslashes_and_unicode_survive_a_round_trip():
    source = [r"| c:\path\to | 041f04400438043204350442 | 🎉 |",
              "| --- | --- | --- |",
              "| a | b | c |"]
    table = st.parse(source, 0)
    assert table.rows[0] == [r"c:\path\to", "041f04400438043204350442", "🎉"]
    assert st.parse(st.render(table), 0).rows == table.rows


def test_escape_unescape_are_inverses_for_cell_text():
    samples = ["grep a|b", "plain", r"a\|b", "both | and \\", "🎉", ""]
    for s in samples:
        assert st.unescape(st.escape(s)) == s, s


def test_escape_puts_a_backslash_before_every_pipe():
    assert st.escape("a|b") == r"a\|b"
    assert st.escape("a||b") == r"a\|\|b"
    assert st.unescape(r"a\|\|b") == "a||b"
    assert st.escape("no pipes") == "no pipes"
    # split_row keeps the escape (it is still in the SOURCE); unescape is what
    # turns it back into the text a user typed
    cells = st.split_row("| " + st.escape("grep a|b") + " |")
    assert cells == [r"grep a\|b"]
    assert [st.unescape(c) for c in cells] == ["grep a|b"]


def test_a_round_trip_through_the_silo_layer_keeps_the_surroundings():
    text = (
        "# Weekly report\n"
        "\n"
        "| Name | Qty |\n"
        "| ---: | ---: |\n"
        "| apple | 3 |\n"
        "\n"
        "Footer note."
    )
    lines = text.split("\n")
    span = sr.table_region(lines)
    prefix, region, suffix = sr.split(lines, span)
    table = st.parse(region, 0)
    assert table is not None

    rebuilt = sr.splice(prefix, st.render(table), suffix)
    assert rebuilt != text           # the pipes are re-aligned to the widest
    again = rebuilt.split("\n")
    again_prefix, _, again_suffix = sr.split(again, sr.table_region(again))
    assert again_prefix == ["# Weekly report", ""]
    assert again_suffix == ["", "Footer note."]
    assert st.parse(again, len(again_prefix)) is not None


def test_a_body_row_cannot_be_parsed_as_a_header():
    """Sitting on the separator keeps working: it belongs to the table above."""
    lines = ["| A |", "| --- |", "| 1 |"]
    table = st.parse(lines, 1)
    assert table is not None
    assert table.has_header
    assert table.rows == [["A"], ["1"]]
