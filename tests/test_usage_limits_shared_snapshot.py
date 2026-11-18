"""CommandCode / OpenCode Go: consumers of the shared LIMISAW snapshot.

The producer is the ONLY poller. FastPrompter reads its published document and
must (a) invert nothing twice, (b) never merge two accounts by display name,
(c) stay silent and standalone when the document is absent, and (d) make no
network request of its own.
"""

from __future__ import annotations

import json

from fastprompter.core.usage_limits.model import (
    AUTH_REQUIRED,
    OK,
    STALE,
    UNAVAILABLE,
    AccountRef,
)
from fastprompter.core.usage_limits.providers.shared_snapshot import (
    SNAPSHOT_ENV,
    SNAPSHOT_SCHEMA,
    SharedSnapshotProvider,
    load_snapshot,
    snapshot_path,
)

NOW = 1_760_000_000.0


def _window(key, remaining, available=True, reset=None, duration=None):
    return {
        "key": key,
        "available": available,
        "remaining": remaining if available else 0,
        "reset_epoch": reset,
        "duration_minutes": duration,
        "gated_by": "",
        "assumed_full": False,
        "group": "",
        "group_label": "",
    }


def _account(provider, source_id, name, status="OK", ok=True, carried=False,
             windows=None, **extra):
    row = {
        "key": provider + "/" + source_id,
        "provider": provider,
        "provider_label": provider,
        "name": name,
        "source_id": source_id,
        "status": status,
        "ok": ok,
        "carried": carried,
        "auth_failed": status == "AUTH_REQUIRED",
        "error": extra.pop("error", ""),
        "windows": windows if windows is not None else [],
        "balances": extra.pop("balances", []),
        "statistics": extra.pop("statistics", []),
    }
    row.update(extra)
    return row


def _write(tmp_path, accounts, checked=NOW, schema=SNAPSHOT_SCHEMA):
    path = tmp_path / "snapshot.json"
    path.write_text(json.dumps({
        "schema": schema,
        "producer": "LIMISAW",
        "checked_at_epoch": checked,
        "accounts": accounts,
    }), encoding="utf-8")
    return str(path)


def _ref(provider, stable_id, name="account"):
    return AccountRef(provider_id=provider, stable_id=stable_id,
                      display_name=name, source_kind="runtime")


# ---------------------------------------------------------------------------
# discovery
# ---------------------------------------------------------------------------

def test_discovers_only_its_own_vendor(tmp_path):
    path = _write(tmp_path, [
        _account("commandcode", "cc-id-1", "vacuum34"),
        _account("opencode-go", "oc-key-1", "OpenCode Go"),
        _account("codex", "codex-1", "Codex"),
    ])
    cc = SharedSnapshotProvider("commandcode", path=path)
    oc = SharedSnapshotProvider("opencode-go", path=path)
    assert [a.stable_id for a in cc.discover_accounts()] == ["cc-id-1"]
    assert [a.stable_id for a in oc.discover_accounts()] == ["oc-key-1"]


def test_identical_display_names_stay_distinct_accounts(tmp_path):
    path = _write(tmp_path, [
        _account("commandcode", "cc-id-1", "vacuum34"),
        _account("commandcode", "cc-id-2", "vacuum34"),
    ])
    refs = SharedSnapshotProvider("commandcode", path=path).discover_accounts()
    assert len(refs) == 2
    assert {r.stable_id for r in refs} == {"cc-id-1", "cc-id-2"}


def test_missing_or_broken_snapshot_is_standalone(tmp_path):
    provider = SharedSnapshotProvider("commandcode", path=str(tmp_path / "absent.json"))
    assert provider.discover_accounts() == []
    assert load_snapshot(str(tmp_path / "absent.json")) is None

    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    assert SharedSnapshotProvider("commandcode", path=str(bad)).discover_accounts() == []

    wrong = _write(tmp_path, [_account("commandcode", "cc-id-1", "n")], schema="other/9")
    assert SharedSnapshotProvider("commandcode", path=wrong).discover_accounts() == []


def test_snapshot_path_env_override(tmp_path, monkeypatch):
    path = _write(tmp_path, [_account("commandcode", "cc-id-1", "n")])
    monkeypatch.setenv(SNAPSHOT_ENV, path)
    assert snapshot_path() == path
    assert len(SharedSnapshotProvider("commandcode").discover_accounts()) == 1


# ---------------------------------------------------------------------------
# probing
# ---------------------------------------------------------------------------

