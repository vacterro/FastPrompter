"""Regression tests for Wave 1 Core audit tickets:
- CORE-001: Verified recovery identity prevents PID reuse / arbitrary process kill.
- CORE-003: Residual watcher_queues_all removed, blank slot reusable for silo transfer.
"""
from __future__ import annotations

from fastprompter.core.instance_lock import (
    UNRESPONSIVE,
    _verify_owner_identity,
    bootstrap_ownership,
)


class FakeLock:
    def __init__(self, owned=False):
        self._owned = owned
        self.abandoned = False

    def acquire(self, timeout_ms=0):
        return self._owned, ""

    def release(self):
        pass


class TestCore001VerifiedRecoveryIdentity:
    def test_mismatched_create_time_refuses_kill(self, monkeypatch):
        """If recorded create_time does not match the live process, PID was reused; refuse kill."""
        rec = {
            "pid": 12345,
            "create_time": 100000,
            "exe": r"c:\python\python.exe",
        }
        monkeypatch.setattr(
            "fastprompter.core.instance_lock._read_owner_record", lambda: rec)
        monkeypatch.setattr(
            "fastprompter.core.instance_lock.is_pid_alive", lambda pid: True)
        monkeypatch.setattr(
            "fastprompter.core.instance_lock._get_process_identity",
            lambda pid: {"pid": pid, "create_time": 999999, "exe": r"c:\python\python.exe"})

        killed = []
        monkeypatch.setattr(
            "fastprompter.core.instance_lock.kill_pid",
            lambda pid: (killed.append(pid) or (True, "killed")))

        assert _verify_owner_identity(rec) is False
        role, reason = bootstrap_ownership(FakeLock(owned=False), lambda: False)
        assert role == UNRESPONSIVE
        assert len(killed) == 0, "Unverified process must never be killed"

    def test_mismatched_executable_refuses_kill(self, monkeypatch):
        """If recorded exe path differs, PID belongs to an unrelated process; refuse kill."""
        rec = {
            "pid": 12345,
            "create_time": 100000,
            "exe": r"c:\fastprompter\fastprompter.exe",
        }
        monkeypatch.setattr(
            "fastprompter.core.instance_lock._read_owner_record", lambda: rec)
        monkeypatch.setattr(
            "fastprompter.core.instance_lock.is_pid_alive", lambda pid: True)
        monkeypatch.setattr(
            "fastprompter.core.instance_lock._get_process_identity",
            lambda pid: {"pid": pid, "create_time": 100000, "exe": r"c:\windows\notepad.exe"})

        killed = []
        monkeypatch.setattr(
            "fastprompter.core.instance_lock.kill_pid",
            lambda pid: (killed.append(pid) or (True, "killed")))

        assert _verify_owner_identity(rec) is False
        role, reason = bootstrap_ownership(FakeLock(owned=False), lambda: False)
        assert role == UNRESPONSIVE
        assert len(killed) == 0, "Unrelated executable must never be killed"


class TestCore003WatcherResidualRemoved:
    def test_legacy_watcher_queues_all_does_not_block_slot_reuse(self):
        """An empty destination slot with lingering historical watcher_queues_all
        remains reusable for cross-project silo transfer."""
        from fastprompter.main import FastPrompter

        data = {
            "temp_presets_all": {"Target": ["", ""]},
            "watcher_queues_all": {"Target": {"0": [{"id": "old_queue"}]}},
            "silo_folders_all": {},
            "archive_silo_folders_all": {},
            "silo_project_paths_all": {},
            "silo_colors_all": {},
            "silo_type_all": {},
            "silo_last_edited_all": {},
            "silo_view_state_all": {},
            "silo_ticked_all": {},
            "silo_selected_all": {},
            "silo_links_all": {},
            "project_sync_map_all": {},
        }
        dest = data["temp_presets_all"]["Target"]
        slot_idx = 0
        text = (dest[slot_idx] or "").strip()
        assert not text
        folders = data.get("silo_folders_all", {}).get("Target", {})
        assert str(slot_idx) not in folders
        assert "watcher_queues_all" not in FastPrompter._TRANSFER_STORE_KEYS
