import os
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtWidgets import QApplication

from fastprompter import main as m

_app = QApplication.instance() or QApplication([])

class TestPortableBackupWiring:
    def test_production_wiring(self, tmp_path, monkeypatch):
        d = str(tmp_path / "portable")
        os.makedirs(d, exist_ok=True)
        import fastprompter.utils.portable_backup as pb
        monkeypatch.setattr(pb, "get_portable_backup_dir", lambda: d)
        
        # Make sure sink is installed
        m._install_portable_backup_sink()
        
        # Reset state
        m._BACKUP_PENDING = None
        m._BACKUP_INFLIGHT_GEN = 0
        m._BACKUP_GEN = 0
        pb._last_backup_time = 0.0

        def wait_idle():
            start = time.time()
            while m._BACKUP_INFLIGHT_GEN != 0 or m._BACKUP_PENDING is not None:
                QApplication.processEvents()
                if time.time() - start > 5:
                    pytest.fail("worker did not complete in time")
                time.sleep(0.01)

        snapshot_A = {"temp_presets_all": {"A": ["test"]}, "categories": {"A": [{"text": "t"}]}, "archive_temp_presets_all": {}, "cats_order": ["A"]}
        m._portable_backup_dispatch(snapshot_A)
        
        assert m._BACKUP_INFLIGHT_GEN != 0
        
        wait_idle()
        
        assert m._BACKUP_INFLIGHT_GEN == 0
        assert pb._last_backup_time > 0.0
        
        # Test coalescing
        pb._last_backup_time = 0.0
        
        # Block export to allow queueing
        real_export = pb._do_export
        blocker = True
        
        def slow_export(snap):
            while blocker:
                time.sleep(0.05)
            real_export(snap)
            
        monkeypatch.setattr(pb, "_do_export", slow_export)
        
        snapshot_A2 = {"test": 1}
        m._portable_backup_dispatch(snapshot_A2)
        assert m._BACKUP_INFLIGHT_GEN != 0
        
        snapshot_B = {"test": 2}
        m._portable_backup_dispatch(snapshot_B)
        
        snapshot_C = {"test": 3}
        m._portable_backup_dispatch(snapshot_C)
        
        assert m._BACKUP_PENDING is snapshot_C
        
        blocker = False
        wait_idle()
        
        # Ensure completion was routed
        assert m._BACKUP_INFLIGHT_GEN == 0
        assert m._BACKUP_PENDING is None
        assert pb._last_backup_time > 0.0

    def test_backup_throttle_on_failure(self, tmp_path, monkeypatch):
        d = str(tmp_path / "portable")
        os.makedirs(d, exist_ok=True)
        import fastprompter.utils.portable_backup as pb
        monkeypatch.setattr(pb, "get_portable_backup_dir", lambda: d)
        
        m._install_portable_backup_sink()
        m._BACKUP_PENDING = None
        m._BACKUP_INFLIGHT_GEN = 0
        m._BACKUP_GEN = 0
        pb._last_backup_time = 1000.0 # simulate past success
        
        def wait_idle():
            start = time.time()
            while m._BACKUP_INFLIGHT_GEN != 0 or m._BACKUP_PENDING is not None:
                QApplication.processEvents()
                if time.time() - start > 5:
                    pytest.fail("worker did not complete in time")
                time.sleep(0.01)

        real_export = pb._do_export
        def fail_export(snap):
            raise OSError("disk full")
            
        monkeypatch.setattr(pb, "_do_export", fail_export)
        
        snapshot = {"temp_presets_all": {}, "categories": {}, "archive_temp_presets_all": {}, "cats_order": []}
        m._portable_backup_dispatch(snapshot)
        wait_idle()
        
        # Should clear the throttle!
        assert pb._last_backup_time == 0.0
