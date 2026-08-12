import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from tests_smoke.test_sync_async import _setup


def test_sync_inflight_survives_profile_switch(win, monkeypatch, tmp_path):
    d = _setup(win, tmp_path)
    
    # 1. Dispatch gen1 for profile A
    win.data["temp_presets"][0] = "# t\nProfile A"
    win.sync_to_disk(force=True)
    snap_a = win._sync_pending
    snap_a["profile"] = 1
    
    win._sync_dispatch_pending()
    
    assert win._sync_inflight_gen == 1
    assert win._sync_busy is True
    
    # 2. Simulate profile switch
    win._sync_on_profile_change()
    
    # The physical worker is still running gen 1!
    assert win._sync_inflight_gen == 1
    assert win._sync_busy is True
    assert getattr(win, "_sync_gen") == 2 # incremented by profile switch
    
    # 3. Request gen2 for profile B
    win.data["temp_presets"][0] = "# t\nProfile B"
    win.sync_to_disk(force=True)
    snap_b = win._sync_pending
    snap_b["profile"] = 2
    
    # 4. Job A completes
    win._sync_on_done(gen=1, snapshot=snap_a, written=["test"], errors=[])
    
    # Since gen1 matched inflight, it cleared inflight, then dispatched B
    assert win._sync_inflight_gen == 3
    assert win._sync_busy is True
    assert getattr(win, "_sync_pending") is None
    
    # Job B completes
    win._sync_on_done(gen=3, snapshot=snap_b, written=["test"], errors=[])
    
    assert win._sync_inflight_gen == 0
    assert win._sync_busy is False
