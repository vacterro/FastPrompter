"""Regression tests for versioned, transactional schema migrations.

Proves the Phase-5/Phase-4 invariants:

* fresh databases reach CURRENT_SCHEMA_VERSION with the full schema
* unversioned legacy databases migrate in place (legacy tables folded in)
* already-migrated databases are left alone
* a failed migration rolls back (no table, no user_version bump) and RAISES —
  it is never silently read as a success
* a retried migration after the failure succeeds
* the pre-migration ``.bak`` stays a usable pre-migration snapshot
* a full save/reload round trip loses nothing
* a FUTURE schema version is refused before any transaction, untouched
* each migration records its OWN exact version edge
"""

import sqlite3

import pytest

import fastprompter.core.state as state_mod
from fastprompter.core.state import CURRENT_SCHEMA_VERSION, FastPrompterState

EXPECTED_TABLES = {"presets", "settings", "temp_presets_v2",
                   "archive_temp_presets_v2"}


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "migrate.db")


@pytest.fixture
def make_state(monkeypatch, db_path):
    monkeypatch.setattr(state_mod, "get_db_path", lambda profile_id=1: db_path)
    # save_data_to_db imports run_portable_backup function-locally; patch the
    # module attribute so a test save never writes real Documents snapshots.
    monkeypatch.setattr(
        "fastprompter.utils.portable_backup.run_portable_backup",
        lambda data, profile_id=1: None)

    def _make():
        return FastPrompterState(profile_id=1)

    return _make


def _tables(conn):
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    return {r[0] for r in rows}


def _user_version(conn):
    return conn.execute("PRAGMA user_version").fetchone()[0]


def _legacy_fixture(db_path, pad_size=0):
    """A pre-versioning (v0.8.x) database: old table set, no last_edited."""
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE presets (category TEXT, slot INTEGER, name TEXT, content TEXT, PRIMARY KEY (category, slot))")
    conn.execute("CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT)")
    conn.execute("CREATE TABLE temp_presets (slot INTEGER, content TEXT)")
    conn.execute("CREATE TABLE archive_temp_presets (slot INTEGER, content TEXT)")
    conn.execute("INSERT INTO temp_presets (slot, content) VALUES (0, 'legacy silo')")
    conn.execute("INSERT INTO archive_temp_presets (slot, content) VALUES (1, 'legacy archive')")
    conn.execute("INSERT INTO settings (key, value) VALUES ('cats_order', '[\"Code\",\"Text\",\"Misc\"]')")
    if pad_size:
        conn.execute("INSERT INTO temp_presets (slot, content) VALUES (5, ?)",
                     ("X" * pad_size,))
    conn.commit()
    conn.close()


class TestFreshDatabase:
    def test_fresh_db_reaches_current_version(self, make_state):
        s = make_state()
        try:
            assert _user_version(s.conn) == CURRENT_SCHEMA_VERSION
            assert EXPECTED_TABLES <= _tables(s.conn)
        finally:
            s.conn.close()

    def test_fresh_db_is_stable_across_reopen(self, make_state, db_path):
        s = make_state()
        s.conn.close()
        s2 = make_state()
        try:
            assert _user_version(s2.conn) == CURRENT_SCHEMA_VERSION
        finally:
            s2.conn.close()


class TestLegacyMigration:
    def test_legacy_tables_folded_into_v2(self, make_state, db_path):
        _legacy_fixture(db_path)
        s = make_state()
        try:
            cur = s.conn.cursor()
            rows = cur.execute(
                "SELECT category, slot, content FROM temp_presets_v2").fetchall()
            assert ("Code", 0, "legacy silo") in rows
            arc = cur.execute(
                "SELECT category, slot, content FROM archive_temp_presets_v2").fetchall()
            assert ("Code", 1, "legacy archive") in arc
            # legacy tables consumed
            assert "temp_presets" not in _tables(s.conn)
            assert "archive_temp_presets" not in _tables(s.conn)
            # snippet timestamp column added
            cols = [r[1] for r in cur.execute("PRAGMA table_info(presets)")]
            assert "last_edited" in cols
            assert _user_version(s.conn) == CURRENT_SCHEMA_VERSION
        finally:
            s.conn.close()

    def test_migrated_legacy_data_survives_reload(self, make_state, db_path):
        _legacy_fixture(db_path)
        s = make_state()
        s.conn.close()
        s2 = make_state()
        try:
            assert s2.data["temp_presets_all"]["Code"][0] == "legacy silo"
            assert "legacy archive" in s2.data["archive_temp_presets_all"]["Code"]
        finally:
            s2.conn.close()

    def test_pre_migration_backup_remains_usable(self, make_state, db_path):
        # >24576 bytes so init_db's startup backup actually runs
        _legacy_fixture(db_path, pad_size=40000)
        s = make_state()
        s.conn.close()
        bak = sqlite3.connect(db_path + ".bak")
        try:
            assert "temp_presets" in _tables(bak)  # a pre-migration snapshot
            assert bak.execute("SELECT COUNT(*) FROM temp_presets").fetchone()[0] >= 1
        finally:
            bak.close()


class TestAlreadyMigrated:
    def test_current_db_left_alone(self, make_state, db_path):
        s = make_state()
        s.conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('sentinel', 'kept')")
        s.conn.commit()
        s.conn.close()

        s2 = make_state()
        try:
            row = s2.conn.execute(
                "SELECT value FROM settings WHERE key='sentinel'").fetchone()
            assert row and row[0] == "kept"
            assert _user_version(s2.conn) == CURRENT_SCHEMA_VERSION
        finally:
            s2.conn.close()


