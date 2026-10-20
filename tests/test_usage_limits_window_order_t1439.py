"""Reading order of quota windows: the 5-hour bucket above the weekly one.

One account can bill several independent quota pools (Antigravity: the Gemini
models and the Claude/GPT models it hosts, each with its own weekly + 5h pair),
and the shared-account plane publishes each pool's windows weekly-first. Read in
that order the 5-hour window -- the one that refills today, and the one the
weekly window gates -- sits UNDER the weekly bar, so the user reads "7 days"
before the quota they can spend right now. The order is decided once, in
``resolved_windows``, which every drawing surface and the alerting path read.
"""

from __future__ import annotations

from fastprompter.core.usage_limits.model import (
    UsageWindow,
    display_windows,
    resolved_windows,
)


def _win(key, minutes, remaining, group="", label=""):
    return UsageWindow(key=key, duration_minutes=minutes, available=True,
                       used_percent=100.0 - remaining,
                       remaining_percent=float(remaining), resets_at_epoch=None,
                       group=group, group_label=label)


def _keys(windows):
    return [w.key for w in windows]


def test_a_weekly_first_input_is_read_5h_first():
    got = resolved_windows([_win("weekly", 10080, 50.0),
                            _win("five_hour", 300, 50.0)], now=0)
    assert _keys(got) == ["five_hour", "weekly"]


def test_the_shortest_of_three_buckets_comes_first():
    got = resolved_windows([_win("monthly", 43200, 50.0),
                            _win("weekly", 10080, 50.0),
                            _win("five_hour", 300, 50.0)], now=0)
    assert _keys(got) == ["five_hour", "weekly", "monthly"]


def test_a_two_pool_plane_payload_reads_5h_first_in_each_pool():
    # The real AG3 shape: pool 0 and pool 1, each sent weekly-first.
    from fastprompter.core.usage_limits import sai_accounts as sai
    payload = [
        {"pool_index": 0, "window": "weekly", "remaining_fraction": 0.5,
         "reset_time": "2026-10-12T00:00:00Z"},
        {"pool_index": 0, "window": "5h", "remaining_fraction": 0.5,
         "reset_time": "2026-10-06T12:00:00Z"},
        {"pool_index": 1, "window": "weekly", "remaining_fraction": 0.9,
         "reset_time": "2026-10-12T00:00:00Z"},
        {"pool_index": 1, "window": "5h", "remaining_fraction": 0.9,
         "reset_time": "2026-10-06T12:00:00Z"},
    ]
    windows = sai._windows_from_plane(payload, "shared-account-plane")
    # The adapter stays faithful to what the plane sent...
    assert _keys(windows) == ["weekly@pool0", "five_hour@pool0",
                              "weekly@pool1", "five_hour@pool1"]
    # ...and reading order puts each pool's 5h first without separating pools.
    assert _keys(resolved_windows(windows, now=0)) == \
        ["five_hour@pool0", "weekly@pool0",
         "five_hour@pool1", "weekly@pool1"]


def test_pools_keep_the_order_the_provider_sent_them():
    got = resolved_windows([_win("weekly", 10080, 50.0, "pool1", "Pool 2"),
                            _win("five_hour", 300, 50.0, "pool1", "Pool 2"),
                            _win("weekly", 10080, 50.0, "pool0", "Pool 1"),
                            _win("five_hour", 300, 50.0, "pool0", "Pool 1")],
                           now=0)
    assert [w.group for w in got] == ["pool1", "pool1", "pool0", "pool0"]


def test_an_ungrouped_account_is_ordered_too():
    got = resolved_windows([_win("weekly", 10080, 40.0),
                            _win("five_hour", 300, 60.0)], now=0)
    assert _keys(got) == ["five_hour", "weekly"]


def test_a_window_of_unknown_duration_sorts_last_not_dropped():
    got = resolved_windows([_win("mystery", None, 50.0),
                            _win("five_hour", 300, 50.0)], now=0)
    assert _keys(got) == ["five_hour", "mystery"]


def test_the_gauge_path_reads_the_same_order():
    got = display_windows([_win("weekly", 10080, 50.0),
                           _win("five_hour", 300, 50.0)], now=0)
    assert _keys(got) == ["five_hour", "weekly"]


def test_no_window_is_gained_or_lost_by_reordering():
    windows = [_win("weekly", 10080, 50.0, "pool0", "Pool 1"),
               _win("five_hour", 300, 50.0, "pool0", "Pool 1")]
    assert sorted(_keys(resolved_windows(windows, now=0))) == \
        sorted(_keys(windows))
