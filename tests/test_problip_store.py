"""T-1238-A: Problip settings persistence and database isolation."""

from __future__ import annotations

import json
import sqlite3

import pytest

from fastprompter.core.problip import DEFAULT_SOUND_ID, SOUND_IDS, IntervalMode
from fastprompter.core.problip_store import (
    CURRENT_SCHEMA_VERSION,
    DEFAULT_VOLUME_PERCENT,
    SETTING_INTERVAL_MODE,
    SETTING_SELECTED_SOUND_IDS,
    ProblipSettings,
    ProblipStore,
    default_db_path,
    normalize_sound_ids,
)


def test_default_path_is_one_global_problip_db(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "fastprompter.core.problip_store.get_data_dir", lambda: str(tmp_path))
    assert default_db_path() == str(tmp_path / "problip.db")


def test_first_install_defaults_are_safe_and_stopped(tmp_path):
    store = ProblipStore(tmp_path / "problip.db")
    try:
        settings = store.load_settings()
        assert settings.run_on_launch is False
        assert settings.interval_mode is IntervalMode.RANDOM_4_7
        assert settings.selected_sound_ids == [DEFAULT_SOUND_ID]
        assert settings.volume_percent == DEFAULT_VOLUME_PERCENT
        assert settings.show_counter is True
        assert settings.blip_glow_enabled is True
        assert settings.windows_autostart is False
    finally:
        store.close()


def test_settings_round_trip_is_global_and_not_profile_keyed(tmp_path):
    db_path = tmp_path / "problip.db"
    first = ProblipStore(db_path)
    try:
        saved = first.update_settings(
            run_on_launch=True,
            interval_mode=IntervalMode.MANUAL,
            manual_from_seconds=30,
            manual_to_seconds=10,
            selected_sound_ids=["sound_space", "sound_glass", "sound_space"],
            volume_percent=73,
            show_counter=False,
            blip_glow_enabled=False,
            windows_autostart=True,
        )
        assert saved.manual_from_seconds == 10
        assert saved.manual_to_seconds == 30
    finally:
        first.close()

    # Reopening the same one path models a profile switch/restart: no p0/p1
    # suffix or profile-owned database is involved.
    second = ProblipStore(db_path)
    try:
        loaded = second.load_settings()
        assert loaded.run_on_launch is True
        assert loaded.interval_mode is IntervalMode.MANUAL
        assert (loaded.manual_from_seconds, loaded.manual_to_seconds) == (10, 30)
        assert loaded.selected_sound_ids == ["sound_space", "sound_glass"]
        assert loaded.volume_percent == 73
        assert loaded.show_counter is False
        assert loaded.blip_glow_enabled is False
        assert loaded.windows_autostart is True
    finally:
        second.close()

    assert db_path.exists()
    assert not list(tmp_path.glob("local_data_v15*.db"))


def test_corrupt_settings_heal_to_safe_canonical_values(tmp_path):
    db_path = tmp_path / "problip.db"
    store = ProblipStore(db_path)
    store.close()

    conn = sqlite3.connect(db_path)
    try:
        conn.executemany(
            "INSERT OR REPLACE INTO problip_settings(key, value) VALUES (?, ?)",
            [
                ("run_on_launch", "not true"),
                (SETTING_INTERVAL_MODE, "not-a-mode"),
                ("manual_from_seconds", "9000"),
                ("manual_to_seconds", "-4"),
                (SETTING_SELECTED_SOUND_IDS, json.dumps(["missing", SOUND_IDS[-1], SOUND_IDS[-1]])),
                ("volume_percent", "999"),
                ("show_counter", "0"),
                ("blip_glow_enabled", "false"),
                ("windows_autostart", "yes"),
            ],
        )
        conn.commit()
    finally:
        conn.close()

    healed = ProblipStore(db_path)
    try:
        settings = healed.load_settings()
        assert settings.run_on_launch is False
        assert settings.interval_mode is IntervalMode.RANDOM_4_7
        assert (settings.manual_from_seconds, settings.manual_to_seconds) == (1, 3600)
        assert settings.selected_sound_ids == [SOUND_IDS[-1]]
        assert settings.volume_percent == 100
        assert settings.show_counter is False
        assert settings.blip_glow_enabled is False
        assert settings.windows_autostart is True

        rows = dict(healed._conn.execute("SELECT key, value FROM problip_settings"))
        assert rows[SETTING_INTERVAL_MODE] == IntervalMode.RANDOM_4_7.value
        assert json.loads(rows[SETTING_SELECTED_SOUND_IDS]) == [SOUND_IDS[-1]]
    finally:
        healed.close()


def test_sound_pool_always_has_original_fallback_and_filters_unknown_ids():
    assert normalize_sound_ids([]) == [DEFAULT_SOUND_ID]
    assert normalize_sound_ids(["missing", DEFAULT_SOUND_ID, DEFAULT_SOUND_ID]) == [DEFAULT_SOUND_ID]
    assert normalize_sound_ids("not json") == [DEFAULT_SOUND_ID]
    assert normalize_sound_ids(json.dumps([SOUND_IDS[1], "missing"])) == [SOUND_IDS[1]]


def test_schema_contains_only_global_problip_tables(tmp_path):
    store = ProblipStore(tmp_path / "problip.db")
    try:
        tables = {
            row[0] for row in store._conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")
        }
        assert tables == {"problip_meta", "problip_settings", "problip_stats"}
        assert store._conn.execute(
            "SELECT schema_version FROM problip_meta WHERE id=1").fetchone()[0] \
            == CURRENT_SCHEMA_VERSION
    finally:
        store.close()


def test_store_isolates_an_existing_profile_database(tmp_path):
    profile_db = tmp_path / "local_data_v15.db"
    conn = sqlite3.connect(profile_db)
    try:
        conn.execute("CREATE TABLE presets (slot INTEGER PRIMARY KEY, content TEXT)")
        conn.execute("INSERT INTO presets VALUES (0, 'untouched')")
        conn.commit()
    finally:
        conn.close()

    store = ProblipStore(tmp_path / "problip.db")
    try:
        store.record_successful_blip()
    finally:
        store.close()

    check = sqlite3.connect(profile_db)
    try:
        assert check.execute("SELECT content FROM presets WHERE slot=0").fetchone()[0] == "untouched"
        assert not {
            row[0] for row in check.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")
        } & {"problip_meta", "problip_settings", "problip_stats"}
    finally:
        check.close()


def test_closed_store_rejects_reads_and_writes(tmp_path):
    store = ProblipStore(tmp_path / "problip.db")
    store.close()
    with pytest.raises(RuntimeError):
        store.load_settings()
    with pytest.raises(RuntimeError):
        store.record_successful_blip()


def test_settings_object_normalizes_direct_construction():
    settings = ProblipSettings(
        interval_mode="bad",
        manual_from_seconds=10000,
        manual_to_seconds=-2,
        selected_sound_ids=["bad"],
        volume_percent=-3,
        run_on_launch="yes",
    )
    assert settings.interval_mode is IntervalMode.RANDOM_4_7
    assert (settings.manual_from_seconds, settings.manual_to_seconds) == (1, 3600)
    assert settings.selected_sound_ids == [DEFAULT_SOUND_ID]
    assert settings.volume_percent == 0
    assert settings.run_on_launch is True
