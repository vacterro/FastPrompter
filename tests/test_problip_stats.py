"""T-1238-A: aggregate statistics and 100K milestone semantics."""

from __future__ import annotations

import datetime as dt

from fastprompter.core.problip_store import (
    INT64_MAX,
    PREMIUM_REWARD_BLIPS,
    PeriodKeys,
    ProblipStore,
    StatsLogic,
    StatsRecord,
    increment_saturating,
)


def test_period_keys_use_local_day_iso_week_and_calendar_month():
    assert PeriodKeys.of(dt.date(2026, 9, 9)) == PeriodKeys(
        day="2026-09-09", week="2026-W37", month="2026-09")
    # ISO week-year differs from calendar year at this boundary.
    assert PeriodKeys.of(dt.date(2021, 1, 1)).week == "2020-W53"
    assert PeriodKeys.of(dt.date(2021, 1, 3)).week == "2020-W53"
    assert PeriodKeys.of(dt.date(2021, 1, 4)).week == "2021-W01"


def test_aware_datetime_is_converted_to_machine_local_calendar_date(monkeypatch):
    value = dt.datetime(2026, 9, 9, 0, 30, tzinfo=dt.UTC)
    # astimezone() without an argument is the implementation's local-zone
    # boundary. Make the test independent of which zone the test runner uses.
    local_date = value.astimezone().date()
    assert PeriodKeys.of(value).day == local_date.isoformat()


def test_pure_stats_snapshot_rollover_does_not_touch_total():
    previous = PeriodKeys.of(dt.date(2026, 9, 8))
    current = PeriodKeys.of(dt.date(2026, 9, 9))
    record = StatsRecord(
        day_key=previous.day,
        today_count=12,
        week_key=previous.week,
        week_count=12,
        month_key=previous.month,
        month_count=12,
        total_count=99,
    )

    shown = StatsLogic.snapshot(record, current)
    assert shown.today_count == 0
    assert shown.week_count == 12  # same ISO week
    assert shown.month_count == 12  # same calendar month
    assert shown.total_count == 99

    after = StatsLogic.after_blip(record, current)
    assert after.day_key == current.day
    assert after.today_count == 1
    assert after.week_count == 13
    assert after.month_count == 13
    assert after.total_count == 100


def test_stats_store_counts_only_explicit_successes_and_survives_reopen(tmp_path):
    db_path = tmp_path / "problip.db"
    day = dt.date(2026, 9, 9)
    store = ProblipStore(db_path)
    try:
        first = store.record_successful_blip(day)
        second = store.record_successful_blip(day)
        assert (first.today_count, first.week_count, first.month_count, first.total_count) == (1, 1, 1, 1)
        assert (second.today_count, second.week_count, second.month_count, second.total_count) == (2, 2, 2, 2)
    finally:
        store.close()

    reopened = ProblipStore(db_path)
    try:
        loaded = reopened.get_stats(day)
        assert loaded.today_count == 2
        assert loaded.week_count == 2
        assert loaded.month_count == 2
        assert loaded.total_count == 2
    finally:
        reopened.close()


def test_period_rollover_resets_only_changed_buckets(tmp_path):
    store = ProblipStore(tmp_path / "problip.db")
    try:
        monday = dt.date(2026, 9, 7)
        sunday = dt.date(2026, 9, 13)
        next_monday = dt.date(2026, 9, 14)
        store.record_successful_blip(monday)
        store.record_successful_blip(sunday)
        rolled = store.record_successful_blip(next_monday)
        assert rolled.today_count == 1
        assert rolled.week_count == 1
        assert rolled.month_count == 3
        assert rolled.total_count == 3
    finally:
        store.close()


def test_saturating_counters_never_wrap_and_negative_values_are_zero():
    assert increment_saturating(-10) == 1
    assert increment_saturating("garbage") == 1
    assert increment_saturating(INT64_MAX) == INT64_MAX
    assert StatsLogic.sanitize(StatsRecord(
        today_count=-5,
        week_count="not numeric",
        month_count=INT64_MAX + 100,
        total_count=-1,
    )) == StatsRecord(month_count=INT64_MAX)


def test_store_saturates_existing_row_instead_of_wrapping(tmp_path):
    db_path = tmp_path / "problip.db"
    store = ProblipStore(db_path)
    day = dt.date(2026, 9, 9)
    keys = PeriodKeys.of(day)
    try:
        store._conn.execute(
            "UPDATE problip_stats SET day_key=?, today_count=?, week_key=?, "
            "week_count=?, month_key=?, month_count=?, total_count=? WHERE id=1",
            (keys.day, INT64_MAX, keys.week, INT64_MAX, keys.month, INT64_MAX,
             INT64_MAX),
        )
        store._conn.commit()
        snapshot = store.record_successful_blip(day)
        assert snapshot.today_count == INT64_MAX
        assert snapshot.week_count == INT64_MAX
        assert snapshot.month_count == INT64_MAX
        assert snapshot.total_count == INT64_MAX
    finally:
        store.close()


def test_reward_latches_at_exact_100000_and_self_heals_on_load(tmp_path):
    db_path = tmp_path / "problip.db"
    store = ProblipStore(db_path)
    day = dt.date(2026, 9, 9)
    keys = PeriodKeys.of(day)
    try:
        store._conn.execute(
            "UPDATE problip_stats SET day_key=?, today_count=0, week_key=?, "
            "week_count=0, month_key=?, month_count=0, total_count=?, "
            "earned_premium=0 WHERE id=1",
            (keys.day, keys.week, keys.month, PREMIUM_REWARD_BLIPS - 1),
        )
        store._conn.commit()
        before = store.get_stats(day)
        assert before.earned_premium is False
        reached = store.record_successful_blip(day)
        assert reached.total_count == PREMIUM_REWARD_BLIPS
        assert reached.earned_premium is True

        # A corrupt/lost flag cannot clear an earned reward when the total says
        # the threshold has already been reached.
        store._conn.execute("UPDATE problip_stats SET earned_premium=0 WHERE id=1")
        store._conn.commit()
        healed = store.get_stats(day)
        assert healed.earned_premium is True
        assert store._conn.execute(
            "SELECT earned_premium FROM problip_stats WHERE id=1").fetchone()[0] == 1
    finally:
        store.close()


def test_earned_flag_is_irreversible_when_total_is_below_threshold(tmp_path):
    store = ProblipStore(tmp_path / "problip.db")
    day = dt.date(2026, 9, 9)
    try:
        store._conn.execute("UPDATE problip_stats SET earned_premium=1 WHERE id=1")
        store._conn.commit()
        snapshot = store.record_successful_blip(day)
        assert snapshot.earned_premium is True
        assert store.get_stats(day).earned_premium is True
    finally:
        store.close()


def test_stats_are_stored_as_one_aggregate_row(tmp_path):
    store = ProblipStore(tmp_path / "problip.db")
    try:
        store.record_successful_blip(dt.date(2026, 9, 9))
        rows = store._conn.execute("SELECT COUNT(*) FROM problip_stats").fetchone()[0]
        assert rows == 1
        # No event history table is created; the aggregate is the complete
        # statistics representation.
        names = {
            row[0] for row in store._conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")
        }
        assert "problip_events" not in names
    finally:
        store.close()
