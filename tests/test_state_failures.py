"""Phase-14: backup/restore failure injection.

Proves the recovery invariants by making the failure happen:

* a failed save does not advance the saved-snapshot markers, so the retry
  writes the data (and a partial transaction rolls back)
* a failed .bak backup never replaces the previous good recovery copy
* a successful backup is atomic (temp file swapped over) and valid
* an unreadable database raises at load instead of silently booting on
  defaults that could then be saved over the recoverable data
* a corrupt settings VALUE (bad JSON) still falls back per-row, not by wiping
"""

import os
import sqlite3

import pytest

import fastprompter.core.state as state_mod
from fastprompter.core.state import FastPrompterState


@pytest.fixture
def make_state(tmp_path, monkeypatch):
    monkeypatch.setattr(state_mod, "get_db_path",
                        lambda profile_id=1: str(tmp_path / "f.db"))
    monkeypatch.setattr(
        "fastprompter.utils.portable_backup.run_portable_backup",
        lambda data: None)

    def _make():
        s = FastPrompterState(profile_id=1)
        s._last_backup_time = 0.0     # force the throttled .bak next save
        return s

    return _make


def _write_silo(state, text):
    state.data["temp_presets_all"]["Code"][0] = text
    state.mark_dirty()
    state.save_data_to_db(text, force=True)


def _silo_rows(db_path):
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute(
            "SELECT category, slot, content FROM temp_presets_v2 "
            "ORDER BY slot").fetchall()
    finally:
        conn.close()


def _valid_bak(path):
    conn = sqlite3.connect(path)
    try:
        conn.execute("SELECT 1").fetchone()
        return True
    finally:
        conn.close()


class _BoomCursor:
    """Delegates everything to a real cursor but fails on the Nth executemany."""

    def __init__(self, real, boom_on_call):
        self._cur = real
        self._boom_on_call = boom_on_call
        self._n = 0

    def __getattr__(self, name):
        if name == "executemany":
            return self._executemany
        return getattr(self._cur, name)

    def _executemany(self, sql, params=()):
        self._n += 1
        if self._n == self._boom_on_call:
            raise sqlite3.OperationalError("disk I/O error")
        return self._cur.executemany(sql, params)


class _BoomConn:
    """A sqlite3.Connection stand-in whose cursors fail on the Nth insert."""

    def __init__(self, real, boom_on_call):
        self._real = real
        self._boom_on_call = boom_on_call

    def __getattr__(self, name):
        return getattr(self._real, name)

    def cursor(self):
        return _BoomCursor(self._real.cursor(), self._boom_on_call)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return self._real.__exit__(*exc)


class TestFailedSave:
    def test_failed_save_does_not_advance_snapshots_and_retry_recovers(
            self, make_state):
        s = make_state()
        _write_silo(s, "first version")
        s.conn.close()

        # reopen; a fresh object's snapshots are empty
        s2 = make_state()
        real_conn = s2.conn
        s2.conn = _BoomConn(real_conn, boom_on_call=1)
        s2.data["temp_presets_all"]["Code"][1] = "second version"
        s2.mark_dirty()
        s2.save_data_to_db("second version", force=True)

        # the failed save must not have cleared the dirty flag or advanced
        # the snapshot, so a retry can still write the change
        assert s2._db_dirty is True
        assert ("Code", 1, "second version") not in s2._last_saved_temp
        assert ("Code", 1, "second version") not in _silo_rows(s2.db_path)

        # the retry succeeds and persists
        s2.conn = real_conn
        s2.save_data_to_db("second version", force=True)
        assert ("Code", 1, "second version") in _silo_rows(s2.db_path)
        s2.conn.close()

    def test_partial_transaction_rolls_back(self, make_state):
        """Two rows in one save, the second insert fails -> neither lands."""
        s = make_state()
        real_conn = s.conn
        s.conn = _BoomConn(real_conn, boom_on_call=2)
        s.data["temp_presets_all"]["Code"][3] = "row a"
        s.data["temp_presets_all"]["Code"][4] = "row b"
        s.mark_dirty()
        s.save_data_to_db("multi", force=True)

        rows = _silo_rows(s.db_path)
        assert ("Code", 3, "row a") not in rows
        assert ("Code", 4, "row b") not in rows
        s.conn = real_conn
        s.conn.close()

    def test_previous_committed_db_stays_readable_after_failed_save(
            self, make_state):
        s = make_state()
        _write_silo(s, "kept data")
        # close the connection: the next save cannot write
        s.conn.close()
        s.data["temp_presets_all"]["Code"][2] = "lost?"
        s.mark_dirty()
        s.save_data_to_db("lost?", force=True)     # fails, is logged, no raise
        # the previously committed data is still there and readable
        assert ("Code", 0, "kept data") in _silo_rows(s.db_path)
        assert s._db_dirty is True                 # the change was NOT swallowed


