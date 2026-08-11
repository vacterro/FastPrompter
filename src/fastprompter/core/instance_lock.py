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

``bootstrap_ownership`` is Qt-free and lock-injected so the decision table is
unit-testable without a mutex or a socket:

    lock held by nobody  -> PRIMARY (this process may write)
    lock held by another -> try authenticated IPC handover
        handover ACKed   -> HANDED_OFF (this process exits normally)
        no ACK           -> UNRESPONSIVE (do NOT become a second writer)
"""

from __future__ import annotations

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
    return _UNRESPONSIVE, reason
