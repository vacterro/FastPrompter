import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from fastprompter import main as m


class _Lock:
    def __init__(self):
        self.released = False

    def release(self):
        self.released = True


class _Controller:
    def __init__(self, clean=True):
        self._clean = clean

    def shutdown(self):
        return self._clean


class _Sound:
    def stop_all_sound(self):
        return None

    def shutdown(self):
        return True


class _LimitService:
    def shutdown(self):
        return True


class _Ipc:
    def close(self):
        return None


class _Conn:
    def close(self):
        return None


class _State:
    def __init__(self, conn):
        self.conn = conn


class _Window:
    _close_workers_clean = True
    _in_physical_teardown = False

    def __init__(self):
        self.problip_controller = _Controller()
        self.voice_controller = _Controller()
        self.ambience_controller = _Controller()
        self.sound_manager = _Sound()
        self.limit_service = _LimitService()
        self.ipc = _Ipc()
        self.conn = _Conn()
        self.state = _State(self.conn)
        self._watcher_shutdown = lambda: True
        self._watcher_arm_shutdown = lambda: True
        self._typo_worker_shutdown = lambda: True
        self._sync_shutdown = lambda: True
        self._push_shutdown = lambda: True
        self._wait_for_undo_saves = lambda: True
        self._undo_save_failed = False

    def close(self):
        return None

    def deleteLater(self):
        return None


class _App:
    def processEvents(self):
        return None


def _make_window(monkeypatch, *, db_backup_drain=True):
    """A window whose EVERY external shutdown owner answers deterministically.

    T-1260: this module tests SHUTDOWN OWNERSHIP -- "who reported unclean, and
    did the lock survive it" -- so every owner the contract names must be
    controlled here. One was not: ``_shutdown_application`` imports and calls
    the REAL ``fastprompter.core.state._drain_all_db_backups()``, which reads
    the process-global ``_BACKUP_WORKERS`` registry. Any earlier test in the
    session that left a physical backup worker registered made this unit drain
    a foreign destination, time out, and report unclean -- so
    ``test_successful_global_pool_drain_preserves_clean_shutdown`` passed
    standalone and failed in a full run. The real drain semantics are an
    INTEGRATION concern and stay covered by the core-state tests; they are not
    this module's contract.
    """
    window = _Window()
    monkeypatch.setattr(m, "sync_shutdown_global", lambda: True)
    monkeypatch.setattr(m, "backup_worker_shutdown_global", lambda: True)
    monkeypatch.setattr(
        "fastprompter.core.state._drain_all_db_backups",
        lambda *a, **k: db_backup_drain,
    )
    monkeypatch.setattr(
        "fastprompter.ui.file_container.container_worker_shutdown_global",
        lambda: True,
    )
    monkeypatch.setattr(
        "fastprompter.ui.file_container.export_worker_shutdown_global",
        lambda: True,
    )
    return window


def test_failed_global_pool_drain_makes_shutdown_unclean(monkeypatch):
    """A: drain False -> returns False, lock never released, later teardown still runs."""
    lock = _Lock()
    window = _make_window(monkeypatch)
    monkeypatch.setattr(m, "drain_qt_threadpool", lambda: False)
    close_calls = []
    window.close = lambda: close_calls.append("close")

    result = m._shutdown_application(window, _App(), lock)

    assert result is False
    assert lock.released is False
    assert close_calls == ["close"]


def test_successful_global_pool_drain_preserves_clean_shutdown(monkeypatch):
    """B: drain True, all others clean -> returns True, lock released exactly once."""
    lock = _Lock()
    window = _make_window(monkeypatch)
    monkeypatch.setattr(m, "drain_qt_threadpool", lambda: True)

    result = m._shutdown_application(window, _App(), lock)

    assert result is True
    assert lock.released is True


def test_another_unclean_owner_retains_lock(monkeypatch):
    """C: drain True but watcher unclean -> lock still retained."""
    lock = _Lock()
    window = _make_window(monkeypatch)
    monkeypatch.setattr(m, "drain_qt_threadpool", lambda: True)
    window._watcher_shutdown = lambda: False

    result = m._shutdown_application(window, _App(), lock)

    assert result is False
    assert lock.released is False


