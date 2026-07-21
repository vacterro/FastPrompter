"""Tests for fastprompter.core.pomodoro — the work/break productivity timer."""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

from fastprompter.core import pomodoro  # noqa: E402
from fastprompter.core.pomodoro import (  # noqa: E402
    PHASE_BREAK,
    PHASE_WORK,
    STATE_IDLE,
    STATE_PAUSED,
    STATE_RUNNING,
    ProductivityTimer,
    format_clock,
)


def make(work=60, brk=30, **kw):
    return ProductivityTimer(work_seconds=work, break_seconds=brk, **kw)


# ---------------------------------------------------------------- clock

def test_format_clock_reads_as_a_clock():
    assert format_clock(0) == "00:00"
    assert format_clock(59) == "00:59"
    assert format_clock(90) == "01:30"
    assert format_clock(3600) == "1:00:00"
    assert format_clock(-5) == "00:00", "a negative remainder is still zero"


# --------------------------------------------------------------- basics

def test_a_new_timer_is_idle_on_a_full_work_phase():
    t = make()
    assert t.state == STATE_IDLE
    assert t.phase == PHASE_WORK
    assert t.remaining == 60


def test_an_idle_timer_does_not_count_down():
    t = make()
    assert t.tick(30) == []
    assert t.remaining == 60


def test_toggle_walks_start_pause_resume():
    t = make()
    assert t.toggle() == STATE_RUNNING
    t.tick(10)
    assert t.remaining == 50
    assert t.toggle() == STATE_PAUSED
    t.tick(10)
    assert t.remaining == 50, "a paused timer must not lose time"
    assert t.toggle() == STATE_RUNNING
    t.tick(10)
    assert t.remaining == 40


def test_reset_returns_to_a_stopped_work_phase():
    t = make()
    t.start()
    t.tick(45)
    t.reset()
    assert (t.state, t.phase, t.remaining) == (STATE_IDLE, PHASE_WORK, 60)


# --------------------------------------------------------------- phases

def test_work_hands_off_to_the_break_and_back():
    t = make(work=60, brk=30)
    t.start()
    assert t.tick(60) == [PHASE_WORK]
    assert t.phase == PHASE_BREAK
    assert t.remaining == 30
    assert t.state == STATE_RUNNING
    assert t.completed_cycles == 1

    assert t.tick(30) == [PHASE_BREAK]
    assert t.phase == PHASE_WORK
    assert t.remaining == 60
    assert t.completed_cycles == 1, "a break is not a completed cycle"


def test_without_breaks_it_stops_after_the_work_phase():
    t = make(breaks_enabled=False)
    t.start()
    assert t.tick(60) == [PHASE_WORK]
    assert t.phase == PHASE_WORK
    assert t.state == STATE_PAUSED, "it must wait rather than loop straight on"
    assert t.remaining == 60
    assert t.completed_cycles == 1


def test_skip_phase_jumps_without_waiting():
    t = make()
    t.start()
    t.tick(5)
    assert t.skip_phase() == PHASE_BREAK
    assert t.remaining == 30
    assert t.completed_cycles == 1
    assert t.skip_phase() == PHASE_WORK
    assert t.completed_cycles == 1, "skipping a break completes no cycle"


# ----------------------------------------------------------- the clock

def test_time_is_taken_from_the_clock_not_from_tick_counts():
    """If the app stalls for ten seconds the timer must have lost ten
    seconds, not one."""
    t = make()
    t.start()
    t.tick(10)
    assert t.remaining == 50


def test_one_long_stall_can_cross_several_phases():
    t = make(work=60, brk=30)
    t.start()
    ended = t.tick(150)          # work + break + work
    assert ended == [PHASE_WORK, PHASE_BREAK, PHASE_WORK]
    assert t.phase == PHASE_BREAK
    assert t.completed_cycles == 2


def test_a_stall_leaves_the_remainder_exact():
    t = make(work=60, brk=30)
    t.start()
    t.tick(70)                   # 60 work + 10 into the break
    assert t.phase == PHASE_BREAK
    assert t.remaining == 20


def test_nonsense_elapsed_values_are_ignored():
    t = make()
    t.start()
    for bad in (None, "soon", -5, 0):
        assert t.tick(bad) == []
    assert t.remaining == 60


# ---------------------------------------------------------------- alarm

def test_the_alarm_stays_pending_until_acknowledged():
    """Someone away from the desk should still find it ringing."""
    t = make()
    t.start()
    t.tick(60)
    assert t.alarm_pending is True
    t.tick(5)
    assert t.alarm_pending is True
    assert t.acknowledge() is True
    assert t.alarm_pending is False
    assert t.acknowledge() is False


def test_starting_acknowledges_a_ringing_alarm():
    t = make()
    t.start()
    t.tick(60)
    assert t.alarm_pending is True
    t.start()
    assert t.alarm_pending is False


def test_repeat_alarm_off_never_leaves_one_ringing():
    t = make(repeat_alarm=False)
    t.start()
    t.tick(60)
    assert t.alarm_pending is False


# ------------------------------------------------------------ durations

def test_a_phase_can_never_be_zero_length():
    """A zero-length phase would end the instant it began."""
    for bad in (0, -10, None, "abc"):
        t = ProductivityTimer(work_seconds=bad)
        assert t.work_seconds >= 1


def test_editing_durations_while_running_keeps_the_time_served():
    t = make(work=60)
    t.start()
    t.tick(20)                       # 40 left
    t.apply_durations(work_seconds=600)
    assert t.remaining == 40, "changing the length must not reset the phase"


def test_editing_durations_while_idle_snaps_to_the_new_length():
    t = make(work=60)
    t.apply_durations(work_seconds=120)
    assert t.remaining == 120


def test_shortening_below_the_remainder_clamps_it():
    t = make(work=600)
    t.start()
    t.apply_durations(work_seconds=60)
    assert t.remaining == 60


# --------------------------------------------------------------- rest

def test_progress_runs_from_zero_to_one():
    t = make(work=60)
    t.start()
    assert t.progress() == 0.0
    t.tick(30)
    assert abs(t.progress() - 0.5) < 1e-9
    t.tick(30)
    assert t.phase == PHASE_BREAK


def test_describe_says_what_is_happening():
    t = make()
    assert "not started" in t.describe()
    t.start()
    t.pause()
    assert "paused" in t.describe()
    t.start()
    t.tick(60)
    assert "alarm ringing" in t.describe()
    assert "1 done" in t.describe()


def test_settings_survive_a_round_trip_but_the_run_state_does_not():
    t = make(work=100, brk=50, breaks_enabled=False, repeat_alarm=False)
    t.start()
    t.tick(30)
    t.completed_cycles = 3

    back = ProductivityTimer.from_dict(t.to_dict())
    assert back.work_seconds == 100
    assert back.break_seconds == 50
    assert back.breaks_enabled is False
    assert back.repeat_alarm is False
    assert back.completed_cycles == 3
    # it must NOT come back mid-run: the app was closed, no time was served
    assert back.state == STATE_IDLE
    assert back.remaining == 100


def test_corrupt_saved_state_does_not_take_the_timer_down():
    for junk in (None, [], "nope", {"work_seconds": "abc"}):
        t = ProductivityTimer.from_dict(junk)
        assert t.work_seconds >= 1
        assert t.state == STATE_IDLE


def test_module_exposes_its_defaults():
    assert pomodoro.DEFAULT_WORK_SECONDS == 45 * 60 + 30
    assert pomodoro.DEFAULT_BREAK_SECONDS == 15 * 60 + 30
