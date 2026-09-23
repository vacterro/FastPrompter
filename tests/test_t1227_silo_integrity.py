"""T-1227 [P0] SILO identity / crash-safe persistence / persistent undo.

These are the focused, end-to-end invariants from the audit wave
`FASTPROMPTER - P0_20260908_0713.md`:

* a scroll/settings-only save can never rewrite SILO text;
* an owner-mismatched flush is refused and lands in a recovery artifact;
* identity anchors travel with their silo through reorder/insert/delete
  and survive a restart;
* destructive silo ops refuse to run when the durable before-state cannot
  be published;
* committed text transitions keep their recovery predecessor in the SAME
  transaction;
* Ctrl+Z / Ctrl+Y fall back to the persistent history after a restart,
  with standard redo-branch invalidation.
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
    tmp_path = tmp_path_factory.mktemp("t1227")
    original_db_path = state_mod.get_db_path
    state_mod.get_db_path = (
        lambda profile_id=1: str(tmp_path / f"t1227_{profile_id}.db"))
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
    # The deferred profile-apply (QTimer.singleShot(0)) clears the
    # initialization guards; without a running event loop it never fires,
    # and every authoritative save would skip the live-editor flush.
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


def _reset(win, texts=("alpha", "bravo", "charlie", "delta")):
    win.cat_combo.setCurrentIndex(0)
    win.on_tab_changed(0)
    win.data["temp_presets"][:] = list(texts)
    win._persistent_history_cursor = {}
    win._persistent_history_suppress_sid = None
    win._switch_to_slot(0, initial=True, is_archive=False)
    return win.get_current_category()


def _commit_text(win, text):
    win.text_area.setPlainText(text)
    win.save_data_to_db(force=True)


class TestNoWrongSlotWrites:
    def test_scroll_only_save_cannot_alter_silo_text(self, win):
        _reset(win)
        before = list(win.data["temp_presets"])
        # The idle/scroll path captures view state and marks settings dirty;
        # it never edited text. The revision gate must skip the flush.
        win.capture_silo_state(0, False)
        win.mark_dirty("settings")
        calls = []
        original = win.mark_dirty
        win.mark_dirty = lambda domain=None: (calls.append(domain),
                                              original(domain))[1]
        try:
            win.save_data_to_db(force=True)
        finally:
            win.mark_dirty = original
        assert win.data["temp_presets"] == before
        assert "temp" not in calls and "arc" not in calls

    def test_owner_mismatch_flush_is_refused_and_archived(self, win):
        _reset(win)
        doc = win._active_doc()
        # A disagreeing stamp is exactly the wrong-slot corruption signal.
        doc._fastprompter_owner = ("SOME_OTHER_CATEGORY", False, 7)
        before = list(win.data["temp_presets"])
        win._flush_live_editor("HACKED-CONTENT")
        assert win.data["temp_presets"] == before
        base = os.path.join(os.path.dirname(win.state.db_path), "recovery")
        artifacts = [n for n in os.listdir(base)
                     if n.startswith("silo_owner_mismatch_")]
        assert artifacts, "owner mismatch must leave a recovery artifact"


class TestIdentityStability:
    def test_identity_follows_silo_through_move_insert_delete(self, win):
        cat = _reset(win)
        marker = win.state.silo_id_for(cat, False, 2)
        assert marker

        win.move_temp_to_index(2, 0)
        assert win.data["temp_presets"][0] == "charlie"
        assert win.state.silo_id_for(cat, False, 0) == marker

        win.insert_silo_at("newbie", pos=0)
        assert win.data["temp_presets"][1] == "charlie"
        assert win.state.silo_id_for(cat, False, 1) == marker

        win.del_silo(0)
        idx = win.data["temp_presets"].index("charlie")
        assert idx == 0
        assert win.state.silo_id_for(cat, False, idx) == marker

    def test_identity_survives_restart(self, win):
        cat = _reset(win, ("one", "two", "three"))
        win.move_temp_to_index(2, 0)
        idx = win.data["temp_presets"].index("three")
        marker = win.state.silo_id_for(cat, False, idx)
        win.save_data_to_db(force=True)

        fresh = state_mod.FastPrompterState(profile_id=1)
        try:
            bind_active_category(fresh.data, cat)
            slots = fresh.data["temp_presets_all"][cat]
            assert fresh.silo_id_for(cat, False, slots.index("three")) == marker
        finally:
            if fresh.conn is not None:
                fresh.conn.close()

    def test_identity_follows_silo_through_category_transfer(self, win):
        cat = _reset(win, ("alpha", "bravo", "charlie"))
        target = next(c for c in win.data["categories"] if c != cat)
        marker = win.state.silo_id_for(cat, False, 2)
        assert win.transfer_silo_to_project(2, target) is True
        win.save_data_to_db(force=True)
        dest = win.data["temp_presets_all"][target]
        idx = dest.index("charlie")
        assert win.state.silo_id_for(target, False, idx) == marker
        assert win.state.silo_id_for(cat, False, 2) != marker

    def test_identity_survives_cross_space_swap(self, win):
        cat = _reset(win, ("alpha", "bravo"))
        win.data["archive_temp_presets"][:] = ["arch1", "arch2"]
        win.state._load_silo_identities()
        nid = win.state.silo_id_for(cat, False, 0)
        aid = win.state.silo_id_for(cat, True, 0)
        assert nid and aid and nid != aid

        win.swap_cross_temp_slots(0, 0, False, True)
        assert win.data["temp_presets"][0] == "arch1"
        assert win.data["archive_temp_presets"][0] == "alpha"
        assert win.state.silo_id_for(cat, False, 0) == aid
        assert win.state.silo_id_for(cat, True, 0) == nid


class TestDurableUndoBefore:
    def test_publish_failure_refuses_destructive_op(self, win, monkeypatch):
        _reset(win, ("alpha", "bravo"))
        monkeypatch.setattr(win, "_wait_for_undo_saves",
                            lambda *a, **k: False)
        assert win._durable_undo_or_refuse("Move silo") is False
        assert win.del_silo(0) is False
        assert win.data["temp_presets"] == ["alpha", "bravo"]

    def test_publish_success_allows_op(self, win, monkeypatch):
        _reset(win, ("alpha", "bravo"))
        monkeypatch.setattr(win, "_wait_for_undo_saves",
                            lambda *a, **k: True)
        assert win._durable_undo_or_refuse("Move silo") is True


def _trash_files(win):
    """Every recovery artifact currently sitting in the profile's _trash."""
    trash = os.path.join(win._files_root(), "_trash")
    try:
        return sorted(os.listdir(trash))
    except OSError:
        return []


