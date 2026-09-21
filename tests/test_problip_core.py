"""T-1238-A: pure Problip scheduler and interval contracts."""

from __future__ import annotations

from fastprompter.core.problip import (
    INITIAL_DELAY_MS,
    MANUAL_MAX_SECONDS,
    MANUAL_MIN_SECONDS,
    PULSE_LONG_MAX_MS,
    PULSE_LONG_MIN_MS,
    PULSE_SHORT_MS,
    RANDOM_MAX_MS,
    RANDOM_MIN_MS,
    IntervalConfig,
    IntervalMode,
    ProblipScheduler,
    ProblipState,
    clamp_manual_seconds,
    normalize_manual_range,
)


class FakeSingleShotTimer:
    """A test port that records every arm without creating a Qt event loop."""

    def __init__(self):
        self.starts: list[tuple[int, int]] = []
        self.stop_calls = 0
        self.active = False

    def start(self, delay_ms: int, generation: int) -> None:
        self.starts.append((delay_ms, generation))
        self.active = True

    def stop(self) -> None:
        self.stop_calls += 1
        self.active = False


class SequenceRandom:
    def __init__(self, values: list[int]):
        self.values = iter(values)
        self.calls: list[tuple[int, int]] = []

    def randint(self, low: int, high: int) -> int:
        self.calls.append((low, high))
        return next(self.values)


def make_scheduler(*, interval=None, play=None, random_source=None, on_success=None):
    timer = FakeSingleShotTimer()
    played: list[int] = []

    def do_play() -> bool:
        played.append(1)
        return True if play is None else play()

    scheduler = ProblipScheduler(
        timer,
        do_play,
        interval=interval,
        random_source=random_source,
        on_success=on_success,
    )
    return scheduler, timer, played


def test_start_uses_one_500ms_first_wait_and_repeated_start_is_noop():
    scheduler, timer, _ = make_scheduler()

    assert scheduler.start() is True
    assert scheduler.state is ProblipState.STARTING
    assert scheduler.generation == 1
    assert timer.starts == [(INITIAL_DELAY_MS, 1)]

    assert scheduler.start() is False
    assert scheduler.generation == 1
    assert timer.starts == [(INITIAL_DELAY_MS, 1)]

    assert scheduler.timer_fired(1) is True
    assert scheduler.state is ProblipState.RUNNING
    assert len(timer.starts) == 2
    assert RANDOM_MIN_MS <= timer.starts[-1][0] <= RANDOM_MAX_MS


def test_timer_callback_is_one_shot_and_stale_generation_cannot_play():
    scheduler, timer, played = make_scheduler()
    scheduler.start()
    generation = scheduler.generation

    assert scheduler.timer_fired(generation - 1) is False
    assert played == []
    assert scheduler.timer_armed is True

    assert scheduler.timer_fired(generation) is True
    assert played == [1]
    # A second delivery for the consumed arm is ignored; only the newly armed
    # current wait may produce the next cue.
    assert scheduler.timer_fired(generation - 1) is False
    assert played == [1]


def test_stop_invalidates_session_and_repeated_stop_is_harmless():
    scheduler, timer, played = make_scheduler()
    scheduler.start()
    old_generation = scheduler.generation

    assert scheduler.stop() is True
    assert scheduler.state is ProblipState.STOPPED
    assert scheduler.generation == old_generation + 1
    assert scheduler.timer_armed is False
    assert timer.stop_calls == 1

    assert scheduler.stop() is False
    assert timer.stop_calls == 1
    assert scheduler.timer_fired(old_generation) is False
    assert played == []


def test_playback_failure_is_truthfully_error_and_explicit_start_can_recover():
    attempts = iter([False, True])
    scheduler, timer, played = make_scheduler(play=lambda: next(attempts))

    scheduler.start()
    first_generation = scheduler.generation
    assert scheduler.timer_fired(first_generation) is False
    assert played == [1]
    assert scheduler.state is ProblipState.ERROR
    assert scheduler.error == "Playback failed"
    assert scheduler.timer_armed is False
    assert timer.stop_calls == 0  # the callback had already consumed its arm

    assert scheduler.start() is True
    second_generation = scheduler.generation
    assert second_generation > first_generation
    assert scheduler.state is ProblipState.STARTING
    assert scheduler.timer_fired(second_generation) is True
    assert scheduler.state is ProblipState.RUNNING


def test_fixed_and_random_interval_values_are_stable_and_inclusive():
    assert IntervalConfig(IntervalMode.FIXED_5S).next_delay_ms() == 5_000
    assert IntervalConfig(IntervalMode.FIXED_10S).next_delay_ms() == 10_000
    assert IntervalConfig(IntervalMode.FIXED_15S).next_delay_ms() == 15_000
    assert IntervalConfig(IntervalMode.FIXED_20S).next_delay_ms() == 20_000
    assert IntervalConfig(IntervalMode.FIXED_30S).next_delay_ms() == 30_000

    random_source = SequenceRandom([RANDOM_MIN_MS, RANDOM_MAX_MS])
    config = IntervalConfig(IntervalMode.RANDOM_4_7)
    assert config.next_delay_ms(random_source) == RANDOM_MIN_MS
    assert config.next_delay_ms(random_source) == RANDOM_MAX_MS
    assert random_source.calls == [
        (RANDOM_MIN_MS, RANDOM_MAX_MS),
        (RANDOM_MIN_MS, RANDOM_MAX_MS),
    ]