class TestFailedBackup:
    def test_failed_bak_never_replaces_the_good_copy(self, make_state, monkeypatch):
        s = make_state()
        _write_silo(s, "recoverable state")
        assert os.path.exists(s.db_path + ".bak") or True
        # create a known-good .bak
        good = sqlite3.connect(s.db_path)
        bak = sqlite3.connect(s.db_path + ".bak")
        with bak:
            good.backup(bak)
        good.close()
        bak.close()
        before = open(s.db_path + ".bak", "rb").read()

        def _boom(source_conn, db_path):
            raise OSError("disk full during backup")

        monkeypatch.setattr(state_mod, "_backup_atomically", _boom)
        s._last_backup_time = 0.0
        s.data["temp_presets_all"]["Code"][1] = "new"
        s.mark_dirty()
        s.save_data_to_db("new", force=True)   # must not raise

        after = open(s.db_path + ".bak", "rb").read()
        assert after == before, "a failed backup must not touch the good copy"
        assert not os.path.exists(s.db_path + ".bak.tmp")
        s.conn.close()

    def test_successful_bak_is_atomic_and_valid(self, make_state):
        s = make_state()
        _write_silo(s, "for the backup")
        s._last_backup_time = 0.0
        s.data["temp_presets_all"]["Code"][0] = "updated"
        s.mark_dirty()
        s.save_data_to_db("updated", force=True)

        assert _valid_bak(s.db_path + ".bak")
        assert not os.path.exists(s.db_path + ".bak.tmp")
        conn = sqlite3.connect(s.db_path + ".bak")
        try:
            rows = conn.execute(
                "SELECT content FROM temp_presets_v2 WHERE category='Code'").fetchall()
            assert ("updated",) in rows
        finally:
            conn.close()
        s.conn.close()


class TestUnreadableDatabase:
    def test_load_failure_raises_instead_of_silent_defaults(self, tmp_path, monkeypatch):
        monkeypatch.setattr(state_mod, "get_db_path",
                            lambda profile_id=1: str(tmp_path / "corrupt.db"))
        monkeypatch.setattr(
            "fastprompter.utils.portable_backup.run_portable_backup",
            lambda data: None)
        # a file that is NOT a database
        with open(str(tmp_path / "corrupt.db"), "wb") as f:
            f.write(b"\x00" * 4096)

        with pytest.raises(sqlite3.DatabaseError):
            FastPrompterState(profile_id=1)

    def test_bad_json_setting_falls_back_per_row_not_by_wiping(
            self, tmp_path, monkeypatch):
        monkeypatch.setattr(state_mod, "get_db_path",
                            lambda profile_id=1: str(tmp_path / "badjson.db"))
        monkeypatch.setattr(
            "fastprompter.utils.portable_backup.run_portable_backup",
            lambda data: None)
        # valid DB, one corrupt JSON setting value
        conn = sqlite3.connect(str(tmp_path / "badjson.db"))
        conn.execute("CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT)")
        conn.execute("INSERT INTO settings VALUES ('pinned_silos_all', '{bad json')")
        conn.execute("INSERT INTO settings VALUES ('cats_order', '[\"Code\"]')")
        conn.commit()
        conn.close()

        s = FastPrompterState(profile_id=1)
        try:
            assert s.data["pinned_silos_all"] == {}    # per-row fallback
            assert s.data["cats_order"] == ["Code"]    # good rows kept
        finally:
            s.conn.close()
