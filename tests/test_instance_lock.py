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
    UNRESPONSIVE,
    WAIT_OBJECT_0,
    InstanceLock,
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

    def test_second_instance_refused_when_owner_silent(self):
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

