"""Packaged release probe: verify a built FastPrompter.exe end to end.

Usage:
    uv run python tools/probe_release.py [path-to-FastPrompter.exe]

The probe runs the EXE in an ISOLATED TEMP DIRECTORY (operator data is never
touched), and checks:

  1. the packaged app starts and stays alive;
  2. it acquires the session writer mutex;
  3. a second packaged instance hands off via authenticated IPC and exits;
  4. the portable data root + database appear in the temp directory;
  5. the database opens and matches the current schema;
  6. a deterministic marker written through the app's own settings persistence
     (`--release-probe-write`) is committed while the app is alive;
  7. GRACEFUL shutdown (WM_CLOSE against the app's own top-level window,
     exercising closeEvent) exits the process and releases the mutex;
  8. relaunch acquires the mutex again and the persisted marker is still there;
  9. the second close is graceful too.

`taskkill /F` is failure cleanup ONLY: a forced kill is recorded as a failed
graceful-shutdown check, never as PASS.

Exit code 0 = every check passed. The full result is written to
build/probe_release_result.json for the release receipt.
"""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import uuid
from ctypes import wintypes
from datetime import UTC, datetime
from pathlib import Path

DEFAULT_EXE = "build/FastPrompter.exe"
PROJECT_ROOT = Path(__file__).resolve().parents[1]
RESULT_PATH = PROJECT_ROOT / "build" / "probe_release_result.json"

WM_CLOSE = 0x0010
MARKER_KEY = "release_probe_marker"
MARKER_PREFIX = "FP-RELEASE-PROBE-"


class ProbeFailure(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _descendant_pids(root_pid: int) -> set[int]:
    kernel32 = ctypes.windll.kernel32
    TH32CS_SNAPPROCESS = 0x00000002

    class PROCESSENTRY32(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.c_void_p),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", ctypes.c_long),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", ctypes.c_char * 260),
        ]

    h_snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if h_snap == -1:
        return {root_pid}
    pe = PROCESSENTRY32()
    pe.dwSize = ctypes.sizeof(PROCESSENTRY32)
    tree: dict[int, list[int]] = {}
    if kernel32.Process32First(h_snap, ctypes.byref(pe)):
        while True:
            tree.setdefault(pe.th32ParentProcessID, []).append(pe.th32ProcessID)
            if not kernel32.Process32Next(h_snap, ctypes.byref(pe)):
                break
    kernel32.CloseHandle(h_snap)

    pids = {root_pid}
    queue = [root_pid]
    while queue:
        curr = queue.pop(0)
        for child in tree.get(curr, []):
            if child not in pids:
                pids.add(child)
                queue.append(child)
    return pids


def _process_windows(pid: int) -> list[int]:
    """Visible top-level windows owned by pid or descendant processes."""
    user32 = ctypes.windll.user32
    handles: list[int] = []
    pids = _descendant_pids(pid)

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def enum_proc(hwnd, _lparam):
        owner = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value in pids and user32.IsWindowVisible(hwnd):
            handles.append(hwnd)
        return True

    user32.EnumWindows(enum_proc, 0)
    return handles


def _window_title(hwnd: int) -> str:
    length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
    buffer = ctypes.create_unicode_buffer(length + 1)
    ctypes.windll.user32.GetWindowTextW(hwnd, buffer, length + 1)
    return buffer.value


def _try_acquire_lock():
    sys.path.insert(0, str(PROJECT_ROOT / "src"))
    from fastprompter.core.instance_lock import InstanceLock

    lock = InstanceLock()
    owned, reason = lock.acquire()
    if owned:
        lock.release()
        lock.release()
    return owned, reason


