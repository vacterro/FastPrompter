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
    "silo": "click_soft.wav",
    "snippet": "click_double.wav",
    "tick": "tick_on.wav",
    "untick": "tick_off.wav",
    "delete": "ui_delete.wav",
    "clear": "ui_clear.wav",
    "type": "type_key_1.wav",
    "backspace": "type_key_3.wav",
    "click": "click_soft.wav",
    "hover": "cs_style/buttonrollover.wav",
    "button_click": "cs_style/buttonclick.wav",
    "button_release": "cs_style/buttonclickrelease.wav",
    "chest_open": "chest_open.wav",
    "chest_close": "chest_closed.wav",
    "notify": "notify.wav",
    "error": "error.wav",
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
    "italic": "click_soft.wav",
    "underline": "click_soft.wav",
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


def get_event_volume(event: str, data: dict[str, Any]) -> int:
    """Get the volume for a specific event (0-10).
    
    Falls back to global sound_volume if no per-event volume set.
    """
    sound_events = data.get("sound_events", {})
    if isinstance(sound_events, dict):
        event_config = sound_events.get(event)
        if isinstance(event_config, dict):
            vol_str = event_config.get("volume")
            if vol_str:
                try:
                    vol = int(vol_str)
                    return max(0, min(10, vol))
                except (ValueError, TypeError):
                    pass
    
    # Global volume
    try:
        vol = int(data.get("sound_volume", "5"))
    except (TypeError, ValueError):
        vol = 5
    return max(0, min(10, vol))


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


def _volume_level(data: dict[str, Any]) -> int:
    """The Volume spinner as an int 0-10, clamped, junk reading as 5."""
    try:
        vol = int(data.get("sound_volume", "5"))
    except (TypeError, ValueError):
        vol = 5
    return max(0, min(10, vol))


def _volume_factor(data: dict[str, Any]) -> float:
    """The Volume spinner as an amplitude factor 0.0-1.0."""
    return _volume_level(data) / 10.0


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


def scaled_wav_path(path: str, level: int) -> str | None:
    """Path to a cached copy of ``path`` scaled to volume ``level`` (0-10).

    A file, not a bytes buffer, because winsound refuses SND_MEMORY together
    with SND_ASYNC ("Cannot play asynchronously from memory") — and playing a
    UI click SYNCHRONOUSLY would freeze the editor for the length of the
    sound on every keystroke. Written once per sound per level into the
    system temp dir; the level is in the filename, so changing the setting
    picks a different file instead of racing a rewrite of the one in flight.

    Returns None if anything about the copy fails, leaving the caller to play
    the original at full volume rather than fall silent.
    """
    import tempfile

    if not (0 <= level < 10):
        return None
    try:
        stem = os.path.splitext(os.path.basename(path))[0]
        cache_dir = os.path.join(tempfile.gettempdir(), "fastprompter_sound")
        os.makedirs(cache_dir, exist_ok=True)
        out = os.path.join(cache_dir, f"{stem}_v{level}.wav")
        if os.path.exists(out) and os.path.getmtime(out) >= os.path.getmtime(path):
            return out
        data = scale_wav_bytes(path, level / 10.0)
        if data is None:
            return None
        with open(out, "wb") as fh:
            fh.write(data)
        return out
    except OSError:
        logger.debug("volume cache write failed for %s", path, exc_info=True)
        return None


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

        file_name = get_sound_file_for_event(name, self._data, self._sounds_dir)
        if not file_name:
            logger.debug("No sound file found for event: %s", name)
            return

        path: str = os.path.join(self._sounds_dir, file_name)
        volume = get_event_volume(name, self._data)

        if QSoundEffect is None:
            self._play_winsound(path, volume)
            return

        # Cache players for frequently used sounds
        if name not in self._players:
            self._players[name] = QSoundEffect(self)
        player = self._players[name]

        try:
            player.setVolume(volume / 10.0)

            if os.path.exists(path):
                player.setSource(QUrl.fromLocalFile(path))
                player.play()
        except Exception:
            logger.exception("Failed to play sound")

    def play_file(self, file_name: str, level: int | None = None) -> None:
        """Play one file by name, ignoring every toggle.

        The settings panel needs this: a preview has to be audible while UI
        sounds are switched off, and it must not route through play(), whose
        whole job is to obey the toggles.
        """
        if not file_name:
            return
        path = os.path.join(self._sounds_dir, file_name)
        self._emit_file(path, level)

    def _emit_file(self, path: str, level: int | None) -> bool:
        """Play a resolved sound-library file at an EXPLICIT volume level.

        Returns True on a successful playback attempt, False on a missing file
        or a playback failure. Never raises into the timer scheduler.
        """
        if not path or not os.path.exists(path):
            return False
        try:
            vol = _volume_level(self._data) if level is None else max(0, min(10, int(level)))
        except (TypeError, ValueError):
            vol = _volume_level(self._data)
        if QSoundEffect is None:
            self._play_winsound(path, vol)
            return True
        try:
            player = self._players.setdefault("__timer__", QSoundEffect(self))
            player.setVolume(vol / 10.0)
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

    def play_sound_ref(self, ref: str, level: int) -> bool:
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
    def _play_winsound(path: str, level: int = 10) -> None:
        """Fallback WAV playback without QtMultimedia.

        This is the path the SHIPPED build takes — QtMultimedia is not in the
        dist — so it has to honour the Volume setting or the setting is
        decorative. winsound has no volume of its own, so anything below 10
        plays a pre-scaled copy of the file instead. Level 0 is silence, and
        is answered by playing nothing rather than by a wav full of zeroes.
        """
        try:
            import winsound

            if level <= 0 or not os.path.exists(path):
                return
            src = scaled_wav_path(path, level) or path
            winsound.PlaySound(src, winsound.SND_FILENAME | winsound.SND_ASYNC)
        except Exception:
            logger.exception("Failed to play sound via winsound")
