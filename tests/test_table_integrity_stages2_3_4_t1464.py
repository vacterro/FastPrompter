"""T-1464: Canonical cell representability, direct cell edit validation, and full table round-trip invariants.

Covers:
- Stage 2: P1 Canonical Cell Representability (silo_table and table_model)
  Empty string, one space, multiple spaces, leading/trailing spaces, literal tabs,
  escaped pipes, backslashes, Unicode, repeated save/reload cycles.
- Stage 3: P1 Direct Cell Edit Validation (setData and model boundary)
  setData with LF, CR, CRLF, header cell newlines, unicode + newline, failed edit
  immutability, no dataChanged emitted, refusal feedback.
- Stage 4: Full Table Round-Trip Invariant
  GRID -> encode_grid -> decode_grid -> paste_tsv -> table_lines -> parse -> TableCellsModel -> GRID
  Multi-column, one-column, mixed empty/nonempty rows, surrounding silo prose,
  multiple tables in one silo.
"""

from __future__ import annotations

import os
import random

import pytest
from PyQt6.QtWidgets import QApplication

from fastprompter.ui import clipboard_tsv as codec
from fastprompter.ui import silo_region
from fastprompter.ui import silo_table as st
from fastprompter.ui.table_model import TableCellsModel

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
_APP = QApplication.instance() or QApplication([])


def _create_model(text: str = "| Col1 | Col2 |\n| :--- | ---: |\n| A | B |\n") -> TableCellsModel:
    m = TableCellsModel()
    m.load_markdown(text)
    return m


# ===========================================================================
# STAGE 2: CANONICAL CELL REPRESENTABILITY
# ===========================================================================

class TestStage2CanonicalRepresentability:
    """Verify that cell values with whitespace boundaries, backslashes, pipes,

    and unicode round-trip losslessly through Markdown serialization and parsing.
    """

    CELL_CASES = [
        # Empty string
        "",
        # One space
        " ",
        # Multiple spaces
        "   ",
        # Leading spaces
        " x",
        "  leading",
        # Trailing spaces
        "x ",
        "trailing  ",
        # Leading and trailing spaces
        " x ",
        "  both  ",
        # Multiple internal spaces
        "a   b",
        "  a   b  ",
        # Literal tabs
        "tab\there",
        "\tleading_tab",
        "trailing_tab\t",
        # Escaped pipes
        "a|b",
        "grep a|b|c",
        # Backslashes
        "path\\",
        "path\\\\",
        "C:\\Users\\test",
        "path\\to|file",
        # Escaped backslash before space
        "\\ ",
        " \\",
        "\\ \\",
        # Unicode
        "🦄|🌈",
        "日本語|テスト",
        "Ünïcødé  ",
        "  🙂 emoji  ",
    ]

    @pytest.mark.parametrize("val", CELL_CASES)
    def test_single_cell_markdown_round_trip(self, val):
        """Cell value -> escape -> render -> parse -> unescape == original value."""
        m = TableCellsModel()
        m.has_header = True
        m.rows = [["Header1", "Header2"], [val, "companion"]]
        m.aligns = [st.ALIGN_LEFT, st.ALIGN_RIGHT]

        lines = m.table_lines()
        md_text = "\n".join(lines)

        m2 = TableCellsModel()
        m2.load_markdown(md_text)

        assert m2.rows[1][0] == val, (
            f"Round-trip failed for {repr(val)}: got {repr(m2.rows[1][0])}, "
            f"rendered lines:\n{md_text}"
        )

    def test_repeated_save_reload_cycles_are_stable(self):
        """Multiple save/reload cycles must remain strictly idempotent."""
        values = ["", " ", "   ", " x", "x ", " x ", "  a   b  ", "a|b", "C:\\test", "🦄"]
        m = TableCellsModel()
        m.has_header = True
        m.rows = [["H1"], *[[v] for v in values]]
        m.aligns = [st.ALIGN_LEFT]

        for cycle in range(5):
            md = "\n".join(m.table_lines())
            m = TableCellsModel()
            m.load_markdown(md)
            for i, expected in enumerate(values):
                assert m.rows[i + 1][0] == expected, f"Cycle {cycle} failed for {repr(expected)}"

    @pytest.mark.parametrize("align", [st.ALIGN_LEFT, st.ALIGN_CENTER, st.ALIGN_RIGHT])
    def test_whitespace_boundary_preserved_across_all_alignments(self, align):
        """Alignment padding must never corrupt user's whitespace-boundary cell values."""
        cell = " target "
        m = TableCellsModel()
        m.has_header = True
        m.rows = [["H"], [cell]]
        m.aligns = [align]

        md = "\n".join(m.table_lines())
        m2 = TableCellsModel()
        m2.load_markdown(md)
        assert m2.rows[1][0] == cell


# ===========================================================================
# STAGE 3: DIRECT CELL EDIT VALIDATION
# ===========================================================================

