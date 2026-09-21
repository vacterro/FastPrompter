"""Voice-countdown settings + pack locations (T-1238-C3.6/C3.7/C3.8).

Voice configuration is application-global audio configuration, so it lives in
``audio.db`` next to the presets and the ambience rules.

Pack locations are two trusted roots and nothing else: the packaged private
``_vault/`` namespace that ships with FastPrompter, and the managed user
library under ``<data>/sound_library/voice/``.  An import COPIES the user's
selected WAVs into the managed library, so the original game folder is never
depended on again -- and no proprietary game audio is ever bundled into a
release.
"""

from __future__ import annotations

import os
import sqlite3
import threading

from fastprompter.core import sound_library
from fastprompter.core.voice_engine import COUNTDOWN_THRESHOLDS, VoicePack

VOICE_DB_NAME = "audio.db"
VOICE_TABLE = "voice_settings_v1"

#: Where imported voice packs are stored inside the managed library.
VOICE_LIBRARY_SUBDIR = "voice"

#: Packs the product knows about.  ``custom`` is whatever the user imported
#: into the ``misc`` folder.
PACK_TYPES = ("vox", "fvox", "gman", "amx_ultimate")

SETTING_ENABLED = "voice_enabled"
SETTING_PACK = "voice_pack"
SETTING_SOURCE_TIMERS = "voice_source_timers"
SETTING_SOURCE_LIMITS = "voice_source_limits"
SETTING_THRESHOLDS = "voice_thresholds"
SETTING_MODE = "voice_playback_mode"
SETTING_VOLUME = "voice_volume_percent"

VOICE_MODES = ("inherit", "mix", "queue", "replace")

DEFAULTS = {
    SETTING_ENABLED: "False",
    SETTING_PACK: "vox",
    SETTING_SOURCE_TIMERS: "True",
    SETTING_SOURCE_LIMITS: "True",
    SETTING_THRESHOLDS: ",".join(str(s) for s, _ in COUNTDOWN_THRESHOLDS),
    SETTING_MODE: "replace",
    SETTING_VOLUME: "80",
}


def packaged_voice_root(pack_type: str) -> str:
    """The shipped pack folder inside the private ``_vault/`` namespace."""
    return os.path.join(sound_library.packaged_root(),
                        sound_library.VAULT_DIR_NAME, pack_type)


def imported_voice_root(pack_type: str) -> str:
    """Where an imported pack of this type is copied to."""
    return os.path.join(sound_library.managed_root(), VOICE_LIBRARY_SUBDIR,
                        pack_type)


#: Packs are immutable on disk during a session; scanning 600+ fragments per
#: query turned the Voice page into a multi-second build.  ``reset_pack_cache``
#: is called after an import, which is the only thing that changes them.
_PACK_CACHE: dict[str, VoicePack] = {}
_STATUS_CACHE: dict[str, dict] | None = None


def reset_pack_cache() -> None:
    global _STATUS_CACHE
    _PACK_CACHE.clear()
    _STATUS_CACHE = None


def voice_pack(pack_type: str) -> VoicePack:
    """The best available pack of this type: imported first, then packaged.

    An imported pack is the user's own material and therefore wins; the
    packaged vault is the fallback that ships with the product.
    """
    kind = pack_type if pack_type in PACK_TYPES else "vox"
    cached = _PACK_CACHE.get(kind)
    if cached is not None:
        return cached
    imported = imported_voice_root(kind)
    if os.path.isdir(imported) and os.listdir(imported):
        pack = VoicePack(imported, kind)
    else:
        pack = VoicePack(packaged_voice_root(kind), kind)
    _PACK_CACHE[kind] = pack
    return pack


def pack_status() -> dict[str, dict]:
    """Truthful readiness of every known pack, for the Voice page."""
    global _STATUS_CACHE
    if _STATUS_CACHE is not None:
        return _STATUS_CACHE
    status: dict[str, dict] = {}
    managed_dir = sound_library.managed_root()
    for kind in PACK_TYPES:
        pack = voice_pack(kind)
        diagnostics = pack.diagnostics()
        missing = diagnostics.get("missing_tokens", [])
        status[kind] = {
            "is_ready": bool(diagnostics.get("is_ready")),
            "fragment_count": diagnostics.get("fragment_count", 0),
            "missing_count": len(missing) if isinstance(missing, list) else 0,
            "imported": pack.root.startswith(managed_dir),
            "root": pack.root,
        }
    _STATUS_CACHE = status
    return status


