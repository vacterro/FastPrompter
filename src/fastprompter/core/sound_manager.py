"""Sound effect manager for FastPrompter.

Manages QSoundEffect instances with volume control, file mapping,
and toggles for UI and typewriter sounds.
"""

import os
from typing import Any

from PyQt6.QtCore import QObject, QUrl

try:
    # QtMultimedia drags in very large FFmpeg DLLs; portable builds may
    # exclude it, in which case we fall back to stdlib winsound.
    from PyQt6.QtMultimedia import QSoundEffect
except ImportError:
    QSoundEffect = None

from fastprompter.core.logging import logger
from fastprompter.utils.paths import get_resource_path

# Default sound mappings (shipped fallbacks)
_DEFAULT_SOUND_MAP: dict[str, str] = {
    # Every value here is checked against the shipped folder by a test — a
    # default pointing at a file that no longer exists is a silent silence,
    # which is exactly what the library rename produced the first time.
    "new": "ui_new.wav",
    "save": "ui_save.wav",
    "silo": "button1.wav",
    "snippet": "click_double.wav",
    "tick": "tick_on.wav",
    "untick": "tick_off.wav",
    "delete": "ui_delete.wav",
    "clear": "ui_clear.wav",
    "type": "type_key_1.wav",
    "backspace": "type_key_3.wav",
    "click": "button1.wav",
    "hover": "cs_style/buttonrollover.wav",
    "button_click": "cs_style/buttonclick.wav",
    "button_release": "cs_style/buttonclickrelease.wav",
    "chest_open": "chest_open.wav",
    "chest_close": "chest_closed.wav",
    "notify": "notify.wav",
    "error": "newday.wav",
    "success": "success_levelup.wav",
    "timer": "timer_tick_pack.wav",
    # T-735. Undo/redo are a PAIR on purpose, the same way tick_on/tick_off
    # are: two pitches of one blip, so the direction is audible without
    # looking. `hotkey` is the generic fallback every shortcut without a
    # named event of its own falls back to.
    "undo": "blip_b.wav",
    "redo": "blip_c.wav",
    "select_all": "pop.wav",
    "settings": "panel_open.wav",
    "help": "menu1.wav",
    "hotkey": "menu_mnu_click.wav",
    # Per-shortcut named events — one event per hotkey so every key is
    # individually re-mappable in the Sound Settings dialog.
    "bold": "click_soft.wav",
    "italic": "click_mouse_click3.wav",
    "underline": "click_mouse_click3.wav",
    "strike": "click_tactile_click.wav",
    "header": "click_double.wav",
    "divider": "menu_mnu_next.wav",
    "snap": "pop_up_02.wav",
    "find": "menu_launch_select1.wav",
    "replace": "menu3.wav",
    "focus": "panel_open.wav",
    "export": "ui_save.wav",
    "quit": "menu_mnu_disa.wav",
    # Panel toggles and mode switches.
    "archive": "chest_open.wav",
    "snippets_toggle": "menu_mnu_next.wav",
    "transform": "click_double.wav",
    "sidebar": "menu_mnu_next.wav",
    "lock": "click_tactile_click.wav",
    # Clipboard actions — their own sounds, not generic "hotkey".
    "copy": "pop.wav",
    "paste": "pop_up_02.wav",
    "cut": "menu_launch_deny1.wav",
    # Zoom, search, dismiss.
    "zoom_in": "blip_b.wav",
    "zoom_out": "blip_c.wav",
    "escape": "menu_mnu_disa.wav",
    "search": "menu_launch_select1.wav",
    # Data actions.
    "backup": "ui_save.wav",
    "restore": "menu_mnu_empt.wav",
    "reset": "ui_clear.wav",
    # Timer / profile / watcher.
    "timer_start": "tick_on.wav",
    "profile": "panel_open.wav",
    "watcher": "notify.wav",
}

