"""The ONE canonical interval-occurrence calculator (CORE-004 / CORE-006).

Before this module the clock-aligned contract lived in two places -- the
scheduler in ``main.py`` and the top-bar countdown next to it -- and both
computed it as ``minute_of_day % minutes == 0``. That expression measures the
interval inside a single calendar day, so it silently resets at midnight:

* a 100-minute rule firing at 23:20 fired again at 00:00, 40 minutes later;
* a 2880-minute (48 hour) rule became eligible every midnight, i.e. daily.

Occurrences are now anchored to one absolute wall clock instant and measured
continuously from it, so a cadence is the same before and after midnight.
Conventional presets are unaffected: every interval that divides 1440 (5, 10,
15, 20, 30, 60, 90, 120, 240, 720, 1440 minutes) still lands on the same
round wall-clock times, because midnight is a multiple of the anchor.

Both consumers -- the firing scheduler and the top-bar countdown -- call
``next_eligible`` here, so the countdown can never advertise an occurrence the
scheduler will suppress, and the scheduler can never fire one the countdown
did not account for.

Scope note: arithmetic is wall-clock (naive local datetime). A DST jump moves
the local clock, and the cadence follows the local clock; that is the same
contract the pre-existing daypart presets relied on.

Implementation note: every datetime is derived from ``ANCHOR``'s own type
rather than from the ``datetime`` module attribute. Tests replace
``datetime.datetime`` to control "now", and a module that re-read that
attribute at call time would try to construct its own anchor out of the fake.
"""

from __future__ import annotations

import datetime

#: The phase reference for clock-aligned rules. Any fixed instant works; a
#: round local midnight keeps every divisor of 1440 on its historical times.
ANCHOR = datetime.datetime(2000, 1, 1, 0, 0)

#: The REAL datetime class, captured through the anchor before any caller can
#: substitute the module attribute.
_DT = type(ANCHOR)
_TD = datetime.timedelta

#: A rule whose next occurrence is further away than this is reported as
#: having no occurrence rather than searched for forever.
HORIZON_DAYS = 400

#: Hard ceiling on boundary probes, so a hostile rule can never spin.
MAX_PROBES = 2000


