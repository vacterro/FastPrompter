"""Mission hardening tests for clipboard TSV codec, atomic model paste, and whitespace semantics.

Covers Stages 1, 2, and 3:
- Stage 1: P1 Scanner / decoder divergence repair & invariant
- Stage 2: P1 Atomic model paste hardening & validation
- Stage 3: P2 Whitespace-only clipboard semantics
"""

from __future__ import annotations

import os
import random
import sys

sys.path.insert(0, os.path.abspath(
    os.path.join(os.path.dirname(__file__), "../src")))

import pytest
from PyQt6.QtWidgets import QApplication

from fastprompter.ui import clipboard_tsv as codec
from fastprompter.ui.table_model import TableCellsModel

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
_APP = QApplication.instance() or QApplication([])

TABLE = (
    "| Col1 | Col2 |\n"
    "| :--- | ---: |\n"
    "| val1 | val2 |\n"
    "| val3 | val4 |\n"
)


def _model(text=TABLE):
    m = TableCellsModel()
    m.load_markdown(text)
    return m


def _shape_of(grid):
    if not grid:
        return 0, 0
    return len(grid), max((len(r) for r in grid), default=0)


# ===========================================================================
# STAGE 1: SCANNER / DECODER DIVERGENCE & INVARIANT TESTS
# ===========================================================================

class TestStage1ScannerDecoderDivergence:
    def test_minimal_counterexample_matches(self):
        """Minimal counterexample: 'a\"\\r\"'."""
        payload = 'a"\r"'
        scan = codec.scan_shape(payload)
        grid = codec.decode_grid(payload)
        assert scan == _shape_of(grid)
        assert scan == (2, 1)
        assert grid == [['a"'], ['"']]

    def test_amplified_counterexample_matches(self):
        """Amplified counterexample: 'a\"' + ('x\\n' * 10001) + '\"'."""
        payload = 'a"' + ('x\n' * 10001) + '"'
        scan = codec.scan_shape(payload)
        grid = codec.decode_grid(payload)
        assert scan == _shape_of(grid)
        assert scan == (10002, 1)
        assert len(grid) == 10002

    def test_empty_string_shape_convention(self):
        """Zero-row shape convention: empty payload produces (0, 0)."""
        assert codec.scan_shape("") == (0, 0)
        assert codec.decode_grid("") == []

    def test_all_newlines_shape_convention(self):
        """All-newline payloads produce (0, 0) and empty grid."""
        for nl in ("\n", "\r\n", "\n\n", "\r\n\r\n\r\n"):
            assert codec.scan_shape(nl) == (0, 0)
            assert codec.decode_grid(nl) == []

    PAYLOADS = [
        # 1. Quote at start of field
        '"hello"',
        '"hello"\t"world"',
        # 2. Quote after ordinary unquoted text
        'a"b\tc"d',
        'start"mid"end',
        # 3. Quote immediately before CR
        'test"\r\nother',
        '"quoted"\r"second"',
        # 4. Quote immediately before LF
        'test"\nother',
        # 5. Quote before CRLF
        'line1"\r\nline2',
        # 6. Quote followed by invalid closing sequence
        '"hello"world\tnext',
        '"a"b"c"',
        # 7. Doubled quotes
        '""',
        '""""',
        '"say ""hello"" to me"',
        '""\t""\n""\t""',
        # 8. Unterminated quoted fields
        '"unterminated',
        '"unterminated\tfield2',
        'field1\t"unterminated\nfield2',
        # 9. Quote inside a plain text field
        'plain "quote" inside',
        '5\'11" tall',
        # 10. Multiple quotes in one field
        '"""a"""b"""c"""',
        'a"b"c"d"e',
        # 11. Mixed quoted and unquoted fields
        'plain\t"quoted"\tplain2\t"another"',
        '"quoted1"\tunquoted\t"quoted2"\r\nrow2',
        # 12. Consecutive blank rows
        'a\tb\n\n\nc\td',
        'row1\n\n\n\nrow2',
        # 13. Trailing empty fields
        'a\tb\t\t',
        'a\t\t\n',
        'a\tb\t\tc\t\t',
        # 14. Unicode
        'Ünïcødé\t"日本語"\t"emoji 😀"\n"\u043a\u0438\u0440\u0438\u043b\u043b\u0438\u0446\u0430"\tplain',
        # 15. Literal tab inside quoted field
        '"cell\twith\ttabs"\tordinary',
        # 16. Literal newline inside quoted field
        '"cell\nwith\nnewlines"\tordinary',
        '"cell\r\nwith\r\ncrlf"\tordinary',
        # 17. Very large quoted field
        '"' + ('a' * 50000) + '"\tordinary',
        # 18. Extremely long malformed payload
        'a"' * 10000,
        # 19. Thousands of rows hidden behind mid-field quote
        'prefix"' + ('line\n' * 500) + '"',
        # 20. Repeated malicious-looking quote patterns
        '"""\r"""\n"""\t"""' * 50,
    ]

    @pytest.mark.parametrize("payload", PAYLOADS, ids=[f"neg_case_{i+1}" for i in range(len(PAYLOADS))])
    def test_twenty_negative_regressions_invariant(self, payload):
        """Scanner and decoder must agree on exact dimensions across all 20 patterns."""
        scan = codec.scan_shape(payload)
        grid = codec.decode_grid(payload)
        assert scan == _shape_of(grid), f"Divergence on payload: {payload[:100]!r}"

    def test_seeded_random_combinatorial_invariant(self):
        """Random combinations of tokens must satisfy the core invariant."""
        rng = random.Random(42)
        tokens = ['"', '""', '\t', '\n', '\r', '\r\n', 'a', 'x', ' ', '  ', '日本語', '123', '']
        for _ in range(500):
            n_tokens = rng.randint(1, 30)
            payload = "".join(rng.choice(tokens) for _ in range(n_tokens))
            scan = codec.scan_shape(payload)
            grid = codec.decode_grid(payload)
            assert scan == _shape_of(grid), f"Random seed failure on: {payload!r}"


