"""Tests for the single-instance writer-ownership model.

Two layers:

* ``bootstrap_ownership`` decision table - driven with fake locks so the
  split-brain logic is deterministic without an OS mutex.
* the real Windows named-mutex primitive - acquire/release in-process and a
  genuine cross-process contention test using a subprocess that holds the
  lock (a frozen first instance is simulated by a process that simply owns
  the mutex and answers nothing).
"""

import subprocess
import sys
import textwrap
import uuid

import pytest

from fastprompter.core.instance_lock import (
    HANDED_OFF,
    PRIMARY,
    RECLAIMED,
    UNRESPONSIVE,
    WAIT_OBJECT_0,
    InstanceLock,
    _read_owner_pid,
    _write_owner_pid,
    bootstrap_ownership,
)


class FakeLock:
    """A lock whose acquire() answer the test controls."""

    def __init__(self, owned=False, reason="", raise_on_acquire=False):
        self.owned = owned
        self.reason = reason
        self.raise_on_acquire = raise_on_acquire
        self.released = False

    def acquire(self, timeout_ms=0):
        if self.raise_on_acquire:
            raise RuntimeError("boom")
        return self.owned, self.reason

    def release(self):
        self.released = True


class TestBootstrapOwnership:
    """The decision table: who may write, and who must stand down."""

    def test_first_instance_acquires_and_becomes_primary(self):
        role, reason = bootstrap_ownership(FakeLock(owned=True), lambda: False)
        assert role == PRIMARY

    def test_second_instance_handed_off_when_owner_acks(self):
        role, _ = bootstrap_ownership(FakeLock(owned=False), lambda: True)
        assert role == HANDED_OFF

    def test_second_instance_refused_when_owner_silent(self, monkeypatch):
        """A silent owner is unresponsive, not a kill target. Isolated from
        any real ``owner.pid`` left in the data dir by a prior app run."""
        monkeypatch.setattr(
            "fastprompter.core.instance_lock._owner_is_stale", lambda: False)
        role, reason = bootstrap_ownership(
            FakeLock(owned=False, reason="another FastPrompter instance owns the database"),
            lambda: False)
        assert role == UNRESPONSIVE
        assert "another FastPrompter" in reason

    def test_second_instance_refused_when_handover_raises(self):
        def boom():
            raise OSError("socket gone")

        role, reason = bootstrap_ownership(FakeLock(owned=False), boom)
        assert role == UNRESPONSIVE
        assert "socket gone" in reason

    def test_ownership_check_failure_is_failed_not_primary(self):
        role, reason = bootstrap_ownership(
            FakeLock(owned=False, raise_on_acquire=True), lambda: False)
        assert role != PRIMARY
        assert "boom" in reason

    def test_acquire_error_never_falls_through_to_writer(self):
        """An ownership-check exception must not let us proceed as primary."""
        role, _ = bootstrap_ownership(
            FakeLock(owned=False, raise_on_acquire=True), lambda: True)
        assert role != PRIMARY

    def test_frozen_owner_live_pid_is_reclaimed(self, monkeypatch):
        """A live owner whose event loop is hung (no IPC ACK within grace)
        is identified by the recorded owner PID, terminated, and the mutex
        re-acquired. The PID file is the gate: only a PID we wrote earlier
        (a FastPrompter) is killed."""
        _write_owner_pid(999999)
        # 1) recorded owner is ALIVE (typical frozen-but-alive case) -> RECLAIMED
        monkeypatch.setattr(
            "fastprompter.core.instance_lock.is_pid_alive", lambda pid: True)
        monkeypatch.setattr(
            "fastprompter.core.instance_lock._owner_is_stale", lambda: True)
        monkeypatch.setattr(
            "fastprompter.core.instance_lock.kill_pid",
            lambda pid, timeout_s=2.0: (True, "process terminated"))
        # 1st acquire: False (someone else holds it). 2nd: True (reclaimed).
        original_acquire = FakeLock.acquire
        calls = {"n": 0}

        def fake_acquire(self, timeout_ms=0):
            calls["n"] += 1
            return calls["n"] >= 2, ""

        try:
            FakeLock.acquire = fake_acquire
            role, reason = bootstrap_ownership(
                FakeLock(owned=False), lambda: False)
        finally:
            FakeLock.acquire = original_acquire
        assert role == RECLAIMED
        assert "999999" in reason
        assert "frozen" in reason

    def test_dead_owner_pid_stays_unresponsive(self, monkeypatch):
        """A dead owner releases its mutex automatically; the OS path is
        faster than our kill. Stays UNRESPONSIVE here so a dead-but-still-
        held lock is a real signal of a wedged OS, not a kill target."""
        _write_owner_pid(999999)
        monkeypatch.setattr(
            "fastprompter.core.instance_lock.is_pid_alive", lambda pid: False)
        role, _ = bootstrap_ownership(FakeLock(owned=False), lambda: False)
        assert role == UNRESPONSIVE

    def test_no_owner_pid_file_stays_unresponsive(self, monkeypatch):
        """A missing PID file must not be auto-reclaimed — killing a
        process we cannot identify is the wrong side of the line."""
        monkeypatch.setattr(
            "fastprompter.core.instance_lock._read_owner_pid", lambda: None)
        role, _ = bootstrap_ownership(FakeLock(owned=False), lambda: False)
        assert role == UNRESPONSIVE

    def test_owner_pid_file_round_trips(self, tmp_path, monkeypatch):
        """The PID file is the cross-process recovery signal: the owner
        writes it on startup, the next launch reads it. Garbage in the
        file must NOT be read as a numeric PID."""
        f = tmp_path / "owner.pid"
        monkeypatch.setattr(
            "fastprompter.core.instance_lock._OWNER_PID_FILE", str(f))
        _write_owner_pid(12345)
        assert _read_owner_pid() == 12345
        f.write_text("not a number")
        assert _read_owner_pid() is None
        f.write_text("")
        assert _read_owner_pid() is None
        try:
            f.unlink()
        except OSError:
            pass
        assert _read_owner_pid() is None

    def test_live_owner_pid_is_reclaimable(self, tmp_path, monkeypatch):
        """A recorded live owner is eligible for frozen-process recovery."""
        f = tmp_path / "owner.pid"
        monkeypatch.setattr(
            "fastprompter.core.instance_lock._OWNER_PID_FILE", str(f))
        _write_owner_pid(12345)
        monkeypatch.setattr(
            "fastprompter.core.instance_lock.is_pid_alive", lambda pid: pid == 12345)
        assert _read_owner_pid() == 12345
        from fastprompter.core.instance_lock import _owner_is_stale
        assert _owner_is_stale() is True



