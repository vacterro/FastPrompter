"""T-1436 (SRC-096 W2-005) — bundle metadata is a two-phase transaction.

Filesystem publication and the history/retention metadata commit are separate.
The destructive half (retention physically deletes older archives) must not run
before the new record is DURABLE; and when a commit does not commit, the fact is
recorded in a retry journal and reported -- never silently swallowed. The
published archive is never deleted because metadata lagged.
"""

from __future__ import annotations

import pytest

from fastprompter.core import silo_bundle as sb
from fastprompter.main import FastPrompter

SILO = "silo_meta"

class _Win:
    """Minimal owner of the metadata-transaction methods under test."""

    def __init__(self, record_path, save_results):
        record_path.parent.mkdir(parents=True, exist_ok=True)
        record_path.write_bytes(b"x")
        self.data = {
            "silo_bundle_history": {
                SILO: {"records": [{"path": str(record_path)}], "source_cache": {}}
            }
        }
        self._save_results = list(save_results)
        self.events: list[tuple] = []
        self.dirty: list[tuple] = []

    def mark_dirty(self, *args, **kwargs):
        self.dirty.append(args)

    def _silo_save_settings(self, report=False):
        ok = self._save_results.pop(0) if self._save_results else True
        self.events.append(("save", report, ok))
        return ok

    _silo_bundle_history = FastPrompter._silo_bundle_history
    _note_bundle_meta_failure = FastPrompter._note_bundle_meta_failure
    _clear_bundle_meta_failure = FastPrompter._clear_bundle_meta_failure
    _silo_bundle_record_success = FastPrompter._silo_bundle_record_success
    _silo_bundle_apply_retention = FastPrompter._silo_bundle_apply_retention


@pytest.fixture
def prune_spy(monkeypatch):
    calls: list[tuple] = []

    def fake(records, canonical_exports_dir=None, keep_versions=5,
             prune_custom=False, bundle_kind=None, protect=None):
        calls.append(tuple(records))
        return list(records), []

    monkeypatch.setattr(sb, "prune_silo_history", fake)
    return calls


def _record(win, target_dir):
    return win._silo_bundle_record_success(
        silo_id=SILO, zip_path=str(target_dir / "new.zip"), display_title="t",
        fingerprint="", target_dir=str(target_dir), options_sig={},
        archive_size=1, archive_mtime_ns=1, signatures={},
        silo_dir=str(target_dir), keep_versions=5,
    )


def test_w2_005_first_commit_precedes_retention_deletion(tmp_path, prune_spy):
    win = _Win(tmp_path / "old.zip", save_results=[True, True])
    assert _record(win, tmp_path) is True
    assert win.events[0][0] == "save"          # the new record is committed
    assert len(prune_spy) == 1                 # ... before retention runs
    assert win.events[-1] == ("save", True, True)
    assert prune_spy[0][0]["path"] == str(tmp_path / "new.zip")


def test_w2_005_failed_first_commit_skips_retention_entirely(tmp_path, prune_spy):
    win = _Win(tmp_path / "old.zip", save_results=[False])
    assert _record(win, tmp_path) is False
    assert prune_spy == []                     # nothing may be deleted yet
    row = win.data["silo_bundle_meta_retry"][SILO]
    assert row["stage"] == "new bundle record"
    assert win.data["silo_bundle_history"][SILO]["records"][0]["path"] == \
        str(tmp_path / "new.zip")
    assert win.dirty, "the retry state must be left dirty for the next save"


def test_w2_005_failed_second_commit_is_recorded_and_published_kept(
        tmp_path, prune_spy):
    win = _Win(tmp_path / "old.zip", save_results=[True, False])
    assert _record(win, tmp_path) is True      # the archive itself published
    assert len(prune_spy) == 1
    row = win.data["silo_bundle_meta_retry"][SILO]
    assert row["stage"] == "retention commit"
    assert "pending_records" in row


def test_w2_005_success_clears_any_retry_record(tmp_path, prune_spy):
    win = _Win(tmp_path / "old.zip", save_results=[True, True])
    win.data["silo_bundle_meta_retry"] = {SILO: {"stage": "stale"}}
    assert _record(win, tmp_path) is True
    assert SILO not in win.data["silo_bundle_meta_retry"]


def test_w2_005_retention_only_path_never_reports_uncommitted_deletions(
        tmp_path, prune_spy):
    failed = _Win(tmp_path / "old.zip", save_results=[False])
    assert failed._silo_bundle_apply_retention(SILO, str(tmp_path), 5) is False
    assert failed.data["silo_bundle_meta_retry"][SILO]["stage"] == \
        "retention-only commit"

    ok = _Win(tmp_path / "old.zip", save_results=[True])
    assert ok._silo_bundle_apply_retention(SILO, str(tmp_path), 5) is True
    assert SILO not in ok.data.get("silo_bundle_meta_retry", {})


def test_w2_005_no_history_is_a_no_op_not_a_failure(tmp_path, prune_spy):
    win = _Win(tmp_path / "old.zip", save_results=[True])
    win.data["silo_bundle_history"] = {}
    assert win._silo_bundle_apply_retention(SILO, str(tmp_path), 5) is None
    assert win.events == []


@pytest.fixture
def make_state(tmp_path, monkeypatch):
    import fastprompter.core.state as state_mod
    from fastprompter.core.state import FastPrompterState

    monkeypatch.setattr(state_mod, "get_db_path",
                        lambda profile_id=1: str(tmp_path / "f.db"))
    monkeypatch.setattr(
        "fastprompter.utils.portable_backup.run_portable_backup",
        lambda data, profile_id=1, **_kw: None)

    def _make():
        s = FastPrompterState(profile_id=1)
        s._last_backup_time_by_profile.clear()
        return s

    return _make


def test_w2_005_retry_record_is_registered_and_survives_restart(make_state, tmp_path):
    """The retry state is only useful if the restart it anticipates can read it.

    A key with no JSON codec entry is written with ``str()`` and reloads as one
    blob -- the reconciliation record would then be silently lost across the
    very restart it exists to survive (the shape CORE-003 fixed for coverage).
    """
    import json
    import sqlite3

    import fastprompter.core.state as state_mod

    assert "silo_bundle_meta_retry" in state_mod._JSON_SETTINGS
    assert state_mod._STRUCTURED_CODECS["silo_bundle_meta_retry"] == (dict, {}, True)

    payload = {SILO: {"stage": "retention commit",
                      "at": "2026-10-05T00:00:00",
                      "pruned": ["C:/rollout/old.zip"],
                      "pending_records": []}}
    s = make_state()
    s.data["silo_bundle_meta_retry"] = payload
    s.mark_dirty("settings")
    assert s.save_data_to_db("", force=True) is True

    conn = sqlite3.connect(tmp_path / "f.db")
    try:
        raw = dict(conn.execute("SELECT key, value FROM settings").fetchall())
    finally:
        conn.close()
    assert json.loads(raw["silo_bundle_meta_retry"]) == payload

    assert make_state().data["silo_bundle_meta_retry"] == payload
