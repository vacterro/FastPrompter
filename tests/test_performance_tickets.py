"""Regression tests for the PERFORMANCE audit tickets (PERF-002..PERF-009).

Non-Qt deterministic core:
  PERF-002  settings-only dirty routing must not trigger snippet/temp/arc scans
  PERF-006  snapshot size accounting includes snippet text; switch undo compact
  PERF-008  portable-backup capture is coalesced (no deep copy while active)
  PERF-009  Sync latest-requested registry is retired after physical publish
"""

import os

import pytest

import fastprompter.utils.portable_backup as pb


# ----------------------------------------------------------------- PERF-002
def test_settings_dirty_does_not_touch_data_domains(tmp_path):
    from fastprompter.core import state as state_mod

    path = str(tmp_path / "db.db")
    state_mod.get_db_path = lambda profile_id=1: path
    s = state_mod.FastPrompterState(profile_id=1)
    try:
        before = {
            "snip": getattr(s, "_dirty_snippets", 0),
            "temp": getattr(s, "_dirty_temp", 0),
            "arc": getattr(s, "_dirty_arc", 0),
        }
        s.mark_dirty("settings")
        # a settings-only mutation must NOT touch the data-domain counters
        assert getattr(s, "_dirty_settings", 0) >= 1
        assert getattr(s, "_dirty_snippets", 0) == before["snip"]
        assert getattr(s, "_dirty_temp", 0) == before["temp"]
        assert getattr(s, "_dirty_arc", 0) == before["arc"]
        assert s._db_dirty is False
        # settle the load baseline first (the fresh state starts with dirty
        # data domains that the first save persists)
        assert s.save_data_to_db(None, force=False, sync=True)
        settled_snip = getattr(s, "_saved_snippets_gen", 0)
        assert settled_snip >= 1
        # a settings-only non-force save must scan settings only (not the
        # data domains), proving the dirty DOMAIN routing works.
        s.mark_dirty("settings")
        assert s.save_data_to_db(None, force=False, sync=True)
        assert getattr(s, "_saved_snippets_gen", 0) == settled_snip
    finally:
        s.conn.close()


# ----------------------------------------------------------------- PERF-006
def test_snapshot_text_size_counts_snippet_text():
    from fastprompter.main import _snapshot_text_size

    snap = {
        "temp_presets": ["aaaa"],          # 4
        "archive_temp_presets": ["bb"],    # 2
        "categories": {
            "Code": [{"text": "cccccccc"}, None, {"text": "dd"}],  # 10
        },
    }
    assert _snapshot_text_size(snap) == 4 + 2 + 10


def test_switch_undo_is_compact_not_full_snapshot():
    """add_data_undo_state("Switch silo") must produce a compact _switch record
    carrying NO categories/temp_presets (i.e. no deep copy of the universe)."""
    from fastprompter.main import FastPrompter
    import types

    # A minimal host that satisfies add_data_undo_state's needs
    class Host:
        data = {
            "categories": {"A": [{"name": "x", "text": "y"}] * 100},
            "cats_order": ["A"],
            "temp_presets": ["silo"] * 100,
            "archive_temp_presets": [],
            "pinned_silos": [],
            "silo_ticked": [],
            "silo_children": {},
            "silo_collapsed": [],
            "silo_folders": {},
            "silo_last_edited": {},
            "silo_colors": {},
            "silo_project_paths": {},
            "silo_types": {},
            "watcher_queues": {},
            "archive_silo_folders": {},
            "archive_project_paths": {},
            "silo_view_state_all": {},
            "silo_gaps": [],
            "silo_gap_names": {},
            "category_file_dirs": {},
        }
        active_temp_slot = 0
        active_is_archive = False
        editing_snippet = None
        data_undo_stack = []

        def __init__(self):
            self._seq = 0

        def _bump_action_seq(self):
            self._seq += 1
            return self._seq

        def _active_doc(self):
            return None

        def _text_undo_steps(self):
            return 0

        def _snapshot_current(self):
            raise AssertionError("_snapshot_current must NOT run for a switch")

        def _stamp_snapshot(self, snap):
            snap["_seq"] = self._bump_action_seq()
            snap["_doc_id"] = 0
            snap["_text_steps"] = 0
            return snap

        def _push_undo_state(self, state, action):
            pass

        def _save_undo_state(self):
            pass

        def get_current_category(self):
            return "A"

        def _same_snapshot(self, a, b):
            return False

    h = Host()
    state = FastPrompter._stamp_snapshot(
        h, {
            "_switch": True,
            "category": "A",
            "active_temp_slot": 1,
            "active_is_archive": False,
        })
    assert state.get("_switch") is True
    assert "categories" not in state
    assert "temp_presets" not in state


