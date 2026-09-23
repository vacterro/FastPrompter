"""CORE-003 (audit/12, SRC-041 R003): archive lineage dirty ownership.

``_silo_lineage_is_trustworthy`` built its dirty-slot exemption from
``showing_archive`` — an attribute that does not exist on the window (absent
therefore False) — so an actively edited ARCHIVE silo was never exempted and
its legitimate unsaved edit produced a false SILO_LINEAGE_MISMATCH refusal.
The exemption now derives from the SAME canonical active-owner helper that
resolves active identity, and genuine mismatches still fail closed.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtWidgets import QApplication

import fastprompter.core.state as state_mod

_APP = QApplication.instance() or QApplication([])


@pytest.fixture(scope="module")
def win(tmp_path_factory):
    tmp_path = tmp_path_factory.mktemp("core003")
    original_db_path = state_mod.get_db_path
    state_mod.get_db_path = (
        lambda profile_id=1: str(tmp_path / f"core003_{profile_id}.db"))
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


class TestCanonicalDirtyOwner:
    def test_archive_active_dirty_tuple_is_canonical(self, win, monkeypatch):
        cat = _reset(win, ("N",))
        win.data["archive_temp_presets"][:] = ["Z"]
        win.state._load_silo_identities()
        win._switch_to_slot(0, initial=True, is_archive=True)
        assert win.active_is_archive is True

        captured = {}

        def spy(dirty_slots=()):
            captured["dirty"] = tuple(dirty_slots)
            return []

        monkeypatch.setattr(win.state, "validate_silo_lineage", spy)
        sid = win.state.silo_id_for(cat, True, 0)
        assert win._silo_lineage_is_trustworthy(sid) is True
        assert captured["dirty"] == ((cat, True, 0),)

    def test_normal_active_dirty_tuple_is_canonical(self, win, monkeypatch):
        cat = _reset(win, ("N",))
        win._switch_to_slot(0, initial=True, is_archive=False)
        assert win.active_is_archive is False

        captured = {}

        def spy(dirty_slots=()):
            captured["dirty"] = tuple(dirty_slots)
            return []

        monkeypatch.setattr(win.state, "validate_silo_lineage", spy)
        sid = win.state.silo_id_for(cat, False, 0)
        assert win._silo_lineage_is_trustworthy(sid) is True
        assert captured["dirty"] == ((cat, False, 0),)


class TestLineageTruthfulness:
    def test_unsaved_archive_edit_is_not_a_false_refusal(self, win):
        cat = _reset(win, ("N",))
        win.data["archive_temp_presets"][:] = ["Z1"]
        win.state._load_silo_identities()
        sid = win.state.silo_id_for(cat, True, 0)
        win.state.record_silo_text_history(sid, "Z0", "Z1", "test")
        assert win.state.save_data_to_db("Z1", force=True) is True

        # A legitimate unsaved archive edit: memory differs from the newest
        # committed hash, exactly like typing in the active editor.
        win.data["archive_temp_presets"][0] = "Z1 + live edit"
        win._switch_to_slot(0, initial=True, is_archive=True)
        assert win._silo_lineage_is_trustworthy(sid) is True

    def test_genuine_archive_mismatch_in_inactive_slot_fails_closed(
            self, win):
        cat = _reset(win, ("N",))
        win.data["archive_temp_presets"][:] = ["Z1", "Z2"]
        win.state._load_silo_identities()
        sid1 = win.state.silo_id_for(cat, True, 1)
        win.state.record_silo_text_history(sid1, "Z0", "Z2", "test")
        assert win.state.save_data_to_db("Z2", force=True) is True

        # Slot 1 is NOT the active silo, so its mismatch must not be exempt.
        win.data["archive_temp_presets"][1] = "TAMPERED"
        win._switch_to_slot(0, initial=True, is_archive=True)
        assert win._silo_lineage_is_trustworthy(sid1) is False

    def test_normal_active_edit_is_not_a_false_refusal(self, win):
        cat = _reset(win, ("N1",))
        sid = win.state.silo_id_for(cat, False, 0)
        win.state.record_silo_text_history(sid, "N0", "N1", "test")
        assert win.state.save_data_to_db("N1", force=True) is True

        win.data["temp_presets"][0] = "N1 + live edit"
        win._switch_to_slot(0, initial=True, is_archive=False)
        assert win._silo_lineage_is_trustworthy(sid) is True
