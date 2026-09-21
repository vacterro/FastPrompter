"""Global Problip persistence and statistics.

Problip is an application feature, not a FastPrompter profile feature.  This
module therefore owns one small ``problip.db`` database under ``get_data_dir``
and never imports or writes the profile/SILO state database.  The store uses
the same canonical SQLite connection policy as FastPrompter (WAL, FULL
synchronous durability, and the bounded busy timeout), while keeping its
schema and transactions isolated from SILO tables.
"""

from __future__ import annotations

import copy
import datetime as _datetime
import json
import os
import threading
from dataclasses import dataclass, field
from typing import Any

from fastprompter.core.problip import (
    DEFAULT_SOUND_ID,
    SOUND_IDS,
    IntervalConfig,
    IntervalMode,
    clamp_manual_seconds,
    normalize_manual_range,
)
from fastprompter.core.sound_library import normalize_rel
from fastprompter.core.state import connect_app_db
from fastprompter.utils.paths import get_data_dir

# The Android product's earned milestone is exactly 100,000 successful blips.
PREMIUM_REWARD_BLIPS = 100_000
INT64_MAX = (1 << 63) - 1
CURRENT_SCHEMA_VERSION = 1
DEFAULT_VOLUME_PERCENT = 5

# Persisted setting keys are deliberately stable.  Values are text so the
# settings table remains small, inspectable, and independent of profile DB
# codecs.  Structured values (selected_sound_ids) use JSON text.
SETTING_RUN_ON_LAUNCH = "run_on_launch"
SETTING_INTERVAL_MODE = "interval_mode"
SETTING_MANUAL_FROM_SECONDS = "manual_from_seconds"
SETTING_MANUAL_TO_SECONDS = "manual_to_seconds"
SETTING_SELECTED_SOUND_IDS = "selected_sound_ids"
SETTING_VOLUME_PERCENT = "volume_percent"
SETTING_SHOW_COUNTER = "show_counter"
SETTING_BLIP_GLOW_ENABLED = "blip_glow_enabled"
SETTING_WINDOWS_AUTOSTART = "windows_autostart"
# C0.14: how a SCHEDULED Problip cue behaves against other audio.  The safe
# default is skip_busy -- a courtesy cue must never talk over an alarm and
# must never build a late-replay backlog.
SETTING_PLAYBACK_MODE = "playback_mode"

# T-1242: discriminated pool-token forms.  Bare IDs stay valid forever (the
# legacy six-ID databases must keep loading unchanged); ``builtin-id:`` pins
# a built-in explicitly and ``user:`` references the managed sound library.
BUILTIN_ID_PREFIX = "builtin-id:"
USER_PREFIX_ = "user:"

PLAYBACK_MODES = ("inherit", "mix", "queue", "replace", "skip_busy")
DEFAULT_PLAYBACK_MODE = "skip_busy"


def clean_playback_mode(value: object) -> str:
    text = str(value or "").strip().lower()
    return text if text in PLAYBACK_MODES else DEFAULT_PLAYBACK_MODE


DEFAULT_SETTINGS: dict[str, str] = {
    # Embedded FastPrompter intentionally starts OFF for a first install.  The
    # standalone desktop reference defaults ON, but an upgrade must not begin
    # beeping without an explicit START.
    SETTING_RUN_ON_LAUNCH: "False",
    SETTING_INTERVAL_MODE: IntervalMode.RANDOM_4_7.value,
    SETTING_MANUAL_FROM_SECONDS: "4",
    SETTING_MANUAL_TO_SECONDS: "7",
    SETTING_SELECTED_SOUND_IDS: json.dumps([DEFAULT_SOUND_ID]),
    SETTING_VOLUME_PERCENT: str(DEFAULT_VOLUME_PERCENT),
    SETTING_SHOW_COUNTER: "True",
    SETTING_BLIP_GLOW_ENABLED: "True",
    SETTING_WINDOWS_AUTOSTART: "False",
    SETTING_PLAYBACK_MODE: DEFAULT_PLAYBACK_MODE,
}