class TestDeleteIsDurableBefore:
    """T-1261: delete was the ONE destructive silo op still pushing a
    non-durable before-state.

    ``del_silo`` used to call ``add_data_undo_state("Delete silo")`` with no
    ``durable=True``, so the snapshot was queued for the undo writer thread
    and the delete marched on regardless. A crash (or a failed flush) between
    that push and the trash write destroyed the silo with nothing on disk to
    come back to — exactly what T-1227 §17 exists to prevent. These tests
    inject the publish failure and assert that NOTHING moved.
    """

    def _refuse_publication(self, win, monkeypatch):
        monkeypatch.setattr(win, "_wait_for_undo_saves",
                            lambda *a, **k: False)

    def test_refusal_returns_false_and_keeps_the_text(self, win, monkeypatch):
        _reset(win, ("alpha", "bravo", "charlie"))
        self._refuse_publication(win, monkeypatch)
        assert win.del_silo(1) is False
        assert win.data["temp_presets"] == ["alpha", "bravo", "charlie"]

    def test_refusal_keeps_the_physical_folder(self, win, monkeypatch):
        _reset(win, ("alpha", "bravo"))
        folder = win._silo_folder_dir(1, is_archive=False)
        assert folder is not None
        os.makedirs(folder, exist_ok=True)
        marker = os.path.join(folder, "asset.txt")
        with open(marker, "w", encoding="utf-8") as handle:
            handle.write("keep me")

        self._refuse_publication(win, monkeypatch)
        assert win.del_silo(1) is False
        assert os.path.isdir(folder)
        with open(marker, encoding="utf-8") as handle:
            assert handle.read() == "keep me"

    def test_refusal_keeps_ownership_mappings(self, win, monkeypatch):
        _reset(win, ("alpha", "bravo"))
        win.data.setdefault("silo_folders", {})["1"] = "bravo-folder"
        win.data.setdefault("silo_project_paths", {})["1"] = "C:/projects/bravo"

        self._refuse_publication(win, monkeypatch)
        assert win.del_silo(1) is False
        assert win.data["silo_folders"]["1"] == "bravo-folder"
        assert win.data["silo_project_paths"]["1"] == "C:/projects/bravo"

    def test_refusal_keeps_the_active_slot_and_documents(self, win,
                                                         monkeypatch):
        _reset(win, ("alpha", "bravo", "charlie"))
        win._switch_to_slot(2, initial=True, is_archive=False)
        slot_before = win.active_temp_slot
        docs_before = len(win.silo_docs)
        presets_before = len(win.data["temp_presets"])

        self._refuse_publication(win, monkeypatch)
        assert win.del_silo(0) is False
        assert win.active_temp_slot == slot_before
        assert len(win.silo_docs) == docs_before
        assert len(win.data["temp_presets"]) == presets_before

    def test_refusal_writes_no_trash_artifact(self, win, monkeypatch):
        _reset(win, ("alpha", "unique-refusal-marker-text"))
        before = _trash_files(win)

        self._refuse_publication(win, monkeypatch)
        assert win.del_silo(1) is False
        # A recovery copy would be a lie: it records a deletion that never
        # happened, and restore would offer to bring back a live silo.
        assert _trash_files(win) == before

    def test_refusal_leaves_no_phantom_undo_entry(self, win, monkeypatch):
        _reset(win, ("alpha", "bravo"))
        win.data_undo_stack = []
        win.data_redo_stack = []

        self._refuse_publication(win, monkeypatch)
        assert win.del_silo(1) is False
        # The refused op must not leave a "Delete silo" step the user can
        # undo into a state that was never reached.
        assert win.data_undo_stack == []

    def test_archive_delete_obeys_the_same_rule(self, win, monkeypatch):
        _reset(win, ("alpha", "bravo"))
        win.data["archive_temp_presets"][:] = ["arc-one", "arc-two"]
        self._refuse_publication(win, monkeypatch)
        assert win.del_silo(0, is_archive=True) is False
        assert win.data["archive_temp_presets"] == ["arc-one", "arc-two"]

    def test_skip_undo_keeps_its_explicitly_requested_semantics(
            self, win, monkeypatch):
        """``skip_undo=True`` means the CALLER owns the before-state.

        It is used by flows that already published their own snapshot, so a
        failing undo writer must not veto them — otherwise the durable-before
        rule would be applied twice to one logical operation.
        """
        _reset(win, ("alpha", "bravo", "charlie"))
        self._refuse_publication(win, monkeypatch)
        assert win.del_silo(1, skip_undo=True) is True
        assert win.data["temp_presets"] == ["alpha", "charlie"]

    def test_successful_delete_still_publishes_and_stays_undoable(self, win,
                                                                 monkeypatch):
        _reset(win, ("alpha", "bravo", "charlie"))
        monkeypatch.setattr(win, "_wait_for_undo_saves", lambda *a, **k: True)
        win.data_undo_stack = []
        win.data_redo_stack = []

        assert win.del_silo(1) is True
        assert win.data["temp_presets"] == ["alpha", "charlie"]
        # exactly one before-state, and it describes the pre-delete world
        assert len(win.data_undo_stack) == 1
        assert win.data_undo_stack[-1]["temp_presets"] == [
            "alpha", "bravo", "charlie"]

    def test_a_deduped_publish_is_not_popped_by_a_later_abort(self, win,
                                                             monkeypatch):
        """The dedup path returns the EXISTING top, which we did not push.

        ``add_data_undo_state(durable=True)`` returns ``data_undo_stack[-1]``
        when the new snapshot equals the top. Treating that as "ours" would
        make a staging failure pop somebody else's history entry.
        """
        _reset(win, ("alpha", "bravo"))
        monkeypatch.setattr(win, "_wait_for_undo_saves", lambda *a, **k: True)
        win.data_undo_stack = []
        win.data_redo_stack = []
        # push the identical state first, so the delete's publish dedups
        seeded = win.add_data_undo_state("Seeded before-state")
        assert seeded is not None
        monkeypatch.setattr(win, "_trash_silo_content",
                            lambda *a, **k: False)   # force the abort path

        assert win.del_silo(1) is False
        assert win.data["temp_presets"] == ["alpha", "bravo"]
        assert win.data_undo_stack and win.data_undo_stack[-1] is seeded


