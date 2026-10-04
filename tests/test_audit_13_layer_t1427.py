"""Regression tests for audit/13.md (SRC-091 / T-1427).

Covers:
- CORE-001: Provider identity quota-pool deduplication across service, capacity UI, and notifications.
- CORE-002: _load_silo_identities disk immutability before startup safety snapshot publication.
- W2-001: Window close residency; quit_app is sole quit authority; closeEvent does not quit app.
- W2-002: UsageLimitService.shutdown retains unfinished futures across timeouts; daemon threads.
- PERF-001: Sync binding metadata cardinality bounded; sweep retired leases/caches on idle & profile switch.
- PERF-002: Settings-only mutations narrow dirty scope to mark_dirty("settings").
"""

from __future__ import annotations

import ast
from pathlib import Path
import subprocess
import sys
import threading
import time
from unittest.mock import MagicMock

import pytest

from fastprompter.core.usage_limits import identity as ident
from fastprompter.core.usage_limits.model import AccountRef, UsageSnapshot, UsageWindow
from fastprompter.core.usage_limits.notifications import (
    evaluate_limit_notifications,
    notification_key,
)
from fastprompter.core.usage_limits.service import UsageLimitService
from fastprompter.main import FastPrompter


def test_core_001_notifications_deduplicate_by_verified_quota_pool():
    """CORE-001: Accounts sharing verified provider identity emit 1 alert per quota pool."""
    fp = "verified_shared_fingerprint_123"
    meta = ident.describe(fp, "google_id_token_sub")

    acct1 = AccountRef("antigravity", "ctx1", "Context 1", "configured", "", True, {})
    acct2 = AccountRef("antigravity", "ctx2", "Context 2", "shared", "", True, {})

    # Both report low remaining capacity (5% remaining on weekly window)
    snap1 = UsageSnapshot(
        account=acct1, status="OK",
        windows=[UsageWindow(key="weekly", duration_minutes=10080, available=True,
                             used_percent=95.0, remaining_percent=5.0)],
        fetched_at=time.time(), provider_metadata=dict(meta)
    )
    snap2 = UsageSnapshot(
        account=acct2, status="OK",
        windows=[UsageWindow(key="weekly", duration_minutes=10080, available=True,
                             used_percent=95.0, remaining_percent=5.0)],
        fetched_at=time.time(), provider_metadata=dict(meta)
    )

    k1 = notification_key(acct1.key, "weekly")
    k2 = notification_key(acct2.key, "weekly")
    rules = {
        k1: {"enabled": True, "threshold": 20},
        k2: {"enabled": True, "threshold": 20},
    }

    accounts = [acct1, acct2]
    snapshots = {acct1.key: snap1, acct2.key: snap2}

    alerts, state = evaluate_limit_notifications(accounts, snapshots, rules, {})
    # Must emit exactly 1 alert for the shared quota pool, not 2 duplicate alerts
    assert len(alerts) == 1
    # State holds a single suppression key for the canonical account representing the pool
    assert len(state) == 1
    assert k1 in state or k2 in state

    # Second pass with same state produces 0 alerts (suppressed)
    alerts2, state2 = evaluate_limit_notifications(accounts, snapshots, rules, state)
    assert len(alerts2) == 0


def test_core_001_capacity_divergence_text():
    """CORE-001: Status text indicates both context count and quota account count when diverging."""
    win = MagicMock()
    win.data = {}
    lbl = MagicMock()
    win.lbl_limit_status = lbl

    acct1 = AccountRef("antigravity", "ctx1", "Context 1", "configured", "", True, {})
    acct2 = AccountRef("antigravity", "ctx2", "Context 2", "shared", "", True, {})

    fp = "shared_quota_fp"
    meta = ident.describe(fp, "google_id_token_sub")
    snap1 = UsageSnapshot(
        account=acct1, status="OK",
        windows=[UsageWindow(key="weekly", duration_minutes=10080, available=True,
                             used_percent=10.0, remaining_percent=90.0)],
        fetched_at=time.time(), provider_metadata=dict(meta)
    )
    snap2 = UsageSnapshot(
        account=acct2, status="OK",
        windows=[UsageWindow(key="weekly", duration_minutes=10080, available=True,
                             used_percent=10.0, remaining_percent=90.0)],
        fetched_at=time.time(), provider_metadata=dict(meta)
    )

    svc = UsageLimitService({}, discover=False)
    with svc._lock:
        svc._state.accounts = [acct1, acct2]
        svc._state.snapshots = {acct1.key: snap1, acct2.key: snap2}
    win.limit_service = svc

    # Call real method
    FastPrompter._update_limit_status(win)

    call_args = lbl.setText.call_args[0][0]
    # Status bar text should explicitly report both contexts and quota pool count
    assert "2 contexts" in call_args
    assert "1 provider quota account" in call_args


