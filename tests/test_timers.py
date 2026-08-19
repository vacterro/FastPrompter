"""Tests for fastprompter.core.timers — the limit-reset timer model."""

import datetime
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

from fastprompter.core import timers  # noqa: E402
from fastprompter.core.timers import (  # noqa: E402
    COLOR_STATIC,
    COLOR_TEMPERATURE,
    MAX_TIMER_SOUND_RULES,
    REPEAT_DAILY,
    REPEAT_NONE,
    REPEAT_WEEKLY,
    SOUND_MODE_POOL,
    Timer,
    choose_timer_sound,
    collect_due,
    eligible_sound_rules,
    load_timers,
    next_due,
    save_timers,
    temperature_color,
)

NOW = datetime.datetime(2026, 7, 21, 12, 0, 0)


def mk(name="t", minutes=60, **kw):
    return Timer(name=name, target=NOW + datetime.timedelta(minutes=minutes), **kw)


class TestRoundTrip:
    def test_survives_save_and_load(self):
        t = mk("Claude limit", 90, repeat=REPEAT_DAILY, volume=7,
               color_mode=COLOR_STATIC, color="#ff8800")
        back = load_timers(save_timers([t]))
        assert len(back) == 1
        b = back[0]
        assert (b.name, b.repeat, b.volume) == ("Claude limit", REPEAT_DAILY, 7)
        assert (b.color_mode, b.color) == (COLOR_STATIC, "#ff8800")
        assert b.target == t.target
        assert b.id == t.id

    def test_corrupt_entries_are_skipped_not_fatal(self):
        good = save_timers([mk()])
        assert load_timers(good + [{"name": "no target"}, None, "junk", 42]) != []
        assert len(load_timers(good + [{"name": "x"}])) == 1
        assert load_timers("not a list") == []
        assert load_timers(None) == []

    def test_bad_volume_is_clamped_not_crashing(self):
        assert Timer("t", NOW, volume=99).volume == 10
        assert Timer("t", NOW, volume=-4).volume == 0
        assert Timer("t", NOW, volume="abc").volume == 5

    def test_blank_name_gets_a_fallback(self):
        assert Timer("   ", NOW).name == "Timer"


class TestDueLogic:
    def test_remaining_and_is_due(self):
        t = mk(minutes=30)
        assert round(t.remaining(NOW)) == 1800
        assert not t.is_due(NOW)
        assert t.is_due(NOW + datetime.timedelta(minutes=31))

    def test_disabled_timers_never_fire(self):
        t = mk(minutes=-10, enabled=False)
        assert not t.is_due(NOW)

    def test_next_due_picks_the_soonest_live_one(self):
        a, b, c = mk("a", 120), mk("b", 30), mk("c", 5, enabled=False)
        assert next_due([a, b, c], NOW).name == "b"
        assert next_due([c], NOW) is None
        assert next_due([], NOW) is None

    def test_one_shot_fires_once(self):
        t = mk(minutes=-1, repeat=REPEAT_NONE)
        assert [x.name for x in collect_due([t], NOW)] == ["t"]
        assert t.fired is True
        assert collect_due([t], NOW) == []          # not again

    def test_repeating_timer_rolls_forward(self):
        t = mk(minutes=-1, repeat=REPEAT_DAILY)
        assert collect_due([t], NOW) != []
        assert t.target > NOW
        assert t.fired is False                      # armed for next time

    def test_long_absence_does_not_fire_once_per_missed_day(self):
        # app closed for a week: a daily timer must land in the future and
        # fire ONCE, not spam a week's worth of alarms
        t = Timer("daily", NOW - datetime.timedelta(days=7), repeat=REPEAT_DAILY)
        fired = collect_due([t], NOW)
        assert len(fired) == 1
        assert t.target > NOW
        assert (t.target - NOW).total_seconds() <= 24 * 3600

    def test_weekly_rolls_by_a_week(self):
        t = Timer("w", NOW - datetime.timedelta(days=1), repeat=REPEAT_WEEKLY)
        collect_due([t], NOW)
        assert t.target > NOW


