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

import calendar
import datetime
import random
import uuid

from fastprompter.theme.themes import blend_hex

# One shared generator for the whole app: never spin up a fresh Random() per
# fire, and let tests inject a seeded one for determinism.
_RNG = random.Random()


def _minute_of_day(when: datetime.datetime) -> int:
    return when.hour * 60 + when.minute

REPEAT_NONE = "once"
REPEAT_DAILY = "daily"
REPEAT_WEEKLY = "weekly"
REPEAT_INTERVAL = "interval"
REPEAT_MONTHLY = "monthly"
REPEAT_YEARLY = "yearly"
REPEAT_CHOICES = (REPEAT_NONE, REPEAT_INTERVAL, REPEAT_DAILY, REPEAT_WEEKLY,
                  REPEAT_MONTHLY, REPEAT_YEARLY)

KIND_ALARM = "alarm"
KIND_CALENDAR = "calendar"
KIND_CHOICES = (KIND_ALARM, KIND_CALENDAR)

# Sound policy: a timer plays ONE fixed sound, or picks from a random pool.
SOUND_MODE_SINGLE = "single"
SOUND_MODE_POOL = "pool"
SOUND_MODE_CHOICES = (SOUND_MODE_SINGLE, SOUND_MODE_POOL)
MAX_TIMER_SOUND_RULES = 10

# The case this was built for: an agent platform hands out a fresh quota
# every N hours from the moment the window opened, so the anchor matters as
# much as the period. Five hours is the common one, hence the default.
DEFAULT_INTERVAL_MINUTES = 5 * 60

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
            return blend_hex(hi_c, lo_c, t)
    return stops[-1][1]


def _heal_anchor_date(repeat_anchor, target):
    """Return an ISO date string for ``repeat_anchor``.

    - explicit valid ISO date -> kept
    - missing / malformed -> derived from ``target.date()``

    Must never raise: malformed data heals to a legacy-safe anchor.
    """
    if isinstance(repeat_anchor, str):
        try:
            datetime.date.fromisoformat(repeat_anchor)
            return repeat_anchor
        except ValueError:
            pass
    return target.date().isoformat()


