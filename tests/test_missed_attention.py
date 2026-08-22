"""Passed-event alert: which fired one-shot timers still nag."""

import datetime

from fastprompter.core.timers import (
    REPEAT_DAILY,
    REPEAT_NONE,
    Timer,
    missed_attention,
)

NOW = datetime.datetime(2026, 8, 10, 12, 0)


def mk(name, *, target=None, fired=True, enabled=True, repeat=REPEAT_NONE):
    return Timer(name=name, target=target or (NOW - datetime.timedelta(hours=1)),
                 fired=fired, enabled=enabled, repeat=repeat)


def test_a_fired_one_shot_still_nags():
    t = mk("rent")
    assert missed_attention([t], {t.id}, now=NOW) == [t]


def test_unknown_ids_are_ignored():
    t = mk("rent")
    assert missed_attention([t], {"nope"}, now=NOW) == []


def test_deleted_timers_stop_nagging():
    t = mk("rent")
    assert missed_attention([], {t.id}, now=NOW) == []


def test_disabled_timers_stop_nagging():
    t = mk("rent", enabled=False)
    assert missed_attention([t], {t.id}, now=NOW) == []


def test_snoozed_timers_stop_nagging():
    # snooze() re-arms: future target, fired cleared
    t = mk("rent", fired=False,
           target=NOW + datetime.timedelta(minutes=10))
    assert missed_attention([t], {t.id}, now=NOW) == []


def test_repeating_timers_never_nag():
    t = mk("standup", repeat=REPEAT_DAILY, fired=True,
           target=NOW - datetime.timedelta(hours=1))
    assert missed_attention([t], {t.id}, now=NOW) == []


def test_future_targets_do_not_nag():
    t = mk("rent", fired=True,
           target=NOW + datetime.timedelta(days=1))
    assert missed_attention([t], {t.id}, now=NOW) == []
