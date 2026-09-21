"""Pure Problip scheduling model.

This module deliberately has no Qt, audio, profile, or FastPrompter-window
imports.  The future UI controller supplies one single-shot timer port and one
playback callback.  Keeping the state machine here makes the timing contract
unit-testable without constructing QApplication and prevents button callbacks
from becoming a second scheduler.
"""

from __future__ import annotations

import random
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

INITIAL_DELAY_MS = 500
RANDOM_MIN_MS = 4_000
RANDOM_MAX_MS = 7_000
MANUAL_MIN_SECONDS = 1
MANUAL_MAX_SECONDS = 3_600
PULSE_SHORT_MS = 5_000
PULSE_LONG_MIN_MS = 10_000
PULSE_LONG_MAX_MS = 20_000

DEFAULT_SOUND_ID = "sound_original"
SOUND_IDS = (
    "sound_original",
    "sound_glass",
    "sound_wood",
    "sound_soft_bell",
    "sound_bonk",
    "sound_space",
)


class ProblipState(StrEnum):
    """Truthful runtime states exposed to the UI and tray."""

    STOPPED = "STOPPED"
    STARTING = "STARTING"
    RUNNING = "RUNNING"
    ERROR = "ERROR"


# A readable alias for callers that use the shorter product terminology.
State = ProblipState


class IntervalMode(StrEnum):
    """Stable persisted interval identifiers."""

    RANDOM_4_7 = "RANDOM_4_7"
    FIXED_5S = "FIXED_5S"
    FIXED_10S = "FIXED_10S"
    FIXED_15S = "FIXED_15S"
    FIXED_20S = "FIXED_20S"
    FIXED_30S = "FIXED_30S"
    PULSE = "PULSE"
    MANUAL = "MANUAL"

    @classmethod
    def coerce(cls, value: IntervalMode | str | object) -> IntervalMode:
        if isinstance(value, cls):
            return value
        raw = str(value or "").strip().upper()
        try:
            return cls(raw)
        except ValueError:
            return cls.RANDOM_4_7


# The modes used by the settings/store code are intentionally also available
# from this module so no UI layer has to duplicate timing constants.
_FIXED_INTERVALS_MS = {
    IntervalMode.FIXED_5S: 5_000,
    IntervalMode.FIXED_10S: 10_000,
    IntervalMode.FIXED_15S: 15_000,
    IntervalMode.FIXED_20S: 20_000,
    IntervalMode.FIXED_30S: 30_000,
}


def clamp_manual_seconds(value: object, default: int = 4) -> int:
    """Return a safe manual bound in the inclusive 1..3600 range."""
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = default
    return max(MANUAL_MIN_SECONDS, min(MANUAL_MAX_SECONDS, number))


def normalize_manual_range(from_seconds: object, to_seconds: object) -> tuple[int, int]:
    """Clamp and order a MANUAL range; equal values become a fixed delay."""
    start = clamp_manual_seconds(from_seconds, default=4)
    end = clamp_manual_seconds(to_seconds, default=7)
    return (start, end) if start <= end else (end, start)


@dataclass(frozen=True)
class IntervalConfig:
    """A normalized interval selection, safe to persist and schedule."""

    mode: IntervalMode = IntervalMode.RANDOM_4_7
    manual_from_seconds: int = 4
    manual_to_seconds: int = 7

    def __post_init__(self) -> None:
        object.__setattr__(self, "mode", IntervalMode.coerce(self.mode))
        start, end = normalize_manual_range(
            self.manual_from_seconds, self.manual_to_seconds)
        object.__setattr__(self, "manual_from_seconds", start)
        object.__setattr__(self, "manual_to_seconds", end)

    @classmethod
    def from_values(
        cls,
        mode: IntervalMode | str | object,
        manual_from_seconds: object = 4,
        manual_to_seconds: object = 7,
    ) -> IntervalConfig:
        return cls(mode, manual_from_seconds, manual_to_seconds)

    def next_delay_ms(
        self,
        random_source: object | None = None,
        *,
        pulse_short_slot: bool = True,
    ) -> int:
        """Draw exactly one delay for the current session phase.

        ``pulse_short_slot`` is transient session state.  It is not part of the
        persisted config and a fresh session always passes ``True`` first.
        """
        if self.mode == IntervalMode.RANDOM_4_7:
            return _random_int(random_source, RANDOM_MIN_MS, RANDOM_MAX_MS)
        if self.mode in _FIXED_INTERVALS_MS:
            return _FIXED_INTERVALS_MS[self.mode]
        if self.mode == IntervalMode.MANUAL:
            start, end = normalize_manual_range(
                self.manual_from_seconds, self.manual_to_seconds)
            return _random_int(random_source, start * 1_000, end * 1_000)
        if self.mode == IntervalMode.PULSE:
            if pulse_short_slot:
                return PULSE_SHORT_MS
            return _random_int(
                random_source, PULSE_LONG_MIN_MS, PULSE_LONG_MAX_MS)
        # ``IntervalMode.coerce`` makes this unreachable, but a defensive
        # fallback keeps malformed future enum values from producing no wait.
        return _random_int(random_source, RANDOM_MIN_MS, RANDOM_MAX_MS)