class TestColour:
    def test_static_mode_never_changes(self):
        t = mk(minutes=1, color_mode=COLOR_STATIC, color="#abcdef")
        assert t.display_color(NOW) == "#abcdef"
        assert t.display_color(NOW + datetime.timedelta(days=5)) == "#abcdef"

    def test_temperature_warms_as_the_deadline_closes(self):
        far = temperature_color(48 * 3600)
        mid = temperature_color(4 * 3600)
        near = temperature_color(60)

        def red(c):
            return int(c[1:3], 16)

        assert red(far) < red(mid) < red(near), (far, mid, near)

    def test_temperature_is_defined_at_every_distance(self):
        for secs in (0, 1, 60, 1800, 7200, 24 * 3600, 10 ** 7, -50):
            c = temperature_color(secs)
            assert c.startswith("#") and len(c) == 7, (secs, c)

    def test_temperature_mode_tracks_remaining_time(self):
        t = mk(minutes=5, color_mode=COLOR_TEMPERATURE)
        hot = t.display_color(NOW)
        cool = t.display_color(NOW - datetime.timedelta(days=3))
        assert hot != cool


class TestSnooze:
    def test_fired_alarm_is_pushed_from_now(self):
        t = Timer("late", NOW - datetime.timedelta(minutes=5))
        t.fired = True
        t.snooze(10, NOW)
        assert t.target == NOW + datetime.timedelta(minutes=10)
        assert t.fired is False and t.enabled is True

    def test_pending_timer_moves_LATER_never_closer(self):
        # snoozing a timer due in 2h must not drag it to 10 minutes away
        t = mk(minutes=120)
        original = t.target
        t.snooze(10, NOW)
        assert t.target == original + datetime.timedelta(minutes=10)
        assert t.target > NOW + datetime.timedelta(minutes=100)

    def test_bad_input_falls_back(self):
        t = mk(minutes=-1)
        t.snooze("abc", NOW)
        assert t.target > NOW
        t2 = mk(minutes=-1)
        t2.snooze(0, NOW)
        assert t2.target > NOW

    def test_summary_includes_description(self):
        assert Timer("N", NOW, description="D").summary() == "N - D"
        assert Timer("N", NOW).summary() == "N"

    def test_description_round_trips(self):
        t = Timer("n", NOW, description="  spaced  ")
        assert t.description == "spaced"
        assert load_timers(save_timers([t]))[0].description == "spaced"

# ---------------------------------------------------------------- interval

def test_interval_repeat_rolls_by_its_own_period():
    now = datetime.datetime(2026, 7, 21, 9, 0, 0)
    t = timers.Timer("limit", now + datetime.timedelta(minutes=5),
                     repeat=timers.REPEAT_INTERVAL, interval_minutes=300)
    t.advance(now + datetime.timedelta(minutes=6))
    assert t.target == now + datetime.timedelta(minutes=305)


def test_interval_never_lands_in_the_past_after_a_long_sleep():
    """The laptop was shut for two days: the timer must name the NEXT window,
    not replay every window that was missed."""
    start = datetime.datetime(2026, 7, 21, 9, 0, 0)
    t = timers.Timer("limit", start, repeat=timers.REPEAT_INTERVAL,
                     interval_minutes=300)
    much_later = start + datetime.timedelta(days=2)
    t.advance(much_later)
    assert t.target > much_later
    # and it is still on the 5-hour grid the anchor established
    assert (t.target - start).total_seconds() % (300 * 60) == 0


def test_interval_period_cannot_be_zero():
    """A zero period would make advance() loop forever."""
    t = timers.Timer("x", datetime.datetime(2026, 7, 21, 9, 0),
                     repeat=timers.REPEAT_INTERVAL, interval_minutes=0)
    assert t.interval_minutes >= 1
    t.advance(datetime.datetime(2026, 7, 21, 10, 0))   # must return at all
    assert t.target > datetime.datetime(2026, 7, 21, 10, 0)


