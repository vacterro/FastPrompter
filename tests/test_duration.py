"""Tests for fastprompter.core.duration — human duration/time parsing."""

import datetime
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

from fastprompter.core.duration import (  # noqa: E402
    PRESETS,
    format_remaining,
    parse_duration,
    parse_when,
    resolve_target,
)

HOUR = 3600
DAY = 24 * HOUR


def secs(text):
    d = parse_duration(text)
    return None if d is None else int(d.total_seconds())


class TestParseDuration:
    def test_the_headline_case(self):
        assert secs("4 days 11 hours") == 4 * DAY + 11 * HOUR
        assert secs("4d 11h") == 4 * DAY + 11 * HOUR
        assert secs("4d11h") == 4 * DAY + 11 * HOUR

    def test_single_units(self):
        assert secs("30m") == 1800
        assert secs("30 minutes") == 1800
        assert secs("2h") == 2 * HOUR
        assert secs("1 week") == 7 * DAY
        assert secs("90s") == 90

    def test_separators_and_filler_words(self):
        assert secs("1d, 2h") == DAY + 2 * HOUR
        assert secs("1d and 2h") == DAY + 2 * HOUR
        assert secs("1d + 2h") == DAY + 2 * HOUR

    def test_fractional(self):
        assert secs("1.5h") == 5400
        assert secs("1,5h") == 5400

    def test_bare_number_means_minutes(self):
        assert secs("45") == 45 * 60
        assert secs("1h 30") == HOUR + 30 * 60

    def test_hm_shorthand(self):
        assert secs("1h30") == HOUR + 30 * 60
        assert secs("2h05") == 2 * HOUR + 5 * 60

    def test_russian(self):
        assert secs("4 дня 11 часов") == 4 * DAY + 11 * HOUR
        assert secs("45 мин") == 45 * 60
        assert secs("2 недели") == 14 * DAY
        assert secs("3 ч") == 3 * HOUR

    def test_case_and_spacing_insensitive(self):
        assert secs("4 DAYS 11 HOURS") == 4 * DAY + 11 * HOUR
        assert secs("  2h   30m  ") == 2 * HOUR + 30 * 60

    def test_refuses_garbage_instead_of_guessing(self):
        # a timer that silently fires at the wrong time is worse than none
        for bad in ("", "   ", "soon", "later today", "4 blah", "abc",
                    "4 days blah 2h", "4 5", "-3h", "0", "0m"):
            assert parse_duration(bad) is None, f"should refuse: {bad!r}"

    def test_refuses_absurd_lengths(self):
        assert parse_duration("500 days") is None
        assert parse_duration("10 weeks") is not None


class TestParseWhen:
    def setup_method(self):
        self.now = datetime.datetime(2026, 7, 21, 10, 0, 0)

    def test_clock_time_later_today(self):
        t = parse_when("18:30", self.now)
        assert (t.hour, t.minute, t.day) == (18, 30, 21)

    def test_time_already_passed_means_tomorrow(self):
        t = parse_when("09:00", self.now)
        assert (t.hour, t.day) == (9, 22)

    def test_explicit_tomorrow(self):
        t = parse_when("tomorrow 9:00", self.now)
        assert (t.hour, t.day) == (9, 22)
        t = parse_when("завтра 09:00", self.now)
        assert (t.hour, t.day) == (9, 22)

    def test_rejects_non_times(self):
        assert parse_when("4 days", self.now) is None
        assert parse_when("25:00", self.now) is None
        assert parse_when("10:99", self.now) is None


class TestResolveTarget:
    def test_prefers_absolute_then_falls_back_to_duration(self):
        now = datetime.datetime(2026, 7, 21, 10, 0, 0)
        assert resolve_target("18:30", now).hour == 18
        assert resolve_target("2h", now) == now + datetime.timedelta(hours=2)
        assert resolve_target("nonsense", now) is None


class TestFormatRemaining:
    def test_scales_the_unit_to_what_is_left(self):
        assert format_remaining(4 * DAY + 11 * HOUR) == "4d 11h"
        assert format_remaining(2 * HOUR + 5 * 60) == "2h 05m"
        assert format_remaining(90) == "1m 30s"
        assert format_remaining(45) == "45s"
        assert format_remaining(0) == "now"
        assert format_remaining(-5) == "now"

    def test_short_form(self):
        assert format_remaining(4 * DAY + 11 * HOUR, short=True) == "4d"
        assert format_remaining(2 * HOUR + 5 * 60, short=True) == "2h"


class TestPresets:
    def test_every_preset_actually_parses(self):
        for label, value in PRESETS:
            assert parse_duration(value) is not None, f"{label!r} -> {value!r}"
