import subprocess
import sys
import time
import uuid

from fastprompter import main as m
from fastprompter.ui import file_container


class _Recorder:
    def __init__(self, events, name):
        self.events = events
        self.name = name

    def close(self):
        self.events.append(self.name)


class _Window:
    def __init__(self, events):
        self.events = events
        self.ipc = _Recorder(events, "IPC_CLOSE")
        self.conn = _Recorder(events, "DB_CLOSE")
        self.state = type("State", (), {"conn": self.conn})()
        self._close_workers_clean = True

    def close(self):
        self.events.extend(("FINAL_CAPTURE", "FINAL_DB_COMMIT"))

    def _wait_for_undo_saves(self):
        self.events.append("UNDO_WRITERS_STOPPED")
        return True

    def deleteLater(self):
        self.events.append("WINDOW_DELETE")


class _App:
    def __init__(self, events):
        self.events = events

    def processEvents(self):
        self.events.append("PROCESS_EVENTS")


class _Lock:
    def __init__(self, events):
        self.events = events
        self.released = False

    def release(self):
        self.events.append("LOCK_RELEASE")
        self.released = True


def test_production_teardown_releases_mutex_after_all_mutators(monkeypatch):
    events = []

    monkeypatch.setattr(
        m, "sync_shutdown_global", lambda: events.append("SYNC_STOPPED") or True
    )
    monkeypatch.setattr(
        m,
        "backup_worker_shutdown_global",
        lambda: events.append("BACKUP_STOPPED") or True,
    )
    monkeypatch.setattr(
        file_container,
        "container_worker_shutdown_global",
        lambda: events.append("CONTAINER_STOPPED") or True,
    )

    lock = _Lock(events)
    assert m._shutdown_application(_Window(events), _App(events), lock) is True

    release = events.index("LOCK_RELEASE")
    for mutation_retired in (
        "FINAL_DB_COMMIT",
        "DB_CLOSE",
        "UNDO_WRITERS_STOPPED",
        "SYNC_STOPPED",
        "BACKUP_STOPPED",
        "CONTAINER_STOPPED",
    ):
        assert events.index(mutation_retired) < release
    assert events.index("WINDOW_DELETE") < release


def test_production_teardown_retains_mutex_after_worker_timeout(monkeypatch):
    events = []
    monkeypatch.setattr(m, "sync_shutdown_global", lambda: False)
    monkeypatch.setattr(m, "backup_worker_shutdown_global", lambda: True)
    monkeypatch.setattr(file_container, "container_worker_shutdown_global", lambda: True)

    lock = _Lock(events)
    assert m._shutdown_application(_Window(events), _App(events), lock) is False
    assert lock.released is False
    assert "LOCK_RELEASE" not in events


def _wait_for(path, proc, timeout=10.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists():
            return
        if proc.poll() is not None:
            raise AssertionError(
                f"teardown process exited early ({proc.returncode}): "
                f"{proc.stdout.read()} {proc.stderr.read()}"
            )
        time.sleep(0.02)
    raise AssertionError(f"timed out waiting for {path}")


def _probe_role(mutex_name):
    script = f"""
from fastprompter.core.instance_lock import InstanceLock, bootstrap_ownership
lock = InstanceLock(name={mutex_name!r})
role, _ = bootstrap_ownership(lock, lambda: False)
print(role, flush=True)
lock.release()
"""
    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, timeout=10
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def test_second_process_waits_for_slow_mutating_teardown(tmp_path):
    mutex_name = rf"Local\FastPrompter_Test_Teardown_{uuid.uuid4().hex}"
    started = tmp_path / "started"
    release = tmp_path / "release"
    mutated = tmp_path / "mutated"
    returned = tmp_path / "returned"
    exit_now = tmp_path / "exit"

    script = f"""
import pathlib
import time
from fastprompter import main as m
from fastprompter.core.instance_lock import InstanceLock, PRIMARY, bootstrap_ownership
from fastprompter.ui import file_container

started = pathlib.Path({str(started)!r})
release = pathlib.Path({str(release)!r})
mutated = pathlib.Path({str(mutated)!r})
returned = pathlib.Path({str(returned)!r})
exit_now = pathlib.Path({str(exit_now)!r})
lock = InstanceLock(name={mutex_name!r})
role, _ = bootstrap_ownership(lock, lambda: False)
assert role == PRIMARY

class Window:
    _close_workers_clean = True
    ipc = None
    conn = None
    state = None
    def close(self): pass
    def _wait_for_undo_saves(self): return True
    def deleteLater(self): pass
class App:
    def processEvents(self): pass

def slow_mutating_shutdown():
    started.write_text('started', encoding='utf-8')
    deadline = time.monotonic() + 10
    while not release.exists() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert release.exists()
    mutated.write_text('old process mutation complete', encoding='utf-8')
    return True

m.sync_shutdown_global = slow_mutating_shutdown
m.backup_worker_shutdown_global = lambda: True
file_container.container_worker_shutdown_global = lambda: True
assert m._shutdown_application(Window(), App(), lock) is True
returned.write_text('returned', encoding='utf-8')
while not exit_now.exists():
    time.sleep(0.01)
"""
    proc = subprocess.Popen(
        [sys.executable, "-c", script],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        _wait_for(started, proc)
        assert _probe_role(mutex_name) != "PRIMARY"

        release.write_text("release", encoding="utf-8")
        _wait_for(mutated, proc)
        _wait_for(returned, proc)
        assert _probe_role(mutex_name) == "PRIMARY"
    finally:
        exit_now.write_text("exit", encoding="utf-8")
        proc.wait(timeout=10)
    assert proc.returncode == 0, proc.stderr.read()
