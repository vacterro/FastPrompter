import os
import sys
import threading

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from fastprompter import main as m
from tests_smoke.test_sync_async import _setup

_app = QApplication.instance() or QApplication([])

class TestSyncShutdownSerialization:
    def test_shutdown_fallback_serialization(self, win, monkeypatch, tmp_path):
        # We need a real worker that is slow inside the write lock
        # gen1 starts, acquires lock, blocks.
        # shutdown begins, bounded wait expires, fallback tries to acquire lock, fails.
        # gen1 resumes and finishes.
        
        block_event = threading.Event()
        resume_event = threading.Event()
        
        real_write = m._sync_mechanical_write
        def mock_write(snapshot):
            with m._SYNC_WRITE_LOCK:
                block_event.set()
                resume_event.wait()
                return real_write(snapshot)
        
        monkeypatch.setattr(m, "_sync_mechanical_write", mock_write)
        
        d = _setup(win, tmp_path)
        os.makedirs(d, exist_ok=True)
        win.data["temp_presets"][0] = "# t\ngen1"
        
        # Dispatch gen1
        snap1 = win._capture_sync_snapshot(force=True)
        assert snap1 is not None
        print("SNAP1 FILES:", snap1["files"])
        
        thread = m.QThread()
        worker = m._SyncWorker()
        worker.moveToThread(thread)
        worker.dispatch.connect(worker._run)
        thread.start()
        
        m._SYNC_SHARED_THREAD = thread
        m._SYNC_SHARED_WORKER = worker
        
        worker.dispatch.emit(snap1, 1)
        win._sync_busy = True
        
        # Wait for worker to enter lock
        block_event.wait(timeout=2.0)
        
        # Worker is now holding the lock. Let's trigger shutdown.
        win.data["temp_presets"][0] = "# t\ngen2"
        # shutdown with short timeout
        win._sync_shutdown(timeout_s=0.1)
        
        # Shutdown should have timed out and failed to acquire lock, skipping fallback.
        resume_event.set()
        
        # Wait for thread to finish
        m.sync_shutdown_global()
        
        # final content should be gen1 because gen2 was dropped!
        import glob
        files = glob.glob(os.path.join(d, "**", "*.md"), recursive=True)
        print(f"FILES in {d}: {files}")
        assert len(files) > 0
        content = open(files[0], encoding='utf-8').read()
        assert "gen1" in content
        assert "gen2" not in content

    def test_shutdown_fallback_succeeds_if_lock_available(self, win, monkeypatch, tmp_path):
        d = _setup(win, tmp_path)
        os.makedirs(d, exist_ok=True)
        win.data["temp_presets"][0] = "# t\nfinal_gen"
        
        win._sync_busy = True # simulate stuck GUI state but NO thread holding the lock
        m._SYNC_SHARED_WORKER = None # no worker
        
        win._sync_shutdown(timeout_s=0.1)
        
        # Fallback should acquire the lock and write final_gen
        import glob
        files = glob.glob(os.path.join(d, "**", "*.md"), recursive=True)
        print(f"FILES in {d}: {files}")
        assert len(files) > 0
        content = open(files[0], encoding='utf-8').read()
        assert "final_gen" in content