@dataclass(frozen=True)
class PeriodKeys:
    """Local calendar identities for today, ISO week, and calendar month."""

    day: str
    week: str
    month: str

    @classmethod
    def from_date(cls, date: _datetime.date) -> PeriodKeys:
        iso = date.isocalendar()
        return cls(
            day=date.isoformat(),
            week=f"{iso.year:04d}-W{iso.week:02d}",
            month=f"{date.year:04d}-{date.month:02d}",
        )

    @classmethod
    def from_datetime(cls, value: _datetime.datetime) -> PeriodKeys:
        return cls.from_date(_local_date(value))

    @classmethod
    def now(cls) -> PeriodKeys:
        return cls.from_date(_datetime.datetime.now().astimezone().date())

    @classmethod
    def of(cls, value: _datetime.date | _datetime.datetime | None = None) -> PeriodKeys:
        if value is None:
            return cls.now()
        if isinstance(value, _datetime.datetime):
            return cls.from_datetime(value)
        if isinstance(value, _datetime.date):
            return cls.from_date(value)
        raise TypeError(f"unsupported period value: {type(value).__name__}")

    @staticmethod
    def week_key(date: _datetime.date) -> str:
        return PeriodKeys.from_date(date).week


# Android naming aliases make the pure model convenient to reuse in tests and
# later UI/controller code without creating a second statistics authority.
BlipPeriodKeys = PeriodKeys


def _local_date(value: _datetime.datetime) -> _datetime.date:
    """Resolve a datetime to the user's local calendar date.

    An aware value is converted to the host local zone before taking the date;
    a naive value is already treated as local wall time.  Production callers
    use ``now=None`` and therefore the machine's local calendar directly.
    """
    if value.tzinfo is not None:
        return value.astimezone().date()
    return value.date()


@dataclass(frozen=True)
class StatsRecord:
    """The compact aggregate persisted in ``problip_stats``."""

    day_key: str = ""
    today_count: int = 0
    week_key: str = ""
    week_count: int = 0
    month_key: str = ""
    month_count: int = 0
    total_count: int = 0
    earned_premium: bool = False


@dataclass(frozen=True)
class StatsSnapshot:
    """What the UI displays for the current local periods."""

    today_count: int = 0
    week_count: int = 0
    month_count: int = 0
    total_count: int = 0
    earned_premium: bool = False

    # Short aliases are useful to non-UI callers and keep the display model
    # readable without changing the canonical *_count field names.
    @property
    def today(self) -> int:
        return self.today_count

    @property
    def week(self) -> int:
        return self.week_count

    @property
    def month(self) -> int:
        return self.month_count

    @property
    def total(self) -> int:
        return self.total_count


# Product/source-compatible names.
BlipStatsRecord = StatsRecord
BlipStats = StatsSnapshot


def _safe_counter(value: Any) -> int:
    """Sanitize an untrusted persisted counter into 0..INT64_MAX."""
    if isinstance(value, bool):
        number = int(value)
    else:
        try:
            number = int(value)
        except (TypeError, ValueError, OverflowError):
            return 0
    return max(0, min(INT64_MAX, number))


def _saturating_increment(value: Any) -> int:
    number = _safe_counter(value)
    return INT64_MAX if number >= INT64_MAX else number + 1


def increment_saturating(value: Any) -> int:
    """Public saturating increment used by tests and store transactions."""
    return _saturating_increment(value)