# Events that ship switched OFF. `hotkey` used to be here on my judgement
# that a sound on EVERY shortcut would be a reason to switch sound off
# altogether. The user asked for exactly that twice, in those words -- "all
# possible hotkeys in software and help" -- so it is their call, not mine,
# and the set is empty. `_heal_hotkey_default` below flips it ON once for
# profiles that already stored the old shipped `False`, because migration
# cannot otherwise tell "the app shipped it off" from "the user turned it
# off", and leaving those profiles silent would look like the feature simply
# does not work.
_DEFAULT_OFF: frozenset[str] = frozenset()
_HOTKEY_DEFAULT_MARK = "sound_hotkey_on_by_default"


def _heal_hotkey_default(data: dict[str, Any]) -> None:
    """One-shot: adopt the new shipped default for `hotkey`.

    Runs once per profile and leaves a marker, so a user who switches it off
    afterwards keeps it off -- the heal must not fight the person.
    """
    if data.get(_HOTKEY_DEFAULT_MARK) == "True":
        return
    data[_HOTKEY_DEFAULT_MARK] = "True"
    events = data.get("sound_events")
    if isinstance(events, dict) and isinstance(events.get("hotkey"), dict):
        events["hotkey"]["enabled"] = "True"

# What each event is, for the settings panel. Nothing is hardcoded about
# WHICH sound plays — only what the event means.
EVENT_LABELS: dict[str, str] = {
    "new": "New silo",
    "save": "Save",
    "silo": "Switch silo",
    "snippet": "Snippet",
    "tick": "Tick on",
    "untick": "Tick off",
    # NOT the bare words "Delete"/"Clear": those keys already exist in the
    # bundle as the toolbar's icon captions, where EST renders "Clear" as the
    # glyph "✕" — which is what showed up in this list instead of a label.
    "delete": "Delete silo",
    "clear": "Clear the editor",
    "undo": "Undo",
    "redo": "Redo",
    "select_all": "Select all",
    "settings": "Settings",
    "help": "Help",
    "hotkey": "Any other hotkey",
    "bold": "Bold",
    "italic": "Italic",
    "underline": "Underline",
    "strike": "Strikethrough",
    "header": "Header format",
    "divider": "Divider line",
    "snap": "Snap corner",
    "find": "Find",
    "replace": "Replace",
    "focus": "Focus mode",
    "export": "Export silo",
    "quit": "Quit",
    "archive": "Archive panel",
    "snippets_toggle": "Snippets panel",
    "transform": "Transform mode",
    "sidebar": "Sidebar toggle",
    "lock": "Lock window",
    "copy": "Copy (Ctrl+C)",
    "paste": "Paste (Ctrl+V)",
    "cut": "Cut (Ctrl+X)",
    "zoom_in": "Zoom in",
    "zoom_out": "Zoom out",
    "escape": "Escape / dismiss",
    "search": "Search dialog",
    "backup": "Backup DB",
    "restore": "Restore DB",
    "reset": "Reset to defaults",
    "timer_start": "Timer started",
    "profile": "Profile switch",
    "watcher": "Watcher start/stop",
    "type": "Typewriter",
    "backspace": "Typewriter: backspace",
    "click": "Click",
    "hover": "Hover a silo",
    "button_click": "Button press",
    "button_release": "Button release",
    "chest_open": "Files panel opens",
    "chest_close": "Files panel closes",
    "notify": "Notification",
    "error": "Error",
    "success": "Success",
    "timer": "Timer alarm",
}


def discover_sound_files(sounds_dir: str) -> list[str]:
    """Discover all WAV files in the sounds directory.
    
    Returns sorted list of WAV filenames (without path).
    """
    if not os.path.isdir(sounds_dir):
        logger.warning("Sounds directory not found: %s", sounds_dir)
        return []
    
    # Recursive: cs_style/ is a real subfolder and its three files are the
    # ones the CS 1.6 style names, so a flat listdir left them unreachable
    # from the picker and made those defaults unresolvable.
    wav_files = []
    try:
        for root, _dirs, names in os.walk(sounds_dir):
            for f in names:
                if not f.lower().endswith(".wav"):
                    continue
                rel = os.path.relpath(os.path.join(root, f), sounds_dir)
                wav_files.append(rel.replace(os.sep, "/"))
        wav_files.sort()
        logger.debug("Discovered %d sound files in %s", len(wav_files), sounds_dir)
    except OSError:
        logger.error("Failed to list sounds directory: %s", sounds_dir)
    
    return wav_files


