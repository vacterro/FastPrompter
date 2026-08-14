import os
import threading
import time

import pytest
from PyQt6.QtCore import QObject, QThread, pyqtSignal
from PyQt6.QtWidgets import QApplication

from fastprompter import main as m
from fastprompter.ui import file_container, watcher_mixin
from fastprompter.ui.watcher_mixin import WatcherMixin

_app = QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def _clean_process_workers():
    assert m.sync_shutdown_global() is True
    assert m.backup_worker_shutdown_global() is True
    assert file_container.container_worker_shutdown_global() is True
    yield
    assert m.sync_shutdown_global() is True
    assert m.backup_worker_shutdown_global() is True
    assert file_container.container_worker_shutdown_global() is True


class _BlockingWorker(QObject):
    dispatch = pyqtSignal()

    def __init__(self, release=None):
        super().__init__()
        self.started = threading.Event()
        self.release = release

    def _run(self):
        self.started.set()
        if self.release is not None:
            assert self.release.wait(5.0), "test did not release worker"


def _thread_with_worker(release=None):
    thread = QThread()
    worker = _BlockingWorker(release)
    worker.moveToThread(thread)
    worker.dispatch.connect(worker._run)
    thread.start()
    assert thread.isRunning()
    return thread, worker


def _start_blocked(release):
    thread, worker = _thread_with_worker(release)
    worker.dispatch.emit()
    assert worker.started.wait(2.0), "worker did not start"
    return thread, worker


def test_wait_thread_seconds_converts_seconds_to_milliseconds():
    class FakeThread:
        def __init__(self):
            self.timeout_ms = None

        def wait(self, timeout_ms):
            self.timeout_ms = timeout_ms
            return True

    thread = FakeThread()
    assert m.wait_thread_seconds(thread, 1.25, "test worker") is True
    assert thread.timeout_ms == 1250


def test_wait_thread_seconds_rejects_invalid_timeout(caplog):
    class FakeThread:
        def wait(self, _timeout_ms):
            raise AssertionError("invalid timeout reached QThread.wait")

    assert m.wait_thread_seconds(FakeThread(), object(), "test worker") is False
    assert "FAILED" in caplog.text


def test_sync_worker_shutdown_stops_thread():
    thread, worker = _thread_with_worker()
    m._SYNC_SHARED_THREAD = thread
    m._SYNC_SHARED_WORKER = worker

    assert m.sync_shutdown_global() is True
    assert thread.isRunning() is False


def test_sync_worker_shutdown_timeout_keeps_owner(monkeypatch):
    release = threading.Event()
    thread, worker = _start_blocked(release)
    m._SYNC_SHARED_THREAD = thread
    m._SYNC_SHARED_WORKER = worker
    monkeypatch.setattr(m, "_SYNC_SHUTDOWN_TIMEOUT_S", 0.05)

    assert m.sync_shutdown_global() is False
    assert thread.isRunning() is True
    assert m._SYNC_SHARED_THREAD is thread
    assert m._SYNC_SHARED_WORKER is worker

    release.set()
    assert m.wait_thread_seconds(thread, 2.0, "test cleanup") is True
    assert m.sync_shutdown_global() is True


def test_backup_worker_shutdown_stops_thread():
    thread, worker = _thread_with_worker()
    m._BACKUP_THREAD = thread
    m._BACKUP_WORKER = worker

    assert m.backup_worker_shutdown_global() is True
    assert thread.isRunning() is False


def test_backup_worker_shutdown_timeout_keeps_owner(monkeypatch):
    release = threading.Event()
    thread, worker = _start_blocked(release)
    m._BACKUP_THREAD = thread
    m._BACKUP_WORKER = worker
    monkeypatch.setattr(m, "_BACKUP_SHUTDOWN_TIMEOUT_S", 0.05)

    assert m.backup_worker_shutdown_global() is False
    assert thread.isRunning() is True
    assert m._BACKUP_THREAD is thread
    assert m._BACKUP_WORKER is worker

    release.set()
    assert m.wait_thread_seconds(thread, 2.0, "test cleanup") is True
    assert m.backup_worker_shutdown_global() is True