def _force_kill(pid: int) -> None:
    subprocess.run(
        ["taskkill", "/F", "/T", "/PID", str(pid)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


class Probe:
    def __init__(self, exe: Path, keep_temp: bool):
        self.exe = exe
        self.keep_temp = keep_temp
        self.checks: list[dict] = []
        self.marker = MARKER_PREFIX + uuid.uuid4().hex[:16]
        self.temp_dir = Path(tempfile.mkdtemp(prefix="fastprompter-probe-"))
        self.exe_copy = self.temp_dir / "FastPrompter.exe"
        self.processes: list[subprocess.Popen] = []

    def check(self, name: str, ok: bool, detail: str = "") -> None:
        self.checks.append({"name": name, "status": "PASS" if ok else "FAIL", "detail": detail})
        if not ok:
            raise ProbeFailure(f"{name}: {detail}")

    def launch(self, extra_args: list[str] | None = None, wait: float = 8.0) -> subprocess.Popen:
        proc = subprocess.Popen(
            [str(self.exe_copy), *(extra_args or [])],
            cwd=str(self.temp_dir),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        self.processes.append(proc)
        deadline = time.monotonic() + wait
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                raise ProbeFailure(f"process exited early with {proc.returncode}")
            time.sleep(0.25)
        return proc

    def graceful_close(self, proc: subprocess.Popen, timeout: float = 40.0) -> bool:
        """WM_CLOSE the app's own window; True when the process exits by itself."""
        deadline = time.monotonic() + timeout
        posted = False
        while time.monotonic() < deadline:
            windows = _process_windows(proc.pid)
            titled = [hwnd for hwnd in windows if "FastPrompter" in _window_title(hwnd)]
            targets = titled or [hwnd for hwnd in windows if _window_title(hwnd)] or windows
            if targets:
                for hwnd in targets:
                    ctypes.windll.user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
                posted = True
                break
            time.sleep(0.5)

        if not posted:
            return False

        while time.monotonic() < deadline:
            if proc.poll() is not None:
                return True
            time.sleep(0.25)
        return False

    def close_or_fail(self, proc: subprocess.Popen, check_name: str) -> None:
        if self.graceful_close(proc):
            self.check(check_name, True)
            return
        self.checks.append(
            {
                "name": check_name,
                "status": "FAIL",
                "detail": "graceful WM_CLOSE timed out; forced kill used as cleanup only",
            }
        )
        _force_kill(proc.pid)
        proc.wait()
        raise ProbeFailure(f"{check_name}: graceful close timed out (forced kill was cleanup only)")

    def read_marker(self, db_path: Path) -> str:
        connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        try:
            row = connection.execute(
                "SELECT value FROM settings WHERE key = ?", (MARKER_KEY,)
            ).fetchone()
        finally:
            connection.close()
        return row[0] if row else ""

    def cleanup(self, remove_temp: bool = True) -> None:
        for proc in self.processes:
            if proc.poll() is None:
                _force_kill(proc.pid)
        if self.keep_temp or not remove_temp:
            return
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def run(self) -> dict:
        sys.path.insert(0, str(PROJECT_ROOT / "src"))
        from fastprompter.core.state import CURRENT_SCHEMA_VERSION, validate_database

        if _try_acquire_lock()[0] is False:
            raise ProbeFailure(
                "the FastPrompter writer mutex is held by a live instance; "
                "close every FastPrompter before the packaged probe"
            )
        self.check("mutex free before start", True)

        shutil.copy2(self.exe, self.exe_copy)

        first = self.launch([f"--release-probe-write={self.marker}"])
        self.check("starts and stays alive", True)
        self.check("app owns the writer mutex", not _try_acquire_lock()[0])

        second = subprocess.Popen(
            [str(self.exe_copy)],
            cwd=str(self.temp_dir),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            rc = second.wait(timeout=25)
        except subprocess.TimeoutExpired:
            _force_kill(second.pid)
            raise ProbeFailure("second instance did not hand off and exit")
        self.check("second instance hands off and exits", rc == 0, f"exit code {rc}")

        db_path = self.temp_dir / "data" / "local_data_v15.db"
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline and not db_path.is_file():
            time.sleep(0.5)
        self.check("portable data root + database created", db_path.is_file(), str(db_path))
        version, _ = validate_database(str(db_path))
        self.check(
            "database opens at the current schema",
            version == CURRENT_SCHEMA_VERSION,
            f"v{version} != v{CURRENT_SCHEMA_VERSION}",
        )

        self.close_or_fail(first, "graceful shutdown releases the process")
        time.sleep(1.0)
        self.check("mutex released after graceful close", _try_acquire_lock()[0])

        marker_now = self.read_marker(db_path)
        self.check(
            "marker persisted through graceful close",
            marker_now == self.marker,
            f"stored marker {marker_now!r}",
        )

        relaunched = self.launch()
        self.check("relaunch acquires the mutex", not _try_acquire_lock()[0])
        self.close_or_fail(relaunched, "second graceful shutdown")
        time.sleep(1.0)
        self.check("mutex released after relaunch close", _try_acquire_lock()[0])
        self.check(
            "persisted marker survives restart",
            self.read_marker(db_path) == self.marker,
        )
        return {
            "ok": True,
            "exe": str(self.exe),
            "exe_sha256": _sha256(self.exe),
            "marker": self.marker,
            "temp_dir": str(self.temp_dir),
            "checks": self.checks,
            "recorded_at": datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }


def _write_result(payload: dict) -> None:
    RESULT_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = RESULT_PATH.with_name(RESULT_PATH.name + f".tmp{os.getpid()}")
    tmp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, RESULT_PATH)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("exe", nargs="?", default=DEFAULT_EXE)
    parser.add_argument("--keep-temp", action="store_true", help="keep the probe dir for forensics")
    args = parser.parse_args(argv)

    exe = Path(args.exe)
    if not exe.is_file():
        print(f"FAIL [exe exists] {exe} not found; build it with tools/build.py first")
        return 1

    probe = Probe(exe.resolve(), args.keep_temp)
    try:
        result = probe.run()
    except ProbeFailure as exc:
        result = {
            "ok": False,
            "exe": str(exe),
            "exe_sha256": _sha256(exe),
            "marker": probe.marker,
            "temp_dir": str(probe.temp_dir),
            "checks": probe.checks,
            "error": str(exc),
            "recorded_at": datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        _write_result(result)
        probe.cleanup(remove_temp=False)
        print(f"FAIL {exc}")
        print(f"Result: {RESULT_PATH} (temp dir kept: {probe.temp_dir})")
        return 1
    _write_result(result)
    probe.cleanup()
    for entry in result["checks"]:
        print(f"{entry['status']} [{entry['name']}]".rstrip())
    print(f"\nAll release-probe checks passed. Result: {RESULT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