def _random_int(source: object | None, low: int, high: int) -> int:
    """Draw an inclusive integer from production or test-injected randomness.

    Tests commonly provide ``lambda low, high``; production uses
    ``random.randint``.  A small adapter also accepts objects exposing
    ``randint`` or ``next_int`` so the core does not depend on one RNG class.
    The result is clamped to the requested range as a final safety boundary.
    """
    try:
        if source is None:
            value = random.randint(low, high)
        elif callable(source):
            value = source(low, high)
        elif hasattr(source, "randint"):
            value = source.randint(low, high)
        elif hasattr(source, "next_int"):
            value = source.next_int(low, high)
        else:
            value = random.randint(low, high)
        return max(low, min(high, int(value)))
    except (TypeError, ValueError, OverflowError, AttributeError):
        return random.randint(low, high)


class SingleShotTimerPort(Protocol):
    """The one timer authority supplied by the desktop controller.

    ``start`` must arm one single-shot timer, not a recurring timer.  The
    generation is passed alongside the delay so an adapter can associate a
    queued callback with its session.  A PyQt controller can wrap one QTimer
    behind this two-method interface without putting Qt into this module.
    """

    def start(self, delay_ms: int, generation: int) -> None:
        ...

    def stop(self) -> None:
        ...


class CallbackTimerPort:
    """Small adapter for tests and non-Qt callers using two callbacks."""

    def __init__(
        self,
        start: Callable[[int, int], None],
        stop: Callable[[], None],
    ) -> None:
        self._start = start
        self._stop = stop

    def start(self, delay_ms: int, generation: int) -> None:
        self._start(delay_ms, generation)

    def stop(self) -> None:
        self._stop()


class CueResult(StrEnum):
    """What one scheduled Problip cue actually did.

    C1.2: a cue that stood down because an alarm or a voice phrase owned the
    audio is NOT a broken Problip installation.  Only a real playback failure
    is an ERROR; a skip keeps the scheduler running, counts nothing and arms
    the next ordinary interval.
    """

    PLAYED = "PLAYED"
    SKIPPED = "SKIPPED"
    FAILED = "FAILED"

    @classmethod
    def coerce(cls, value: object) -> CueResult:
        if isinstance(value, cls):
            return value
        if value is True:
            return cls.PLAYED
        if value is False or value is None:
            return cls.FAILED
        try:
            return cls(str(value).strip().upper())
        except ValueError:
            return cls.FAILED


