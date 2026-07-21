"""Tests for fastprompter.core.timers — the limit-reset timer model."""

import datetime
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

from fastprompter.core import timers  # noqa: E402
from fastprompter.core.timers import (  # noqa: E402
    COLOR_STATIC,
    COLOR_TEMPERATURE,
    REPEAT_DAILY,
    REPEAT_NONE,
    REPEAT_WEEKLY,
    Timer,
    collect_due,
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
