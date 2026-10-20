"""T-1457 Stage 2: the shared clipboard TSV codec.

The defect this pins: the table clipboard joined cells with a tab and split
them on a tab, so ``"alpha<TAB>beta"<TAB>X`` was read as THREE cells and the
same implementation could not carry a literal tab inside a cell through a
copy/paste at all.

The contract is Excel's: a field containing a quote, a tab or a line break is
wrapped in double quotes and its inner quotes are doubled.  Both directions
go through one codec, so a copy can never produce something the paste reads
differently.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.abspath(
    os.path.join(os.path.dirname(__file__), "../src")))

import pytest  # noqa: E402

from fastprompter.ui import clipboard_tsv as codec  # noqa: E402

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


# ---------------------------------------------------------------------------
# 1/2/3/4 -- quoting
# ---------------------------------------------------------------------------

class TestQuoting:
    def test_a_plain_cell_is_not_quoted(self):
        assert codec.encode_cell("plain") == "plain"
        assert codec.encode_cell("") == ""
        assert codec.encode_cell(None) == ""

    def test_a_tab_inside_a_cell_is_quoted(self):
        assert codec.encode_cell("a\tb") == '"a\tb"'

    def test_a_line_break_inside_a_cell_is_quoted(self):
        assert codec.encode_cell("a\nb") == '"a\nb"'
        assert codec.encode_cell("a\r\nb") == '"a\r\nb"'

    def test_a_quote_inside_a_cell_is_doubled(self):
        assert codec.encode_cell('say "hi"') == '"say ""hi"""'

    def test_a_lone_quote_cell_round_trips(self):
        for text in ('"', '""', 'a"', '"a', '"a"'):
            assert codec.decode_grid(codec.encode_grid([[text]])) == [[text]]

    def test_quoted_tsv_from_a_spreadsheet_is_two_cells_not_three(self):
        """The negative control from the ticket, verbatim."""
        grid = codec.decode_grid('"alpha\tbeta"\tX')
        assert grid == [["alpha\tbeta", "X"]]
        assert len(grid[0]) == 2

    def test_a_quoted_field_may_contain_a_row_separator(self):
        assert codec.decode_grid('"a\nb"\tX') == [["a\nb", "X"]]

    def test_a_malformed_leading_quote_is_read_literally(self):
        """A plain-text payload whose cell starts with a quote is not a
        quoted field; reading it literally is what keeps the pre-existing
        behaviour for ordinary pastes."""
        assert codec.decode_grid('"unterminated\tX') == \
            [['"unterminated', "X"]]
        assert codec.decode_grid('"a"b\tX') == [['"a"b', "X"]]


# ---------------------------------------------------------------------------
# 5 -- ordinary TSV behaviour is unchanged
# ---------------------------------------------------------------------------

class TestOrdinaryTsv:
    @pytest.mark.parametrize("payload,expected", [
        ("a\tb", [["a", "b"]]),
        ("a\tb\nc\td", [["a", "b"], ["c", "d"]]),
        ("a\tb\n", [["a", "b"]]),
        ("a\tb\n\n", [["a", "b"]]),
        ("a\tb\r\nc\td\r\n", [["a", "b"], ["c", "d"]]),
        ("a\t\tb", [["a", "", "b"]]),
        ("a\tb\t", [["a", "b", ""]]),
        ("\ta", [["", "a"]]),
        ("a\n\nb", [["a"], [""], ["b"]]),
        ("single", [["single"]]),
        ("a\tb\nc", [["a", "b"], ["c"]]),
    ])
    def test_the_shape_is_exactly_the_pre_codec_one(self, payload, expected):
        assert codec.decode_grid(payload) == expected

    def test_a_backslash_and_a_pipe_are_untouched(self):
        """The codec is not the markdown escaper: it must not rewrite them."""
        assert codec.decode_grid("x\\\\|y\tz") == [["x\\\\|y", "z"]]


# ---------------------------------------------------------------------------
# 6 -- Unicode, CRLF, trailing empty cells
# ---------------------------------------------------------------------------