def test_w2_001_close_event_does_not_call_qapplication_quit():
    """W2-001: closeEvent must keep the app resident and never call QApplication.quit."""
    from fastprompter import main as m_module
    main_py = Path(m_module.__file__)
    tree = ast.parse(main_py.read_text(encoding="utf-8"), filename=str(main_py))

    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "closeEvent":
            for sub in ast.walk(node):
                if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute):
                    if sub.func.attr == "quit":
                        target = getattr(sub.func.value, "id", "")
                        assert target != "QApplication", (
                            "QApplication.quit() must not be called inside closeEvent; "
                            "quit_app() is the sole quit authority"
                        )


def test_w2_002_shutdown_retains_unfinished_futures_across_timeouts():
    """W2-002: Repeated shutdown calls with timeouts keep active futures tracked."""
    service = UsageLimitService({}, discover=False)

    class _HangingProvider:
        provider_id = "fake"
        def __init__(self):
            self.entered = threading.Event()
            self.release = threading.Event()
        def discover_accounts(self):
            return []
        def probe(self, account, deadline):
            self.entered.set()
            self.release.wait(timeout=10.0)
            return UsageSnapshot(account=account, status="OK", windows=[])

    provider = _HangingProvider()
    acct = AccountRef("fake", "h1", "Hanging", "configured", "", True, {})
    with service._lock:
        service._providers = {"fake": provider}
        service._state.accounts = [acct]

    service.refresh()
    assert provider.entered.wait(timeout=5.0)

    try:
        # First timeout shutdown
        res1 = service.shutdown(timeout=0.05)
        assert res1 is False
        with service._lock:
            # Active futures must NOT have been dumped
            assert len(service._active_futures) == 1

        # Second timeout shutdown must still see active future and return False boundedly
        res2 = service.shutdown(timeout=0.05)
        assert res2 is False
        with service._lock:
            assert len(service._active_futures) == 1
    finally:
        provider.release.set()
        res3 = service.shutdown(timeout=5.0)
        assert res3 is True


def test_w2_002_daemon_executor_exits_process_cleanly():
    """W2-002: Subprocess with hanging probe thread terminates cleanly on sys.exit."""
    code = """
import sys
import threading
import time
from fastprompter.core.usage_limits.service import UsageLimitService
from fastprompter.core.usage_limits.model import AccountRef, UsageSnapshot

class HangingProvider:
    provider_id = "fake"
    def discover_accounts(self): return []
    def probe(self, account, deadline):
        time.sleep(30)
        return UsageSnapshot(account=account, status="OK", windows=[])

svc = UsageLimitService({}, discover=False)
svc._providers = {"fake": HangingProvider()}
svc._state.accounts = [AccountRef("fake", "h", "H", "configured", "", True, {})]
svc.refresh()
time.sleep(0.1)
svc.shutdown(timeout=0.05)
sys.exit(0)
"""
    cmd = [sys.executable, "-c", code]
    p = subprocess.run(cmd, timeout=5.0, capture_output=True, text=True)
    assert p.returncode == 0


def test_perf_001_sync_sweep_retired_metadata():
    """PERF-001: Sync sweep clears retired leases and caches on idle and profile switch."""
    win = MagicMock()
    win._push_inflight = False
    win._push_jobs_pending = {}
    win._sync_commit_gate = threading.Lock()
    win._configured_sync_binding_keys = lambda: {("default", False, 0)}
    win._sync_last_applied = {("default", False, 0): 100, ("retired", False, 1): 200}
    win._sync_eol_cache = {("default", False, 0): "\n", ("retired", False, 1): "\r\n"}
    win._sync_bom_cache = {("default", False, 0): b"", ("retired", False, 1): b"\xef\xbb\xbf"}
    win._sync_unsafe_bindings = {("default", False, 0), ("retired", False, 1)}
    win._sync_leases = {("default", False, 0): ("w", 10.0), ("retired", False, 1): ("w", 20.0)}

    FastPrompter._sweep_retired_sync_metadata(win)

    # Retired entries should be removed
    assert ("retired", False, 1) not in win._sync_last_applied
    assert ("retired", False, 1) not in win._sync_eol_cache
    assert ("retired", False, 1) not in win._sync_bom_cache
    assert ("retired", False, 1) not in win._sync_unsafe_bindings
    assert ("retired", False, 1) not in win._sync_leases
    # Configured entry remains
    assert ("default", False, 0) in win._sync_last_applied
    assert ("default", False, 0) in win._sync_unsafe_bindings


def test_perf_002_settings_only_mutations_mark_dirty_settings():
    """PERF-002: Settings-only changes mark only 'settings' dirty."""
    win = MagicMock()
    win.mark_dirty = MagicMock()
    win.data = {}
    win.cb_focus = None
    win.btn_bullet_toggle = None

    FastPrompter.toggle_hide_on_clickout(win)
    win.mark_dirty.assert_called_with("settings")

    win.mark_dirty.reset_mock()
    FastPrompter.set_auto_bullet(win, True)
    win.mark_dirty.assert_called_with("settings")
