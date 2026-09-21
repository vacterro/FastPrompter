"""T-1269 append A4 — the real Windows clipboard interop probe (operator-run).

The operator's machine has two external clipboard participants (ClipDiary and a
custom ``clipboard+.pyw`` script) besides FastPrompter, and the intermittent
Ctrl+V report has to be attributed to one of them -- or to FastPrompter -- from
EVIDENCE rather than from blame. This tool is the OS-side half of that: it
prints the Windows clipboard GENERATION and OWNER, so the operator can see
whether the generation moves a second time after their own copy (which is what
a background clipboard manager does), and which process owns the clipboard at
that moment.

What it deliberately does NOT do:
  * it never prints clipboard CONTENT -- only lengths, digests and process
    names, so the probe can be run with real user data on the clipboard;
  * it never writes to the clipboard except in the ``--self-copy`` check, which
    restores the previous plain text afterwards;
  * it never sleeps-and-hopes: the generation counter and owner are read from
    the OS, so a race is proven by a moved counter, not by a timer.

Usage::

    uv run python tools/probe_clipboard_interop.py                # report + one probe
    uv run python tools/probe_clipboard_interop.py --watch 30     # watch for 30 s
    uv run python tools/probe_clipboard_interop.py --matrix       # the 12-scenario checklist
    uv run python tools/probe_clipboard_interop.py --self-copy    # Qt set/read-back probe

Run it once for each interop combination in ``SCENARIOS``; the operator-facing
matrix (which combination produced which class of failure) is assembled from
these readings plus FastPrompter's own in-app ring, which the app records per
attempt (``VaultTextEdit.paste_diagnostics()`` and
``VaultTextEdit.paste_key_router_evidence()``).
"""

from __future__ import annotations

import argparse
import hashlib
import os
import sys
import time

sys.path.insert(0, os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src")))

from fastprompter.core.win_clipboard import (  # noqa: E402
    UNKNOWN,
    clipboard_generation,
    clipboard_sequence_number,
)

# The 12 interop scenarios the append requires, in order. Kept here (not only
# in prose) so a drift between the tool and the operator instruction is
# visible in code, and so tests can pin the list.
SCENARIOS = (
    ("fp_only", "FastPrompter only (no external clipboard software)"),
    ("clipdiary_only", "ClipDiary running, clipboard+.pyw stopped"),
    ("clipboard_plus_only", "clipboard+.pyw running, ClipDiary stopped"),
    ("both_running", "ClipDiary AND clipboard+.pyw running"),
    ("os_history", "Windows clipboard history enabled"),
    ("from_notepad", "copy from Notepad"),
    ("from_browser", "copy from a browser"),
    ("from_editor", "copy from VS Code / another editor"),
    ("rapid_copy_paste", "repeated rapid copy -> paste"),
    ("copy_a_copy_b_paste", "copy A -> copy B -> immediate paste"),
    ("new_after_b", "NEW after copy B"),
    ("ctrl_v_after_b", "Ctrl+V after copy B"),
)

# Substring tokens that identify a clipboard participant by process name. A
# custom clipboard+ script runs inside pythonw.exe, so it cannot be identified
# by name -- pythonw is listed separately and explicitly as UNIDENTIFIED
# rather than being guessed at.
_PARTICIPANT_TOKENS = ("clipdiary", "clipboard", "clipbrd", "clipx",
                       "ditto", "arsclip", "clipmate", "clcl")
_SCRIPT_HOSTS = ("pythonw.exe", "python.exe", "wscript.exe", "cscript.exe")


def running_clipboard_participants():
    """Best-effort list of clipboard-capable processes: pid, name, identified.

    A process is reported as ``identified: True`` only when its own name matches
    a known clipboard tool. Script hosts are reported as ``identified: False``:
    the operator knows a custom ``clipboard+.pyw`` rides one of them, and the
    tool is not allowed to pretend it resolved which script that is.
    """
    if sys.platform != "win32":
        return []
    import ctypes
    from ctypes import wintypes

    class PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", ctypes.c_long),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", ctypes.c_wchar * 260),
        ]

    kernel32 = ctypes.windll.kernel32
    snapshot = kernel32.CreateToolhelp32Snapshot(0x2, 0)  # SNAPPROCESS
    if not snapshot or snapshot == -1:
        return []
    found = []
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        ok = kernel32.Process32FirstW(snapshot, ctypes.byref(entry))
        while ok:
            name = entry.szExeFile or ""
            lowered = name.lower()
            identified = any(tok in lowered for tok in _PARTICIPANT_TOKENS)
            if identified or lowered in _SCRIPT_HOSTS:
                found.append({
                    "pid": int(entry.th32ProcessID),
                    "process": name,
                    "identified": identified,
                })
            ok = kernel32.Process32NextW(snapshot, ctypes.byref(entry))
    finally:
        kernel32.CloseHandle(snapshot)
    return found


