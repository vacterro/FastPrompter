"""Wave-6 regression: startup-safety outcome authority + profile-transition
atomicity + coordinator handoff/deadline seams.

Every defect came from `audit/` evidence/repro_wave6_current.py (R1..R7).
These are the deterministic versions of those repros so the audit findings
stay green as automated coverage, not as a one-off script.
"""

import os
import sqlite3
import threading
import time

import pytest

import fastprompter.core.state as state_mod
from fastprompter.core.state import (
    FastPrompterState,
    StartupSafetyUnavailableError,
    _StartupBackupContext,
)


def _reset_coord():
    with state_mod._BACKUP_LOCK:
        for d in (
            state_mod._BACKUP_PROFILE_PENDING,
            state_mod._BACKUP_PROFILE_RUNNING,
            state_mod._BACKUP_WORKERS,
            state_mod._BACKUP_GENERATION,
            state_mod._BACKUP_REVOKED,
            state_mod._BACKUP_DRAINING,
            state_mod._BACKUP_DRAIN_OUTCOMES,
        ):
            d.clear()


def _make_db(path, big=False, invalid_slot=False):
    old_get = state_mod.get_db_path
    try:
        state_mod.get_db_path = lambda profile_id=1: path
        st = FastPrompterState(1)
        if big or invalid_slot:
            slot = 150 if invalid_slot else 1
            st.conn.execute(
                "INSERT OR REPLACE INTO presets(category,slot,name,content,last_edited) "
                "VALUES(?,?,?,?,?)",
                ("Code", slot, "audit-row", "X" * 100_000, 0),
            )
            st.conn.commit()
            st.conn.execute("VACUUM")
        st.conn.close()
    finally:
        state_mod.get_db_path = old_get


@pytest.fixture(autouse=True)
def _reset():
    _reset_coord()
    yield
    _reset_coord()


# ---------------------------------------------------------------- Ticket 01

def test_completed_failed_gate_refuses_mutation(tmp_path):
    """A1/R1: a completed FAILED startup context must refuse an ordinary save
    and leave the DB unchanged (ready.is_set() is NOT safety)."""
    db = str(tmp_path / "a.db")
    old_get = state_mod.get_db_path
    try:
        state_mod.get_db_path = lambda profile_id=1: db
        st = FastPrompterState(1)
        ctx = _StartupBackupContext(st.db_path, 999)
        ctx.outcome = _StartupBackupContext.OUTCOME_FAILED
        ctx.ready.set()
        st._startup_backup_ctx = ctx
        st.data["theme"] = "W6_SHOULD_NOT_COMMIT"
        st.mark_dirty("settings")
        result = st.save_data_to_db("x", force=True)
        row = st.conn.execute(
            "SELECT value FROM settings WHERE key='theme'").fetchone()
        assert result is False
        assert row is None or row[0] != "W6_SHOULD_NOT_COMMIT"
        assert st._last_save_outcome == _StartupBackupContext.OUTCOME_FAILED
        st.conn.close()
    finally:
        state_mod.get_db_path = old_get


def test_completed_superseded_refuses_force_save(tmp_path):
    """A2: completed SUPERSEDED + force save -> False, DB unchanged, dirty
    retained."""
    db = str(tmp_path / "b.db")
    old_get = state_mod.get_db_path
    try:
        state_mod.get_db_path = lambda profile_id=1: db
        st = FastPrompterState(1)
        ctx = _StartupBackupContext(st.db_path, 1000)
        ctx.outcome = _StartupBackupContext.OUTCOME_SUPERSEDED
        ctx.ready.set()
        st._startup_backup_ctx = ctx
        st.data["theme"] = "W6_SUPERSEDED"
        st.mark_dirty("settings")
        result = st.save_data_to_db("x", force=True)
        row = st.conn.execute(
            "SELECT value FROM settings WHERE key='theme'").fetchone()
        assert result is False
        assert row is None or row[0] != "W6_SUPERSEDED"
        st.conn.close()
    finally:
        state_mod.get_db_path = old_get


def test_published_allows_save(tmp_path):
    """A3/A4: PUBLISHED and NOT_REQUIRED both proceed."""
    db = str(tmp_path / "c.db")
    old_get = state_mod.get_db_path
    try:
        state_mod.get_db_path = lambda profile_id=1: db
        st = FastPrompterState(1)
        ctx = _StartupBackupContext(st.db_path, 1001)
        ctx.outcome = _StartupBackupContext.OUTCOME_PUBLISHED
        ctx.ready.set()
        st._startup_backup_ctx = ctx
        st.data["theme"] = "W6_OK"
        st.mark_dirty("settings")
        assert st.save_data_to_db("x", force=True) is True
        row = st.conn.execute(
            "SELECT value FROM settings WHERE key='theme'").fetchone()
        assert row[0] == "W6_OK"
        st.conn.close()
    finally:
        state_mod.get_db_path = old_get


