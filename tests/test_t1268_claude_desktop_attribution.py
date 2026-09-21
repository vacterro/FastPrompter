"""T-1268: Claude Desktop usage belongs to its organization, not default flag."""

from __future__ import annotations

import json
import time

import pytest

from fastprompter.core.usage_limits.model import OK, STALE
from fastprompter.core.usage_limits.providers.claude import ClaudeProvider
from fastprompter.core.usage_limits.service import apply_display_names


def _write_config(path, organization="org-a", payload=None):
    path.mkdir(parents=True, exist_ok=True)
    (path / "settings.json").write_text("{}", encoding="utf-8")
    config = payload if payload is not None else {
        "oauthAccount": {"organizationUuid": organization},
    }
    (path / ".claude.json").write_text(json.dumps(config), encoding="utf-8")
    return path


def _write_history(path, *, organization=None, age_s=30,
                   five_hour=48, weekly=83):
    sample = {
        "t": (time.time() - age_s) * 1000,
        "u": {"fh": five_hour, "sd": weekly},
    }
    if organization is not None:
        sample["org"] = organization
    path.write_text(json.dumps({"version": 2, "samples": [sample]}),
                    encoding="utf-8")
    return path


@pytest.fixture()
def two_accounts(tmp_path, monkeypatch):
    root = tmp_path / "profile"
    default = _write_config(root / ".claude", "org-A")
    (root / ".claude.json").write_text(json.dumps({
        "oauthAccount": {"organizationUuid": "org-A"},
    }), encoding="utf-8")
    extra = _write_config(root / ".claude-account2", "org-B")
    monkeypatch.setenv("HOME", str(root))
    monkeypatch.setenv("USERPROFILE", str(root))
    provider = ClaudeProvider(use_cli=False)
    accounts = apply_display_names(provider.discover_accounts())
    assert len(accounts) == 2
    account_a = next(a for a in accounts if a.metadata["is_default"])
    account_b = next(a for a in accounts if not a.metadata["is_default"])
    assert account_a.metadata["claude_account_count"] == 2
    assert account_b.metadata["claude_account_count"] == 2
    return provider, account_a, account_b, root, default, extra


def _reading(provider, account, history):
    provider._desktop_history = str(history)
    return provider._desktop_reading(account)


@pytest.mark.parametrize(
    ("sample_org", "owner"),
    [
        ("org-A", "a"),
        ("org-B", "b"),
        ("org-C", None),
    ],
)
def test_identity_matrix_matches_only_the_owning_account(
        two_accounts, tmp_path, sample_org, owner):
    provider, account_a, account_b, *_ = two_accounts
    history = _write_history(tmp_path / "history.json",
                             organization=sample_org)
    reading_a = _reading(provider, account_a, history)
    reading_b = _reading(provider, account_b, history)
    assert bool(reading_a.get("windows")) is (owner == "a")
    assert bool(reading_b.get("windows")) is (owner == "b")


@pytest.mark.parametrize("payload", [
    "not-json",
    {},
    {"oauthAccount": {}},
    {"oauthAccount": {"organizationUuid": None}},
])
def test_bad_account_identity_never_falsely_owns_desktop_data(
        two_accounts, tmp_path, payload):
    provider, account_a, account_b, _root, _default, _extra = two_accounts
    config = _root / ".claude.json"
    if isinstance(payload, str):
        config.write_text(payload, encoding="utf-8")
    else:
        config.write_text(json.dumps(payload), encoding="utf-8")
    history = _write_history(tmp_path / "history.json", organization="org-A")
    assert _reading(provider, account_a, history) == {}
    assert _reading(provider, account_b, history) == {}


def test_two_accounts_with_legacy_orgless_sample_fail_closed(
        two_accounts, tmp_path):
    provider, account_a, account_b, *_ = two_accounts
    history = _write_history(tmp_path / "history.json")
    assert _reading(provider, account_a, history) == {}
    assert _reading(provider, account_b, history) == {}