def get_sound_file_for_event(
    event: str,
    data: dict[str, Any],
    sounds_dir: str
) -> str | None:
    """Get the sound file for an event from settings or defaults.
    
    Priority:
    1. User mapping in data["sound_events"][event]["file"]
    2. Default mapping in _DEFAULT_SOUND_MAP
    3. Fallback to {event}.wav
    
    Returns None if no file found.
    """
    # Check user mapping first
    sound_events = data.get("sound_events", {})
    if isinstance(sound_events, dict):
        event_config = sound_events.get(event)
        if isinstance(event_config, dict):
            file_name = event_config.get("file")
            if file_name:
                path = os.path.join(sounds_dir, file_name)
                if os.path.exists(path):
                    logger.debug("Using user sound: %s for event %s", file_name, event)
                    return file_name
                else:
                    logger.warning("User sound file not found: %s for event %s", path, event)
    
    # Fall back to defaults
    file_name = _DEFAULT_SOUND_MAP.get(event)
    if file_name:
        path = os.path.join(sounds_dir, file_name)
        if os.path.exists(path):
            return file_name
    
    # Last resort: try {event}.wav
    path = os.path.join(sounds_dir, f"{event}.wav")
    if os.path.exists(path):
        return f"{event}.wav"
    
    return None


def is_event_enabled(event: str, data: dict[str, Any]) -> bool:
    """Check if a sound event is enabled in settings.
    
    Respects sound_ui/sound_typewriter global toggles and per-event enabled flag.
    """
    # Global toggles. Backspace belongs to the TYPEWRITER switch, not the UI
    # one — it is the same effect, and the user asked for it as an option of
    # the typewriter sound. Left in the UI branch it clattered away while the
    # typewriter was off.
    if event in ("type", "backspace"):
        if data.get("sound_typewriter", "False") != "True":
            return False
    elif data.get("sound_ui", "False") != "True":
        return False
    
    # Per-event toggle
    sound_events = data.get("sound_events", {})
    if isinstance(sound_events, dict):
        event_config = sound_events.get(event)
        if isinstance(event_config, dict):
            enabled = event_config.get("enabled", "True")
            if enabled != "True":
                return False
    
    return True


def _parse_volume_value(raw) -> float | None:
    """Parse 0.0-1.0 float, legacy 0-10 int/str -> float, None on bad."""
    if raw is None or raw == "":
        return None
    if isinstance(raw, bool):
        return None
    # legacy int 0-10 without decimal
    if isinstance(raw, int) and 0 <= raw <= 10:
        return max(0.0, min(1.0, raw / 10.0))
    if isinstance(raw, str) and raw.strip().isdigit():
        try:
            iv = int(raw.strip())
            if 0 <= iv <= 10:
                return max(0.0, min(1.0, iv / 10.0))
        except (TypeError, ValueError):
            pass
    try:
        v = float(str(raw).strip())
    except (TypeError, ValueError):
        return None
    if v > 1.0 and v <= 10.0 and float(v).is_integer():
        v = v / 10.0
    return max(0.0, min(1.0, v))


def get_event_volume(event: str, data: dict[str, Any]) -> float:
    """Get the volume for a specific event 0.0-1.0, fallback to global."""
    sound_events = data.get("sound_events", {})
    if isinstance(sound_events, dict):
        event_config = sound_events.get(event)
        if isinstance(event_config, dict):
            vol_str = event_config.get("volume")
            if vol_str not in (None, ""):
                pv = _parse_volume_value(vol_str)
                if pv is not None:
                    return pv
    gv = _parse_volume_value(data.get("sound_volume", "0.5"))
    return gv if gv is not None else 0.5