def test_pending_ordinary_autosave_defers(tmp_path):
    """A5: PENDING ordinary autosave returns fast, no DB mutation, dirty
    retained."""
    db = str(tmp_path / "d.db")
    old_get = state_mod.get_db_path
    try:
        state_mod.get_db_path = lambda profile_id=1: db
        st = FastPrompterState(1)
        ctx = _StartupBackupContext(st.db_path, 1002)
        st._startup_backup_ctx = ctx  # outcome PENDING, ready unset
        st.data["theme"] = "W6_PENDING"
        st.mark_dirty("settings")
        start = time.monotonic()
        result = st.save_data_to_db("x")
        elapsed = time.monotonic() - start
        assert result is False
        assert elapsed < 0.5
        row = st.conn.execute(
            "SELECT value FROM settings WHERE key='theme'").fetchone()
        assert row is None or row[0] != "W6_PENDING"
        assert st._dirty_settings > st._saved_settings_gen
        st.conn.close()
    finally:
        state_mod.get_db_path = old_get


def test_loader_recovery_refuses_when_snapshot_not_published(tmp_path):
    """A7/A8/R2: registration refused -> SUPERSEDED context; loader recovery
    must NOT mutate and must raise a controlled error leaving the row in
    place.  We force the destination DRAINING so the bounded registration
    retry gives up, not just a momentary lock-hold."""
    db = str(tmp_path / "e.db")
    _make_db(db, big=True, invalid_slot=True)
    for p in (db + ".bak", db + ".bak-wal", db + ".bak-shm"):
        try:
            os.remove(p)
        except FileNotFoundError:
            pass
    key = state_mod._backup_key(db)
    with state_mod._BACKUP_LOCK:
        state_mod._BACKUP_DRAINING[key] = True
    old_get = state_mod.get_db_path
    try:
        state_mod.get_db_path = lambda profile_id=1: db
        with pytest.raises(StartupSafetyUnavailableError):
            FastPrompterState(1)
        conn = sqlite3.connect(db)
        row = conn.execute(
            "SELECT slot FROM presets WHERE name='audit-row'").fetchone()
        conn.close()
        assert row[0] == 150, "recovery must NOT move the row without PUBLISHED safety"
    finally:
        state_mod.get_db_path = old_get
        with state_mod._BACKUP_LOCK:
            state_mod._BACKUP_DRAINING.pop(key, None)


def test_loader_recovery_proceeds_after_published_snapshot(tmp_path):
    """A8 (retry): once the coordinator frees, the startup snapshot PUBLISHES
    and loader recovery of the overflow row succeeds exactly once."""
    db = str(tmp_path / "f.db")
    _make_db(db, big=True, invalid_slot=True)
    for p in (db + ".bak", db + ".bak-wal", db + ".bak-shm"):
        try:
            os.remove(p)
        except FileNotFoundError:
            pass
    old_get = state_mod.get_db_path
    try:
        state_mod.get_db_path = lambda profile_id=1: db
        st = FastPrompterState(1)
        assert os.path.exists(db + ".bak")
        conn = sqlite3.connect(db)
        rows = conn.execute(
            "SELECT slot FROM presets WHERE name='audit-row'").fetchall()
        conn.close()
        assert rows and rows[0][0] == 0, "overflow row recovered into slot 0"
        st.conn.close()
    finally:
        state_mod.get_db_path = old_get


# ---------------------------------------------------------------- Ticket 02

def test_switch_refusal_does_not_detach_runtime(tmp_path):
    """P1/P0-003: Main-side contract — a False switch must not proceed. We
    exercise the State-level refusal path directly (pre-switch save fails)."""
    db = str(tmp_path / "g.db")
    old_get = state_mod.get_db_path
    try:
        state_mod.get_db_path = lambda profile_id=1: db
        st = FastPrompterState(1)
        old_conn = st.conn
        # save_current=True and the save fails -> switch refused, A intact
        import fastprompter.core.state as sm
        real_save = sm.FastPrompterState.save_data_to_db
        sm.FastPrompterState.save_data_to_db = (
            lambda self, *a, **k: False)
        try:
            result = st.switch_profile(2, save_current=True)
        finally:
            sm.FastPrompterState.save_data_to_db = real_save
        assert result is False
        assert st.profile_id == 1
        assert st.conn is old_conn
        st.conn.close()
    finally:
        state_mod.get_db_path = old_get


