"""P0-6: the save_data_to_db boolean contract.

True means the database holds the latest state (committed now, or already
clean). False means the write FAILED and the change is still dirty — a quit
path that sees False must refuse to close and must not release ownership.
"""


import pytest

import fastprompter.core.state as state_mod
from fastprompter.core.state import FastPrompterState


@pytest.fixture
def make_state(tmp_path, monkeypatch):
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


def test_save_returns_true_on_clean_commit(make_state):
    s = make_state()
    s.data["temp_presets_all"]["Code"][0] = "hello"
    s.mark_dirty()
    assert s.save_data_to_db("hello", force=True) is True


def test_save_returns_true_when_nothing_changed(make_state):
    s = make_state()
    # first save lands the initial state
    assert s.save_data_to_db("", force=True) is True
    # nothing dirty, nothing changed -> clean, no write needed
    assert s.save_data_to_db("") is True


def test_save_returns_false_when_connection_missing(make_state):
    s = make_state()
    s.conn.close()
    s.conn = None
    assert s.save_data_to_db("x", force=True) is False


def test_save_returns_false_when_commit_fails(make_state):
    s = make_state()
    s.data["temp_presets_all"]["Code"][0] = "boom"
    s.mark_dirty()
    # force a write failure: settings encoding is stored via executemany on
    # the live connection; sabotage the transaction with an invalid table
    s.conn.execute("DROP TABLE settings")
    s.conn.commit()
    assert s.save_data_to_db("boom", force=True) is False
    # the change stays dirty and a later save can still succeed
    assert s._db_dirty is True
    s.conn.execute(
        "CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT)")
    s.conn.commit()
    assert s.save_data_to_db("boom", force=True) is True
    assert s._db_dirty is False


def test_failed_save_never_triggers_portable_backup(make_state, monkeypatch):
    calls = []
    monkeypatch.setattr(
        "fastprompter.utils.portable_backup.run_portable_backup",
        lambda data, profile_id=1, **_kw: calls.append(profile_id))
    s = make_state()
    s.conn.close()
    s.conn = None
    assert s.save_data_to_db("x", force=True) is False
    assert calls == []


def test_successful_save_triggers_portable_backup(make_state, monkeypatch):
    calls = []
    monkeypatch.setattr(
        "fastprompter.utils.portable_backup.run_portable_backup",
        lambda data, profile_id=1, **_kw: calls.append(profile_id))
    s = make_state()
    s.data["temp_presets_all"]["Code"][0] = "hello"
    s.mark_dirty()
    assert s.save_data_to_db("hello", force=True) is True
    assert calls == [1]
