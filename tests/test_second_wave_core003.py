def test_backup_begin_refused_while_draining(tmp_path):
    import threading
    from fastprompter.core.state import (
        _BACKUP_INFLIGHT,
        _BACKUP_LOCK,
        _BACKUP_DRAINING,
        _begin_backup_generation,
        _backup_key,
        _drain_db_backup,
    )
    db = str(tmp_path / "y.db")
    key = _backup_key(db)
    if _BACKUP_LOCK is None:
        _BACKUP_LOCK = threading.Lock()
    with _BACKUP_LOCK:
        _BACKUP_DRAINING[key] = True
    assert _begin_backup_generation(db) is None
    with _BACKUP_LOCK:
        _BACKUP_DRAINING.pop(key, None)
    assert _begin_backup_generation(db) is not None


def test_drain_blocks_new_and_clears_after_worker(tmp_path):
    import threading
    from fastprompter.core.state import (
        _BACKUP_INFLIGHT,
        _BACKUP_LOCK,
        _begin_backup_generation,
        _drain_db_backup,
    )
    db = str(tmp_path / "z.db")
    key, gen = _begin_backup_generation(db)
    if _BACKUP_LOCK is None:
        _BACKUP_LOCK = threading.Lock()
    with _BACKUP_LOCK:
        _BACKUP_INFLIGHT[key] = True
    released = threading.Event()

    def _finish():
        released.wait(timeout=5)
        with _BACKUP_LOCK:
            _BACKUP_INFLIGHT.pop(key, None)

    t = threading.Thread(target=_finish, daemon=True)
    t.start()
    # new requests refused while in-flight + draining flag set
    import fastprompter.core.state as st
    with _BACKUP_LOCK:
        st._BACKUP_DRAINING[key] = True
    assert _begin_backup_generation(db) is None
    with _BACKUP_LOCK:
        st._BACKUP_DRAINING.pop(key, None)
    # drain waits for the worker (it uses _BACKUP_INFLIGHT, not _BACKUP_DRAINING)
    assert _drain_db_backup(db, timeout=0.2) is False  # in flight
    released.set()
    t.join(timeout=5)
    assert _drain_db_backup(db, timeout=2.0) is True
