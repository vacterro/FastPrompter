"""Ambience rule persistence in ``audio.db`` (T-1238-C3.10).

Ambience definitions are APPLICATION-global audio configuration, so they
live in ``audio.db`` beside the sound presets -- never in a profile DB.

What is persisted is the RULE: enabled, sound ref, volume, trigger, schedule,
weekdays, weather condition, repeat, interval and fades, under a stable id.
What is never persisted is anything transient: the active channel handle, the
fade position, an in-flight weather request or a timer object.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import uuid

from fastprompter.core.ambience_engine import (
    DEFAULT_FADE_MS,
    REPEAT_LOOP,
    TRIGGER_ALWAYS,
    AmbienceRule,
)

AMBIENCE_DB_NAME = "audio.db"
AMBIENCE_TABLE = "ambience_rules_v1"

#: Location + opt-in for the weather trigger.  Weather is OFF until the user
#: configures a place: FastPrompter never geolocates anyone silently.
WEATHER_SETTINGS_TABLE = "ambience_settings_v1"
SETTING_WEATHER_ENABLED = "weather_enabled"
SETTING_WEATHER_LABEL = "weather_label"
SETTING_WEATHER_LAT = "weather_latitude"
SETTING_WEATHER_LON = "weather_longitude"

#: Does the user WANT ambience running?  This is a DESIRED state, not a
#: runtime one: it changes only when the user explicitly starts or stops
#: ambience, and it is what a fresh application session restores.  It is
#: application-global (audio.db, beside the rules) rather than per-profile,
#: so switching profile never silently turns the user's ambience off.
#:
#: Deliberately NOT written by shutdown or by STOP ALL SOUND.  Both of those
#: silence the CURRENT runtime; treating them as "the user stopped ambience"
#: would mean one press of STOP ALL quietly disabled ambience for every
#: future launch.
SETTING_RUNTIME_ENABLED = "runtime_enabled"


def new_rule_id() -> str:
    return f"amb_{uuid.uuid4().hex[:12]}"


#: Templates offered by the UI.  They ship DISABLED and without a sound: a
#: template the user has not configured must never start making noise.
def rule_templates() -> list[AmbienceRule]:
    return [
        AmbienceRule(id=new_rule_id(), name="Always ambience", sound_ref="",
                     trigger=TRIGGER_ALWAYS, repeat=REPEAT_LOOP,
                     enabled=False, volume=0.4,
                     fade_in_ms=DEFAULT_FADE_MS, fade_out_ms=DEFAULT_FADE_MS),
        AmbienceRule(id=new_rule_id(), name="Sunday ambience", sound_ref="",
                     trigger="WEEKDAY", weekday="sunday", repeat=REPEAT_LOOP,
                     enabled=False, volume=0.4,
                     fade_in_ms=DEFAULT_FADE_MS, fade_out_ms=DEFAULT_FADE_MS),
        AmbienceRule(id=new_rule_id(), name="Rain ambience", sound_ref="",
                     trigger="WEATHER", weather="rain", repeat=REPEAT_LOOP,
                     enabled=False, volume=0.4,
                     fade_in_ms=DEFAULT_FADE_MS, fade_out_ms=DEFAULT_FADE_MS),
    ]


class AmbienceStore:
    """Durable ambience rules + the opt-in weather location."""

    def __init__(self, db_path: str | None = None) -> None:
        if db_path is None:
            from fastprompter.utils.paths import get_data_dir

            db_path = os.path.join(get_data_dir(), AMBIENCE_DB_NAME)
        self.db_path = db_path
        parent = os.path.dirname(os.path.abspath(db_path))
        if parent:
            os.makedirs(parent, exist_ok=True)
        self._lock = threading.RLock()
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        from fastprompter.core.state import connect_app_db

        return connect_app_db(self.db_path)

    def _ensure_schema(self) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                f"CREATE TABLE IF NOT EXISTS {AMBIENCE_TABLE} ("
                "id TEXT PRIMARY KEY, position INTEGER NOT NULL DEFAULT 0,"
                "payload TEXT NOT NULL)")
            conn.execute(
                f"CREATE TABLE IF NOT EXISTS {WEATHER_SETTINGS_TABLE} ("
                "key TEXT PRIMARY KEY, value TEXT NOT NULL)")

    # -- rules ---------------------------------------------------------------

    def load_rules(self) -> list[AmbienceRule]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                f"SELECT payload FROM {AMBIENCE_TABLE} ORDER BY position, id"  # nosec B608 - closed table constant
            ).fetchall()
        rules: list[AmbienceRule] = []
        for (payload,) in rows:
            try:
                raw = json.loads(payload)
            except (TypeError, ValueError):
                continue  # a corrupt row is skipped, never guessed at
            if isinstance(raw, dict) and raw.get("id"):
                rules.append(AmbienceRule.from_dict(raw))
        return rules

    def save_rules(self, rules: list[AmbienceRule]) -> None:
        """Replace the whole rule set in one transaction (stable ids kept)."""
        payloads = [(rule.id, index, json.dumps(rule.to_dict(),
                                                separators=(",", ":")))
                    for index, rule in enumerate(rules)]
        with self._lock, self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                conn.execute(f"DELETE FROM {AMBIENCE_TABLE}")  # nosec B608 - closed table constant
                conn.executemany(
                    f"INSERT INTO {AMBIENCE_TABLE}(id, position, payload) "
                    "VALUES(?, ?, ?)", payloads)  # nosec B608 - closed table constant
                conn.commit()
            except Exception:
                conn.rollback()
                raise

    def upsert_rule(self, rule: AmbienceRule) -> list[AmbienceRule]:
        rules = self.load_rules()
        for index, existing in enumerate(rules):
            if existing.id == rule.id:
                rules[index] = rule
                break
        else:
            rules.append(rule)
        self.save_rules(rules)
        return rules

    def delete_rule(self, rule_id: str) -> list[AmbienceRule]:
        rules = [rule for rule in self.load_rules() if rule.id != rule_id]
        self.save_rules(rules)
        return rules

    def duplicate_rule(self, rule_id: str) -> list[AmbienceRule]:
        rules = self.load_rules()
        for rule in list(rules):
            if rule.id == rule_id:
                clone = AmbienceRule.from_dict(rule.to_dict())
                clone.id = new_rule_id()
                clone.name = f"{rule.name} (copy)"
                clone.enabled = False
                rules.append(clone)
                break
        self.save_rules(rules)
        return rules

    # -- weather opt-in --------------------------------------------------------

    def weather_config(self) -> dict:
        with self._lock, self._connect() as conn:
            rows = dict(conn.execute(
                f"SELECT key, value FROM {WEATHER_SETTINGS_TABLE}").fetchall())  # nosec B608 - closed table constant
        return {
            "enabled": rows.get(SETTING_WEATHER_ENABLED, "False") == "True",
            "label": rows.get(SETTING_WEATHER_LABEL, ""),
            "latitude": _as_float(rows.get(SETTING_WEATHER_LAT)),
            "longitude": _as_float(rows.get(SETTING_WEATHER_LON)),
        }

    def set_weather_config(self, *, enabled: bool, label: str = "",
                           latitude=None, longitude=None) -> dict:
        """Persist the opt-in and the user-typed location.

        Enabling without a usable coordinate pair is refused: an enabled
        weather trigger that cannot fetch anything would be a lie in the UI.
        """
        lat, lon = _as_float(latitude), _as_float(longitude)
        if enabled and (lat is None or lon is None):
            enabled = False
        rows = {
            SETTING_WEATHER_ENABLED: "True" if enabled else "False",
            SETTING_WEATHER_LABEL: str(label or ""),
            SETTING_WEATHER_LAT: "" if lat is None else repr(lat),
            SETTING_WEATHER_LON: "" if lon is None else repr(lon),
        }
        with self._lock, self._connect() as conn:
            conn.executemany(
                f"INSERT INTO {WEATHER_SETTINGS_TABLE}(key, value) VALUES(?, ?)"  # nosec B608 - closed table constant
                " ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                list(rows.items()))
        return self.weather_config()

    # -- desired runtime state -------------------------------------------------

    def runtime_enabled(self) -> bool:
        """Does the user want ambience running?  Default: no.

        A fresh install must be silent.  Only an explicit start writes True.
        """
        with self._lock, self._connect() as conn:
            row = conn.execute(
                f"SELECT value FROM {WEATHER_SETTINGS_TABLE} WHERE key = ?",  # nosec B608 - closed table constant
                (SETTING_RUNTIME_ENABLED,)).fetchone()
        return bool(row) and row[0] == "True"

    def set_runtime_enabled(self, enabled: bool) -> bool:
        """Record the user's explicit start/stop decision."""
        value = "True" if enabled else "False"
        with self._lock, self._connect() as conn:
            conn.execute(
                f"INSERT INTO {WEATHER_SETTINGS_TABLE}(key, value) VALUES(?, ?)"  # nosec B608 - closed table constant
                " ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (SETTING_RUNTIME_ENABLED, value))
        return bool(enabled)


def _as_float(value) -> float | None:
    try:
        if value is None or value == "":
            return None
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if -180.0 <= number <= 180.0 else None
