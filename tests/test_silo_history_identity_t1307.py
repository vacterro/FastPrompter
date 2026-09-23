"""CORE-001 (audit/12, SRC-041 R001): SILO text-history ownership is
IDENTITY-based, never coordinate-based.

A structural SILO operation (reorder, insert, delete, cross-space swap,
cross-category transfer) moves stable silo_ids together with their silos.
The committed-text diff must compare each identity against ITS OWN committed
text, so a structural-only change queues ZERO text-history transitions and
persistent recovery can never traverse another SILO's text.

The old implementation paired the previous content by `(category, slot)` and
then attributed the difference to the POST-REMAP identity occupying that
slot, so a plain A/B swap manufactured `SID-B: A -> B` and `SID-A: B -> A`.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtWidgets import QApplication

import fastprompter.core.state as state_mod
from fastprompter.core.state import bind_active_category

_APP = QApplication.instance() or QApplication([])


@pytest.fixture(scope="module")
def win(tmp_path_factory):
    tmp_path = tmp_path_factory.mktemp("core001")
    original_db_path = state_mod.get_db_path
    state_mod.get_db_path = (
        lambda profile_id=1: str(tmp_path / f"core001_{profile_id}.db"))
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


def _reset(win, texts):
    win.cat_combo.setCurrentIndex(0)
    win.on_tab_changed(0)
    win.data["temp_presets"][:] = list(texts)
    win.data["archive_temp_presets"][:] = []
    win._persistent_history_cursor = {}
    win._persistent_history_suppress_sid = None
    win._switch_to_slot(0, initial=True, is_archive=False)
    cat = win.get_current_category()
    # Each test gets FRESH identities for its slots: the module-scoped window
    # reuses (category, slot) anchors otherwise, and an in-place text reset
    # would then be a legitimate identity edit of the previous test's silo.
    st = win.state
    ids = getattr(st, "silo_identities", None)
    if ids is not None:
        for key in [k for k in ids if k[0] == cat]:
            del ids[key]
    # ... and the persisted anchor rows, or _load_silo_identities would
    # legitimately adopt the previous test's ids for these coordinates.
    try:
        with st.conn:
            st.conn.execute(
                "DELETE FROM silo_identity_v1 WHERE category=?", (cat,))
    except Exception:
        pass
    st._load_silo_identities()
    return cat


def _active_text(win):
    slots = (win.data["archive_temp_presets"]
             if getattr(win, "active_is_archive", False)
             else win.data["temp_presets"])
    slot = getattr(win, "active_temp_slot", 0)
    return slots[slot] if 0 <= slot < len(slots) else ""


def _commit(win):
    """Authoritative save with NO text edit: the editor is synchronized to
    whatever the active slot already holds, then force-saved."""
    win.text_area.setPlainText(_active_text(win))
    assert win.save_data_to_db(force=True) is True


def _counts(win, *sids):
    return {sid: len(win.state.silo_text_history_for(sid)) for sid in sids}


def _partner_sid(win, cat, known, name):
    slot = win.data["temp_presets_all"][cat].index(name)
    sid = win.state.silo_id_for(cat, False, slot)
    assert sid and sid not in known, f"{name} must own a distinct identity"
    return sid


class TestStructuralOpsQueueZeroTransitions:
    def test_swap_two_normal_silos(self, win):
        cat = _reset(win, ("A", "B"))
        sid_a = win.state.silo_id_for(cat, False, 0)
        sid_b = win.state.silo_id_for(cat, False, 1)
        _commit(win)
        before = _counts(win, sid_a, sid_b)
        assert before == {sid_a: 0, sid_b: 0}

        win.swap_temp_slots(0, 1, False)
        _commit(win)

        assert win.data["temp_presets"][:2] == ["B", "A"]
        assert _counts(win, sid_a, sid_b) == before
        assert not (getattr(win.state, "_pending_silo_history", None) or [])

    def test_move_one_to_zero(self, win):
        cat = _reset(win, ("A", "B", "C"))
        sids = [win.state.silo_id_for(cat, False, i) for i in range(3)]
        _commit(win)
        before = _counts(win, *sids)

        win.move_temp_to_index(1, 0)
        _commit(win)

        assert win.data["temp_presets"][:3] == ["B", "A", "C"]
        assert _counts(win, *sids) == before

    def test_insert_before_existing_silos(self, win):
        cat = _reset(win, ("A", "B"))
        sid_a = win.state.silo_id_for(cat, False, 0)
        sid_b = win.state.silo_id_for(cat, False, 1)
        _commit(win)
        before = _counts(win, sid_a, sid_b)

        win.insert_silo_at("NEW", pos=0)
        _commit(win)

        assert win.data["temp_presets"][:3] == ["NEW", "A", "B"]
        assert _counts(win, sid_a, sid_b) == before
        sid_new = _partner_sid(win, cat, {sid_a, sid_b}, "NEW")
        # A brand-new identity has no predecessor transition.
        assert win.state.silo_text_history_for(sid_new) == []

    def test_delete_preceding_silo(self, win, monkeypatch):
        cat = _reset(win, ("A", "B", "C"))
        sid_a = win.state.silo_id_for(cat, False, 0)
        sid_b = win.state.silo_id_for(cat, False, 1)
        sid_c = win.state.silo_id_for(cat, False, 2)
        _commit(win)
        before = _counts(win, sid_a, sid_b, sid_c)
        monkeypatch.setattr(win, "_wait_for_undo_saves",
                            lambda *a, **k: True)

        assert win.del_silo(0) is True
        _commit(win)

        assert win.data["temp_presets"][:2] == ["B", "C"]
        assert _counts(win, sid_b, sid_c) == {
            sid_b: before[sid_b], sid_c: before[sid_c]}
        # The deleted identity's timeline is retained untouched.
        assert _counts(win, sid_a) == {sid_a: before[sid_a]}

    def test_normal_archive_cross_space_swap(self, win):
        cat = _reset(win, ("N"))
        win.data["archive_temp_presets"][:] = ["Z"]
        win.state._load_silo_identities()
        sid_n = win.state.silo_id_for(cat, False, 0)
        sid_z = win.state.silo_id_for(cat, True, 0)
        assert sid_n and sid_z and sid_n != sid_z
        _commit(win)
        before = _counts(win, sid_n, sid_z)

        win.swap_cross_temp_slots(0, 0, False, True)
        _commit(win)

        assert win.data["temp_presets"][0] == "Z"
        assert win.data["archive_temp_presets"][0] == "N"
        assert win.state.silo_id_for(cat, False, 0) == sid_z
        assert win.state.silo_id_for(cat, True, 0) == sid_n
        assert _counts(win, sid_n, sid_z) == before

    def test_cross_category_identity_transfer(self, win):
        cat = _reset(win, ("A", "B", "C"))
        target = next(c for c in win.data["categories"] if c != cat)
        sid_c = win.state.silo_id_for(cat, False, 2)
        sid_a = win.state.silo_id_for(cat, False, 0)
        _commit(win)
        before = _counts(win, sid_a, sid_c)

        assert win.transfer_silo_to_project(2, target) is True
        _commit(win)

        dest = win.data["temp_presets_all"][target]
        idx = dest.index("C")
        assert win.state.silo_id_for(target, False, idx) == sid_c
        assert win.state.silo_id_for(cat, False, 2) != sid_c
        assert _counts(win, sid_a, sid_c) == before


class TestRestartOwnership:
    def test_restart_after_each_structural_only_case(self, win, monkeypatch):
        monkeypatch.setattr(win, "_wait_for_undo_saves",
                            lambda *a, **k: True)
        cases = (
            ("swap", lambda w: w.swap_temp_slots(0, 1, False)),
            ("move", lambda w: w.move_temp_to_index(2, 0)),
            ("insert", lambda w: w.insert_silo_at("NEW", pos=1)),
            ("delete", lambda w: w.del_silo(0)),
        )
        for name, op in cases:
            cat = _reset(win, ("A", "B", "C"))
            sids = {text: win.state.silo_id_for(cat, False, i)
                    for i, text in enumerate(("A", "B", "C"))}
            _commit(win)
            op(win)
            _commit(win)

            fresh = state_mod.FastPrompterState(profile_id=1)
            try:
                bind_active_category(fresh.data, cat)
                slots = fresh.data["temp_presets_all"][cat]
                for text, sid in sids.items():
                    if text not in slots:
                        continue
                    assert fresh.silo_id_for(
                        cat, False, slots.index(text)) == sid, name
                    assert fresh.silo_text_history_for(sid) == [], name
            finally:
                if fresh.conn is not None:
                    fresh.conn.close()

    def test_edit_moved_silo_records_one_transition_for_that_identity(
            self, win):
        cat = _reset(win, ("A", "B", "C"))
        sid_a = win.state.silo_id_for(cat, False, 0)
        sid_b = win.state.silo_id_for(cat, False, 1)
        sid_c = win.state.silo_id_for(cat, False, 2)
        _commit(win)
        before = _counts(win, sid_a, sid_b, sid_c)

        win.move_temp_to_index(1, 0)
        _commit(win)
        assert _counts(win, sid_a, sid_b, sid_c) == before

        win._switch_to_slot(0, initial=True, is_archive=False)
        win.text_area.setPlainText("B + edit")
        assert win.save_data_to_db(force=True) is True

        assert [(h[1], h[2]) for h in win.state.silo_text_history_for(sid_b)] \
            == [("B", "B + edit")]
        assert _counts(win, sid_a) == {sid_a: before[sid_a]}
        assert _counts(win, sid_c) == {sid_c: before[sid_c]}

    def test_persistent_undo_after_restart_never_returns_other_silo_text(
            self, win):
        cat = _reset(win, ("ALPHA", "BRAVO"))
        sid_a = win.state.silo_id_for(cat, False, 0)
        sid_b = win.state.silo_id_for(cat, False, 1)
        _commit(win)

        win.swap_temp_slots(0, 1, False)
        _commit(win)
        # BRAVO now owns slot 0; edit it and commit exactly one transition.
        win._switch_to_slot(0, initial=True, is_archive=False)
        win.text_area.setPlainText("BRAVO v2")
        assert win.save_data_to_db(force=True) is True

        fresh = state_mod.FastPrompterState(profile_id=1)
        try:
            bind_active_category(fresh.data, cat)
            slots = fresh.data["temp_presets_all"][cat]
            assert fresh.silo_id_for(cat, False, slots.index("BRAVO v2")) \
                == sid_b
            assert fresh.silo_text_history_for(sid_a) == []
            assert [h[2] for h in fresh.silo_text_history_for(sid_b)] \
                == ["BRAVO v2"]
        finally:
            if fresh.conn is not None:
                fresh.conn.close()

        from fastprompter.main import FastPrompter
        w2 = FastPrompter()
        for _ in range(5):
            _APP.processEvents()
        w2._initializing_ui = False
        w2._suspend_temp_sync = False
        try:
            w2._persistent_history_cursor = {}
            w2.text_area.setPlainText("BRAVO v2")
            assert w2._persistent_text_step(forward=False)
            assert w2.text_area.toPlainText() == "BRAVO"
            assert w2.text_area.toPlainText() != "ALPHA"
        finally:
            for name in ("auto_save_timer", "topmost_timer", "_cache_timer"):
                timer = getattr(w2, name, None)
                if timer is not None:
                    timer.stop()
            service = getattr(w2, "limit_service", None)
            if service is not None:
                service.shutdown()
            if getattr(w2, "state", None) is not None:
                w2.state.conn = None
            w2.close()


class TestFailedCommitRetry:
    def test_failed_save_after_drain_commits_the_transition_exactly_once(
            self, win, monkeypatch):
        cat = _reset(win, ("BASE",))
        sid = win.state.silo_id_for(cat, False, 0)
        _commit(win)
        base = len(win.state.silo_text_history_for(sid))

        win.text_area.setPlainText("BASE v2")
        real_drain = win.state._drain_silo_history_locked

        def boom(cur):
            # The drain consumed the queue, then the transaction failed.
            win.state._pending_silo_history = []
            raise RuntimeError("simulated post-drain failure")

        monkeypatch.setattr(win.state, "_drain_silo_history_locked", boom)
        assert win.save_data_to_db(force=True) is False
        assert any(r[1] == "BASE" and r[2] == "BASE v2"
                   for r in win.state._pending_silo_history)

        monkeypatch.setattr(win.state, "_drain_silo_history_locked",
                            real_drain)
        assert win.save_data_to_db(force=True) is True
        hist = win.state.silo_text_history_for(sid)[base:]
        assert [(h[1], h[2]) for h in hist] == [("BASE", "BASE v2")]