def _heal_bool(value, default=True):
    """One canonical boolean healer for persisted timer fields.

    Python truthiness is NOT the persistence contract: ``bool("False")`` is
    True, so a legacy string field would silently invert itself. Accepts
    real bools, the strings "True"/"False" and numeric 1/0; anything else
    falls back to the explicit field default.
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        s = value.strip().lower()
        if s in ("true", "1"):
            return True
        if s in ("false", "0"):
            return False
        return default
    if isinstance(value, (int, float)):
        # Accept only exact numeric 0/1. Values like 2, -1, 0.5 or NaN
        # must NOT be coerced into meaning; they fall back to the field
        # default so corrupt persistence never silently flips behaviour.
        if isinstance(value, float) and (value != value or value == float("inf") or value == -float("inf")):
            return default
        if value in (0, 1):
            return bool(value)
        return default
    return default


def _heal_sound_rules(raw):
    """Coerce stored sound rules into a safe list.

    - missing / non-list -> empty pool
    - each entry is a dict with the documented schema
    - over the cap -> truncated
    - malformed entries are dropped (never fatal)
    """
    if not isinstance(raw, list):
        return []
    out = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        sound = entry.get("sound")
        if not isinstance(sound, str) or not sound:
            continue
        enabled = _heal_bool(entry.get("enabled", True), True)
        all_day = _heal_bool(entry.get("all_day", True), True)
        start = entry.get("start_minute", 0)
        end = entry.get("end_minute", 0)
        try:
            start = max(0, min(1439, int(start)))
            end = max(0, min(1439, int(end)))
        except (TypeError, ValueError):
            start, end = 0, 0
        vol = entry.get("volume", None)
        if vol is not None:
            try:
                vol = max(0, min(10, int(vol)))
            except (TypeError, ValueError):
                vol = None
        out.append({
            "sound": sound,
            "enabled": enabled,
            "all_day": all_day,
            "start_minute": start,
            "end_minute": end,
            "volume": vol,
        })
        if len(out) >= MAX_TIMER_SOUND_RULES:
            break
    return out


def _anchor_date(timer) -> datetime.date:
    """The recurrence anchor as a date, falling back to the target date."""
    if isinstance(timer.repeat_anchor, str):
        try:
            return datetime.date.fromisoformat(timer.repeat_anchor)
        except ValueError:
            return timer.target.date()
    return timer.target.date()


def _next_monthly_after(timer, after):
    """Next monthly occurrence strictly after ``after`` (anchor-aware clamp)."""
    anchor = _anchor_date(timer)
    h, mi, s = timer.target.hour, timer.target.minute, timer.target.second
    anchor_mi = anchor.year * 12 + (anchor.month - 1)
    after_mi = after.year * 12 + (after.month - 1)
    k = max(0, after_mi - anchor_mi)
    while True:
        mi_idx = anchor_mi + k
        y, mo = divmod(mi_idx, 12)
        day = min(anchor.day, calendar.monthrange(y, mo + 1)[1])
        cand = datetime.datetime(y, mo + 1, day, h, mi, s)
        if cand > after:
            return cand
        k += 1


def _next_yearly_after(timer, after):
    """Next yearly occurrence strictly after ``after`` (anchor-aware clamp)."""
    anchor = _anchor_date(timer)
    h, mi, s = timer.target.hour, timer.target.minute, timer.target.second
    for k in range(0, 4000):
        y = anchor.year + k
        day = min(anchor.day, calendar.monthrange(y, anchor.month)[1])
        cand = datetime.datetime(y, anchor.month, day, h, mi, s)
        if cand > after:
            return cand
    return after + datetime.timedelta(days=366)


class Timer:
    """One countdown. `target` is always an absolute local datetime."""

    __slots__ = ("id", "name", "description", "target", "repeat", "sound",
                 "volume", "color_mode", "color", "enabled", "fired",
                 "interval_minutes", "kind", "show_notification",
                 "show_in_top_bar", "repeat_anchor", "sound_mode",
                 "sound_rules", "auto_limit_key")

    def __init__(self, name, target, repeat=REPEAT_NONE, sound="tick",
                 volume=5, color_mode=COLOR_TEMPERATURE, color=DEFAULT_COLOR,
                 enabled=True, id=None, fired=False, description="",
                 interval_minutes=DEFAULT_INTERVAL_MINUTES, kind=KIND_ALARM,
                 show_notification=True, show_in_top_bar=True,
                 repeat_anchor=None, sound_mode=SOUND_MODE_SINGLE,
                 sound_rules=None, auto_limit_key=None):
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
        self.enabled = _heal_bool(enabled, True)
        self.fired = _heal_bool(fired, False)
        self.auto_limit_key = auto_limit_key
        try:
            # a zero or negative period would make advance() spin forever
            self.interval_minutes = max(1, int(interval_minutes))
        except (TypeError, ValueError):
            self.interval_minutes = DEFAULT_INTERVAL_MINUTES
        # ---- T-1004 behaviour flags (legacy-safe defaults) -------------
        self.kind = kind if kind in KIND_CHOICES else KIND_ALARM
        # any malformed value heals to the ON default (never a silent flip)
        self.show_notification = _heal_bool(show_notification, True)
        self.show_in_top_bar = _heal_bool(show_in_top_bar, True)
        self.repeat_anchor = _heal_anchor_date(repeat_anchor, target)
        # ---- T-1005 sound policy (legacy-safe: single + empty pool) ----
        self.sound_mode = sound_mode if sound_mode in SOUND_MODE_CHOICES else SOUND_MODE_SINGLE
        self.sound_rules = _heal_sound_rules(sound_rules)

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
            "interval_minutes": self.interval_minutes,
            "kind": self.kind,
            "show_notification": self.show_notification,
            "show_in_top_bar": self.show_in_top_bar,
            "repeat_anchor": self.repeat_anchor,
            "sound_mode": self.sound_mode,
            # deep copy: a saved snapshot must never alias the live rules,
            # or mutating one profile's rules would rewrite the other's
            "sound_rules": [dict(r) for r in self.sound_rules],
            "auto_limit_key": getattr(self, "auto_limit_key", None),
        }

    @classmethod
    def from_dict(cls, d):
        """Returns None for anything malformed — a corrupt entry must not
        take the whole timer list (or the app) down with it."""
        if not isinstance(d, dict):
            return None
        try:
            target = datetime.datetime.fromisoformat(d["target"])
            if target.utcoffset() is not None:
                return None
            name = d.get("name", "Timer")
            description = d.get("description", "")
            if not isinstance(name, str) or not isinstance(description, str):
                return None
        except (KeyError, TypeError, ValueError):
            return None
        kind = d.get("kind", KIND_ALARM)
        if kind not in KIND_CHOICES:
            kind = KIND_ALARM
        anchor = _heal_anchor_date(d.get("repeat_anchor"), target)
        sound_mode = d.get("sound_mode", SOUND_MODE_SINGLE)
        if sound_mode not in SOUND_MODE_CHOICES:
            sound_mode = SOUND_MODE_SINGLE
        # booleans pass through raw: __init__ runs the canonical healer, so
        # legacy string flags ("False") cannot silently invert themselves
        try:
            return cls(
                name=name,
                description=description,
                target=target,
                repeat=d.get("repeat", REPEAT_NONE),
                sound=d.get("sound", "tick"),
                volume=d.get("volume", 5),
                color_mode=d.get("color_mode", COLOR_TEMPERATURE),
                color=d.get("color", DEFAULT_COLOR),
                enabled=d.get("enabled", True),
                id=d.get("id"),
                fired=d.get("fired", False),
                interval_minutes=d.get("interval_minutes", DEFAULT_INTERVAL_MINUTES),
                kind=kind,
                show_notification=d.get("show_notification", True),
                show_in_top_bar=d.get("show_in_top_bar", True),
                repeat_anchor=anchor,
                sound_mode=sound_mode,
                sound_rules=d.get("sound_rules"),
                auto_limit_key=d.get("auto_limit_key"),
            )
        except (TypeError, ValueError, AttributeError):
            return None

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

    def shift(self, minutes=0):
        """Shift the existing target forward or backward, regardless of now."""
        try:
            minutes = int(minutes)
        except (TypeError, ValueError):
            minutes = 0
        self.target += datetime.timedelta(minutes=minutes)
        if self.target > datetime.datetime.now():
            self.fired = False
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
        if self.repeat == REPEAT_INTERVAL:
            step = datetime.timedelta(minutes=max(1, self.interval_minutes))
        elif self.repeat == REPEAT_DAILY:
            step = datetime.timedelta(days=1)
        elif self.repeat == REPEAT_WEEKLY:
            step = datetime.timedelta(weeks=1)
        elif self.repeat == REPEAT_MONTHLY:
            return self._advance_monthly(now)
        elif self.repeat == REPEAT_YEARLY:
            return self._advance_yearly(now)
        else:
            self.fired = True
            return False
        while self.target <= now:
            self.target += step
        self.fired = False
        return True

    def _advance_monthly(self, now):
        """Roll a monthly timer to its next occurrence past ``now``.

        The anchor day is preserved and clamped per month (31 Jan -> 28 Feb ->
        31 Mar), so we never derive March from the clamped February target.
        Like the plain repeat kinds, a target already in the future is a
        no-op: advance() must never skip the next occurrence.
        """
        if self.target > now:
            self.fired = False
            return True
        nxt = _next_monthly_after(self, self.target)
        while nxt <= now:
            nxt = _next_monthly_after(self, nxt)
        self.target = nxt
        self.fired = False
        return True

    def _advance_yearly(self, now):
        """Roll a yearly timer to its next occurrence past ``now``.

        Future target is a no-op, matching the daily/weekly/interval kinds.
        """
        if self.target > now:
            self.fired = False
            return True
        nxt = _next_yearly_after(self, self.target)
        while nxt <= now:
            nxt = _next_yearly_after(self, nxt)
        self.target = nxt
        self.fired = False
        return True


def limit_window(name, hours=5, anchor=None, now=None, **kw):
    """A rolling usage window: it opened at `anchor` and rolls every `hours`.

    Written for "my 5-hour agent limit started at 09:20": the first target is
    anchor + 5h, and it keeps rolling from there, so after a laptop has been
    shut for two days the timer still names the NEXT reset rather than a
    string of missed ones.
    """
    now = now or datetime.datetime.now()
    anchor = anchor or now
    minutes = max(1, int(round(float(hours) * 60)))
    target = anchor + datetime.timedelta(minutes=minutes)
    timer = Timer(name=name, target=target, repeat=REPEAT_INTERVAL,
                  interval_minutes=minutes, **kw)
    # anchored in the past (the window opened this morning) -> roll forward
    if timer.target <= now:
        timer.advance(now)
    return timer


def snooze_clone(timer, minutes=10, now=None):
    """A one-shot reminder for THIS occurrence of a fired repeating timer.

    A fired repeating timer has already advanced to its NEXT occurrence by
    the time the user clicks Snooze (``collect_due`` rolls it before the
    toast shows); snoozing the object itself would shift the whole series.
    This builds a fresh one-shot Timer at ``now + minutes`` carrying the
    fired timer's full behaviour, with a brand-new ID, and leaves the
    original on its advanced schedule.
    """
    now = now or datetime.datetime.now()
    try:
        minutes = max(1, int(minutes))
    except (TypeError, ValueError):
        minutes = 10
    return Timer(
        name=timer.name,
        description=timer.description,
        target=now + datetime.timedelta(minutes=minutes),
        repeat=REPEAT_NONE,
        sound=timer.sound,
        volume=timer.volume,
        color_mode=timer.color_mode,
        color=timer.color,
        enabled=True,
        fired=False,
        kind=timer.kind,
        show_notification=timer.show_notification,
        show_in_top_bar=timer.show_in_top_bar,
        sound_mode=timer.sound_mode,
        sound_rules=[dict(r) for r in timer.sound_rules],
    )


def describe(timer, now=None):
    """Plain words for the row/tooltip: what it is and when it lands.

    A bare countdown is not enough for a rolling window - "in 12m" leaves
    you guessing whether that is the reset or the next one.
    """
    now = now or datetime.datetime.now()
    rem = timer.remaining(now)
    if rem <= 0:
        when = "now"
    else:
        mins = int(rem // 60)
        if mins < 60:
            when = f"in {mins}m"
        else:
            hours, mins = divmod(mins, 60)
            when = f"in {hours}h" if not mins else f"in {hours}h {mins:02d}m"
    at = timer.target.strftime("%H:%M")
    bits = [f"{timer.name} - {when} (at {at})"]
    if timer.repeat == REPEAT_INTERVAL:
        every = timer.interval_minutes
        if every % 60 == 0:
            bits.append(f"every {every // 60}h")
        else:
            bits.append(f"every {every}m")
    elif timer.repeat != REPEAT_NONE:
        bits.append(timer.repeat)
    if not timer.enabled:
        bits.append("paused")
    return " - ".join(bits)


def load_timers(raw):
    """Parse the stored list, skipping anything corrupt.

    Duplicate, empty or non-string IDs are replaced with a fresh one: two
    timers sharing an id would make "delete the alarm" take the wrong timer
    (or both), and an id the dialog cannot round-trip is a permanent
    non-edit. Content is preserved, only the id changes.
    """
    if not isinstance(raw, list):
        return []
    out = []
    seen = set()
    for entry in raw:
        t = Timer.from_dict(entry)
        if t is None:
            continue
        if not isinstance(t.id, str) or not t.id.strip() or t.id in seen:
            t.id = uuid.uuid4().hex[:12]
        seen.add(t.id)
        out.append(t)
    return out


def save_timers(timers):
    return [t.to_dict() for t in timers]


def next_due(timers, now=None, *, topbar_only=False):
    """The soonest enabled, unfired timer — the one worth showing.

    With ``topbar_only=True`` timers whose ``show_in_top_bar`` is False are
    ignored: a hidden timer keeps firing, but the top bar shows the nearest
    visible one.
    """
    now = now or datetime.datetime.now()
    live = [t for t in timers if t.enabled and not t.fired]
    if topbar_only:
        live = [t for t in live if t.show_in_top_bar]
    if not live:
        return None
    return min(live, key=lambda t: t.target)


def missed_attention(timers, missed_ids, now=None):
    """One-shot timers from ``missed_ids`` that still deserve a red alert.

    A one-shot timer that FIRED (its moment passed) lands in ``missed_ids``
    until it is dealt with. This helper decides which of those ids still
    warrant the "passed event" attention indicator:

    * unknown ids and timers that no longer exist are skipped,
    * disabled timers are skipped (the user turned the event off),
    * re-armed (snoozed) timers are skipped: ``snooze()`` moved the target
      into the future and cleared ``fired``, so ``fired and target < now``
      is False again.

    Repeating timers are never candidates — they roll to their next
    occurrence and are not "missed", they are merely next.
    """
    now = now or datetime.datetime.now()
    by_id = {t.id: t for t in timers}
    out = []
    for tid in missed_ids or ():
        t = by_id.get(tid)
        if t is None or not t.enabled:
            continue
        if t.repeat == REPEAT_NONE and t.fired and t.target < now:
            out.append(t)
    return out


def collect_due(timers, now=None):
    """Every timer that has come due, advancing repeats past `now`."""
    now = now or datetime.datetime.now()
    fired = []
    for t in timers:
        if t.is_due(now):
            fired.append(t)
            t.advance(now)
    return fired


# ----------------------------------------------------- calendar query helpers

def occurs_on_date(timer, date):
    """Does ``timer`` recur on ``date``? Pure: never mutates the timer.

    Recurrence basis for daily/weekly/monthly/yearly is the immutable
    recurrence ANCHOR (the timer's creation date), NOT the mutable
    next-fire ``target``. Using ``target`` here meant that as soon as a
    recurring timer was advanced by ``collect_due``/``advance`` its apparent
    calendar history got rewritten and previously valid occurrences vanished.

    ``REPEAT_NONE`` keeps comparing against the current (one-shot) target.
    """
    if not isinstance(date, datetime.date):
        return False
    target_date = timer.target.date()
    if timer.repeat == REPEAT_NONE:
        return date == target_date
    # Recurring: bound by the immutable anchor, never the mutable target.
    anchor = _anchor_date(timer)
    if date < anchor:
        return False
    if timer.repeat == REPEAT_DAILY:
        return True
    if timer.repeat == REPEAT_WEEKLY:
        return (date - anchor).days % 7 == 0
    if timer.repeat == REPEAT_MONTHLY:
        day = min(anchor.day, calendar.monthrange(date.year, date.month)[1])
        return date.day == day
    if timer.repeat == REPEAT_YEARLY:
        day = min(anchor.day, calendar.monthrange(date.year, anchor.month)[1])
        return date.month == anchor.month and date.day == day
    return False


def occurrences_in_month(timer, year, month):
    """All dates in ``(year, month)`` on which ``timer`` recurs.

    Pure and bounded: a visible month has at most 31 date markers, so the
    loop is inherently small and never runs unbounded.
    """
    if not (isinstance(year, int) and isinstance(month, int)):
        return []
    if not (1 <= month <= 12):
        return []
    last = calendar.monthrange(year, month)[1]
    out = []
    for d in range(1, last + 1):
        date = datetime.date(year, month, d)
        if occurs_on_date(timer, date):
            out.append(date)
    return out


# --------------------------------------------------------- T-1005 sound policy

def _rule_matches_window(rule, minute):
    """Does a pool rule's time window include ``minute`` (minute-of-day)?"""
    if rule.get("all_day"):
        return True
    start = rule.get("start_minute", 0)
    end = rule.get("end_minute", 0)
    # start == end with all_day=False is an invalid zero-length window; the UI
    # refuses to save one, but if one slipped through it matches nothing rather
    # than collapsing to "always on".
    if start == end:
        return False
    if start < end:
        return start <= minute < end          # normal window
    return minute >= start or minute < end      # overnight window


def eligible_sound_rules(timer, when):
    """Pool rows that are enabled AND whose time window covers ``when``.

    Pure: never mutates the timer. Two overlapping rows using the same sound
    count as two candidates on purpose (the spec forbids silent dedupe).
    """
    if timer.sound_mode != SOUND_MODE_POOL:
        return []
    minute = _minute_of_day(when)
    out = []
    for rule in timer.sound_rules:
        if not rule.get("enabled"):
            continue
        if _rule_matches_window(rule, minute):
            out.append(rule)
    return out


def choose_timer_sound(timer, when, rng=None):
    """Pick the sound to play at ``when``.

    Returns ``(sound_ref, effective_volume)`` or ``None``.

    * SINGLE: the timer's own ``sound`` / ``volume``.
    * POOL:   a random eligible row's sound, with its explicit volume or the
      timer's volume when the rule inherits.

    In POOL mode, if no rule is eligible the timer is SILENT (returns None).
    There is deliberately no fallback to ``timer.sound`` — time-specific silence
    must be expressible.
    """
    rng = rng or _RNG
    if timer.sound_mode == SOUND_MODE_SINGLE:
        return (timer.sound, timer.volume)
    eligible = eligible_sound_rules(timer, when)
    if not eligible:
        return None
    rule = rng.choice(eligible)
    volume = rule.get("volume")
    if volume is None:
        volume = timer.volume
    return (rule.get("sound"), volume)
