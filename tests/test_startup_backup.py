"""T-818 regression: current-schema startup must not block the UI thread on a
full validated backup, yet the safety snapshot must still complete before the
first mutation; an OLD schema must still take exactly one synchronous
validated backup before its schema write.
"""

import os
import sqlite3
import threading
import time

import fastprompter.core.state as state_mod


def _make_db(path, user_version=1, rows=None):
    conn = sqlite3.connect(path)
    conn.execute(f"PRAGMA user_version={user_version}")
    conn.execute("CREATE TABLE settings(key TEXT PRIMARY KEY, value TEXT)")
    conn.execute("CREATE TABLE presets(category TEXT, slot INTEGER, "
                 "name TEXT, content TEXT, last_edited INTEGER, "
                 "PRIMARY KEY (category, slot))")
    conn.execute("CREATE TABLE temp_presets_v2(category TEXT, slot INTEGER, "
                 "content TEXT, PRIMARY KEY (category, slot))")
    conn.execute("CREATE TABLE archive_temp_presets_v2(category TEXT, "
                 "slot INTEGER, content TEXT, PRIMARY KEY (category, slot))")
    for k, v in (rows or {}).items():
        conn.execute("INSERT INTO settings VALUES(?,?)", (k, str(v)))
    conn.commit()
    conn.close()


def _big(monkeypatch, db_path):
    """Make the existing DB look >24576 bytes so the backup path triggers."""
    real = os.path.getsize

    def gs(p):
        return 1_000_000 if str(p) == str(db_path) else real(p)

    monkeypatch.setattr(state_mod.os.path, "getsize", gs)


def test_current_schema_starts_without_synchronous_backup(tmp_path, monkeypatch):
    db = tmp_path / "cur.db"
    _make_db(str(db), user_version=1)
    monkeypatch.setattr(state_mod, "get_db_path",
                        lambda profile_id=1: str(db))
    _big(monkeypatch, db)

    entered = threading.Event()
    release = threading.Event()
    ran_in = []
    real_bak = state_mod._backup_atomically

    def blocked_backup(src, dest, validate=True):
        ran_in.append(threading.current_thread().name)
        entered.set()
        release.wait(10)
        return real_bak(src, dest, validate)

    monkeypatch.setattr(state_mod, "_backup_atomically", blocked_backup)

    # Construction returns promptly => the validated backup was NOT done
    # synchronously on the startup thread. If a synchronous call had happened
    # it would run in THIS thread; a background job runs in its own thread, so
    # either nothing has run yet or it ran in "fp-startup-backup".
    state = state_mod.FastPrompterState(profile_id=1)
    assert (not ran_in
            or ran_in[0] != threading.current_thread().name), \
        "startup performed the full backup synchronously"
    assert state._startup_backup_ready is not None, \
        "current-schema startup must launch a background safety snapshot"

    release.set()
    deadline = time.monotonic() + 5
    while not os.path.exists(str(db) + ".bak") and time.monotonic() < deadline:
        time.sleep(0.01)
    assert os.path.exists(str(db) + ".bak"), \
        "background snapshot must still produce the .bak"
    assert state._startup_backup_ready.is_set()


def test_first_mutation_is_gated_on_background_snapshot(
        tmp_path, monkeypatch):
    db = tmp_path / "cur.db"
    _make_db(str(db), user_version=1)
    monkeypatch.setattr(state_mod, "get_db_path",
                        lambda profile_id=1: str(db))
    _big(monkeypatch, db)

    release = threading.Event()
    real_bak = state_mod._backup_atomically

    def blocked_backup(src, dest, validate=True):
        release.wait(10)
        return real_bak(src, dest, validate)

    monkeypatch.setattr(state_mod, "_backup_atomically", blocked_backup)

    state = state_mod.FastPrompterState(profile_id=1)
    done = threading.Event()

    def do_save():
        state.save_data_to_db("text", force=True)
        done.set()

    t = threading.Thread(target=do_save, daemon=True)
    t.start()
    time.sleep(0.3)
    assert not done.is_set(), \
        "the first save must block until the background snapshot completes"

    release.set()
    assert done.wait(5), "save must proceed once the snapshot is ready"


def test_migration_takes_one_synchronous_backup_before_schema_write(
        tmp_path, monkeypatch):
    db = tmp_path / "old.db"
    _make_db(str(db), user_version=0, rows={"tray_visible": "True"})
    monkeypatch.setattr(state_mod, "get_db_path",
                        lambda profile_id=1: str(db))
    _big(monkeypatch, db)

    order = []

    def recording_backup(src, dest, validate=True):
        order.append("backup")

    monkeypatch.setattr(state_mod, "_backup_atomically", recording_backup)
    real_mig = state_mod._migrate_schema

    def guarded_migrate(conn, first):
        assert order == ["backup"], \
            "the validated backup must run before the schema write"
        order.append("migrate")
        return real_mig(conn, first)

    monkeypatch.setattr(state_mod, "_migrate_schema", guarded_migrate)

    state_mod.FastPrompterState(profile_id=1)
    assert order == ["backup", "migrate"], \
        "exactly one validated backup before the migration"
