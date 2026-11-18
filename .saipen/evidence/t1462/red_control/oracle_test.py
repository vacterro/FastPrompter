"""T-1462 -- AI Usage Limits visibility repair.

Contract: filtering must follow REMAINING, SPENDABLE capacity. An untouched
100% quota is healthy; a genuinely exhausted or fully gated account is not.
An unavailable sibling window carries no number and no gating authority, so it
must never veto a live pool (the shared LIMISAW snapshot contract:
``available=false`` means "no number", never "0%").
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from fastprompter.core.usage_limits.model import (
    AUTH_REQUIRED,
    FIVE_HOUR,
    MONTHLY,
    OK,
    WEEKLY,
    AccountRef,
    UsageSnapshot,
    UsageWindow,
    account_has_usage,
    account_usable_now,
    qualified_key,
)
from fastprompter.ui.limit_account_selector import visible_quota_accounts


def _acc(provider="codex", name="Test"):
    return AccountRef(provider, f"stable_{name}", name, "auto_default")


def _win(key, remaining, *, used=None, duration=None, group="", available=True,
         gated_by=None, reset_pending=False, assumed_full=False,
         remaining_amount=None, unit=""):
    if used is None:
        used = 100.0 - remaining if isinstance(remaining, (int, float)) else None
    return UsageWindow(
        key=key,
        duration_minutes=duration,
        available=available,
        used_percent=used,
        remaining_percent=remaining,
        gated_by=gated_by,
        assumed_full=assumed_full,
        reset_pending=reset_pending,
        group=group,
        remaining_amount=remaining_amount,
        unit=unit,
    )


def _snap(account, *windows, status=OK, metadata=None):
    return UsageSnapshot(account, status, list(windows),
                         provider_metadata=metadata or {})


def _visible(snap, *, hide_zero=True, hide_unusable=True,
             hidden_keys=frozenset()):
    service = SimpleNamespace(state_copy=SimpleNamespace(
        accounts=[snap.account], snapshots={snap.account.key: snap}))
    data = {
        "limit_gauges_hide_zero_usage": "True" if hide_zero else "False",
        "limit_gauges_hidden_accounts": list(hidden_keys),
    }
    return [a.key for a in visible_quota_accounts(data, service,
                                                   hide_unusable)]


# ---------------------------------------------------------------------------
# Live capacity matrix (both filters ON unless stated)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("windows", [
    # Untouched, fully available governing quota.
    (_win(FIVE_HOUR, 100.0), _win(WEEKLY, 100.0)),
    # CommandCode GOAT: 5h 98%, weekly 61%, monthly unavailable (no number).
    (_win(FIVE_HOUR, 98.0), _win(WEEKLY, 61.0),
     _win(MONTHLY, None, available=False)),
    # OpenCode Go: 5h 43%, weekly 78%, monthly 89%.
    (_win(FIVE_HOUR, 43.0), _win(WEEKLY, 78.0), _win(MONTHLY, 89.0)),
    # Monthly-only plan, full capacity.
    (_win(MONTHLY, 100.0),),
])
def test_live_capacity_survives_both_filters(windows):
    snap = _snap(_acc(), *windows)
    assert account_has_usage(snap) is True
    assert account_usable_now(snap) is True
    assert _visible(snap) == [snap.account.key]


def test_unavailable_optional_window_does_not_veto_live_pool():
    """CommandCode publishes NO monthly object; the unavailable placeholder
    must not reject the live 5h/weekly pair (ProbeCommandCode.cs:214-216)."""
    snap = _snap(_acc(), _win(FIVE_HOUR, 98.0), _win(WEEKLY, 61.0),
                 _win(MONTHLY, None, available=False))
    assert account_usable_now(snap) is True


def test_unavailable_shorter_window_does_not_veto_live_longer_window():
    snap = _snap(_acc(), _win(FIVE_HOUR, None, available=False),
                 _win(WEEKLY, 69.0))
    assert account_usable_now(snap) is True


def test_required_governing_window_unknown_is_not_confirmed_usable():
    """Explicit gated_by evidence pointing at an unreadable dependency stays
    uncertain: no availability and no exhaustion is invented for it."""
    snap = _snap(_acc(), _win(FIVE_HOUR, 50.0, gated_by=WEEKLY),
                 _win(WEEKLY, None, available=False))
    assert account_usable_now(snap) is False


def test_exhausted_longer_window_still_gates_shorter_one():
    snap = _snap(_acc(), _win(FIVE_HOUR, 50.0), _win(WEEKLY, 0.0))
    resolved = __import__(
        "fastprompter.core.usage_limits.model", fromlist=["resolved_windows"]
    ).resolved_windows(snap.windows)
    assert any(w.gated_by == WEEKLY for w in resolved)
    assert account_usable_now(snap) is False
    assert account_has_usage(snap) is False


def test_exhausted_5h_with_live_weekly_follows_each_filter():
    snap = _snap(_acc(), _win(FIVE_HOUR, 0.0), _win(WEEKLY, 69.0))
    # Hide exhausted only: weekly capacity keeps the account.
    assert account_has_usage(snap) is True
    assert _visible(snap, hide_unusable=False) == [snap.account.key]
    # Available-only ON: the 5h short window governs immediate work.
    assert account_usable_now(snap) is False
    assert _visible(snap, hide_unusable=True) == []


def test_all_applicable_pools_exhausted_are_hidden():
    snap = _snap(_acc(), _win(FIVE_HOUR, 0.0), _win(WEEKLY, 0.0))
    assert account_has_usage(snap) is False
    assert account_usable_now(snap) is False
    assert _visible(snap) == []


def test_one_antigravity_pool_exhausted_other_live():
    snap = _snap(
        _acc("antigravity", "AG"),
        _win(qualified_key(FIVE_HOUR, "gemini"), 0.0, group="gemini"),
        _win(qualified_key(WEEKLY, "gemini"), 0.0, group="gemini"),
        _win(qualified_key(FIVE_HOUR, "claude_gpt"), 43.0,
             group="claude_gpt"),
        _win(qualified_key(WEEKLY, "claude_gpt"), 78.0,
             group="claude_gpt"),
    )
    assert account_has_usage(snap) is True
    assert account_usable_now(snap) is True
    assert _visible(snap) == [snap.account.key]


def test_wallet_capacity_survives_exhausted_meter():
    snap = _snap(_acc("freebuff", "FB"),
                 _win(FIVE_HOUR, 0.0), _win(WEEKLY, 0.0),
                 metadata={"wallet_balance": 30.0})
    assert account_has_usage(snap) is True
    assert account_usable_now(snap) is True
    assert _visible(snap) == [snap.account.key]


def test_effective_one_percent_floor_is_not_spendable():
    snap = _snap(_acc(), _win(FIVE_HOUR, 1.0), _win(WEEKLY, 1.0))
    assert account_has_usage(snap) is False
    assert account_usable_now(snap) is False


def test_reset_pending_is_not_invented_as_replenished():
    snap = _snap(_acc(), _win(FIVE_HOUR, None, available=False,
                              reset_pending=True),
                 _win(WEEKLY, None, available=False, reset_pending=True))
    assert account_has_usage(snap) is False
    assert account_usable_now(snap) is False


# ---------------------------------------------------------------------------
# Shared filtering authority and diagnostic surface
# ---------------------------------------------------------------------------

def test_filter_combinations_and_explicit_hide():
    live = _snap(_acc("codex", "Live"), _win(FIVE_HOUR, 100.0),
                 _win(WEEKLY, 100.0))
    service = SimpleNamespace(state_copy=SimpleNamespace(
        accounts=[live.account], snapshots={live.account.key: live}))
    base = {"limit_gauges_hidden_accounts": []}

    for hide_zero, hide_unusable in ((False, False), (False, True),
                                     (True, False), (True, True)):
        data = dict(base,
                    limit_gauges_hide_zero_usage="True" if hide_zero else "False")
        shown = visible_quota_accounts(data, service, hide_unusable)
        assert [a.key for a in shown] == [live.account.key]

    data = dict(base, limit_gauges_hide_zero_usage="False",
                limit_gauges_hidden_accounts=[live.account.key])
    assert visible_quota_accounts(data, service, False) == []


def test_diagnostic_status_keeps_visibility_without_claiming_usable():
    snap = _snap(_acc("antigravity", "Offline"), status=AUTH_REQUIRED)
    assert account_has_usage(snap) is False
    assert account_usable_now(snap) is False
    assert _visible(snap) == [snap.account.key]
