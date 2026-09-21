"""Tests for the single-instance writer-ownership model.

Two layers:

* ``bootstrap_ownership`` decision table - driven with fake locks so the
  split-brain logic is deterministic without an OS mutex. W2-001: a live
  mutex owner is NEVER killed or force-reclaimed on IPC silence.
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
    _read_owner_pid,
    _verify_owner_identity,
    _write_owner_pid,
    bootstrap_ownership,
)


class FakeLock:
    """A lock whose acquire() answer the test controls.

    ``acquire_calls`` counts every acquire so a test can prove a no-ACK
    startup never polls for a forced mutex reclamation.
    """

    def __init__(self, owned=False, reason="", raise_on_acquire=False):
        self.owned = owned
        self.reason = reason
        self.raise_on_acquire = raise_on_acquire
        self.released = False
        self.acquire_calls = 0

    def acquire(self, timeout_ms=0):
        self.acquire_calls += 1
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
        """W2-001 test B: a live owner that never ACKs IPC is UNRESPONSIVE.
        No kill, no second acquisition attempt: a missing ACK is a
        responsiveness signal, never ownership transfer."""
        killed = []
        monkeypatch.setattr(
            "fastprompter.core.instance_lock.kill_pid",
            lambda pid, timeout_s=2.0: (killed.append(pid) or (True, "killed")))
        lock = FakeLock(
            owned=False, reason="another FastPrompter instance owns the database")
        role, reason = bootstrap_ownership(lock, lambda: False)
        assert role == UNRESPONSIVE
        assert "another FastPrompter" in reason
        assert killed == [], "no-ACK must never terminate the live owner"
        assert lock.acquire_calls == 1, "no-ACK must not poll for reclamation"

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

    def test_live_identity_matched_owner_is_never_killed_on_no_ack(
            self, monkeypatch):
        """W2-001 test C: even a recorded owner whose identity VERIFIES as
        the live process is not a kill target when IPC does not ACK. The
        mutex is authoritative; identity match authorizes nothing."""
        rec = {
            "pid": 4242,
            "create_time": 123456,
            "exe": r"c:\fastprompter\fastprompter.exe",
        }
        live = {"pid": 4242, "create_time": 123456,
                "exe": r"c:\fastprompter\fastprompter.exe"}
        monkeypatch.setattr(
            "fastprompter.core.instance_lock._read_owner_record",
            lambda: rec)
        monkeypatch.setattr(
            "fastprompter.core.instance_lock.is_pid_alive", lambda pid: True)
        monkeypatch.setattr(
            "fastprompter.core.instance_lock._get_process_identity",
            lambda pid: live)
        # prove the setup really is an identity match, so the refusal below
        # cannot be explained by a verification failure
        assert _verify_owner_identity(rec) is True
        killed = []
        monkeypatch.setattr(
            "fastprompter.core.instance_lock.kill_pid",
            lambda pid, timeout_s=2.0: (killed.append(pid) or (True, "killed")))
        lock = FakeLock(owned=False, reason="another FastPrompter instance owns the database")
        role, reason = bootstrap_ownership(lock, lambda: False)
        assert role == UNRESPONSIVE
        assert killed == [], "identity match must not authorize killing"
        assert lock.acquire_calls == 1

    def test_ipc_handover_exception_is_unresponsive(self, monkeypatch):
        """W2-001 test D: a raised handover is UNRESPONSIVE, never a kill."""
        killed = []
        monkeypatch.setattr(
            "fastprompter.core.instance_lock.kill_pid",
            lambda pid, timeout_s=2.0: (killed.append(pid) or (True, "killed")))

        def boom():
            raise OSError("socket gone")

        lock = FakeLock(owned=False, reason="another FastPrompter instance owns the database")
        role, reason = bootstrap_ownership(lock, boom)
        assert role == UNRESPONSIVE
        assert "socket gone" in reason
        assert killed == []
        assert lock.acquire_calls == 1

    def test_missing_or_corrupt_owner_record_never_promotes_writer(
            self, monkeypatch):
        """W2-001 test E: a missing OR corrupt owner record must produce
        UNRESPONSIVE — never a writer promotion, never a kill."""
        killed = []
        monkeypatch.setattr(
            "fastprompter.core.instance_lock.kill_pid",
            lambda pid, timeout_s=2.0: (killed.append(pid) or (True, "killed")))
        for rec in (None, {"no_pid_here": True}, "4242", 4242):
            monkeypatch.setattr(
                "fastprompter.core.instance_lock._read_owner_record",
                lambda rec=rec: rec)
            lock = FakeLock(owned=False, reason="another FastPrompter instance owns the database")
            role, _ = bootstrap_ownership(lock, lambda: False)
            assert role == UNRESPONSIVE, f"record {rec!r} must not promote a writer"
            assert lock.acquire_calls == 1
        assert killed == []

    def test_owner_pid_file_round_trips(self, tmp_path, monkeypatch):
        """The PID file is a diagnostic ownership record: the owner writes it
        on startup. Garbage in the file must NOT be read as a numeric PID."""
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

    def test_w2_001_regression_guard_no_ack_path_never_kills(self, monkeypatch):
        """W2-001 test H: EVERY non-primary/no-ACK startup path completes
        without ever invoking kill_pid. If the destructive reclaim ever
        creeps back into any no-ACK branch, this fails immediately."""

        def _forbidden(pid, timeout_s=2.0):
            raise AssertionError(
                "kill_pid must be unreachable from normal startup (W2-001)")

        monkeypatch.setattr(
            "fastprompter.core.instance_lock.kill_pid", _forbidden)

        rec = {"pid": 4242, "create_time": 1,
               "exe": r"c:\fastprompter\fastprompter.exe"}
        live = {"pid": 4242, "create_time": 1,
                "exe": r"c:\fastprompter\fastprompter.exe"}
        monkeypatch.setattr(
            "fastprompter.core.instance_lock._read_owner_record",
            lambda: rec)
        monkeypatch.setattr(
            "fastprompter.core.instance_lock.is_pid_alive", lambda pid: True)
        monkeypatch.setattr(
            "fastprompter.core.instance_lock._get_process_identity",
            lambda pid: live)

        def boom():
            raise OSError("socket gone")

        scenarios = [
            ("silent owner", lambda: False),          # B
            ("identity-matched silent owner", lambda: False),  # C (record live)
            ("handover raises", boom),                # D
        ]
        for label, handover in scenarios:
            lock = FakeLock(owned=False, reason="owned by someone else")
            role, _ = bootstrap_ownership(lock, handover)
            assert role == UNRESPONSIVE, f"{label}: must refuse, not reclaim"
            assert lock.acquire_calls == 1, f"{label}: must not poll reclamation"

        # E: missing / corrupt owner record
        for bad in (None, {"no_pid": 1}, "4242"):
            monkeypatch.setattr(
                "fastprompter.core.instance_lock._read_owner_record",
                lambda bad=bad: bad)
            lock = FakeLock(owned=False, reason="owned by someone else")
            role, _ = bootstrap_ownership(lock, lambda: False)
            assert role == UNRESPONSIVE, f"record {bad!r}: must refuse"
            assert lock.acquire_calls == 1

        # restore the identity-matched record for the record: RECLAIMED must
        # not even be importable as a reachable outcome any more
        import fastprompter.core.instance_lock as il
        assert not hasattr(il, "RECLAIMED"), (
            "RECLAIMED must not exist as a role normal startup can produce")



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
    import time
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
    owned = False
    for _ in range(50):
        owned, reason = lock.acquire(timeout_ms=50)
        if owned:
            break
        time.sleep(0.02)
    assert owned, reason
    lock.release()


@pytest.mark.skipif(sys.platform != "win32", reason="named mutex is Windows-only")
def test_real_mutex_live_primary_no_ack_is_never_killed_or_reclaimed():
    """W2-001 Windows integration probe (isolated mutex name, isolated owner
    process — never touches a real user FastPrompter).

    1. a primary subprocess takes the REAL named mutex and stays alive,
       deliberately answering no IPC;
    2. a second bootstrap against that mutex must come back UNRESPONSIVE;
    3. the primary PID must still be alive afterwards;
    4. the second instance must still not own the mutex;
    5. after the primary is terminated by the harness, the OS abandoned-
       owner semantics let the next acquirer take the mutex
       (abandoned=True proves the dead-owner recovery path is intact).
    """
    import ctypes
    import time
    from ctypes import wintypes

    from fastprompter.core.instance_lock import (
        UNRESPONSIVE,
        bootstrap_ownership,
        is_pid_alive,
    )

    name = f"Local\\FastPrompter_Test_{uuid.uuid4()}"
    proc = subprocess.Popen(
        [sys.executable, "-c", _hold_mutex_script(name)],
        stdout=subprocess.PIPE, text=True)
    # Keep one handle to the mutex open in THIS process, for the whole test:
    # a kernel object whose handle count reaches zero is destroyed, and its
    # abandonment flag dies with it — the next CreateMutexW then yields a
    # CLEAN mutex (WAIT_OBJECT_0) instead of WAIT_ABANDONED, purely as a
    # race of handle-close vs the next waiter. Holding a reference across
    # the primary's death makes the abandoned state deterministic (measured
    # 120/120 WAIT_ABANDONED with the handle held, 0/120 without).
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
    k.CreateMutexW.restype = wintypes.HANDLE
    k.CloseHandle.argtypes = [wintypes.HANDLE]
    keep_alive = k.CreateMutexW(None, False, name)
    assert keep_alive, "probe could not open the test mutex"
    try:
        assert proc.stdout.readline().strip() == "LOCKED"

        lock = InstanceLock(name)
        role, reason = bootstrap_ownership(lock, lambda: False)  # no IPC ACK
        assert role == UNRESPONSIVE, (
            f"a live silent owner must yield UNRESPONSIVE, got {role}: {reason}")
        assert not lock._owned, "second instance must never own the mutex"

        primary_pid = proc.pid
        assert is_pid_alive(primary_pid), (
            "the live primary must survive a no-ACK second launch")

        # a fresh contender still cannot take the mutex: ownership untouched
        contender = InstanceLock(name)
        owned, _why = contender.acquire()
        assert owned is False, "mutex must still be held by the live primary"
        contender.release()

        # terminate the primary normally-by-harness; the keep-alive handle
        # stays open so the object survives with its abandoned flag set
        proc.kill()
        proc.wait()
        lock2 = InstanceLock(name)
        owned = False
        for _ in range(50):
            owned, reason = lock2.acquire(timeout_ms=50)
            if owned:
                break
            time.sleep(0.02)
        assert owned, f"dead owner must free the mutex: {reason}"
        assert lock2.abandoned is True, (
            "ownership taken from a killed owner must be recorded abandoned")
        lock2.release()
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
        k.CloseHandle(keep_alive)


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
        import time
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
        # a thread's mutex release at termination is processed by the kernel
        # slightly after join() observes thread death; poll briefly instead
        # of racing a single immediate acquire (the abandoned=True contract
        # below is what this test pins)
        owned, reason = False, ""
        for _ in range(50):
            owned, reason = lock.acquire(timeout_ms=50)
            if owned:
                break
            time.sleep(0.02)
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

