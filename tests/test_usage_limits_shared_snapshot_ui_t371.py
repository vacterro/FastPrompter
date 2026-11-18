"""T-371: the shared LIMISAW reading must reach the quota surface a user sees.

``test_usage_limits_shared_snapshot.py`` proves the provider translates the
document correctly. This file covers the half with the operator in it: the real
discovery + probe path feeding ``LimitOverview``, the vendor labels that name
the rows, and the standalone promise -- no producer means no rows and no socket.
"""

from __future__ import annotations

import json
import socket
import time

from _qt_retire import retire
from PyQt6.QtWidgets import QWidget

from fastprompter.core.usage_limits.model import UNAVAILABLE, AccountRef
from fastprompter.core.usage_limits.providers.shared_snapshot import (
    SNAPSHOT_SCHEMA,
    SharedSnapshotProvider,
)
from fastprompter.core.usage_limits.service import apply_display_names

# The renderer expires windows whose reset already passed, so these fixtures
# must sit in the future at run time -- not at a frozen epoch.
NOW = time.time()


class _State:
    def __init__(self, accounts=(), snapshots=None, status="IDLE"):
        self.accounts = list(accounts)
        self.snapshots = dict(snapshots or {})
        self.status = status


class _Service:
    def __init__(self, accounts=(), snapshots=None, status="IDLE"):
        self._state = _State(accounts, snapshots, status)

    @property
    def state_copy(self):
        return self._state

    def add_callback(self, cb):
        pass


class _MainWin(QWidget):
    def __init__(self):
        super().__init__()
        self.data = {}
        self._theme_cache = {}


def _window(key, remaining, available=True, reset=None):
    return {
        "key": key,
        "label": key,
        "available": available,
        "remaining": remaining if available else 0,
        "reset_epoch": reset,
        "gated_by": "",
        "assumed_full": False,
        "group": "",
        "group_label": "",
    }


def _account(provider, source_id, name, windows, **extra):
    row = {
        "key": provider + "/" + source_id,
        "provider": provider,
        "provider_label": provider,
        "name": name,
        "source_id": source_id,
        "status": "OK",
        "ok": True,
        "carried": False,
        "auth_failed": False,
        "error": "",
        "windows": windows,
        "balances": [],
        "statistics": [],
    }
    row.update(extra)
    return row


def _write(tmp_path, accounts):
    path = tmp_path / "snapshot.json"
    path.write_text(json.dumps({
        "schema": SNAPSHOT_SCHEMA,
        "producer": "LIMISAW",
        "checked_at_epoch": NOW,
        "accounts": accounts,
    }), encoding="utf-8")
    return str(path)


def _discover_and_probe(path):
    """The service's real path: both providers, shared document, no network."""
    providers = [
        SharedSnapshotProvider("commandcode", path=path),
        SharedSnapshotProvider("opencode-go", path=path),
    ]
    accounts = []
    for provider in providers:
        accounts.extend(provider.discover_accounts())
    accounts = apply_display_names(accounts)
    snapshots = {}
    for account in accounts:
        provider = next(p for p in providers if p.provider_id == account.provider_id)
        snapshots[account.key] = provider.probe(account, deadline=1e9)
    return accounts, snapshots


def test_both_vendors_reach_the_visible_overview(qapp, tmp_path):
    path = _write(tmp_path, [
        _account("commandcode", "cc-id-1", "vacuum34", [
            _window("five_hour", 89, reset=NOW + 7200),
            _window("weekly", 62, reset=NOW + 86400),
            _window("monthly", 0, available=False),
        ], plan="GOAT", verified_identity="eb73faf48d7eda8c"),
        _account("opencode-go", "oc-key-1", "my-local-key", [
            _window("five_hour", 44, reset=NOW + 3600),
            _window("weekly", 78, reset=NOW + 86400),
            _window("monthly", 89, reset=NOW + 2592000),
        ]),
    ])
    accounts, snapshots = _discover_and_probe(path)

    from fastprompter.ui.limit_overview import LimitOverview
    view = LimitOverview(_MainWin(), _Service(accounts, snapshots))
    try:
        headers = [p for kind, p, _s in view._rows if kind == "account"]
        assert [a.display_name for a in headers] == ["CommandCode", "OpenCode Go"]
        shots = {p.provider_id: s for kind, p, s in view._rows if kind == "account"}
        assert shots["commandcode"].plan_type == "GOAT"
        assert shots["opencode-go"].plan_type is None
        window_keys = [p.key for kind, p, _s in view._rows if kind == "window"]
        assert window_keys.count("five_hour") == 2
        assert window_keys.count("weekly") == 2
        # CommandCode publishes its monthly bucket as unavailable; the overview
        # omits it rather than inventing a 0% bar, so only OpenCode's is drawn.
        assert window_keys.count("monthly") == 1
        monthly = [(p, s) for kind, p, s in view._rows
                   if kind == "window" and p.key == "monthly"]
        assert monthly[0][0].remaining_percent == 89.0
        assert monthly[0][1].account.provider_id == "opencode-go"
        tooltip = view._build_tooltip()
        assert "CommandCode" in tooltip and "OpenCode Go" in tooltip
        # The vendor labels are shared by the painter and the pool heading.
        from fastprompter.ui.limit_gauges import _PROVIDER_LABEL as gauge_labels
        from fastprompter.ui.limit_overview import _PROVIDER_LABEL as overview_labels
        for labels in (gauge_labels, overview_labels):
            assert labels["commandcode"] == "CommandCode"
            assert labels["opencode-go"] == "OpenCode Go"
    finally:
        retire(view)


def test_absent_producer_is_standalone_and_opens_no_socket(qapp, tmp_path, monkeypatch):
    def _refuse(*_args, **_kwargs):
        raise AssertionError("the shared-snapshot consumer attempted network I/O")

    monkeypatch.setattr(socket, "create_connection", _refuse)
    monkeypatch.setattr(socket.socket, "connect", _refuse)

    absent = str(tmp_path / "absent.json")
    assert SharedSnapshotProvider("commandcode", path=absent).discover_accounts() == []
    snap = SharedSnapshotProvider("commandcode", path=absent).probe(
        AccountRef(provider_id="commandcode", stable_id="cc-id-1",
                   display_name="CommandCode", source_kind="runtime"),
        deadline=1e9)
    assert snap.status == UNAVAILABLE

    from fastprompter.ui.limit_overview import LimitOverview
    view = LimitOverview(_MainWin(), _Service())
    try:
        assert [row for row in view._rows if row[0] == "account"] == []
    finally:
        retire(view)