class TestFailedMigration:
    def test_failed_migration_rolls_back_and_raises(self, make_state, db_path, monkeypatch):
        _legacy_fixture(db_path)

        def _bad(conn, first_category):
            cur = conn.cursor()
            cur.execute("CREATE TABLE marker_table (x TEXT)")
            cur.execute("PRAGMA user_version = 1")
            raise state_mod.MigrationError("boom")

        monkeypatch.setattr(state_mod, "_migrate_v0_to_v1", _bad)
        with pytest.raises(state_mod.MigrationError):
            make_state()

        # the failed migration was rolled back completely
        conn = sqlite3.connect(db_path)
        try:
            assert "marker_table" not in _tables(conn)
            assert _user_version(conn) == 0
            assert "temp_presets" in _tables(conn)  # legacy data untouched
        finally:
            conn.close()

    def test_retry_after_failure_succeeds(self, make_state, db_path, monkeypatch):
        _legacy_fixture(db_path)

        def _bad(conn, first_category):
            raise state_mod.MigrationError("boom")

        monkeypatch.setattr(state_mod, "_migrate_v0_to_v1", _bad)
        with pytest.raises(state_mod.MigrationError):
            make_state()

        monkeypatch.undo()
        s = make_state()          # the retry after the rollback
        try:
            assert _user_version(s.conn) == CURRENT_SCHEMA_VERSION
            assert "temp_presets" not in _tables(s.conn)
        finally:
            s.conn.close()


class TestMalformedLegacySettings:
    def test_bad_json_setting_falls_back_without_crash(self, make_state, db_path):
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT)")
        conn.execute("INSERT INTO settings (key, value) VALUES ('pinned_silos_all', '{not json')")
        conn.execute("INSERT INTO settings (key, value) VALUES ('cats_order', '[\"Code\"]')")
        conn.commit()
        conn.close()
        s = make_state()
        try:
            # the corrupted JSON key must not crash load or take the app down
            assert s.data["pinned_silos_all"] == {}
            assert s.data["cats_order"] == ["Code"]
        finally:
            s.conn.close()


class TestRoundTrip:
    def test_save_reload_round_trip_loses_nothing(self, make_state):
        s = make_state()
        s.data["temp_presets_all"]["Code"][0] = "round trip silo"
        s.data["categories"]["Code"][0] = {"name": "snip", "text": "snippet text"}
        s.mark_dirty()
        s.save_data_to_db("round trip silo", force=True)
        s.conn.close()

        s2 = make_state()
        try:
            assert s2.data["temp_presets_all"]["Code"][0] == "round trip silo"
            assert s2.data["categories"]["Code"][0]["text"] == "snippet text"
            assert s2.data["last_text"] == "round trip silo"
        finally:
            s2.conn.close()


class TestFutureSchemaRejected:
    """Phase-4: a database from a NEWER FastPrompter is refused, untouched."""

    def _future_db(self, db_path, version, marker="future data"):
        s = FastPrompterState(profile_id=1)
        s.conn.close()
        conn = sqlite3.connect(db_path)
        # the base schema exists (fresh from the state above); bump the version
        # as a newer build would have done
        conn.execute(f"PRAGMA user_version = {version}")
        conn.execute("INSERT INTO settings (key, value) VALUES ('marker', ?)",
                     (marker,))
        conn.commit()
        conn.close()
        return marker

    def test_current_plus_one_is_rejected(self, make_state, db_path):
        from fastprompter.core.state import (
            CURRENT_SCHEMA_VERSION,
            UnsupportedSchemaVersion,
        )
        self._future_db(db_path, CURRENT_SCHEMA_VERSION + 1)
        with pytest.raises(UnsupportedSchemaVersion):
            make_state()

    def test_version_999_is_rejected(self, make_state, db_path):
        from fastprompter.core.state import UnsupportedSchemaVersion
        self._future_db(db_path, 999)
        with pytest.raises(UnsupportedSchemaVersion):
            make_state()

    def test_rejected_db_is_left_unchanged(self, make_state, db_path):
        from fastprompter.core.state import (
            CURRENT_SCHEMA_VERSION,
            UnsupportedSchemaVersion,
        )
        self._future_db(db_path, CURRENT_SCHEMA_VERSION + 1, marker="future")
        before = open(db_path, "rb").read()
        with pytest.raises(UnsupportedSchemaVersion):
            make_state()
        assert open(db_path, "rb").read() == before
        conn = sqlite3.connect(db_path)
        try:
            assert conn.execute("PRAGMA user_version").fetchone()[0] \
                == CURRENT_SCHEMA_VERSION + 1
            assert conn.execute(
                "SELECT value FROM settings WHERE key='marker'").fetchone()[0] \
                == "future"
        finally:
            conn.close()

    def test_current_version_is_a_no_op(self, make_state, db_path):
        from fastprompter.core.state import CURRENT_SCHEMA_VERSION
        s = make_state()           # fresh -> current
        assert s.conn.execute("PRAGMA user_version").fetchone()[0] \
            == CURRENT_SCHEMA_VERSION
        s.conn.execute("INSERT OR REPLACE INTO settings (key, value) "
                       "VALUES ('marker', 'kept')")
        s.conn.commit()
        s.conn.close()
        s2 = make_state()          # reopen at current -> no migration
        try:
            assert s2.conn.execute(
                "SELECT value FROM settings WHERE key='marker'").fetchone()[0] \
                == "kept"
        finally:
            s2.conn.close()

    def test_v0_migration_records_exactly_version_1(self, make_state, db_path):
        """migrate_v0_to_v1 must record its OWN edge (1), not a copy of the
        current constant."""
        _legacy_fixture(db_path)
        s = make_state()
        try:
            assert s.conn.execute("PRAGMA user_version").fetchone()[0] == 1
        finally:
            s.conn.close()