def sentinel_digest(token):
    """A repeatable label for a generated sentinel WITHOUT its contents.

    Scenarios 10-12 need sentinels whose expected generation is known, but the
    generated text must not be persisted or logged, so only a short digest and
    the length are ever printed.
    """
    token = token or ""
    return {
        "digest": hashlib.sha256(token.encode("utf-8")).hexdigest()[:12],
        "length": len(token),
    }


def make_sentinel(tag="A"):
    """A harmless unique sentinel; callers print only ``sentinel_digest``."""
    return f"FP-T1269-{tag}-{os.getpid()}-{int(time.time() * 1000) % 100000}"


def probe_once(label="probe"):
    """One generation reading, printed as the operator-readable evidence line."""
    return clipboard_generation(label)


def format_probe(probe):
    owner = probe.get("owner") or {}
    return (f"{probe.get('label', '')!s:<16} "
            f"t={probe.get('monotonic')} seq={probe.get('sequence')} "
            f"owner={owner.get('process', UNKNOWN)} pid={owner.get('pid')} "
            f"self={owner.get('is_self')} status={owner.get('status')}")


def report_environment():
    print("== FastPrompter clipboard interop probe (T-1269 A4) ==")
    print(f"platform            : {sys.platform}")
    print(f"python              : {sys.version.split()[0]}")
    print(f"native sequence API : "
          f"{'available' if clipboard_sequence_number() is not None else 'NO READING'}")
    print(f"clipboard owner     : {format_probe(probe_once('owner'))}")
    participants = running_clipboard_participants()
    if not participants:
        print("clipboard processes : none detected (or not on Windows)")
    else:
        print("clipboard processes :")
        for p in participants:
            tag = "identified" if p["identified"] else "script host (UNIDENTIFIED)"
            print(f"    pid={p['pid']:<8} {p['process']:<22} {tag}")
    print("NOTE: a custom clipboard+ script shares pythonw.exe, so its name "
          "cannot be resolved; the OWNER reading during a live conflict is the "
          "only authoritative attribution.")


def watch(seconds=30.0, interval=0.25):
    """Print every generation/owner CHANGE for ``seconds``.

    A clipboard manager that rewrites the clipboard after the operator's own
    copy shows up here as a second, later generation bump with a different
    owner. That is the class-3 signature; nothing is inferred from timing.
    """
    print(f"== watching the clipboard for {seconds:.0f}s ==")
    print("copy text in Notepad / a browser now, and watch whether the "
          "generation moves AGAIN after your own copy.")
    last = None
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        probe = probe_once("watch")
        key = (probe.get("sequence"),
               (probe.get("owner") or {}).get("pid"))
        if key != last:
            print(format_probe(probe))
            last = key
        time.sleep(interval)
    print("== watch finished ==")


def self_copy_probe():
    """Qt set/read-back probe: does OUR OWN write bump the OS generation?

    This separates "the OS generation counter is lying" from "an external owner
    moved it": if setting text through Qt does not bump the sequence number,
    the counter cannot be used as evidence on that machine and the report must
    say so.
    """
    os.environ.setdefault("QT_QPA_PLATFORM", "windows")
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    clip = QApplication.clipboard()
    previous = clip.text()
    before = probe_once("before_set")
    token = make_sentinel("SELF")
    clip.setText(token)
    app.processEvents()
    after = probe_once("after_set")
    read_back = clip.text()
    print(format_probe(before))
    print(format_probe(after))
    print(f"sentinel            : {sentinel_digest(token)}")
    print(f"read-back           : digest={sentinel_digest(read_back)['digest']} "
          f"length={len(read_back or '')}")
    print(f"generation bumped   : {before.get('sequence') != after.get('sequence')}")
    try:
        clip.setText(previous or "")
        app.processEvents()
    except Exception:
        pass
    return 0


