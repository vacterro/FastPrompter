"""T-1462 focused-unit receipt adapter (self-contained).

Same oracle as .saipen/evidence/t1462/red_control/oracle_test.py, whose digest
is anchored in the measured regression pair E-5107/E-5108. The SAIPEN focused
harness copies only tools/ + src/ into its sandbox, so the oracle is expressed
here as unittest methods with identical fixtures and assertions. No test file
in tests/ was changed.
"""

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from fastprompter.core.usage_limits.model import (  # noqa: E402
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
    resolved_windows,
)
from fastprompter.ui.limit_account_selector import visible_quota_accounts  # noqa: E402


def _acc(provider="codex", name="Test"):
    return AccountRef(provider, f"stable_{name}", name, "auto_default")


def _win(key, remaining, *, used=None, duration=None, group="", available=True,
         gated_by=None, reset_pending=False, assumed_full=False,
         remaining_amount=None, unit=""):
    if used is None:
        used = 100.0 - remaining if isinstance(remaining, (int, float)) else None
    return UsageWindow(
        key=key, duration_minutes=duration, available=available,
        used_percent=used, remaining_percent=remaining, gated_by=gated_by,
        assumed_full=assumed_full, reset_pending=reset_pending, group=group,
        remaining_amount=remaining_amount, unit=unit,
    )


def _snap(account, *windows, status=OK, metadata=None):
    return UsageSnapshot(account, status, list(windows),
                         provider_metadata=metadata or {})


def _visible(snap, *, hide_zero=True, hide_unusable=True, hidden_keys=frozenset()):
    service = SimpleNamespace(state_copy=SimpleNamespace(
        accounts=[snap.account], snapshots={snap.account.key: snap}))
    data = {
        "limit_gauges_hide_zero_usage": "True" if hide_zero else "False",
        "limit_gauges_hidden_accounts": list(hidden_keys),
    }
    return [a.key for a in visible_quota_accounts(data, service, hide_unusable)]


