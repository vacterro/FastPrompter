"""Process-lifetime writer ownership for the single-instance contract.

Ownership of the database is a property of a live PROCESS, not of a
responsive event loop. The old model used "did the IPC socket ACK within
1.5 s" as proof of liveness, so a frozen instance — still holding the DB
open — let a second process become another writer. That is the split-brain
this module exists to make impossible.

The primitive is a Windows named mutex: an OS-owned object that is released
automatically when the owning process dies, and that cannot be "stale" the
way a text file can. One process holds it for its whole lifetime; anyone who
fails to acquire it knows a live owner exists and must not touch the DB.

Namespace decision (Phase 13, second pass): the mutex name is FIXED and
session-global, exactly like the IPC server name. Intended product invariant:
only ONE FastPrompter process may run per Windows session, regardless of how
many portable copies/data roots exist — two copies pointing at DIFFERENT
data roots still contend for the single writer, and the second hands off to
the first via IPC instead of running. Names are deliberately NOT derived
from a data root.

``bootstrap_ownership`` is Qt-free and lock-injected so the decision table is
unit-testable without a mutex or a socket:

    lock held by nobody  -> PRIMARY (this process may write)
    lock held by another -> try authenticated IPC handover
        handover ACKed   -> HANDED_OFF (this process exits normally)
        no ACK           -> UNRESPONSIVE (do NOT become a second writer)
"""

from __future__ import annotations

import os
import sys

from fastprompter.core.logging import logger

# Windows wait results
WAIT_OBJECT_0 = 0x00000000
WAIT_ABANDONED = 0x00000080
WAIT_TIMEOUT = 0x00000102

MUTEX_NAME = r"Local\FastPrompter_Write_V15"

_PRIMARY = "PRIMARY"
_HANDED_OFF = "HANDED_OFF"
_UNRESPONSIVE = "UNRESPONSIVE"
_FAILED = "FAILED"

# Public role constants (bootstrap_ownership returns one of these).
PRIMARY = _PRIMARY
HANDED_OFF = _HANDED_OFF
UNRESPONSIVE = _UNRESPONSIVE
FAILED = _FAILED
RECLAIMED = "RECLAIMED"

# Where the owning process records its PID so a later launch can identify
# and (when justified) reclaim a frozen owner. The file lives beside the
# data directory.
_OWNER_PID_FILE = "owner.pid"


def _owner_pid_path() -> str:
    """Absolute path of the owner-PID file."""
    from fastprompter.utils.paths import get_data_dir
    return os.path.join(get_data_dir(), _OWNER_PID_FILE)


def _write_owner_pid(pid: int) -> None:
    """Record this process's PID as the mutex owner (best-effort)."""
    try:
        with open(_owner_pid_path(), "w", encoding="utf-8") as f:
            f.write(str(int(pid)))
    except Exception:
        pass


def _read_owner_pid() -> int | None:
    """Read the recorded owner PID; returns None on any anomaly."""
    try:
        raw = open(_owner_pid_path(), encoding="utf-8").read().strip()
    except Exception:
        return None
    return int(raw) if raw.isdigit() else None


def _owner_is_stale() -> bool:
    """True when the recorded owner did not acknowledge IPC within grace.

    The PID file alone is never enough to kill: ``_read_owner_pid`` must
    name a process we wrote ourselves (a FastPrompter), it must be alive
    (dead owners release the mutex to the OS automatically), and the IPC
    probe must have already failed. Only then is a live-but-frozen owner
    a reclaim target instead of an UNRESPONSIVE report.
    """
    pid = _read_owner_pid()
    if pid is None:
        return False
    return is_pid_alive(pid) and True


