"""CORE-002 (audit/12, SRC-041 R002): persistent undo/redo must acknowledge
durable publication.

``_apply_persistent_text`` discarded the forced save's boolean and
``_persistent_text_step`` advanced ``_persistent_history_cursor`` regardless,
so a refused authoritative save still reported a successful recovery step and
moved the forensic timeline. Failure injection is the point of this file:
every refusal path is exercised with the save forced False, then with the save
raising, and the durable restart result is proven in both directions.
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
    tmp_path = tmp_path_factory.mktemp("core002")
    original_db_path = state_mod.get_db_path
    state_mod.get_db_path = (
        lambda profile_id=1: str(tmp_path / f"core002_{profile_id}.db"))
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
    st = win.state
    ids = getattr(st, "silo_identities", None)
    if ids is not None:
        for key in [k for k in ids if k[0] == cat]:
            del ids[key]
    try:
        with st.conn:
            st.conn.execute(
                "DELETE FROM silo_identity_v1 WHERE category=?", (cat,))
    except Exception:
        pass
    st._load_silo_identities()
    return cat


def _commit_text(win, text):
    win.text_area.setPlainText(text)
    assert win.save_data_to_db(force=True) is True


def _history_rows(win, sid):
    return win.state.silo_text_history_for(sid)


class TestRefusedPublication:
    def test_failed_persistent_undo_is_fail_closed(self, win, monkeypatch):
        cat = _reset(win, ("A",))
        sid = win.state.silo_id_for(cat, False, 0)
        _commit_text(win, "A")
        _commit_text(win, "B")
        base = len(_history_rows(win, sid))
        win.state.mark_dirty("settings")
        settings_dirty = win.state._dirty_settings

        attempts = {"n": 0}

        def refusing_save(force=False, **kw):
            attempts["n"] += 1
            return False

        monkeypatch.setattr(win, "save_data_to_db", refusing_save)
        assert win._persistent_text_step(forward=False) is False

        assert attempts["n"] == 1, "exactly one authoritative publication try"
        assert win.text_area.toPlainText() == "B"
        assert win.data["temp_presets"][0] == "B"
        assert sid not in win._persistent_history_cursor
        assert len(_history_rows(win, sid)) == base, "no reverse history"
        assert win._persistent_history_suppress_sid is None
        # Unrelated dirty domains and retry markers are preserved.
        assert win.state._dirty_settings == settings_dirty
        assert win.state.has_pending_changes is True

    def test_failed_persistent_redo_is_fail_closed(self, win, monkeypatch):
        cat = _reset(win, ("A",))
        sid = win.state.silo_id_for(cat, False, 0)
        _commit_text(win, "A")
        _commit_text(win, "B")

        # Establish a real post-undo state: store "A", cursor at 0.
        assert win._persistent_text_step(forward=False) is True
        assert win.text_area.toPlainText() == "A"
        assert win.data["temp_presets"][0] == "A"
        assert win._persistent_history_cursor == {sid: 0}
        base = len(_history_rows(win, sid))

        monkeypatch.setattr(win, "save_data_to_db",
                            lambda force=False, **kw: False)
        assert win._persistent_text_step(forward=True) is False

        assert win.text_area.toPlainText() == "A"
        assert win.data["temp_presets"][0] == "A"
        assert win._persistent_history_cursor == {sid: 0}
        assert len(_history_rows(win, sid)) == base

    def test_exception_from_save_path_is_fail_closed(self, win, monkeypatch):
        cat = _reset(win, ("A",))
        sid = win.state.silo_id_for(cat, False, 0)
        _commit_text(win, "A")
        _commit_text(win, "B")
        base = len(_history_rows(win, sid))

        def exploding_save(force=False, **kw):
            raise RuntimeError("storage failure")

        monkeypatch.setattr(win, "save_data_to_db", exploding_save)
        assert win._persistent_text_step(forward=False) is False

        assert win.text_area.toPlainText() == "B"
        assert win.data["temp_presets"][0] == "B"
        assert sid not in win._persistent_history_cursor
        assert len(_history_rows(win, sid)) == base
        assert win._persistent_history_suppress_sid is None


class TestSuccessfulPublication:
    def test_successful_undo_advances_exactly_once_and_survives_restart(
            self, win, monkeypatch):
        cat = _reset(win, ("A",))
        sid = win.state.silo_id_for(cat, False, 0)
        _commit_text(win, "A")
        _commit_text(win, "B")
        base = len(_history_rows(win, sid))

        calls = {"n": 0}
        real_save = win.save_data_to_db

        def counting_save(force=False, **kw):
            calls["n"] += 1
            return real_save(force=force, **kw)

        monkeypatch.setattr(win, "save_data_to_db", counting_save)
        assert win._persistent_text_step(forward=False) is True
        assert calls["n"] == 1
        assert win.text_area.toPlainText() == "A"
        assert win._persistent_history_cursor == {sid: 0}
        assert len(_history_rows(win, sid)) == base, \
            "a recovery replay never appends history"

        fresh = state_mod.FastPrompterState(profile_id=1)
        try:
            bind_active_category(fresh.data, cat)
            slots = fresh.data["temp_presets_all"][cat]
            assert slots[0] == "A", "the recovered value is the DB truth"
        finally:
            if fresh.conn is not None:
                fresh.conn.close()

    def test_failed_recovery_leaves_original_value_authoritative_after_restart(
            self, win, monkeypatch):
        cat = _reset(win, ("A",))
        _commit_text(win, "A")
        _commit_text(win, "B")

        monkeypatch.setattr(win, "save_data_to_db",
                            lambda force=False, **kw: False)
        assert win._persistent_text_step(forward=False) is False

        fresh = state_mod.FastPrompterState(profile_id=1)
        try:
            bind_active_category(fresh.data, cat)
            slots = fresh.data["temp_presets_all"][cat]
            assert slots[0] == "B", "the original value stays the DB truth"
        finally:
            if fresh.conn is not None:
                fresh.conn.close()
