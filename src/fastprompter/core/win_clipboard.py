"""Bounded Windows clipboard GENERATION diagnostics — T-1269 append A.

The operator still sees intermittent Ctrl+V behaviour on the real machine:
sometimes nothing is inserted, sometimes an OLDER clipboard value appears,
while NEW — which reads ``QClipboard.text()`` — seeds from the clipboard
correctly. Two external clipboard participants run on that machine (ClipDiary
and a custom clipboard+ script), so the report has three possible owners and
the app must not guess which one it is:

CLASS 1  key routing      Ctrl+V never reaches FastPrompter.
CLASS 2  paste route      the key arrives and the OS clipboard holds the
                          expected payload, but FastPrompter inserts nothing
                          or into the wrong target.
CLASS 3  ownership race   the key arrives, but by paste time the OS clipboard
                          itself carries a different GENERATION than the item
                          the operator just copied.

In-process state can separate classes 1 and 2 (``VaultTextEdit.
paste_diagnostics`` and ``paste_key_router_evidence``). Class 3 lives on the
other side of the Windows clipboard boundary: only the OS knows its clipboard
generation moved, and an in-process record that never asks is exactly what
would let the app claim it pasted the newest item when it pasted an older one.

This module asks the OS, with two native calls through ctypes — the same
bounded-native-call policy the rest of the project follows (``instance_lock``,
``hotkeys`` already call kernel32/user32 directly), so no pywin32 dependency is
introduced for something ``GetClipboardSequenceNumber()`` already provides:

* ``GetClipboardSequenceNumber()`` — a counter Windows bumps on every clipboard
  ownership change, whoever owns it. Reading it around a paste is the only way
  to prove the payload consumed is the generation the user copied.
* ``GetClipboardOwner()`` + ``GetWindowThreadProcessId()`` + the process image
  name — WHO currently owns the clipboard, so a conflict can be attributed to a
  process name instead of to "something".

NOTHING here reads, copies, stores or logs clipboard CONTENT. Only the
generation counter, the owning HWND/PID/process name and a monotonic timestamp.
Every call is failure-tolerant by design: a missing API, a NULL owner, a
protected process or a non-Windows platform yields ``UNKNOWN``/``None`` instead
of an exception, because a diagnostic must never be able to break the paste it
is observing.
"""

from __future__ import annotations

import ctypes
import os
import sys
import time

IS_WINDOWS = sys.platform == "win32"

UNKNOWN = "UNKNOWN"

# Windows process-access right needed only to read the image name.
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


def clipboard_sequence_number():
    """The OS clipboard generation counter, or ``None`` when unavailable.

    ``GetClipboardSequenceNumber()`` is bumped by Windows for every clipboard
    ownership change (``EmptyClipboard``/``SetClipboardData``) regardless of
    which process caused it — including ClipDiary, a custom clipboard script,
    or the Windows clipboard-history service. Two readings that differ prove
    the payload under the clipboard was replaced between them.

    Windows also returns 0 when there is no clipboard at all, so 0 is reported
    as ``None`` (no evidence) rather than as a generation.
    """
    if not IS_WINDOWS:
        return None
    try:
        user32 = ctypes.windll.user32
        fn = user32.GetClipboardSequenceNumber
        fn.restype = ctypes.c_uint32
        fn.argtypes = []
        value = int(fn())
        return value if value > 0 else None
    except Exception:
        return None


