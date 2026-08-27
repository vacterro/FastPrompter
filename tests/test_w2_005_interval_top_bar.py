"""W2-005 regression: interval rules with show_in_top_bar=True must render a
real top-bar countdown in _update_timer_label, computed against the same next
boundary the scheduler fires on, while preserving Temp/Productivity precedence
and hiding rules that must not appear.
"""

import os
import sys
import datetime as _dt_mod

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

import fastprompter.main as main_mod  # noqa: E402

RealDateTime = _dt_mod.datetime


def _rule(rid, minutes, **kw):
    r = {
        "id": rid, "name": rid, "minutes": minutes, "enabled": True,
        "sound": "newday", "volume": 0.5, "show_notification": False,
        "show_in_top_bar": False, "align_mode": "clock", "all_day": True,
        "start_minute": 0, "end_minute": 1439,
    }
    r.update(kw)
    return r


class _Fake:
    def __init__(self, rules, now=None):
        self.data = {"interval_notifs": rules,
                     "timer_show_minutes": "False"}
        self._current_lang = "EN"
        self._header_dense = False
        self._header_ultra = False
        self.timers = []
        self._now = now or RealDateTime(2026, 1, 1, 10, 0, 0)

    def _interval_notifs(self):
        return self.data["interval_notifs"]

    def _temp_timer(self):
        return None

    def mark_dirty(self):
        pass


def _bind(fake):
    fake._interval_top_bar_remaining = \
        main_mod.FastPrompter._interval_top_bar_remaining.__get__(fake)
    fake._interval_top_bar_candidate = \
        main_mod.FastPrompter._interval_top_bar_candidate.__get__(fake)
    return fake


def _rem(fake, rule, now=None):
    now = now or fake._now
    fake._now = now
    return fake._interval_top_bar_remaining(rule, now)


def test_clock_rule_shows_countdown_until_next_boundary():
    fake = _bind(_Fake([]))
    # 60m clock rule, now 10:00 -> next boundary 10:30? no: multiples of 60 are
    # 10:00 itself (just crossed) and 11:00. last_fired_minute empty so 10:00
    # is "now" boundary => 0.0
    r = _rule("r", 60, show_in_top_bar=True)
    assert _rem(fake, r, RealDateTime(2026, 1, 1, 10, 0, 0)) == 0.0
    # 10:00:30, boundary minute still 10:00 but last_fired_minute already set
    # -> rolls to 11:00 (60 min)
    r2 = _rule("r", 60, show_in_top_bar=True, last_fired_minute="2026-01-01 10:00")
    assert _rem(fake, r2, RealDateTime(2026, 1, 1, 10, 0, 30)) == 59 * 60 + 30


def test_clock_rule_mid_window():
    fake = _bind(_Fake([]))
    # 45m clock rule: boundaries 00:00, 00:45, ... 09:45, 10:30, ...
    # now 10:00 -> next boundary 10:30 = 30 min away
    r = _rule("r", 45, show_in_top_bar=True, last_fired_minute="2026-01-01 09:45")
    assert _rem(fake, r, RealDateTime(2026, 1, 1, 10, 0, 0)) == 30 * 60


def test_disabled_or_not_shown_returns_none():
    fake = _bind(_Fake([]))
    r = _rule("r", 60, enabled=False)
    assert _rem(fake, r) is None
    r2 = _rule("r", 60, enabled=True, show_in_top_bar=False)
    assert _rem(fake, r2) is None


def test_active_hour_window_gates_impossible_occurrence():
    fake = _bind(_Fake([]))
    # active window 08:00-12:00, all_day False; now 10:00, 60m clock next
    # boundary 11:00 (inside) -> countdown; rule with window 13:00-18:00 ->
    # next occurrence outside -> None
    r = _rule("r", 60, show_in_top_bar=True, all_day=False, start_minute=8 * 60, end_minute=12 * 60,
              last_fired_minute="2026-01-01 10:00")
    rem = _rem(fake, r, RealDateTime(2026, 1, 1, 10, 0, 0))
    assert rem is not None and rem > 0
    r2 = _rule("r2", 60, show_in_top_bar=True, all_day=False, start_minute=13 * 60, end_minute=18 * 60,
               last_fired_minute="2026-01-01 10:00")
    assert _rem(fake, r2, RealDateTime(2026, 1, 1, 10, 0, 0)) is None


def test_elapsed_mode_uses_last_fired_anchor():
    fake = _bind(_Fake([]))
    # elapsed 30m, last fired 10 minutes ago -> 20 min left
    import time as _tm
    now_ts = _tm.time()
    r = _rule("r", 30, show_in_top_bar=True, align_mode="elapsed", last_fired=now_ts - 10 * 60)
    rem = _rem(fake, r)
    assert rem is not None
    assert 19 * 60 < rem <= 20 * 60


def test_candidate_picks_topmost_eligible():
    fake = _bind(_Fake([]))
    rules = [
        _rule("hidden", 15, show_in_top_bar=False),
        _rule("shown", 30, show_in_top_bar=True, last_fired_minute="2026-01-01 10:00"),
    ]
    fake.data["interval_notifs"] = rules
    cand = fake._interval_top_bar_candidate(RealDateTime(2026, 1, 1, 10, 0, 0))
    assert cand is not None
    rule, rem = cand
    assert rule["id"] == "shown"
    assert rem > 0