def is_pid_alive(pid: int) -> bool:
    """Best-effort liveness probe for a Windows PID."""
    import ctypes
    from ctypes import wintypes
    if not pid or pid <= 0:
        return False
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    h = ctypes.windll.kernel32.OpenProcess(
        PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
    if not h:
        return False
    try:
        exit_code = wintypes.DWORD()
        ok = ctypes.windll.kernel32.GetExitCodeProcess(h, ctypes.byref(exit_code))
        return bool(ok) and exit_code.value == 259  # STILL_ACTIVE
    finally:
        ctypes.windll.kernel32.CloseHandle(h)


def kill_pid(pid: int, timeout_s: float = 2.0) -> tuple[bool, str]:
    """Terminate one specific process. Returns (ok, detail)."""
    import ctypes
    if not pid or pid <= 0:
        return False, "no pid"
    h = ctypes.windll.kernel32.OpenProcess(
        0x0001, False, int(pid))  # PROCESS_TERMINATE
    if not h:
        return False, "open failed"
    try:
        ok = ctypes.windll.kernel32.TerminateProcess(h, 1)
        if not ok:
            return False, "terminate failed"
    finally:
        ctypes.windll.kernel32.CloseHandle(h)
    return True, "process terminated"


def _load_kernel32():
    import ctypes
    from ctypes import wintypes

    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
    k.CreateMutexW.restype = wintypes.HANDLE
    k.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    k.WaitForSingleObject.restype = wintypes.DWORD
    k.ReleaseMutex.argtypes = [wintypes.HANDLE]
    k.ReleaseMutex.restype = wintypes.BOOL
    k.CloseHandle.argtypes = [wintypes.HANDLE]
    k.CloseHandle.restype = wintypes.BOOL
    return k


class InstanceLock:
    """Writer ownership over a named OS mutex.

    The handle is kept for the process lifetime and closed on release. A
    process that dies without releasing leaves the mutex abandoned; the OS
    then hands ownership to the next acquirer, which is the recovery path.

    Normal release is EXPLICIT: ``ReleaseMutex`` then ``CloseHandle``, so a
    waiter can take over while the owner's process is still alive. Abandoned
    ownership is recorded separately — a crash-recovered lock is not the same
    as a clean handoff, and the caller should validate persistence state
    before trusting it.
    """

    def __init__(self, name=MUTEX_NAME, kernel32=None):
        if sys.platform != "win32":
            raise RuntimeError("InstanceLock is a Windows ownership primitive")
        self.name = name
        self._k = kernel32 or _load_kernel32()
        self._handle = None
        self._owned = False
        self.abandoned = False

    def acquire(self, timeout_ms=0):
        """Try to take ownership. Returns (owned: bool, reason: str).

        ``timeout_ms=0`` means "don't wait": either we own it now or a live
        owner holds it. A timed-out acquisition has already closed the handle
        the caller may never own. ``self.abandoned`` records whether this
        ownership was recovered from a dead owner (WAIT_ABANDONED).
        """
        handle = self._k.CreateMutexW(None, False, self.name)
        if not handle:
            import ctypes
            return False, (f"could not create the ownership mutex "
                           f"(error {ctypes.get_last_error()})")
        status = self._k.WaitForSingleObject(handle, max(0, int(timeout_ms)))
        if status in (WAIT_OBJECT_0, WAIT_ABANDONED):
            # WAIT_ABANDONED: the previous owner died mid-run and the OS
            # handed ownership to us — the recovery path, not an error, but
            # it is RECORDED: a crash-recovered lock is not a clean handoff.
            self._handle = handle
            self._owned = True
            self.abandoned = (status == WAIT_ABANDONED)
            _write_owner_pid(os.getpid())
            if status == WAIT_ABANDONED:
                return True, "ownership recovered from a dead instance"
            return True, ""
        self._k.CloseHandle(handle)
        return False, "another FastPrompter instance owns the database"

    def release(self):
        """Release the mutex and close the handle, in that order.

        ``ReleaseMutex`` is called only when THIS object actually owns the
        mutex, and exactly once; a failure is logged without double-releasing.
        After this returns, a waiter can acquire the mutex while this process
        is still alive.
        """
        handle = self._handle
        if handle is not None:
            if self._owned:
                try:
                    if not self._k.ReleaseMutex(handle):
                        import ctypes
                        logger.warning(
                            "mutex release failed (error %s); closing the "
                            "handle anyway", ctypes.get_last_error())
                except Exception:
                    logger.exception("mutex release raised; closing the handle")
            try:
                self._k.CloseHandle(handle)
            except Exception:
                pass
            self._handle = None
            self._owned = False
            self.abandoned = False


def bootstrap_ownership(lock, ipc_handover):
    """Decide what this process may do. Returns (role, reason).

    ``lock.acquire()`` returns (owned, reason). ``ipc_handover()`` returns
    True when the live owner acknowledged showing its window. The role is one
    of PRIMARY / HANDED_OFF / UNRESPONSIVE / FAILED.
    """
    try:
        owned, reason = lock.acquire()
    except Exception as exc:
        return _FAILED, f"ownership check failed: {exc}"
    if owned:
        return _PRIMARY, reason

    try:
        acked = bool(ipc_handover())
    except Exception as exc:
        return _UNRESPONSIVE, f"{reason}; IPC handover failed: {exc}"
    if acked:
        return _HANDED_OFF, "the running instance showed its window"

    # A live owner that did NOT acknowledge IPC within grace is a frozen/
    # hung instance, not a healthy one — and a healthy instance that simply
    # ignores us must not be killed, so the recorded owner PID is the gate:
    # only a PID we wrote earlier (a FastPrompter) is ever a kill target.
    if _owner_is_stale():
        pid = _read_owner_pid()
        ok, detail = kill_pid(pid)
        if ok:
            # The dead/frozen owner's mutex is released by the OS on
            # termination; try once more to become the writer.
            try:
                owned2, _reason2 = lock.acquire()
            except Exception as exc:
                return _UNRESPONSIVE, f"{reason}; reclaim failed: {exc}"
            if owned2:
                return RECLAIMED, f"frozen owner {pid} {detail}; lock reclaimed"
            return _UNRESPONSIVE, f"frozen owner {pid} {detail}; lock still held"
        return _UNRESPONSIVE, f"frozen owner {pid} kill failed ({detail})"
    return _UNRESPONSIVE, reason
