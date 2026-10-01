"""T-1359 regression: the fresh-profile interval default IS the 24h Chime
preset, from ONE canonical constant, and existing stored interval settings
are never migrated or overwritten by the default change.

Covers the acceptance of SRC-071's follow-up ("let the 24h chime preset be
enabled by default right away"):

* fresh/default profile (DEFAULT_PROFILE and the structured codec fallback)
  == the same list the timer dialog ships as the "24h Chime" preset;
* the canonical definition is shared (identity, not a divergent copy);
* an existing database with explicit custom rules — or an explicit EMPTY
  list — keeps exactly what it stored across a real save/reload restart;
* the four preset windows partition the 24h clock at hourly boundaries.
"""

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

from fastprompter.core import state as state_mod  # noqa: E402
from fastprompter.core.default_profile import DEFAULT_PROFILE  # noqa: E402
from fastprompter.core.interval_presets import DAYPART_CHIME_RULES  # noqa: E402


def test_fresh_default_is_daypart_chime_preset():
    profile_rules = DEFAULT_PROFILE["interval_notifs"]
    codec_rules = state_mod._STRUCTURED_CODECS["interval_notifs"][1]
    assert profile_rules == DAYPART_CHIME_RULES
    assert codec_rules == DAYPART_CHIME_RULES
    assert len(profile_rules) == 4


def test_single_canonical_constant_no_divergent_copy():
    # The UI preset and the core default must be the SAME object, so a future
    # edit to one cannot drift from the other (the T-1359 handoff rule).
    import fastprompter.ui.timer_dialog as timer_dialog

    assert timer_dialog.DAYPART_CHIME_RULES is DAYPART_CHIME_RULES
    assert timer_dialog.DEFAULT_INTERVAL_RULES is DAYPART_CHIME_RULES
    # And the profile bakes a private copy, not a shared mutable reference.
    assert DEFAULT_PROFILE["interval_notifs"] is not DAYPART_CHIME_RULES


def test_preset_windows_partition_24h_hourly():
    # Every hourly boundary of the day must fall in exactly one enabled
    # window, so a fresh user hears exactly one chime per hour, every hour.
    assert all(rule["enabled"] for rule in DAYPART_CHIME_RULES)
    assert all(rule["minutes"] == 60 for rule in DAYPART_CHIME_RULES)
    for minute in range(0, 24 * 60, 60):
        covering = [
            rule for rule in DAYPART_CHIME_RULES
            if (rule["start_minute"] <= minute <= rule["end_minute"])
            or (rule["start_minute"] > rule["end_minute"]
                and (minute >= rule["start_minute"] or minute <= rule["end_minute"]))
        ]
        assert len(covering) == 1, f"minute {minute}: {covering}"


def _isolated_state(tmp_path, monkeypatch):
    monkeypatch.setattr(
        state_mod, "get_db_path", lambda profile_id=1: str(tmp_path / "t1359.db"))
    monkeypatch.setattr(
        "fastprompter.utils.portable_backup.run_portable_backup",
        lambda data, profile_id=1, **_kw: None)
    return state_mod.FastPrompterState(profile_id=1)


def test_stored_custom_rules_survive_restart(tmp_path, monkeypatch):
    custom = [{
        "id": "user_own", "name": "Mine", "minutes": 20, "enabled": True,
        "sound": "file:ROGUE.wav", "volume": 0.4,
        "show_notification": True, "show_in_top_bar": True,
        "align_mode": "elapsed", "all_day": True, "start_minute": 0,
        "end_minute": 1439, "last_fired": 0.0, "last_fired_minute": "",
    }]
    s = _isolated_state(tmp_path, monkeypatch)
    try:
        s.data["interval_notifs"] = custom
        s.mark_dirty()
        s.save_data_to_db("text", force=True)
    finally:
        s.conn.close()
    s2 = _isolated_state(tmp_path, monkeypatch)
    try:
        assert s2.data["interval_notifs"] == custom
    finally:
        s2.conn.close()


def test_stored_empty_list_survives_restart(tmp_path, monkeypatch):
    # An explicit empty list is a user decision, not a missing key: the new
    # default must not resurrect four chimes under it.
    s = _isolated_state(tmp_path, monkeypatch)
    try:
        s.data["interval_notifs"] = []
        s.mark_dirty()
        s.save_data_to_db("text", force=True)
    finally:
        s.conn.close()
    s2 = _isolated_state(tmp_path, monkeypatch)
    try:
        assert s2.data["interval_notifs"] == []
    finally:
        s2.conn.close()