def test_manual_bounds_clamp_reorder_and_equal_becomes_fixed():
    assert clamp_manual_seconds(-99) == MANUAL_MIN_SECONDS
    assert clamp_manual_seconds(99999) == MANUAL_MAX_SECONDS
    assert normalize_manual_range(30, 5) == (5, 30)
    assert normalize_manual_range("bad", None) == (4, 7)

    config = IntervalConfig.from_values(IntervalMode.MANUAL, 30, 5)
    assert (config.manual_from_seconds, config.manual_to_seconds) == (5, 30)
    assert 5_000 <= config.next_delay_ms(lambda low, high: low) <= 30_000

    equal = IntervalConfig.from_values(IntervalMode.MANUAL, 12, 12)
    assert equal.next_delay_ms(lambda low, high: high) == 12_000


def test_pulse_is_short_then_fresh_random_long_and_resets_on_new_session():
    random_source = SequenceRandom([PULSE_LONG_MIN_MS, PULSE_LONG_MAX_MS])
    scheduler, timer, _ = make_scheduler(
        interval=IntervalConfig(IntervalMode.PULSE),
        random_source=random_source,
    )
    scheduler.start()
    generation = scheduler.generation

    assert scheduler.timer_fired(generation) is True
    assert timer.starts[-1] == (PULSE_SHORT_MS, generation)
    assert scheduler.pulse_short_slot is False

    assert scheduler.timer_fired(generation) is True
    assert PULSE_LONG_MIN_MS <= timer.starts[-1][0] <= PULSE_LONG_MAX_MS
    assert random_source.calls == [(PULSE_LONG_MIN_MS, PULSE_LONG_MAX_MS)]
    assert scheduler.pulse_short_slot is True

    scheduler.stop()
    scheduler.start()
    new_generation = scheduler.generation
    assert scheduler.timer_fired(new_generation) is True
    assert timer.starts[-1] == (PULSE_SHORT_MS, new_generation)


def test_interval_mode_change_rearms_same_scheduler_and_resets_pulse_phase():
    scheduler, timer, _ = make_scheduler(interval=IntervalConfig(IntervalMode.FIXED_30S))
    scheduler.start()
    generation = scheduler.generation
    scheduler.timer_fired(generation)
    assert timer.starts[-1] == (30_000, generation)

    assert scheduler.set_interval(IntervalMode.PULSE) is True
    assert scheduler.state is ProblipState.RUNNING
    assert timer.starts[-1] == (PULSE_SHORT_MS, generation)
    assert scheduler.pulse_short_slot is False

    # Re-selecting the same mode does not create another arm or change phase.
    arm_count = len(timer.starts)
    assert scheduler.set_interval(IntervalMode.PULSE) is False
    assert len(timer.starts) == arm_count


def test_manual_range_change_rearms_only_when_manual_is_active():
    scheduler, timer, _ = make_scheduler(
        interval=IntervalConfig(IntervalMode.FIXED_5S),
        random_source=SequenceRandom([10_000, 30_000]),
    )
    scheduler.start()
    generation = scheduler.generation
    scheduler.timer_fired(generation)
    arm_count = len(timer.starts)
    assert scheduler.set_manual_range(20, 10) is True
    assert len(timer.starts) == arm_count  # inactive MANUAL bounds are storage only

    scheduler.set_interval(IntervalMode.MANUAL, 20, 10)
    assert timer.starts[-1][0] == 10_000
    assert scheduler.set_manual_range(30, 40) is True
    assert timer.starts[-1][0] == 30_000


def test_late_callback_never_catches_up_multiple_blips():
    scheduler, timer, played = make_scheduler(
        interval=IntervalConfig(IntervalMode.FIXED_5S))
    scheduler.start()
    generation = scheduler.generation

    # One timer delivery means one playback attempt, irrespective of how late
    # the real event loop delivered it.
    assert scheduler.timer_fired(generation) is True
    assert len(played) == 1
    assert len(timer.starts) == 2
    assert scheduler.timer_fired(generation) is True
    assert len(played) == 2
    assert len(timer.starts) == 3


def test_success_observer_can_stop_without_old_callback_rearming_timer():
    holder = {}

    def stop_after_success():
        holder["scheduler"].stop()

    scheduler, timer, played = make_scheduler(on_success=stop_after_success)
    holder["scheduler"] = scheduler
    scheduler.start()
    generation = scheduler.generation

    assert scheduler.timer_fired(generation) is False
    assert played == [1]
    assert scheduler.state is ProblipState.STOPPED
    assert scheduler.timer_armed is False
    assert timer.stop_calls == 0  # the current callback was already consumed
