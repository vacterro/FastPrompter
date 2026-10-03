"""Tests for Codex quota identity pinning, explicit home binding, and UI preservation."""

import json
import time

from fastprompter.core.usage_limits.model import (
    ERROR,
    OK,
    AccountRef,
    UsageSnapshot,
)
from fastprompter.core.usage_limits.providers._codex_probe import (
    parse_windows,
    probe_codex_home,
)
from fastprompter.core.usage_limits.providers.codex import CodexProvider


def test_parse_windows_unavailable_when_used_percent_missing():
    # If usedPercent is missing or None, available must be False (NO DATA != 100%)
    raw = {
        "rateLimits": {
            "primary": {"windowDurationMins": 300, "usedPercent": None},
            "secondary": {"windowDurationMins": 10080},
        }
    }
    parsed = parse_windows(raw)
    assert parsed["five_hour"]["available"] is False
    assert parsed["five_hour"]["remaining_percent"] is None
    assert parsed["five_hour"]["used_percent"] is None

    assert parsed["weekly"]["available"] is False
    assert parsed["weekly"]["remaining_percent"] is None
    assert parsed["weekly"]["used_percent"] is None


def test_identity_mismatch_fails_closed(tmp_path, monkeypatch):
    # auth.json expects account-A, but child process / app-server returns account-B
    home = tmp_path / ".codex"
    home.mkdir()
    auth_file = home / "auth.json"
    auth_file.write_text(json.dumps({
        "tokens": {"account_id": "expected-uuid-111"}
    }), encoding="utf-8")

    class FakeSession:
        def call(self, method, params=None, timeout=None):
            if method == "initialize":
                return {"result": {}}
            if method == "account/read":
                return {
                    "result": {
                        "account": {"email": "wrong@test.com", "planType": "plus"},
                        "workspaceRouting": {"chatgptAccountId": "wrong-uuid-222"},
                    }
                }
            if method == "account/rateLimits/read":
                return {
                    "result": {
                        "accountId": "wrong-uuid-222",
                        "rateLimits": {
                            "primary": {"windowDurationMins": 300, "usedPercent": 0},
                        },
                    }
                }
            return {"result": {}}

        def notify(self, method):
            pass

        def close(self):
            pass

    import fastprompter.core.usage_limits.providers._codex_probe as probe_mod
    monkeypatch.setattr(probe_mod, "_start_app_server", lambda *a, **kw: FakeSession())

    result = probe_codex_home(str(home), deadline=time.monotonic() + 5.0)
    assert result["ok"] is False
    assert result["status"] == "IDENTITY_MISMATCH"
    assert "Identity mismatch" in result["error"]
    assert result["expected_account_id"] == "expected-uuid-111"
    assert result["probed_account_id"] == "wrong-uuid-222"

    # CodexProvider.probe reflects the identity mismatch
    account = AccountRef("codex", "codex_1", "Codex 1", "auto_default", source_path=str(home))
    snap = CodexProvider().probe(account, deadline=time.monotonic() + 5.0)
    assert snap.status == "IDENTITY_MISMATCH"
    assert snap.error_code == "identity_mismatch"


def test_identity_match_binds_verified_metadata(tmp_path, monkeypatch):
    # auth.json and app-server agree on account-A
    home = tmp_path / ".codex"
    home.mkdir()
    auth_file = home / "auth.json"
    auth_file.write_text(json.dumps({
        "tokens": {"account_id": "matched-uuid-333"}
    }), encoding="utf-8")

    class FakeSession:
        def call(self, method, params=None, timeout=None):
            if method == "initialize":
                return {"result": {}}
            if method == "account/read":
                return {
                    "result": {
                        "account": {"email": "matched@example.com", "planType": "plus"},
                        "workspaceRouting": {"chatgptAccountId": "matched-uuid-333"},
                    }
                }
            if method == "account/rateLimits/read":
                return {
                    "result": {
                        "accountId": "matched-uuid-333",
                        "rateLimits": {
                            "primary": {"windowDurationMins": 300, "usedPercent": 15},
                            "secondary": {"windowDurationMins": 10080, "usedPercent": 40},
                        },
                    }
                }
            return {"result": {}}

        def notify(self, method):
            pass

        def close(self):
            pass

    import fastprompter.core.usage_limits.providers._codex_probe as probe_mod
    monkeypatch.setattr(probe_mod, "_start_app_server", lambda *a, **kw: FakeSession())

    account = AccountRef("codex", "codex_1", "Codex 1", "auto_default", source_path=str(home))
    snap = CodexProvider().probe(account, deadline=time.monotonic() + 5.0)
    assert snap.status == OK
    assert snap.provider_metadata["codex_account_id"] == "matched-uuid-333"
    assert snap.provider_metadata["codex_email"] == "matched@example.com"
    assert snap.provider_metadata["codex_home"] == str(home)


def test_ui_preserves_unprobed_and_failing_accounts(monkeypatch):
    import sys

    from PyQt6.QtWidgets import QApplication
    # bound to a name on purpose: the QApplication is garbage-collected
    # immediately when no reference survives the statement
    _app = QApplication.instance() or QApplication(sys.argv)
    from fastprompter.ui.limit_gauges import LimitGauges
    from fastprompter.ui.limit_overview import LimitOverview

    class FakeWin:
        data = {
            "limit_gauges_hide_zero_usage": "True",
            "limit_gauges_hide_unusable_5h": "True",
            "limit_gauges_hidden_accounts": [],
            "limit_gauges_account_order": [],
        }

    class FakeService:
        def add_callback(self, cb):
            pass

        class State:
            def __init__(self):
                self.accounts = [
                    AccountRef("codex", "codex_err", "Codex Broken", "configured"),
                    AccountRef("codex", "codex_unprobed", "Codex Fresh", "configured"),
                ]
                self.snapshots = {
                    "codex:codex_err": UsageSnapshot(
                        account=self.accounts[0],
                        status=ERROR,
                        windows=[],
                        error_code="probe_failed",
                        error_summary="auth error",
                    ),
                    # codex_unprobed is missing from snapshots (unprobed / None)
                }

        state_copy = State()

    win = FakeWin()
    svc = FakeService()

    gauges = LimitGauges(win, svc)
    visible_gauges = gauges._visible_accounts()
    # Neither the error account nor the unprobed account may be hidden
    assert len(visible_gauges) == 2

    overview = LimitOverview(win, svc)
    visible_overview = overview._accounts()
    assert len(visible_overview) == 2