class T1462VisibilityOracle(unittest.TestCase):
    def test_live_capacity_survives_both_filters(self):
        matrices = [
            (_win(FIVE_HOUR, 100.0), _win(WEEKLY, 100.0)),
            (_win(FIVE_HOUR, 98.0), _win(WEEKLY, 61.0),
             _win(MONTHLY, None, available=False)),
            (_win(FIVE_HOUR, 43.0), _win(WEEKLY, 78.0), _win(MONTHLY, 89.0)),
            (_win(MONTHLY, 100.0),),
        ]
        for windows in matrices:
            with self.subTest(windows=[w.key for w in windows]):
                snap = _snap(_acc(), *windows)
                self.assertTrue(account_has_usage(snap))
                self.assertTrue(account_usable_now(snap))
                self.assertEqual(_visible(snap), [snap.account.key])

    def test_unavailable_optional_window_does_not_veto_live_pool(self):
        snap = _snap(_acc(), _win(FIVE_HOUR, 98.0), _win(WEEKLY, 61.0),
                     _win(MONTHLY, None, available=False))
        self.assertTrue(account_usable_now(snap))

    def test_unavailable_shorter_window_does_not_veto_live_longer_window(self):
        snap = _snap(_acc(), _win(FIVE_HOUR, None, available=False),
                     _win(WEEKLY, 69.0))
        self.assertTrue(account_usable_now(snap))

    def test_required_governing_window_unknown_is_not_confirmed_usable(self):
        snap = _snap(_acc(), _win(FIVE_HOUR, 50.0, gated_by=WEEKLY),
                     _win(WEEKLY, None, available=False))
        self.assertFalse(account_usable_now(snap))

    def test_exhausted_longer_window_still_gates_shorter_one(self):
        snap = _snap(_acc(), _win(FIVE_HOUR, 50.0), _win(WEEKLY, 0.0))
        resolved = resolved_windows(snap.windows)
        self.assertTrue(any(w.gated_by == WEEKLY for w in resolved))
        self.assertFalse(account_usable_now(snap))
        self.assertFalse(account_has_usage(snap))

    def test_exhausted_5h_with_live_weekly_follows_each_filter(self):
        snap = _snap(_acc(), _win(FIVE_HOUR, 0.0), _win(WEEKLY, 69.0))
        self.assertTrue(account_has_usage(snap))
        self.assertEqual(_visible(snap, hide_unusable=False), [snap.account.key])
        self.assertFalse(account_usable_now(snap))
        self.assertEqual(_visible(snap, hide_unusable=True), [])

    def test_all_applicable_pools_exhausted_are_hidden(self):
        snap = _snap(_acc(), _win(FIVE_HOUR, 0.0), _win(WEEKLY, 0.0))
        self.assertFalse(account_has_usage(snap))
        self.assertFalse(account_usable_now(snap))
        self.assertEqual(_visible(snap), [])

    def test_one_antigravity_pool_exhausted_other_live(self):
        snap = _snap(
            _acc("antigravity", "AG"),
            _win(qualified_key(FIVE_HOUR, "gemini"), 0.0, group="gemini"),
            _win(qualified_key(WEEKLY, "gemini"), 0.0, group="gemini"),
            _win(qualified_key(FIVE_HOUR, "claude_gpt"), 43.0,
                 group="claude_gpt"),
            _win(qualified_key(WEEKLY, "claude_gpt"), 78.0,
                 group="claude_gpt"),
        )
        self.assertTrue(account_has_usage(snap))
        self.assertTrue(account_usable_now(snap))
        self.assertEqual(_visible(snap), [snap.account.key])

    def test_wallet_capacity_survives_exhausted_meter(self):
        snap = _snap(_acc("freebuff", "FB"), _win(FIVE_HOUR, 0.0),
                     _win(WEEKLY, 0.0), metadata={"wallet_balance": 30.0})
        self.assertTrue(account_has_usage(snap))
        self.assertTrue(account_usable_now(snap))
        self.assertEqual(_visible(snap), [snap.account.key])

    def test_effective_one_percent_floor_is_not_spendable(self):
        snap = _snap(_acc(), _win(FIVE_HOUR, 1.0), _win(WEEKLY, 1.0))
        self.assertFalse(account_has_usage(snap))
        self.assertFalse(account_usable_now(snap))

    def test_reset_pending_is_not_invented_as_replenished(self):
        snap = _snap(_acc(), _win(FIVE_HOUR, None, available=False,
                                  reset_pending=True),
                     _win(WEEKLY, None, available=False, reset_pending=True))
        self.assertFalse(account_has_usage(snap))
        self.assertFalse(account_usable_now(snap))

    def test_filter_combinations_and_explicit_hide(self):
        live = _snap(_acc("codex", "Live"), _win(FIVE_HOUR, 100.0),
                     _win(WEEKLY, 100.0))
        service = SimpleNamespace(state_copy=SimpleNamespace(
            accounts=[live.account], snapshots={live.account.key: live}))
        base = {"limit_gauges_hidden_accounts": []}
        for hide_zero, hide_unusable in ((False, False), (False, True),
                                         (True, False), (True, True)):
            data = dict(base, limit_gauges_hide_zero_usage=str(hide_zero))
            shown = visible_quota_accounts(data, service, hide_unusable)
            self.assertEqual([a.key for a in shown], [live.account.key])
        data = dict(base, limit_gauges_hide_zero_usage="False",
                    limit_gauges_hidden_accounts=[live.account.key])
        self.assertEqual(visible_quota_accounts(data, service, False), [])

    def test_diagnostic_status_keeps_visibility_without_claiming_usable(self):
        snap = _snap(_acc("antigravity", "Offline"), status=AUTH_REQUIRED)
        self.assertFalse(account_has_usage(snap))
        self.assertFalse(account_usable_now(snap))
        self.assertEqual(_visible(snap), [snap.account.key])


if __name__ == "__main__":
    unittest.main()