def _hold_mutex_script(name):
    return textwrap.dedent(f"""
        import ctypes, time, sys
        from ctypes import wintypes
        k = ctypes.WinDLL("kernel32", use_last_error=True)
        k.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
        k.CreateMutexW.restype = wintypes.HANDLE
        k.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        k.CloseHandle.argtypes = [wintypes.HANDLE]
        h = k.CreateMutexW(None, False, {name!r})
        status = k.WaitForSingleObject(h, 0)
        print("LOCKED", flush=True)
        time.sleep(10)
    """)


@pytest.mark.skipif(sys.platform != "win32", reason="named mutex is Windows-only")
def test_real_mutex_acquire_release():
    name = f"Local\\FastPrompter_Test_{uuid.uuid4()}"
    lock = InstanceLock(name)
    owned, reason = lock.acquire()
    assert owned, reason
    lock.release()
    # after release the same name is free again
    lock2 = InstanceLock(name)
    owned, reason = lock2.acquire()
    assert owned, reason
    lock2.release()


@pytest.mark.skipif(sys.platform != "win32", reason="named mutex is Windows-only")
def test_real_mutex_held_by_other_process_cannot_be_acquired():
    name = f"Local\\FastPrompter_Test_{uuid.uuid4()}"
    proc = subprocess.Popen(
        [sys.executable, "-c", _hold_mutex_script(name)],
        stdout=subprocess.PIPE, text=True)
    try:
        assert proc.stdout.readline().strip() == "LOCKED"
        lock = InstanceLock(name)
        owned, reason = lock.acquire()
        assert owned is False, "a live owner must block the second writer"
        assert "another FastPrompter" in reason
        lock.release()
    finally:
        proc.kill()
        proc.wait()


@pytest.mark.skipif(sys.platform != "win32", reason="named mutex is Windows-only")
def test_real_mutex_freed_after_owner_dies():
    name = f"Local\\FastPrompter_Test_{uuid.uuid4()}"
    proc = subprocess.Popen(
        [sys.executable, "-c", _hold_mutex_script(name)],
        stdout=subprocess.PIPE, text=True)
    try:
        assert proc.stdout.readline().strip() == "LOCKED"
    finally:
        proc.kill()
        proc.wait()
    # OS released the mutex with the process - the next owner may acquire it
    lock = InstanceLock(name)
    owned, reason = lock.acquire()
    assert owned, reason
    lock.release()


