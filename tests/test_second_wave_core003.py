"""CORE-003 coordinator regression (rewritten for the T01 physical-worker
registry): the coordinator separates profile request state from the physical
destination worker registry; a drain refuses new publishers, waits on the
physical worker set, and reports a real bounded deadline."""

import os
import threading
import time

from fastprompter.core.state import (
    _BACKUP_DRAINING,
    _BACKUP_LOCK,
    _backup_key,
    _backup_register_worker,
    _backup_retire_worker,
    _drain_db_backup,
    _schedule_periodic_backup,
)


def test_backup_begin_refused_while_draining(tmp_path):
    from fastprompter.core.state import _backup_request_backup
    db = str(tmp_path / "y.db")
    key = _backup_key(db)
    with _BACKUP_LOCK:
        _BACKUP_DRAINING[key] = True
    assert _backup_register_worker(db)[0] is None
    assert _backup_request_backup(db, 1) is None
    with _BACKUP_LOCK:
        _BACKUP_DRAINING.pop(key, None)
    assert _backup_register_worker(db)[0] is not None


def test_drain_blocks_new_and_clears_after_worker(tmp_path):
    from fastprompter.core.state import _backup_register_worker
    db = str(tmp_path / "z.db")
    key, gen, token = _backup_register_worker(db)
    released = threading.Event()

    def _finish():
        released.wait(timeout=5)
        _backup_retire_worker(key, token)

    t = threading.Thread(target=_finish, daemon=True)
    t.start()
    # new requests refused while in-flight + draining flag set
    import fastprompter.core.state as st
    with _BACKUP_LOCK:
        st._BACKUP_DRAINING[key] = True
    assert st._backup_register_worker(db)[0] is None
    with _BACKUP_LOCK:
        st._BACKUP_DRAINING.pop(key, None)
    # drain waits for the PHYSICAL worker token (registry, not profile state)
    assert _drain_db_backup(db, timeout=0.2) is False  # in flight
    released.set()
    t.join(timeout=5)
    assert _drain_db_backup(db, timeout=2.0) is True


def test_two_workers_same_destination_drain_waits_both(tmp_path):
    """T01: the destination worker registry is a set; a drain stays False
    until EVERY physical worker token retires."""
    from fastprompter.core.state import _backup_register_worker
    db = str(tmp_path / "two.db")
    k1, g1, t1 = _backup_register_worker(db)
    k2, g2, t2 = _backup_register_worker(db)
    assert t1 != t2
    released = threading.Event()

    def _finish2():
        released.wait(timeout=5)
        _backup_retire_worker(k2, t2)

    th = threading.Thread(target=_finish2, daemon=True)
    th.start()
    assert _drain_db_backup(db, timeout=0.2) is False  # t1 + t2 still present
    _backup_retire_worker(k1, t1)
    assert _drain_db_backup(db, timeout=0.2) is False  # t2 still present
    released.set()
    th.join(timeout=5)
    assert _drain_db_backup(db, timeout=2.0) is True


def test_periodic_worker_publishes_bak(tmp_path):
    """T01 worker-body regression: the periodic backup worker must survive the
    prepare/publish path and land a real .bak next to the source DB (the
    publish helper name must resolve — a stale name would NameError the
    worker and silently starve every .bak refresh)."""
    import sqlite3

    from fastprompter.core.state import _drain_db_backup

    db = str(tmp_path / "live.db")
    conn = sqlite3.connect(db)
    conn.execute("PRAGMA user_version=1")
    conn.execute("CREATE TABLE settings(key TEXT PRIMARY KEY, value TEXT)")
    conn.execute("CREATE TABLE presets(category TEXT, slot INTEGER, "
                 "name TEXT, content TEXT, last_edited INTEGER, "
                 "PRIMARY KEY (category, slot))")
    conn.execute("CREATE TABLE temp_presets_v2(category TEXT, slot INTEGER, "
                 "content TEXT, PRIMARY KEY (category, slot))")
    conn.execute("CREATE TABLE archive_temp_presets_v2(category TEXT, "
                 "slot INTEGER, content TEXT, PRIMARY KEY (category, slot))")
    conn.commit()
    conn.close()

    _schedule_periodic_backup(db, 1)
    deadline = time.monotonic() + 5
    while not os.path.exists(db + ".bak") and time.monotonic() < deadline:
        time.sleep(0.01)
    assert os.path.exists(db + ".bak"), "periodic worker must publish the .bak"
    assert _drain_db_backup(db, timeout=5.0) is True, \
        "worker must retire cleanly after publishing"
