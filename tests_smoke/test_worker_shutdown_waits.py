import os
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QObject, QThread, pyqtSignal
from PyQt6.QtWidgets import QApplication

from fastprompter import main as m
from fastprompter.ui import file_container
from fastprompter.ui.watcher_mixin import WatcherMixin

_app = QApplication.instance() or QApplication([])

class FakeWorker(QObject):
    dispatch = pyqtSignal()
    def __init__(self, slow=False):
        super().__init__()
        self.slow = slow

    def _run(self):
        if self.slow:
            # wait longer than timeout
            time.sleep(10.0)

def test_sync_worker_shutdown():
    thread = QThread()
    worker = FakeWorker()
    worker.moveToThread(thread)
    worker.dispatch.connect(worker._run)
    thread.start()
    
    m._SYNC_SHARED_THREAD = thread
    m._SYNC_SHARED_WORKER = worker
    
    success = m.sync_shutdown_global()
    assert success is True
    assert thread.isRunning() is False

def test_sync_worker_shutdown_timeout():
    thread = QThread()
    worker = FakeWorker(slow=True)
    worker.moveToThread(thread)
    worker.dispatch.connect(worker._run)
    thread.start()
    
    m._SYNC_SHARED_THREAD = thread
    m._SYNC_SHARED_WORKER = worker
    
    # trigger slow run
    worker.dispatch.emit()
    # sleep a bit so the run starts
    time.sleep(0.1)
    
    # the timeout is typically small (e.g. 2 seconds)
    m._SYNC_SHUTDOWN_TIMEOUT_S = 1.0
    success = m.sync_shutdown_global()
    
    assert success is False
    assert thread.isRunning() is True
    
    # cleanup (avoid crashing test suite)
    thread.terminate()
    thread.wait()

def test_backup_worker_shutdown():
    thread = QThread()
    worker = FakeWorker()
    worker.moveToThread(thread)
    worker.dispatch.connect(worker._run)
    thread.start()
    
    m._BACKUP_THREAD = thread
    m._BACKUP_WORKER = worker
    
    success = m.backup_worker_shutdown_global()
    assert success is True
    assert thread.isRunning() is False

def test_backup_worker_shutdown_timeout(monkeypatch):
    thread = QThread()
    worker = FakeWorker(slow=True)
    worker.moveToThread(thread)
    worker.dispatch.connect(worker._run)
    thread.start()
    
    m._BACKUP_THREAD = thread
    m._BACKUP_WORKER = worker
    
    worker.dispatch.emit()
    time.sleep(0.1)
    
    # speed up timeout
    monkeypatch.setattr(m, "wait_thread_seconds", lambda th, s: th.wait(500))
    success = m.backup_worker_shutdown_global()
    
    assert success is False
    assert thread.isRunning() is True
    
    thread.terminate()
    thread.wait()

def test_container_worker_shutdown():
    thread = QThread()
    worker = FakeWorker()
    worker.moveToThread(thread)
    worker.dispatch.connect(worker._run)
    thread.start()
    
    file_container._CONTAINER_THREAD = thread
    file_container._CONTAINER_WORKER = worker
    
    success = file_container.container_worker_shutdown_global()
    assert success is True
    assert thread.isRunning() is False

def test_container_worker_shutdown_timeout(monkeypatch):
    thread = QThread()
    worker = FakeWorker(slow=True)
    worker.moveToThread(thread)
    worker.dispatch.connect(worker._run)
    thread.start()
    
    file_container._CONTAINER_THREAD = thread
    file_container._CONTAINER_WORKER = worker
    
    worker.dispatch.emit()
    time.sleep(0.1)
    
    monkeypatch.setattr(m, "wait_thread_seconds", lambda th, s: th.wait(500))
    success = file_container.container_worker_shutdown_global()
    
    assert success is False
    assert thread.isRunning() is True
    
    thread.terminate()
    thread.wait()

def test_watcher_worker_shutdown():
    class FakeWatcher(WatcherMixin):
        def __init__(self):
            pass
            
    w = FakeWatcher()
    thread = QThread()
    worker = FakeWorker()
    worker.moveToThread(thread)
    worker.dispatch.connect(worker._run)
    thread.start()
    
    w._watcher_worker_thread = thread
    w._watcher_worker = worker
    
    success = w._watcher_shutdown()
    assert success is True
    assert thread.isRunning() is False

def test_watcher_worker_shutdown_timeout(monkeypatch):
    class FakeWatcher(WatcherMixin):
        def __init__(self):
            pass
            
    w = FakeWatcher()
    thread = QThread()
    worker = FakeWorker(slow=True)
    worker.moveToThread(thread)
    worker.dispatch.connect(worker._run)
    thread.start()
    
    w._watcher_worker_thread = thread
    w._watcher_worker = worker
    
    worker.dispatch.emit()
    time.sleep(0.1)
    
    monkeypatch.setattr(m, "wait_thread_seconds", lambda th, s: th.wait(500))
    success = w._watcher_shutdown()
    
    assert success is False
    assert thread.isRunning() is True
    
    thread.terminate()
    thread.wait()