def test_failed_drain_does_not_call_wait_for_done_again(monkeypatch):
    """D: bounded contract - drain is called once, not replaced by unbounded wait."""
    calls = []

    def fake_drain():
        calls.append("drain")
        return False

    lock = _Lock()
    window = _make_window(monkeypatch)
    monkeypatch.setattr(m, "drain_qt_threadpool", fake_drain)

    m._shutdown_application(window, _App(), lock)

    assert calls == ["drain"]

def test_core_backup_drain_failure_keeps_shutdown_unclean(monkeypatch):
    """E: the DB-backup drain is a real owner -- False must retain the lock.

    The isolation added for T-1260 controls this owner's answer; it must not
    make the owner disappear. Setting it False here proves the production
    wiring from ``_drain_all_db_backups`` into the clean/unclean verdict is
    still live.
    """
    lock = _Lock()
    window = _make_window(monkeypatch, db_backup_drain=False)
    monkeypatch.setattr(m, "drain_qt_threadpool", lambda: True)

    result = m._shutdown_application(window, _App(), lock)

    assert result is False
    assert lock.released is False


def test_foreign_backup_workers_cannot_make_this_unit_unclean(monkeypatch):
    """T-1260 regression: another test's residual worker must not leak in.

    A physical worker token left in ``fastprompter.core.state._BACKUP_WORKERS``
    by an unrelated test used to be drained BY THIS UNIT -- a foreign
    destination that nobody was ever going to retire, so the bounded drain
    expired and the "all clean" scenario reported unclean. With the owner
    isolated, the residue is inert here (and still the core-state tests'
    problem, where it belongs).
    """
    import fastprompter.core.state as state_mod

    key = state_mod._backup_key("Z:/nobody/leaked-from-another-test.db")
    state_mod._BACKUP_WORKERS.setdefault(key, set()).add("t1260-residue")
    try:
        lock = _Lock()
        window = _make_window(monkeypatch)
        monkeypatch.setattr(m, "drain_qt_threadpool", lambda: True)

        result = m._shutdown_application(window, _App(), lock)

        assert result is True
        assert lock.released is True
    finally:
        workers = state_mod._BACKUP_WORKERS.get(key)
        if workers is not None:
            workers.discard("t1260-residue")
            if not workers:
                state_mod._BACKUP_WORKERS.pop(key, None)


def test_ambience_controller_that_cannot_retire_its_worker_is_unclean(monkeypatch):
    """CORE-002: the ambience weather worker is an OWNED resource.

    ``AmbienceController.shutdown()`` returns False when its bounded join could
    not retire the weather worker; that worker can still emit weatherChanged
    against a controller that is already logically closed. A discarded return
    value used to make this the one owner whose failure vanished, so this
    proves the verdict wiring, not the join itself (see
    ``test_ambience_weather_ownership`` for the real thread behaviour).
    """
    lock = _Lock()
    window = _make_window(monkeypatch)
    monkeypatch.setattr(m, "drain_qt_threadpool", lambda: True)
    window.ambience_controller = _Controller(False)

    result = m._shutdown_application(window, _App(), lock)

    assert result is False
    assert lock.released is False


def test_a_clean_ambience_shutdown_keeps_the_verdict_clean(monkeypatch):
    """The other half: a clean retirement must not be mistaken for failure."""
    lock = _Lock()
    window = _make_window(monkeypatch)
    monkeypatch.setattr(m, "drain_qt_threadpool", lambda: True)
    window.ambience_controller = _Controller(True)

    result = m._shutdown_application(window, _App(), lock)

    assert result is True
    assert lock.released is True


def test_the_unit_leaves_no_backup_registry_residue_of_its_own():
    """Leak sentinel: this module must not be somebody else's polluter."""
    import fastprompter.core.state as state_mod

    live = {k: set(v) for k, v in state_mod._BACKUP_WORKERS.items() if v}
    assert "t1260-residue" not in {t for tokens in live.values()
                                   for t in tokens}
