"""Phase-2/3 (second pass): atomic validated database restore + shared backup.

Proves:
* a failed restore NEVER reduces a healthy live DB (byte-for-byte untouched)
* the source is validated (opens, integrity, schema version, tables) before
  any write
* future schema versions are refused
* same-file (incl. alternate path) is rejected
* the pre-restore safety snapshot of the live DB exists and is valid
* the candidate is built via the SQLite backup API and validated before the
  atomic replace
* a successful restore round-trips through FastPrompterState
"""

import os
import sqlite3

import pytest

import fastprompter.core.state as state_mod
from fastprompter.core.state import (
    CURRENT_SCHEMA_VERSION,
    FastPrompterState,
    FatalRestoreError,
    RestoreError,
    _same_file,
    restore_database,
    validate_database,
)


def _make_db(path, marker):
    """A real FastPrompter database containing `marker`."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    state_mod.get_db_path = lambda profile_id=1: path
    s = FastPrompterState(profile_id=1)
    s.data["temp_presets_all"]["Code"][0] = marker
    s.data["categories"]["Code"][0] = {"name": "snip", "text": marker}
    s.mark_dirty()
    s.save_data_to_db(marker, force=True, sync=True)
    s.conn.close()
    return s


def _bytes(path):
    with open(path, "rb") as f:
        return f.read()


class TestValidateDatabase:
    def test_garbage_file_is_rejected(self, tmp_path):
        p = str(tmp_path / "garbage.db")
        with open(p, "wb") as f:
            f.write(b"this is not a database" * 10)
        with pytest.raises(RestoreError):
            validate_database(p)

    def test_truncated_database_is_rejected(self, tmp_path):
        p = str(tmp_path / "real.db")
        _make_db(p, "marker")
        data = _bytes(p)
        trunc = str(tmp_path / "trunc.db")
        with open(trunc, "wb") as f:
            f.write(data[: len(data) // 3])
        with pytest.raises(RestoreError):
            validate_database(trunc)

    def test_future_schema_is_rejected(self, tmp_path):
        p = str(tmp_path / "future.db")
        _make_db(p, "marker")
        conn = sqlite3.connect(p)
        conn.execute(f"PRAGMA user_version = {CURRENT_SCHEMA_VERSION + 1}")
        conn.commit()
        conn.close()
        with pytest.raises(RestoreError) as ei:
            validate_database(p)
        assert "newer" in str(ei.value)

    def test_missing_tables_rejected(self, tmp_path):
        p = str(tmp_path / "empty.db")
        conn = sqlite3.connect(p)
        conn.execute("CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT)")
        conn.commit()
        conn.close()
        with pytest.raises(RestoreError):
            validate_database(p)

    def test_valid_database_returns_version(self, tmp_path):
        p = str(tmp_path / "ok.db")
        _make_db(p, "marker")
        version, tables = validate_database(p)
        assert version == CURRENT_SCHEMA_VERSION
        assert "temp_presets_v2" in tables

    def test_legacy_v0_database_is_accepted(self, tmp_path):
        p = str(tmp_path / "legacy.db")
        conn = sqlite3.connect(p)
        conn.execute("CREATE TABLE presets (category TEXT, slot INTEGER, name TEXT, content TEXT, PRIMARY KEY (category, slot))")
        conn.execute("CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT)")
        conn.execute("CREATE TABLE temp_presets (slot INTEGER, content TEXT)")
        conn.commit()
        conn.close()
        version, _ = validate_database(p)   # migration handles it on startup
        assert version == 0


class TestSchemaInvariants:
    """T-807: validation must reject malformed v0/v1 BEFORE they are published
    as a restore target (or migrate at startup), and a canonical v1 must
    enforce its PRIMARY KEY so repeated writes of one settings key collapse to
    exactly one row.
    """

    def test_legacy_v0_missing_silo_columns_rejected(self, tmp_path):
        p = str(tmp_path / "v0.db")
        conn = sqlite3.connect(p)
        conn.execute("CREATE TABLE presets (category TEXT, slot INTEGER, name TEXT, content TEXT, PRIMARY KEY (category, slot))")
        conn.execute("CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT)")
        conn.execute("CREATE TABLE temp_presets (content TEXT)")  # missing slot
        conn.commit()
        conn.close()
        with pytest.raises(RestoreError):
            validate_database(p)

    def test_legacy_v0_missing_archive_columns_rejected_if_present(self, tmp_path):
        p = str(tmp_path / "v0.db")
        conn = sqlite3.connect(p)
        conn.execute("CREATE TABLE presets (category TEXT, slot INTEGER, name TEXT, content TEXT, PRIMARY KEY (category, slot))")
        conn.execute("CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT)")
        conn.execute("CREATE TABLE temp_presets (slot INTEGER, content TEXT)")
        # present but missing the migration-read `content` column
        conn.execute("CREATE TABLE archive_temp_presets (slot INTEGER)")
        conn.commit()
        conn.close()
        with pytest.raises(RestoreError):
            validate_database(p)

    def test_v1_missing_settings_pk_rejected(self, tmp_path):
        p = str(tmp_path / "v1.db")
        conn = sqlite3.connect(p)
        conn.execute("CREATE TABLE presets (category TEXT, slot INTEGER, name TEXT, content TEXT, last_edited INTEGER, PRIMARY KEY (category, slot))")
        conn.execute("CREATE TABLE settings (key TEXT, value TEXT)")  # no PK
        conn.execute("CREATE TABLE temp_presets_v2 (category TEXT, slot INTEGER, content TEXT, PRIMARY KEY (category, slot))")
        conn.execute("CREATE TABLE archive_temp_presets_v2 (category TEXT, slot INTEGER, content TEXT, PRIMARY KEY (category, slot))")
        conn.execute("PRAGMA user_version = 1")
        conn.commit()
        conn.close()
        with pytest.raises(RestoreError) as ei:
            validate_database(p)
        assert "PRIMARY KEY" in str(ei.value)

    def test_v1_missing_presets_pk_rejected(self, tmp_path):
        p = str(tmp_path / "v1.db")
        conn = sqlite3.connect(p)
        conn.execute("CREATE TABLE presets (category TEXT, slot INTEGER, name TEXT, content TEXT, last_edited INTEGER)")  # no PK
        conn.execute("CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT)")
        conn.execute("CREATE TABLE temp_presets_v2 (category TEXT, slot INTEGER, content TEXT, PRIMARY KEY (category, slot))")
        conn.execute("CREATE TABLE archive_temp_presets_v2 (category TEXT, slot INTEGER, content TEXT, PRIMARY KEY (category, slot))")
        conn.execute("PRAGMA user_version = 1")
        conn.commit()
        conn.close()
        with pytest.raises(RestoreError):
            validate_database(p)

    def test_canonical_v1_accepted_after_strengthening(self, tmp_path):
        p = str(tmp_path / "ok.db")
        _make_db(p, "marker")
        version, _ = validate_database(p)
        assert version == CURRENT_SCHEMA_VERSION

    def test_repeated_settings_write_leaves_one_row(self, tmp_path):
        # A properly-keyed v1 settings table must collapse repeated writes of
        # the same logical key into exactly one row. The regression was a v1
        # whose settings table lacked the PK, so INSERT OR REPLACE duplicated
        # keys; validation now refuses such a file.
        p = str(tmp_path / "ok.db")
        _make_db(p, "marker")
        conn = sqlite3.connect(p)
        for _ in range(5):
            conn.execute(
                "INSERT OR REPLACE INTO settings (key, value) VALUES ('x', 'v')")
        conn.commit()
        n = conn.execute(
            "SELECT COUNT(*) FROM settings WHERE key='x'").fetchone()[0]
        conn.close()
        assert n == 1



class TestSameFile:
    def test_same_path_rejected(self, tmp_path):
        p = str(tmp_path / "db.db")
        _make_db(p, "a")
        with pytest.raises(RestoreError) as ei:
            restore_database(p, p)
        assert "same file" in str(ei.value)

    def test_alternate_path_rejected(self, tmp_path):
        p = str(tmp_path / "db.db")
        _make_db(p, "a")
        alt = os.path.join(str(tmp_path), "sub", "..", "db.db")
        assert _same_file(p, alt)
        with pytest.raises(RestoreError):
            restore_database(alt, p)


class TestRestoreDatabase:
    def test_failed_restore_leaves_live_db_untouched(self, tmp_path):
        live = str(tmp_path / "live.db")
        _make_db(live, "live data")
        before = _bytes(live)
        garbage = str(tmp_path / "garbage.db")
        with open(garbage, "wb") as f:
            f.write(b"not a database" * 20)

        with pytest.raises(RestoreError):
            restore_database(garbage, live)
        assert _bytes(live) == before, "live DB must be byte-for-byte intact"
        assert "live data" in _rows(live)

    def test_missing_source_rejected_without_touching_live(self, tmp_path):
        live = str(tmp_path / "live.db")
        _make_db(live, "live data")
        before = _bytes(live)
        with pytest.raises(RestoreError):
            restore_database(str(tmp_path / "absent.db"), live)
        assert _bytes(live) == before

    def test_future_schema_source_refused_and_live_untouched(self, tmp_path):
        live = str(tmp_path / "live.db")
        _make_db(live, "live data")
        before = _bytes(live)
        future = str(tmp_path / "future.db")
        _make_db(future, "future data")
        conn = sqlite3.connect(future)
        conn.execute(f"PRAGMA user_version = {CURRENT_SCHEMA_VERSION + 1}")
        conn.commit()
        conn.close()

        with pytest.raises(RestoreError):
            restore_database(future, live)
        assert _bytes(live) == before

    def test_successful_restore_replaces_and_round_trips(self, tmp_path):
        live = str(tmp_path / "live.db")
        _make_db(live, "old live data")
        backup = str(tmp_path / "backup.db")
        _make_db(backup, "restored data")

        restore_database(backup, live)

        # no temp/WAL leftovers immediately after the replace (the read-only
        # probes below can legitimately recreate WAL side files on open)
        assert not os.path.exists(live + ".restoretmp")
        assert not os.path.exists(live + "-wal")
        assert not os.path.exists(live + "-shm")
        assert validate_database(live)[0] == CURRENT_SCHEMA_VERSION
        assert _rows(live) == "restored data"
        # a pre-restore safety snapshot of the old live DB exists and is valid
        safety = live + ".prerestore.bak"
        assert os.path.isfile(safety)
        assert _rows(safety) == "old live data"

    def test_restored_db_loads_via_state(self, tmp_path, monkeypatch):
        live = str(tmp_path / "live.db")
        _make_db(live, "old")
        backup = str(tmp_path / "backup.db")
        _make_db(backup, "round trip")
        restore_database(backup, live)

        monkeypatch.setattr(state_mod, "get_db_path",
                            lambda profile_id=1: live)
        monkeypatch.setattr(
            "fastprompter.utils.portable_backup.run_portable_backup",
            lambda data, profile_id=1: None)
        s = FastPrompterState(profile_id=1)
        try:
            assert s.data["temp_presets_all"]["Code"][0] == "round trip"
        finally:
            s.conn.close()

    def test_backup_api_failure_does_not_touch_live(self, tmp_path, monkeypatch):
        class _BoomConn:
            """A real connection whose .backup raises (the C method is
            immutable, so the failure is injected at the seam)."""

            def __init__(self, real):
                self._real = real

            def __getattr__(self, name):
                if name == "backup":
                    def _boom(*a, **k):
                        raise sqlite3.OperationalError("disk full during backup")
                    return _boom
                return getattr(self._real, name)

            def close(self):
                return self._real.close()

        live = str(tmp_path / "live.db")
        _make_db(live, "live data")
        before = _bytes(live)
        backup = str(tmp_path / "backup.db")
        _make_db(backup, "other")

        real_open = state_mod._open_read_only

        def _seam(path):
            conn = real_open(path)
            if os.path.normcase(path) == os.path.normcase(backup):
                return _BoomConn(conn)
            return conn

        monkeypatch.setattr(state_mod, "_open_read_only", _seam)
        with pytest.raises(RestoreError):
            restore_database(backup, live)
        assert _bytes(live) == before


def _rows(path):
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        row = conn.execute(
            "SELECT content FROM temp_presets_v2 WHERE category='Code' AND slot=0").fetchone()
        return row[0] if row else None
    finally:
        conn.close()


class TestRestoreSidecarRollback:
    """T-808: the WAL/SHM quarantine + main swap must be transactional. An
    ordinary swap failure restores every sidecar exactly (the live DB is
    intact and the caller reopens it); a swap failure whose sidecar rollback
    ALSO fails enters the fatal recovery path (live repaired from the safety
    snapshot, never reopened in-process)."""

    def _injure_wal(self, live):
        with open(live + "-wal", "wb") as f:
            f.write(b"wal-frames")

    def test_ordinary_swap_failure_restores_all_sidecars(self, tmp_path,
                                                         monkeypatch):
        live = str(tmp_path / "live.db")
        _make_db(live, "live data")
        before = _bytes(live)
        backup = str(tmp_path / "backup.db")
        _make_db(backup, "other")
        self._injure_wal(live)
        real_replace = state_mod.os.replace

        def fake_replace(src, dst):
            # main swap (temp -> live) fails; everything else proceeds
            if dst == live and src.endswith(".restoretmp"):
                raise OSError("swap boom")
            return real_replace(src, dst)

        monkeypatch.setattr(state_mod.os, "replace", fake_replace)
        with pytest.raises(RestoreError):
            restore_database(backup, live)
        # live main untouched; WAL restored exactly; nothing stranded
        assert _bytes(live) == before
        assert os.path.isfile(live + "-wal")
        assert not os.path.exists(live + ".wal.quarantine")
        # the live DB is still a valid v1 with its original content
        assert validate_database(live)[0] == CURRENT_SCHEMA_VERSION
        assert _rows(live) == "live data"

    def test_fatal_swap_and_rollback_failure_recovers(self, tmp_path,
                                                      monkeypatch):
        live = str(tmp_path / "live.db")
        _make_db(live, "live data")
        backup = str(tmp_path / "backup.db")
        _make_db(backup, "other")
        self._injure_wal(live)
        real_replace = state_mod.os.replace

        def fake_replace(src, dst):
            # main swap fails ...
            if dst == live and src.endswith(".restoretmp"):
                raise OSError("swap boom")
            # ... AND the sidecar rollback (quarantine -> live) also fails
            if src.endswith(".wal.quarantine") or src.endswith(".shm.quarantine"):
                raise OSError("rollback boom")
            return real_replace(src, dst)

        monkeypatch.setattr(state_mod.os, "replace", fake_replace)
        with pytest.raises(FatalRestoreError):
            restore_database(backup, live)
        # No stranded quarantined sidecars; the on-disk live DB was repaired
        # from the safety snapshot, so it is a valid v1 carrying the ORIGINAL
        # data — and the process must never reopen it (the caller's contract).
        assert not os.path.exists(live + ".wal.quarantine")
        assert not os.path.exists(live + ".shm.quarantine")
        assert validate_database(live)[0] == CURRENT_SCHEMA_VERSION
        assert _rows(live) == "live data"
