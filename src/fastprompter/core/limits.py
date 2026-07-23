"""Reading "limit reached" out of an agent's own words.

Agents say it in prose, in their chat transcript, and each one says it
differently. This turns that prose into a decision: is the limit hit right
now, and if the text names a reset time, when.

Qt-free and clock-injected, so every pattern is testable without an agent
running and without waiting for a real reset.

Two rules:

* **Ambiguity is NOT a limit.** A false "reached" pauses a queue that could
  have kept working; a false "clear" only means the watcher tries and the
  agent refuses. So a match has to be specific, and the word "limit" alone
  is not enough — "no limit", "limit: 200k" and "rate limits apply" are all
  ordinary UI text.
* **A time we did not read is None, never a guess.** Callers decide what
  window to assume; inventing "+5h" here would bury that guess where nobody
  can see it.
"""

from __future__ import annotations

import datetime
import re

# Phrases that mean the limit IS hit. Each is deliberately a full phrase,
# not the word "limit" - see the ambiguity rule above.
_HIT = (
    r"limit\s+reached",
    r"reached\s+your\s+(?:usage\s+)?limit",
    r"you'?ve\s+(?:hit|reached)\s+(?:the|your)\s+\w*\s*limit",
    r"out\s+of\s+(?:free\s+)?(?:messages|credits|usage)",
    r"quota\s+(?:exceeded|exhausted)",
    r"rate\s*limit(?:ed|\s+exceeded)",
    r"come\s+back\s+after\s+the\s+\w+\s+reset",
    r"try\s+again\s+(?:later|after|in|at)\b",
    r"usage\s+limit",
    r"daily\s+(?:free\s+)?limit",
)
# Phrases that look like a hit but are not — checked FIRST.
_NOT_HIT = (
    r"no\s+limit",
    r"unlimited",
    r"limits?\s+apply",
    r"limit:\s*\d",
    r"limit\s+is\s+\d",
    r"about\s+(?:usage\s+)?limits",
)

_HIT_RE = re.compile("|".join(_HIT), re.I)
_NOT_HIT_RE = re.compile("|".join(_NOT_HIT), re.I)

# "resets 3pm", "resets at 14:30", "back at 9 am", "available again at 21:05"
_AT_RE = re.compile(
    r"(?:reset[s]?|back|again|retry|available)\b[^.\n]{0,20}?"
    r"\bat\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?"
    r"|reset[s]?\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)",
    re.I)
# "resets in 2h 15m", "try again in 45 minutes", "in 3 hours"
_IN_RE = re.compile(
    r"\bin\s+(?:(\d+)\s*h(?:ours?|rs?)?)?\s*(?:(\d+)\s*m(?:in(?:ute)?s?)?)?",
    re.I)


class LimitState:
    """What the text said. `resets_at` is None when it named no time."""

    __slots__ = ("reached", "resets_at", "matched", "source")

    def __init__(self, reached=False, resets_at=None, matched="", source=""):
        self.reached = bool(reached)
        self.resets_at = resets_at
        self.matched = matched or ""
        self.source = source or ""

    def __repr__(self):
        when = self.resets_at.strftime("%H:%M") if self.resets_at else "unknown"
        return f"LimitState(reached={self.reached}, resets_at={when})"

    def __eq__(self, other):
        return (isinstance(other, LimitState)
                and self.reached == other.reached
                and self.resets_at == other.resets_at)


def _parse_at(text, now):
    """An absolute clock time in the text -> the next datetime it lands on."""
    m = _AT_RE.search(text)
    if not m:
        return None
    hour = m.group(1) or m.group(4)
    minute = m.group(2) or m.group(5) or "0"
    ampm = (m.group(3) or m.group(6) or "").lower()
    try:
        hour, minute = int(hour), int(minute)
    except (TypeError, ValueError):
        return None
    if ampm == "pm" and hour < 12:
        hour += 12
    elif ampm == "am" and hour == 12:
        hour = 0
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now:                     # already gone today -> tomorrow
        target += datetime.timedelta(days=1)
    return target


def _parse_in(text, now):
    """A relative "in 2h 15m" -> a datetime."""
    for m in _IN_RE.finditer(text):
        hours, mins = m.group(1), m.group(2)
        if not hours and not mins:
            continue                       # bare "in", e.g. "in the chat"
        delta = datetime.timedelta(hours=int(hours or 0),
                                   minutes=int(mins or 0))
        if delta.total_seconds() <= 0:
            continue
        return now + delta
    return None


def scan_text(text, now=None):
    """Read one blob of agent text into a LimitState.

    Looks at the LAST 4000 characters: a transcript keeps every limit
    message it ever printed, and an hour-old one must not read as current.
    """
    now = now or datetime.datetime.now()
    if not text:
        return LimitState(False)
    tail = text[-4000:]

    hit = _HIT_RE.search(tail)
    if not hit:
        return LimitState(False, source=tail[-200:])

    # a negation anywhere near the hit disqualifies it
    window = tail[max(0, hit.start() - 60):hit.end() + 60]
    if _NOT_HIT_RE.search(window):
        return LimitState(False, matched=hit.group(0), source=window)

    after = tail[hit.start():hit.start() + 300]
    resets = _parse_at(after, now) or _parse_in(after, now)
    return LimitState(True, resets, hit.group(0), window)


def assume_window(now=None, hours=5):
    """The fallback when the agent says it is limited but names no time.

    Kept separate and explicit so the guess is the CALLER's, visible in the
    UI as "assumed", rather than something scan_text quietly made up.
    """
    now = now or datetime.datetime.now()
    return now + datetime.timedelta(hours=float(hours))