def test_interval_survives_a_save_load_round_trip():
    t = timers.Timer("limit", datetime.datetime(2026, 7, 21, 9, 0),
                     repeat=timers.REPEAT_INTERVAL, interval_minutes=300)
    back = timers.load_timers(timers.save_timers([t]))[0]
    assert back.repeat == timers.REPEAT_INTERVAL
    assert back.interval_minutes == 300


def test_timers_saved_before_intervals_existed_still_load():
    old_entry = {"name": "old", "target": "2026-07-21T09:00:00",
                 "repeat": "daily"}
    back = timers.load_timers([old_entry])[0]
    assert back.interval_minutes == timers.DEFAULT_INTERVAL_MINUTES


# ------------------------------------------------------------ limit window

def test_limit_window_counts_from_the_anchor():
    now = datetime.datetime(2026, 7, 21, 12, 0, 0)
    anchor = datetime.datetime(2026, 7, 21, 11, 30, 0)
    t = timers.limit_window("Claude", hours=5, anchor=anchor, now=now)
    assert t.target == anchor + datetime.timedelta(hours=5)
    assert t.repeat == timers.REPEAT_INTERVAL
    assert t.interval_minutes == 300


def test_limit_window_anchored_in_the_past_rolls_to_the_next_one():
    """'my window opened at 06:00' said at 14:00 must point at the next
    reset, not at one that already passed."""
    now = datetime.datetime(2026, 7, 21, 14, 0, 0)
    anchor = datetime.datetime(2026, 7, 21, 6, 0, 0)
    t = timers.limit_window("Claude", hours=5, anchor=anchor, now=now)
    assert t.target > now
    assert t.target == datetime.datetime(2026, 7, 21, 16, 0, 0)


def test_limit_window_defaults_to_starting_now():
    now = datetime.datetime(2026, 7, 21, 12, 0, 0)
    t = timers.limit_window("x", hours=5, now=now)
    assert t.target == now + datetime.timedelta(hours=5)


def test_describe_spells_out_the_window_in_words():
    now = datetime.datetime(2026, 7, 21, 12, 0, 0)
    t = timers.limit_window("Claude limit", hours=5,
                            anchor=datetime.datetime(2026, 7, 21, 11, 0),
                            now=now)
    text = timers.describe(t, now)
    assert "Claude limit" in text
    assert "16:00" in text, "the actual reset time must be visible"
    assert "in 4h" in text
    assert "every 5h" in text, "a rolling window must say that it rolls"


def test_describe_marks_a_paused_timer():
    now = datetime.datetime(2026, 7, 21, 12, 0, 0)
    t = timers.limit_window("x", hours=5, now=now)
    t.enabled = False
    assert "paused" in timers.describe(t, now)


# ============================================================ T-1004 extension

def test_legacy_timer_migrates_to_safe_defaults():
    """A v0.8.40 timer with no new fields must behave as an alarm that is
    fully visible (notification + top bar) with single sound semantics."""
    old = {"name": "legacy", "target": "2026-07-21T09:00:00", "repeat": "daily"}
    t = timers.load_timers([old])[0]
    assert t.kind == timers.KIND_ALARM
    assert t.show_notification is True
    assert t.show_in_top_bar is True
    assert t.sound_mode == timers.SOUND_MODE_SINGLE
    assert t.sound_rules == []
    assert t.repeat_anchor == "2026-07-21"


def test_new_fields_round_trip():
    t = timers.Timer(
        "ev", datetime.datetime(2026, 1, 31, 8, 30, 0),
        kind=timers.KIND_CALENDAR, repeat=timers.REPEAT_MONTHLY,
        show_notification=False, show_in_top_bar=False,
        repeat_anchor="2026-01-31",
    )
    back = timers.load_timers(timers.save_timers([t]))[0]
    assert back.kind == timers.KIND_CALENDAR
    assert back.show_notification is False
    assert back.show_in_top_bar is False
    assert back.repeat_anchor == "2026-01-31"
    assert back.repeat == timers.REPEAT_MONTHLY


def test_malformed_kind_heals_to_alarm():
    d = {"name": "x", "target": "2026-07-21T09:00:00", "kind": "bogus"}
    t = timers.load_timers([d])[0]
    assert t.kind == timers.KIND_ALARM


