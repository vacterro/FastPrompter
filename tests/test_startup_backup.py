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


# ----------------------------------------------------------- CORE-002: per-profile
def _make_large_current_db(tmp_path, name):
    """A current-schema DB that exceeds the snapshot-size threshold."""
    db = tmp_path / name
    _make_db(str(db), user_version=1)
    # pad so os.path.getsize reports > 24576 and the background path triggers
    with open(str(db) + ".pad", "wb") as f:
        f.write(b"\0" * 30000)
    return str(db)


def test_each_profile_gets_its_own_startup_backup_gate(
        tmp_path, monkeypatch):
    db_a = _make_large_current_db(tmp_path, "a.db")
    db_b = _make_large_current_db(tmp_path, "b.db")

    paths = {1: db_a, 2: db_b}
    monkeypatch.setattr(state_mod, "get_db_path",
                        lambda profile_id=1: paths[profile_id])

    real_getsize = os.path.getsize

    def gs(p):
        if str(p) in (db_a, db_b):
            return 1_000_000
        return real_getsize(p)

    monkeypatch.setattr(os.path, "getsize", gs)

    state = state_mod.FastPrompterState(profile_id=1)
    a_ctx = state._startup_backup_ctx
    assert a_ctx is not None, "profile A must get a startup-backup gate"
    # wait for A's snapshot to actually land
    deadline = time.monotonic() + 5
    while not os.path.exists(db_a + ".bak") and time.monotonic() < deadline:
        time.sleep(0.01)
    assert os.path.exists(db_a + ".bak")
    assert state._startup_backup_ready.is_set()

    # switch to B (also large/current) — must build a DISTINCT gate
    state.switch_profile(2, save_current=False)
    b_ctx = state._startup_backup_ctx
    assert b_ctx is not None
    assert b_ctx is not a_ctx, "profile B must not reuse A's gate"
    assert b_ctx.gen != a_ctx.gen

    # B's snapshot must complete before B's first mutating save can proceed.
    # Force the save to run inline (no background gap): the gate must already be
    # set by the time this returns.
    state.save_data_to_db("b text", force=True)
    assert os.path.exists(db_b + ".bak"), \
        "profile B must receive its own .bak before mutations proceed"


def test_stale_old_profile_worker_cannot_release_new_profile_gate(
        tmp_path, monkeypatch):
    db_a = _make_large_current_db(tmp_path, "a.db")
    db_b = _make_large_current_db(tmp_path, "b.db")
    paths = {1: db_a, 2: db_b}
    monkeypatch.setattr(state_mod, "get_db_path",
                        lambda profile_id=1: paths[profile_id])
    real_getsize = os.path.getsize

    def gs(p):
        if str(p) in (db_a, db_b):
            return 1_000_000
        return real_getsize(p)

    monkeypatch.setattr(os.path, "getsize", gs)

    # CORE-009: block B's own startup backup behind a deterministic barrier so
    # the test cannot race B's legitimate completion. A's worker is NOT blocked
    # (it runs to completion normally).
    b_entered = threading.Event()
    b_release = threading.Event()
    real_bak = state_mod._backup_atomically

    def blocked_b_backup(src, dest, validate=True):
        if str(dest) == db_b + ".bak":
            b_entered.set()
            b_release.wait(10)
        return real_bak(src, dest, validate)

    monkeypatch.setattr(state_mod, "_backup_atomically", blocked_b_backup)

    state = state_mod.FastPrompterState(profile_id=1)
    a_ctx = state._startup_backup_ctx
    deadline = time.monotonic() + 5
    while not a_ctx.ready.is_set() and time.monotonic() < deadline:
        time.sleep(0.01)

    # Simulate A's background worker finishing AFTER the profile transition:
    # it can only release its own captured context.
    state.switch_profile(2, save_current=False)
    b_ctx = state._startup_backup_ctx
    assert b_ctx is not a_ctx
    # B's worker is provably still blocked inside _backup_atomically.
    assert b_entered.wait(5), "B's startup backup never started"
    a_ctx.ready.set()           # stale A worker "finishes"
    assert not b_ctx.ready.is_set(), \
        "a stale old-profile worker must not release the new profile's gate"
    # Release B's barrier and wait for its physical worker to retire so the
    # fixture cannot disappear under a live daemon (CORE-009).
    b_release.set()
    deadline = time.monotonic() + 5
    while not b_ctx.ready.is_set() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert b_ctx.ready.is_set(), "B's own backup should complete after release"


def test_failed_profile_init_restores_old_backup_context(
        tmp_path, monkeypatch):
    db_a = _make_large_current_db(tmp_path, "a.db")
    db_b = _make_large_current_db(tmp_path, "b.db")
    paths = {1: db_a, 2: db_b}
    monkeypatch.setattr(state_mod, "get_db_path",
                        lambda profile_id=1: paths[profile_id])
    real_getsize = os.path.getsize

    def gs(p):
        if str(p) in (db_a, db_b):
            return 1_000_000
        return real_getsize(p)

    monkeypatch.setattr(os.path, "getsize", gs)

    state = state_mod.FastPrompterState(profile_id=1)
    a_ctx = state._startup_backup_ctx
    deadline = time.monotonic() + 5
    while not a_ctx.ready.is_set() and time.monotonic() < deadline:
        time.sleep(0.01)

    # Make B's initialization fail AFTER the gate reset.
    real_init = state_mod.FastPrompterState.init_db

    def broken_init(self):
        if self.profile_id == 2:
            raise RuntimeError("simulated B load failure")
        return real_init(self)

    monkeypatch.setattr(state_mod.FastPrompterState, "init_db", broken_init)

    import pytest
    with pytest.raises(RuntimeError):
        state.switch_profile(2, save_current=False)

    # A's context and generation are restored; A is still usable.
    assert state._startup_backup_ctx is a_ctx, \
        "failed B init must restore A's backup context"
    assert state.profile_id == 1
    assert state.save_data_to_db("a text", force=True) is True