def race_check(seconds=5.0, interval=0.1):
    """Copy a sentinel and PROVE whether an external owner rewrites it.

    A3/A5: the operator's report -- Ctrl+V inserting an OLDER value -- is only
explained by the OS clipboard generation moving after the operator's own copy.
A clipboard manager that re-captures the payload does exactly that, and the
signature is a SECOND generation bump (with the competing owner named) after the
one our own write caused. This mode reproduces that around a known sentinel:

    1. record the generation, then write a generated sentinel (the "copy");
    2. sample the generation and owner until they move AGAIN, or time runs out;
    3. compare the payload digest with the sentinel's, never its contents;
    4. report ``external_recapture`` from the moved generation, restore the
       previous clipboard text afterwards.

No sleep-and-hope: the verdict is the OS counter, and the sampling interval is
only how often the counter is read. A machine where the counter never moves gets
``unknown`` from the shared classifier rather than a fabricated race.
"""
    os.environ.setdefault("QT_QPA_PLATFORM", "windows")
    from PyQt6.QtWidgets import QApplication

    from fastprompter.core.win_clipboard import clipboard_race_evidence

    app = QApplication.instance() or QApplication([])
    clip = QApplication.clipboard()
    previous = clip.text()
    before = probe_once("before_copy")
    token = make_sentinel("RACE")
    expected = sentinel_digest(token)
    clip.setText(token)
    app.processEvents()
    baseline = probe_once("after_copy")
    print(format_probe(before))
    print(format_probe(baseline))
    print(f"sentinel            : {expected}")
    samples = [("after_copy", baseline)]
    moves = []
    payload_replaced = False
    restore_on = baseline.get("sequence"), (baseline.get("owner") or {}).get("pid")
    deadline = time.monotonic() + max(0.0, float(seconds))
    while time.monotonic() < deadline:
        time.sleep(max(0.01, float(interval)))
        probe = probe_once("watch")
        key = (probe.get("sequence"), (probe.get("owner") or {}).get("pid"))
        if key == restore_on:
            continue
        label = f"move_{len(moves) + 1}"
        samples.append((label, probe))
        moves.append({
            "label": label,
            "sequence": probe.get("sequence"),
            "process": (probe.get("owner") or {}).get("process", UNKNOWN),
            "pid": (probe.get("owner") or {}).get("pid"),
            "is_self": (probe.get("owner") or {}).get("is_self"),
        })
        print(format_probe(probe))
        if sentinel_digest(clip.text() or "")["digest"] != expected["digest"]:
            payload_replaced = True
        restore_on = key
        baseline = probe
    evidence = clipboard_race_evidence(samples)
    external = [m for m in moves if m.get("is_self") is not True]
    print(f"generation moved after our own copy : {bool(moves)}")
    print(f"competing owners                    : "
          f"{[m.get('process') for m in external] or UNKNOWN}")
    print(f"payload replaced (digest differs)   : {payload_replaced}")
    print(f"external_recapture                  : {bool(moves)}")
    print(f"race evidence (shared classifier)   : {evidence['evidence']} "
          f"sequences={evidence['sequences']}")
    try:
        clip.setText(previous or "")
        app.processEvents()
    except Exception:
        pass
    return 1 if moves else 0