def test_container_worker_shutdown_stops_thread():
    thread, worker = _thread_with_worker()
    file_container._CONTAINER_THREAD = thread
    file_container._CONTAINER_WORKER = worker

    assert file_container.container_worker_shutdown_global() is True
    assert thread.isRunning() is False


def test_container_worker_shutdown_timeout_keeps_owner(monkeypatch):
    release = threading.Event()
    thread, worker = _start_blocked(release)
    file_container._CONTAINER_THREAD = thread
    file_container._CONTAINER_WORKER = worker
    monkeypatch.setattr(file_container, "_CONTAINER_SHUTDOWN_TIMEOUT_S", 0.05)

    assert file_container.container_worker_shutdown_global() is False
    assert thread.isRunning() is True
    assert file_container._CONTAINER_THREAD is thread
    assert file_container._CONTAINER_WORKER is worker

    release.set()
    assert m.wait_thread_seconds(thread, 2.0, "test cleanup") is True
    assert file_container.container_worker_shutdown_global() is True


def test_container_shutdown_drains_two_queued_commands(monkeypatch):
    release = threading.Event()
    executed = []
    real_copy = file_container._copy_atomic

    def command_copy(src, dest, is_dir, root=None, root_identity=None):
        executed.append(src)
        if len(executed) == 1:
            assert release.wait(5.0), "test did not release first command"
        return real_copy(src, dest, is_dir, root, root_identity)

    monkeypatch.setattr(file_container, "_copy_atomic", command_copy)
    monkeypatch.setattr(file_container, "_CONTAINER_SHUTDOWN_TIMEOUT_S", 2.0)
    file_container.container_worker_shutdown_global()

    import tempfile

    root = tempfile.mkdtemp(prefix="fastprompter-container-drain-")
    src_a = os.path.join(root, "source-a.txt")
    src_b = os.path.join(root, "source-b.txt")
    dest_a = os.path.join(root, "dest-a.txt")
    dest_b = os.path.join(root, "dest-b.txt")
    for path, text in ((src_a, "A"), (src_b, "B")):
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)

    file_container.dispatch_container_command(
        {"kind": "export", "root": None, "items": (("copy", src_a, dest_a, False),)},
        "A",
    )
    file_container.dispatch_container_command(
        {"kind": "export", "root": None, "items": (("copy", src_b, dest_b, False),)},
        "B",
    )
    deadline = time.monotonic() + 2.0
    while not executed and time.monotonic() < deadline:
        time.sleep(0.01)
    assert executed == [src_a]
    release.set()

    assert file_container.container_worker_shutdown_global() is True
    assert executed == [src_a, src_b]
    assert open(dest_a, encoding="utf-8").read() == "A"
    assert open(dest_b, encoding="utf-8").read() == "B"


class _Watcher(WatcherMixin):
    def __init__(self):
        self._watcher_worker_thread = None
        self._watcher_worker = None


def test_watcher_worker_shutdown_stops_thread():
    watcher = _Watcher()
    thread, worker = _thread_with_worker()
    watcher._watcher_worker_thread = thread
    watcher._watcher_worker = worker

    assert watcher._watcher_shutdown() is True
    assert thread.isRunning() is False


def test_watcher_worker_shutdown_timeout_keeps_owner(monkeypatch):
    watcher = _Watcher()
    release = threading.Event()
    thread, worker = _start_blocked(release)
    watcher._watcher_worker_thread = thread
    watcher._watcher_worker = worker
    monkeypatch.setattr(watcher_mixin, "_WATCHER_SHUTDOWN_TIMEOUT_S", 0.05)

    assert watcher._watcher_shutdown() is False
    assert thread.isRunning() is True
    assert watcher._watcher_worker_thread is thread
    assert watcher._watcher_worker is worker

    release.set()
    assert m.wait_thread_seconds(thread, 2.0, "test cleanup") is True
    assert watcher._watcher_shutdown() is True


@pytest.mark.parametrize("seconds", [-1, -0.5, 0])
def test_wait_thread_seconds_clamps_negative_timeout(seconds):
    class FakeThread:
        def wait(self, timeout_ms):
            assert timeout_ms == 0
            return False

    assert m.wait_thread_seconds(FakeThread(), seconds, "test worker") is False