def test_malformed_repeat_anchor_heals_from_target():
    d = {"name": "x", "target": "2026-07-21T09:00:00", "repeat_anchor": "nope"}
    t = timers.load_timers([d])[0]
    assert t.repeat_anchor == "2026-07-21"


def test_missing_repeat_anchor_derives_from_target():
    t = timers.Timer("x", datetime.datetime(2026, 2, 15, 12, 0, 0),
                     repeat=timers.REPEAT_MONTHLY)
    assert t.repeat_anchor == "2026-02-15"
    assert timers._anchor_date(t) == datetime.date(2026, 2, 15)


def test_monthly_31st_clamps_and_returns():
    t = timers.Timer("jan31", datetime.datetime(2026, 1, 31, 9, 0, 0),
                     repeat=timers.REPEAT_MONTHLY, repeat_anchor="2026-01-31")
    t.advance(datetime.datetime(2026, 2, 1, 0, 0, 0))
    assert t.target == datetime.datetime(2026, 2, 28, 9, 0, 0)
    t.advance(datetime.datetime(2026, 3, 1, 0, 0, 0))
    # March returns to the 31st, NOT derived from clamped February 28
    assert t.target == datetime.datetime(2026, 3, 31, 9, 0, 0)


def test_monthly_leap_february():
    t = timers.Timer("leap", datetime.datetime(2024, 1, 31, 9, 0, 0),
                     repeat=timers.REPEAT_MONTHLY, repeat_anchor="2024-01-31")
    t.advance(datetime.datetime(2024, 2, 1, 0, 0, 0))
    assert t.target == datetime.datetime(2024, 2, 29, 9, 0, 0)


def test_monthly_aug31_chain():
    t = timers.Timer("aug", datetime.datetime(2026, 8, 31, 9, 0, 0),
                     repeat=timers.REPEAT_MONTHLY, repeat_anchor="2026-08-31")
    t.advance(datetime.datetime(2026, 9, 1, 0, 0, 0))
    assert t.target == datetime.datetime(2026, 9, 30, 9, 0, 0)
    t.advance(datetime.datetime(2026, 10, 1, 0, 0, 0))
    assert t.target == datetime.datetime(2026, 10, 31, 9, 0, 0)


def test_yearly_feb29_clamps_on_non_leap():
    t = timers.Timer("feb29", datetime.datetime(2024, 2, 29, 9, 0, 0),
                     repeat=timers.REPEAT_YEARLY, repeat_anchor="2024-02-29")
    t.advance(datetime.datetime(2025, 1, 1, 0, 0, 0))
    assert t.target == datetime.datetime(2025, 2, 28, 9, 0, 0)
    t.advance(datetime.datetime(2026, 1, 1, 0, 0, 0))
    assert t.target == datetime.datetime(2026, 2, 28, 9, 0, 0)
    t.advance(datetime.datetime(2028, 1, 1, 0, 0, 0))
    assert t.target == datetime.datetime(2028, 2, 29, 9, 0, 0)


def test_advance_future_monthly_target_is_noop():
    """advance() must not skip the next occurrence when already future."""
    t = timers.Timer("m", datetime.datetime(2026, 9, 30, 9, 0, 0),
                     repeat=timers.REPEAT_MONTHLY, repeat_anchor="2026-08-30")
    assert t.advance(datetime.datetime(2026, 8, 18, 0, 0, 0)) is True
    assert t.target == datetime.datetime(2026, 9, 30, 9, 0, 0)
    assert t.fired is False


def test_advance_future_yearly_target_is_noop():
    t = timers.Timer("y", datetime.datetime(2027, 2, 28, 9, 0, 0),
                     repeat=timers.REPEAT_YEARLY, repeat_anchor="2026-02-28")
    assert t.advance(datetime.datetime(2026, 8, 18, 0, 0, 0)) is True
    assert t.target == datetime.datetime(2027, 2, 28, 9, 0, 0)
    assert t.fired is False