class TestPreservation:
    def test_unicode_survives_both_directions(self):
        # The Cyrillic sample is written as escapes so the no-cyrillic source
        # gate stays strict; at runtime it is the same real string.
        grid = [["Ünïcødé", "日本語"],
                ["emoji 🙂", "\u043a\u0438\u0440\u0438\u043b\u043b\u0438\u0446\u0430"]]
        assert codec.decode_grid(codec.encode_grid(grid)) == grid

    def test_crlf_payload_parses_like_lf(self):
        assert codec.decode_grid("a\tb\r\nc\td") == \
            codec.decode_grid("a\tb\nc\td")

    def test_a_crlf_inside_a_quoted_cell_is_preserved(self):
        grid = [["a\r\nb"]]
        assert codec.decode_grid(codec.encode_grid(grid)) == grid

    def test_trailing_empty_cells_are_preserved(self):
        grid = [["a", "", ""], ["", "b", ""]]
        assert codec.decode_grid(codec.encode_grid(grid)) == grid

    @pytest.mark.parametrize("grid", [
        [["x"], [""]],
        [[""], ["x"], [""]],
        [["x"], [""], [""]],
        [["x"], [""], [""], [""]],
        [[""]],
        [[""], [""]],
        [[""], [""], [""]],
    ])
    def test_single_column_empty_rows_preserved(self, grid):
        """P1 trailing empty row data-loss counterexamples round-trip exactly."""
        assert codec.decode_grid(codec.encode_grid(grid)) == grid
        assert codec.scan_shape(codec.encode_grid(grid)) == (len(grid), 1)

    def test_twenty_thousand_case_randomized_roundtrip_audit(self):
        """Mandatory property invariant: decode_grid(encode_grid(grid)) == grid across 20k cases."""
        import random
        rng = random.Random(42)
        tokens = [
            "", " ", "  ", "x", "hello", 'quote"in"cell', '"', '""',
            "tab\there", "\t", "pipe|here", chr(92), chr(92) * 2, "日本語", "emoji🙂"
        ]
        for _ in range(20000):
            n_rows = rng.randint(1, 8)
            n_cols = rng.randint(1, 5)
            grid = [[rng.choice(tokens) for _ in range(n_cols)] for _ in range(n_rows)]
            enc = codec.encode_grid(grid)
            dec = codec.decode_grid(enc)
            assert dec == grid
            rows, cols = codec.scan_shape(enc)
            assert (rows, cols) == (len(dec), max(len(r) for r in dec))

    @pytest.mark.parametrize("grid", [
        [["a", "b"]],
        [["a\tb", "c"]],
        [["a\nb", "c"]],
        [['"q"', "d"]],
        [["", ""]],
        [["x"] * 12 for _ in range(7)],
        [["tab\there", "nl\nhere", 'quote"here', "plain"]],
    ])
    def test_every_grid_round_trips_exactly(self, grid):
        assert codec.decode_grid(codec.encode_grid(grid)) == grid


# ---------------------------------------------------------------------------
# 7 -- the shape scan and the materialised grid agree
# ---------------------------------------------------------------------------

class TestShape:
    @pytest.mark.parametrize("payload", [
        "a\tb", "a\tb\nc\td", "a\tb\n", "a\tb\n\n", "a\n\nb",
        '"a\tb"\tX', '"a\nb"\tX', "a\tb\t", "\ta", "single",
        '"q"\t"r"\n"s"\t"t"', "a\tb\r\nc\td\r\n",
    ])
    def test_scan_shape_matches_the_grid(self, payload):
        rows, cols = codec.scan_shape(payload)
        grid = codec.decode_grid(payload)
        assert rows == len(grid)
        assert cols == max(len(r) for r in grid)

    def test_a_quoted_row_separator_does_not_add_a_row(self):
        assert codec.scan_shape('"a\nb"\tX') == (1, 2)

    def test_scan_shape_allocates_nothing_per_cell(self):
        """The budget guard must stay O(1) in cells: a huge payload is
        counted, not materialised."""
        payload = ("x" * 100 + "\t") * 20000
        rows, cols = codec.scan_shape(payload)
        assert rows == 1
        assert cols == 20001


# ---------------------------------------------------------------------------
# 7 -- multiline cells cannot be stored in a markdown table
# ---------------------------------------------------------------------------

class TestMultiline:
    def test_a_multiline_cell_is_detected(self):
        assert codec.has_multiline_cell([["a\nb"]]) is True
        assert codec.has_multiline_cell([["a\r\nb"]]) is True
        assert codec.has_multiline_cell([["a\tb", "c"]]) is False
        assert codec.has_multiline_cell([]) is False
        assert codec.has_multiline_cell([[""]]) is False


# ---------------------------------------------------------------------------
# The model's own contract
# ---------------------------------------------------------------------------