class TestReleaseMutexSemantics:
    """Phase-7: normal release is EXPLICIT ReleaseMutex, not process death."""

    @pytest.mark.skipif(sys.platform != "win32", reason="named mutex is Windows-only")
    def test_waiter_acquires_after_explicit_release_while_owner_alive(self):
        name = f"Local\\FastPrompter_Test_{uuid.uuid4()}"
        owner = InstanceLock(name)
        owned, _ = owner.acquire()
        assert owned

        import ctypes
        import threading
        import time
        from ctypes import wintypes

        started = threading.Event()
        result = {}

        def waiter():
            k = ctypes.WinDLL("kernel32", use_last_error=True)
            k.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
            k.CreateMutexW.restype = wintypes.HANDLE
            k.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
            k.WaitForSingleObject.restype = wintypes.DWORD
            h = k.CreateMutexW(None, False, name)
            started.set()
            st = k.WaitForSingleObject(h, 5000)
            result["status"] = st
            k.CloseHandle(h)

        t = threading.Thread(target=waiter)
        t.start()
        started.wait()
        time.sleep(0.3)
        # the waiter must still be blocked while the owner is alive
        assert "status" not in result, "waiter acquired while owner was alive"

        owner.release()               # the owner's PROCESS stays alive here
        t.join(5)
        assert not t.is_alive()
        assert result["status"] == WAIT_OBJECT_0, \
            "waiter must acquire only after ReleaseMutex, not before"

    @pytest.mark.skipif(sys.platform != "win32", reason="named mutex is Windows-only")
    def test_abandoned_ownership_is_recorded(self):
        """A dead owner (thread terminated without release) must be recorded
        as abandoned, NOT as a clean handoff."""
        name = f"Local\\FastPrompter_Test_{uuid.uuid4()}"
        import ctypes
        import threading
        from ctypes import wintypes

        def holder():
            k = ctypes.WinDLL("kernel32", use_last_error=True)
            k.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
            k.CreateMutexW.restype = wintypes.HANDLE
            k.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
            k.WaitForSingleObject.restype = wintypes.DWORD
            h = k.CreateMutexW(None, False, name)
            k.WaitForSingleObject(h, 0)   # owns it, then the thread dies
            # no ReleaseMutex, no CloseHandle -> abandoned

        t = threading.Thread(target=holder)
        t.start()
        t.join()

        lock = InstanceLock(name)
        owned, reason = lock.acquire()
        assert owned, reason
        assert lock.abandoned is True, "abandoned recovery must be recorded"
        assert "dead instance" in reason
        lock.release()



class TestNamespaceDecision:
    """Phase-13: one FastPrompter per Windows session.

    The mutex (and IPC server) names are FIXED and session-global, NOT derived
    from a data root: two portable copies pointing at different data roots
    still contend for one writer, and the second hands off via IPC."""

    @pytest.mark.skipif(sys.platform != "win32", reason="named mutex is Windows-only")
    def test_mutex_name_is_fixed_and_global(self):
        from fastprompter.core.instance_lock import MUTEX_NAME
        assert MUTEX_NAME == r"Local\FastPrompter_Write_V15"
        assert InstanceLock().name == MUTEX_NAME

    @pytest.mark.skipif(sys.platform != "win32", reason="named mutex is Windows-only")
    def test_two_locks_on_the_fixed_name_contend(self):
        import threading
        lock1 = InstanceLock()
        owned, reason = lock1.acquire()
        if not owned:
            pytest.skip("a real FastPrompter instance holds the session mutex")
        result = {}

        def waiter():
            lock_w = InstanceLock()
            ok, why = lock_w.acquire()
            result["ok"] = ok
            result["reason"] = why

        # a different THREAD on the same fixed name cannot acquire while the
        # owning thread holds it (Windows mutexes are reentrant per-thread,
        # so same-thread would wrongly succeed)
        t = threading.Thread(target=waiter)
        t.start()
        t.join(5)
        assert result["ok"] is False
        assert "another FastPrompter" in result["reason"]
        lock1.release()

        # after the explicit release, a new thread acquires
        result2 = {}

        def waiter2():
            lock_w = InstanceLock()
            ok, _ = lock_w.acquire()
            result2["ok"] = ok
            if ok:
                lock_w.release()

        t2 = threading.Thread(target=waiter2)
        t2.start()
        t2.join(5)
        assert result2["ok"] is True