def migrate_sound_settings(data: dict[str, Any], sounds_dir: str = "") -> None:
    """Bring data["sound_events"] up to date, and HEAL it.

    Called on every start, not once: an override pointing at a file the
    library no longer ships is dropped here rather than left to fail
    silently at play time (the sound rename made every stored mapping stale
    at once). A value the user chose that still exists is never touched, and
    an event added in a later version gets its default without wiping the
    rest.
    """
    events = data.get("sound_events")
    if not isinstance(events, dict):
        events = {}
    healed = {}
    for event, default_file in _DEFAULT_SOUND_MAP.items():
        cfg = events.get(event)
        cfg = dict(cfg) if isinstance(cfg, dict) else {}
        chosen = cfg.get("file") or ""
        if chosen and sounds_dir and not os.path.exists(
                os.path.join(sounds_dir, chosen)):
            chosen = ""                      # stale name: fall back to default
        cfg["file"] = chosen or default_file
        cfg.setdefault("enabled", "False" if event in _DEFAULT_OFF else "True")
        cfg.setdefault("volume", "")
        healed[event] = cfg
    # anything the user added for an event this build does not know stays put
    for event, cfg in events.items():
        if event not in healed and isinstance(cfg, dict):
            healed[event] = cfg
    data["sound_events"] = healed
    _heal_hotkey_default(data)


def _volume_level(data: dict[str, Any]) -> float:
    """The Volume spinner as 0.0-1.0, legacy 0-10 handled, junk -> 0.5."""
    pv = _parse_volume_value(data.get("sound_volume", "0.5"))
    return pv if pv is not None else 0.5


def _volume_factor(data: dict[str, Any]) -> float:
    """The Volume spinner as an amplitude factor 0.0-1.0."""
    return _volume_level(data)


def scale_wav_bytes(path: str, factor: float) -> bytes | None:
    """A copy of the WAV at ``path`` with every sample scaled by ``factor``.

    winsound has no volume control of its own, and the shipped build has no
    QtMultimedia in it (there is no qt6multimedia.dll in the dist) — that is
    the whole reason the Volume setting appeared to do nothing in the
    packaged app while working in a dev checkout. Scaling the samples is the
    only way that path can obey the setting.

    Returns None when the file is not something we can safely rewrite —
    compressed, exotic sample width, or a big-endian host — in which case the
    caller plays it unscaled rather than not at all.
    """
    import io
    import sys
    import wave
    from array import array

    if sys.byteorder != "little":
        return None
    try:
        with wave.open(path, "rb") as wf:
            if wf.getcomptype() != "NONE":
                return None
            width = wf.getsampwidth()
            # The shipped effects are 32-bit PCM, which is exactly why this
            # has to cover width 4: a 1/2-only version returns None for every
            # sound the app actually plays and the setting stays decorative.
            if width not in (1, 2, 4):
                return None
            params = wf.getparams()
            frames = wf.readframes(wf.getnframes())
    except (OSError, wave.Error):
        logger.debug("volume scaling skipped for %s", path, exc_info=True)
        return None

    if width in (2, 4):
        code = "h" if width == 2 else "i"
        samples = array(code)
        if samples.itemsize != width:
            return None
        samples.frombytes(frames[: len(frames) - (len(frames) % width)])
        lo, hi = -(1 << (8 * width - 1)), (1 << (8 * width - 1)) - 1
        for i, s in enumerate(samples):
            samples[i] = max(lo, min(hi, int(s * factor)))
    else:
        # 8-bit WAV samples are UNSIGNED with silence at 128, so they have to
        # be scaled around that midpoint — scaling the raw byte would pull
        # the whole waveform down towards a DC offset instead of quieter.
        samples = array("B")
        samples.frombytes(frames)
        for i, s in enumerate(samples):
            samples[i] = max(0, min(255, int((s - 128) * factor) + 128))

    buf = io.BytesIO()
    try:
        with wave.open(buf, "wb") as out:
            out.setparams(params)
            out.writeframes(samples.tobytes())
    except wave.Error:
        logger.debug("volume scaling failed to re-encode %s", path, exc_info=True)
        return None
    return buf.getvalue()


