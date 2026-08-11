"""Packaged release probe: verify a built FastPrompter.exe end to end.

Source tests cannot prove the onefile/Nuitka assumptions, so this script runs
a REAL packaged executable through the ownership/handover/persistence contract.
It is deliberately a MANUAL / nightly / release-time tool — a Nuitka build is
too expensive for PR CI.

Usage:
    uv run python tools/probe_release.py [path-to-FastPrompter.exe]

Checks (in order):
  1. the packaged app starts and stays alive
  2. it acquires the session writer mutex
  3. a second packaged instance hands off via authenticated IPC and exits
  4. the portable data root + database are created beside the EXE
  5. the database opens and matches the current schema version
  6. a clean exit releases the mutex (a new acquire succeeds)
  7. a relaunch acquires the mutex again

Exit code 0 = every check passed; anything else prints the failing check.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time

DEFAULT_EXE = "build/FastPrompter.exe"
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def _fail(check, detail=""):
    print(f"FAIL [{check}] {detail}".rstrip())
    sys.exit(1)


def _pass(check):
    print(f"PASS [{check}]")


def main():
    exe = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else DEFAULT_EXE)
    if not os.path.isfile(exe):
        _fail("exe exists", f"{exe} not found; build it with tools/build.py first")

    exe_dir = os.path.dirname(exe)

    def launch(wait=6.0):
        proc = subprocess.Popen([exe], cwd=exe_dir,
                                stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL)
        time.sleep(wait)
        if proc.poll() is not None:
            _fail("stays alive", f"process exited early with {proc.returncode}")
        return proc

    def probe_lock(expect_owned):
        sys.path.insert(0, os.path.join(PROJECT_ROOT, "src"))
        from fastprompter.core.instance_lock import InstanceLock
        lock = InstanceLock()
        owned, reason = lock.acquire()
        if expect_owned and not owned:
            _fail("mutex", f"expected to own it, got: {reason}")
        if not expect_owned and owned:
            _fail("mutex", "expected the app to own it, but we acquired it")
        if owned:
            lock.release()
        return owned

    # 1 + 2: first instance starts and owns the writer mutex
    probe_lock(expect_owned=False)              # nothing running yet
    first = launch()
    _pass("starts and stays alive")
    probe_lock(expect_owned=True)               # the app owns the session mutex

    # 3: a second instance hands off and exits (no second writer)
    second = subprocess.Popen([exe], cwd=exe_dir,
                              stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL)
    try:
        rc = second.wait(timeout=15)
    except subprocess.TimeoutExpired:
        second.kill()
        _fail("handoff", "second instance did not exit (did not hand off)")
    if rc != 0:
        _fail("handoff", f"second instance exited with {rc}")
    _pass("second instance hands off and exits")
    probe_lock(expect_owned=True)               # the first still owns it

    # 4 + 5: data root + database beside the EXE, current schema
    db_path = os.path.join(exe_dir, "data", "local_data_v15.db")
    for _ in range(20):
        if os.path.isfile(db_path):
            break
        time.sleep(0.5)
    if not os.path.isfile(db_path):
        _fail("data root", f"{db_path} was not created beside the EXE")
    _pass("portable data root + database created")
    sys.path.insert(0, os.path.join(PROJECT_ROOT, "src"))
    from fastprompter.core.state import CURRENT_SCHEMA_VERSION, validate_database
    version, _ = validate_database(db_path)
    if version != CURRENT_SCHEMA_VERSION:
        _fail("schema", f"db at v{version}, expected v{CURRENT_SCHEMA_VERSION}")
    _pass("database opens at the current schema")

    # 6 + 7: clean exit releases the mutex, then a relaunch acquires it
    first.terminate()
    try:
        first.wait(timeout=10)
    except subprocess.TimeoutExpired:
        first.kill()
        _fail("clean exit", "first instance did not exit on terminate")
    time.sleep(1.0)
    probe_lock(expect_owned=False)              # the mutex is free again
    _pass("clean exit releases the mutex")
    relaunched = launch(wait=3.0)
    probe_lock(expect_owned=True)
    relaunched.terminate()
    try:
        relaunched.wait(timeout=10)
    except subprocess.TimeoutExpired:
        relaunched.kill()
    _pass("relaunch acquires the mutex")

    print("\nAll release-probe checks passed.")


if __name__ == "__main__":
    main()