class ProblipScheduler:
    """One-session Problip state machine driven by one single-shot timer.

    ``play`` is called at most once for each current timer callback.  A true
    result means the scheduled cue actually started; only then does the state
    become RUNNING and ``on_success`` run.  A false result or exception enters
    ERROR and disarms the timer without rewriting the user's remembered run
    preference (that preference belongs to the store/controller boundary).

    The scheduler never computes missed intervals and never loops to catch up.
    After a late callback it emits one cue and arms the next wait from the
    callback's actual completion, which is the desktop equivalent of the
    Android scheduler's no-backlog behavior.
    """

    def __init__(
        self,
        timer: SingleShotTimerPort,
        play: Callable[[], bool],
        *,
        interval: IntervalConfig | None = None,
        random_source: object | None = None,
        on_success: Callable[[], None] | None = None,
        on_state_changed: Callable[[ProblipState], None] | None = None,
    ) -> None:
        self._timer = timer
        self._play = play
        self._random_source = random_source
        self._on_success = on_success
        self._on_state_changed = on_state_changed
        self._interval = interval or IntervalConfig()
        self._state = ProblipState.STOPPED
        self._error: str | None = None
        self._generation = 0
        self._pulse_short_slot = True
        self._timer_armed = False
        self._pending_delay_ms: int | None = None

    @property
    def state(self) -> ProblipState:
        return self._state

    @property
    def error(self) -> str | None:
        return self._error

    @property
    def generation(self) -> int:
        """Current session generation; stale callbacks must not reuse it."""
        return self._generation

    @property
    def interval(self) -> IntervalConfig:
        return self._interval

    @property
    def timer_armed(self) -> bool:
        return self._timer_armed

    @property
    def pending_delay_ms(self) -> int | None:
        return self._pending_delay_ms

    @property
    def pulse_short_slot(self) -> bool:
        """The next PULSE wait phase; exposed for deterministic diagnostics."""
        return self._pulse_short_slot

    def start(self) -> bool:
        """Start one session, or no-op when already STARTING/RUNNING."""
        if self._state in (ProblipState.STARTING, ProblipState.RUNNING):
            return False
        self._generation += 1
        self._error = None
        self._pulse_short_slot = True
        self._set_state(ProblipState.STARTING)
        try:
            # The first cue is intentionally independent of the chosen mode.
            self._arm(INITIAL_DELAY_MS)
        except Exception as exc:
            self._fail(f"Could not arm Problip scheduler: {exc}")
        return True

    def stop(self) -> bool:
        """Stop the current session; repeated STOP is harmless."""
        if (self._state == ProblipState.STOPPED
                and not self._timer_armed
                and self._error is None):
            return False
        self._generation += 1
        self._disarm()
        self._pulse_short_slot = True
        self._error = None
        self._set_state(ProblipState.STOPPED)
        return True

    def set_interval(
        self,
        interval: IntervalConfig | IntervalMode | str,
        manual_from_seconds: object | None = None,
        manual_to_seconds: object | None = None,
    ) -> bool:
        """Replace interval config and re-arm an active session immediately.

        STARTING retains the 500 ms first-cue contract.  RUNNING draws a fresh
        wait from the new mode and resets PULSE to its short phase.  STOPPED and
        ERROR only update persisted configuration; they do not start anything.
        Assigning an equal normalized config is a no-op and preserves the phase.
        """
        if isinstance(interval, IntervalConfig):
            new_config = interval
        else:
            new_config = IntervalConfig(
                mode=interval,
                manual_from_seconds=(
                    self._interval.manual_from_seconds
                    if manual_from_seconds is None else manual_from_seconds),
                manual_to_seconds=(
                    self._interval.manual_to_seconds
                    if manual_to_seconds is None else manual_to_seconds),
            )
        if new_config == self._interval:
            return False
        old_config = self._interval
        mode_changed = new_config.mode != old_config.mode
        manual_bounds_changed = (
            new_config.manual_from_seconds != old_config.manual_from_seconds
            or new_config.manual_to_seconds != old_config.manual_to_seconds
        )
        self._interval = new_config
        # PULSE phase belongs to the selected mode, not to unrelated manual
        # bounds stored alongside another mode.  Changing the mode itself (or
        # changing an active MANUAL range) is the explicit re-arm contract.
        if mode_changed:
            self._pulse_short_slot = True
        should_rearm = mode_changed or (
            new_config.mode == IntervalMode.MANUAL and manual_bounds_changed)
        if self._state == ProblipState.STARTING and should_rearm:
            self._arm(INITIAL_DELAY_MS)
        elif self._state == ProblipState.RUNNING and should_rearm:
            self._arm(self._next_interval_delay())
        return True

    def set_manual_range(self, from_seconds: object, to_seconds: object) -> bool:
        """Update MANUAL bounds; active MANUAL sessions re-arm immediately."""
        return self.set_interval(
            self._interval.mode,
            manual_from_seconds=from_seconds,
            manual_to_seconds=to_seconds,
        )

    def timer_fired(self, generation: int | None = None) -> bool:
        """Consume one timer callback, ignoring stale or inactive callbacks.

        This method deliberately performs one playback attempt only.  It does
        not inspect wall-clock debt or replay missed callbacks after suspend.
        """
        if generation is not None and generation != self._generation:
            return False
        if not self._timer_armed:
            return False
        if self._state not in (ProblipState.STARTING, ProblipState.RUNNING):
            return False
        self._timer_armed = False
        self._pending_delay_ms = None
        session_generation = self._generation
        try:
            result = CueResult.coerce(self._play())
        except Exception as exc:
            self._fail(f"Playback failed: {exc}")
            return False
        if result is CueResult.FAILED:
            self._fail("Playback failed")
            return False
        if result is CueResult.SKIPPED:
            # The cue stood down for a more important sound: stay RUNNING,
            # count nothing, glow nothing, and wait one ordinary interval.
            if (session_generation != self._generation
                    or self._state not in (ProblipState.STARTING,
                                           ProblipState.RUNNING)):
                return False
            self._set_state(ProblipState.RUNNING)
            if not self._timer_armed:
                try:
                    self._arm(self._next_interval_delay())
                except Exception as exc:
                    self._fail(f"Could not arm Problip scheduler: {exc}")
                    return False
            return True
        # Playback is a callback boundary.  A synchronous STOP or a newer
        # session must win over the old timer callback and must not be undone
        # by the success path below.
        if (session_generation != self._generation
                or self._state not in (ProblipState.STARTING, ProblipState.RUNNING)):
            return False

        self._set_state(ProblipState.RUNNING)
        if self._on_success is not None:
            try:
                self._on_success()
            except Exception:
                # Statistics/UI observers must never turn an audible success
                # into a scheduler ERROR. The audio result is authoritative.
                pass
        if (session_generation != self._generation
                or self._state != ProblipState.RUNNING):
            return False
        # An observer may have changed the interval while handling success. In
        # that case it already re-armed this same single-shot timer; do not
        # start a second wait on top of it.
        if self._timer_armed:
            return True
        try:
            self._arm(self._next_interval_delay())
        except Exception as exc:
            self._fail(f"Could not arm Problip scheduler: {exc}")
            return False
        return True

    # Naming used by controller adapters and tests that model Qt's timeout.
    handle_timer = timer_fired
    on_timer = timer_fired

    def _next_interval_delay(self) -> int:
        short_slot = self._pulse_short_slot
        if self._interval.mode == IntervalMode.PULSE:
            self._pulse_short_slot = not short_slot
        return self._interval.next_delay_ms(
            self._random_source, pulse_short_slot=short_slot)

    def _arm(self, delay_ms: int) -> None:
        delay = max(1, int(delay_ms))
        self._pending_delay_ms = delay
        self._timer_armed = True
        try:
            self._timer.start(delay, self._generation)
        except Exception:
            self._timer_armed = False
            self._pending_delay_ms = None
            raise

    def _disarm(self) -> None:
        was_armed = self._timer_armed
        self._timer_armed = False
        self._pending_delay_ms = None
        if was_armed:
            self._timer.stop()

    def _fail(self, message: str) -> None:
        self._generation += 1
        self._disarm()
        self._pulse_short_slot = True
        self._error = message or "Playback failed"
        self._set_state(ProblipState.ERROR)
        return True

    def fail(self, message: str) -> bool:
        """Public failure entry point for the owning controller.

        Enters the ERROR state exactly like the internal playback-failure
        path (bumps the generation, disarms the timer, clears the PULSE
        phase) so the controller never has to reach into ``_fail``.
        Returns True when the state actually changed to ERROR.
        """
        if self._state is ProblipState.ERROR and self._error == (message or "Playback failed"):
            return False
        self._fail(message)
        return True

    def _set_state(self, state: ProblipState) -> None:
        if state == self._state:
            return
        self._state = state
        if self._on_state_changed is not None:
            try:
                self._on_state_changed(state)
            except Exception:
                pass


# Clear name for callers that think of the object as the core engine.
ProblipEngine = ProblipScheduler