class TestDeleteCueIsSuccessFeedback:
    """T-1261: the "delete" sound means a silo WAS deleted.

    ``del_silo`` used to open with ``sound_manager.play("delete")`` — before
    index validation, before the durable undo publication, before trash
    staging and before physical retirement. Every refusal therefore sounded
    exactly like a completed deletion, and ``del_last_snippet`` played a
    second cue of its own on top of the successful path.
    """

    @staticmethod
    def _cues(win, monkeypatch):
        """Record every sound key requested during the operation."""
        played = []
        monkeypatch.setattr(win.sound_manager, "play",
                            lambda key, *a, **k: played.append(key))
        return played

    def test_publication_refusal_plays_no_delete_cue(self, win, monkeypatch):
        _reset(win, ("alpha", "bravo"))
        monkeypatch.setattr(win, "_wait_for_undo_saves",
                            lambda *a, **k: False)
        played = self._cues(win, monkeypatch)
        assert win.del_silo(1) is False
        assert played.count("delete") == 0

    def test_retirement_failure_plays_no_delete_cue(self, win, monkeypatch):
        _reset(win, ("alpha", "bravo"))
        monkeypatch.setattr(win, "_wait_for_undo_saves", lambda *a, **k: True)
        monkeypatch.setattr(win, "_delete_file_container",
                            lambda *a, **k: "FAILED")
        played = self._cues(win, monkeypatch)
        assert win.del_silo(1) is False
        assert win.data["temp_presets"] == ["alpha", "bravo"]
        assert played.count("delete") == 0

    def test_trash_staging_failure_plays_no_delete_cue(self, win, monkeypatch):
        _reset(win, ("alpha", "bravo"))
        monkeypatch.setattr(win, "_wait_for_undo_saves", lambda *a, **k: True)
        monkeypatch.setattr(win, "_trash_silo_content", lambda *a, **k: False)
        played = self._cues(win, monkeypatch)
        assert win.del_silo(1) is False
        assert played.count("delete") == 0

    def test_invalid_target_plays_no_delete_cue(self, win, monkeypatch):
        _reset(win, ("alpha", "bravo"))
        played = self._cues(win, monkeypatch)
        assert win.del_silo(99) is False
        assert played.count("delete") == 0

    def test_guard_not_met_plays_no_delete_cue(self, win, monkeypatch):
        """One silo left: the op is a no-op, so it must stay silent."""
        _reset(win, ("only",))
        played = self._cues(win, monkeypatch)
        assert win.del_silo(0) is False
        assert played.count("delete") == 0

    def test_successful_delete_plays_exactly_one_cue(self, win, monkeypatch):
        _reset(win, ("alpha", "bravo", "charlie"))
        monkeypatch.setattr(win, "_wait_for_undo_saves", lambda *a, **k: True)
        played = self._cues(win, monkeypatch)
        assert win.del_silo(1) is True
        assert win.data["temp_presets"] == ["alpha", "charlie"]
        assert played.count("delete") == 1

    def test_successful_archive_delete_plays_exactly_one_cue(self, win,
                                                             monkeypatch):
        _reset(win, ("alpha", "bravo"))
        win.data["archive_temp_presets"][:] = ["arc-one", "arc-two"]
        monkeypatch.setattr(win, "_wait_for_undo_saves", lambda *a, **k: True)
        played = self._cues(win, monkeypatch)
        assert win.del_silo(0, is_archive=True) is True
        assert played.count("delete") == 1

    def test_defer_ui_delete_stays_silent_for_its_batch_owner(self, win,
                                                             monkeypatch):
        """Batch delete plays ONE cue for the whole selection."""
        _reset(win, ("alpha", "bravo", "charlie"))
        monkeypatch.setattr(win, "_wait_for_undo_saves", lambda *a, **k: True)
        played = self._cues(win, monkeypatch)
        assert win.del_silo(1, defer_ui=True) is True
        assert played.count("delete") == 0

    def test_ui_route_does_not_double_the_cue(self, win, monkeypatch):
        """``del_last_snippet`` -> ``del_silo``: one gesture, one cue."""
        from PyQt6.QtWidgets import QMessageBox

        import fastprompter.ui.snippet_ops_mixin as ops_mod

        _reset(win, ("alpha", "bravo"))
        win._switch_to_slot(1, initial=True, is_archive=False)
        win.editing_snippet = None
        win.text_area.setPlainText("bravo")
        monkeypatch.setattr(win, "_wait_for_undo_saves", lambda *a, **k: True)
        monkeypatch.setattr(
            ops_mod.QMessageBox, "question",
            staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes))
        played = self._cues(win, monkeypatch)

        win.del_last_snippet()
        assert played.count("delete") == 1
        assert len(win.data["temp_presets"]) == 1

    def test_ui_route_refusal_plays_no_cue(self, win, monkeypatch):
        from PyQt6.QtWidgets import QMessageBox

        import fastprompter.ui.snippet_ops_mixin as ops_mod

        _reset(win, ("alpha", "bravo"))
        win._switch_to_slot(1, initial=True, is_archive=False)
        win.editing_snippet = None
        win.text_area.setPlainText("bravo")
        monkeypatch.setattr(win, "_wait_for_undo_saves",
                            lambda *a, **k: False)
        monkeypatch.setattr(
            ops_mod.QMessageBox, "question",
            staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes))
        played = self._cues(win, monkeypatch)

        win.del_last_snippet()
        assert played.count("delete") == 0
        assert win.data["temp_presets"] == ["alpha", "bravo"]


