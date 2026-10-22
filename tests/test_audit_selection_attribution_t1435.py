"""T-1435 (SRC-095 CORE-006) — duplicate-requirement selection attribution.

``create_bundle_coverage_event`` supports an exact ``selected_span`` so a Fast
Pack Selection of the SECOND of two byte-identical requirement lines is
attributed to the second receipt (duplicate ordinal 2), not the first. This was
broken only at the CALL SITE: ``_record_bundle_coverage`` did not forward the
span, so the event fell back to ``markdown_text.find(selected_text)``, which
always resolves the first occurrence.
"""

from __future__ import annotations

import inspect

import fastprompter.core.silo_coverage as sc
from fastprompter import main as main_mod

DOC = (
    "# Duplicates\n\n"
    "• Fix button\n"
    "• Other item\n"
    "• Fix button\n"
)
LINE = "• Fix button\n"
FIRST = DOC.find(LINE)
SECOND = DOC.find(LINE, FIRST + 1)


def _covered_states(doc, selected_text, selected_span):
    event = sc.create_bundle_coverage_event(
        silo_id="silo_1",
        bundle_kind="selection_bundle",
        archive_name="fast_second.zip",
        markdown_text=doc,
        selected_text=selected_text,
        selected_span=selected_span,
    )
    ledger = sc.CoverageLedger()
    ledger.record_event(event)
    cmap = sc.reconcile_pack_coverage(doc, ledger)
    return [r.state for r in cmap.requirements]


def _is_covered(state):
    return state in (sc.CoverageState.FULL, sc.CoverageState.RECENT_FULL)


def test_core_006_exact_span_attributes_the_second_duplicate():
    states = _covered_states(DOC, LINE, (SECOND, SECOND + len(LINE)))

    assert len(states) == 3
    # The second "Fix button" was packed: it is covered, the first is not.
    assert _is_covered(states[2]), states
    assert states[0] == sc.CoverageState.FRESH, states
    assert states[1] == sc.CoverageState.FRESH, states


def test_core_006_without_the_span_the_first_duplicate_is_misattributed():
    # Control documenting the bug the call-site fix closes: with only the text
    # (no span) ``find`` resolves the FIRST occurrence, so packing the second
    # line falsely credits the first.
    states = _covered_states(DOC, LINE, None)

    assert _is_covered(states[0]), states
    assert states[2] == sc.CoverageState.FRESH, states


def test_core_006_recorder_forwards_an_explicit_span():
    src = inspect.getsource(main_mod.FastPrompter._record_bundle_coverage)
    assert "selected_span" in src
    assert "create_bundle_coverage_event" in src
    assert "selected_span=(" in src


def test_core_006_both_selection_call_sites_forward_the_expanded_span():
    # PERF-001 (SRC-097) split the entry point in two: the capture freezes the
    # converted span, and the completion half records it for BOTH outcomes with
    # ONE call site (what used to be two), after publication committed.
    src = inspect.getsource(main_mod.FastPrompter.fast_pack_selection)
    finish = inspect.getsource(main_mod.FastPrompter._fast_pack_complete)
    assert "\"selected_span\": (exp_start, exp_end)" in src, src
    assert "selected_span=cap.get(\"selected_span\")" in finish, finish
    assert finish.count("_record_bundle_coverage(") == 1, finish
    assert finish.index("selected_span=cap.get") > finish.index(
        "meta_ok = self._silo_bundle_record_success")


def test_core_006_silo_bundle_call_sites_do_not_send_a_selection_span():
    # A whole-silo bundle has no selection; the span must stay absent so the
    # full-bundle mode (every requirement covered) is preserved.
    src = inspect.getsource(main_mod.FastPrompter._bundle_on_finished)
    assert src.count("_record_bundle_coverage(") == 2, src
    assert "selected_span" not in src