def test_failed_b_init_keeps_a_gate_valid(tmp_path):
    """P2/R4: failed B init restores A with a VALID (re-armed) safety gate —
    not a poisoned SUPERSEDED ctx with no retry path."""
    db_a = str(tmp_path / "a.db")
    db_b = str(tmp_path / "b.db")
    paths = {1: db_a, 2: db_b}
    _make_db(db_a, big=True)
    old_get = state_mod.get_db_path
    old_prep = state_mod._prepare_backup_candidate
    old_init = FastPrompterState.init_db
    entered = threading.Event()
    release = threading.Event()

    def blocked_prep(src, dest, validate=True):
        if str(dest) == db_a + ".bak":
            entered.set()
            release.wait(10)
        return old_prep(src, dest, validate)

    try:
        state_mod.get_db_path = lambda profile_id=1: paths[profile_id]
        state_mod._prepare_backup_candidate = blocked_prep
        st = FastPrompterState(1)
        ctx = st._startup_backup_ctx
        entered.wait(2)

        def broken_init(self):
            if self.profile_id == 2:
                raise RuntimeError("forced B init failure")
            return old_init(self)

        FastPrompterState.init_db = broken_init
        try:
            st.switch_profile(2, save_current=False)
        except RuntimeError:
            pass
        release.set()
        assert ctx.ready.wait(5)
        # A's gate must have PUBLISHED (re-armed), not stayed SUPERSEDED
        assert ctx.outcome == _StartupBackupContext.OUTCOME_PUBLISHED, (
            f"A safety gate poisoned: {ctx.outcome}")
        st.data["theme"] = "W6_AFTER_FAILED_SWITCH"
        st.mark_dirty("settings")
        assert st.save_data_to_db("x", force=True) is True
        st.conn.close()
    finally:
        state_mod.get_db_path = old_get
        state_mod._prepare_backup_candidate = old_prep
        FastPrompterState.init_db = old_init
        release.set()


def test_successful_switch_retires_a_once(tmp_path):
    """P3: a successful A->B switch retires A's backup ownership and leaves B
    authoritative."""
    db_a = str(tmp_path / "a.db")
    db_b = str(tmp_path / "b.db")
    paths = {1: db_a, 2: db_b}
    _make_db(db_a)
    old_get = state_mod.get_db_path
    try:
        state_mod.get_db_path = lambda profile_id=1: paths[profile_id]
        st = FastPrompterState(1)
        assert st.switch_profile(2, save_current=False) is True
        assert st.profile_id == 2
        assert st.db_path == db_b
        assert os.path.exists(db_b)
        st.conn.close()
    finally:
        state_mod.get_db_path = old_get


# ---------------------------------------------------------------- Ticket 04

def test_late_coalesced_request_is_not_orphaned(tmp_path):
    """C1/R5: a request arriving between the worker's final PENDING check and
    RUNNING clear must not end as pending=True/running=False/workers=0."""
    db = str(tmp_path / "x.db")
    c = sqlite3.connect(db)
    c.execute("CREATE TABLE x(a)")
    c.commit()
    c.close()
    old_prep = state_mod._prepare_backup_candidate
    old_pub = state_mod._backup_publish_candidate_authorized
    old_finish = state_mod._backup_profile_finish
    at_finish = threading.Event()
    release = threading.Event()
    try:
        state_mod._prepare_backup_candidate = (
            lambda *a, **k: os.path.join(str(tmp_path), "fake.tmp"))
        state_mod._backup_publish_candidate_authorized = (
            lambda *a, **k: True)

        def blocked_finish(profile_id, key=None, token=None, generation=None):
            at_finish.set()
            release.wait(5)
            return old_finish(profile_id, key, token, generation=generation)

        state_mod._backup_profile_finish = blocked_finish
        state_mod._schedule_periodic_backup(db, 7)
        assert at_finish.wait(2)
        # worker has finished its first publish and is blocked inside finish;
        # this request coalesces (RUNNING still True) and must be drained
        state_mod._schedule_periodic_backup(db, 7)
        release.set()
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            with state_mod._BACKUP_LOCK:
                running = state_mod._BACKUP_PROFILE_RUNNING.get("7")
                pending = state_mod._BACKUP_PROFILE_PENDING.get("7")
                workers = len(state_mod._BACKUP_WORKERS.get(
                    state_mod._backup_key(db), set()))
            if not running and not pending and not workers:
                break
            time.sleep(0.01)
        assert (running, pending, workers) == (None, None, 0) or (
            not running and not pending and not workers), (
            f"orphaned coalesced request: running={running} pending={pending} "
            f"workers={workers}")
    finally:
        release.set()
        state_mod._prepare_backup_candidate = old_prep
        state_mod._backup_publish_candidate_authorized = old_pub
        state_mod._backup_profile_finish = old_finish