def test_advance_past_monthly_lands_next_future_occurrence():
    t = timers.Timer("m", datetime.datetime(2026, 8, 30, 9, 0, 0),
                     repeat=timers.REPEAT_MONTHLY, repeat_anchor="2026-08-30")
    t.advance(datetime.datetime(2026, 9, 5, 0, 0, 0))
    assert t.target == datetime.datetime(2026, 9, 30, 9, 0, 0)


def test_advance_past_yearly_lands_next_future_occurrence():
    t = timers.Timer("y", datetime.datetime(2026, 2, 28, 9, 0, 0),
                     repeat=timers.REPEAT_YEARLY, repeat_anchor="2026-02-28")
    t.advance(datetime.datetime(2026, 8, 18, 0, 0, 0))
    assert t.target == datetime.datetime(2027, 2, 28, 9, 0, 0)


def test_weekly_rolls_by_seven_days():
    t = timers.Timer("w", datetime.datetime(2026, 7, 21, 9, 0, 0),
                     repeat=timers.REPEAT_WEEKLY)
    t.advance(datetime.datetime(2026, 7, 22, 0, 0, 0))
    assert t.target == datetime.datetime(2026, 7, 28, 9, 0, 0)


def test_daily_rolls_by_one_day():
    t = timers.Timer("d", datetime.datetime(2026, 7, 21, 9, 0, 0),
                     repeat=timers.REPEAT_DAILY)
    t.advance(datetime.datetime(2026, 7, 22, 0, 0, 0))
    assert t.target == datetime.datetime(2026, 7, 22, 9, 0, 0)


def test_monthly_closed_multiple_years_lands_future_once():
    t = timers.Timer("m", datetime.datetime(2026, 1, 31, 9, 0, 0),
                     repeat=timers.REPEAT_MONTHLY, repeat_anchor="2026-01-31")
    now = datetime.datetime(2029, 5, 1, 0, 0, 0)
    fired = timers.collect_due([t], now)
    assert len(fired) == 1
    assert t.target > now
    assert t.fired is False


def test_yearly_closed_multiple_years_lands_future_once():
    t = timers.Timer("y", datetime.datetime(2024, 2, 29, 9, 0, 0),
                     repeat=timers.REPEAT_YEARLY, repeat_anchor="2024-02-29")
    now = datetime.datetime(2035, 1, 1, 0, 0, 0)
    fired = timers.collect_due([t], now)
    assert len(fired) == 1
    assert t.target > now


def test_occurrence_helpers_do_not_mutate_timer():
    t = timers.Timer("ev", datetime.datetime(2026, 1, 31, 9, 0, 0),
                     repeat=timers.REPEAT_MONTHLY, repeat_anchor="2026-01-31")
    before = t.target
    # call every helper many times with various dates
    for m in range(1, 13):
        timers.occurrences_in_month(t, 2026, m)
    timers.occurs_on_date(t, datetime.date(2026, 3, 31))
    assert t.target == before


def test_occurs_on_date_rules():
    once = timers.Timer("o", datetime.datetime(2026, 7, 21, 9, 0, 0),
                        repeat=timers.REPEAT_NONE)
    assert timers.occurs_on_date(once, datetime.date(2026, 7, 21))
    assert not timers.occurs_on_date(once, datetime.date(2026, 7, 22))

    daily = timers.Timer("d", datetime.datetime(2026, 7, 21, 9, 0, 0),
                         repeat=timers.REPEAT_DAILY)
    assert timers.occurs_on_date(daily, datetime.date(2026, 8, 5))
    assert not timers.occurs_on_date(daily, datetime.date(2026, 7, 20))

    wk = timers.Timer("w", datetime.datetime(2026, 7, 21, 9, 0, 0),
                      repeat=timers.REPEAT_WEEKLY)
    assert timers.occurs_on_date(wk, datetime.date(2026, 7, 28))
    assert not timers.occurs_on_date(wk, datetime.date(2026, 7, 27))

    mo = timers.Timer("m", datetime.datetime(2026, 1, 31, 9, 0, 0),
                      repeat=timers.REPEAT_MONTHLY, repeat_anchor="2026-01-31")
    assert timers.occurs_on_date(mo, datetime.date(2026, 2, 28))
    assert timers.occurs_on_date(mo, datetime.date(2026, 3, 31))
    assert not timers.occurs_on_date(mo, datetime.date(2026, 2, 27))

    yr = timers.Timer("y", datetime.datetime(2024, 2, 29, 9, 0, 0),
                      repeat=timers.REPEAT_YEARLY, repeat_anchor="2024-02-29")
    assert timers.occurs_on_date(yr, datetime.date(2025, 2, 28))
    assert timers.occurs_on_date(yr, datetime.date(2028, 2, 29))
    assert not timers.occurs_on_date(yr, datetime.date(2025, 2, 27))