def scaled_wav_path(path: str, level: float | int) -> str | None:
    """Path to a cached copy of ``path`` scaled to volume ``level`` 0.0-1.0.

    Legacy int 0-10 handled: divide by 10. A file, not a bytes buffer, because
    winsound refuses SND_MEMORY together with SND_ASYNC. Written once per sound
    per level into temp dir; level in filename so changing setting picks a
    different file. Returns None if anything fails, leaving caller to play
    original at full volume.

    PERF-005: the temp directory is a managed cache (byte/file budget, oldest
    evicted, startup pruning) so long sessions cannot grow it without bound.
    """
    import tempfile

    try:
        lv = float(level)
    except (TypeError, ValueError):
        return None
    # legacy int scale
    if lv > 1.0 and lv <= 10.0 and float(lv).is_integer():
        lv = lv / 10.0
    lv = max(0.0, min(1.0, lv))
    if not (0.0 < lv < 1.0):
        return None
    try:
        stem = os.path.splitext(os.path.basename(path))[0]
        cache_dir = _scaled_cache_dir()
        os.makedirs(cache_dir, exist_ok=True)
        # quantize to 1% steps to keep cache bounded
        q = int(round(lv * 100))
        out = os.path.join(cache_dir, f"{stem}_v{q}.wav")
        if os.path.exists(out) and os.path.getmtime(out) >= os.path.getmtime(path):
            return out
        data = scale_wav_bytes(path, lv)
        if data is None:
            return None
        with open(out, "wb") as fh:
            fh.write(data)
        # safe insertion: prune the on-disk budget, protecting the fresh file
        _prune_scaled_cache_dir(protect=out)
        return out
    except OSError:
        logger.debug("volume cache write failed for %s", path, exc_info=True)
        return None


# ---- PERF-005: bounded winsound scaled-WAV cache ---------------------------
_SCALED_CACHE_DIR_NAME = "fastprompter_sound"
# ~256 MiB on-disk budget; 1% levels x 414 shipped WAVs can otherwise reach
# ~2.11 GiB. 4096 files also caps the per-level explosion independently.
_SCALED_CACHE_MAX_BYTES = 256 * 1024 * 1024
_SCALED_CACHE_MAX_FILES = 4096
# winsound SND_ASYNC reads the file off disk; never delete a WAV younger than
# this grace window (it may still be playing asynchronously).
_SCALED_CACHE_GRACE_SECONDS = 30.0
# in-memory (path, level) resolution cache cap per SoundManager
_SCALED_MEM_CACHE_CAP = 2048


def _scaled_cache_dir() -> str:
    import tempfile
    return os.path.join(tempfile.gettempdir(), _SCALED_CACHE_DIR_NAME)


def _prune_scaled_cache_dir(protect: str | None = None) -> None:
    """Keep the on-disk scaled-WAV cache within its byte/file budget (PERF-005).

    Evicts oldest files first; never touches a file younger than the grace
    window (it may be mid-playback via winsound SND_ASYNC) and never the file
    passed as ``protect`` (the one just written). Best-effort: filesystem
    errors are swallowed, the cache is disposable.
    """
    import time as _time

    d = _scaled_cache_dir()
    try:
        entries = []
        total = 0
        now = _time.time()
        for name in os.listdir(d):
            p = os.path.join(d, name)
            try:
                if not os.path.isfile(p):
                    continue
                st = os.stat(p)
                entries.append((st.st_mtime, st.st_size, p))
                total += st.st_size
            except OSError:
                continue
        entries.sort(key=lambda e: e[0])  # oldest first
        for mtime, size, p in entries:
            if (total <= _SCALED_CACHE_MAX_BYTES
                    and len(entries) <= _SCALED_CACHE_MAX_FILES):
                break
            if protect is not None and os.path.normcase(p) == os.path.normcase(protect):
                continue
            if now - mtime < _SCALED_CACHE_GRACE_SECONDS:
                continue
            try:
                os.remove(p)
                total -= size
            except OSError:
                continue
    except OSError:
        pass


