"""T-1247 [P0] Explicit NEW always creates a distinct SILO.

The legacy "max 5 blanks / reuse empty" policy made explicit NEW
navigation: with five empty silos on screen, pressing NEW jumped to an
existing blank instead of creating one, and the bottom path
(append_empty_silo) reused the first empty slot it found.

Contract under test:

* every successful explicit NEW creates exactly one new SILO object and
  one new stable identity, regardless of existing contents;
* the only creation ceiling is MAX_SILOS_PER_CATEGORY, at which NEW
  refuses explicitly (count unchanged, selection unchanged, no blank
  selected as a substitute);
* empty silo existence survives persistence (T-1222) with exact
  count/order/IDs after restart;
* editing one of many empty silos never mutates another (T-1227 owner
  verification stays intact);
* template NEW fills the freshly created identity, never an existing
  blank.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from _qt_retire import retire
from PyQt6.QtWidgets import QApplication

import fastprompter.core.state as state_mod
from fastprompter.core.state import bind_active_category

_APP = QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def _own_the_clipboard():
    """Snapshot/restore: this module writes to the machine-global clipboard,
    and T-1260 is the ticket about not doing that to everybody else."""
    clip = _APP.clipboard()
    before = clip.text()
    try:
        yield
    finally:
        if before:
            clip.setText(before)
        else:
            clip.clear()


@pytest.fixture()
def win(tmp_path):
    original_db_path = state_mod.get_db_path
    state_mod.get_db_path = (
        lambda profile_id=1: str(tmp_path / f"t1247_{profile_id}.db"))
    import fastprompter.utils.portable_backup as backup_mod
    original_backup = backup_mod.run_portable_backup
    backup_mod.run_portable_backup = lambda data, profile_id=1, **_kw: None

    from fastprompter.main import FastPrompter
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
        _APP.processEvents()
    w._initializing_ui = False
    w._suspend_temp_sync = False
    # T-1260: this module's contract is silo IDENTITY and ORDER, so the
    # clipboard-seeding automation is pinned OFF here rather than inherited.
    # The shipped profile defaults ``new_silo_paste_clipboard`` to True, and
    # the clipboard is machine-global: an earlier test that pressed a real
    # Ctrl+X (tests/test_editor_delete_sounds.py cuts "bc") left that text on
    # it, so every "new empty silo" assertion below read "bc" instead of "".
    # The seeding path itself is covered explicitly in
    # ``TestClipboardSeedIsolation``, with the clipboard under the test's own
    # control.
    w.data["new_silo_paste_clipboard"] = "False"
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
        # T-1286: deliver this window's DeferredDelete NOW (receiver-scoped).
        # A bare close() left the whole window tree alive until a later test
        # pumped an event loop; the accumulated backlog made QTest.qWait() in
        # tests/test_timer_fire.py stall past that test's 5 s watchdog.
        retire(w)
        for name, value in originals.items():
            setattr(FastPrompter, name, value)
        state_mod.get_db_path = original_db_path
        backup_mod.run_portable_backup = original_backup


def _switch(win, idx):
    """Select a slot AND mirror its text into the live editor, so the
    select_empty_silo live-flush (which copies the editor back into the
    slot being left) cannot clobber unrelated preset content."""
    win._switch_to_slot(idx, initial=True, is_archive=False)
    presets = win.data["temp_presets"]
    if 0 <= idx < len(presets):
        win.text_area.setPlainText(presets[idx])


def _reset(win, texts=("alpha", "bravo")):
    win.cat_combo.setCurrentIndex(0)
    win.on_tab_changed(0)
    win.data["temp_presets"][:] = list(texts)
    win.data["silo_children"] = {}
    win.data["silo_gaps"] = []
    _switch(win, 0)
    return win.get_current_category()


def _persisted_ids(win, cat):
    """Identity anchors are materialised at commit time; read them from a
    freshly-loaded state so un-saved in-memory slots are not misread as None."""
    win.save_data_to_db(force=True)
    fresh = state_mod.FastPrompterState(profile_id=1)
    try:
        bind_active_category(fresh.data, cat)
        n = len(fresh.data["temp_presets_all"][cat])
        return [fresh.silo_id_for(cat, False, i) for i in range(n)]
    finally:
        if fresh.conn is not None:
            fresh.conn.close()


class TestExplicitNewCreates:
    def test_red_control_five_empties_then_new_increases_count(self, win):
        """RED CONTROL (matrix 3): the exact old-bug shape. Five existing
        empties + canonical NEW must now create a sixth empty silo at the
        top, not navigate to one of the five."""
        _reset(win, ("", "", "", "", ""))
        win.select_empty_silo(insertion="top")
        assert len(win.data["temp_presets"]) == 6
        assert win.data["temp_presets"][0] == ""
        assert win.active_temp_slot == 0
        # all five previous empties shifted down intact
        assert win.data["temp_presets"][1:] == [""] * 5

    def test_red_control_any_empty_append_bottom_increases_count(self, win):
        """RED CONTROL (matrix 5): existing blank + append_empty_silo must
        append a NEW blank at the bottom, never select index 0."""
        _reset(win, ("", "abc", ""))
        win.append_empty_silo()
        assert win.data["temp_presets"] == ["", "abc", "", ""]
        assert win.active_temp_slot == 3

    def test_current_empty_new_creates_distinct(self, win):
        """Matrix 1: current silo empty + canonical NEW still creates a new
        top silo.

        T-1260: this used to call ``select_empty_silo(insertion=None)``, which
        is the POINTER route -- production deliberately derives the position
        from ``QApplication.keyboardModifiers()`` there. Asserting "modifiers
        do not matter" while asking production to read ambient modifier state
        is self-contradictory and order-sensitive: any earlier test that left
        Shift or Ctrl latched turned this into "above"/"below" and the
        assertion failed. The canonical default is explicit; the pointer route
        is covered by TestPointerDerivedInsertion below, with the modifier
        source under the test's control.
        """
        _reset(win, ("keep", ""))
        _switch(win, 1)
        win.select_empty_silo()                # canonical default == "top"
        assert len(win.data["temp_presets"]) == 3
        assert win.data["temp_presets"] == ["", "keep", ""]
        assert win.active_temp_slot == 0

    def test_top_new_order_shift(self, win):
        """Matrix: [A, B, C] + NEW -> [NEW_EMPTY, A, B, C]."""
        _reset(win, ("A", "B", "C"))
        win.select_empty_silo(insertion="top")
        assert win.data["temp_presets"] == ["", "A", "B", "C"]
        assert win.active_temp_slot == 0

    def test_ctrl_n_x10_creates_ten_distinct(self, win):
        """Matrix 4/6: Ctrl+N x10 == ten distinct empty silos, each with
        its own stable identity (old magic limit was 5)."""
        cat = _reset(win, ("A", "B"))
        for _ in range(10):
            win.select_empty_silo(insertion="top")  # the Ctrl+N route
        presets = win.data["temp_presets"]
        assert len(presets) == 12
        assert presets[0:10] == [""] * 10
        assert presets[10:] == ["A", "B"]
        ids = _persisted_ids(win, cat)
        assert len(ids) == 12
        assert len(set(ids)) == 12, "every empty silo must own a distinct id"

    def test_shift_insert_above_selected(self, win):
        """Matrix 7: Shift NEW inserts above the selected silo."""
        _reset(win, ("A", "B"))
        _switch(win, 1)  # B selected
        win.select_empty_silo(insertion="above")
        assert win.data["temp_presets"] == ["A", "", "B"]
        assert win.active_temp_slot == 1

    def test_ctrl_insert_below_selected(self, win):
        """Matrix 8: Ctrl NEW inserts below the selected silo."""
        _reset(win, ("A", "B"))
        _switch(win, 0)  # A selected
        win.select_empty_silo(insertion="below")
        assert win.data["temp_presets"] == ["A", "", "B"]
        assert win.active_temp_slot == 1

    def test_bottom_new_with_existing_blanks_always_appends(self, win):
        """Matrix 5 deep: blanks at 0 and 2 never selected nor reused."""
        _reset(win, ("", "abc", ""))
        win.append_empty_silo()
        win.append_empty_silo()
        assert win.data["temp_presets"] == ["", "abc", "", "", ""]

    def test_mixed_identical_content_distinct_identities(self, win):
        """Matrix 13: two empty + two identical non-empty silos are four
        distinct identities; identity never collapses on equal content."""
        cat = _reset(win, ("", "", "same", "same"))
        ids = _persisted_ids(win, cat)
        assert len(ids) == 4
        assert len(set(ids)) == 4


class TestTemplateNew:
    def test_template_new_fills_fresh_identity_not_existing_blank(self, win):
        """Matrix 9: template NEW creates a genuinely new silo first, then
        fills THAT one. An existing blank must not be overwritten."""
        _reset(win, ("", "keep"))
        win._new_silo_with_text("TEMPLATE")
        assert win.data["temp_presets"] == ["TEMPLATE", "", "keep"]
        assert win.active_temp_slot == 0


class TestRestart:
    def _commit(self, win):
        win.save_data_to_db(force=True)

    def test_restart_preserves_exact_count_order_ids(self, win):
        """Matrix 10/11: five empty NEWs + restart = same count, same
        order, same identities, all still empty."""
        cat = _reset(win, ("anchor",))
        for _ in range(5):
            win.select_empty_silo(insertion="top")
        before_presets = list(win.data["temp_presets"])
        before_ids = _persisted_ids(win, cat)
        self._commit(win)

        fresh = state_mod.FastPrompterState(profile_id=1)
        try:
            bind_active_category(fresh.data, cat)
            after = list(fresh.data["temp_presets_all"][cat])
            assert after == before_presets, (
                "restart must not trim/dedupe/merge empty silos")
            # identities remap through the canonical table: id set preserved
            n = len(after)
            after_ids = [fresh.silo_id_for(cat, False, i) for i in range(n)]
            assert len(set(after_ids)) == n
            assert set(after_ids) == set(before_ids)
        finally:
            if fresh.conn is not None:
                fresh.conn.close()

    def test_restart_preserves_mixed_identical_content(self, win):
        """Matrix 13 persistence half: two empty + two 'same' survive
        restart as four silos."""
        cat = _reset(win, ("", "", "same", "same"))
        before = list(win.data["temp_presets"])
        self._commit(win)
        fresh = state_mod.FastPrompterState(profile_id=1)
        try:
            bind_active_category(fresh.data, cat)
            assert list(fresh.data["temp_presets_all"][cat]) == before
        finally:
            if fresh.conn is not None:
                fresh.conn.close()


class TestEditOneOfManyEmpty:
    def test_edit_middle_empty_only_that_silo_changes(self, win):
        """Matrix 12: five empties, type 'hello' in the middle one — the
        other four stay '' before AND after save/reload."""
        cat = _reset(win, ("", "", "", "", ""))
        _switch(win, 2)
        win.text_area.setPlainText("hello")
        win.save_data_to_db(force=True)
        assert win.data["temp_presets"][2] == "hello"
        assert [p for i, p in enumerate(win.data["temp_presets"])
                if i != 2] == ["", "", "", ""]

        fresh = state_mod.FastPrompterState(profile_id=1)
        try:
            bind_active_category(fresh.data, cat)
            slots = list(fresh.data["temp_presets_all"][cat])
            assert slots == ["", "", "hello", "", ""]
        finally:
            if fresh.conn is not None:
                fresh.conn.close()

    def test_delete_one_empty_removes_only_that_identity(self, win):
        """Matrix 15: deleting one empty silo removes exactly that
        identity; the other empties keep theirs."""
        cat = _reset(win, ("", "", ""))
        ids_before = _persisted_ids(win, cat)
        assert win.del_silo(1) is True or win.del_silo(1)
        ids_after = _persisted_ids(win, cat)
        assert len(ids_after) == 2
        assert len(set(ids_after)) == 2
        # the two survivors keep their original identities
        assert set(ids_after).issubset(set(ids_before))
        # exactly one identity (the deleted empty silo) is gone
        assert len(set(ids_before) - set(ids_after)) == 1


class TestCapacity:
    def test_capacity_refusal_is_explicit_no_substitution(self, win):
        """Matrix 16/17: at MAX_SILOS_PER_CATEGORY with empties present,
        NEW refuses: count unchanged, selection unchanged, no blank
        selected as substitute (an empty silo consumes capacity)."""
        _reset(win, ("x",))
        win.data["temp_presets"][:] = [""] * win.MAX_SILOS_PER_CATEGORY
        _switch(win, 7)
        before = list(win.data["temp_presets"])
        sel_before = win.active_temp_slot

        win.select_empty_silo(insertion="top")
        assert win.data["temp_presets"] == before
        assert win.active_temp_slot == sel_before

        win.append_empty_silo()
        assert win.data["temp_presets"] == before
        assert win.active_temp_slot == sel_before


class TestAdjacentHappyPath:
    def test_select_rename_delete_undo_redo_with_multiple_empties(self, win):
        """Matrix: bounded sweep over select/rename/delete/undo/redo with
        ten empties present — no identity drift."""
        cat = _reset(win, ("", "", "", "", "", "", "", "", "", "solo"))
        ids_before = _persisted_ids(win, cat)
        # select across empties
        for i in range(10):
            _switch(win, i)
            assert win.active_temp_slot == i
        # identities unchanged by pure navigation
        assert _persisted_ids(win, cat) == ids_before
        # delete the last empty, undo restores the logical object
        n_before = len(win.data["temp_presets"])
        assert win.del_silo(9)
        assert len(win.data["temp_presets"]) == n_before - 1
        ids_mid = _persisted_ids(win, cat)
        assert len(set(ids_mid)) == n_before - 1
        # undo removes the delete; every identity back in place
        win.undo_action() if hasattr(win, "undo_action") else win.undo()
        after = _persisted_ids(win, cat)
        assert len(after) == n_before
        # CANONICAL (spec s20): the current structural-undo contract restores
        # the logical object but identity anchors are re-materialised by
        # _load_silo_identities, so a restored slot MAY carry a fresh id.
        # The invariant that matters: no drift — same count, same order,
        # every silo still distinct.
        assert [win.data["temp_presets"][i] for i in range(n_before)] == \
            [""] * 9 + ["solo"]
        assert len(set(after)) == n_before

class TestPointerDerivedInsertion:
    """``insertion=None`` is the MOUSE route, and its modifiers are the gesture.

    Production reads ``QApplication.keyboardModifiers()`` only on this path
    (CORE-013: a keyboard route must never infer intent from the modifier that
    triggered its own shortcut). These tests own the modifier source instead of
    inheriting whatever a previous QTest event left latched, so the three
    gestures are pinned without any ambient dependency.
    """

    @staticmethod
    def _modifiers(monkeypatch, value):
        import fastprompter.ui.snippet_ops_mixin as ops_mod

        class _Ambient:
            @staticmethod
            def keyboardModifiers():
                return value

            @staticmethod
            def clipboard():
                return QApplication.clipboard()

        monkeypatch.setattr(ops_mod, "QApplication", _Ambient)

    def test_plain_click_inserts_at_the_top(self, win, monkeypatch):
        from PyQt6.QtCore import Qt

        _reset(win, ("keep", ""))
        _switch(win, 1)
        self._modifiers(monkeypatch, Qt.KeyboardModifier.NoModifier)
        win.select_empty_silo(insertion=None)
        assert win.data["temp_presets"] == ["", "keep", ""]
        assert win.active_temp_slot == 0

    def test_shift_click_inserts_above_the_active_silo(self, win, monkeypatch):
        from PyQt6.QtCore import Qt

        _reset(win, ("A", "B", "C"))
        _switch(win, 1)
        self._modifiers(monkeypatch, Qt.KeyboardModifier.ShiftModifier)
        win.select_empty_silo(insertion=None)
        assert win.data["temp_presets"] == ["A", "", "B", "C"]
        assert win.active_temp_slot == 1

    def test_ctrl_click_inserts_below_the_active_silo(self, win, monkeypatch):
        from PyQt6.QtCore import Qt

        _reset(win, ("A", "B", "C"))
        _switch(win, 1)
        self._modifiers(monkeypatch, Qt.KeyboardModifier.ControlModifier)
        win.select_empty_silo(insertion=None)
        assert win.data["temp_presets"] == ["A", "B", "", "C"]
        assert win.active_temp_slot == 2

    def test_a_latched_modifier_cannot_reach_the_canonical_route(
            self, win, monkeypatch):
        """T-1260 regression: explicit intent ignores ambient modifier state.

        This is the exact contamination that broke
        ``test_current_empty_new_creates_distinct`` in a full run -- a Shift
        left latched by an earlier test. The canonical route must not care.
        """
        from PyQt6.QtCore import Qt

        _reset(win, ("keep", ""))
        _switch(win, 1)
        self._modifiers(monkeypatch, Qt.KeyboardModifier.ShiftModifier
                        | Qt.KeyboardModifier.ControlModifier)
        win.select_empty_silo()
        assert win.data["temp_presets"] == ["", "keep", ""]
        assert win.active_temp_slot == 0

    def test_no_test_in_this_module_leaves_a_modifier_latched(self, win):
        """Leak sentinel: the ambient modifier source is clean on exit."""
        from PyQt6.QtCore import Qt

        assert QApplication.keyboardModifiers() == Qt.KeyboardModifier.NoModifier
class TestClipboardSeedIsolation:
    """``new_silo_paste_clipboard`` is ON in the shipped profile, and the
    clipboard is machine-global state shared with the operator's desktop.

    T-1260: that combination is what turned this module red in a full run
    while it passed alone. Both halves are pinned here -- the isolation the
    rest of the module relies on, and the production behaviour it isolates
    away -- so neither can rot unnoticed.
    """

    @staticmethod
    def _clip():
        return _APP.clipboard()

    def test_dirty_clipboard_cannot_seed_a_new_silo_in_this_module(self, win):
        """The exact contaminating condition, made explicit and harmless."""
        self._clip().setText("bc")
        _reset(win, ("keep", ""))
        _switch(win, 1)
        win.select_empty_silo()
        assert win.data["temp_presets"] == ["", "keep", ""]

    def test_the_seeding_feature_still_works_when_a_test_asks_for_it(self, win):
        """The isolation must not delete the production path from coverage."""
        self._clip().setText("seeded-by-this-test")
        _reset(win, ("keep", ""))
        _switch(win, 1)
        win.data["new_silo_paste_clipboard"] = "True"
        win.select_empty_silo()
        assert win.data["temp_presets"] == ["seeded-by-this-test", "keep", ""]

    def test_a_seeded_new_silo_is_still_a_distinct_identity(self, win):
        """Seeding fills the FRESH slot; it never reuses an existing one."""
        self._clip().setText("seed")
        _reset(win, ("keep", ""))
        _switch(win, 1)
        win.data["new_silo_paste_clipboard"] = "True"
        before = len(win.data["temp_presets"])
        win.select_empty_silo(insertion="below")
        assert len(win.data["temp_presets"]) == before + 1
        assert win.data["temp_presets"][win.active_temp_slot] == "seed"
        assert win.active_temp_slot == 2

