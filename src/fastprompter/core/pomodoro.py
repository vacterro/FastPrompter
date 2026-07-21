"""Productivity timer — work/break phases, modelled after my_timer2.

This is deliberately NOT the same thing as `timers.py`. A Timer there is a
deadline: an absolute moment that arrives whether or not the app is looking.
This is a *stopwatch you drive*: it counts down only while running, it can
be paused indefinitely, and its phases hand off to each other.

Kept free of Qt so the phase rules can be tested without a UI, and driven by
elapsed wall-clock time rather than by counting ticks — a timer that loses a
minute because the app was busy is not a timer anyone trusts.
"""

from __future__ import annotations

PHASE_WORK = "work"
PHASE_BREAK = "break"

STATE_IDLE = "idle"
STATE_RUNNING = "running"
STATE_PAUSED = "paused"

DEFAULT_WORK_SECONDS = 45 * 60 + 30      # my_timer2's defaults
DEFAULT_BREAK_SECONDS = 15 * 60 + 30


def format_clock(seconds):
    """mm:ss, and hh:mm:ss once it runs past an hour."""
    seconds = int(max(0, round(seconds)))
    hours, rem = divmod(seconds, 3600)
    mins, secs = divmod(rem, 60)
    if hours:
        return f"{hours}:{mins:02d}:{secs:02d}"
    return f"{mins:02d}:{secs:02d}"