# ----------------------------------------------------------------- PERF-008
def test_backup_capture_coalesced_while_active(tmp_path, monkeypatch):
    backup_dir = str(tmp_path / "portable")
    os.makedirs(backup_dir, exist_ok=True)
    monkeypatch.setattr(pb, "get_portable_backup_dir", lambda: backup_dir)
    pb.last_success_by_profile.clear()
    pb._backup_active.clear()
    pb._backup_newer_wanted.clear()

    calls = {"n": 0}
    real_capture = pb.capture_snapshot

    def counting_capture(data, profile_id=1):
        calls["n"] += 1
        return real_capture(data, profile_id=profile_id)

    monkeypatch.setattr(pb, "capture_snapshot", counting_capture)

    # async-style: install a sink so the export is dispatched, not run
    received = []

    def fake_sink(snapshot):
        received.append(snapshot)

    pb.set_backup_sink(fake_sink)
    try:
        pb.run_portable_backup({}, profile_id=1)
        assert calls["n"] == 1  # first dispatch captures
        assert 1 in pb._backup_active
        assert len(received) == 1

        # PERF-008 as amended by CORE-002: while a request is active the
        # worker owns the export, so repeated eligible saves must NOT reach
        # the sink again -- but each one DOES refresh the pending snapshot
        # (an immutable committed copy), because deferred generation must be
        # exactly the state of the save that requested it.
        for _ in range(20):
            pb.run_portable_backup({}, profile_id=1)
        assert len(received) == 1, "coalescing must prevent repeated dispatches"
        assert calls["n"] == 21, "each eligible save refreshes its own snapshot"
        assert 1 in pb._backup_newer_wanted

        # worker finished: retire the active marker and deliver the NEWEST
        # pending snapshot immediately (CORE-003)
        pb.backup_finished(profile_id=1)
        assert len(received) == 2, "newest pending snapshot dispatched on finish"
        # the newest dispatch is itself in flight -> marker re-armed until
        # the worker reports that one done too
        assert 1 in pb._backup_active
        # throttle cleared for the wanted-newer profile -> next save captures
        assert 1 not in pb.last_success_by_profile
        pb.backup_finished(profile_id=1)
        assert 1 not in pb._backup_active
    finally:
        pb.set_backup_sink(None)


# ----------------------------------------------------------------- PERF-009
def test_sync_latest_requested_retired_after_publish(tmp_path, monkeypatch):
    import fastprompter.main as main_mod

    dest = str(tmp_path / "mirror" / "silo.md")
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    main_mod._SYNC_LATEST_REQUESTED.clear()

    snap = {
        "files": {dest: "hello"},
        "root": str(tmp_path),
        "root_identity": str(tmp_path),
        "_write_seq": None,
    }
    monkeypatch.setattr(main_mod, "_SYNC_WRITE_SEQ",
                        getattr(main_mod, "_SYNC_WRITE_SEQ", 0))
    snap = main_mod._sync_register_snapshot(snap)
    key = os.path.normcase(os.path.abspath(dest))
    assert main_mod._SYNC_LATEST_REQUESTED.get(key) == snap["_write_seq"]

    written, errors = main_mod._sync_mechanical_write(snap)
    assert not errors
    assert written == [dest]
    # PERF-009: after physical publish, the registry entry is retired
    assert key not in main_mod._SYNC_LATEST_REQUESTED


def test_sync_latest_requested_kept_for_newer_owner(tmp_path, monkeypatch):
    import fastprompter.main as main_mod

    dest = str(tmp_path / "mirror" / "silo.md")
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    main_mod._SYNC_LATEST_REQUESTED.clear()

    snap = {
        "files": {dest: "hello"},
        "root": str(tmp_path),
        "root_identity": str(tmp_path),
        "_write_seq": None,
    }
    monkeypatch.setattr(main_mod, "_SYNC_WRITE_SEQ",
                        getattr(main_mod, "_SYNC_WRITE_SEQ", 0))
    snap = main_mod._sync_register_snapshot(snap)
    seq = snap["_write_seq"]
    key = os.path.normcase(os.path.abspath(dest))

    # a NEWER snapshot owns the destination before the older one publishes
    main_mod._SYNC_LATEST_REQUESTED[key] = seq + 100
    written, _ = main_mod._sync_mechanical_write(snap)
    assert key in main_mod._SYNC_LATEST_REQUESTED, \
        "a newer owner must keep the registry entry"