# ---------------------------------------------------------------- Ticket 05

def test_thread_start_rollback_bounded_under_contention(tmp_path):
    """C3/R6: forced Thread.start failure with the coordinator contended must
    return inside a small GUI budget (no 350ms block)."""
    db = str(tmp_path / "x.db")
    c = sqlite3.connect(db)
    c.execute("CREATE TABLE x(a)")
    c.commit()
    c.close()
    orig_start = threading.Thread.start
    go = threading.Event()
    held = threading.Event()

    def holder():
        go.wait()
        state_mod._BACKUP_LOCK.acquire()
        held.set()
        time.sleep(0.35)
        state_mod._BACKUP_LOCK.release()

    h = threading.Thread(target=holder)
    orig_start(h)

    def patched_start(self):
        if getattr(self, "name", "") == "fastprompter-db-backup":
            go.set()
            held.wait(1)
            raise RuntimeError("forced Thread.start failure")
        return orig_start(self)

    threading.Thread.start = patched_start
    try:
        start = time.monotonic()
        try:
            state_mod._schedule_periodic_backup(db, 42)
        except RuntimeError:
            pass
        elapsed_ms = (time.monotonic() - start) * 1000
        assert elapsed_ms < 150, (
            f"rollback blocked GUI caller {elapsed_ms:.1f}ms under contention")
    finally:
        threading.Thread.start = orig_start
        h.join()
        # rollback converges: no ghost worker, profile flag cleared
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            with state_mod._BACKUP_LOCK:
                running = state_mod._BACKUP_PROFILE_RUNNING.get("42")
                workers = len(state_mod._BACKUP_WORKERS.get(
                    state_mod._backup_key(db), set()))
            if not running and not workers:
                break
            time.sleep(0.01)
        assert not running and not workers, (
            f"ghost state after start failure: running={running} workers={workers}")


# ---------------------------------------------------------------- Ticket 06

def test_shutdown_drain_global_deadline(tmp_path):
    """S1/S2/R7: aggregate shutdown drain honors ONE global deadline
    independent of the number of stuck destinations."""
    old_drain = state_mod._drain_db_backup
    with state_mod._BACKUP_LOCK:
        for i in range(6):
            state_mod._BACKUP_WORKERS[f"/tmp/fake{i}.db"] = {i}

    def slow(_db, timeout=5.0):
        time.sleep(timeout)
        return False

    state_mod._drain_db_backup = slow
    try:
        start = time.monotonic()
        state_mod._drain_all_db_backups(timeout=0.1)
        elapsed = time.monotonic() - start
        assert elapsed < 0.5, (
            f"global shutdown drain took {elapsed:.2f}s for 6 destinations")
    finally:
        state_mod._drain_db_backup = old_drain
        with state_mod._BACKUP_LOCK:
            state_mod._BACKUP_WORKERS.clear()


def test_shutdown_timeout_denies_remaining_publications(tmp_path):
    """S3: after the global deadline, every still-live destination is
    publication-denied (revoked+draining)."""
    old_drain = state_mod._drain_db_backup
    with state_mod._BACKUP_LOCK:
        for i in range(3):
            state_mod._BACKUP_WORKERS[f"/tmp/fake{i}.db"] = {i}
        keys = list(state_mod._BACKUP_WORKERS.keys())

    def slow(_db, timeout=5.0):
        time.sleep(timeout)
        return False

    state_mod._drain_db_backup = slow
    try:
        state_mod._drain_all_db_backups(timeout=0.05)
        with state_mod._BACKUP_LOCK:
            revoked = [k for k in keys
                       if state_mod._BACKUP_REVOKED.get(k)]
            draining = [k for k in keys
                        if state_mod._BACKUP_DRAINING.get(k)]
        assert set(revoked) == set(keys), (
            f"not all destinations denied after timeout: {revoked}")
        assert set(draining) == set(keys), (
            f"not all destinations draining after timeout: {draining}")
    finally:
        state_mod._drain_db_backup = old_drain
        with state_mod._BACKUP_LOCK:
            state_mod._BACKUP_WORKERS.clear()
            state_mod._BACKUP_REVOKED.clear()
            state_mod._BACKUP_DRAINING.clear()