def test_occurrences_in_month_bounded_and_correct():
    mo = timers.Timer("m", datetime.datetime(2026, 1, 31, 9, 0, 0),
                      repeat=timers.REPEAT_MONTHLY, repeat_anchor="2026-01-31")
    feb = timers.occurrences_in_month(mo, 2026, 2)
    assert feb == [datetime.date(2026, 2, 28)]
    mar = timers.occurrences_in_month(mo, 2026, 3)
    assert mar == [datetime.date(2026, 3, 31)]

    daily = timers.Timer("d", datetime.datetime(2026, 2, 1, 9, 0, 0),
                         repeat=timers.REPEAT_DAILY)
    feb_d = timers.occurrences_in_month(daily, 2026, 2)
    assert len(feb_d) == 28  # Feb 1..28
    assert datetime.date(2026, 2, 1) in feb_d
    assert datetime.date(2026, 1, 31) not in feb_d  # never before target


def test_new_repeat_choices_are_valid_and_preserved():
    for r in (timers.REPEAT_MONTHLY, timers.REPEAT_YEARLY):
        assert r in timers.REPEAT_CHOICES
        t = timers.Timer("x", datetime.datetime(2026, 1, 1, 9, 0, 0), repeat=r)
        assert t.repeat == r


# ============================================================ T-1005 sound policy

def _pool(rules, sound="tick", volume=5):
    return timers.Timer(
        "pool", datetime.datetime(2026, 7, 21, 12, 0, 0),
        sound_mode=SOUND_MODE_POOL, sound_rules=list(rules), sound=sound,
        volume=volume,
    )


def test_single_mode_returns_own_sound_and_volume():
    t = timers.Timer("s", NOW, sound="notify", volume=8)
    assert choose_timer_sound(t, NOW) == ("notify", 8)


def test_pool_with_no_eligible_rule_is_silent():
    # all-day disabled, window 06:00-12:00, but it is 18:00 -> nothing matches
    t = _pool([{"sound": "tick", "enabled": True, "all_day": False,
                "start_minute": 360, "end_minute": 720}])
    assert eligible_sound_rules(t, datetime.datetime(2026, 7, 21, 18, 0)) == []
    assert choose_timer_sound(t, datetime.datetime(2026, 7, 21, 18, 0)) is None


def test_pool_picks_an_eligible_rule_with_volume_inheritance():
    t = _pool([
        {"sound": "tick", "enabled": True, "all_day": False,
         "start_minute": 360, "end_minute": 720, "volume": None},
    ])
    ref, vol = choose_timer_sound(t, datetime.datetime(2026, 7, 21, 9, 0))
    assert ref == "tick"
    assert vol == 5  # inherited from timer.volume


def test_pool_rule_explicit_volume_overrides_inheritance():
    t = _pool([
        {"sound": "notify", "enabled": True, "all_day": False,
         "start_minute": 360, "end_minute": 720, "volume": 2},
    ])
    ref, vol = choose_timer_sound(t, datetime.datetime(2026, 7, 21, 9, 0))
    assert (ref, vol) == ("notify", 2)


