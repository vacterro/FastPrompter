"""T-1432 (SRC-093) — PERF-001 Pack Coverage scaling suite.

Proves the two eliminated defects: per-requirement linear ledger scans during
reconciliation, and O(visible_lines * requirements) paint lookup, plus the
one-inflight/one-latest off-thread reconciliation whose stale results can
never be painted.
"""

from __future__ import annotations

import inspect
import time

from PyQt6.QtGui import QPainter, QPixmap
from PyQt6.QtWidgets import QApplication

from fastprompter.core import silo_coverage as sc
from fastprompter.ui.editor import VaultTextEdit

_APP = None


def _app():
    """One process-wide QApplication, held so Qt cannot outlive its owner."""
    global _APP
    if _APP is None:
        _APP = QApplication.instance() or QApplication([])
    return _APP


# --- equivalence: indexed lookup == legacy first-match scan ----------------

def _legacy_line_state(cmap, line_no):
    """The pre-PERF-001 lookup, kept here as the equivalence oracle."""
    for item in cmap.requirements:
        if item.line_start <= line_no <= item.line_end:
            return item.state, item
    return None, None


def _items():
    """Deliberately overlapping + multi-line + duplicate-line ranges."""
    return (
        sc.CoverageItem("R1", 1, 3, "a", sc.CoverageState.FULL, None),
        sc.CoverageItem("R2", 2, 2, "b", sc.CoverageState.FRESH, None),
        sc.CoverageItem("R3", 3, 6, "c", sc.CoverageState.PARTIAL, None),
        sc.CoverageItem("R4", 3, 4, "d", sc.CoverageState.RECENT_FULL, None),
        sc.CoverageItem("R5", 9, 9, "e", sc.CoverageState.RECENT_PARTIAL, None),
        sc.CoverageItem("R6", 12, 11, "f", sc.CoverageState.FRESH, None),  # empty
    )


def test_perf_001_indexed_lookup_matches_linear_reference_on_every_line():
    cmap = sc.CoverageMap(requirements=_items())
    for line_no in range(0, 15):
        want_state, want_item = _legacy_line_state(cmap, line_no)
        got_state, got_item = cmap.get_line_state(line_no)
        assert got_state == want_state, line_no
        assert got_item is want_item, line_no


def test_perf_001_overlapping_range_owner_is_the_first_tuple_match():
    cmap = sc.CoverageMap(requirements=_items())
    # Line 3 is claimed by R1 (1-3) and R3 (3-6); tuple order decides. Line 4
    # is claimed by R3 and R4; line 2 by R1 and R2.
    assert cmap.get_line_state(3)[1].req_id == "R1"
    assert cmap.get_line_state(2)[1].req_id == "R1"
    assert cmap.get_line_state(4)[1].req_id == "R3"
    assert cmap.get_line_state(6)[1].req_id == "R3"


def test_perf_001_indexed_lookup_matches_reference_on_a_real_document():
    text = _doc(120)
    ledger = sc.CoverageLedger()
    ledger.record_event(_event(text, 0, 40))
    cmap = sc.reconcile_pack_coverage(text, ledger)
    for line_no in range(1, 260):
        want = _legacy_line_state(cmap, line_no)
        got = cmap.get_line_state(line_no)
        assert got[0] == want[0], line_no
        assert got[1] is want[1], line_no


# --- no per-requirement linear ledger scan --------------------------------

class _SpyIndex(dict):
    """A receipt index that counts every lookup it serves."""

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.lookups = 0

    def get(self, key, default=None):
        self.lookups += 1
        return super().get(key, default)


def _doc(count, prefix="-"):
    lines = ["# Requirements", ""]
    for i in range(count):
        lines.append(f"{prefix} Requirement number {i:04d}")
        lines.append("")
    return "\n".join(lines)


