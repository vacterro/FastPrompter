"""Weekly-reset false-positive audit (user evidence: reset toast at ~60%).

The old detector announced a "reset" for ANY upward jump > 1.0% — so a
Claude weekly reading of 20% -> 60% (a correction/refill, observed in the
field) fired the reset toast. RESET is a semantic event: only a CONFIRMED
near-full refill may notify. These tests pin the classifier and the
notification policy.
"""

import time

from fastprompter.core.usage_limits.model import (
    FIVE_HOUR,
    OK,
    WEEKLY,
    UsageSnapshot,
    UsageWindow,
)
from fastprompter.core.usage_limits.model import (
    AccountRef as AR,
)
from fastprompter.core.usage_limits.notifications import (
    CONFIRMED_REFILL_FRACTION,
    _classify_recovery,
    evaluate_limit_notifications,
    notification_key,
)


def _account(provider_id="claude", stable="w1", name="Claude 1"):
    return AR(provider_id=provider_id, stable_id=stable,
              display_name=name, source_kind="test")


def _snapshot(account, remaining, key=WEEKLY, reset=None, status=OK):
    if reset is None:
        reset = time.time() + 86400
    window = UsageWindow(key, 10080 if key == WEEKLY else 300,
                         True, 100 - remaining, remaining, reset)
    return UsageSnapshot(account=account, status=status,
                         windows=[window], fetched_at=time.time())


def _rule(key):
    return {key: {"enabled": "True", "threshold": 20,
                  "reset_enabled": "True",
                  "reset_show_notification": "True"}}


def _kinds(alerts):
    return [a.kind for a in alerts]


# ---------------------------------------------------------------- classifier

class TestRecoveryClassifier:
    def test_near_full_is_reset(self):
        window = UsageWindow(WEEKLY, 10080, True, 5, 95, time.time() + 86400)
        assert _classify_recovery(20.0, window) == "reset"

    def test_full_is_reset(self):
        window = UsageWindow(WEEKLY, 10080, True, 0, 100, time.time() + 86400)
        assert _classify_recovery(20.0, window) == "reset"

    def test_sixty_percent_is_partial_not_reset(self):
        window = UsageWindow(WEEKLY, 10080, True, 40, 60, time.time() + 86400)
        assert _classify_recovery(20.0, window) == "partial"

    def test_unknown_percentage_is_reconciliation(self):
        window = UsageWindow(WEEKLY, 10080, False, None, None, None)
        assert _classify_recovery(20.0, window) == "reconciliation"

    def test_threshold_is_documented_constant(self):
        assert 0.85 <= CONFIRMED_REFILL_FRACTION <= 0.97


# ------------------------------------------------------- spec cases A-G