def import_pack_files(paths, pack_type: str) -> int:
    """Copy user-selected WAVs into the managed voice library.

    Returns how many files landed.  Nothing is downloaded and nothing outside
    the user's explicit selection is touched.
    """
    kind = pack_type if pack_type in PACK_TYPES else "vox"
    target = imported_voice_root(kind)
    try:
        os.makedirs(target, exist_ok=True)
    except OSError:
        return 0
    written = 0
    for path in paths or ():
        ref = sound_library.import_file(
            path, subdir=f"{VOICE_LIBRARY_SUBDIR}/{kind}")
        if ref:
            written += 1
    reset_pack_cache()  # the packs on disk just changed
    return written


def parse_thresholds(raw: object) -> list[int]:
    known = {seconds for seconds, _label in COUNTDOWN_THRESHOLDS}
    if isinstance(raw, (list, tuple, set)):
        parts = list(raw)
    else:
        parts = [p.strip() for p in str(raw or "").split(",") if p.strip()]
    out: list[int] = []
    for part in parts:
        try:
            value = int(part)
        except (TypeError, ValueError):
            continue
        if value in known and value not in out:
            out.append(value)
    return sorted(out, reverse=True)


class VoiceStore:
    """Durable voice-countdown configuration in ``audio.db``."""

    def __init__(self, db_path: str | None = None) -> None:
        if db_path is None:
            from fastprompter.utils.paths import get_data_dir

            db_path = os.path.join(get_data_dir(), VOICE_DB_NAME)
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
                f"CREATE TABLE IF NOT EXISTS {VOICE_TABLE} ("
                "key TEXT PRIMARY KEY, value TEXT NOT NULL)")

    def load(self) -> dict:
        with self._lock, self._connect() as conn:
            rows = dict(conn.execute(
                f"SELECT key, value FROM {VOICE_TABLE}").fetchall())  # nosec B608 - closed table constant
        merged = {**DEFAULTS, **rows}
        pack = merged[SETTING_PACK]
        mode = merged[SETTING_MODE]
        try:
            volume = max(0, min(100, int(merged[SETTING_VOLUME])))
        except (TypeError, ValueError):
            volume = 80
        return {
            "enabled": merged[SETTING_ENABLED] == "True",
            "pack": pack if pack in PACK_TYPES else "vox",
            "source_timers": merged[SETTING_SOURCE_TIMERS] == "True",
            "source_limits": merged[SETTING_SOURCE_LIMITS] == "True",
            "thresholds": parse_thresholds(merged[SETTING_THRESHOLDS]),
            "mode": mode if mode in VOICE_MODES else "replace",
            "volume_percent": volume,
        }

    def save(self, **changes) -> dict:
        rows: dict[str, str] = {}
        for key, value in changes.items():
            if key == "enabled":
                rows[SETTING_ENABLED] = "True" if value else "False"
            elif key == "pack":
                rows[SETTING_PACK] = str(value) if value in PACK_TYPES else "vox"
            elif key == "source_timers":
                rows[SETTING_SOURCE_TIMERS] = "True" if value else "False"
            elif key == "source_limits":
                rows[SETTING_SOURCE_LIMITS] = "True" if value else "False"
            elif key == "thresholds":
                rows[SETTING_THRESHOLDS] = ",".join(
                    str(s) for s in parse_thresholds(value))
            elif key == "mode":
                rows[SETTING_MODE] = (str(value) if value in VOICE_MODES
                                      else "replace")
            elif key == "volume_percent":
                try:
                    rows[SETTING_VOLUME] = str(max(0, min(100, int(value))))
                except (TypeError, ValueError):
                    rows[SETTING_VOLUME] = "80"
            else:
                raise KeyError(key)
        if rows:
            with self._lock, self._connect() as conn:
                conn.executemany(
                    f"INSERT INTO {VOICE_TABLE}(key, value) VALUES(?, ?) "  # nosec B608 - closed table constant
                    "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                    list(rows.items()))
        return self.load()
