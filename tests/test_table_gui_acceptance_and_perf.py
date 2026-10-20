"""Stage 6: Windows GUI Acceptance & Performance Verification.

1. Performance under load:
   - 200x20 cell table paste runs in < 500ms on model/codec layer.
   - Clean signal emission (dataChanged, beginInsertRows) without exponential accumulation.
2. UI interaction & semantic acceptance:
   - Selection copy -> paste back preserves exact formatting without mutating
     neighboring unselected cells.
   - Multiline cell in quotes (e.g. "line1\\nline2") is atomically refused to
     protect markdown storage invariants without mutating table state.
"""

from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.abspath(
    os.path.join(os.path.dirname(__file__), "../src")))

from PyQt6.QtWidgets import QApplication

from fastprompter.ui import clipboard_tsv as codec
from fastprompter.ui.table_model import TableCellsModel

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
_APP = QApplication.instance() or QApplication([])


def test_200x20_load_performance():
    """Paste of 200x20 (4000 cells) table runs under 500ms."""
    rows = 200
    cols = 20
    data = [
        [f"R{r}C{c}" for c in range(cols)]
        for r in range(rows)
    ]
    payload = "\n".join("\t".join(row) for row in data)

    m = TableCellsModel()
    m.load_markdown("| A |\n| --- |\n| 1 |")

    start = time.perf_counter()
    n_r, n_c = m.paste_tsv(0, 0, payload)
    elapsed = time.perf_counter() - start

    assert (n_r, n_c) == (rows, cols), f"Expected ({rows}, {cols}), got ({n_r}, {n_c})"
    assert len(m.rows) >= rows
    assert m.rows[0][0] == "R0C0"
    assert m.rows[199][19] == "R199C19"
    # Budget requirement: runs in under 500ms (0.5s)
    assert elapsed < 0.5, f"Paste took {elapsed:.4f}s, expected < 0.5s"


def test_model_signal_cleanliness_under_load():
    """Verify signals fire cleanly without exponential accumulation."""
    m = TableCellsModel()
    m.load_markdown("| A | B |\n| --- | --- |\n| 1 | 2 |")

    signal_counts = {
        "dataChanged": 0,
        "rowsInserted": 0,
        "columnsInserted": 0,
    }
    m.dataChanged.connect(lambda *_: signal_counts.__setitem__(
        "dataChanged", signal_counts["dataChanged"] + 1))
    m.rowsInserted.connect(lambda *_: signal_counts.__setitem__(
        "rowsInserted", signal_counts["rowsInserted"] + 1))
    m.columnsInserted.connect(lambda *_: signal_counts.__setitem__(
        "columnsInserted", signal_counts["columnsInserted"] + 1))

    # Paste a 50x10 grid into a 2x2 model
    rows = 50
    cols = 10
    payload = "\n".join("\t".join(f"val_{r}_{c}" for c in range(cols)) for r in range(rows))
    n_r, n_c = m.paste_tsv(0, 0, payload)
    assert (n_r, n_c) == (rows, cols)

    # In atomic paste, dataChanged fires exactly once for the updated region
    assert signal_counts["dataChanged"] == 1
    # Row and column insertion signals fire cleanly once for expansion
    assert signal_counts["rowsInserted"] == 1
    assert signal_counts["columnsInserted"] == 1


def test_selection_copy_paste_preserves_neighbors():
    """Selection range copy -> paste back preserves exact formatting and does not mutate neighbors."""
    m = TableCellsModel()
    md = (
        "| A | B | C | D |\n"
        "| --- | --- | --- | --- |\n"
        "| 1 | 2 | 3 | 4 |\n"
        "| 5 | 6 | 7 | 8 |\n"
        "| 9 | 10 | 11 | 12 |\n"
    )
    m.load_markdown(md)
    # Header: row 0 (A, B, C, D)
    # Data: row 1 (1, 2, 3, 4), row 2 (5, 6, 7, 8), row 3 (9, 10, 11, 12)

    # Encode subgrid (rows 2..3, cols 1..2 -> [[6, 7], [10, 11]])
    subgrid = [
        [m.rows[r][c] for c in (1, 2)]
        for r in (2, 3)
    ]
    assert subgrid == [["6", "7"], ["10", "11"]]
    tsv = codec.encode_grid(subgrid)

    # Check state before paste
    assert m.rows[1][0] == "1"
    assert m.rows[1][1] == "2"
    assert m.rows[2][0] == "5"
    assert m.rows[2][3] == "8"
    assert m.rows[3][0] == "9"
    assert m.rows[3][3] == "12"

    # Paste back to row 2, col 1
    n_r, n_c = m.paste_tsv(2, 1, tsv)
    assert (n_r, n_c) == (2, 2)

    # Targeted cells intact
    assert m.rows[2][1] == "6"
    assert m.rows[2][2] == "7"
    assert m.rows[3][1] == "10"
    assert m.rows[3][2] == "11"

    # Neighbors completely unchanged
    assert m.rows[1][0] == "1"
    assert m.rows[1][1] == "2"
    assert m.rows[2][0] == "5"
    assert m.rows[2][3] == "8"
    assert m.rows[3][0] == "9"
    assert m.rows[3][3] == "12"


def test_quoted_multiline_cell_refused_atomically_to_protect_markdown():
    """Paste of cell with newline in quotes is refused to prevent markdown table corruption."""
    m = TableCellsModel()
    m.load_markdown("| Col1 | Col2 |\n| --- | --- |\n| A | B |\n| C | D |")
    before = [list(r) for r in m.rows]

    # RFC-4180 multiline field: "line1\nline2"
    payload = '"line1\nline2"'
    n_r, n_c = m.paste_tsv(0, 0, payload)

    # Must refuse (0, 0) without mutating rows
    assert (n_r, n_c) == (0, 0)
    assert m.rows == before
    assert "line break" in m.paste_refusal


def test_quoted_multiline_grid_refused_atomically():
    """2x2 grid with embedded newlines is refused atomically."""
    m = TableCellsModel()
    m.load_markdown("| A | B |\n| --- | --- |\n| . | . |")
    before = [list(r) for r in m.rows]

    payload = '"multi\nline"\t"has\ttab"\n"plain"\t"another\r\nline"'
    n_r, n_c = m.paste_tsv(0, 0, payload)

    assert (n_r, n_c) == (0, 0)
    assert m.rows == before
    assert "line break" in m.paste_refusal