class TestStage3DirectCellEditValidation:
    """Validate that TableCellsModel.setData refuses unrepresentable multiline data

    before mutation, retains exact state, emits no signals, and provides usable feedback.
    """

    def test_set_data_lf_refused(self):
        m = _create_model()
        before = [list(r) for r in m.rows]
        assert not m.setData(m.index(1, 0), "line1\nline2")
        assert m.rows == before
        assert "line break" in m.edit_refusal

    def test_set_data_cr_refused(self):
        m = _create_model()
        before = [list(r) for r in m.rows]
        assert not m.setData(m.index(1, 0), "line1\rline2")
        assert m.rows == before
        assert "line break" in m.edit_refusal

    def test_set_data_crlf_refused(self):
        m = _create_model()
        before = [list(r) for r in m.rows]
        assert not m.setData(m.index(1, 0), "line1\r\nline2")
        assert m.rows == before
        assert "line break" in m.edit_refusal

    def test_header_cell_newline_refused(self):
        m = _create_model()
        before_header = list(m.rows[0])
        assert not m.setData(m.index(0, 0), "Col1\nCol2")
        assert m.rows[0] == before_header
        assert "line break" in m.edit_refusal

    def test_unicode_plus_newline_refused(self):
        m = _create_model()
        before = [list(r) for r in m.rows]
        assert not m.setData(m.index(1, 0), "Ünïcødé\n🙂")
        assert m.rows == before
        assert "line break" in m.edit_refusal

    def test_failed_edit_emits_no_data_changed(self):
        m = _create_model()
        emitted = []
        m.dataChanged.connect(lambda tl, br, roles: emitted.append((tl.row(), tl.column())))
        assert not m.setData(m.index(1, 0), "bad\ncell")
        assert len(emitted) == 0

    def test_valid_edit_succeeds_and_round_trips(self):
        m = _create_model()
        emitted = []
        m.dataChanged.connect(lambda tl, br, roles: emitted.append((tl.row(), tl.column())))
        assert m.setData(m.index(1, 0), "valid_edit")
        assert m.rows[1][0] == "valid_edit"
        assert len(emitted) == 1
        assert m.edit_refusal == ""

        # Round trip through save/reload
        md = "\n".join(m.table_lines())
        m2 = TableCellsModel()
        m2.load_markdown(md)
        assert m2.rows[1][0] == "valid_edit"


# ===========================================================================
# STAGE 4: FULL TABLE ROUND-TRIP INVARIANT
# ===========================================================================

