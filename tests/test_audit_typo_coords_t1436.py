"""T-1436 (SRC-096 PERF-001) — the typo span boundary is batch AND snapshot-bound.

Two defects in one boundary:

* the complete span list was converted endpoint-by-endpoint with ``py_to_qt``,
  which encodes the whole prefix per endpoint -- O(N*K) for K spans;
* ``_typo_apply_spans`` re-materialized the LIVE document with
  ``toPlainText()`` on the GUI result path, even though the scan had been
  accepted for an immutable snapshot the caller already held. The conversion
  then ran against text that could have moved.

The batch converter must be exactly equivalent to the old form (it is the same
contract, just measured once), and the accepted-result path must convert
against the retained snapshot.
"""

from __future__ import annotations

import random

import pytest
from PyQt6.QtWidgets import QPlainTextEdit

from fastprompter.main import FastPrompter
from fastprompter.ui.qt_text_coords import (
    convert_spans_py_to_qt,
    py_to_qt,
    qt_units,
)


def _per_endpoint(s, spans):
    return [(py_to_qt(s, a), py_to_qt(s, b)) for a, b in spans]


def test_perf_001_batch_converter_is_exactly_the_per_endpoint_form():
    rng = random.Random(1436)
    docs = [
        "",
        "plain ascii only",
        "\U0001F600",                        # one astral character
        "a\U0001F600b",
        "x\U0001F600\U0001F999y",            # two astral characters
        "\u00e9\u0301 combining",
        "\u65e5\u672c\u8a9e\U0001F600z",
    ]
    cases = 0
    for doc in docs:
        for _ in range(60):
            count = rng.randint(0, 6)
            spans = []
            for _ in range(count):
                a = rng.randint(0, len(doc))
                b = rng.randint(0, len(doc))
                spans.append((a, b) if a <= b else (b, a))
            assert convert_spans_py_to_qt(doc, spans) == _per_endpoint(doc, spans)
            cases += 1
    assert cases == 420

def test_perf_001_empty_span_list_converts_to_empty():
    assert convert_spans_py_to_qt("anything \U0001F600", []) == []

def test_perf_001_endpoints_are_clamped_like_py_to_qt():
    doc = "a\U0001F600b"
    assert convert_spans_py_to_qt(doc, [(-5, 0)]) == [(0, 0)]
    assert convert_spans_py_to_qt(doc, [(0, 99)]) == [(0, qt_units(doc))]
    assert convert_spans_py_to_qt(doc, [(1, 2)]) == [
        (py_to_qt(doc, 1), py_to_qt(doc, 2))
    ]

class _NoLiveRead(QPlainTextEdit):
    """An editor whose live document must NOT be read: the accepted path has a
    snapshot, so a ``toPlainText()`` here is the defect under test."""

    def toPlainText(self):  # noqa: N802 - Qt override
        raise AssertionError("live document read on the accepted-result path")

class _Win:
    def __init__(self, editor):
        self.text_area = editor
        self.data = {"typo_color": "#e05555"}

    _typo_apply_spans = FastPrompter._typo_apply_spans


def test_perf_001_accepted_path_converts_against_the_retained_snapshot(qapp):
    editor = _NoLiveRead()
    win = _Win(editor)
    snapshot = "ab\U0001F600cd"
    win._typo_apply_spans([(2, 3)], source_text=snapshot)
    # Qt spans, converted against the SNAPSHOT (no live read happened).
    assert editor._typo_spans == [(2, 4)]

def test_perf_001_without_a_snapshot_the_live_document_is_still_read(qapp):
    editor = _NoLiveRead()
    win = _Win(editor)
    with pytest.raises(AssertionError):
        win._typo_apply_spans([(0, 1)])


def test_perf_001_checked_in_check_tick_retains_the_scanned_snapshot():
    """The in-flight request carries the exact text the worker scanned, and the
    completion hands it back to the converter instead of re-reading."""
    from inspect import getsource

    tick = getsource(FastPrompter._typo_check_tick)
    assert "_typo_inflight = (request_id, ident, doc_rev, text)" in tick
    scanned = getsource(FastPrompter._on_typo_scanned)
    assert "_rid, ident, doc_rev, snap_text = inflight" in scanned
    assert "self._typo_apply_spans(spans, source_text=snap_text)" in scanned
    dispatch = getsource(FastPrompter._dispatch_pending_typo_scan)
    assert "self._typo_inflight = (_rid, _ident, _rev, _text)" in dispatch