# ===========================================================================
# STAGE 2: ATOMIC MODEL PASTE HARDENING & VALIDATION
# ===========================================================================

class TestStage2AtomicModelPasteHardening:
    def test_invalid_negative_coordinates_refused(self):
        m = _model()
        before_rows = [list(r) for r in m.rows]
        assert m.paste_tsv(-1, 0, "a\tb") == (0, 0)
        assert "Invalid paste destination" in m.paste_refusal
        assert m.rows == before_rows

        assert m.paste_tsv(0, -1, "a\tb") == (0, 0)
        assert "Invalid paste destination" in m.paste_refusal
        assert m.rows == before_rows

    def test_paste_exceeding_resulting_cell_budget_refused(self):
        m = _model()
        before_rows = [list(r) for r in m.rows]
        # Bounded by _PASTE_MAX_CELLS (4,000,000)
        # 2001 cols x 2000 rows = 4,002,000 cells > 4,000,000
        # Even if individual dims fit within 10,000 rows and 2,000 cols,
        # total cells must not exceed budget.
        # Construct payload with 2001 cols
        payload = "\t".join(f"c{i}" for i in range(2001))
        assert m.paste_tsv(0, 0, payload) == (0, 0)
        assert "would exceed the table budget" in m.paste_refusal
        assert m.rows == before_rows

    def test_multiline_cell_refused_without_mutating_model(self):
        m = _model()
        before_rows = [list(r) for r in m.rows]
        assert m.paste_tsv(0, 0, '"line1\nline2"') == (0, 0)
        assert "contains a line break" in m.paste_refusal
        assert m.rows == before_rows

    def test_parser_shape_divergence_fails_closed(self, monkeypatch):
        """Even if scanner and decoder are forced to diverge, model fails closed."""
        m = _model()
        before_rows = [list(r) for r in m.rows]
        # Monkeypatch scan_shape to lie
        monkeypatch.setattr(codec, "scan_shape", lambda p: (1, 1))
        # Payload actually decodes to 2 rows
        payload = "r1\nr2"
        assert m.paste_tsv(0, 0, payload) == (0, 0)
        assert "parser shape divergence" in m.paste_refusal
        assert m.rows == before_rows

    def test_paste_at_boundary_expands_both_dimensions_atomically(self):
        m = _model()
        # Original: 3 rows (header + 2 rows), 2 cols
        # Paste 2x2 at (3, 2)
        rows, cols = m.paste_tsv(3, 2, "new1\tnew2\nnew3\tnew4")
        assert (rows, cols) == (2, 2)
        assert m.rowCount() == 5
        assert m.columnCount() == 4
        assert m.rows[3][2] == "new1"
        assert m.rows[3][3] == "new2"
        assert m.rows[4][2] == "new3"
        assert m.rows[4][3] == "new4"

    def test_exact_dimensions_reported(self):
        m = _model()
        rows, cols = m.paste_tsv(1, 1, "x1\tx2\tx3\ny1\ty2\ty3")
        assert (rows, cols) == (2, 3)

    def test_refusal_emits_no_data_changed_or_layout_changed(self):
        m = _model()
        data_changed_events = []
        layout_changed_events = []
        m.dataChanged.connect(lambda *a: data_changed_events.append(a))
        m.layoutChanged.connect(lambda *a: layout_changed_events.append(a))

        # Refused due to multiline
        m.paste_tsv(0, 0, '"a\nb"')
        assert len(data_changed_events) == 0
        assert len(layout_changed_events) == 0

        # Refused due to negative coords
        m.paste_tsv(-1, -1, "valid")
        assert len(data_changed_events) == 0
        assert len(layout_changed_events) == 0

    def test_undo_and_redo_of_accepted_paste_via_markdown_roundtrip(self):
        m = _model()
        orig_md = "\n".join(m.table_lines())
        m.paste_tsv(1, 0, "alpha\tbeta\ngamma\tdelta")
        pasted_md = "\n".join(m.table_lines())
        assert orig_md != pasted_md

        # Simulate undo by reloading original
        m.load_markdown(orig_md)
        assert m.rows[1][0] == "val1"
        assert m.rows[2][0] == "val3"

        # Simulate redo by reloading pasted
        m.load_markdown(pasted_md)
        assert m.rows[1][0] == "alpha"
        assert m.rows[2][0] == "gamma"