def minute_index(moment: datetime.datetime) -> int:
    """Whole minutes from ANCHOR to ``moment`` (may be negative)."""
    return int((moment - ANCHOR).total_seconds() // 60)


def minute_of_day(moment: datetime.datetime) -> int:
    return moment.hour * 60 + moment.minute


def in_active_window(minute: int, start: int, end: int) -> bool:
    """True when ``minute`` falls inside ``[start, end]``.

    ``start > end`` means the window wraps past midnight: 22:00-06:00 is
    ``start=1320, end=360`` and matches both 23:00 and 02:00.
    """
    if start <= end:
        return start <= minute <= end
    return minute >= start or minute <= end


def _rule_window(rule: dict) -> tuple[int, int] | None:
    """The rule's active window as ``(start, end)``, or None for all-day."""
    if rule.get("all_day", True):
        return None
    try:
        start = int(rule.get("start_minute", 0))
        end = int(rule.get("end_minute", 1439))
    except (TypeError, ValueError):
        return None
    start = max(0, min(1439, start))
    end = max(0, min(1439, end))
    return start, end


def _minutes_of(rule: dict) -> int | None:
    try:
        return max(1, int(rule.get("minutes") or 60))
    except (TypeError, ValueError):
        return None


def _at_minute_index(index: int) -> datetime.datetime:
    """The moment ``index`` minutes after ANCHOR."""
    return ANCHOR + _TD(minutes=index)


def _minute_floor(moment: datetime.datetime) -> datetime.datetime:
    return moment.replace(second=0, microsecond=0)


def next_clock_boundary(moment: datetime.datetime, minutes: int,
                        *, inclusive: bool) -> datetime.datetime:
    """The first clock-aligned occurrence at or after ``moment``.

    ``inclusive=True`` returns ``moment``'s minute when it sits exactly on a
    boundary, which is what the firing path needs: a late tick during the
    boundary minute must still see that boundary.
    """
    minutes = max(1, int(minutes))
    index = minute_index(moment)
    if inclusive:
        if index % minutes == 0:
            target = index
        else:
            target = ((index // minutes) + 1) * minutes
    else:
        target = ((index // minutes) + 1) * minutes
    return _at_minute_index(target)


def _window_opens(moment: datetime.datetime, start: int, end: int):
    """Every moment the active window opens, ordered, around ``moment``.

    A same-day window opens once per day at ``start``. A wrapping window
    (``start > end``) also opens at midnight, because its post-midnight half
    begins then.
    """
    opens: list[datetime.datetime] = []
    base = _minute_floor(moment)
    midnight = base.replace(hour=0, minute=0)
    for offset in (-1, 0, 1, 2):
        day_start = midnight + _TD(days=offset)
        opens.append(day_start + _TD(minutes=start))
        if start > end:
            opens.append(day_start)
    opens.sort()
    return opens


def next_window_open(moment: datetime.datetime, start: int, end: int):
    """The first moment at or after ``moment`` that is inside the window."""
    if in_active_window(minute_of_day(moment), start, end):
        return moment
    for candidate in _window_opens(moment, start, end):
        if candidate >= moment:
            return candidate
    return None


def next_clock_occurrence(rule: dict, moment: datetime.datetime,
                          *, inclusive: bool) -> datetime.datetime | None:
    """The next clock-aligned occurrence that the window actually allows.

    CORE-006: the old code inspected only the NEAREST mathematical boundary
    and gave up when that boundary fell outside the active window, so a
    morning-only rule vanished from the top bar for the rest of the day even
    though tomorrow morning was a valid occurrence. The search now walks
    forward to the first boundary the window admits.
    """
    minutes = _minutes_of(rule)
    if minutes is None:
        return None
    window = _rule_window(rule)
    probe = next_clock_boundary(moment, minutes, inclusive=inclusive)
    if window is None:
        return probe
    start, end = window
    horizon = moment + _TD(days=HORIZON_DAYS)
    for _ in range(MAX_PROBES):
        if probe > horizon:
            return None
        if in_active_window(minute_of_day(probe), start, end):
            return probe
        # CORE-004 (audit/18): ``inclusive=False`` ALREADY advances to the
        # next boundary, so adding a minute here skipped an eligible boundary
        # whenever ``minutes`` was 1. The search could walk straight past the
        # only valid minute of a narrow window and report no occurrence while
        # the scheduler still fired it. Ask for the exclusive next boundary
        # from the current probe, which keeps the probe order strict.
        probe = next_clock_boundary(probe, minutes, inclusive=False)
    return None


def next_elapsed_occurrence(rule: dict, moment: datetime.datetime,
                            now_ts: float) -> datetime.datetime | None:
    """The next occurrence of an elapsed-aligned rule.

    The deadline is ``last_fired + minutes``; when the rule has never fired the
    countdown starts from now. CORE-006: an active window is applied here too,
    so the announced moment is the one the scheduler will actually use -- an
    elapsed deadline that lands in a closed window fires when the window next
    opens, not when the arithmetic says.
    """
    minutes = _minutes_of(rule)
    if minutes is None:
        return None
    try:
        last = float(rule.get("last_fired") or 0.0)
    except (TypeError, ValueError):
        last = 0.0
    if last <= 0.0:
        deadline = moment
    else:
        # The wall clock is the anchor for an elapsed rule, exactly as the
        # firing path measures it (``now_ts - last >= minutes * 60``). Express
        # the result as an offset from ``moment`` so no datetime is rebuilt
        # from the epoch.
        remaining = last + minutes * 60.0 - now_ts
        deadline = moment + _TD(seconds=remaining)
    window = _rule_window(rule)
    if window is None:
        return deadline
    start, end = window
    # CORE-005 (audit/18): the deadline is the EARLIEST permitted firing
    # instant, not necessarily a future one. The old code asked only whether
    # the deadline's clock minute sat inside the window, and returned it when
    # it did -- even when that minute was hours in the past. A rule that
    # missed its deadline while the app was closed then showed a permanent
    # "due now" countdown while the scheduler's active-hours guard correctly
    # refused to fire. Reconcile with the current moment first.
    if deadline <= moment:
        if in_active_window(minute_of_day(moment), start, end):
            return moment
        return next_window_open(moment, start, end)
    if in_active_window(minute_of_day(deadline), start, end):
        return deadline
    return next_window_open(deadline, start, end)


def next_eligible(rule: dict, moment: datetime.datetime,
                  *, now_ts: float | None = None,
                  inclusive: bool = False) -> datetime.datetime | None:
    """The ONE next eligible occurrence of ``rule`` at or after ``moment``.

    ``inclusive`` matters for the firing path: pass the current minute (second
    zero) with ``inclusive=True`` and an occurrence equal to it is returned, so
    a late sample still catches the boundary it belongs to.

    An ELAPSED rule is measured against the real wall clock, exactly as the
    firing path measures it (``now_ts - last >= minutes * 60``). Without an
    explicit ``now_ts`` the module reads ``time.time()`` rather than deriving
    one from ``moment``, because the caller's ``moment`` may be a test clock
    while the stored ``last_fired`` is a real epoch.
    """
    align_mode = str(rule.get("align_mode", "clock"))
    if align_mode == "clock":
        return next_clock_occurrence(rule, moment, inclusive=inclusive)
    if now_ts is None:
        import time as _time

        now_ts = _time.time()
    return next_elapsed_occurrence(rule, moment, now_ts)


def is_due_now(rule: dict, now_dt: datetime.datetime) -> bool:
    """True when ``now_dt`` sits inside this rule's current occurrence minute.

    The firing condition, expressed through the same calculator the countdown
    uses. ``last_fired_minute`` still provides the once-per-minute dedupe; this
    only answers "is the current minute an occurrence".
    """
    current_minute = _minute_floor(now_dt)
    occurrence = next_eligible(rule, current_minute, inclusive=True)
    if occurrence is None:
        return False
    return occurrence == current_minute


def seconds_until_next(rule: dict, now_dt: datetime.datetime) -> float | None:
    """Seconds until the next eligible occurrence, or None if there is none.

    Returns 0.0 while the current minute IS the occurrence and it has not
    fired yet, so the top bar can show "now" during the firing grace period.
    A boundary minute already stamped in ``last_fired_minute`` is in the past
    by definition, so the countdown rolls forward to the following occurrence
    instead of sitting at zero.
    """
    current_minute = _minute_floor(now_dt)
    occurrence = next_eligible(rule, current_minute, inclusive=True)
    if occurrence is None:
        return None
    if occurrence == current_minute:
        fired_key = rule.get("last_fired_minute")
        if fired_key and fired_key == now_dt.strftime("%Y-%m-%d %H:%M"):
            # This occurrence already fired; the NEXT one is what remains.
            occurrence = next_eligible(
                rule, current_minute + _TD(minutes=1), inclusive=True)
            if occurrence is None:
                return None
    return max(0.0, (occurrence - now_dt).total_seconds())
