"""PERF-002 (audit/12, SRC-041 R008): undo/redo cap enforcement reuses the
cached snapshot size.

``_snapshot_current`` already stores ``_text_size`` on every finalized
snapshot, but the cap loops rescanned the WHOLE stack after every eviction —
triangular work on what the audit measured as 1,085 full traversals for one
cap operation. These tests pin the reference semantics (identical survivors),
the zero-rescan contract, single-computation for legacy entries, and the
finalization ordering (size computed AFTER the live editor text is folded in).
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from fastprompter.main import (
    FastPrompter,
    _snapshot_cached_text_size,
    _snapshot_text_size,
    _trim_snapshot_stack,
)

_MAX_CHARS = 20_000_000


def _snap(total, label):
    return {"label": label, "_text_size": total}


def _ref_trim(stack, max_entries=50, max_chars=_MAX_CHARS):
    """The OLD reference semantics: entry cap first, then a whole-stack sum
    re-evaluated after EVERY eviction."""
    while len(stack) > max_entries:
        stack.pop(0)
    while len(stack) > 1 and sum(
            _snapshot_cached_text_size(s) for s in stack) > max_chars:
        stack.pop(0)


class TestReferenceEquivalence:
    def test_under_cap_stack_unchanged(self):
        stack = [_snap(10, i) for i in range(5)]
        expected = list(stack)
        _trim_snapshot_stack(stack)
        assert stack == expected

    def test_exactly_at_cap_survives(self):
        stack = [_snap(4_000_000, i) for i in range(5)]  # = 20,000,000
        _trim_snapshot_stack(stack)
        assert len(stack) == 5

    def test_multi_pop_matches_reference(self):
        stack = [_snap(10_000_000, i) for i in range(5)]
        ref = [_snap(10_000_000, i) for i in range(5)]
        _trim_snapshot_stack(stack)
        _ref_trim(ref)
        assert [s["label"] for s in stack] == [s["label"] for s in ref]
        assert len(stack) == 2

    def test_fifty_entry_cap_applies_first(self):
        stack = [_snap(0, i) for i in range(60)]
        _trim_snapshot_stack(stack)
        assert [s["label"] for s in stack] == list(range(10, 60))

    def test_never_below_one_survivor(self):
        stack = [_snap(999_000_000, 1)]
        _trim_snapshot_stack(stack)
        assert len(stack) == 1


class TestCostContract:
    def test_cached_sizes_trigger_zero_full_scans(self, monkeypatch):
        import fastprompter.main as m

        calls = {"n": 0}
        real = m._snapshot_text_size

        def counting(snap):
            calls["n"] += 1
            return real(snap)

        monkeypatch.setattr(m, "_snapshot_text_size", counting)
        stack = [_snap(10_000_000, i) for i in range(5)]
        m._trim_snapshot_stack(stack)
        assert calls["n"] == 0, "finalized snapshots must never be rescanned"
        assert len(stack) == 2

    def test_legacy_entries_are_computed_at_most_once(self, monkeypatch):
        import fastprompter.main as m

        calls = {"n": 0}
        real = m._snapshot_text_size

        def counting(snap):
            calls["n"] += 1
            return real(snap)

        monkeypatch.setattr(m, "_snapshot_text_size", counting)
        stack = []
        for _i in range(4):
            stack.append({"temp_presets": ["x" * 6_000_000]})  # 6M chars

        m._trim_snapshot_stack(stack, max_chars=_MAX_CHARS)

        assert len(stack) == 3  # 24M -> pop one, 18M remains
        assert calls["n"] == 4, \
            "each legacy entry may be traversed once, then reused"

    def test_multi_pop_is_one_total_plus_constant_subtraction(
            self, monkeypatch):
        import fastprompter.main as m

        calls = {"n": 0}
        real = m._snapshot_cached_text_size

        def counting(snap):
            calls["n"] += 1
            return real(snap)

        monkeypatch.setattr(m, "_snapshot_cached_text_size", counting)
        stack = [_snap(10_000_000, i) for i in range(10)]  # 100M -> 8 pops
        m._trim_snapshot_stack(stack)
        assert len(stack) == 2
        # One initial total (10 lookups) + one subtraction per pop (8).
        assert calls["n"] == 18, \
            "cap enforcement must not re-sum the whole stack per pop"

    def test_navigation_only_entries_are_zero_cost(self, monkeypatch):
        import fastprompter.main as m

        calls = {"n": 0}
        real = m._snapshot_text_size

        def counting(snap):
            calls["n"] += 1
            return real(snap)

        monkeypatch.setattr(m, "_snapshot_text_size", counting)
        stack = [{"_switch": True, "category": "Code"} for _ in range(60)]
        m._trim_snapshot_stack(stack)
        assert len(stack) == 50
        # The entry-cap trim removes 10 with no measurement at all; the 50
        # survivors are measured ONCE each (their size is 0 and is cached),
        # never per-pop-rescanned: total accessor work is linear.
        assert calls["n"] == 50


@pytest.fixture(scope="module")
def win(tmp_path_factory):
    import fastprompter.core.state as state_mod

    tmp_path = tmp_path_factory.mktemp("perf002")
    original_db_path = state_mod.get_db_path
    state_mod.get_db_path = (
        lambda profile_id=1: str(tmp_path / f"perf002_{profile_id}.db"))
    import fastprompter.utils.portable_backup as backup_mod
    original_backup = backup_mod.run_portable_backup
    backup_mod.run_portable_backup = lambda data, profile_id=1, **_kw: None

    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])

    originals = {
        name: getattr(FastPrompter, name)
        for name in ("setup_single_instance_server", "register_all_hotkeys",
                     "unregister_all_hotkeys")
    }
    FastPrompter.setup_single_instance_server = lambda self: None
    FastPrompter.register_all_hotkeys = lambda self: None
    FastPrompter.unregister_all_hotkeys = lambda self: None
    w = FastPrompter()
    for _ in range(5):
        app.processEvents()
    w._initializing_ui = False
    w._suspend_temp_sync = False
    try:
        yield w
    finally:
        for name in ("auto_save_timer", "topmost_timer", "_cache_timer"):
            timer = getattr(w, name, None)
            if timer is not None:
                timer.stop()
        service = getattr(w, "limit_service", None)
        if service is not None:
            service.shutdown()
        if getattr(w, "state", None) is not None:
            w.state.conn = None
        w.close()
        for name, value in originals.items():
            setattr(FastPrompter, name, value)
        state_mod.get_db_path = original_db_path
        backup_mod.run_portable_backup = original_backup


class TestFinalizationOrdering:
    def test_size_is_finalized_after_the_live_text_fold(self, win):
        marker = "LIVE-TEXT-MARKER-4f9a"
        win._switch_to_slot(0, initial=True, is_archive=False)
        win.text_area.setPlainText(marker)

        snap = win._snapshot_current()

        # The live editor text was folded into the snapshot BEFORE the size
        # was finalized, and the stored value equals an independent recount
        # of the finalized fields (no stale pre-fold size).
        key = ("archive_temp_presets" if snap["active_is_archive"]
               else "temp_presets")
        assert marker in snap[key][snap["active_temp_slot"]]
        stored = snap.pop("_text_size")
        assert stored == _snapshot_text_size(snap)