def contention_probe(iterations=300):
    """Do the live clipboard participants BLOCK the paste read path?

    Class 2 has an external cause the in-app ring cannot see: ``OpenClipboard``
    is machine-wide, and a clipboard tool that holds it can make another
    process's clipboard access fail or return empty for that instant. Windows
    does not queue the second opener -- it FAILS it -- so a paste landing in
    that window inserts nothing while everything inside FastPrompter looks
    correct.

    This measures the refusal rate of the native open and whether the Qt
    payload read comes back unusable while the real clipboard managers run. It
    reports only counts, lengths and generations: a refusal is the failure
    class, never the content.
    """
    os.environ.setdefault("QT_QPA_PLATFORM", "windows")
    import ctypes

    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        app = QApplication([])          # kept alive: a dropped QApplication
        # takes the clipboard wrapper with it and clip is then None
    clip = app.clipboard()
    user32 = ctypes.windll.user32
    user32.OpenClipboard.restype = ctypes.c_bool
    user32.OpenClipboard.argtypes = [ctypes.c_void_p]
    user32.CloseClipboard.restype = ctypes.c_bool

    refusals = 0
    consecutive = 0
    worst = 0
    no_mime = 0
    no_text_flag = 0
    sequences = set()
    total = max(1, int(iterations))
    for _ in range(total):
        if user32.OpenClipboard(None):
            user32.CloseClipboard()
            consecutive = 0
        else:
            refusals += 1
            consecutive += 1
            worst = max(worst, consecutive)
        data = clip.mimeData()
        if data is None:
            no_mime += 1
        elif not data.hasText():
            no_text_flag += 1
        sequence = clipboard_sequence_number()
        if sequence is not None:
            sequences.add(sequence)
    print(f"iterations                       : {total}")
    print(f"OpenClipboard refusals           : {refusals} "
          f"({refusals / total:.1%}), longest streak {worst}")
    print(f"mimeData() returned None         : {no_mime}")
    print(f"mimeData() without a text format : {no_text_flag}")
    print(f"distinct generations seen        : {sorted(sequences)}")
    blocked = bool(refusals or no_mime)
    print(f"clipboard read path blocked      : {blocked}")
    if not blocked:
        print("verdict                          : no external blocking "
              "observed in this state; class 2 is NOT reproduced here")
    return 1 if blocked else 0


def print_matrix():
    print("== interop matrix: run the app in each row and record the result ==")
    print("For every scenario collect, from FastPrompter itself:")
    print("  * VaultTextEdit.paste_key_router_evidence()  -> class 1 if the key "
          "counter did not move")
    print("  * VaultTextEdit.paste_diagnostics()[-1]      -> failure_class, "
          "clipboard_changed_during_paste, clipboard_owner_process")
    print("  * this probe's sequence/owner readings around the same copy")
    print()
    for i, (sid, text) in enumerate(SCENARIOS, start=1):
        marker = "  [sentinel A/B required]" if sid in (
            "copy_a_copy_b_paste", "new_after_b", "ctrl_v_after_b") else ""
        print(f"{i:>2}. {sid:<22} {text}{marker}")
    print()
    print("Expected generation for the sentinel rows: the LAST copied token. "
          "A paste that yields the FIRST token, or nothing, while the "
          "generation moved between key entry and paste return, is class 3 -- "
          "an external owner, named by clipboard_owner_process.")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--watch", type=float, metavar="SECONDS",
                        help="watch generation/owner changes for N seconds")
    parser.add_argument("--matrix", action="store_true",
                        help="print the 12-scenario interop checklist")
    parser.add_argument("--self-copy", action="store_true",
                        help="Qt set/read-back probe (restores the clipboard)")
    parser.add_argument("--contention", type=int, metavar="N", nargs="?",
                        const=300, default=None,
                        help="measure whether a live external clipboard "
                             "participant blocks OpenClipboard / the Qt "
                             "payload read (exit 1 when it does)")
    parser.add_argument("--race-check", type=float, metavar="SECONDS",
                        help="write a sentinel and detect an EXTERNAL owner "
                             "rewriting the clipboard afterwards "
                             "(exit 1 when the generation moves again; "
                             "restores the clipboard)")
    args = parser.parse_args(argv)
    if args.matrix:
        return print_matrix()
    report_environment()
    if args.contention is not None:
        print()
        return contention_probe(args.contention)
    if args.race_check is not None:
        print()
        return race_check(args.race_check)
    if args.self_copy:
        print()
        return self_copy_probe()
    if args.watch:
        print()
        watch(args.watch)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