# ===========================================================================
# STAGE 3: WHITESPACE-ONLY CLIPBOARD SEMANTICS
# ===========================================================================

class TestStage3WhitespaceOnlyClipboardSemantics:
    def test_copy_and_paste_single_space(self):
        """Test A: Copy and paste a single space."""
        m = _model()
        rows, cols = m.paste_tsv(1, 0, " ")
        assert (rows, cols) == (1, 1)
        assert m.rows[1][0] == " "

    def test_copy_and_paste_multiple_spaces(self):
        """Test B: Copy and paste multiple spaces."""
        m = _model()
        rows, cols = m.paste_tsv(1, 0, "   ")
        assert (rows, cols) == (1, 1)
        assert m.rows[1][0] == "   "

    def test_paste_two_empty_cells_over_populated_cells(self):
        """Test C: Paste two empty cells over two populated cells."""
        m = _model()
        assert m.rows[1][:2] == ["val1", "val2"]
        rows, cols = m.paste_tsv(1, 0, "\t")
        assert (rows, cols) == (1, 2)
        assert m.rows[1][:2] == ["", ""]

    def test_paste_trailing_empty_columns(self):
        """Test D: Paste trailing empty columns."""
        m = _model()
        rows, cols = m.paste_tsv(1, 0, "valA\t\t")
        assert (rows, cols) == (1, 3)
        assert m.rows[1][0] == "valA"
        assert m.rows[1][1] == ""
        assert m.rows[1][2] == ""

    def test_copy_and_paste_completely_empty_selected_range(self):
        """Test E: Copy and paste a completely empty selected range."""
        m = _model()
        # Set 2x2 cells to empty
        m.rows[1][0] = ""
        m.rows[1][1] = ""
        m.rows[2][0] = ""
        m.rows[2][1] = ""
        # Copy 2x2 range
        indexes = [
            m.index(1, 0), m.index(1, 1),
            m.index(2, 0), m.index(2, 1)
        ]
        tsv = m.clipboard_range(indexes)
        assert tsv == "\t\n\t"

        # Now paste into another model
        m2 = _model()
        assert m2.rows[1][:2] == ["val1", "val2"]
        assert m2.rows[2][:2] == ["val3", "val4"]
        rows, cols = m2.paste_tsv(1, 0, tsv)
        assert (rows, cols) == (2, 2)
        assert m2.rows[1][:2] == ["", ""]
        assert m2.rows[2][:2] == ["", ""]

    def test_copy_and_paste_single_empty_cell(self):
        """Distinguish empty selection from single empty cell."""
        m = _model()
        # Empty selection returns ""
        assert m.clipboard_range([]) == ""

        # Single empty cell returns '""' (quoted empty field)
        m.rows[1][0] = ""
        idx = [m.index(1, 0)]
        tsv = m.clipboard_range(idx)
        assert tsv == '""'

        # Pasting '""' writes an empty cell over a populated cell
        m2 = _model()
        assert m2.rows[1][0] == "val1"
        rows, cols = m2.paste_tsv(1, 0, tsv)
        assert (rows, cols) == (1, 1)
        assert m2.rows[1][0] == ""

    def test_empty_clipboard_remains_safe_noop(self):
        """Test F: Empty clipboard remains a safe no-op."""
        m = _model()
        before_rows = [list(r) for r in m.rows]
        assert m.paste_tsv(1, 0, "") == (0, 0)
        assert m.paste_tsv(1, 0, None) == (0, 0)
        assert m.paste_tsv(1, 0, "\n\n\n") == (0, 0)
        assert m.rows == before_rows

    def test_empty_strings_do_not_delete_table_structure(self):
        """Test G: Empty strings do not unexpectedly delete table structure."""
        m = _model()
        orig_row_count = m.rowCount()
        orig_col_count = m.columnCount()
        m.paste_tsv(1, 0, "")
        assert m.rowCount() == orig_row_count
        assert m.columnCount() == orig_col_count
