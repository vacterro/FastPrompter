"""Human duration and clock-time parsing.

Accepts what people actually type when they want to be reminded:

    "4 days 11 hours"   "4d 11h"    "90m"      "1h30"
    "2 недели 3 дня"    "45 мин"    "1.5h"     "0:45"
    "18:30"             "tomorrow 9:00"        "завтра 09:00"

Returns either a timedelta (a delay from now) or a datetime (an absolute
moment). Anything unparseable returns None rather than guessing — a timer
that silently fires at the wrong moment is worse than one that refuses to
be created.
"""

from __future__ import annotations

import datetime
import re

# Longest-first so "months" can't be eaten by "mo", and Russian stems are
# truncated to what survives every case ending ("недел|я|и|ю").
_UNITS: list[tuple[tuple[str, ...], float]] = [
    (("weeks", "week", "wk", "w", "недел"), 7 * 24 * 3600),
    (("days", "day", "d", "дней", "дня", "день", "д"), 24 * 3600),
    (("hours", "hour", "hrs", "hr", "h", "часов", "часа", "час", "ч"), 3600),
    (("minutes", "minute", "mins", "min", "m", "минут", "мин", "м"), 60),
    (("seconds", "second", "secs", "sec", "s", "секунд", "сек", "с"), 1),
]

_UNIT_LOOKUP: dict[str, float] = {}
for _names, _secs in _UNITS:
    for _n in _names:
        _UNIT_LOOKUP[_n] = _secs

# number + optional unit word
_PART_RE = re.compile(
    r"(\d+(?:[.,]\d+)?)\s*([a-zA-Zа-яА-ЯёЁ]*)",
    re.UNICODE,
)
_CLOCK_RE = re.compile(r"^\s*(\d{1,2})\s*[:.]\s*(\d{2})\s*$")
_HM_SHORTHAND_RE = re.compile(r"^\s*(\d{1,2})\s*[hч]\s*(\d{1,2})\s*$", re.IGNORECASE)

_TOMORROW = ("tomorrow", "tmr", "завтра")
_TODAY = ("today", "сегодня")

MAX_SECONDS = 365 * 24 * 3600  # a year; beyond that it's a typo, not a timer


def _match_unit(word: str) -> float | None:
    w = word.lower()
    if not w:
        return None
    if w in _UNIT_LOOKUP:
        return _UNIT_LOOKUP[w]
    # prefix match for inflected Russian ("недели", "минуток")
    for names, secs in _UNITS:
        for n in names:
            if len(n) > 1 and w.startswith(n):
                return secs
    return None


def parse_duration(text: str) -> datetime.timedelta | None:
    """"4 days 11 hours" -> timedelta. None if nothing usable."""
    if not text:
        return None
    s = text.strip().lower()
    if not s:
        return None

    # "1h30" / "2ч15" - bare trailing number means minutes
    m = _HM_SHORTHAND_RE.match(s)
    if m:
        h, mins = int(m.group(1)), int(m.group(2))
        if mins >= 60:
            return None
        return datetime.timedelta(hours=h, minutes=mins)

    total = 0.0
    matched = False
    last_end = 0
    pending: float | None = None
    for m in _PART_RE.finditer(s):
        # reject junk between the parts ("4 days blah 2h")
        between = s[last_end:m.start()].strip(" ,;+&\t")
        if between and between not in ("and", "и"):
            return None
        last_end = m.end()

        value = float(m.group(1).replace(",", "."))
        unit = _match_unit(m.group(2))
        if unit is None:
            if m.group(2):
                return None  # a word we don't know - refuse, don't guess
            # bare number: remember it, resolve after the loop
            if pending is not None:
                return None  # "4 5" is not a duration
            pending = value
            matched = True
            continue
        total += value * unit
        matched = True

    trailing = s[last_end:].strip(" ,;+&\t")
    if trailing and trailing not in ("and", "и"):
        return None
    if not matched:
        return None

    if pending is not None:
        # a lone number means minutes ("45"), but "1h 30" means 30 minutes too
        total += pending * 60
    if total <= 0 or total > MAX_SECONDS:
        return None
    return datetime.timedelta(seconds=round(total))


def parse_when(text: str, now: datetime.datetime | None = None) -> datetime.datetime | None:
    """Absolute target time: "18:30", "tomorrow 9:00". None if not one."""
    if not text:
        return None
    now = now or datetime.datetime.now()
    s = text.strip().lower()

    day_offset = 0
    for word in _TOMORROW:
        if s.startswith(word):
            day_offset = 1
            s = s[len(word):].strip()
            break
    else:
        for word in _TODAY:
            if s.startswith(word):
                s = s[len(word):].strip()
                break

    m = _CLOCK_RE.match(s)
    if not m:
        return None
    hour, minute = int(m.group(1)), int(m.group(2))
    if hour > 23 or minute > 59:
        return None

    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    target += datetime.timedelta(days=day_offset)
    # a bare time that already passed today means tomorrow
    if day_offset == 0 and target <= now:
        target += datetime.timedelta(days=1)
    return target


def resolve_target(text: str, now: datetime.datetime | None = None) -> datetime.datetime | None:
    """Turn whatever the user typed into an absolute moment."""
    now = now or datetime.datetime.now()
    when = parse_when(text, now)
    if when is not None:
        return when
    delta = parse_duration(text)
    if delta is not None:
        return now + delta
    return None


def format_remaining(seconds: float, short: bool = False) -> str:
    """Human countdown: "4d 11h", "2h 05m", "45s", "now"."""
    seconds = int(max(0, seconds))
    if seconds <= 0:
        return "now"
    d, rem = divmod(seconds, 24 * 3600)
    h, rem = divmod(rem, 3600)
    m, s = divmod(rem, 60)
    if d:
        return f"{d}d {h}h" if not short else f"{d}d"
    if h:
        return f"{h}h {m:02d}m" if not short else f"{h}h"
    if m:
        return f"{m}m {s:02d}s" if not short else f"{m}m"
    return f"{s}s"


# Ready-made choices for the dropdown, so nobody has to type at all.
PRESETS: list[tuple[str, str]] = [
    ("5 minutes", "5m"),
    ("15 minutes", "15m"),
    ("30 minutes", "30m"),
    ("1 hour", "1h"),
    ("2 hours", "2h"),
    ("4 hours", "4h"),
    ("5 hours", "5h"),
    ("8 hours", "8h"),
    ("12 hours", "12h"),
    ("1 day", "1d"),
    ("2 days", "2d"),
    ("4 days 11 hours", "4d 11h"),
    ("1 week", "1w"),
]