def test_probe_maps_shared_windows_without_second_inversion(tmp_path):
    path = _write(tmp_path, [
        _account("commandcode", "cc-id-1", "vacuum34", plan="GOAT",
                 windows=[
                     _window("five_hour", 94, reset=NOW + 300, duration=300),
                     _window("weekly", 63, reset=NOW + 3600, duration=10080),
                     _window("monthly", 0, available=False),
                 ],
                 balances=[{"id": "monthly_credits", "label": "Monthly credits left",
                            "value": 57.2, "unit": "credits"}],
                 statistics=[{"id": "total_runs", "label": "Total runs",
                              "value": 16013, "unit": "runs"}],
                 verified_identity="0123456789abcdef"),
    ])
    snap = SharedSnapshotProvider("commandcode", path=path).probe(
        _ref("commandcode", "cc-id-1"), deadline=1e9)
    assert snap.status == OK
    assert snap.plan_type == "GOAT"
    assert snap.fetched_at == NOW
    five = snap.window("five_hour")
    assert five.available and five.remaining_percent == 94.0
    assert five.used_percent == 6.0  # the producer already inverted percent-USED
    assert five.resets_at_epoch == NOW + 300
    monthly = snap.window("monthly")
    assert monthly is not None and not monthly.available
    assert monthly.remaining_percent is None and monthly.used_percent is None
    meta = snap.provider_metadata
    assert meta["balances"][0]["id"] == "monthly_credits"
    assert meta["statistics"][0]["id"] == "total_runs"
    assert meta["verified_identity"] is True


def test_probe_maps_opencode_monthly(tmp_path):
    path = _write(tmp_path, [
        _account("opencode-go", "oc-key-1", "OpenCode Go", windows=[
            _window("five_hour", 50), _window("weekly", 80), _window("monthly", 90),
        ]),
    ])
    snap = SharedSnapshotProvider("opencode-go", path=path).probe(
        _ref("opencode-go", "oc-key-1"), deadline=1e9)
    assert snap.status == OK
    assert snap.window("monthly").remaining_percent == 90.0
    assert snap.window("monthly").used_percent == 10.0


def test_probe_status_mapping(tmp_path):
    path = _write(tmp_path, [
        _account("commandcode", "cc-auth", "a", status="AUTH_REQUIRED", ok=False,
                 error="CommandCode credits: HTTP 401"),
        _account("commandcode", "cc-stale", "b", carried=True, ok=False),
        _account("commandcode", "cc-rate", "c", status="RATE_LIMITED", ok=False,
                 error="HTTP 429"),
    ])
    provider = SharedSnapshotProvider("commandcode", path=path)
    auth = provider.probe(_ref("commandcode", "cc-auth"), deadline=1e9)
    stale = provider.probe(_ref("commandcode", "cc-stale"), deadline=1e9)
    rate = provider.probe(_ref("commandcode", "cc-rate"), deadline=1e9)
    assert auth.status == AUTH_REQUIRED and "401" in auth.error_summary
    assert stale.status == STALE and stale.stale_since == NOW
    # The shared model has no RATE_LIMITED state; the raw vendor outcome is
    # preserved as the code and the summary, never as a fabricated OK.
    assert rate.status == UNAVAILABLE and rate.error_code == "RATE_LIMITED"


def test_probe_unknown_account_and_missing_snapshot(tmp_path):
    path = _write(tmp_path, [_account("commandcode", "cc-id-1", "n")])
    provider = SharedSnapshotProvider("commandcode", path=path)
    unknown = provider.probe(_ref("commandcode", "cc-id-9"), deadline=1e9)
    assert unknown.status == UNAVAILABLE and unknown.error_code == "account_not_in_snapshot"

    gone = SharedSnapshotProvider("commandcode", path=str(tmp_path / "absent.json"))
    missing = gone.probe(_ref("commandcode", "cc-id-1"), deadline=1e9)
    assert missing.status == UNAVAILABLE
    assert missing.error_code == "shared_snapshot_unavailable"
    assert missing.error_summary == ""  # standalone is not an error banner


def test_probe_refuses_to_outlive_deadline(tmp_path):
    path = _write(tmp_path, [_account("commandcode", "cc-id-1", "n")])
    snap = SharedSnapshotProvider("commandcode", path=path).probe(
        _ref("commandcode", "cc-id-1"), deadline=0.0)
    assert snap.status == "ERROR" and snap.error_code == "deadline_exceeded"