def _clean_key(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _clean_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


class StatsLogic:
    """Pure statistics/reward authority, independent of SQLite."""

    @staticmethod
    def sanitize(record: StatsRecord) -> StatsRecord:
        total = _safe_counter(record.total_count)
        return StatsRecord(
            day_key=_clean_key(record.day_key),
            today_count=_safe_counter(record.today_count),
            week_key=_clean_key(record.week_key),
            week_count=_safe_counter(record.week_count),
            month_key=_clean_key(record.month_key),
            month_count=_safe_counter(record.month_count),
            total_count=total,
            # Never recompute a true flag back to false.  Total reality also
            # heals an older/corrupt row whose flag was lost.
            earned_premium=(
                _clean_bool(record.earned_premium)
                or total >= PREMIUM_REWARD_BLIPS
            ),
        )

    @staticmethod
    def after_blip(record: StatsRecord, keys: PeriodKeys) -> StatsRecord:
        current = StatsLogic.sanitize(record)
        today = (_saturating_increment(current.today_count)
                 if current.day_key == keys.day else 1)
        week = (_saturating_increment(current.week_count)
                if current.week_key == keys.week else 1)
        month = (_saturating_increment(current.month_count)
                 if current.month_key == keys.month else 1)
        total = _saturating_increment(current.total_count)
        return StatsRecord(
            day_key=keys.day,
            today_count=today,
            week_key=keys.week,
            week_count=week,
            month_key=keys.month,
            month_count=month,
            total_count=total,
            earned_premium=current.earned_premium or total >= PREMIUM_REWARD_BLIPS,
        )

    @staticmethod
    def snapshot(record: StatsRecord, keys: PeriodKeys) -> StatsSnapshot:
        current = StatsLogic.sanitize(record)
        return StatsSnapshot(
            today_count=current.today_count if current.day_key == keys.day else 0,
            week_count=current.week_count if current.week_key == keys.week else 0,
            month_count=current.month_count if current.month_key == keys.month else 0,
            total_count=current.total_count,
            earned_premium=current.earned_premium,
        )


# Android source-compatible name.
BlipStatsLogic = StatsLogic


@dataclass
class ProblipSettings:
    """Normalized application-global Problip preferences."""

    run_on_launch: bool = False
    interval_mode: IntervalMode = IntervalMode.RANDOM_4_7
    manual_from_seconds: int = 4
    manual_to_seconds: int = 7
    selected_sound_ids: list[str] = field(default_factory=lambda: [DEFAULT_SOUND_ID])
    volume_percent: int = DEFAULT_VOLUME_PERCENT
    show_counter: bool = True
    blip_glow_enabled: bool = True
    windows_autostart: bool = False
    playback_mode: str = DEFAULT_PLAYBACK_MODE

    def __post_init__(self) -> None:
        self.interval_mode = IntervalMode.coerce(self.interval_mode)
        self.manual_from_seconds, self.manual_to_seconds = normalize_manual_range(
            self.manual_from_seconds, self.manual_to_seconds)
        self.selected_sound_ids = normalize_sound_ids(self.selected_sound_ids)
        try:
            volume = int(self.volume_percent)
        except (TypeError, ValueError, OverflowError):
            volume = DEFAULT_VOLUME_PERCENT
        self.volume_percent = max(0, min(100, volume))
        self.run_on_launch = _clean_bool(self.run_on_launch)
        self.show_counter = _clean_bool(self.show_counter)
        self.blip_glow_enabled = _clean_bool(self.blip_glow_enabled)
        self.windows_autostart = _clean_bool(self.windows_autostart)
        self.playback_mode = clean_playback_mode(self.playback_mode)

    @property
    def interval_config(self) -> IntervalConfig:
        return IntervalConfig(
            mode=self.interval_mode,
            manual_from_seconds=self.manual_from_seconds,
            manual_to_seconds=self.manual_to_seconds,
        )

    def copy(self) -> ProblipSettings:
        return copy.deepcopy(self)

    def to_dict(self) -> dict[str, Any]:
        return {
            SETTING_RUN_ON_LAUNCH: self.run_on_launch,
            SETTING_INTERVAL_MODE: self.interval_mode.value,
            SETTING_MANUAL_FROM_SECONDS: self.manual_from_seconds,
            SETTING_MANUAL_TO_SECONDS: self.manual_to_seconds,
            SETTING_SELECTED_SOUND_IDS: list(self.selected_sound_ids),
            SETTING_VOLUME_PERCENT: self.volume_percent,
            SETTING_SHOW_COUNTER: self.show_counter,
            SETTING_BLIP_GLOW_ENABLED: self.blip_glow_enabled,
            SETTING_WINDOWS_AUTOSTART: self.windows_autostart,
            SETTING_PLAYBACK_MODE: self.playback_mode,
        }


def normalize_sound_ids(value: Any) -> list[str]:
    """Filter unknown/corrupt IDs and guarantee a semantically non-empty pool.

    T-1242: accepts BOTH the legacy six bare built-in IDs (every existing
    database keeps loading unchanged) and explicit discriminated tokens:
    ``builtin-id:<id>`` pins a built-in while ``user:<rel>`` selects a sound
    from the managed library.  A user ref is never silently reinterpreted as
    a built-in; unknown refs are dropped only by the same rule that already
    dropped unknown built-ins, and the empty result falls back to Original.
    """
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (TypeError, ValueError, json.JSONDecodeError):
            value = []
    if not isinstance(value, (list, tuple, set)):
        value = []
    result: list[str] = []
    for sound_id in value:
        if not isinstance(sound_id, str) or not sound_id or sound_id in result:
            continue
        if sound_id in SOUND_IDS:
            result.append(sound_id)          # legacy bare built-in
        elif sound_id.startswith(BUILTIN_ID_PREFIX) and \
                sound_id[len(BUILTIN_ID_PREFIX):] in SOUND_IDS:
            result.append(sound_id)          # explicit built-in token
        elif sound_id.startswith(USER_PREFIX_):
            rel = normalize_rel(sound_id[len(USER_PREFIX_):])
            if rel and sound_id == f"{USER_PREFIX_}{rel}":
                result.append(sound_id)      # contained managed-library ref
    return result or [DEFAULT_SOUND_ID]


def pool_entry_kind(sound_id: str) -> str:
    """``builtin``, ``user`` or ``unknown`` for one persisted pool token."""
    if sound_id in SOUND_IDS:
        return "builtin"
    if sound_id.startswith(BUILTIN_ID_PREFIX) and \
            sound_id[len(BUILTIN_ID_PREFIX):] in SOUND_IDS:
        return "builtin"
    if sound_id.startswith(USER_PREFIX_):
        return "user"
    return "unknown"



def _serialize_setting(key: str, value: Any) -> str:
    if key == SETTING_PLAYBACK_MODE:
        return clean_playback_mode(value)
    if key == SETTING_SELECTED_SOUND_IDS:
        return json.dumps(normalize_sound_ids(value), separators=(",", ":"))
    if key == SETTING_INTERVAL_MODE:
        return IntervalMode.coerce(value).value
    if key in (SETTING_MANUAL_FROM_SECONDS, SETTING_MANUAL_TO_SECONDS):
        # Store the pair normalization in save_settings; this individual
        # fallback still keeps arbitrary writes inside the legal range.
        return str(clamp_manual_seconds(value))
    if key == SETTING_VOLUME_PERCENT:
        try:
            number = int(value)
        except (TypeError, ValueError, OverflowError):
            number = DEFAULT_VOLUME_PERCENT
        return str(max(0, min(100, number)))
    if key in (
        SETTING_RUN_ON_LAUNCH,
        SETTING_SHOW_COUNTER,
        SETTING_BLIP_GLOW_ENABLED,
        SETTING_WINDOWS_AUTOSTART,
    ):
        return "True" if _clean_bool(value) else "False"
    return str(value)


def _parse_settings(rows: dict[str, Any]) -> ProblipSettings:
    selected = rows.get(SETTING_SELECTED_SOUND_IDS, DEFAULT_SETTINGS[SETTING_SELECTED_SOUND_IDS])
    try:
        selected = json.loads(selected) if isinstance(selected, str) else selected
    except (TypeError, ValueError, json.JSONDecodeError):
        selected = []
    start, end = normalize_manual_range(
        rows.get(SETTING_MANUAL_FROM_SECONDS, 4),
        rows.get(SETTING_MANUAL_TO_SECONDS, 7),
    )
    return ProblipSettings(
        run_on_launch=_clean_bool(rows.get(SETTING_RUN_ON_LAUNCH, False)),
        interval_mode=IntervalMode.coerce(
            rows.get(SETTING_INTERVAL_MODE, IntervalMode.RANDOM_4_7.value)),
        manual_from_seconds=start,
        manual_to_seconds=end,
        selected_sound_ids=normalize_sound_ids(selected),
        volume_percent=rows.get(SETTING_VOLUME_PERCENT, DEFAULT_VOLUME_PERCENT),
        show_counter=_clean_bool(rows.get(SETTING_SHOW_COUNTER, True)),
        blip_glow_enabled=_clean_bool(rows.get(SETTING_BLIP_GLOW_ENABLED, True)),
        windows_autostart=_clean_bool(rows.get(SETTING_WINDOWS_AUTOSTART, False)),
        playback_mode=clean_playback_mode(
            rows.get(SETTING_PLAYBACK_MODE, DEFAULT_PLAYBACK_MODE)),
    )


class ProblipStore:
    """Thread-safe global SQLite store for settings and aggregate statistics."""

    def __init__(self, db_path: str | os.PathLike[str] | None = None,
                 *, connection_factory=connect_app_db) -> None:
        self.db_path = os.fspath(db_path) if db_path is not None else default_db_path()
        parent = os.path.dirname(os.path.abspath(self.db_path))
        if parent:
            os.makedirs(parent, exist_ok=True)
        self._lock = threading.RLock()
        self._closed = False
        self._connection_factory = connection_factory
        self._conn = connection_factory(self.db_path)
        self._init_schema()

    @classmethod
    def open_default(cls) -> ProblipStore:
        return cls(default_db_path())

    def _check_open(self) -> None:
        if self._closed:
            raise RuntimeError("ProblipStore is closed")

    def _init_schema(self) -> None:
        with self._lock:
            self._check_open()
            cur = self._conn.cursor()
            try:
                cur.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS problip_meta (
                        id INTEGER PRIMARY KEY CHECK (id = 1),
                        schema_version INTEGER NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS problip_settings (
                        key TEXT PRIMARY KEY,
                        value TEXT NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS problip_stats (
                        id INTEGER PRIMARY KEY CHECK (id = 1),
                        day_key TEXT NOT NULL,
                        today_count INTEGER NOT NULL,
                        week_key TEXT NOT NULL,
                        week_count INTEGER NOT NULL,
                        month_key TEXT NOT NULL,
                        month_count INTEGER NOT NULL,
                        total_count INTEGER NOT NULL,
                        earned_premium INTEGER NOT NULL CHECK (earned_premium IN (0, 1))
                    );
                    INSERT OR IGNORE INTO problip_meta (id, schema_version)
                        VALUES (1, 1);
                    INSERT OR IGNORE INTO problip_stats (
                        id, day_key, today_count, week_key, week_count,
                        month_key, month_count, total_count, earned_premium
                    ) VALUES (1, '', 0, '', 0, '', 0, 0, 0);
                    """
                )
                version_row = cur.execute(
                    "SELECT schema_version FROM problip_meta WHERE id=1").fetchone()
                version = int(version_row[0]) if version_row else CURRENT_SCHEMA_VERSION
                if version > CURRENT_SCHEMA_VERSION:
                    raise RuntimeError(
                        f"Problip database schema v{version} is newer than supported "
                        f"v{CURRENT_SCHEMA_VERSION}")
                if version < CURRENT_SCHEMA_VERSION:
                    # Future migrations belong here; version is deliberately
                    # advanced only after the migration body succeeds.
                    cur.execute(
                        "UPDATE problip_meta SET schema_version=? WHERE id=1",
                        (CURRENT_SCHEMA_VERSION,))
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise

    def load_settings(self) -> ProblipSettings:
        with self._lock:
            self._check_open()
            rows = dict(self._conn.execute(
                "SELECT key, value FROM problip_settings").fetchall())
            settings = _parse_settings(rows)
            # First-run/default healing is persisted once, so corrupt/unknown
            # values cannot keep re-entering later controller instances. Avoid
            # opening a write transaction on every ordinary settings read.
            canonical = _serialized_settings(settings)
            if any(rows.get(key) != value for key, value in canonical.items()):
                self._write_settings_locked(settings)
            return settings.copy()

    # Common shorthand used by controller code.
    get_settings = load_settings

    def get_setting(self, key: str, default: Any = None) -> Any:
        settings = self.load_settings()
        return settings.to_dict().get(key, default)

    def save_settings(self, settings: ProblipSettings) -> ProblipSettings:
        normalized = settings.copy()
        normalized.__post_init__()
        with self._lock:
            self._check_open()
            self._write_settings_locked(normalized)
            return normalized.copy()

    def update_settings(self, **changes: Any) -> ProblipSettings:
        with self._lock:
            current = self.load_settings()
            values = current.to_dict()
            values.update(changes)
            updated = ProblipSettings(**_settings_kwargs(values))
            self._write_settings_locked(updated)
            return updated.copy()

    def set_setting(self, key: str, value: Any) -> ProblipSettings:
        with self._lock:
            current = self.load_settings()
            values = current.to_dict()
            if key not in values:
                raise KeyError(key)
            values[key] = value
            updated = ProblipSettings(**_settings_kwargs(values))
            self._write_settings_locked(updated)
            return updated.copy()

    def set_run_on_launch(self, enabled: bool) -> ProblipSettings:
        return self.set_setting(SETTING_RUN_ON_LAUNCH, bool(enabled))

    def _write_settings_locked(self, settings: ProblipSettings) -> None:
        kwargs = _settings_kwargs(settings.to_dict())
        normalized = ProblipSettings(**kwargs)
        rows = {
            SETTING_RUN_ON_LAUNCH: normalized.run_on_launch,
            SETTING_INTERVAL_MODE: normalized.interval_mode.value,
            SETTING_MANUAL_FROM_SECONDS: normalized.manual_from_seconds,
            SETTING_MANUAL_TO_SECONDS: normalized.manual_to_seconds,
            SETTING_SELECTED_SOUND_IDS: normalized.selected_sound_ids,
            SETTING_VOLUME_PERCENT: normalized.volume_percent,
            SETTING_SHOW_COUNTER: normalized.show_counter,
            SETTING_BLIP_GLOW_ENABLED: normalized.blip_glow_enabled,
            SETTING_WINDOWS_AUTOSTART: normalized.windows_autostart,
            SETTING_PLAYBACK_MODE: normalized.playback_mode,
        }
        try:
            self._conn.execute("BEGIN IMMEDIATE")
            self._conn.executemany(
                "INSERT INTO problip_settings(key, value) VALUES(?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                [(key, _serialize_setting(key, value)) for key, value in rows.items()],
            )
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

    def get_stats_record(self) -> StatsRecord:
        with self._lock:
            self._check_open()
            record = self._read_stats_locked()
            clean = StatsLogic.sanitize(record)
            if clean != record:
                self._write_stats_locked(clean)
            return clean

    # Aliases clarify that this returns the persisted aggregate rather than a
    # period-filtered display snapshot.
    load_stats_record = get_stats_record

    def get_stats(self, now: _datetime.date | _datetime.datetime | None = None) -> StatsSnapshot:
        with self._lock:
            return StatsLogic.snapshot(self.get_stats_record(), PeriodKeys.of(now))

    snapshot_stats = get_stats

    def record_successful_blip(
        self,
        now: _datetime.date | _datetime.datetime | None = None,
    ) -> StatsSnapshot:
        """Durably count one successful scheduled playback.

        The whole period rollover, total increment, and reward latch are one
        SQLite transaction.  A dropped/failed/test cue must never call this
        method.  ``FULL`` durability is supplied by ``connect_app_db``.
        """
        keys = PeriodKeys.of(now)
        with self._lock:
            self._check_open()
            # Read, rollover, reward-latch, and write under one RESERVED
            # SQLite transaction. The per-instance RLock is not enough when a
            # second FastPrompter process has the same global database open.
            try:
                self._conn.execute("BEGIN IMMEDIATE")
                before = self._read_stats_locked()
                after = StatsLogic.after_blip(before, keys)
                self._upsert_stats_locked(after)
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise
            return StatsLogic.snapshot(after, keys)

    # Explicit aliases for callers whose terminology says increment rather
    # than record.
    record_blip = record_successful_blip
    increment_successful_blip = record_successful_blip

    def _read_stats_locked(self) -> StatsRecord:
        row = self._conn.execute(
            "SELECT day_key, today_count, week_key, week_count, "
            "month_key, month_count, total_count, earned_premium "
            "FROM problip_stats WHERE id=1").fetchone()
        return _record_from_row(row)

    def _upsert_stats_locked(self, record: StatsRecord) -> None:
        clean = StatsLogic.sanitize(record)
        self._conn.execute(
            "INSERT INTO problip_stats ("
            "id, day_key, today_count, week_key, week_count, month_key, "
            "month_count, total_count, earned_premium) VALUES "
            "(1, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET "
            "day_key=excluded.day_key, today_count=excluded.today_count, "
            "week_key=excluded.week_key, week_count=excluded.week_count, "
            "month_key=excluded.month_key, month_count=excluded.month_count, "
            "total_count=excluded.total_count, "
            "earned_premium=MAX(problip_stats.earned_premium, excluded.earned_premium)",
            (
                clean.day_key,
                clean.today_count,
                clean.week_key,
                clean.week_count,
                clean.month_key,
                clean.month_count,
                clean.total_count,
                int(clean.earned_premium),
            ),
        )

    def _write_stats_locked(self, record: StatsRecord) -> None:
        try:
            self._conn.execute("BEGIN IMMEDIATE")
            self._upsert_stats_locked(record)
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._conn.close()
            self._closed = True

    def __enter__(self) -> ProblipStore:
        self._check_open()
        return self

    def __exit__(self, _exc_type, _exc, _tb) -> None:
        self.close()


def _serialized_settings(settings: ProblipSettings) -> dict[str, str]:
    values = settings.to_dict()
    return {
        key: _serialize_setting(key, value)
        for key, value in values.items()
    }


def _settings_kwargs(values: dict[str, Any]) -> dict[str, Any]:
    """Translate the stable persisted-key dictionary to dataclass fields."""
    return {
        "run_on_launch": values.get(SETTING_RUN_ON_LAUNCH, False),
        "interval_mode": values.get(SETTING_INTERVAL_MODE, IntervalMode.RANDOM_4_7.value),
        "manual_from_seconds": values.get(SETTING_MANUAL_FROM_SECONDS, 4),
        "manual_to_seconds": values.get(SETTING_MANUAL_TO_SECONDS, 7),
        "selected_sound_ids": values.get(SETTING_SELECTED_SOUND_IDS, [DEFAULT_SOUND_ID]),
        "volume_percent": values.get(SETTING_VOLUME_PERCENT, DEFAULT_VOLUME_PERCENT),
        "show_counter": values.get(SETTING_SHOW_COUNTER, True),
        "blip_glow_enabled": values.get(SETTING_BLIP_GLOW_ENABLED, True),
        "windows_autostart": values.get(SETTING_WINDOWS_AUTOSTART, False),
        "playback_mode": values.get(SETTING_PLAYBACK_MODE,
                                    DEFAULT_PLAYBACK_MODE),
    }


def _record_from_row(row: tuple[Any, ...] | None) -> StatsRecord:
    if not row:
        return StatsRecord()
    return StatsRecord(
        day_key=row[0],
        today_count=row[1],
        week_key=row[2],
        week_count=row[3],
        month_key=row[4],
        month_count=row[5],
        total_count=row[6],
        earned_premium=_clean_bool(row[7]),
    )


def default_db_path() -> str:
    """Return the one application-global Problip DB path."""
    return os.path.join(get_data_dir(), "problip.db")


# A descriptive alias keeps the path contract easy to discover.
get_problip_db_path = default_db_path