class ProductivityTimer:
    """Work, then break, then work again — for as long as you keep going.

    Every state change goes through this class, so the UI never has to work
    out what "pressing the button now" means.
    """

    def __init__(self, work_seconds=DEFAULT_WORK_SECONDS,
                 break_seconds=DEFAULT_BREAK_SECONDS, breaks_enabled=True,
                 repeat_alarm=True):
        self.work_seconds = self._sane(work_seconds, DEFAULT_WORK_SECONDS)
        self.break_seconds = self._sane(break_seconds, DEFAULT_BREAK_SECONDS)
        self.breaks_enabled = bool(breaks_enabled)
        self.repeat_alarm = bool(repeat_alarm)

        self.phase = PHASE_WORK
        self.state = STATE_IDLE
        self.remaining = self.work_seconds
        self.completed_cycles = 0
        # set when a phase ends and stays set until acknowledged, so an alarm
        # can keep sounding for someone who walked away from the desk
        self.alarm_pending = False

    # ---- helpers ------------------------------------------------------
    @staticmethod
    def _sane(value, fallback):
        """A phase of zero (or nonsense) would end the instant it started."""
        try:
            value = int(round(float(value)))
        except (TypeError, ValueError):
            return fallback
        return max(1, value)

    def phase_length(self, phase=None):
        phase = phase or self.phase
        return self.break_seconds if phase == PHASE_BREAK else self.work_seconds

    @property
    def running(self):
        return self.state == STATE_RUNNING

    def progress(self):
        """0.0 at the start of the phase, 1.0 at its end."""
        total = self.phase_length()
        if total <= 0:
            return 1.0
        return max(0.0, min(1.0, 1.0 - (self.remaining / total)))

    # ---- controls -----------------------------------------------------
    def start(self):
        """Begin, or resume after a pause. Acknowledges a pending alarm."""
        self.alarm_pending = False
        if self.state == STATE_IDLE:
            self.remaining = self.phase_length()
        self.state = STATE_RUNNING
        return self.state

    def pause(self):
        if self.state == STATE_RUNNING:
            self.state = STATE_PAUSED
        return self.state

    def toggle(self):
        """The single action button: start -> pause -> resume."""
        return self.pause() if self.running else self.start()

    def reset(self):
        """Back to the beginning of a work phase, stopped."""
        self.alarm_pending = False
        self.phase = PHASE_WORK
        self.state = STATE_IDLE
        self.remaining = self.work_seconds
        return self.state

    def acknowledge(self):
        """Silence a ringing alarm without touching the countdown."""
        was = self.alarm_pending
        self.alarm_pending = False
        return was

    def apply_durations(self, work_seconds=None, break_seconds=None):
        """Change the phase lengths.

        A running phase keeps counting down from where it is; only an idle
        timer snaps to the new length, so editing the box mid-session does
        not silently throw away the time already served.
        """
        if work_seconds is not None:
            self.work_seconds = self._sane(work_seconds, self.work_seconds)
        if break_seconds is not None:
            self.break_seconds = self._sane(break_seconds, self.break_seconds)
        if self.state == STATE_IDLE:
            self.remaining = self.phase_length()
        else:
            self.remaining = min(self.remaining, self.phase_length())
        return self.remaining

    def skip_phase(self):
        """Jump straight to the other phase, keeping the timer running."""
        finished_work = self.phase == PHASE_WORK
        self._enter_next_phase(count_cycle=finished_work)
        self.alarm_pending = False
        return self.phase

    # ---- the clock ----------------------------------------------------
    def tick(self, elapsed_seconds):
        """Advance by real elapsed time. Returns the phases that ended.

        Driven by elapsed time rather than by assuming each call is one
        second: if the app stalls, the timer must still be right afterwards.
        A long stall can carry it through more than one phase, so this loops.
        """
        ended = []
        if self.state != STATE_RUNNING:
            return ended
        try:
            elapsed = float(elapsed_seconds)
        except (TypeError, ValueError):
            return ended
        if elapsed <= 0:
            return ended

        # guard against an unbounded loop if a phase were ever zero-length
        for _ in range(1000):
            if elapsed < self.remaining:
                self.remaining -= elapsed
                break
            elapsed -= self.remaining
            ended.append(self.phase)
            self.alarm_pending = self.repeat_alarm or self.alarm_pending
            finished_work = self.phase == PHASE_WORK
            self._enter_next_phase(count_cycle=finished_work)
            if self.state != STATE_RUNNING:
                break
        return ended

    def _enter_next_phase(self, count_cycle):
        if count_cycle:
            self.completed_cycles += 1
        if self.phase == PHASE_WORK:
            if self.breaks_enabled:
                self.phase = PHASE_BREAK
                self.remaining = self.break_seconds
                self.state = STATE_RUNNING
            else:
                # no break configured: stop and re-arm the work phase, the
                # way my_timer2 does rather than looping straight back in
                self.phase = PHASE_WORK
                self.remaining = self.work_seconds
                self.state = STATE_PAUSED
        else:
            self.phase = PHASE_WORK
            self.remaining = self.work_seconds
            self.state = STATE_RUNNING

    # ---- words --------------------------------------------------------
    def label(self):
        """What to show on the badge: the clock plus the phase."""
        return f"{format_clock(self.remaining)} {self.phase}"

    def describe(self):
        bits = [f"{self.phase.capitalize()} {format_clock(self.remaining)}"]
        if self.state == STATE_PAUSED:
            bits.append("paused")
        elif self.state == STATE_IDLE:
            bits.append("not started")
        if self.completed_cycles:
            bits.append(f"{self.completed_cycles} done")
        if self.alarm_pending:
            bits.append("alarm ringing")
        return " - ".join(bits)

    # ---- persistence --------------------------------------------------
    def to_dict(self):
        return {
            "work_seconds": self.work_seconds,
            "break_seconds": self.break_seconds,
            "breaks_enabled": self.breaks_enabled,
            "repeat_alarm": self.repeat_alarm,
            "completed_cycles": self.completed_cycles,
        }

    @classmethod
    def from_dict(cls, d):
        """Durations and the cycle count survive a restart; the run state
        does not — coming back to a timer that silently kept counting while
        the app was closed would be a lie."""
        if not isinstance(d, dict):
            return cls()
        timer = cls(
            work_seconds=d.get("work_seconds", DEFAULT_WORK_SECONDS),
            break_seconds=d.get("break_seconds", DEFAULT_BREAK_SECONDS),
            breaks_enabled=d.get("breaks_enabled", True),
            repeat_alarm=d.get("repeat_alarm", True),
        )
        try:
            timer.completed_cycles = max(0, int(d.get("completed_cycles", 0)))
        except (TypeError, ValueError):
            timer.completed_cycles = 0
        return timer