class TestModelClipboard:
    def _model(self):
        from fastprompter.ui.table_model import TableCellsModel
        m = TableCellsModel()
        m.load_markdown("| A | B |\n| --- | --- |\n| 1 | 2 |\n")
        return m

    def test_a_literal_tab_in_a_cell_survives_copy_and_paste(self):
        m = self._model()
        m.setData(m.index(1, 0), "x\ty")
        payload = m.clipboard_range([m.index(1, 0), m.index(1, 1)])
        assert payload == '"x\ty"\t2'

        target = self._model()
        rows, cols = target.paste_tsv(1, 0, payload)
        assert (rows, cols) == (1, 2)
        assert target.paste_refusal == ""
        assert target.rows[1][0] == "x\ty"
        assert target.rows[1][1] == "2"

    def test_an_external_quoted_paste_is_two_cells(self):
        m = self._model()
        rows, cols = m.paste_tsv(1, 0, '"alpha\tbeta"\tX')
        assert (rows, cols) == (1, 2)
        assert m.rows[1][0] == "alpha\tbeta"
        assert m.rows[1][1] == "X"

    def test_a_multiline_cell_is_refused_atomically(self):
        m = self._model()
        before = [list(r) for r in m.rows]
        rows, cols = m.paste_tsv(1, 0, '"a\nb"\tX')
        assert (rows, cols) == (0, 0)
        assert "line break" in m.paste_refusal
        assert m.rows == before

    def test_an_ordinary_paste_still_works(self):
        m = self._model()
        rows, cols = m.paste_tsv(1, 0, "7\t8")
        assert (rows, cols) == (1, 2)
        assert m.paste_refusal == ""
        assert m.rows[1] == ["7", "8"]

    def test_a_unicode_quote_payload_round_trips_through_the_model(self):
        m = self._model()
        m.setData(m.index(1, 0), 'Ünï "cøde"\t🙂')
        payload = m.clipboard_range([m.index(1, 0), m.index(1, 1)])
        target = self._model()
        assert target.paste_tsv(1, 0, payload) == (1, 2)
        assert target.rows[1][0] == 'Ünï "cøde"\t🙂'

    def test_oversized_payloads_are_still_refused_before_parsing(self):
        m = self._model()
        payload = "x" * (m._PASTE_MAX_CHARS + 1)
        assert m.paste_tsv(0, 0, payload) == (0, 0)
        assert m.paste_refusal


# ---------------------------------------------------------------------------
# Negative controls -- the retired defect, pinned as the exact behaviour the
# codec must NOT reproduce.  A guard that cannot go red guards nothing.
# ---------------------------------------------------------------------------

class TestNegativeControls:
    def test_the_old_join_and_split_really_did_lose_a_literal_tab(self):
        cell = "alpha\tbeta"
        # The pre-T-1457 implementation, verbatim.
        old_payload = "\t".join([cell, "X"])
        assert old_payload == "alpha\tbeta\tX"
        assert old_payload.split("\t") == ["alpha", "beta", "X"]   # 3 cells
        # The codec encodes the same rectangle unambiguously.
        new_payload = codec.encode_grid([[cell, "X"]])
        assert new_payload == '"alpha\tbeta"\tX'
        assert codec.decode_grid(new_payload) == [[cell, "X"]]      # 2 cells

    def test_the_codec_payload_is_not_the_naive_payload(self):
        grid = [["a\tb", "c"]]
        assert codec.encode_grid(grid) != "\t".join(grid[0])

    def test_a_cell_with_a_line_break_cannot_be_smuggled_into_a_table(self):
        """The markdown format is one line per row, so the model must refuse
        rather than write a row that reads back as something else."""
        from fastprompter.ui import silo_table as st

        payload = codec.encode_grid([["a\nb", "c"]])
        # The codec itself is lossless ...
        assert codec.decode_grid(payload) == [["a\nb", "c"]]

        # ... but the canonical markdown table is NOT: the document is plain
        # text with one line per row, so the newline inside the cell splits
        # the row when the rendered lines are stored (and re-read) as text.
        # That loss is exactly why paste_tsv refuses such a payload.
        table = st.Table(first_block=0, last_block=1,
                         rows=[["a\nb", "c"], ["x", "y"]],
                         aligns=[st.ALIGN_LEFT, st.ALIGN_LEFT],
                         has_header=True)
        document_lines = "\n".join(st.render(table)).split("\n")
        assert len(document_lines) > 3          # one cell became two lines
        reparsed = st.parse(document_lines, 0)
        assert reparsed is None or reparsed.rows != [["a\nb", "c"], ["x", "y"]]