def _owner_process_name(pid):
    """Best-effort image name for ``pid``; ``UNKNOWN`` when it cannot be read.

    A clipboard owner may be a protected or already-exited process, so failure
    is normal and is reported as UNKNOWN rather than raised. Only the base name
    is returned: that is enough to identify ClipDiary / a python script, and it
    keeps a full user path out of the diagnostic.
    """
    if pid is None or pid <= 0:
        return UNKNOWN
    if not IS_WINDOWS:
        return UNKNOWN
    handle = None
    try:
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(
            _PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
        if not handle:
            return UNKNOWN
        buf = ctypes.create_unicode_buffer(1024)
        size = ctypes.c_uint32(1024)
        ok = kernel32.QueryFullProcessImageNameW(
            handle, 0, buf, ctypes.byref(size))
        if not ok or not buf.value:
            return UNKNOWN
        return os.path.basename(buf.value) or UNKNOWN
    except Exception:
        return UNKNOWN
    finally:
        try:
            if handle:
                ctypes.windll.kernel32.CloseHandle(handle)
        except Exception:
            pass


def clipboard_owner():
    """Bounded snapshot of who owns the clipboard right now.

    ``status`` is one of ``ok`` (owner resolved), ``no_owner`` (the clipboard
    is free / has a NULL owner), ``unavailable`` (not Windows) or ``unknown``
    (the call failed). Unresolvable pieces stay ``UNKNOWN`` — the acceptance
    explicitly allows that instead of inventing an identity.
    """
    info = {
        "status": "unknown",
        "hwnd": None,
        "pid": None,
        "process": UNKNOWN,
        "is_self": None,
    }
    if not IS_WINDOWS:
        info["status"] = "unavailable"
        return info
    try:
        user32 = ctypes.windll.user32
        get_owner = user32.GetClipboardOwner
        get_owner.restype = ctypes.c_void_p
        get_owner.argtypes = []
        hwnd = get_owner()
        if not hwnd:
            info["status"] = "no_owner"
            return info
        info["hwnd"] = int(hwnd)
        pid = ctypes.c_uint32(0)
        get_pid = user32.GetWindowThreadProcessId
        get_pid.restype = ctypes.c_uint32
        get_pid.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32)]
        get_pid(ctypes.c_void_p(info["hwnd"]), ctypes.byref(pid))
        if pid.value:
            info["pid"] = int(pid.value)
            info["process"] = _owner_process_name(info["pid"])
            info["is_self"] = info["pid"] == os.getpid()
        info["status"] = "ok"
        return info
    except Exception:
        info["status"] = "unknown"
        return info


def clipboard_generation(label=""):
    """One bounded observation of the OS clipboard generation (never content)."""
    return {
        "label": label,
        "monotonic": time.monotonic(),
        "sequence": clipboard_sequence_number(),
        "owner": clipboard_owner(),
    }


def clipboard_race_evidence(samples):
    """Compare clipboard generations across one operation's sample points.

    ``samples`` is an iterable of ``(label, probe)`` pairs — the natural shape
    for "key entry / immediately before the payload is read / immediately after
    the paste returns". Evidence is ``same`` only when every readable sequence
    agrees, ``changed`` when they do not, and ``unknown`` when fewer than two
    readings were obtainable: an unproven race must never be reported as one.
    """
    labelled = list(samples or ())
    sequences = {}
    owner_processes = []
    for label, probe in labelled:
        probe = probe if isinstance(probe, dict) else {}
        value = probe.get("sequence")
        sequences[label] = value if isinstance(value, int) else None
        owner = probe.get("owner") if isinstance(probe.get("owner"), dict) else {}
        process = owner.get("process")
        if process and process != UNKNOWN and process not in owner_processes:
            owner_processes.append(process)
    known = [v for v in sequences.values() if isinstance(v, int)]
    if len(known) < 2:
        evidence = "unknown"
    else:
        evidence = "same" if len(set(known)) == 1 else "changed"
    latest_owner = {}
    for _label, probe in reversed(labelled):
        owner = (probe or {}).get("owner") if isinstance(probe, dict) else None
        if isinstance(owner, dict) and owner.get("status") == "ok":
            latest_owner = owner
            break
    return {
        "evidence": evidence,
        "changed": evidence == "changed",
        "sequences": sequences,
        "owner_processes": owner_processes,
        "owner": latest_owner,
    }