def test_pool_boundaries_start_inclusive_end_exclusive():
    rules = [{"sound": "tick", "enabled": True, "all_day": False,
              "start_minute": 360, "end_minute": 720}]  # 06:00-12:00
    for minute, expect in ((359, False), (360, True), (719, True),
                           (720, False)):
        t = _pool(rules)
        when = NOW.replace(hour=minute // 60, minute=minute % 60)
        got = bool(eligible_sound_rules(t, when))
        assert got == expect, (minute, got, expect)


def test_pool_overnight_window():
    # 22:00 -> 06:00 (1320 -> 360): 22:00 YES, 05:59 YES, 06:00 NO, 21:59 NO
    rules = [{"sound": "tick", "enabled": True, "all_day": False,
              "start_minute": 1320, "end_minute": 360}]
    cases = {
        datetime.datetime(2026, 7, 21, 22, 0): True,
        datetime.datetime(2026, 7, 21, 5, 59): True,
        datetime.datetime(2026, 7, 21, 6, 0): False,
        datetime.datetime(2026, 7, 21, 21, 59): False,
    }
    for when, expect in cases.items():
        t = _pool(rules)
        assert bool(eligible_sound_rules(t, when)) == expect, when


def test_pool_zero_length_window_matches_nothing():
    t = _pool([{"sound": "tick", "enabled": True, "all_day": False,
                "start_minute": 600, "end_minute": 600}])
    assert eligible_sound_rules(t, NOW) == []


def test_pool_overlapping_rows_count_as_separate_candidates():
    t = _pool([
        {"sound": "tick", "enabled": True, "all_day": True, "volume": None},
        {"sound": "tick", "enabled": True, "all_day": True, "volume": None},
    ])
    assert len(eligible_sound_rules(t, NOW)) == 2


def test_pool_disabled_rule_not_eligible():
    t = _pool([{"sound": "tick", "enabled": False, "all_day": True,
                "volume": None}])
    assert eligible_sound_rules(t, NOW) == []


def test_pool_random_pick_is_deterministic_with_seeded_rng():
    import random
    rules = [
        {"sound": "tick", "enabled": True, "all_day": True, "volume": None},
        {"sound": "notify", "enabled": True, "all_day": True, "volume": None},
    ]
    t = _pool(rules)
    rng = random.Random(1234)
    picks = {choose_timer_sound(t, NOW, rng)[0] for _ in range(200)}
    assert picks == {"tick", "notify"}  # both reachable, never crashes


def test_pool_rules_truncated_at_max():
    lots = [{"sound": "tick", "enabled": True, "all_day": True, "volume": None}
            for _ in range(50)]
    t = _pool(lots)
    assert len(t.sound_rules) == MAX_TIMER_SOUND_RULES


def test_malformed_pool_rule_dropped_on_load():
    d = {"name": "x", "target": "2026-07-21T09:00:00",
         "sound_mode": "pool",
         "sound_rules": [{"sound": "tick", "enabled": True, "all_day": True},
                         "garbage", {"enabled": True}]}
    t = timers.load_timers([d])[0]
    assert len(t.sound_rules) == 1
    assert t.sound_rules[0]["sound"] == "tick"


def test_pool_mode_does_not_fall_back_to_single_sound():
    # even when the pool has no eligible rule, never play timer.sound
    t = _pool([], sound="notify", volume=9)
    assert choose_timer_sound(t, NOW) is None


def test_next_due_topbar_only_ignores_hidden_timers():
    hidden = timers.Timer("hidden", NOW - datetime.timedelta(minutes=2),
                          show_in_top_bar=False)
    visible = timers.Timer("visible", NOW + datetime.timedelta(minutes=10),
                           show_in_top_bar=True)
    due = timers.next_due([hidden, visible], NOW, topbar_only=True)
    assert due.name == "visible"   # hidden one still fires, just not shown
    assert timers.next_due([hidden], NOW, topbar_only=True) is None


def test_next_due_default_still_sees_hidden_timers():
    """Scheduler/general use must keep hidden timers visible to next_due."""
    hidden = timers.Timer("hidden", NOW - datetime.timedelta(minutes=2),
                          show_in_top_bar=False)
    visible = timers.Timer("visible", NOW + datetime.timedelta(minutes=10),
                           show_in_top_bar=True)
    due = timers.next_due([hidden, visible], NOW)
    assert due.name == "hidden"   # nearest, hidden or not
    assert timers.next_due([hidden], NOW).name == "hidden"