class TestSpecCases:
    KEY = property(lambda self: None)  # unused; keys are per-test

    def _eval(self, account, snap, rules, state, **kw):
        return evaluate_limit_notifications(
            [account], {account.key: snap}, rules, state, **kw)

    def test_a_20_to_100_is_a_reset(self):
        acc = _account()
        key = notification_key(acc.key, WEEKLY)
        _acc, state = self._eval(acc, _snapshot(acc, 20), _rule(key), {})
        alerts, _state = self._eval(acc, _snapshot(acc, 100), _rule(key), state)
        assert _kinds(alerts) == ["reset"]

    def test_b_20_to_97_is_a_reset_candidate(self):
        acc = _account()
        key = notification_key(acc.key, WEEKLY)
        _acc, state = self._eval(acc, _snapshot(acc, 20), _rule(key), {})
        alerts, _state = self._eval(acc, _snapshot(acc, 97), _rule(key), state)
        assert _kinds(alerts) == ["reset"]

    def test_c_20_to_60_is_NEVER_a_reset(self):
        acc = _account()
        key = notification_key(acc.key, WEEKLY)
        _acc, state = self._eval(acc, _snapshot(acc, 20), _rule(key), {})
        alerts, _state = self._eval(acc, _snapshot(acc, 60), _rule(key), state)
        assert alerts == []

    def test_d_first_observation_of_100_is_not_a_reset(self):
        acc = _account()
        key = notification_key(acc.key, WEEKLY)
        alerts, _state = self._eval(acc, _snapshot(acc, 100), _rule(key), {})
        assert alerts == []

    def test_e_elapsed_epoch_makes_the_prior_invalid_not_a_reset(self):
        # previous = 70% but its window's reset time already elapsed: under
        # resolved_windows that observation becomes reset_pending/unavailable,
        # i.e. NO valid previous state. The fresh near-full sample is then an
        # initial observation (case-D semantics), not a confirmed reset.
        acc = _account()
        key = notification_key(acc.key, WEEKLY)
        rules = _rule(key)
        stale_reset = time.time() - 600
        _acc, state = self._eval(
            acc, _snapshot(acc, 0, reset=stale_reset), rules, {})
        assert state == {}   # the elapsed window is skipped entirely
        alerts, _state = self._eval(
            acc, _snapshot(acc, 100), rules, state)
        assert alerts == []

    def test_f_5_to_60_after_reconnect_is_not_a_reset(self):
        acc = _account()
        key = notification_key(acc.key, WEEKLY)
        _acc, state = self._eval(acc, _snapshot(acc, 5), _rule(key), {})
        alerts, _state = self._eval(acc, _snapshot(acc, 60), _rule(key), state)
        assert alerts == []

    def test_g_timestamp_change_with_partial_value_is_not_a_reset(self):
        # The provider rolls resets_at forward on a partially consumed window:
        # epoch evidence alone must not confirm a reset below near-full.
        acc = _account()
        key = notification_key(acc.key, WEEKLY)
        _acc, state = self._eval(acc, _snapshot(acc, 5), _rule(key), {})
        later = time.time() + 2 * 86400
        alerts, _state = self._eval(
            acc, _snapshot(acc, 60, reset=later), _rule(key), state)
        assert alerts == []


# ------------------------------------------------------------- policy