def test_one_account_keeps_legacy_orgless_compatibility(tmp_path, monkeypatch):
    root = tmp_path / "profile"
    default = root / ".claude"
    default.mkdir(parents=True)
    (default / "settings.json").write_text("{}", encoding="utf-8")
    monkeypatch.setenv("HOME", str(root))
    monkeypatch.setenv("USERPROFILE", str(root))
    provider = ClaudeProvider(use_cli=False)
    account = provider.discover_accounts()[0]
    history = _write_history(tmp_path / "history.json")
    reading = _reading(provider, account, history)
    assert reading["windows"]["five_hour"]["used"] == 48.0


def test_stale_desktop_sample_stays_with_matching_account_and_has_no_reset(
        two_accounts, tmp_path):
    provider, account_a, account_b, *_ = two_accounts
    history = _write_history(tmp_path / "history.json", organization="org-B",
                             age_s=6 * 3600)
    assert _reading(provider, account_a, history) == {}
    reading = _reading(provider, account_b, history)
    assert reading["fresh"] is False
    assert all(window["resets_at"] is None
               for window in reading["windows"].values())
    snapshot = provider.probe(account_b, time.monotonic() + 5)
    assert snapshot.status == STALE
    assert snapshot.window("five_hour").remaining_percent == 52
    assert snapshot.window("five_hour").resets_at_epoch is None


def test_parser_keeps_org_from_the_sample_that_supplied_the_percentages(
        tmp_path):
    from fastprompter.core.usage_limits.providers._claude_desktop import (
        latest_usage,
    )

    now = 1_800_000_000.0
    path = tmp_path / "history.json"
    path.write_text(json.dumps({"samples": [
        {"t": (now - 3600) * 1000, "org": "org-old",
         "u": {"fh": 10, "sd": 5}},
        {"t": (now - 60) * 1000, "org": " ORG-B ",
         "u": {"fh": 48, "sd": 83}},
    ]}), encoding="utf-8")
    usage = latest_usage(path=path, now=now)
    assert usage["org"] == "org-b"
    assert usage["windows"]["five_hour"] == 48.0
    assert usage["windows"]["weekly"] == 83.0


def test_desktop_org_is_rendered_only_under_its_account(two_accounts, tmp_path):
    pytest.importorskip("PyQt6.QtWidgets")
    from PyQt6.QtWidgets import QApplication, QWidget

    from fastprompter.ui.limit_overview import LimitOverview

    _app = QApplication.instance() or QApplication([])
    provider, account_a, account_b, *_ = two_accounts
    history = _write_history(tmp_path / "history.json", organization="org-B")
    provider._desktop_history = str(history)
    snapshots = {
        account_a.key: provider.probe(account_a, time.monotonic() + 5),
        account_b.key: provider.probe(account_b, time.monotonic() + 5),
    }
    assert snapshots[account_a.key].status != OK
    assert snapshots[account_b.key].status == OK
    assert snapshots[account_b.key].window("five_hour").remaining_percent == 52
    assert snapshots[account_b.key].window("weekly").remaining_percent == 17

    class State:
        def __init__(self):
            self.accounts = [account_a, account_b]
            self.snapshots = snapshots

    class Service:
        state_copy = State()

    class Host(QWidget):
        def __init__(self):
            super().__init__()
            self.data = {}
            self._theme_cache = {"raw_colors": {}}

    host = Host()
    view = LimitOverview(host, Service(), host)
    try:
        rows = {}
        current = None
        for kind, payload, _shot in view._rows:
            if kind == "account":
                current = payload.display_name
                rows[current] = []
            elif kind == "window" and current is not None:
                rows[current].append(payload)
        assert rows[account_a.display_name] == []
        assert [window.remaining_percent for window in
                rows[account_b.display_name]] == [52.0, 17.0]
        assert all(window.resets_at_epoch is None
                   for window in rows[account_b.display_name])
    finally:
        view.close()
        view.deleteLater()
        host.close()
        host.deleteLater()


def test_account_reports_do_not_expose_organization_uuid(two_accounts):
    from fastprompter.core.usage_limits.providers.claude import accounts_report

    provider, account_a, account_b, *_ = two_accounts
    rows = accounts_report([account_a, account_b], {})
    assert all("organization" not in row for row in rows)
    assert "org-a" not in repr(rows)
    assert "org-b" not in repr(rows)