class TestPersistentHistory:
    def test_transition_commits_with_predecessor(self, win):
        cat = _reset(win, ("A",))
        sid = win.state.silo_id_for(cat, False, 0)
        _commit_text(win, "A")
        base = len(win.state.silo_text_history_for(sid))
        _commit_text(win, "A + edit1")
        hist = win.state.silo_text_history_for(sid)[base:]
        assert [(h[1], h[2]) for h in hist] == [("A", "A + edit1")]
        assert win.data["temp_presets"][0] == "A + edit1"

    def test_persistent_undo_redo_after_restart(self, win):
        _reset(win, ("A",))
        _commit_text(win, "A")
        for text in ("A + edit1", "A + edit1 + edit2"):
            _commit_text(win, text)

        # Simulate a restart: no native undo steps and no cursor.
        win._persistent_history_cursor = {}
        win.text_area.setPlainText("A + edit1 + edit2")

        assert win._persistent_text_step(forward=False)
        assert win.text_area.toPlainText() == "A + edit1"
        assert win._persistent_text_step(forward=False)
        assert win.text_area.toPlainText() == "A"
        assert win._persistent_text_step(forward=True)
        assert win.text_area.toPlainText() == "A + edit1"
        assert win._persistent_text_step(forward=True)
        assert win.text_area.toPlainText() == "A + edit1 + edit2"

    def test_new_commit_discards_redo_branch(self, win):
        cat = _reset(win, ("A",))
        sid = win.state.silo_id_for(cat, False, 0)
        _commit_text(win, "A")
        _commit_text(win, "B")
        _commit_text(win, "C")

        win._persistent_history_cursor = {}
        win.text_area.setPlainText("C")
        assert win._persistent_text_step(forward=False)  # back to B
        assert win.text_area.toPlainText() == "B"

        _commit_text(win, "D")
        # The abandoned C branch must be gone from the timeline.
        timeline = [h[2] for h in win.state.silo_text_history_for(sid)]
        assert timeline[-1] == "D"
        assert "C" not in timeline
        assert win._persistent_history_cursor.get(sid) is None

        # And a fresh persistent undo from D reaches B, never C.
        win._persistent_history_cursor = {}
        win.text_area.setPlainText("D")
        assert win._persistent_text_step(forward=False)
        assert win.text_area.toPlainText() == "B"


