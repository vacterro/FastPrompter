"""Canonical interval-notification presets, shared by core and UI (T-1359).

The 24h Chime preset used to live only inside the timer dialog as one of
several selectable presets, while :mod:`fastprompter.core.default_profile`
carried its own divergent single-rule literal. Two hand-maintained copies of
"what a fresh profile gets" can only drift, so the canonical definition lives
here — a non-UI core module — and both consumers import THIS list:

* ``default_profile`` bakes it into ``DEFAULT_PROFILE["interval_notifs"]``;
* ``timer_dialog`` offers it as the "24h Chime" preset and as its
  "Defaults" button.

The rules are data, frozen in spirit: treat the list as read-only and
``copy.deepcopy`` before storing it into any mutable profile.
"""

from __future__ import annotations

# Four clock-aligned hourly windows that partition the day (07:00-11:59
# morning, 12:00-12:59 noon, 13:00-21:59 day & evening, 22:00-06:59 night),
# each chiming once per hour at a quiet 0.05 volume. Boundaries are minute
# ranges, inclusive, wrapping across midnight for the night window.
DAYPART_CHIME_RULES = [
    {
        "id": "interval_default_noon",
        "name": "Noon (12:00)",
        "minutes": 60,
        "enabled": True,
        "sound": "file:GENIE.wav",
        "volume": 0.05,
        "show_notification": True,
        "show_in_top_bar": False,
        "align_mode": "clock",
        "all_day": False,
        "start_minute": 720,
        "end_minute": 779,
        "last_fired": 0.0,
        "last_fired_minute": "",
    },
    {
        "id": "interval_default_morning",
        "name": "Morning (07:00 - 11:00)",
        "minutes": 60,
        "enabled": True,
        "sound": "file:NEWDAY.wav",
        "volume": 0.05,
        "show_notification": True,
        "show_in_top_bar": False,
        "align_mode": "clock",
        "all_day": False,
        "start_minute": 420,
        "end_minute": 719,
        "last_fired": 0.0,
        "last_fired_minute": "",
    },
    {
        "id": "interval_default_day",
        "name": "Day & Evening (13:00 - 21:00)",
        "minutes": 60,
        "enabled": True,
        "sound": "file:NEWDAY.wav",
        "volume": 0.05,
        "show_notification": True,
        "show_in_top_bar": False,
        "align_mode": "clock",
        "all_day": False,
        "start_minute": 780,
        "end_minute": 1319,
        "last_fired": 0.0,
        "last_fired_minute": "",
    },
    {
        "id": "interval_default_night",
        "name": "Night (22:00 - 06:00)",
        "minutes": 60,
        "enabled": True,
        "sound": "file:alert_owl2.wav",
        "volume": 0.05,
        "show_notification": True,
        "show_in_top_bar": False,
        "align_mode": "clock",
        "all_day": False,
        "start_minute": 1320,
        "end_minute": 419,
        "last_fired": 0.0,
        "last_fired_minute": "",
    },
]


def daypart_chime_rules() -> list[dict]:
    """A private deepcopy of the canonical 24h Chime preset.

    Every caller that stores the preset into a profile must go through this,
    so no consumer can mutate the canonical list by editing what it saved.
    """
    import copy

    return copy.deepcopy(DAYPART_CHIME_RULES)
