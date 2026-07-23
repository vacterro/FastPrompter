"""Tests for fastprompter.core.limits.

Every case is real agent wording, or a near-miss chosen because it would
fool a naive "does it contain the word limit" check. The clock is injected,
so nothing here waits for a reset.
"""

import datetime
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

from fastprompter.core.limits import assume_window, scan_text  # noqa: E402

NOW = datetime.datetime(2026, 7, 22, 14, 30)


# ------------------------------------------------------------------ hits

def test_the_freebuff_wording_reads_as_reached():
    """Verbatim from the app: it names no time, so resets_at stays None."""
    text = ("⚠ Daily free limit reached for deepseek/deepseek-v4-flash. "
            "Come back after the daily reset.")
    state = scan_text(text, NOW)
    assert state.reached is True
    assert state.resets_at is None, "it named no clock time - do not invent one"


def test_a_five_hour_window_with_a_reset_time():
    state = scan_text("5-hour limit reached ∙ resets 3pm", NOW)
    assert state.reached is True
    assert state.resets_at == NOW.replace(hour=15, minute=0)


def test_a_reset_time_already_past_today_rolls_to_tomorrow():
    state = scan_text("limit reached, resets at 9:00", NOW)
    assert state.resets_at == datetime.datetime(2026, 7, 23, 9, 0)


def test_a_24_hour_clock_reset():
    state = scan_text("usage limit reached — available again at 21:05", NOW)
    assert state.resets_at == NOW.replace(hour=21, minute=5)


def test_a_relative_reset():
    state = scan_text("rate limited. try again in 2h 15m", NOW)
    assert state.resets_at == NOW + datetime.timedelta(hours=2, minutes=15)


def test_relative_minutes_only():
    state = scan_text("quota exceeded, try again in 45 minutes", NOW)
    assert state.resets_at == NOW + datetime.timedelta(minutes=45)


def test_out_of_messages_counts():
    assert scan_text("You are out of free messages.", NOW).reached is True


def test_am_pm_noon_and_midnight_are_not_off_by_twelve():
    assert scan_text("limit reached, resets at 12am", NOW).resets_at \
        == datetime.datetime(2026, 7, 23, 0, 0)
    assert scan_text("limit reached, resets at 12pm", NOW).resets_at \
        == datetime.datetime(2026, 7, 23, 12, 0)


# --------------------------------------------------------------- non-hits

def test_the_word_limit_alone_is_not_a_limit():
    """The whole reason the patterns are phrases: a false 'reached' pauses a
    queue that could have kept working."""
    for innocent in (
        "context limit: 200000 tokens",
        "No limit on file size.",
        "Standard rate limits apply to this endpoint.",
        "Read about usage limits in the docs",
        "unlimited messages on this plan",
    ):
        assert scan_text(innocent, NOW).reached is False, innocent


def test_empty_and_none_are_clear():
    assert scan_text("", NOW).reached is False
    assert scan_text(None, NOW).reached is False


def test_a_negation_next_to_the_phrase_disqualifies_it():
    state = scan_text("There is no limit reached warning on this plan.", NOW)
    assert state.reached is False


# ------------------------------------------------------------ transcript

def test_only_the_tail_of_a_transcript_is_read():
    """A chat log keeps every limit message it ever printed. An hour-old one
    must not read as current."""
    old = "Daily limit reached. Come back after the daily reset.\n"
    fresh = "x" * 5000 + "\nall good, working normally\n"
    assert scan_text(old + fresh, NOW).reached is False


def test_a_limit_at_the_very_end_is_seen():
    state = scan_text("y" * 5000 + "\n5-hour limit reached ∙ resets 6pm", NOW)
    assert state.reached is True
    assert state.resets_at == NOW.replace(hour=18, minute=0)


def test_a_bare_in_is_not_a_duration():
    """'try again later, in the meantime read the docs' has no time in it."""
    state = scan_text("rate limited. try again later, in the meantime wait",
                      NOW)
    assert state.reached is True
    assert state.resets_at is None


# ---------------------------------------------------------------- fallback

def test_the_assumed_window_is_the_callers_guess_not_the_scanners():
    """scan_text never invents a time; assume_window is explicit so the UI
    can label it as assumed."""
    assert assume_window(NOW, hours=5) == NOW + datetime.timedelta(hours=5)
    assert assume_window(NOW, hours=24) == NOW + datetime.timedelta(hours=24)


def test_state_carries_what_it_matched_for_the_ui():
    state = scan_text("Daily free limit reached for some-model.", NOW)
    assert "limit" in state.matched.lower()
    assert state.source, "the surrounding words are kept for a tooltip"