class TestNotificationPolicy:
    def test_claude_weekly_20_to_60_silent_then_recover(self):
        acc = _account()
        key = notification_key(acc.key, WEEKLY)
        rules = _rule(key)
        _acc, state = evaluate_limit_notifications(
            [acc], {acc.key: _snapshot(acc, 20)}, rules, {})
        # partial refill: silent, and NOT latched — the climb may still
        # confirm at near full later without being suppressed
        alerts, state = evaluate_limit_notifications(
            [acc], {acc.key: _snapshot(acc, 60)}, rules, state)
        assert alerts == []
        assert "reset_alerted" not in state[key]
        # repeated polls in the same episode stay silent
        alerts, state = evaluate_limit_notifications(
            [acc], {acc.key: _snapshot(acc, 65)}, rules, state)
        assert alerts == []
        # a genuine drop re-arms...
        alerts, state = evaluate_limit_notifications(
            [acc], {acc.key: _snapshot(acc, 10)}, rules, state)
        assert _kinds(alerts) == ["low"]
        assert "reset_alerted" not in state[key]
        # ...and a later CONFIRMED reset notifies exactly once
        alerts, state = evaluate_limit_notifications(
            [acc], {acc.key: _snapshot(acc, 100)}, rules, state)
        assert _kinds(alerts) == ["reset"]
        alerts, _state = evaluate_limit_notifications(
            [acc], {acc.key: _snapshot(acc, 100)}, rules, state)
        assert alerts == []

    def test_gradual_recovery_to_60_emits_nothing(self):
        acc = _account()
        key = notification_key(acc.key, WEEKLY)
        rules = _rule(key)
        state = {}
        reset_alerts = 0
        for pct in (5, 20, 40, 55, 60):
            alerts, state = evaluate_limit_notifications(
                [acc], {acc.key: _snapshot(acc, pct)}, rules, state)
            reset_alerts += sum(1 for a in alerts if a.kind == "reset")
        assert reset_alerts == 0

    def test_startup_first_sample_does_not_emit_reset(self):
        acc = _account()
        key = notification_key(acc.key, WEEKLY)
        old_state = {key: {"remaining": 10.0}}
        alerts, state = evaluate_limit_notifications(
            [acc], {acc.key: _snapshot(acc, 100)}, _rule(key),
            old_state, is_initial_poll=True)
        assert alerts == []
        assert state[key]["reset_alerted"] is True

    def test_stale_snapshot_never_fires(self):
        from fastprompter.core.usage_limits.model import STALE
        acc = _account()
        key = notification_key(acc.key, WEEKLY)
        prior = {key: {"remaining": 10.0}}
        alerts, _state = evaluate_limit_notifications(
            [acc], {acc.key: _snapshot(acc, 100, status=STALE)},
            _rule(key), prior)
        assert alerts == []
        assert _state == prior

    def test_missing_then_recovered_value_does_not_manufacture_a_reset(self):
        # 10% -> missing (window drops out) -> 60%: the gap must not erase
        # enough history to promote a partial refill into a reset.
        acc = _account()
        key = notification_key(acc.key, WEEKLY)
        rules = _rule(key)
        _acc, state = evaluate_limit_notifications(
            [acc], {acc.key: _snapshot(acc, 10)}, rules, {})
        empty = UsageSnapshot(account=acc, status=OK, windows=[],
                              fetched_at=time.time())
        alerts, state = evaluate_limit_notifications(
            [acc], {acc.key: empty}, rules, state)
        assert alerts == []
        assert state[key]["remaining"] == 10.0   # history survives the gap
        alerts, _state = evaluate_limit_notifications(
            [acc], {acc.key: _snapshot(acc, 60)}, rules, state)
        assert alerts == []

    def test_near_full_jitter_does_not_rearm_the_announcement(self):
        # 100 -> 98 -> 100 inside the same confirmed epoch: the 1% jitter dip
        # must not re-arm and re-announce the reset.
        acc = _account()
        key = notification_key(acc.key, WEEKLY)
        rules = _rule(key)
        _acc, state = evaluate_limit_notifications(
            [acc], {acc.key: _snapshot(acc, 5)}, rules, {})
        alerts, state = evaluate_limit_notifications(
            [acc], {acc.key: _snapshot(acc, 100)}, rules, state)
        assert _kinds(alerts) == ["reset"]
        alerts, state = evaluate_limit_notifications(
            [acc], {acc.key: _snapshot(acc, 98)}, rules, state)
        assert alerts == []
        alerts, _state = evaluate_limit_notifications(
            [acc], {acc.key: _snapshot(acc, 100)}, rules, state)
        assert alerts == []

    def test_five_hour_provider_semantics_unchanged(self):
        # The classifier is generic, but a full 5h refill still confirms.
        acc = _account(provider_id="codex", stable="fh", name="Codex")
        key = notification_key(acc.key, FIVE_HOUR)
        rules = _rule(key)
        _acc, state = evaluate_limit_notifications(
            [acc], {acc.key: _snapshot(acc, 5, key=FIVE_HOUR)}, rules, {})
        alerts, _state = evaluate_limit_notifications(
            [acc], {acc.key: _snapshot(acc, 100, key=FIVE_HOUR)},
            rules, state)
        assert _kinds(alerts) == ["reset"]

    def test_low_alert_contract_unchanged_by_classifier(self):
        # A threshold breach fires the low alert exactly as before; the
        # classifier only gates the RESET kind.
        acc = _account()
        key = notification_key(acc.key, WEEKLY)
        rules = {key: {"enabled": "True", "threshold": 20}}
        alerts, _state = evaluate_limit_notifications(
            [acc], {acc.key: _snapshot(acc, 10)}, rules, {})
        assert _kinds(alerts) == ["low"]