class TestStage4FullTableRoundTripInvariant:
    """Establish the complete chain:

    GRID -> encode_grid -> decode_grid -> paste_tsv -> table_lines -> parse -> TableCellsModel -> GRID
    """

    def _execute_full_round_trip(self, grid: list[list[str]], has_header: bool = True) -> list[list[str]]:
        # 1. Encode grid to TSV
        tsv = codec.encode_grid(grid)
        # 2. Decode grid from TSV
        decoded = codec.decode_grid(tsv)
        assert decoded == grid, f"Codec mismatch: decoded={decoded} != grid={grid}"

        # 3. Model paste
        m = TableCellsModel()
        # Seed an empty table of appropriate width
        width = len(grid[0]) if grid else 1
        m.load_markdown("| " + " | ".join(f"C{i}" for i in range(width)) + " |\n| " + " | ".join(["---"] * width) + " |\n| " + " | ".join([""] * width) + " |\n")
        m.has_header = has_header
        # Paste at (0, 0)
        rows_pasted, cols_pasted = m.paste_tsv(0, 0, tsv)
        assert (rows_pasted, cols_pasted) == (len(grid), len(grid[0]))

        # 4. Serialize to Markdown lines
        lines = m.table_lines()
        md_text = "\n".join(lines)

        # 5. Parse and reload into fresh model
        m2 = TableCellsModel()
        m2.load_markdown(md_text)

        # Return grid slice corresponding to input
        return [row[:len(grid[0])] for row in m2.rows[:len(grid)]]

    def test_mixed_empty_and_nonempty_rows(self):
        grid = [
            ["H1", "H2"],
            ["", ""],
            ["data1", ""],
            ["", "data2"],
            ["", ""],
        ]
        result = self._execute_full_round_trip(grid)
        assert result == grid

    def test_single_column_table_with_trailing_empty_rows(self):
        grid = [
            ["Header"],
            ["x"],
            [""],
            ["y"],
            [""],
            [""],
        ]
        result = self._execute_full_round_trip(grid)
        assert result == grid

    def test_multi_column_whitespace_and_unicode_table(self):
        grid = [
            ["ColA", "ColB", "ColC"],
            [" leading", "trailing ", " both "],
            ["", "   ", "tab\there"],
            ["path\\", "pipe|here", "🦄|🌈"],
        ]
        result = self._execute_full_round_trip(grid)
        assert result == grid

    def test_silo_prose_preservation_with_table_splice(self):
        prefix = ["# Title", "", "Introductory note."]
        suffix = ["", "Footer text after table.", "End of silo."]

        table_grid = [
            ["Name", "Score"],
            ["Alice", "95"],
            ["Bob", " 88 "],
        ]
        tsv = codec.encode_grid(table_grid)
        m = TableCellsModel()
        m.load_markdown("| A | B |\n| --- | --- |\n| 1 | 2 |\n")
        m.paste_tsv(0, 0, tsv)

        table_md = m.table_lines()
        full_doc = silo_region.splice(prefix, table_md, suffix)
        full_doc_lines = full_doc.split("\n")

        # Verify surrounding text
        assert full_doc_lines[:len(prefix)] == prefix
        assert full_doc_lines[-len(suffix):] == suffix

        # Parse region and reload
        span = silo_region.table_region(full_doc_lines)
        assert span is not None
        region_lines = full_doc_lines[span[0]:span[1] + 1]

        m2 = TableCellsModel()
        m2.load_markdown("\n".join(region_lines))
        assert m2.rows[0] == ["Name", "Score"]
        assert m2.rows[1] == ["Alice", "95"]
        assert m2.rows[2] == ["Bob", " 88 "]

    def test_paste_over_existing_values_with_table_expansion(self):
        """Pasting a 3x3 grid into a 2x2 table must overwrite and expand seamlessly."""
        m = TableCellsModel()
        m.load_markdown("| A | B |\n| --- | --- |\n| 1 | 2 |\n")
        assert m.rowCount() == 2
        assert m.columnCount() == 2

        incoming = [
            ["NewA", "NewB", "NewC"],
            ["X1", "X2", "X3"],
            ["Y1", "Y2", "Y3"],
        ]
        tsv = codec.encode_grid(incoming)
        rows_w, cols_w = m.paste_tsv(0, 0, tsv)
        assert (rows_w, cols_w) == (3, 3)

        lines = m.table_lines()
        m2 = TableCellsModel()
        m2.load_markdown("\n".join(lines))
        assert m2.rows == incoming

    def test_multiple_tables_in_one_silo_independent(self):
        """Editing one table must not perturb another table in the same silo."""
        doc = [
            "# Multi Table Silo",
            "",
            "| T1A | T1B |",
            "| :--- | ---: |",
            "| alpha | beta |",
            "",
            "Middle prose between tables.",
            "",
            "| T2A | T2B |",
            "| :--- | ---: |",
            "| 100 | 200 |",
            "",
            "End footer.",
        ]

        t1 = st.parse(doc, 2)
        assert t1 is not None and t1.rows[1] == ["alpha", "beta"]

        t2 = st.parse(doc, 8)
        assert t2 is not None and t2.rows[1] == ["100", "200"]

        # Mutate table 1 through model
        m1 = TableCellsModel()
        m1.rows = [list(r) for r in t1.rows]
        m1.aligns = list(t1.aligns)
        m1.has_header = t1.has_header
        m1.rows[1][0] = "  alpha_updated  "

        # Splice table 1 back into doc
        doc_updated = silo_region.splice(doc[:t1.first_block], m1.table_lines(), doc[t1.last_block + 1:]).split("\n")

        # Parse table 2 from updated doc
        t2_reloaded = st.parse(doc_updated, 8)
        assert t2_reloaded is not None
        assert t2_reloaded.rows[1] == ["100", "200"], "Table 2 must remain completely intact"

        # Parse table 1 from updated doc
        t1_reloaded = st.parse(doc_updated, 2)
        assert t1_reloaded is not None
        assert st.unescape(t1_reloaded.rows[1][0]) == "  alpha_updated  "

    def test_randomized_seeded_full_chain_audit(self):
        """Stress-test full chain with 200 randomized grids covering all token types."""
        rng = random.Random(42)
        tokens = [
            "", " ", "   ", "x", "  x", "x  ", " x ", "a\tb", "pipe|here",
            "path\\", "path\\\\", "C:\\Users", "🦄|🌈", "日本語", 'quote"word',
            "0", "42"
        ]

        for case_idx in range(200):
            n_rows = rng.randint(1, 5)
            n_cols = rng.randint(1, 4)
            grid = [[rng.choice(tokens) for _ in range(n_cols)] for _ in range(n_rows)]

            # Chain: encode -> decode -> paste_tsv -> table_lines -> parse -> TableCellsModel
            tsv = codec.encode_grid(grid)
            decoded = codec.decode_grid(tsv)
            assert decoded == grid, f"Codec failed on case {case_idx}"

            m = TableCellsModel()
            m.load_markdown("| " + " | ".join(f"C{c}" for c in range(n_cols)) + " |\n| " + " | ".join(["---"] * n_cols) + " |\n| " + " | ".join([""] * n_cols) + " |\n")
            rows_w, cols_w = m.paste_tsv(0, 0, tsv)
            assert (rows_w, cols_w) == (n_rows, n_cols)

            md = "\n".join(m.table_lines())
            m2 = TableCellsModel()
            m2.load_markdown(md)
            result_grid = [row[:n_cols] for row in m2.rows[:n_rows]]
            assert result_grid == grid, (
                f"Full round-trip failed on case {case_idx}:\n"
                f"Input: {grid}\n"
                f"Output: {result_grid}\n"
                f"Markdown:\n{md}"
            )
