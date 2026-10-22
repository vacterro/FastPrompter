"""PERF-004 acceptance: a save that cannot contain a silo-text transition
skips the whole-workspace silo-history diff (T-1432 / SRC-093).

The audit found ``save_data_to_db()`` calling ``_queue_silo_text_history()``
unconditionally: once ANY domain was dirty, the diff reconstructed the committed
identity->text map and walked every normal and archive category (up to 100 slots
each) just to discover zero transitions — so a font-size or snippet save cost
scaled with total workspace size.

What this file pins, one test per audit VERIFY bullet:

* a settings-only save on a LARGE workspace never enters
  ``committed_silo_identities()`` or the diff;
* a snippet-only save skips it too;
* one normal silo edit still queues OLD->NEW and persists it;
* one archive silo edit does the same;
* a forced save and a generic full-scan dirty flag still run the full diff, and
  a pending identity mutation still takes the ownership reconciliation;
* a structural swap with unchanged text queues zero transitions on the plain
  (non-forced) save path;
* the walk the gate removes is measured directly, so the "large workspace"
  claim is evidence rather than assertion.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtWidgets import QApplication

import fastprompter.core.state as state_mod
from fastprompter.core.state import FastPrompterState

_APP = QApplication.instance() or QApplication([])

CATS = 12
SLOTS = 100


@pytest.fixture(scope="module")
def win(tmp_path_factory):
    tmp_path = tmp_path_factory.mktemp("perf004")
    original_db_path = state_mod.get_db_path
    state_mod.get_db_path = (
        lambda profile_id=1: str(tmp_path / f"perf004_{profile_id}.db"))
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
        w._in_physical_teardown = True
        push_clean = w._push_shutdown()
        if getattr(w, "state", None) is not None:
            w.state.conn = None
        w.close()
        from _qt_retire import retire
        retire(w)
        for name, value in originals.items():
            setattr(FastPrompter, name, value)
        state_mod.get_db_path = original_db_path
        backup_mod.run_portable_backup = original_backup
        assert push_clean


def _spy(monkeypatch, win):
    """Count exactly the two calls PERF-004 removes, plus recorded transitions.

    ``committed_silo_identities`` is used ONLY by the diff, and
    ``_queue_silo_text_history`` is called ONLY from the save path, so a zero
    count is a precise "the diff was not entered" rather than a proxy.
    """
    calls = {"queue": 0, "identities": 0, "recorded": 0}

    real_queue = win._queue_silo_text_history

    def counting_queue(*args, **kwargs):
        calls["queue"] += 1
        return real_queue(*args, **kwargs)

    monkeypatch.setattr(win, "_queue_silo_text_history", counting_queue)

    real_identities = FastPrompterState.committed_silo_identities

    def counting_identities(self, *args, **kwargs):
        calls["identities"] += 1
        return real_identities(self, *args, **kwargs)

    monkeypatch.setattr(FastPrompterState, "committed_silo_identities", counting_identities)

    real_record = FastPrompterState.record_silo_text_history

    def counting_record(self, *args, **kwargs):
        calls["recorded"] += 1
        return real_record(self, *args, **kwargs)

    monkeypatch.setattr(FastPrompterState, "record_silo_text_history", counting_record)

    return calls


def _small_workspace(win, texts=("alpha", "bravo"), archive=()):
    """Fresh identities for a small, deterministic silo space."""
    win.cat_combo.setCurrentIndex(0)
    win.on_tab_changed(0)
    cat = win.get_current_category()
    win.data["temp_presets"][:] = list(texts)
    win.data["temp_presets_all"][cat][:] = list(texts)
    if archive:
        win.data["archive_temp_presets"][:] = list(archive)
        win.data["archive_temp_presets_all"][cat][:] = list(archive)
    win._persistent_history_cursor = {}
    win._persistent_history_suppress_sid = None
    win._switch_to_slot(0, initial=True, is_archive=False)
    st = win.state
    ids = getattr(st, "silo_identities", None)
    if ids is not None:
        # Each test gets FRESH anchors: a module-scoped window otherwise reuses
        # (category, slot) ids, and an in-place text reset would then be a
        # legitimate identity edit of the previous test's silo.
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


def _install_large_workspace(win):
    """Many categories x 100 slots in both spaces, then one forced commit.

    The active category's lists are edited IN PLACE so the flat
    ``temp_presets``/``archive_temp_presets`` aliases stay bound to
    ``*_all[cat]``; otherwise the live-editor flush would legitimately see a
    text mismatch and mark the temp domain dirty.
    """
    cat = win.get_current_category()
    normal = win.data["temp_presets_all"]
    archive = win.data["archive_temp_presets_all"]
    for index in range(CATS):
        name = cat if index == 0 else f"perf004_cat{index}"
        texts = [f"normal {index}.{slot}" for slot in range(SLOTS)]
        atexts = [f"archive {index}.{slot}" for slot in range(SLOTS)]
        for store, values in ((normal, texts), (archive, atexts)):
            if name in store:
                store[name][:] = values
            else:
                store[name] = list(values)
    win.data["temp_presets"][:] = list(normal[cat])
    win.data["archive_temp_presets"][:] = list(archive[cat])
    win._switch_to_slot(0, initial=True, is_archive=False)
    win.state._load_silo_identities()
    assert win.save_data_to_db(force=True) is True
    assert len(win.state._last_saved_temp) >= CATS * SLOTS
    assert len(win.state._last_saved_arc) >= CATS * SLOTS
    assert win.state.has_pending_changes is False


class TestSavesThatCannotContainASiloTextTransition:

    def test_settings_only_save_skips_the_history_diff_on_a_large_workspace(
            self, win, monkeypatch):
        _install_large_workspace(win)
        calls = _spy(monkeypatch, win)

        win.data["font_family"] = "Courier New"
        win.mark_dirty("settings")
        assert win.save_data_to_db() is True

        assert calls == {"queue": 0, "identities": 0, "recorded": 0}
        # The save still did its own job: the settings domain committed and
        # nothing is left pending.
        assert win.state._saved_settings_gen == win.state._dirty_settings
        assert win.state.has_pending_changes is False

    def test_snippet_only_save_skips_the_history_diff(self, win, monkeypatch):
        _install_large_workspace(win)
        cat = win.get_current_category()
        snippet = win.data["categories"][cat][0]
        if not isinstance(snippet, dict):
            snippet = {"name": "perf004", "text": ""}
            win.data["categories"][cat][0] = snippet
        snippet["text"] = "snippet edited for PERF-004"
        win.mark_dirty("snippets")

        calls = _spy(monkeypatch, win)
        assert win.save_data_to_db() is True

        assert calls == {"queue": 0, "identities": 0, "recorded": 0}
        assert win.state.has_pending_changes is False

    def test_the_walk_the_gate_removes_is_measured_directly(self, win, monkeypatch):
        """The pre-repair path paid this traversal on every one of those saves."""
        _install_large_workspace(win)
        walked = {"slots": 0}
        real_silo_id_for = FastPrompterState.silo_id_for

        def counting_silo_id_for(self, *args, **kwargs):
            walked["slots"] += 1
            return real_silo_id_for(self, *args, **kwargs)

        monkeypatch.setattr(FastPrompterState, "silo_id_for", counting_silo_id_for)
        win._queue_silo_text_history()

        # Both spaces, every category, every slot: the identity resolution is
        # the per-silo cost the domain gate now skips entirely.
        assert walked["slots"] >= CATS * SLOTS


class TestSavesThatMustStillReconcile:

    def test_one_normal_silo_edit_still_queues_and_persists_its_transition(
            self, win, monkeypatch):
        cat = _small_workspace(win)
        win.save_data_to_db(force=True)
        sid = win.state.silo_id_for(cat, False, 0)
        assert sid
        base = len(win.state.silo_text_history_for(sid))

        calls = _spy(monkeypatch, win)
        win.text_area.setPlainText("alpha edited by the user")
        assert win.save_data_to_db() is True

        assert calls["queue"] == 1 and calls["identities"] == 1
        history = win.state.silo_text_history_for(sid)[base:]
        assert [(h[1], h[2]) for h in history] == [("alpha", "alpha edited by the user")]
        assert win.data["temp_presets"][0] == "alpha edited by the user"

    def test_one_archive_silo_edit_still_queues_and_persists_its_transition(
            self, win, monkeypatch):
        cat = _small_workspace(win, texts=("alpha",), archive=("archived alpha",))
        win.save_data_to_db(force=True)
        sid = win.state.silo_id_for(cat, True, 0)
        assert sid
        base = len(win.state.silo_text_history_for(sid))

        calls = _spy(monkeypatch, win)
        win.data["archive_temp_presets"][:] = ["archived alpha edited"]
        win.data["archive_temp_presets_all"][cat][:] = ["archived alpha edited"]
        win.mark_dirty("arc")
        assert win.save_data_to_db() is True

        assert calls["queue"] == 1 and calls["identities"] == 1
        history = win.state.silo_text_history_for(sid)[base:]
        assert [(h[1], h[2]) for h in history] == [
            ("archived alpha", "archived alpha edited")]
        assert win.data["archive_temp_presets"][0] == "archived alpha edited"

    def test_forced_save_still_runs_the_full_history_diff(self, win, monkeypatch):
        _small_workspace(win)
        win.save_data_to_db(force=True)

        calls = _spy(monkeypatch, win)
        assert win.save_data_to_db(force=True) is True

        assert calls["queue"] == 1 and calls["identities"] == 1

    def test_generic_full_scan_dirty_never_bypasses_reconciliation(
            self, win, monkeypatch):
        _small_workspace(win)
        win.save_data_to_db(force=True)
        win.state._db_dirty = True

        calls = _spy(monkeypatch, win)
        assert win.save_data_to_db() is True

        assert calls["queue"] == 1 and calls["identities"] == 1

    def test_pending_identity_mutation_still_takes_the_full_diff(
            self, win, monkeypatch):
        _small_workspace(win)
        win.save_data_to_db(force=True)
        win.state._silo_id_dirty = True

        calls = _spy(monkeypatch, win)
        assert win.save_data_to_db() is True

        assert calls["queue"] == 1 and calls["identities"] == 1

    def test_structural_swap_with_unchanged_text_queues_zero_transitions(
            self, win, monkeypatch):
        cat = _small_workspace(win, texts=("A", "B"))
        sid_a = win.state.silo_id_for(cat, False, 0)
        sid_b = win.state.silo_id_for(cat, False, 1)
        assert sid_a and sid_b and sid_a != sid_b
        win.save_data_to_db(force=True)
        before = {sid_a: len(win.state.silo_text_history_for(sid_a)),
                  sid_b: len(win.state.silo_text_history_for(sid_b))}
        assert before == {sid_a: 0, sid_b: 0}

        calls = _spy(monkeypatch, win)
        win.swap_temp_slots(0, 1, False)
        assert win.save_data_to_db() is True

        assert calls["recorded"] == 0
        assert win.data["temp_presets"][:2] == ["B", "A"]
        assert {sid_a: len(win.state.silo_text_history_for(sid_a)),
                sid_b: len(win.state.silo_text_history_for(sid_b))} == before
        assert not (getattr(win.state, "_pending_silo_history", None) or [])
