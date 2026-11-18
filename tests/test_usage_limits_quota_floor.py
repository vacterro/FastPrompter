"""Quota 1% exhaustion normalization (SAIHANDOFF quota handoff).

A trusted reading that ROUNDS to 1% remaining is treated as 0% for
availability, gating, alerts and display alike — the same effective-quota
policy SAITULS (``Limits.Pct``) and LIMISAW
(``Model.NormalizeRemainingPercent``) already implement. One point is inside
the reading's own noise, and a vendor quoting 1% has practically nothing left,
so account selection, automatic routing and keepalive must not read it as
permission to spend.

The policy is applied once, on the resolved copy in ``resolved_windows``, so
display, gating, sorting and the lowest-remaining pick all agree. Raw provider
telemetry is never mutated; UNKNOWN stays UNKNOWN and is never invented as 0.
"""

from __future__ import annotations

from fastprompter.core.usage_limits.model import (
    FIVE_HOUR,
    OK,
    WEEKLY,
    AccountRef,
    UsageSnapshot,
    UsageWindow,
    effective_remaining_percent,
    exhausted_key,
    resolved_windows,
    window_usable,
)


def _account(provider="claude", stable="cl1"):
    return AccountRef(provider_id=provider, stable_id=stable,
                      display_name="CL1", source_kind="auto_default")


def _win(key, minutes, remaining, group="", label=""):
    return UsageWindow(key=key, duration_minutes=minutes, available=True,
                       used_percent=100.0 - float(remaining),
                       remaining_percent=float(remaining), resets_at_epoch=None,
                       group=group, group_label=label)


def _resolved_one(remaining):
    return resolved_windows([_win(WEEKLY, 10080, remaining)])[0]


# ---- the boundary itself ---------------------------------------------------

def test_raw_0_stays_0():
    w = _resolved_one(0)
    assert w.remaining_percent == 0.0
    assert w.used_percent == 100.0


def test_raw_1_reads_as_0():
    """RED control: before the fix a raw 1% stayed 1 and counted as usable."""
    w = _resolved_one(1)
    assert w.remaining_percent == 0.0
    assert w.used_percent == 100.0
    assert exhausted_key(_win(WEEKLY, 10080, 1)) is True
    assert window_usable(_win(WEEKLY, 10080, 1)) is False


def test_raw_2_is_untouched():
    w = _resolved_one(2)
    assert w.remaining_percent == 2.0
    assert window_usable(_win(WEEKLY, 10080, 2)) is True


def test_raw_100_is_untouched():
    w = _resolved_one(100)
    assert w.remaining_percent == 100.0


def test_fraction_rounds_before_the_floor():
    # 1.2 rounds to 1 -> floored to 0; 1.6 rounds to 2 -> kept as-is (the
    # policy zeroes the <=1 band, it never rounds the stored reading).
    assert _resolved_one(1.2).remaining_percent == 0.0
    assert _resolved_one(1.6).remaining_percent == 1.6


def test_display_equals_gating():
    for rem in (0.0, 1.0, 2.0, 50.0, 100.0):
        w = _win(WEEKLY, 10080, rem)
        shown = int(round(effective_remaining_percent(w)))
        usable = window_usable(w)
        assert usable == (shown > 0), f"display/gating disagree at {rem}%"


# ---- UNKNOWN is never invented as 0 ---------------------------------------

def test_missing_percentage_stays_none():
    w = UsageWindow(key=WEEKLY, duration_minutes=10080, available=True,
                    used_percent=None, remaining_percent=None)
    assert effective_remaining_percent(w) is None
    assert resolved_windows([w])[0].remaining_percent is None
    assert exhausted_key(w) is False
    assert window_usable(w) is False


def test_unavailable_window_is_not_floored_to_zero():
    w = UsageWindow.unavailable(WEEKLY)
    r = resolved_windows([w])[0]
    assert r.remaining_percent is None
    assert r.available is False


# ---- pool isolation and gating --------------------------------------------

def test_claude_five_hour_80_weekly_1_is_ineligible():
    five = _win(FIVE_HOUR, 300, 80)
    week = _win(WEEKLY, 10080, 1)
    out = resolved_windows([five, week])
    by_key = {w.key: w for w in out}
    assert by_key[WEEKLY].remaining_percent == 0.0        # 1% -> 0
    assert by_key[FIVE_HOUR].remaining_percent == 0.0     # gated by dead weekly
    assert by_key[FIVE_HOUR].gated_by == WEEKLY


def test_weekly_1_gates_the_five_hour_sibling():
    five = _win(FIVE_HOUR, 300, 80)
    week = _win(WEEKLY, 10080, 1)
    out = resolved_windows([five, week])
    assert not window_usable(next(w for w in out if w.key == FIVE_HOUR))


def test_two_independent_pools_stay_independent():
    """Antigravity bills Gemini and Claude/GPT pools separately: one pool at
    1% must not zero the other."""
    gemini_5h = _win(FIVE_HOUR, 300, 90, group="gemini", label="Gemini")
    gemini_week = _win(WEEKLY, 10080, 1, group="gemini", label="Gemini")
    cg_5h = _win(FIVE_HOUR, 300, 90, group="claude", label="Claude & GPT")
    cg_week = _win(WEEKLY, 10080, 90, group="claude", label="Claude & GPT")
    out = {w.key + w.group: w for w in resolved_windows(
        [gemini_5h, gemini_week, cg_5h, cg_week])}
    assert out[FIVE_HOUR + "gemini"].remaining_percent == 0.0   # gated
    assert out[FIVE_HOUR + "claude"].remaining_percent == 90.0  # untouched


# ---- cache / account level -------------------------------------------------

def test_cached_snapshot_with_1_reads_as_0():
    snap = UsageSnapshot(account=_account(), status=OK,
                         windows=[_win(WEEKLY, 10080, 1)])
    assert resolved_windows(snap.windows)[0].remaining_percent == 0.0


def test_used_mode_0_left_is_100_used():
    w = _resolved_one(1)
    assert 100.0 - w.remaining_percent == 100.0


def test_reset_alone_does_not_invent_quota():
    import time as _t
    w = UsageWindow(key=WEEKLY, duration_minutes=10080, available=True,
                    used_percent=99.0, remaining_percent=1.0,
                    resets_at_epoch=_t.time() - 10)
    r = resolved_windows([w])[0]
    # An elapsed reset leaves the window pending, never a fabricated 100%.
    assert r.remaining_percent is None
    assert r.reset_pending is True


def test_fresh_post_reset_reading_reopens_the_pool():
    w = _win(WEEKLY, 10080, 50)
    r = resolved_windows([w])[0]
    assert r.remaining_percent == 50.0
    assert window_usable(r) is True


# ---- RED control -----------------------------------------------------------

def test_floor_disabled_restores_the_defect(monkeypatch):
    """Disabling the policy reproduces the pre-fix behaviour: a raw 1% is
    painted 1% and counts as usable. This is the in-suite proof that the
    repair (not the fixture) is what makes the boundary tests pass."""
    import fastprompter.core.usage_limits.model as m
    monkeypatch.setattr(m, "_EFFECTIVE_FLOOR_PCT", 0.0)
    w = _win(WEEKLY, 10080, 1)
    assert m.window_usable(w) is True                 # usable again
    assert m.exhausted_key(w) is False
    assert resolved_windows([w])[0].remaining_percent == 1.0  # paints 1%
    monkeypatch.undo()
    assert window_usable(w) is False                  # fix restored
    assert resolved_windows([w])[0].remaining_percent == 0.0

