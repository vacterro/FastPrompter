"""Timer / limit-reset model.

Built for the actual use case: knowing when an agentic platform's usage
limit comes back. Each timer is a name plus a moment, optionally repeating,
with its own sound and colour. Kept free of Qt so the scheduling rules can
be tested directly.

Colour has two modes:
  * static      - one colour the user picked, always.
  * temperature - cool while the wait is long, warming as it closes in, so
                  the top bar tells you how urgent things are at a glance.
"""

from __future__ import annotations

import datetime
import uuid

REPEAT_NONE = "once"
REPEAT_DAILY = "daily"
REPEAT_WEEKLY = "weekly"
REPEAT_CHOICES = (REPEAT_NONE, REPEAT_DAILY, REPEAT_WEEKLY)

DEFAULT_COLOR = "#6aa9ff"
COLOR_STATIC = "static"
COLOR_TEMPERATURE = "temperature"

# cold -> hot. The last stop is what "about to fire" looks like.
_TEMPERATURE_STOPS = (
    (24 * 3600, "#4a90d9"),   # a day or more out: calm blue
    (6 * 3600, "#46b98a"),    # hours: green
    (2 * 3600, "#d9c04a"),    # soon: yellow
    (30 * 60, "#e08a3c"),     # very soon: orange
    (0, "#e05555"),           # minutes: red
)


def _clamp_byte(v):
    return max(0, min(255, int(round(v))))


def _hex_to_rgb(h):
    h = (h or "").strip().lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    if len(h) != 6:
        return (128, 128, 128)
    try:
        return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return (128, 128, 128)


def _mix(c1, c2, t):
    t = max(0.0, min(1.0, t))
    r1, g1, b1 = _hex_to_rgb(c1)
    r2, g2, b2 = _hex_to_rgb(c2)
    return "#{:02x}{:02x}{:02x}".format(
        _clamp_byte(r1 + (r2 - r1) * t),
        _clamp_byte(g1 + (g2 - g1) * t),
        _clamp_byte(b1 + (b2 - b1) * t),
    )


def temperature_color(remaining_seconds: float) -> str:
    """Blend smoothly between the stops above, so it warms gradually."""
    rem = max(0.0, float(remaining_seconds))
    stops = _TEMPERATURE_STOPS
    if rem >= stops[0][0]:
        return stops[0][1]
    for i in range(len(stops) - 1):
        hi_s, hi_c = stops[i]
        lo_s, lo_c = stops[i + 1]
        if lo_s <= rem <= hi_s:
            span = hi_s - lo_s
            t = 0.0 if span <= 0 else (hi_s - rem) / span
            return _mix(hi_c, lo_c, t)
    return stops[-1][1]


class Timer:
    """One countdown. `target` is always an absolute local datetime."""

    __slots__ = ("id", "name", "description", "target", "repeat", "sound",
                 "volume", "color_mode", "color", "enabled", "fired")

    def __init__(self, name, target, repeat=REPEAT_NONE, sound="tick",
                 volume=5, color_mode=COLOR_TEMPERATURE, color=DEFAULT_COLOR,
                 enabled=True, id=None, fired=False, description=""):
        self.id = id or uuid.uuid4().hex[:12]
        self.name = (name or "Timer").strip() or "Timer"
        self.description = (description or "").strip()
        self.target = target
        self.repeat = repeat if repeat in REPEAT_CHOICES else REPEAT_NONE
        self.sound = sound or "tick"
        try:
            self.volume = max(0, min(10, int(volume)))
        except (TypeError, ValueError):
            self.volume = 5
        self.color_mode = color_mode if color_mode in (COLOR_STATIC, COLOR_TEMPERATURE) else COLOR_TEMPERATURE
        self.color = color or DEFAULT_COLOR
        self.enabled = bool(enabled)
        self.fired = bool(fired)

    # ---- serialisation ------------------------------------------------
    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "target": self.target.isoformat(timespec="seconds"),
            "repeat": self.repeat,
            "sound": self.sound,
            "volume": self.volume,
            "color_mode": self.color_mode,
            "color": self.color,
            "enabled": self.enabled,
            "fired": self.fired,
        }

    @classmethod
    def from_dict(cls, d):
        """Returns None for anything malformed — a corrupt entry must not
        take the whole timer list (or the app) down with it."""
        if not isinstance(d, dict):
            return None
        try:
            target = datetime.datetime.fromisoformat(d["target"])
        except (KeyError, TypeError, ValueError):
            return None
        return cls(
            name=d.get("name", "Timer"),
            description=d.get("description", ""),
            target=target,
            repeat=d.get("repeat", REPEAT_NONE),
            sound=d.get("sound", "tick"),
            volume=d.get("volume", 5),
            color_mode=d.get("color_mode", COLOR_TEMPERATURE),
            color=d.get("color", DEFAULT_COLOR),
            enabled=d.get("enabled", True),
            id=d.get("id"),
            fired=d.get("fired", False),
        )

    # ---- state --------------------------------------------------------
    def remaining(self, now=None):
        now = now or datetime.datetime.now()
        return (self.target - now).total_seconds()

    def is_due(self, now=None):
        return self.enabled and not self.fired and self.remaining(now) <= 0

    def display_color(self, now=None):
        if self.color_mode == COLOR_STATIC:
            return self.color
        return temperature_color(self.remaining(now))

    def snooze(self, minutes=10, now=None):
        """Push the timer back — always LATER, never closer.

        For an alarm that already went off this means "remind me again in N
        minutes". For one still counting down it adds N minutes to the
        existing target; resetting that to now+N would drag a timer due in
        two hours forward to ten minutes away, which is the opposite of
        what pressing snooze should ever do.
        """
        now = now or datetime.datetime.now()
        try:
            minutes = max(1, int(minutes))
        except (TypeError, ValueError):
            minutes = 10
        step = datetime.timedelta(minutes=minutes)
        base = self.target if self.target > now else now
        self.target = base + step
        self.fired = False
        self.enabled = True
        return self.target

    def summary(self):
        """One line for tooltips and list rows."""
        bits = [self.name]
        if self.description:
            bits.append(self.description)
        return " - ".join(bits)

    def advance(self, now=None):
        """Roll a repeating timer to its next occurrence.

        Loops rather than adding a single period: after the app has been
        closed for a week a daily timer must land in the FUTURE, not on
        yesterday, and must not fire once per missed day.
        """
        now = now or datetime.datetime.now()
        if self.repeat == REPEAT_DAILY:
            step = datetime.timedelta(days=1)
        elif self.repeat == REPEAT_WEEKLY:
            step = datetime.timedelta(weeks=1)
        else:
            self.fired = True
            return False
        while self.target <= now:
            self.target += step
        self.fired = False
        return True


def load_timers(raw):
    """Parse the stored list, skipping anything corrupt."""
    if not isinstance(raw, list):
        return []
    out = []
    for entry in raw:
        t = Timer.from_dict(entry)
        if t is not None:
            out.append(t)
    return out


def save_timers(timers):
    return [t.to_dict() for t in timers]


def next_due(timers, now=None):
    """The soonest enabled, unfired timer — the one worth showing."""
    now = now or datetime.datetime.now()
    live = [t for t in timers if t.enabled and not t.fired]
    if not live:
        return None
    return min(live, key=lambda t: t.target)


def collect_due(timers, now=None):
    """Every timer that has come due, advancing repeats past `now`."""
    now = now or datetime.datetime.now()
    fired = []
    for t in timers:
        if t.is_due(now):
            fired.append(t)
            t.advance(now)
    return fired