def _event(text, first, count, *, kind="full", epoch=1000.0, silo="silo_1"):
    """A coverage event covering requirements [first, first+count)."""
    idx_lines = []
    from fastprompter.core import silo_index
    idx = silo_index.build_silo_index(text, "source.md")
    reqs = list(idx.requirements)[first:first + count]
    receipts = []
    seen: dict[str, int] = {}
    for req in reqs:
        ckey = sc.requirement_coverage_key(req.text, req.media)
        seen[ckey] = seen.get(ckey, 0) + 1
        if kind == "partial":
            seg = (0, max(1, len(req.text) // 2))
        else:
            seg = None
        receipts.append(sc.RequirementCoverageReceipt(
            coverage_key=ckey, duplicate_ordinal=seen[ckey], coverage_kind=kind,
            covered_segment=seg, bundle_kind="silo_bundle", archive_name="a.zip",
            first_bundled_epoch=epoch, last_bundled_epoch=epoch, times_bundled=1))
    idx_lines = receipts
    return sc.BundleCoverageEvent(
        silo_id=silo, bundle_kind="silo_bundle", archive_name="a.zip",
        receipts=tuple(idx_lines), timestamp_epoch=epoch)


def test_perf_001_reconcile_performs_exactly_one_lookup_per_requirement():
    text = _doc(1000)
    ledger = sc.CoverageLedger()
    ledger.record_event(_event(text, 0, 50))
    ledger.record_event(_event(text, 60, 50, epoch=2000.0))
    assert len(ledger.entries) == 100

    spy = _SpyIndex(sc.build_receipt_index(ledger.entries))
    cmap = sc.reconcile_pack_coverage(text, spy)

    # 1000 requirements -> 1000 lookups. A linear scan would issue up to
    # 1000 * 100 = 100,000 comparisons against the ledger.
    assert spy.lookups == len(cmap.requirements) == 1000


def test_perf_001_ledger_and_prebuilt_index_agree():
    text = _doc(200)
    ledger = sc.CoverageLedger()
    ledger.record_event(_event(text, 0, 30))
    ledger.record_event(_event(text, 10, 30, kind="partial", epoch=3000.0))
    cutoff = 2500.0

    from_ledger = sc.reconcile_pack_coverage(text, ledger, cutoff)
    from_index = sc.reconcile_pack_coverage(
        text, sc.build_receipt_index(ledger.entries), cutoff)

    assert from_ledger == from_index
    assert from_ledger.fresh_count + from_ledger.covered_count + \
        from_ledger.partial_count == len(from_ledger.requirements)


def test_perf_001_duplicate_receipts_still_honour_first_match():
    text = _doc(5)
    ledger = sc.CoverageLedger()
    ledger.record_event(_event(text, 0, 5, kind="partial", epoch=100.0))
    # A second entry for the SAME (key, ordinal) — the ledger scan took the
    # first one; the index must too.
    first = ledger.entries[0]
    ledger.entries.append(sc.RequirementCoverageReceipt(
        coverage_key=first.coverage_key,
        duplicate_ordinal=first.duplicate_ordinal,
        coverage_kind="full",
        last_bundled_epoch=9999.0, times_bundled=5))

    cmap = sc.reconcile_pack_coverage(text, ledger)
    st, item = cmap.get_line_state(cmap.requirements[0].line_start)
    assert st == sc.CoverageState.PARTIAL
    assert item.receipt is first


# --- one-inflight / one-latest / stale refusal ----------------------------

class _Deferred:
    """Records requests instead of running them, so tests control completion."""

    def __init__(self):
        self.requests = []

    def __call__(self, request):
        self.requests.append(request)


def _reconciler(applied):
    runner = _Deferred()
    rec = sc.CoverageReconciler(runner, lambda token, value: applied.append((token, value)))
    return rec, runner


def test_perf_001_at_most_one_run_in_flight_and_one_pending():
    applied = []
    rec, runner = _reconciler(applied)

    rec.submit("A", "a")
    rec.submit("B", "b")
    rec.submit("C", "c")

    assert [t for t, _ in runner.requests] == ["A"]   # one in flight
    assert rec.in_flight is True

    rec.result("A", "value-a")                        # stale: newest is C
    assert [t for t, _ in runner.requests] == ["A", "C"]   # B was coalesced away
    assert applied == []

    rec.result("C", "value-c")
    assert applied == [("C", "value-c")]
    assert rec.in_flight is False
    assert rec.discarded == 1


def test_perf_001_newer_request_wins(tmp_path):
    applied = []
    rec, runner = _reconciler(applied)
    rec.submit("old", object())
    rec.submit("new", object())
    rec.result("old", "OLD")
    assert applied == []                              # older never applied
    rec.result("new", "NEW")
    assert applied == [("new", "NEW")]


def test_perf_001_synchronous_runner_applies_immediately():
    applied = []
    rec = sc.CoverageReconciler(lambda request: rec.result(
        request[0], f"done-{request[1]}"), lambda token, value: applied.append(value))
    rec.submit("t1", "p1")
    assert applied == ["done-p1"]
    assert rec.in_flight is False


# --- editor integration: stale results never painted ----------------------

class _Win:
    def __init__(self):
        self.data = {"show_pack_coverage": "True", "pack_coverage_fade": "True",
                     "show_line_numbers": "True", "line_marks": "False"}
        self.current_silo = "silo_1"
        self._theme_cache = {"raw_colors": {"accent": "#D3B57A", "border_light": "#826941"}}
        self._coverage_store = None
        self.text_area = None
        self.text_edit = None
        self.state = None

    def _active_silo_id(self):
        return self.current_silo

    def _get_custom_colors(self):
        return {}

    def _get_coverage_store(self):
        if self._coverage_store is None:
            self._coverage_store = sc.CoverageStore()
        return self._coverage_store


def _editor():
    win = _Win()
    editor = VaultTextEdit(win)
    win.text_area = editor
    win.text_edit = editor
    return win, editor


def _deferred_reconciler(editor):
    captured = []
    editor._coverage_reconciler._runner = lambda request: captured.append(request)
    return captured


def test_perf_001_editor_discards_a_result_for_a_changed_document():
    _app()
    win, editor = _editor()
    editor.setPlainText(_doc(5))
    captured = _deferred_reconciler(editor)

    editor.refresh_pack_coverage()
    assert len(captured) == 1
    seq, _payload = captured[0]

    # The document changes while reconciliation is "blocked".
    editor.setPlainText(_doc(5, prefix="*"))

    editor._on_coverage_result(seq, sc.CoverageMap(fresh_count=999))
    assert editor._coverage_map is None      # stale result never painted


def test_perf_001_editor_newest_request_wins_and_is_applied():
    _app()
    win, editor = _editor()
    editor.setPlainText(_doc(5))
    captured = _deferred_reconciler(editor)

    editor.refresh_pack_coverage()
    editor.refresh_pack_coverage()
    assert len(captured) == 1                # second coalesced while first ran

    first_seq = captured[0][0]
    editor._on_coverage_result(first_seq, sc.CoverageMap(fresh_count=1))
    assert editor._coverage_map is None      # older result discarded
    assert len(captured) == 2                # the pending request was dispatched

    newest_seq = captured[1][0]
    best = sc.CoverageMap(fresh_count=2)
    editor._on_coverage_result(newest_seq, best)
    assert editor._coverage_map is best


def test_perf_001_editor_invisible_overlay_discards_results():
    _app()
    win, editor = _editor()
    editor.setPlainText(_doc(5))
    captured = _deferred_reconciler(editor)
    editor.refresh_pack_coverage()
    seq, _payload = captured[0]

    editor.hide_pack_coverage_session()      # overlay off for the session
    editor._on_coverage_result(seq, sc.CoverageMap(fresh_count=7))
    assert editor._coverage_map is None


def test_perf_001_document_identity_survives_wrapper_churn():
    """A same-document touch-up must not read as a document change.

    PyQt can hand back a new Python wrapper for the same QTextDocument, so the
    token keys on the C++ address; keying on ``id()`` made a settled edit drop
    its own reconciliation result on the floor.
    """
    from PyQt6 import sip

    _app()
    win, editor = _editor()
    editor.setPlainText(_doc(5))

    identity, revision = editor._coverage_document_identity()
    assert identity == int(sip.unwrapinstance(editor.document()))
    assert identity != 0
    assert editor._coverage_token() == editor._coverage_token()
    assert editor._coverage_token()[1] == revision

    # The identity tracks a real swap, so the guard still rejects a new document.
    other = VaultTextEdit(win)
    other.setPlainText(_doc(5))
    assert other._coverage_document_identity()[0] != identity


# --- colors resolved once per paint pass ---------------------------------

def test_perf_001_marker_reuses_the_pass_colors(monkeypatch):
    _app()
    win, editor = _editor()
    editor._coverage_map = sc.CoverageMap(requirements=(
        sc.CoverageItem("R1", 1, 4, "t", sc.CoverageState.FULL, None),))

    calls = {"n": 0}
    real = editor._coverage_theme_colors

    def counted():
        calls["n"] += 1
        return real()

    monkeypatch.setattr(editor, "_coverage_theme_colors", counted)

    pix = QPixmap(40, 40)
    painter = QPainter(pix)
    try:
        for line in (1, 2, 3, 4):
            editor._paint_coverage_marker(painter, line, 0, 12,
                                          theme=("#D3B57A", "#826941"))
    finally:
        painter.end()
    assert calls["n"] == 0                   # zero per-row theme resolution

    painter = QPainter(pix)
    try:
        editor._paint_coverage_marker(painter, 1, 0, 12)   # fallback preserved
    finally:
        painter.end()
    assert calls["n"] == 1


def test_perf_001_paint_passes_resolve_colors_once():
    gutter = inspect.getsource(VaultTextEdit.line_number_area_paint_event)
    assert "cov_theme = (" in gutter
    assert "theme=cov_theme" in gutter
    viewport = inspect.getsource(VaultTextEdit.paintEvent)
    assert "cov_theme = (" in viewport
    assert "theme=cov_theme" in viewport


# --- benchmarks: scaling, not user-hardware FPS ---------------------------

def test_perf_001_lookup_pass_is_far_cheaper_than_the_linear_scan():
    text = _doc(1000)
    ledger = sc.CoverageLedger()
    ledger.record_event(_event(text, 0, 100))
    cmap = sc.reconcile_pack_coverage(text, ledger)
    assert len(cmap.requirements) == 1000

    lines = list(range(1, 201))

    def indexed():
        for line in lines:
            cmap.get_line_state(line)

    def linear():
        for line in lines:
            _legacy_line_state(cmap, line)

    indexed(); linear()                       # warm both paths
    t0 = time.perf_counter()
    for _ in range(100):
        indexed()
    t_indexed = time.perf_counter() - t0
    t0 = time.perf_counter()
    for _ in range(100):
        linear()
    t_linear = time.perf_counter() - t0

    assert indexed() is None
    # 20,000 lookups: the indexed pass must be substantially below the
    # 10.619 ms/200-line linear baseline measured by the audit.
    assert t_indexed * 10 < t_linear


def test_perf_001_reconcile_no_longer_scans_the_ledger_per_requirement():
    """The match step is indexed; the per-requirement ledger scan is gone.

    The silo parse (untouched by PERF-001) dominates a whole reconcile, so the
    benchmark isolates the match step: identical requirement keys, identical
    100 receipts, indexed lookup against the pre-PERF first-match scan.
    """
    text = _doc(1000)
    ledger = sc.CoverageLedger()
    ledger.record_event(_event(text, 0, 100))
    assert len(ledger.entries) == 100

    cmap = sc.reconcile_pack_coverage(text, ledger)
    assert len(cmap.requirements) == 1000

    keys = [sc.requirement_coverage_key(req.text, req.media)
            for req in silo_index_requirements(text)]

    def indexed_match():
        lookup = sc.build_receipt_index(ledger.entries)
        return [lookup.get((key, 1)) for key in keys]

    def linear_match():
        out = []
        for key in keys:
            hit = None
            for existing in ledger.entries:
                if existing.coverage_key == key:
                    hit = existing
                    break
            out.append(hit)
        return out

    assert indexed_match() == linear_match()     # same answers on this document
    indexed_match(); linear_match()              # warm both paths
    t0 = time.perf_counter()
    indexed_match()
    t_indexed = time.perf_counter() - t0
    t0 = time.perf_counter()
    linear_match()
    t_linear = time.perf_counter() - t0

    # 1,000 requirements x 100 receipts: the scan cannot stay within 10x.
    assert t_indexed * 10 < t_linear


def silo_index_requirements(text):
    from fastprompter.core import silo_index
    return silo_index.build_silo_index(text, "source.md").requirements
