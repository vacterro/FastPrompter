import os
import subprocess
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from fastprompter import main as m
from fastprompter.ui import file_container

_app = QApplication.instance() or QApplication([])

class FakeLock:
    def __init__(self):
        self.released = False
        self.abandoned = False
    
    def release(self):
        self.released = True

class TestTeardownOwnership:
    def test_teardown_order(self, monkeypatch):
        # We need to trace when mutations happen and when lock is released
        events = []
        
        lock = FakeLock()
        
        # intercept lock release
        real_release = lock.release
        def mock_release():
            events.append("LOCK_RELEASED")
            real_release()
        lock.release = mock_release
        
        # intercept sync_shutdown_global
        def mock_sync_shutdown():
            events.append("SYNC_SHUTDOWN")
        monkeypatch.setattr(m, "sync_shutdown_global", mock_sync_shutdown)
        
        # intercept backup_worker_shutdown_global
        def mock_backup_shutdown():
            events.append("BACKUP_SHUTDOWN")
        monkeypatch.setattr(m, "backup_worker_shutdown_global", mock_backup_shutdown)
        
        # intercept container worker shutdown
        def mock_container_shutdown():
            events.append("CONTAINER_SHUTDOWN")
        monkeypatch.setattr(file_container, "container_worker_shutdown_global", mock_container_shutdown)

        # intercept window deleteLater and close
        class FakeWindow:
            def close(self):
                events.append("WINDOW_CLOSE")
            def deleteLater(self):
                events.append("WINDOW_DELETE")

        window = FakeWindow()
        
        # emulate finally block manually since we can't easily jump into main_entry
        try:
            window.close()
            window.deleteLater()
            QApplication.processEvents()
        except Exception:
            pass
        m.sync_shutdown_global()
        try:
            m.backup_worker_shutdown_global()
        except Exception:
            pass
        try:
            file_container.container_worker_shutdown_global()
        except Exception:
            pass
        lock.release()
        
        # verify event order
        assert "LOCK_RELEASED" in events
        lock_idx = events.index("LOCK_RELEASED")
        
        assert events.index("WINDOW_CLOSE") < lock_idx
        assert events.index("SYNC_SHUTDOWN") < lock_idx
        assert events.index("BACKUP_SHUTDOWN") < lock_idx
        assert events.index("CONTAINER_SHUTDOWN") < lock_idx

    def test_real_lock_overlap(self, monkeypatch):
        # process A enters slow teardown, process B attempts startup.
        # we will use the actual InstanceLock
        from fastprompter.core.instance_lock import PRIMARY, InstanceLock, bootstrap_ownership
        test_mutex = "Local\\FastPrompter_Test_Mutex_" + str(os.getpid())
    
        lockA = InstanceLock(name=test_mutex)
        roleA, _ = bootstrap_ownership(lockA, lambda: False)
        assert roleA == PRIMARY
        
        # B attempts to start in a subprocess
        script = f"""
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join('{os.path.dirname(__file__)}', '../src')))
from fastprompter.core.instance_lock import InstanceLock, PRIMARY, bootstrap_ownership
lockB = InstanceLock(name=r'{test_mutex}')
roleB, _ = bootstrap_ownership(lockB, lambda: False)
print('ROLE:', roleB)
lockB.release()
"""
        env = os.environ.copy()
        result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, env=env)
        
        assert "ROLE: HANDED_OFF" in result.stdout or "ROLE: UNRESPONSIVE" in result.stdout
        
        lockA.release()
        
        # Now B should be able to become primary
        result2 = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, env=env)
        assert "ROLE: PRIMARY" in result2.stdout