def _bounded_cache_insert(cache: dict, key, value) -> None:
    """Insert into the in-memory (path, level) cache, evicting the oldest
    entry when the mapping exceeds its cap (PERF-005)."""
    cache[key] = value
    while len(cache) > _SCALED_MEM_CACHE_CAP:
        try:
            cache.pop(next(iter(cache)), None)
        except StopIteration:
            break


class SoundManager(QObject):
    """Manages UI sound effects using QSoundEffect.

    Usage::

        sm = SoundManager(parent_widget, data_dict)
        sm.play("click")
        sm.play("tick")
    """

    def __init__(self, parent: QObject, data: dict[str, Any]) -> None:
        super().__init__(parent)
        self._data: dict[str, Any] = data
        self._players: dict[str, QSoundEffect] = {}
        self._sounds_dir: str = get_resource_path("sound")
        self._available_sounds: list[str] = discover_sound_files(self._sounds_dir)
        # PERF-004: the typewriter sound fires on every keystroke, so all
        # filesystem probing (file resolution, scaled-WAV cache validation)
        # must be cached after the first resolution of a configuration and
        # reused until the configuration changes or a playback actually fails.
        self._file_cache: dict[str, str | None] = {}
        self._file_sig: dict[str, Any] = {}
        self._scaled_cache: dict[tuple[str, int], tuple[bool, str | None]] = {}
        self._data_id: int = id(self._data)
        # PERF-005: prune leftover scaled-WAV temp files from previous sessions
        # at startup, before any playback could be using them.
        _prune_scaled_cache_dir()

    def invalidate_cache(self) -> None:
        """PERF-004: drop cached resolution when the sound configuration
        changes (mapping, volume, or a replaced profile data dict). The next
        play()/preview rebuilds it lazily."""
        self._file_cache.clear()
        self._file_sig.clear()
        self._scaled_cache.clear()
        self._data_id = id(self._data)

    def _file_resolution_sig(self, name: str) -> Any:
        """Cheap (no-stat) signature of the bits that affect file resolution
        for ``name``: the user-mapped file name. Defaults are static."""
        events = self._data.get("sound_events")
        if isinstance(events, dict) and isinstance(events.get(name), dict):
            return events[name].get("file")
        return None

    def get_available_sounds(self) -> list[str]:
        """Get list of available sound files, sorting favorites and defaults to top."""
        favs = set(self._data.get("sound_favorites", []))
        defaults = ["newday.wav", "newweek.wav", "newmonth.wav"]
        
        def sort_key(name):
            is_fav = name in favs
            try:
                def_idx = defaults.index(name)
            except ValueError:
                def_idx = 999
            return (not is_fav, def_idx, name)
            
        return sorted(self._available_sounds, key=sort_key)

    def play(self, name: str) -> None:
        """Play a named sound effect.

        Respects the ``sound_ui`` and ``sound_typewriter`` toggles
        and the ``sound_volume`` setting from the data dict.
        Silently does nothing if the corresponding toggle is off or
        the sound file is missing.
        """
        if not is_event_enabled(name, self._data):
            return

        # PERF-004: reuse the cached file resolution for this configuration
        # generation instead of re-probing the filesystem on every keystroke.
        if id(self._data) != self._data_id:
            self.invalidate_cache()
        sig = self._file_resolution_sig(name)
        cached = self._file_cache.get(name)
        if cached is not None and self._file_sig.get(name) == sig:
            file_name, path, path_exists = cached
        else:
            file_name = get_sound_file_for_event(
                name, self._data, self._sounds_dir)
            path = os.path.join(self._sounds_dir, file_name) if file_name else ""
            path_exists = bool(path) and os.path.exists(path)
            self._file_cache[name] = (file_name, path, path_exists)
            self._file_sig[name] = sig
        if not file_name:
            logger.debug("No sound file found for event: %s", name)
            return

        volume = get_event_volume(name, self._data)

        if QSoundEffect is None:
            self._play_winsound(path, volume, self._scaled_cache)
            return

        # Cache players for frequently used sounds
        if name not in self._players:
            self._players[name] = QSoundEffect(self)
        player = self._players[name]

        try:
            # volume is already 0.0-1.0
            player.setVolume(max(0.0, min(1.0, float(volume))))

            if path_exists:
                player.setSource(QUrl.fromLocalFile(path))
                player.play()
        except Exception:
            logger.exception("Failed to play sound")

    def play_file(self, file_name: str, level: float | int | None = None) -> None:
        """Play one file by name, ignoring every toggle.

        The settings panel needs this: a preview has to be audible while UI
        sounds are switched off, and it must not route through play(), whose
        whole job is to obey the toggles.
        """
        if not file_name:
            return
        path = os.path.join(self._sounds_dir, file_name)
        self._emit_file(path, level)

    def _emit_file(self, path: str, level: float | int | None = None) -> bool:
        """Play a resolved sound-library file at an EXPLICIT volume level.

        Returns True on a successful playback attempt, False on a missing file
        or a playback failure. Never raises into the timer scheduler.
        """
        if not path or not os.path.exists(path):
            return False
        try:
            if level is None:
                vol = _volume_level(self._data)
            else:
                pv = _parse_volume_value(level)
                vol = pv if pv is not None else _volume_level(self._data)
        except (TypeError, ValueError):
            vol = _volume_level(self._data)
        if QSoundEffect is None:
            self._play_winsound(path, vol, self._scaled_cache)
            return True
        try:
            # W2-fix: give timer playback its OWN player slot. Sharing
            # "__timer__" with settings previews meant a preview could
            # restomp setSource/setVolume while an alarm was mid-play,
            # cutting it off or dropping its explicit volume.
            player = self._players.setdefault("__alarm__", QSoundEffect(self))
            player.setVolume(max(0.0, min(1.0, float(vol))))
            player.setSource(QUrl.fromLocalFile(path))
            player.play()
            return True
        except Exception:
            logger.exception("Failed to play timer sound ref")
            return False

    @staticmethod
    def _resolve_library_path(rel: str, sounds_dir: str) -> str | None:
        """Resolve a ``file:`` timer ref to a sound-library path, or None.

        A timer's stored JSON must never turn the sound library into an
        arbitrary-file player: reject parent traversal (``../``), absolute
        paths, drive-qualified paths and UNC escapes. Only ``.wav`` files
        inside ``sounds_dir`` are accepted.
        """
        if not rel or not rel.lower().endswith(".wav"):
            return None
        cand = rel.replace("\\", "/")
        parts = cand.split("/")
        if any(p == ".." for p in parts):
            return None
        first = parts[0]
        if first == "" or ":" in first or first.startswith("\\\\") or cand.startswith("//"):
            return None
        base = os.path.normpath(sounds_dir)
        full = os.path.normpath(os.path.join(sounds_dir, rel))
        if full != base and not full.startswith(base + os.sep):
            return None
        if not os.path.isfile(full):
            return None
        return full

    def play_sound_ref(self, ref: str, level: float | int) -> bool:
        """One canonical explicit playback path for timer sounds.

        ``ref`` is either ``file:<rel>`` (a sound-library file, contained) or a
        named SoundManager event (resolved through the current settings, at the
        timer's explicit volume). Timer playback ignores the ``sound_ui`` toggle
        — the timer's own sound policy owns audibility — and never mutates the
        global sound settings.

        Returns False (never raises) on a missing file, an invalid ref, or a
        playback failure, so a vanished WAV cannot crash the scheduler.
        """
        if not isinstance(ref, str) or not ref:
            return False
        if ref.startswith("file:"):
            path = self._resolve_library_path(ref[len("file:"):], self._sounds_dir)
            if path is None:
                return False
            return self._emit_file(path, level)
        file_name = get_sound_file_for_event(ref, self._data, self._sounds_dir)
        if not file_name:
            return False
        # The named-event resolution must obey the SAME library containment
        # rule as ``file:`` refs: a stored user mapping such as "../outside.wav"
        # would otherwise turn the sound library into an arbitrary-file player.
        path = self._resolve_library_path(file_name, self._sounds_dir)
        if path is None:
            return False
        return self._emit_file(path, level)

    def play_click(self) -> None:
        """Convenience method for click sounds."""
        self.play("click")

    def play_tick(self, on: bool = True) -> None:
        """Tick on / tick off — two different sounds.

        `untick` -> tick_off.wav has been in the map since the registry was
        built, and nothing ever asked for it: every caller played "tick" in
        both directions, so switching a box OFF sounded exactly like
        switching it ON. Callers that are not a two-state toggle (a one-shot
        confirmation) keep the default and stay on "tick".
        """
        self.play("tick" if on else "untick")

    def play_hover(self) -> None:
        """Convenience method for hover sounds."""
        self.play("hover")

    def play_button_release(self) -> None:
        """Convenience method for button release sounds."""
        self.play("button_release")

    @staticmethod
    def _play_winsound(path: str, level: float | int = 1.0, cache: dict | None = None) -> None:
        """Fallback WAV playback without QtMultimedia.

        This is the path the SHIPPED build takes — QtMultimedia is not in the
        dist — so it has to honour the Volume setting or the setting is
        decorative. winsound has no volume of its own, so anything below 1.0
        plays a pre-scaled copy of the file instead. Level 0 is silence, and
        is answered by playing nothing rather than by a wav full of zeroes.
        """
        try:
            import winsound

            # PERF-004: cache the (source-exists, scaled-path) resolution so the
            # per-keystroke path never re-stats the source or the scaled cache.
            # The cache is trusted once built; an actual playback failure
            # invalidates it (handled in the except below).
            if cache is None:
                cache = {}
            try:
                lv = float(level)
                if lv > 1.0 and lv <= 10.0 and float(lv).is_integer():
                    lv = lv / 10.0
                lv = max(0.0, min(1.0, lv))
            except (TypeError, ValueError):
                lv = 1.0
            q = int(round(lv * 100))
            key = (path, q)
            cached = cache.get(key)
            if cached is not None:
                src_exists, scaled = cached
                if src_exists and scaled is not None:
                    winsound.PlaySound(
                        scaled, winsound.SND_FILENAME | winsound.SND_ASYNC)
                    return
                # previously resolved as missing: respect the cached verdict
                # (a silent no-op) without re-probing the filesystem
                return
            if lv <= 0.0 or not os.path.exists(path):
                _bounded_cache_insert(cache, key, (False, None))
                return
            scaled = scaled_wav_path(path, lv) or path
            _bounded_cache_insert(cache, key, (True, scaled))
            winsound.PlaySound(
                scaled, winsound.SND_FILENAME | winsound.SND_ASYNC)
        except Exception:
            # a real playback failure invalidates the cached path so the next
            # attempt re-resolves (e.g. the source WAV was replaced/deleted)
            try:
                # q may not be bound if exception was before its assignment
                q2 = locals().get("q")
                if q2 is not None:
                    cache.pop((path, q2), None)
                cache.pop((path, int(level) if isinstance(level, (int, float)) else level), None)
            except Exception:
                pass
            logger.exception("Failed to play sound via winsound")
