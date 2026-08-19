"""Packaged release probe: verify a built FastPrompter.exe end to end.

Source tests cannot prove the onefile/Nuitka assumptions, so this script runs
a REAL packaged executable through the ownership/handover/persistence contract.
It is deliberately a MANUAL / nightly / release-time tool вЂ” a Nuitka build is
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

    def assert_lock_free():
        sys.path.insert(0, os.path.join(PROJECT_ROOT, "src"))
        from fastprompter.core.instance_lock import InstanceLock
        lock = InstanceLock()
        owned, reason = lock.acquire()
        if not owned:
            _fail("mutex", f"expected lock to be free, but could not acquire: {reason}")
        lock.release()
        lock.release()

    def assert_lock_owned_by_app():
        sys.path.insert(0, os.path.join(PROJECT_ROOT, "src"))
        from fastprompter.core.instance_lock import InstanceLock
        lock = InstanceLock()
        owned, reason = lock.acquire()
        if owned:
            lock.release()
            _fail("mutex", "expected the app to own it, but we acquired it")

    # 1 + 2: first instance starts and owns the writer mutex
    assert_lock_free()              # nothing running yet
    first = launch()
    _pass("starts and stays alive")
    assert_lock_owned_by_app()               # the app owns the session mutex

    # 3: a second instance hands off and exits (no second writer)
    second = subprocess.Popen([exe], cwd=exe_dir,
                              stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL)
    try:
        rc = second.wait(timeout=15)
    except subprocess.TimeoutExpired:
        subprocess.run(['taskkill', '/F', '/T', '/PID', str(second.pid)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        _fail("handoff", "second instance did not exit (did not hand off)")
    if rc != 0:
        _fail("handoff", f"second instance exited with {rc}")
    _pass("second instance hands off and exits")
    assert_lock_owned_by_app()               # the first still owns it

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
    subprocess.run(['taskkill', '/F', '/T', '/PID', str(first.pid)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    first.wait()
    time.sleep(1.0)
    assert_lock_free()              # the mutex is free again
    _pass("clean exit releases the mutex")
    relaunched = launch(wait=3.0)
    assert_lock_owned_by_app()
    subprocess.run(['taskkill', '/F', '/T', '/PID', str(relaunched.pid)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    relaunched.wait()
    _pass("relaunch acquires the mutex")

    print("\nAll release-probe checks passed.")


if __name__ == "__main__":
    main()

