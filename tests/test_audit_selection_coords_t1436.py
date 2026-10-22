"""T-1436 (SRC-096 CORE-006, astral half) — Fast Pack Selection reads the
selection in PYTHON coordinates.

``QTextCursor.selectionStart()/selectionEnd()`` are UTF-16 code units, while
``doc_text`` is a Python string. One astral character anywhere before the
selection shifts every later Python index by one code point, so the naive
``doc_text[selectionStart():selectionEnd()]`` packs the WRONG slice -- the
payload, its line numbers and its coverage attribution all follow the shift.

The fix converts both endpoints with ``qt_to_py`` against ONE frozen document
snapshot, BEFORE token expansion runs in Python coordinates.
"""

from __future__ import annotations

from inspect import getsource

from fastprompter.main import FastPrompter
from fastprompter.ui.qt_text_coords import qt_to_py

# An emoji (2 UTF-16 units, 1 Python code point) before the selected line.
DOC = "note \U0001F600\nPICK ME\n"
LINE = "PICK ME\n"
PY_START = DOC.index(LINE)
PY_END = PY_START + len(LINE)
# Qt counts the emoji as two units, so the same span sits one unit later.
QT_START = PY_START + 1
QT_END = PY_END + 1

def test_core_006_raw_qt_positions_read_the_wrong_slice():
    # Control documenting the defect: this is what the call site used to do.
    shifted = DOC[QT_START:QT_END]
    assert shifted != LINE, shifted
    assert shifted == "ICK ME\n", shifted

def test_core_006_converting_both_endpoints_reads_the_selected_line():
    converted = (qt_to_py(DOC, QT_START), qt_to_py(DOC, QT_END))
    assert converted == (PY_START, PY_END)
    assert DOC[converted[0]:converted[1]] == LINE

def test_core_006_call_site_converts_before_expanding_in_python_coords():
    body = getsource(FastPrompter.fast_pack_selection)
    convert = body.index("qt_to_py(")
    expand = body.index("expand_selection_token_boundaries(")
    assert convert < expand, (
        "cursor endpoints must be converted to Python indexes before token "
        "expansion runs on them"
    )
    assert "cursor.selectionStart()" in body and "cursor.selectionEnd()" in body
    assert body.index("cursor.selectionStart()") > convert

def test_core_006_one_frozen_snapshot_feeds_the_conversion():
    body = getsource(FastPrompter.fast_pack_selection)
    snapshot = body.index("self._editor_text_snapshot()")
    convert = body.index("qt_to_py(")
    assert snapshot < convert
    # The converted span is what the payload slices on the GUI side and what the
    # frozen capture carries to the half that records coverage. PERF-001
    # (SRC-097) moved the recording itself into the completion half, so the
    # invariant is checked across the two methods: the converted span leaves the
    # capture and is what coverage records.
    assert "doc_text[exp_start:exp_end]" in body
    assert "\"selected_span\": (exp_start, exp_end)" in body
    finish = getsource(FastPrompter._fast_pack_complete)
    assert "selected_span=cap.get(\"selected_span\")" in finish