class TestSaveRollback:
    def test_failed_save_restores_recovery_queue(self, win, monkeypatch):
        cat = _reset(win, ("A",))
        sid = win.state.silo_id_for(cat, False, 0)
        _commit_text(win, "A")
        base = len(win.state.silo_text_history_for(sid))
        win.state.record_silo_text_history(sid, "A", "A + edit1", "test")

        real_drain = win.state._drain_silo_history_locked

        def boom(cur):
            # Simulate the real drain consuming the queue, then the txn
            # failing before commit.
            win.state._pending_silo_history = []
            raise RuntimeError("simulated post-drain failure")

        monkeypatch.setattr(win.state, "_drain_silo_history_locked", boom)
        assert win.state.save_data_to_db("A + edit1", force=True) is False
        assert any(r[1] == "A" and r[2] == "A + edit1"
                   for r in win.state._pending_silo_history)

        monkeypatch.setattr(win.state, "_drain_silo_history_locked", real_drain)
        assert win.state.save_data_to_db("A + edit1", force=True) is True
        hist = win.state.silo_text_history_for(sid)[base:]
        assert [(h[1], h[2]) for h in hist] == [("A", "A + edit1")]


class TestCrashRestart:
    def test_restart_has_no_twin_and_recovers_predecessor(self, win):
        cat = _reset(win, ("alpha",))
        sid = win.state.silo_id_for(cat, False, 0)
        for text in ("A", "A + edit1", "A + edit1 + edit2"):
            _commit_text(win, text)
        # Every commit above is durable on disk; opening a second window
        # against the same DB is the post-crash restart path.
        from fastprompter.main import FastPrompter
        w2 = FastPrompter()
        for _ in range(5):
            _APP.processEvents()
        w2._initializing_ui = False
        w2._suspend_temp_sync = False
        try:
            last = "A + edit1 + edit2"
            assert w2.data["temp_presets"].count(last) == 1
            idx = w2.data["temp_presets"].index(last)
            sid2 = w2.state.silo_id_for(w2.get_current_category(), False, idx)
            assert sid2 == sid
            timeline = [h[2] for h in w2.state.silo_text_history_for(sid2)]
            assert timeline[-1] == last
            assert "A + edit1" in timeline

            # Ctrl+Z after restart has no native step: the persistent
            # history must still recover the predecessor.
            w2._persistent_history_cursor = {}
            w2.text_area.setPlainText(last)
            assert w2._persistent_text_step(forward=False)
            assert w2.text_area.toPlainText() == "A + edit1"
        finally:
            for name in ("auto_save_timer", "topmost_timer", "_cache_timer"):
                timer = getattr(w2, name, None)
                if timer is not None:
                    timer.stop()
            service = getattr(w2, "limit_service", None)
            if service is not None:
                service.shutdown()
            w2._in_physical_teardown = True
            push_clean = w2._push_shutdown()
            if getattr(w2, "state", None) is not None:
                w2.state.conn = None
            w2.close()
            from _qt_retire import retire
            retire(w2)
            assert push_clean

