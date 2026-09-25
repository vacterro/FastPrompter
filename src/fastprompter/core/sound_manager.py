"""Sound effect manager for FastPrompter.

Manages QSoundEffect instances with volume control, file mapping,
and toggles for UI and typewriter sounds.
"""

import inspect
import math
import os
import queue
import tempfile
import threading
import time
import wave
from collections import deque
from typing import Any

from PyQt6.QtCore import QEventLoop, QObject, QTimer, QUrl, pyqtSignal

try:
    # QtMultimedia drags in very large FFmpeg DLLs; portable builds may
    # exclude it, in which case we fall back to stdlib winsound.
    from PyQt6.QtMultimedia import QSoundEffect
except ImportError:
    QSoundEffect = None

from fastprompter.core import sound_library
from fastprompter.core.audio_hub import (
    DROPPED_OUTCOMES,
    AudioHub,
    NullTransport,
    Outcome,
    QtSoundTransport,
)
from fastprompter.core.audio_render import device_ready_wav
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
    "project": "Click.wav",
    "snippet": "click_double.wav",
    "tick": "tick_on.wav",
    "untick": "tick_off.wav",
    "delete": "ui_delete.wav",
    "clear": "ui_clear.wav",
    "type": "type_key_1.wav",
    "backspace": "type_key_3.wav",
    "delete_forward": "type_key_2.wav",
    "delete_selection": "ui_delete.wav",
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
    # Scroll wheel feedback in long panels — subtle by design.
    "scroll": "click_hint.wav",
    # Settings tabs (Window / Editor / Clock / Data). Its own event, not
    # `project`: switching a settings PAGE is not switching a project, and
    # sharing one event would make the two impossible to remap apart.
    "settings_tab": "menu_launch_upmenu1.wav",
    # T-1244 master-mute pair: DOWN when muting, UP when unmuting, so the
    # direction is audible the same way undo/redo and tick_on/tick_off are.
    # These two events are the ONLY sounds that survive the mute itself.
    "audio_mute_on": "menu_mnu_empt.wav",
    "audio_mute_off": "pop_up_02.wav",
    # T-1245 semantic UI APPEARANCE events: one sound when a user-visible
    # surface actually appears -- never on widget construction, relayout,
    # paint, retranslation or a hidden widget's internal refresh. Ownership:
    # each surface has exactly ONE appearance event; a dialog that owns a
    # more specific event (the Audio Hub -> audio_hub_show) must not also
    # fire the generic dialog_show for the same presentation.
    "app_show": "menu1.wav",
    "settings_show": "panel_open.wav",
    "audio_hub_show": "CaseOpen.wav",
    "dialog_show": "menu2.wav",
    "panel_show": "pop_up_02.wav",
    "notification_show": "chime_bell_ding1.wav",
    "hover_card_show": "click_hint.wav",
}

#: T-1245: the semantic appearance events. One emit per real appearance
#: transition; ``SoundManager.play_appearance`` is the only sanctioned route.
APPEARANCE_EVENTS: frozenset[str] = frozenset({
    "app_show", "settings_show", "audio_hub_show", "dialog_show",
    "panel_show", "notification_show", "hover_card_show",
})

#: Double-delivery guard: Qt can deliver a show signal more than once for
#: one appearance (showEvent + QEvent.Show from two code paths, re-entrancy
#: around setVisible). A second play_appearance call for the SAME event
#: inside this window is the SAME appearance and is swallowed -- while a
#: real hide -> show later (outside the window) emits one new event.
APPEARANCE_DEDUPE_S = 0.30

# The mute cue must be audible while muted (otherwise the unmute press is
# silent and the state is unverifiable by ear). Everything else is gated.
_MUTE_CUE_EVENTS: frozenset[str] = frozenset({"audio_mute_on", "audio_mute_off"})

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
# ---------------------------------------------------------------------------
# C0.6 -- one canonical event -> bus map.  Every ordinary FastPrompter event
# enters the hub on a real bus, so the user's global Overlay/Stack/Replace
# setting and the per-event override actually govern product playback.
# ---------------------------------------------------------------------------

_ALERT_EVENTS = frozenset({
    "timer", "timer_start", "notify", "error", "success",
    "pomodoro", "pomodoro_break", "alarm", "newday", "newweek", "newmonth",
})

_ALERT_SLOTS = frozenset({"__alarm__"})
_PREVIEW_SLOTS = frozenset({"__preview__"})


def _make_hub_transport():
    """Build the hub backend from the SAME Qt binding this module imported.

    The hub must never reach around this module for its own copy of Qt: a
    build (or a test) where ``QSoundEffect`` is unavailable or is a stand-in
    has NO mixing backend, and the truthful degraded fallback plus the proven
    single-transport policy engine is what must run there.
    """
    if QSoundEffect is None:
        return NullTransport()
    try:
        return QtSoundTransport(qsoundeffect_cls=QSoundEffect,
                                url_factory=QUrl.fromLocalFile)
    except Exception:
        return NullTransport()


def bus_for_event(event: str) -> str:
    """Which audio bus an ordinary named event belongs to."""
    name = str(event or "")
    if name in _PREVIEW_SLOTS:
        return "preview"
    if name in _ALERT_SLOTS or name in _ALERT_EVENTS:
        return "alert"
    if name.startswith("file:"):
        return "alert"  # a timer's explicit sound ref
    if name.startswith("problip"):
        return "problip"
    if name.startswith("voice"):
        return "voice"
    return "ui"


_HOTKEY_DEFAULT_MARK = "sound_hotkey_on_by_default"


def _wav_duration_ms(path: str) -> int | None:
    """Return a WAV's playback length without loading its samples."""
    try:
        with wave.open(path, "rb") as source:
            rate = source.getframerate()
            if rate <= 0:
                return None
            return max(1, round(source.getnframes() * 1000 / rate))
    except (OSError, EOFError, wave.Error):
        return None


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
    "project": "Switch project",
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
    "type": "Typewriter",
    "backspace": "Backspace",
    "delete_forward": "Delete forward",
    "delete_selection": "Delete selected text",
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
    "scroll": "Scroll tick",
    "settings_tab": "Settings tab switch",
    # T-1244: the master-mute confirmation cues are ordinary, remappable
    # Sound Settings rows -- with enabled checkbox, picker, gain, preview.
    "audio_mute_on": "Master mute ON",
    "audio_mute_off": "Master mute OFF",
    # T-1245: semantic appearance events. The labels say WHAT appeared,
    # never HOW it was constructed -- construction, relayout, paint and
    # retranslation must never reach these rows.
    "app_show": "App becomes visible",
    "settings_show": "Settings panel opens",
    "audio_hub_show": "Sound hub opens",
    "dialog_show": "Dialog opens",
    "panel_show": "Panel opens",
    "notification_show": "Notification appears",
    "hover_card_show": "Hover card appears",
}


_DISCOVERED_CACHE: dict[tuple[str, bool], tuple[float, list[str]]] = {}

#: Private sound namespaces.  A directory whose name starts with "_" is a
#: VAULT: shipped raw material (GoldSrc vox/fvox fragments, alternate packs)
#: that must stay resolvable by reference but must never flood the ordinary
#: picker -- 757 vault files turned one combo into ~77k widget items and made
#: Sound Settings take seconds to open.
VAULT_DIR_NAME = "_vault"


def _is_private_dir(name: str) -> bool:
    return name.startswith("_")


def discover_sound_files(sounds_dir: str, force: bool = False, *,
                         include_vault: bool = False) -> list[str]:
    """Discover the ordinary WAV library, as sorted relative refs.

    Private ``_``-prefixed namespaces (``_vault/``) are skipped by default:
    they stay fully playable by reference, they are simply not part of the
    everyday picker.  Pass ``include_vault=True`` for the explicit vault
    browser.
    """
    if not os.path.isdir(sounds_dir):
        logger.warning("Sounds directory not found: %s", sounds_dir)
        return []

    cache_key = (sounds_dir, bool(include_vault))
    if not force and cache_key in _DISCOVERED_CACHE:
        mtime, cached = _DISCOVERED_CACHE[cache_key]
        try:
            if os.path.getmtime(sounds_dir) <= mtime:
                return list(cached)
        except OSError:
            pass

    # Recursive: cs_style/ is a real subfolder and its three files are the
    # ones the CS 1.6 style names, so a flat listdir left them unreachable
    # from the picker and made those defaults unresolvable.
    wav_files = []
    try:
        cur_mtime = os.path.getmtime(sounds_dir)
        for root, dirs, names in os.walk(sounds_dir):
            if not include_vault:
                # Prune in place: never descend into a private namespace.
                dirs[:] = [d for d in dirs if not _is_private_dir(d)]
            for f in names:
                if not f.lower().endswith(".wav"):
                    continue
                rel = os.path.relpath(os.path.join(root, f), sounds_dir)
                wav_files.append(rel.replace(os.sep, "/"))
        wav_files.sort()
        _DISCOVERED_CACHE[cache_key] = (cur_mtime, wav_files)
        logger.debug("Discovered %d sound files in %s", len(wav_files), sounds_dir)
    except OSError:
        logger.error("Failed to list sounds directory: %s", sounds_dir)
    
    return wav_files


def discover_vault_files(sounds_dir: str, force: bool = False) -> list[str]:
    """The private vault, as refs relative to ``sounds_dir`` (``_vault/...``).

    These refs resolve and play exactly like any other library reference;
    they are only kept out of the default listing.
    """
    root = os.path.join(sounds_dir, VAULT_DIR_NAME)
    if not os.path.isdir(root):
        return []
    everything = discover_sound_files(sounds_dir, force, include_vault=True)
    prefix = f"{VAULT_DIR_NAME}/"
    return [ref for ref in everything if ref.startswith(prefix)]


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
    # A STORED SOUND REFERENCE IS A REFERENCE, NOT A FILESYSTEM PATH.  Validate
    # it through the one canonical resolver; never join it under sounds_dir and
    # test the result, or a valid ``user:imported/x.wav`` / ``builtin:`` /
    # private ``_vault`` ref reads as missing and silently falls back.
    sound_events = data.get("sound_events", {})
    if isinstance(sound_events, dict):
        event_config = sound_events.get(event)
        if isinstance(event_config, dict):
            ref = event_config.get("file")
            if ref and sound_library.resolve_sound_ref(
                    ref, builtin_root=sounds_dir) is not None:
                # Return the EXACT stored token: no strip, no rewrite, no
                # packaged-root path.  The resolver turns it into a path later.
                return ref

    # Fall back to defaults -- same canonical resolution, not os.path.join.
    ref = _DEFAULT_SOUND_MAP.get(event)
    if ref and sound_library.resolve_sound_ref(
            ref, builtin_root=sounds_dir) is not None:
        return ref

    # Last resort: try {event}.wav
    ref = f"{event}.wav"
    if sound_library.resolve_sound_ref(
            ref, builtin_root=sounds_dir) is not None:
        return ref

    return None


def is_event_enabled(event: str, data: dict[str, Any]) -> bool:
    """Check if a sound event is enabled in settings.
    
    Respects the T-1244 ``audio_global_muted`` master mute, the
    sound_ui/sound_typewriter global toggles and the per-event enabled flag.
    The mute cue events themselves stay audible while muted.
    """
    # Master mute (T-1244): a hotkey/setting can silence EVERY event, with
    # the sole exception of the mute cue pair itself — without that escape
    # hatch the unmute press would play nothing and the state would be
    # indistinguishable from a broken audio chain.
    if (data.get("audio_global_muted", "False") == "True"
            and event not in _MUTE_CUE_EVENTS):
        return False
    # Global toggles. Backspace and the other editor delete keys belong to
    # the TYPEWRITER switch, not the UI one — they are the same effect, and
    # the user asked for it as an option of the typewriter sound. Left in
    # the UI branch it clattered away while the typewriter was off.
    if event in ("type", "backspace", "delete_forward", "delete_selection"):
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


# ---------------------------------------------------------------------------
# Relative per-event gain (T-1242 spec 10-12)
#
# The old per-event control was an ABSOLUTE 0..10 level whose 0 was a magic
# "inherit the global volume" sentinel -- so it could only ever be quieter
# than global, and the sentinel read as "muted" to users.  The user-facing
# concept is now GAIN in dB, relative to the global master:
#
#     master    = sound_volume, 0.0..1.0
#     factor    = 10 ** (gain_db / 20)
#     effective = clamp(master * factor, 0.0, 1.0)
#
# 0 dB is exactly the global volume; negative is quieter, positive louder.
# ---------------------------------------------------------------------------

GAIN_DB_MIN = -24.0
GAIN_DB_MAX = 12.0
GAIN_DB_DEFAULT = 0.0

#: Marks a profile whose sound_events carry gain_db.  Legacy ``volume`` is
#: kept alongside it so an older build can still read the profile.
GAIN_SCHEMA_KEY = "sound_gain_schema"
GAIN_SCHEMA_VERSION = "1"


def clamp_gain_db(value: float) -> float:
    return max(GAIN_DB_MIN, min(GAIN_DB_MAX, float(value)))


def gain_db_to_factor(gain_db: float) -> float:
    """Amplitude factor for a dB gain (0 dB -> 1.0)."""
    return 10.0 ** (clamp_gain_db(gain_db) / 20.0)


def factor_to_gain_db(factor: float) -> float:
    """dB gain for an amplitude ratio; a non-positive ratio is the floor."""
    try:
        value = float(factor)
    except (TypeError, ValueError):
        return GAIN_DB_DEFAULT
    if value <= 0.0:
        return GAIN_DB_MIN
    return clamp_gain_db(20.0 * math.log10(value))


def parse_gain_db(raw) -> float | None:
    """Parse a stored gain value; None when absent or unreadable."""
    if raw is None or raw == "" or isinstance(raw, bool):
        return None
    try:
        return clamp_gain_db(float(str(raw).strip()))
    except (TypeError, ValueError):
        return None


def global_volume(data: dict[str, Any]) -> float:
    """The CURRENT master volume 0.0-1.0 (the truthful UI value)."""
    gv = _parse_volume_value(data.get("sound_volume", "0.5"))
    return gv if gv is not None else 0.5


def get_event_gain_db(event: str, data: dict[str, Any]) -> float:
    """The stored relative gain for one event, 0 dB when unset."""
    sound_events = data.get("sound_events", {})
    if isinstance(sound_events, dict):
        cfg = sound_events.get(event)
        if isinstance(cfg, dict):
            parsed = parse_gain_db(cfg.get("gain_db"))
            if parsed is not None:
                return parsed
            # A profile written before the migration: derive the gain that
            # reproduces its absolute level against the CURRENT master.
            legacy = cfg.get("volume")
            if legacy not in (None, ""):
                absolute = _parse_volume_value(legacy)
                if absolute is not None and absolute > 0.0:
                    master = global_volume(data)
                    if master > 0.0:
                        return factor_to_gain_db(absolute / master)
    return GAIN_DB_DEFAULT


def effective_event_volume(event: str, data: dict[str, Any]) -> float:
    """master * 10**(gain_db/20), clamped to 0.0-1.0."""
    master = global_volume(data)
    return max(0.0, min(1.0, master * gain_db_to_factor(
        get_event_gain_db(event, data))))


def get_event_volume(event: str, data: dict[str, Any]) -> float:
    """Effective amplitude for one event (global master + relative gain)."""
    return effective_event_volume(event, data)


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
        # A ref is stale only when the one canonical resolver cannot find it.
        # A valid ``user:`` / ``builtin:`` / ``_vault`` ref resolves through the
        # resolver, so it must SURVIVE migration byte-for-byte -- never be healed
        # into the event default just because a packaged-root join of the token
        # does not exist.
        if chosen and sounds_dir and sound_library.resolve_sound_ref(
                chosen, builtin_root=sounds_dir) is None:
            chosen = ""                      # stale name: fall back to default
        cfg["file"] = chosen or default_file
        cfg.setdefault("enabled", "False" if event in _DEFAULT_OFF else "True")
        cfg.setdefault("volume", "")
        healed[event] = cfg
    # anything the user added for an event this build does not know stays put
    for event, cfg in events.items():
        if event not in healed and isinstance(cfg, dict):
            healed[event] = dict(cfg)
    _migrate_event_gain(data, healed)
    data["sound_events"] = healed
    _heal_hotkey_default(data)
    # T-1242 spec 8: one-shot retirement of the experimental render/edge-pad
    # defaults.  Runs on every start but acts at most once per profile.
    SoundManager.migrate_experimental_render_policy(data)


def _migrate_event_gain(data: dict[str, Any], events: dict[str, Any]) -> int:
    """Give every event a ``gain_db``, preserving today's audible relation.

    Legacy blank/zero ``volume`` meant "inherit global" -> 0 dB.  An explicit
    absolute level becomes the gain that reproduces the SAME effective
    amplitude against the current master, clamped to the control's range.
    A muted master cannot define a ratio, so those migrate to 0 dB (the
    master stays authoritative and still mutes everything).
    """
    master = global_volume(data)
    migrated = 0
    for cfg in events.values():
        if not isinstance(cfg, dict):
            continue
        if parse_gain_db(cfg.get("gain_db")) is not None:
            continue
        legacy = cfg.get("volume")
        gain = GAIN_DB_DEFAULT
        if legacy not in (None, "") and master > 0.0:
            absolute = _parse_volume_value(legacy)
            if absolute is not None and absolute > 0.0:
                gain = factor_to_gain_db(absolute / master)
        cfg["gain_db"] = f"{gain:.1f}"
        migrated += 1
    data[GAIN_SCHEMA_KEY] = GAIN_SCHEMA_VERSION
    return migrated


# ---- PERF-001: bounded diagnostic metadata cache ---------------------------
# `_record()` enriches every request with the source WAV's format summary and
# the already-published device-rate render. Both used to re-open the file and,
# for the render identity, SHA-256 the WHOLE file on every request -- on the
# typing hot path and AFTER the AudioHub verdict, so hub coalescing could not
# help. The cache is keyed by a stable file signature (normalised path + size +
# mtime_ns): a replaced or edited file changes its signature and is re-read
# exactly once, and the same basename in another directory stays a distinct
# entry. Memory-only, bounded, never a background task.
_DIAG_CACHE_CAP = 512
_diag_format_cache: dict[tuple, str] = {}
_diag_render_cache: dict[tuple, str | None] = {}
_diag_digest_cache: dict[tuple, str | None] = {}


def _file_signature(path: str) -> tuple[str, int, int] | None:
    """Stable identity of a file on disk, or None when it cannot be stat-ed."""
    try:
        info = os.stat(path)
    except OSError:
        return None
    return (os.path.normcase(os.path.abspath(path)),
            int(info.st_size), int(info.st_mtime_ns))


def _diag_cache_put(cache: dict, key: tuple, value) -> None:
    """Insert with FIFO eviction so a cache can never grow without bound."""
    if len(cache) >= _DIAG_CACHE_CAP:
        cache.pop(next(iter(cache)), None)
    cache[key] = value


def _diag_cache_clear() -> None:
    """Drop every cached diagnostic fact (called by invalidate_cache())."""
    _diag_format_cache.clear()
    _diag_render_cache.clear()
    _diag_digest_cache.clear()


def _read_wav_summary(path: str) -> str:
    """"PCM 16bit 1ch 22050Hz 0.31s" -- or a short reason it is unreadable."""
    try:
        with wave.open(path, "rb") as wf:
            comp = wf.getcomptype()
            rate = wf.getframerate() or 0
            frames = wf.getnframes()
            duration = (frames / rate) if rate else 0.0
            return (f"{'PCM' if comp == 'NONE' else comp} "
                    f"{wf.getsampwidth() * 8}bit {wf.getnchannels()}ch "
                    f"{rate}Hz {duration:.2f}s")
    except FileNotFoundError:
        return "MISSING"
    except (OSError, wave.Error, EOFError):
        return "UNREADABLE"


def _wav_format_summary(path: str, signature: tuple | None = None) -> str:
    """Cached `_read_wav_summary` (PERF-001): one parse per file signature.

    `signature` may be passed in by a caller that already stat-ed the file, so
    one request costs one stat instead of one per enrichment.
    """
    if signature is None:
        signature = _file_signature(path)
    if signature is not None:
        cached = _diag_format_cache.get(signature)
        if cached is not None:
            return cached
    summary = _read_wav_summary(path)
    if signature is not None:
        _diag_cache_put(_diag_format_cache, signature, summary)
    return summary


def _rendered_path_for(path: str, signature: tuple | None = None) -> str | None:
    """The already-published device-rate render for ``path"" (never renders)."""
    # PERF-001: the render IDENTITY (whole-file digest + device rate + render
    # version) is cached per file signature, so a stable source costs one
    # memory lookup instead of a whole-file SHA-256 on every request. The
    # published file itself is still stat-ed per call -- O(1) -- so a render
    # that appears or disappears later is reported on the very next request.
    if signature is None:
        signature = _file_signature(path)
    if signature is None:
        return None
    try:
        from fastprompter.core.audio_render import RENDER_VERSION, device_sample_rate

        target = device_sample_rate()
        if not target:
            return None
        key: tuple = (signature, int(target), int(RENDER_VERSION))
    except Exception:
        return None
    if key in _diag_render_cache:
        out = _diag_render_cache[key]
    else:
        out = _resolve_render_identity(path, int(target))
        _diag_cache_put(_diag_render_cache, key, out)
    return out if out and os.path.exists(out) else None


def _resolve_render_identity(path: str, target: int) -> str | None:
    """The published render filename for `path` at `target` Hz, or None."""
    try:
        from fastprompter.core.audio_render import RENDER_VERSION
        from fastprompter.core.audio_render import (
            _source_digest as _render_digest,
        )

        digest = _render_digest(path)
        if not digest:
            return None
        stem = os.path.splitext(os.path.basename(path))[0][:24]
        return os.path.join(
            tempfile.gettempdir(), "fastprompter_sound",
            f"{stem}_{digest}_r{int(target)}_v{RENDER_VERSION}.wav")
    except Exception:
        return None


def render_enabled_state() -> bool:
    """The renderer's live A/B switch state (for change detection)."""
    try:
        from fastprompter.core.audio_render import render_enabled

        return render_enabled()
    except Exception:
        return False


def edge_pad_enabled_state() -> bool:
    """The edge-pad A/B switch's live state (for change detection)."""
    try:
        from fastprompter.core.audio_render import edge_pad_enabled

        return edge_pad_enabled()
    except Exception:
        return False


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

    T-1242: cache identity is the source CONTENT digest + level, never the
    basename -- two same-named files from different libraries (builtin vs
    managed user import) can never share one scaled copy.  Shared digest
    helper with audio_render (RENDER_VERSION keeps algorithm changes apart
    from level changes).
    """

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
        digest = _source_digest(path)
        if not digest:
            return None
        cache_dir = _scaled_cache_dir()
        os.makedirs(cache_dir, exist_ok=True)
        # quantize to 1% steps to keep cache bounded
        q = int(round(lv * 100))
        stem = os.path.splitext(os.path.basename(path))[0][:24]
        out = os.path.join(cache_dir, f"{stem}_{digest}_v{q}.wav")
        # The cache key IS the published filename (T-1242: this name was
        # missing, so every cold scale raised NameError inside a caller's
        # broad ``except Exception`` and silently lost the scaled copy).
        key = out
        if os.path.exists(out):
            return out
        owner, flight = _scaled_claim(key)
        if not owner:
            if not flight.wait(timeout=30.0):
                return None
            return out if os.path.exists(out) else None
        try:
            data = scale_wav_bytes(path, lv)
            if data is None:
                return None
            _atomic_write_bytes(out, data, cache_dir)
            _prune_scaled_cache_dir(protect=out)
            return out
        finally:
            _scaled_release(key, flight)
    except OSError:
        logger.debug("volume cache write failed for %s", path, exc_info=True)
        return None
    except Exception:
        # Scaling is an OPTIMISATION; a bug here must degrade to "play the
        # original", never to silence.
        logger.warning("volume cache aborted for %s", path, exc_info=True)
        return None


def _read_source_digest(path: str) -> str | None:
    """Short SHA256 over file content; shared identity for both WAV caches."""
    import hashlib

    digest = hashlib.sha256()
    try:
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(65536), b""):
                digest.update(chunk)
    except OSError:
        return None
    return digest.hexdigest()[:16]


def _source_digest(path: str) -> str | None:
    """Cached `_read_source_digest` (PERF-001): the whole file is hashed once
    per file signature, never once per playback request."""
    signature = _file_signature(path)
    if signature is not None and signature in _diag_digest_cache:
        return _diag_digest_cache[signature]
    digest = _read_source_digest(path)
    if signature is not None:
        _diag_cache_put(_diag_digest_cache, signature, digest)
    return digest


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

# ---- T-1242 single-flight scaled-WAV cache ------------------------------
# scaled_wav_path() has the same concurrency class as
# audio_render.device_ready_wav(): prewarm_device_cache() runs on a daemon
# thread while the first real cue may call scaled_wav_path() for the SAME
# source/cache key. Without a per-key lock two threads write the SAME final
# .wav directly and a caller can observe a half-written file. Exactly one
# thread writes; others wait on the published file.
_SCALED_RENDER_LOCK = threading.Lock()
_SCALED_FLIGHTS: dict[str, threading.Event] = {}
_SCALED_FLIGHTS_MAX = 64


def _scaled_claim(key: str) -> tuple[bool, threading.Event | None]:
    """Atomically claim the scaled-cache slot for ``key``."""
    with _SCALED_RENDER_LOCK:
        event = _SCALED_FLIGHTS.get(key)
        if event is not None:
            return False, event
        event = threading.Event()
        if len(_SCALED_FLIGHTS) >= _SCALED_FLIGHTS_MAX:
            for done in [k for k, e in _SCALED_FLIGHTS.items() if e.is_set()]:
                _SCALED_FLIGHTS.pop(done, None)
        if len(_SCALED_FLIGHTS) >= _SCALED_FLIGHTS_MAX:
            # Registry saturated with active owners: fail closed without
            # returning an event belonging to another key.
            refusal = threading.Event()
            refusal.set()
            return False, refusal
        _SCALED_FLIGHTS[key] = event
        return True, event


def _scaled_release(key: str, event: threading.Event) -> None:
    """Publish completion, then forget the key (bounded registry)."""
    event.set()
    with _SCALED_RENDER_LOCK:
        if _SCALED_FLIGHTS.get(key) is event:
            _SCALED_FLIGHTS.pop(key, None)


def _atomic_write_bytes(final_path: str, data: bytes, dir_path: str) -> None:
    """Write data to final_path atomically: unique temp, fsync, os.replace."""
    import tempfile
    fd, tmp = tempfile.mkstemp(prefix=f"{os.path.basename(final_path)}.",
                               suffix=".part", dir=dir_path or None)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, final_path)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


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


# How long after a winsound playback ends the device is left alone before
# the next sound starts. SND_ASYNC resets the waveOut device asynchronously;
# starting a fresh file during that reset can play the previous sound's
# leftover tail at the head of the new one.
# A UI blip may wait behind at most this much already-sounding audio
# before it is dropped rather than replayed seconds later (a long alarm
# owns the channel; a click must not fire after it). A rapid burst of
# SHORT blips (mashing a hotkey) stacks freely below this window.
# Bounded FIFO depth for stacking a rapid hotkey burst; when full the
# OLDEST queued blip is dropped so the newest intent survives.
_SOUND_QUEUE_MAX = 64
_WINSOUND_DEVICE_LOCK = threading.RLock()


def _silence_winsound(trace=None):
    """Stop whatever is sounding on the single waveOut device (T-1221).

    T-1228: reserved for TRUE silence only -- shutdown, an explicit cancel
    with NO replacement, or catastrophic retirement. Ordinary request-to-
    request replacement must NOT call this: a fresh ``PlaySound(new.wav,
    SND_ASYNC)`` already replaces the sounding wave on the single device,
    and a stop immediately before the start is the user-reported audible
    transient ("pop") before the intended notification.
    """
    try:
        import winsound
        if trace is not None:
            try:
                trace("STOP_DEVICE", None, "explicit silence")
            except Exception:
                pass
        with _WINSOUND_DEVICE_LOCK:
            winsound.PlaySound(None, 0)
    except (ImportError, RuntimeError):
        pass


class _SerialWavWorker:
    """One transport worker for LONG sounds. No Qt objects or GUI access.

    T-1221: the transport must never own a backlog of user sound intent.
    It holds ONE current long sound plus AT MOST ONE not-yet-started
    replacement, latest wins: ``submit``/``replace`` overwrite whatever the
    worker has not started yet, and ``drop_pending`` discards it. Short UI
    feedback never enters this worker at all — it dispatches SND_ASYNC
    directly at the moment of its action (see SoundManager._start_request),
    so it can never be blocked behind a long alarm.

    Longs are dispatched SND_ASYNC as well: a synchronous PlaySound holds
    the winsound module lock for the whole WAV, which would serialize every
    other dispatch — including the interrupt — behind the sounding alarm.
    The long's completion boundary is its file duration, waited out on the
    worker WITHOUT holding the device lock, interruptible by a newer
    submission (notify) or by close().
    """

    def __init__(self, play, trace=None):
        self._cond = threading.Condition()
        self._next_job = None
        self._epoch = 0
        self._dispatching = False
        # Token of the job taken but not yet finished (playing or about to
        # play). Plain attribute: GIL-atomic reads, benign staleness — the
        # caller's confirm loop re-reads it (T-1221 §4).
        self.holding = None
        self.completed = queue.SimpleQueue()
        self.closed = threading.Event()
        self.play = play
        # T-1228: optional bounded transport trace hook (memory only).
        self._trace = trace
        self.thread = threading.Thread(target=self._run, name="FastPrompter audio", daemon=True)
        self.thread.start()

    def submit(self, job):
        """Latest-wins: replace any not-yet-started job with this one."""
        with self._cond:
            self._next_job = job
            self._epoch += 1
            self._cond.notify_all()

    # Same mailbox, intent-revealing name for replacement submissions.
    replace = submit

    def drop_pending(self):
        """Discard intent and wait until any device dispatch has finished."""
        with self._cond:
            self._next_job = None
            # Wake the duration wait of a superseded current sound: its
            # epoch check now fails, so the worker takes the next intent
            # instead of sleeping out a sound that no longer owns the
            # channel (T-1221).
            self._epoch += 1
            while self._dispatching:
                self._cond.wait()
            self._cond.notify_all()

    def pending(self):
        """True when a not-yet-started job sits in the mailbox."""
        with self._cond:
            return self._next_job is not None

    def _run(self):
        while not self.closed.is_set():
            with self._cond:
                while self._next_job is None and not self.closed.is_set():
                    self._cond.wait(0.1)
                job, self._next_job = self._next_job, None
                taken_epoch = self._epoch
                self.holding = job[0] if job is not None else None
            if job is None or self.closed.is_set():
                continue
            token, path, volume, cache, sync = job
            # T-1228: NO unconditional device silence before a fresh WAV.
            # ``PlaySound(new.wav, SND_ASYNC)`` itself replaces whatever is
            # sounding on the single waveOut device; a stop-then-start here is
            # exactly the stray "pop" heard before the intended notification.
            # A newer intent is detected by the epoch/mailbox check below and
            # skipped, so obsolete audio is dropped without ever touching the
            # device.
            with self._cond:
                superseded = (self._epoch != taken_epoch
                              or self._next_job is not None)
            if superseded:
                self.holding = None
                continue
            if self._trace is not None:
                try:
                    self._trace("START_WAV", {"id": token, "path": path},
                                "worker dispatch")
                except Exception:
                    pass
            # SND_ASYNC only: a synchronous PlaySound holds the winsound
            # module lock for the WHOLE playback, which serializes every
            # other dispatch behind the sounding long — measured on real
            # Windows: an interrupt PlaySound(None, 0) waited 9 seconds
            # behind a SND_SYNC alarm (that lock is the actual root cause
            # of the user's SRC-010 queue report). Async returns at once
            # and a fresh call replaces the sounding wave; the completion
            # boundary is the file's own duration, waited out here WITHOUT
            # holding the device lock, so shorts and interrupts stay
            # immediate (T-1221).
            try:
                with self._cond:
                    if (self._epoch != taken_epoch or self._next_job is not None
                            or self.closed.is_set()):
                        self.holding = None
                        continue
                    self._dispatching = True
                try:
                    with _WINSOUND_DEVICE_LOCK:
                        result = self.play(path, volume, cache, False)
                finally:
                    with self._cond:
                        self._dispatching = False
                        self._cond.notify_all()
                ok = result is not False
            except Exception:
                logger.exception("WAV worker playback failed")
                self.completed.put((token, False))
                self.holding = None
                continue
            if sync:
                ms = _wav_duration_ms(path)
                end_by = time.monotonic() + ((ms / 1000.0) if ms else 0.12)
                with self._cond:
                    while (time.monotonic() < end_by
                           and self._epoch == taken_epoch
                           and not self.closed.is_set()):
                        remaining = end_by - time.monotonic()
                        self._cond.wait(min(0.05, max(0.005, remaining)))
            self.completed.put((token, ok))
            self.holding = None

    def close(self, *_args):
        self.drop_pending()
        self.closed.set()
        with self._cond:
            self._cond.notify_all()


_SOURCE_CACHE: dict[tuple[str, int, str], str] = {}
_SOURCE_CACHE_MAX = 256


def _sound_source():
    """Bounded caller provenance, without retaining frame objects.

    The resolution is cached per call site: a typewriter/backspace burst hits
    the same (file, line, function) on every keystroke, so after the first
    request the hot path answers from the cache and never re-walks frames
    (audit 6.4: provenance must not become a typing-latency regression)."""
    frame = inspect.currentframe()
    try:
        f = frame.f_back if frame else None
        for _ in range(12):
            if f is None:
                break
            if f.f_code.co_filename != __file__ and f.f_code.co_name != "play_sound":
                key = (f.f_code.co_filename, f.f_lineno, f.f_code.co_name)
                cached = _SOURCE_CACHE.get(key)
                if cached is not None:
                    return cached
                value = (f"{os.path.basename(f.f_code.co_filename)}:"
                         f"{f.f_lineno}:{f.f_code.co_name}")
                if len(_SOURCE_CACHE) >= _SOURCE_CACHE_MAX:
                    _SOURCE_CACHE.clear()
                _SOURCE_CACHE[key] = value
                return value
            f = f.f_back
        return "unknown"
    finally:
        del frame


def _winsound_play(scaled: str, sync: bool) -> None:
    """One winsound device call.

    SND_SYNC is NOT a winsound constant — synchronous playback is simply
    the ABSENCE of SND_ASYNC — and reading the attribute raised
    AttributeError on real Windows, silently killing every long alarm on
    the packaged path. So: sync == no SND_ASYNC flag (T-1221). SND_ASYNC
    returns at once, and a fresh call REPLACES whatever is still sounding
    on the single waveOut device: that is how a deliberate action's blip
    lands in the moment of the action instead of joining a serial FIFO
    that replays after the user moved on (SRC-010).
    """
    import winsound

    flags = winsound.SND_FILENAME | getattr(winsound, "SND_NODEFAULT", 2)
    if not sync:
        flags |= winsound.SND_ASYNC
    with _WINSOUND_DEVICE_LOCK:
        winsound.PlaySound(scaled, flags)


class SoundManager(QObject):
    #: Emitted from the render worker with the paths that are ready to be
    #: attached to the transport.  A QUEUED CONNECTION marshals the actual
    #: QSoundEffect creation back onto the GUI thread -- QSoundEffect is a
    #: QObject and must not be built on a worker.
    _preload_ready = pyqtSignal(list)

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
        self._short_player = None
        self._sounds_dir: str = get_resource_path("sound")
        self._available_sounds: list[str] = discover_sound_files(self._sounds_dir)
        # winsound serialization (see _emit_winsound): monotonic time until the
        # currently scheduled playback ends, its file path, the one sound
        # waiting behind it, and whether the drain timer is armed.
        self._pending = deque()
        self._current = None
        self._provenance = deque(maxlen=256)
        # T-1228: bounded, memory-only transport trace so a stray-audio report
        # can be attributed (which operation, which file, which reason) without
        # writing anything to disk on every typewriter keystroke.
        self._transport_trace = deque(maxlen=256)
        self._request_seq = 0
        self._finished = deque(maxlen=256)
        self._closed = False
        self._worker = None
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(15)
        self._poll_timer.timeout.connect(self._poll_transport)
        # PERF-004: the typewriter sound fires on every keystroke, so all
        # filesystem probing (file resolution, scaled-WAV cache validation)
        # must be cached after the first resolution of a configuration and
        # reused until the configuration changes or a playback actually fails.
        self._file_cache: dict[str, str | None] = {}
        self._file_sig: dict[str, Any] = {}
        self._scaled_cache: dict[tuple[str, int], tuple[bool, str | None]] = {}
        self._coalesce_until: dict[str, float] = {}
        # T-1245: per-appearance-event last-emit stamps for the one-cue-per-
        # appearance dedupe (see play_appearance).
        self._appearance_last_emit: dict[str, float] = {}
        self._dur_cache: dict[str, float] = {}
        self._data_id: int = id(self._data)
        # PERF-005: prune leftover scaled-WAV temp files from previous sessions
        # at startup, before any playback could be using them.
        _prune_scaled_cache_dir()
        # T-1238-G: the AudioHub is the one audio authority behind this
        # facade.  Named-event play() keeps the T-1228/SRC-010 policy engine
        # (its semantics are the shipped default), while explicit-mode
        # requests (Overlay/Stack/Replace per event/bus) and STOP ALL enter
        # through the hub so every audible sound shares one provenance and
        # bus model.
        self._hub = AudioHub(transport=_make_hub_transport(),
                             global_mode=self.persisted_global_mode())
        # T-1244: the persisted master-mute state is authoritative from the
        # moment the manager exists -- "Settings never opened" must mute.
        self._hub.set_muted(
            self._data.get("audio_global_muted", "False") == "True")
        # C0.6/C0.7: ordinary events converge on the hub whenever a real
        # mixing backend exists.  With the degraded backend there is nothing
        # to mix, so the proven T-1221/T-1228 single-transport policy engine
        # stays in charge instead of pretending Overlay/Stack/Replace work.
        self._hub_routing_enabled = True
        self._hub_degraded = False
        # PERF-003 (SRC-021): the persisted render/edge-pad policy is applied
        # BEFORE anything schedules renderer prewarm.  The old order called
        # prewarm_device_cache() first, which synchronously resolved NumPy on
        # the GUI thread for a job GUARANTEED to no-op (the renderer starts
        # disabled), and the same six Problip WAVs were then scheduled again by
        # the hot-set preload below -- two overlapping startup owners, one
        # pointless NumPy import, one pointless render sweep.
        self.apply_device_render_setting()
        # T-1242 spec 5: warm the CONFIGURED hot set (enabled events + the
        # timer/notification sounds) once the event loop is running, so
        # opening Sound Settings is never the first decode of a common WAV.
        # PERF-003: this is the ONE renderer-prewarm owner; it resolves NumPy
        # and renders only when the policy applied above enabled rendering,
        # while the transport attach still warms sources either way.
        QTimer.singleShot(0, self._preload_hot_set_safely)

    def _preload_hot_set_safely(self) -> None:
        if self._closed:
            return
        try:
            self.preload_hot_set()
        except Exception:
            logger.debug("hot-set preload failed", exc_info=True)

    # -- Audio hub facade (T-1238-G) ---------------------------------------

    def persisted_global_mode(self) -> str:
        """The profile's stored global playback mode (Overlay by default)."""
        from fastprompter.core.sound_presets import profile_global_mode

        return profile_global_mode(self._data)

    def set_playback_mode(self, mode, *, persist: bool = False) -> None:
        """Set the global user playback mode (Overlay/Stack/Replace)."""
        self._hub.set_global_mode(mode)
        if persist:
            from fastprompter.core.sound_presets import GLOBAL_MODE_KEY

            self._data[GLOBAL_MODE_KEY] = str(self._hub.global_mode)

    def reload_playback_mode(self) -> None:
        """Re-read the persisted global mode (profile switch, preset apply)."""
        self._hub.set_global_mode(self.persisted_global_mode())
        # T-1244: the master mute is ALSO profile state.  After a switch the
        # hub must follow the new active profile immediately -- including a
        # stale mute from the previous profile being released (never left
        # muted) and a muted profile taking effect without opening Settings.
        self._hub.set_muted(
            self._data.get("audio_global_muted", "False") == "True")

    def event_mode(self, event: str) -> str:
        """The per-event playback override, or ``inherit``."""
        events = self._data.get("sound_events")
        if isinstance(events, dict) and isinstance(events.get(event), dict):
            raw = str(events[event].get("mode") or "inherit").strip().lower()
            if raw in ("inherit", "mix", "queue", "replace", "skip_busy"):
                return raw
        return "inherit"

    def hub_routing_active(self) -> bool:
        """True when ordinary events really enter the AudioHub."""
        return bool(self._hub_routing_enabled and self._hub.capability_mixing)

    def backend_status(self) -> dict:
        """Truthful backend report for the Playback settings page."""
        diagnostics = self._hub.diagnostics()
        diagnostics["routing"] = (
            "legacy" if getattr(self, "_hub_degraded", False)
            else ("hub" if self.hub_routing_active() else "legacy")
        )
        diagnostics["backend"] = type(self._hub.transport).__name__
        diagnostics["degraded"] = bool(getattr(self, "_hub_degraded", False))
        return diagnostics

    def audio_hub(self) -> AudioHub:
        """The single audio authority (buses, sequences, ambience entry)."""
        return self._hub

    def _legacy_silence_now(self) -> None:
        """Synchronously retire the legacy winsound owner and mailbox."""
        try:
            if self._current is not None:
                self._record(self._current, "CANCELLED")
                self._current = None
            self._poll_timer.stop()
            while self._pending:
                self._record(self._pending.popleft(), "CANCELLED")
        except Exception:
            pass
        for player in (self._players.get("__ui__"),
                       getattr(self, "_short_player", None)):
            if player is not None and hasattr(player, "stop"):
                try:
                    player.stop()
                except RuntimeError:
                    pass
        if self._worker is not None:
            self._worker.drop_pending()
        _silence_winsound(self._trace_transport)

    # -- T-1244 master mute ---------------------------------------------------

    def master_muted(self) -> bool:
        """True while the global master mute is engaged."""
        return self._hub.is_muted()

    def set_master_muted(self, muted: bool) -> None:
        """Engage/release the T-1244 global master mute (ONE canonical API).

        Order matters: the hub state is flipped FIRST, so any request that
        arrives mid-toggle is already gated, and only then is the legacy
        single-transport ownership silenced (mirrors stop_all_sound, but
        WITHOUT re-stopping the hub when unmuting).
        """
        muted = bool(muted)
        self._hub.set_muted(muted)
        if not muted:
            return
        # Degraded/legacy transport path: hub_routing may be inactive (no
        # mixing backend), so the request engine below is authoritative and
        # needs its own immediate silence. Mirrors stop_all_sound() exactly.
        self._legacy_silence_now()
        self._trace_transport("MASTER_MUTE", None, "on" if muted else "off")

    def transport_policy_generation(self) -> int:
        """The transport's current render-policy generation (T-1242 spec 13).

        Problip pins this at START so ordinary scheduled cues can never flip
        physical representations mid-session.  -1 when the transport has no
        such concept.
        """
        generation = getattr(self._hub.transport, "render_policy_generation",
                             None)
        return generation() if callable(generation) else -1

    def add_stop_all_listener(self, callback) -> None:
        """Register something that must also fall silent on STOP ALL SOUND.

        The hub silences ambience LAYERS, but the ambience runtime owns timers
        that would simply start them again on the next evaluation tick. Core
        must not import the UI, so the runtime registers a plain callable here
        instead. Listeners are advisory: one that raises is logged and skipped,
        never allowed to break emergency silence.
        """
        if not callable(callback):
            return
        listeners = getattr(self, "_stop_all_listeners", None)
        if listeners is None:
            listeners = self._stop_all_listeners = []
        if callback not in listeners:
            listeners.append(callback)

    def _fire_stop_all_listeners(self) -> None:
        for callback in list(getattr(self, "_stop_all_listeners", ()) or ()):
            try:
                callback()
            except Exception:
                from fastprompter.core.logging import logger as _log
                _log.debug("STOP ALL listener failed", exc_info=True)

    def stop_all_sound(self) -> None:
        """STOP ALL SOUND -- the emergency silence command.

        Stops every transient channel, clears every queue, cancels voice
        sequences and ambience layers, and invalidates stale callbacks.
        Future sounds remain allowed; settings are untouched -- including the
        user's remembered ambience preference, which this must never rewrite.
        """
        self._hub.stop_all()
        self._fire_stop_all_listeners()
        # The legacy policy engine's single transport must also fall silent.
        self._legacy_silence_now()
        self._trace_transport("STOP_ALL", None, "stop_all_sound")

    # -- hot-set preloading (T-1242 spec 5) ---------------------------------

    def hot_sound_paths(self) -> list[str]:
        """Absolute WAVs worth warming: enabled events + configured extras.

        Deliberately NOT the whole vault: preloading hundreds of imported
        clips would allocate hundreds of QSoundEffects for sounds nobody has
        selected.
        """
        paths: list[str] = []
        seen: set[str] = set()

        def _add(candidate: str) -> None:
            if not candidate:
                return
            full = os.path.abspath(candidate)
            if full in seen or not os.path.isfile(full):
                return
            seen.add(full)
            paths.append(full)

        events = self._data.get("sound_events")
        if isinstance(events, dict):
            for event, cfg in events.items():
                if not isinstance(cfg, dict):
                    continue
                if str(cfg.get("enabled", "True")).lower() != "true":
                    continue
                name = cfg.get("file") or _DEFAULT_SOUND_MAP.get(event, "")
                if not name:
                    continue
                resolved = sound_library.resolve_sound_ref(
                    name, builtin_root=self._sounds_dir)
                # A stored ref resolves through the resolver ONLY: the old
                # packaged-root join fallback is dead weight for every bare
                # ref and bogus for namespaced ones.
                if resolved:
                    _add(resolved)
        for key in ("timer_sound", "notification_sound", "alarm_sound"):
            ref = self._data.get(key)
            if isinstance(ref, str) and ref:
                _add(self.resolve_ref_path(ref))
        # The six Problip blips and every configured ambience bed: these are
        # the cues a user hears most, and a cold first play goes through Qt's
        # Loading state on the audio thread.
        problip_dir = os.path.join(self._sounds_dir, "problip")
        if os.path.isdir(problip_dir):
            for name in sorted(os.listdir(problip_dir)):
                if name.lower().endswith(".wav"):
                    _add(os.path.join(problip_dir, name))
        try:
            from fastprompter.core.ambience_store import AmbienceStore

            for rule in AmbienceStore().load_rules():
                if getattr(rule, "enabled", False):
                    _add(self.resolve_ref_path(rule.sound_ref))
        except Exception:
            logger.debug("ambience hot-set skipped", exc_info=True)
        return paths

    def preload_hot_set(self, paths=None) -> list[str]:
        """Render + attach the hot set without blocking the GUI thread.

        Rendering happens on a daemon worker; the transport attachment is
        marshalled back through ``_preload_ready`` so the first Preview is
        never the moment a common WAV starts decoding.
        """
        from fastprompter.core.audio_render import (
            device_ready_wav,
            ensure_numpy,
            render_enabled,
        )

        items = list(paths) if paths is not None else self.hot_sound_paths()
        if not items:
            return []
        # PERF-003: renderer prewarm exists only for a render that can
        # actually happen.  With rendering disabled (the shipped default) the
        # render half is a guaranteed no-op, so NumPy is neither resolved nor
        # probed; the transport attach below still warms the sources.
        rendering = render_enabled()
        if rendering:
            # Resolve numpy HERE, on the GUI thread: the worker must not
            # import it, and without it the pure-Python resampler holds the
            # GIL long enough to freeze the window.
            ensure_numpy()
        if not getattr(self, "_preload_connected", False):
            self._preload_ready.connect(self._attach_preloaded)
            self._preload_connected = True

        def _work() -> None:
            if rendering:
                for item in items:
                    try:
                        device_ready_wav(item)      # publish the cached render
                    except Exception:
                        logger.debug("preload render failed for %s", item,
                                     exc_info=True)
                    time.sleep(0.005)      # keep the GUI thread responsive
            # Hand back the ORIGINAL paths: the transport pools by the path
            # it is PLAYED with and resolves the rendered file itself, so
            # preloading the rendered name warmed a pool nothing ever used.
            ready = list(items)
            try:
                self._preload_ready.emit(ready)
            except RuntimeError:
                pass                       # manager torn down mid-preload
        threading.Thread(target=_work, name="FastPrompter audio preload",
                         daemon=True).start()
        return items

    def _attach_preloaded(self, paths) -> None:
        """GUI-thread half of preload_hot_set: warm the transport's pool."""
        if self._closed:
            return
        hub = getattr(self, "_hub", None)
        if hub is None:
            return
        try:
            hub.preload(paths)
        except Exception:
            logger.debug("transport preload failed", exc_info=True)

    #: Profile keys for the two audio-rendering A/B switches (BOTH
    #: experimental, default OFF -- T-1242 spec 8/9: the first playback was
    #: reported correct, so raw playback is the control path until an A/B
    #: matrix proves the renderer improves repeated short-cue playback).
    DEVICE_RENDER_KEY = "audio_device_render"
    EDGE_PAD_KEY = "audio_edge_pad"
    #: One-shot policy marker (spec 8): profiles created while the
    #: experimental defaults were ON get migrated to OFF exactly once; an
    #: explicit choice made AFTER the marker exists is never touched.
    RENDER_POLICY_MARKER_KEY = "audio_render_policy_migrated_v2"

    @classmethod
    def migrate_experimental_render_policy(cls, data: dict) -> bool:
        """One-shot migration of the old experimental defaults to OFF.

        Old profiles carry neither of the two keys (they predate the
        switches) or carry "True" baked by the old default.  Such a profile
        was never an explicit user choice, so it is reset to the new default
        once; the marker prevents ever overriding a real user decision made
        afterwards.  Returns True when a migration was applied.
        """
        if str(data.get(cls.RENDER_POLICY_MARKER_KEY, "")) == "True":
            return False
        changed = False
        for key in (cls.DEVICE_RENDER_KEY, cls.EDGE_PAD_KEY):
            value = data.get(key)
            # "True" was the old experimental default (never a user choice
            # when the marker is absent); absent means pre-switch profile.
            if value in (None, "True"):
                data[key] = "False"
                changed = True
        data[cls.RENDER_POLICY_MARKER_KEY] = "True"
        return changed

    def apply_device_render_setting(self) -> tuple[bool, bool]:
        """Push both rendering switches into the renderer.

        T-1242 spec B5/B8: the RENDERER defines the contract ``pad`` is a
        sub-mode of ``render`` (edge padding only applies when the file is
        rendered).  A persisted ``pad=True`` with render OFF is clamped to
        pad OFF here -- the one authoritative truth -- instead of leaving a
        checkbox that is checked, disabled and unclickable, i.e. the user
        report "cannot be turned OFF".  The persisted value is also written
        back so the UI and the profile agree after a restart.
        """
        from fastprompter.core.audio_render import (
            set_edge_pad_enabled,
            set_render_enabled,
        )

        enabled = str(self._data.get(self.DEVICE_RENDER_KEY, "False")) == "True"
        padded = str(self._data.get(self.EDGE_PAD_KEY, "False")) == "True"
        if padded and not enabled:
            # Spec B5: an explicit OFF must remain OFF, and a stray pad=True
            # without render must not survive as a permanently-on checkbox.
            padded = False
            self._data[self.EDGE_PAD_KEY] = "False"
        previous = (render_enabled_state(), edge_pad_enabled_state())
        set_render_enabled(enabled)
        set_edge_pad_enabled(padded)
        if (enabled, padded) != previous:
            # T-1242 spec 5: a policy change invalidates the transport's
            # pooled physical sources; the next playback re-resolves.
            self.invalidate_cache()
        return enabled, padded

    def invalidate_cache(self) -> None:
        """PERF-004: drop cached resolution when the sound configuration
        changes (mapping, volume, or a replaced profile data dict). The next
        play()/preview rebuilds it lazily.

        T-1242 spec 5: this is ALSO the one canonical source invalidation --
        already-created QSoundEffect pool entries are retired so a UI toggle
        can never leave the transport playing a representation the UI just
        turned off.  Playing channels are stopped only as a side effect of
        retiring their pooled effects; there is no Replace masking.
        """
        self._file_cache.clear()
        self._file_sig.clear()
        self._scaled_cache.clear()
        # PERF-001: same canonical invalidation for the diagnostic metadata --
        # a policy/volume/mapping change must not leave stale duration/format
        # or rendered-provenance facts behind.
        _diag_cache_clear()
        self._data_id = id(self._data)
        while self._pending:
            self._record(self._pending.popleft(), "CANCELLED")
        try:
            self._hub.invalidate_sources()
        except Exception:
            logger.debug("hub source invalidation failed", exc_info=True)

    def _request_coalesce_window(self, request) -> float:
        """How long after this request an identical COALESCE_HIGH_RATE
        request is folded into it (SRC-010). One duration window per WAV,
        so a typewriter burst plays once per file length — never a queue."""
        path = request["path"]
        cached = self._dur_cache.get(path)
        if cached is None:
            ms = _wav_duration_ms(path)
            cached = (ms / 1000.0) if ms else 0.12
            self._dur_cache[path] = cached
        return cached

    def _file_resolution_sig(self, name: str) -> Any:
        """Cheap (no-stat) signature of the bits that affect file resolution
        for ``name``: the user-mapped file name. Defaults are static."""
        events = self._data.get("sound_events")
        if isinstance(events, dict) and isinstance(events.get(name), dict):
            return events[name].get("file")
        return None

    def resolve_ref_path(self, ref: str) -> str:
        """Absolute WAV for a library ref/name, or "" when it resolves to none.

        The one place that turns "computalk1.wav" / "user:imported/x.wav"
        into something a transport can actually open.  Handing a transport a
        bare NAME is how ambience ended up silent: os.path.isfile() answered
        False and the layer never started (T-1242).

        Runtime paths (not persisted profile data) may be absolute and are
        honored; a persisted ref NEVER passes the absolute branch -- callers
        that feed this from the profile go through sound_library containment
        first, and normalize/contained_path reject absolute tokens there.
        """
        if not ref:
            return ""
        if os.path.isabs(ref) and os.path.isfile(ref):
            return ref
        resolved = sound_library.resolve_sound_ref(
            ref, builtin_root=self._sounds_dir)
        return resolved or ""

    def ref_resolves(self, ref: str) -> bool:
        """Does this stored reference actually resolve to a playable file?

        A ref living in the private ``_vault/`` namespace (or the managed
        user library) resolves and plays even though it is deliberately not
        listed in the everyday picker -- so the picker must not label it
        missing.
        """
        if not ref:
            return False
        return sound_library.resolve_sound_ref(
            ref, builtin_root=self._sounds_dir) is not None

    def get_vault_sounds(self) -> list[str]:
        """The private ``_vault/`` namespace, listed only on request."""
        return discover_vault_files(self._sounds_dir)

    def get_available_sounds(self) -> list[str]:
        """Get list of available sound files, sorting favorites and defaults to top."""
        favs = set(self._data.get("sound_favorites", []))
        defaults = ["newday.wav", "newweek.wav", "newmonth.wav"]
        # The default trio must lead regardless of the letter case a checkout
        # carries on disk (Windows case-insensitive checkouts can hold either
        # casing depending on checkout order; T-1012 case-renamed the tracked
        # files while stored/picked refs kept legacy casing).
        defaults_l = {d.lower() for d in defaults}

        def sort_key(name):
            is_fav = name in favs
            def_idx = (
                defaults.index(name.lower())
                if name.lower() in defaults_l
                else 999
            )
            return (not is_fav, def_idx, name)

        return sorted(self._available_sounds, key=sort_key)

    def play(self, name: str, *, source=None, policy=None, dedupe_key=None) -> None:
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
            # C0.12: one canonical resolver -- packaged ``builtin:`` refs and
            # managed ``user:`` refs both play; arbitrary absolute paths never
            # become playable from persisted profile data.
            path = sound_library.resolve_sound_ref(
                file_name, builtin_root=self._sounds_dir) or "" if file_name else ""
            path_exists = bool(path)
            self._file_cache[name] = (file_name, path, path_exists)
            self._file_sig[name] = sig
        if not file_name:
            logger.debug("No sound file found for event: %s", name)
            return

        volume = get_event_volume(name, self._data)

        if path_exists:
            resolved_policy = policy or (
                "COALESCE_HIGH_RATE" if name in (
                    "type", "backspace", "delete_forward", "delete_selection",
                    "hover", "scroll")
                else "EXCLUSIVE_LONG" if name in ("timer", "notify", "error") else "STACK_SHORT")
            return self._request(name, path, volume, resolved_policy, source,
                                 dedupe_key=dedupe_key)

    def play_to_completion(self, name: str, max_wait_ms: int = 15000) -> bool:
        """Play one UI event and keep Qt alive until its WAV has finished.

        Normal UI sounds must stay asynchronous.  Process-exit sound is the
        exception: once QApplication quits, both QSoundEffect and winsound are
        torn down, so the tail is otherwise cut off.  A short nested event loop
        keeps audio and painting responsive, with a hard bound for malformed
        or unexpectedly long custom files.
        """
        if not is_event_enabled(name, self._data):
            return False
        # The exit sound is the one blocking case: it needs the legacy
        # transport's completion token to keep Qt alive until the tail ends.
        if not self._play_legacy(name):
            return False
        token = self._request_seq
        loop = QEventLoop()
        check = QTimer(self)
        check.setInterval(15)
        def poll():
            self._poll_transport()
            if any(t == token for t, _ in self._finished):
                loop.quit()
        check.timeout.connect(poll)
        check.start()
        QTimer.singleShot(max(1, int(max_wait_ms)), loop.quit)
        loop.exec()
        check.stop()
        check.deleteLater()
        return any(t == token and ok for t, ok in self._finished)

    def _play_legacy(self, name: str) -> bool:
        """play() forced onto the legacy single transport (exit sound only)."""
        if not is_event_enabled(name, self._data):
            return False
        file_name = get_sound_file_for_event(name, self._data, self._sounds_dir)
        path = sound_library.resolve_sound_ref(
            file_name, builtin_root=self._sounds_dir) if file_name else None
        if not path:
            return False
        return bool(self._request(name, path, get_event_volume(name, self._data),
                                  "EXCLUSIVE_LONG", force_legacy=True))

    def play_file(self, file_name: str, level: float | int | None = None) -> bool:
        """Play one stored sound reference, ignoring every toggle.

        The settings panel needs this: a preview has to be audible while UI
        sounds are switched off, and it must not route through play(), whose
        whole job is to obey the toggles.
        """
        if not file_name:
            return False
        # The argument is a sound-library REFERENCE (``user:imported/x.wav``,
        # ``builtin:...``, legacy bare) -- never an arbitrary raw path.  Resolve
        # it through the one canonical resolver; os.path.join here made managed
        # user sounds unpreviewable and let absolute tokens through unchecked.
        path = sound_library.resolve_sound_ref(
            file_name, builtin_root=self._sounds_dir)
        if not path:
            return False
        # T-1242 spec 8: the caller needs the TRUTH about the physical start,
        # not "a request object was created".
        return self._emit_file(path, level, slot="__preview__")

    def _emit_file(self, path: str, level: float | int | None = None,
                   *, slot: str = "__alarm__", event=None, source=None,
                   dedupe_key=None) -> bool:
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
        policy = "PREVIEW" if slot == "__preview__" else "EXCLUSIVE_LONG"
        return self._request(event or slot, path, vol, policy, source,
                             dedupe_key=dedupe_key)

    @staticmethod
    def _resolve_library_path(rel: str, sounds_dir: str) -> str | None:
        """Resolve a ``file:`` timer ref to a sound-library path, or None.

        A timer's stored JSON must never turn the sound library into an
        arbitrary-file player: reject parent traversal (``../``), absolute
        paths, drive-qualified paths and UNC escapes. Only ``.wav`` files
        inside ``sounds_dir`` are accepted.
        """
        return sound_library.resolve_sound_ref(rel, builtin_root=sounds_dir)

    def play_sound_ref(self, ref: str, level: float | int, *, preview=False,
                       dedupe_key=None) -> bool:
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
            return self._emit_file(path, level, event=ref,
                                   slot="__preview__" if preview else "__alarm__",
                                   dedupe_key=dedupe_key)
        file_name = get_sound_file_for_event(ref, self._data, self._sounds_dir)
        if not file_name:
            return False
        # The named-event resolution must obey the SAME library containment
        # rule as ``file:`` refs: a stored user mapping such as "../outside.wav"
        # would otherwise turn the sound library into an arbitrary-file player.
        path = self._resolve_library_path(file_name, self._sounds_dir)
        if path is None:
            return False
        return self._emit_file(path, level, event=ref,
                                slot="__preview__" if preview else "__alarm__",
                                dedupe_key=dedupe_key)

    def preview_sound_ref(self, ref, level):
        return self.play_sound_ref(ref, level, preview=True)

    def request_count(self) -> int:
        """Monotonic count of playback requests seen (played, coalesced,
        replaced or dropped).

        The button-sound filter arms a default click with this number and
        drops it when the click's own handler already produced a sound
        (T-1225): any request bumps the counter, so even a COALESCED action
        sound suppresses the default.
        """
        hub_count = self._hub.request_count() if getattr(self, "_hub", None) is not None else 0
        return self._request_seq + hub_count

    def play_click(self) -> None:
        """Convenience method for click sounds."""
        self.play("click")

    def play_project(self) -> None:
        """Convenience method for project switch/click sounds."""
        self.play("project")

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

    def _record(self, request, outcome):
        """One bounded provenance entry, enriched with the audio truth.

        T-1242 spec 34: the entry says what the global master was, what the
        event's relative gain was, what effective amplitude that produced,
        which file was actually handed to the transport and in what format.
        No user text ever enters here.
        """
        entry = dict(request, outcome=outcome,
                     monotonic=time.monotonic(), wall=time.time())
        try:
            entry["effective_global_volume"] = round(
                global_volume(self._data), 4)
            event = request.get("event") or ""
            if event and not str(event).startswith("__"):
                entry["event_gain_db"] = round(
                    get_event_gain_db(event, self._data), 1)
            volume = request.get("volume")
            if volume is not None:
                entry["effective_volume"] = round(float(volume), 4)
            path = request.get("path") or ""
            if path:
                # PERF-001: ONE stat per request feeds both cached lookups.
                signature = _file_signature(path)
                entry["source_wav"] = _wav_format_summary(path, signature)
                rendered = _rendered_path_for(path, signature)
                if rendered:
                    entry["rendered_path"] = os.path.basename(rendered)
                    entry["rendered_wav"] = _wav_format_summary(rendered)
        except Exception:            # diagnostics must never break playback
            logger.debug("diagnostic enrichment failed", exc_info=True)
        self._provenance.append(entry)

    def diagnostic_log(self):
        """Bounded, copy-only provenance for troubleshooting; no per-key disk I/O."""
        return [dict(entry) for entry in self._provenance]

    def _trace_transport(self, operation, request=None, reason=None):
        """Append one bounded transport-trace entry (T-1228).

        Memory only, never disk: the logical ``diagnostic_log`` says what was
        requested; this says what the TRANSPORT did (replace/start/stop) so a
        stray sound can be attributed to a caller bug, an OS notification, or
        a stop-before-start transient.
        """
        self._transport_trace.append({
            "monotonic": time.monotonic(),
            "wall": time.time(),
            "operation": operation,
            "id": request.get("id") if request else None,
            "event": request.get("event") if request else None,
            "path": request.get("path") if request else None,
            "reason": reason,
        })

    def transport_diagnostic_log(self):
        """Copy-only bounded transport trace for stray-audio attribution."""
        return [dict(entry) for entry in self._transport_trace]

    def play_mute_cue(self, event: str) -> bool:
        """Play exactly ONE mute ON/OFF confirmation cue (T-1244 escape hatch).

        This is the ONLY route that may sound while the master mute is
        engaged: it is limited to ``audio_mute_on`` / ``audio_mute_off`` by
        name and never reachable from the ordinary play()/preview/ref APIs.
        Uses the hub's ``allow_while_muted`` request flag on the normal
        backend, and the legacy engine's own escape flag on degraded builds.
        """
        if event not in _MUTE_CUE_EVENTS:
            return False
        # Respect the row's own Sound Settings enabled checkbox (the cue is
        # an ordinary remappable event row) but NEVER the master mute or the
        # sound_ui toggle: the confirmation must survive both.
        cfg = self._data.get("sound_events", {}).get(event)
        if isinstance(cfg, dict) and cfg.get("enabled", "True") != "True":
            return False
        file_name = get_sound_file_for_event(event, self._data, self._sounds_dir)
        path = (sound_library.resolve_sound_ref(
            file_name, builtin_root=self._sounds_dir) if file_name else None)
        if not path:
            return False
        return bool(self._request(
            event, path, get_event_volume(event, self._data), "PREVIEW",
            allow_while_muted=True))

    def play_appearance(self, event: str) -> bool:
        """Play ONE semantic appearance cue for a user-visible surface (T-1245).

        The single sanctioned route for ``app_show``, ``settings_show``,
        ``audio_hub_show``, ``dialog_show``, ``panel_show``,
        ``notification_show`` and ``hover_card_show``. Callers report the
        APPEARANCE TRANSITION only:

        * a surface that was hidden/nonexistent becomes visible -> call here;
        * construction, relayout, paint, language reapplication, a hidden
          widget's internal refresh, dialog child-control init, repeated
          delivery of the same show signal, and hover-card geometry changes
          while already visible -> never call here.

        The dedupe window swallows a re-delivered signal for the same event
        (Qt can hand a show to two code paths for one appearance), while a
        genuine hide -> show later falls outside it and emits one new event.
        Everything else is ordinary event machinery: registry remap, per-row
        enable checkbox, gain, playback mode, master mute and STOP ALL all
        apply exactly as for any other event.
        """
        if event not in APPEARANCE_EVENTS:
            return False
        now = time.monotonic()
        last = self._appearance_last_emit.get(event)
        self._appearance_last_emit[event] = now
        if last is not None and (now - last) < APPEARANCE_DEDUPE_S:
            # Same appearance delivered twice: exactly one semantic cue.
            return False
        if not is_event_enabled(event, self._data):
            return False
        if id(self._data) != self._data_id:
            self.invalidate_cache()
        file_name = get_sound_file_for_event(
            event, self._data, self._sounds_dir)
        path = (sound_library.resolve_sound_ref(
            file_name, builtin_root=self._sounds_dir) if file_name else None)
        if not path:
            return False
        volume = get_event_volume(event, self._data)
        if self.hub_routing_active():
            return self._request(
                event, path, volume, "STACK_SHORT",
                force_legacy=bool(self._hub_degraded))
        return bool(self._request(event, path, volume, "STACK_SHORT"))

    def _request(self, event, path, volume, policy, source=None, *,
                 dedupe_key=None, force_legacy=False, allow_while_muted=False):
        if id(self._data) != self._data_id:
            self.invalidate_cache()
        self._request_seq += 1
        parent = self.parent()
        request = dict(id=self._request_seq, event=event, path=path, volume=volume,
                       policy=policy, source=source or _sound_source(),
                       dedupe_key=dedupe_key,
                       profile=self._data_id, silo=getattr(parent, "active_temp_slot", None),
                       requested_at=time.monotonic())
        self._trace_transport("REQUEST", request, policy)
        if self._closed:
            self._record(request, "CANCELLED")
            return False
        # T-1244: the master mute fails closed for EVERY legacy request
        # (preview/alarm/explicit refs included) before any physical start,
        # so the degraded no-mixing-backend build is covered too.  Only the
        # canonical mute-cue route (play_mute_cue) claims the escape hatch.
        if self._hub.is_muted() and not allow_while_muted:
            self._record(request, "DROPPED_MUTED")
            return False
        occupied = ([self._current] if self._current else []) + list(self._pending)
        # COALESCE_HIGH_RATE is evaluated BEFORE any preemption: folding a
        # repeat must never silence the sound that is playing (T-1221 §4 —
        # never stop the device and only then discover it was a duplicate).
        if policy == "COALESCE_HIGH_RATE":
            # Same-file window (transport-independent): a key held down floods
            # requests far faster than one WAV; fold repeats within the file's
            # own duration so the channel is never starved OR queuing.
            until = self._coalesce_until.get(event, 0.0)
            if until and time.monotonic() < until:
                self._record(request, "COALESCED")
                return True
            self._coalesce_until[event] = time.monotonic() + self._request_coalesce_window(request)
        if policy == "EXCLUSIVE_LONG" and any(
                r["policy"] == "EXCLUSIVE_LONG"
                and dedupe_key is not None
                and r.get("dedupe_key") == dedupe_key
                for r in occupied):
            self._record(request, "COALESCED")
            return True
        # SRC-010: an alarm still owning the channel must not delay an
        # action sound. The transport preemption itself happens in
        # _start_request; here only the intent is recorded.
        if policy != "EXCLUSIVE_LONG" and any(r["policy"] == "EXCLUSIVE_LONG" for r in occupied):
            self._record(request, "REPLACED_ALARM")
        # C0.6: with a real mixing backend the request now enters the ONE
        # audio authority, carrying its bus and the effective playback mode.
        # Without one, the proven single-transport policy engine stays.
        if self.hub_routing_active() and not force_legacy:
            return self._start_request_hub(
                request, allow_while_muted=allow_while_muted)
        if force_legacy:
            request["fallback_owner"] = True
            self._hub.set_legacy_fallback_active(True)
        # Nothing ever queues: a new request starts in the moment of its
        # action, replacing whatever owns the transport (T-1221).
        return self._start_request(request, force_winsound=force_legacy)

    def _start_request_hub(
        self, request, allow_while_muted: bool = False,
    ) -> bool:
        """Emit one already-policed request through the AudioHub."""
        if getattr(self, "_hub_degraded", False) and self._current is not None:
            # A legacy long cue still owns the single-transport path.  Keep
            # one owner until it finishes; the next idle request probes rich
            # playback again.
            request["fallback"] = "legacy_active"
            self._hub.set_legacy_fallback_active(True)
            return self._start_request(request, force_winsound=True)
        if getattr(self, "_hub_degraded", False):
            self._hub_degraded = False
            self._hub.set_legacy_fallback_active(False)

        event = request["event"]
        bus = bus_for_event(event)
        mode = self.event_mode(event)
        if bus == "preview":
            mode = "mix" if mode == "inherit" else mode
        result = self._hub.play_result(
            request["path"], event=event, bus=bus,
            mode=None if mode == "inherit" else mode,
            volume=request["volume"],
            allow_while_muted=allow_while_muted)
        outcome = result.outcome
        request["bus"] = bus
        request["mode"] = mode
        request["channel"] = result.channel
        request["transport"] = type(self._hub.transport).__name__
        if outcome in DROPPED_OUTCOMES:
            # T-1242 spec 3/34: carry the transport's own reason into the
            # diagnostic so "I heard nothing" is answerable from one paste.
            for entry in reversed(self._hub.provenance()):
                if entry.get("request_id") == result.request_id:
                    for field in ("reason", "status", "error", "file_exists",
                                  "failure_stage"):
                        if field in entry:
                            request[f"transport_{field}"] = entry[field]
                    break
        self._record(request, outcome.value)
        self._trace_transport("HUB_PLAY", request, f"{bus}/{mode}")
        if outcome is Outcome.STOPPED:
            reason = request.get("transport_reason", "")
            if reason in {
                "OUTPUT_UNAVAILABLE", "SOURCE_ERROR", "SOURCE_NOT_PLAYING",
                "SINK_START_FAILURE", "EFFECT_PLAY_EXCEPTION",
                "BACKEND_EXCEPTION", "POOL_EXHAUSTED",
                "TRANSPORT_UNAVAILABLE",
            }:
                self._hub_degraded = True
                self._hub.set_legacy_fallback_active(True)
                recover = getattr(self._hub, "recover", None)
                if callable(recover):
                    try:
                        recover("rich_backend_failure")
                    except Exception:
                        logger.debug("rich audio recovery failed", exc_info=True)
                request["fallback"] = "legacy"
                request["fallback_from"] = type(self._hub.transport).__name__
                request["fallback_transport"] = "legacy"
                self._trace_transport("DEGRADE", request, reason)
                return self._start_request(request, force_winsound=True)
        if outcome not in DROPPED_OUTCOMES:
            self._hub_degraded = False
            self._hub.set_legacy_fallback_active(False)
        return outcome not in DROPPED_OUTCOMES

    def _preempt_current_transport(self, discard_pending=False, silence=False):
        """Stop the one sound that owns the transport right now (T-1221 §6).

        Cancels the current logical request exactly once and stops the
        active long QSoundEffect player. It never cancels the request that
        FOLLOWS this call, never emits duplicate CANCELLED provenance, and
        never runs on the worker thread: stale completions stay harmless
        through the token check in _complete_request.

        ``discard_pending`` is for SHORT preemption only — shorts never
        enter the mailbox, so a parked long intent would otherwise survive
        the cancel and play later (the old hidden worker.jobs FIFO). A LONG
        replacement must NOT drain here: its own latest-wins submission
        replaces the parked intent, and draining could kill the newest
        request. ``silence`` defaults to False (T-1228): starting the new WAV
        is itself the preemption, so the winsound device is never stopped
        before a replacement. It is kept only for an explicit cancel with no
        replacement.
        """
        current = self._current
        if current is not None:
            self._record(current, "CANCELLED")
        self._current = None
        player = self._players.get("__ui__")
        if player is not None and hasattr(player, "stop"):
            try:
                player.stop()
            except RuntimeError:
                pass
        if self._worker is not None:
            if discard_pending:
                self._worker.drop_pending()
                self._trace_transport("DROP_PENDING", None, "short preemption")
            if silence:
                _silence_winsound(self._trace_transport)

    def _start_request(self, request, force_winsound=False):
        long = request["policy"] == "EXCLUSIVE_LONG"
        # T-1221 §4: the outgoing owner is cancelled BEFORE the new request
        # becomes current, so the CANCELLED provenance can never mark the
        # replacement itself. T-1228: neither a LONG nor a SHORT replacement
        # silences the winsound device -- starting the new WAV IS the
        # preemption, so no stop-before-start transient is ever emitted.
        if long or self._current is not None:
            self._preempt_current_transport(
                discard_pending=not long, silence=False)
        self._current = request
        request["started_at"] = time.monotonic()
        self._qt_seen_playing = False
        self._starting = True
        try:
            if force_winsound or QSoundEffect is None:
                if long:
                    if self._worker is None:
                        self._worker = _SerialWavWorker(
                            self._play_winsound, trace=self._trace_transport)
                        destroyed = getattr(self, "destroyed", None)
                        if destroyed is not None:
                            destroyed.connect(self._worker.close)
                    # T-1228: STARTING THE NEW WAV IS THE PREEMPTION.
                    # SND_ASYNC PlaySound(new.wav) replaces the sounding wave
                    # on the single device, so publish the newest job to the
                    # mailbox and let the worker dispatch it directly. No
                    # caller-side device silence and no poll loop: the worker
                    # drops an obsolete job through its own epoch/mailbox check
                    # (T-1221: no delayed replay), and the device is never
                    # stopped before the replacement starts.
                    self._worker.replace((request["id"], request["path"],
                                          request["volume"], self._scaled_cache,
                                          True))
                    self._trace_transport("REPLACE_WAV", request,
                                          request.get("policy"))
                    self._record(request, "PLAYED")
                    self._poll_timer.start()
                    return True
                # T-1221 §3a packaged path: short feedback dispatches
                # SND_ASYNC right here, on the caller thread, in the moment
                # of the action. It can never sit behind a long SND_SYNC
                # alarm (the alarm was preempted above), and the fresh
                # async call replaces whatever blip is still sounding.
                # First use of a (file, volume) pair does one bounded,
                # cached scale + temp write; every later keystroke answers
                # from self._scaled_cache (PERF-004 kept).
                self._trace_transport("START_WAV", request, "short dispatch")
                ok = self._play_winsound(request["path"], request["volume"],
                                         self._scaled_cache,
                                         sync=False) is not False
                self._record(request, "PLAYED" if ok else "FAILED")
                self._finished.append((request["id"], ok))
                degraded_owner = (
                    request.get("fallback") in {"legacy", "legacy_active"}
                    or request.get("fallback_owner") is True
                )
                if ok and degraded_owner:
                    # The async device call returns before the WAV ends.  Keep
                    # the degraded legacy owner until its real duration so a
                    # rich retry cannot overlap the same physical owner.
                    duration_ms = _wav_duration_ms(request["path"])
                    request["fallback_until"] = time.monotonic() + (
                        duration_ms / 1000.0 if duration_ms else 0.12)
                    self._poll_timer.start()
                else:
                    self._current = None
                return ok
            if long:
                # T-1221 §5 REPLACE: one long notification at a time. The
                # previous long player was stopped by the preemption above,
                # so distinct alarms never chorus and none ever queues.
                player = self._players["__ui__"] = QSoundEffect(self)
                signal = getattr(player, "playingChanged", None)
                if signal is not None:
                    signal.connect(self._qt_playing_changed)
                player.setVolume(max(0.0, min(1.0, float(request["volume"]))))
                player.setSource(QUrl.fromLocalFile(
                    device_ready_wav(request["path"]) or request["path"]))
                self._trace_transport("REPLACE_WAV", request, "long player")
                player.play()
            else:
                # New short-sound path: always a FRESH player per request.
                # The old single shared "__ui__" player made a second request
                # either queue behind the first (QSoundEffect cannot overlap
                # on one instance) or restart it — both wrong for SRC-010.
                # A per-request player lets concurrent requests overlap, and
                # the previous short player is stopped so the same burst does
                # not leave an older tail running under the newest sound.
                prev = self._short_player
                if prev is not None and hasattr(prev, "stop"):
                    try:
                        prev.stop()
                    except RuntimeError:
                        pass  # already destroyed by Qt parent teardown
                player = self._short_player = QSoundEffect(self)
                player.setVolume(max(0.0, min(1.0, float(request["volume"]))))
                player.setSource(QUrl.fromLocalFile(
                    device_ready_wav(request["path"]) or request["path"]))
                self._trace_transport("START_WAV", request, "short player")
                player.play()
                # Every short request is "done" the moment it is sent to
                # the device: it replaced (or joins) whatever sounded and
                # occupies no channel the next action must wait for.
                self._record(request, "PLAYED")
                self._finished.append((request["id"], True))
                self._short_player = None
                self._current = None
                self._poll_timer.start()
                return True
            playing = getattr(player, "isPlaying", None)
            self._qt_seen_playing = bool(playing()) if callable(playing) else False
            self._record(request, "PLAYED")
            self._poll_timer.start()
            return True
        except Exception:
            logger.exception("Sound transport failed")
            self._record(request, "FAILED")
            self._current = None
            return False
        finally:
            self._starting = False

    def _qt_playing_changed(self):
        if self._current is None or self._starting:
            return
        player = self._players.get("__ui__")
        playing = getattr(player, "isPlaying", None)
        if not callable(playing):
            return
        if playing():
            self._qt_seen_playing = True
        elif self._qt_seen_playing:
            self._complete_request(self._current["id"])

    def _poll_transport(self):
        if id(self._data) != self._data_id:
            self.invalidate_cache()
        if self._worker is not None:
            while True:
                try:
                    token, success = self._worker.completed.get_nowait()
                except queue.Empty:
                    break
                self._complete_request(token, success)
            if self._current is None:
                return
            # A short degraded fallback can coexist with an already-created
            # long worker.  The worker branch must not hide its duration owner.
            if self._current.get("fallback_until") is None:
                return
        if self._current is not None:
            fallback_until = self._current.get("fallback_until")
            if fallback_until is not None:
                if time.monotonic() < fallback_until:
                    return
                self._complete_request(self._current["id"])
                return
            if self._worker is not None:
                return
            player = self._players.get("__ui__")
            status = getattr(player, "status", None)
            if callable(status) and status() == QSoundEffect.Status.Error:
                self._complete_request(self._current["id"], False)
            else:
                self._qt_playing_changed()
                if (self._current is not None and not self._qt_seen_playing
                        and time.monotonic() - self._current["started_at"] > 5):
                    self._complete_request(self._current["id"], False)

    def _complete_request(self, token, success=True):
        if self._current is None or self._current["id"] != token:
            return  # stale transport completion can never drain a new owner
        if not success:
            self._record(self._current, "FAILED")
        self._finished.append((token, success))
        self._current = None
        self._poll_timer.stop()
        if id(self._data) != self._data_id:
            self.invalidate_cache()
        while self._pending and not self._closed:
            if self._start_request(self._pending.popleft()):
                break

    def shutdown(self):
        """Cancel pending intent and retire the transport worker on app exit."""
        self._closed = True
        while self._pending:
            self._record(self._pending.popleft(), "CANCELLED")
        self._poll_timer.stop()
        if self._worker is not None:
            self._worker.close()
            self._trace_transport("DROP_PENDING", None, "shutdown")
            # SND_SYNC owns a real completion boundary. Cancellation is
            # explicit and used only at exit, never to interleave ordinary
            # requests (T-1228: one of the few legitimate STOP_DEVICE sites).
            if self._worker.thread.is_alive():
                _silence_winsound(self._trace_transport)
                self._worker.thread.join(timeout=1)
        short = getattr(self, "_short_player", None)
        if short is not None and hasattr(short, "stop"):
            try:
                short.stop()
            except RuntimeError:
                pass
        player = self._players.get("__ui__")
        if player is not None and hasattr(player, "stop"):
            player.stop()
        if self._current is not None:
            self._record(self._current, "CANCELLED")
            self._current = None
        # T-1242 P0: the hub transport owns live sinks and pooled effects;
        # after shutdown nothing may keep the authority to make a sound.
        hub = getattr(self, "_hub", None)
        if hub is not None:
            try:
                hub.close()
            except Exception:
                logger.debug("audio hub close failed", exc_info=True)

    @staticmethod
    def _play_winsound(path: str, level: float | int = 1.0,
                       cache: dict | None = None, sync: bool = True) -> None:
        """Fallback WAV playback without QtMultimedia.

        This is the path the SHIPPED build takes — QtMultimedia is not in the
        dist — so it has to honour the Volume setting or the setting is
        decorative. winsound has no volume of its own, so anything below 1.0
        plays a pre-scaled copy of the file instead. Level 0 is silence, and
        is answered by playing nothing rather than by a wav full of zeroes.

        ``sync``: long alarms and the exit sound play SND_SYNC for a real
        completion boundary; short UI feedback plays SND_ASYNC so the next
        request replaces the sounding one at once (SRC-010 immediacy).
        """
        try:
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
                    _winsound_play(scaled, sync)
                    return True
                # previously resolved as missing: respect the cached verdict
                # (a silent no-op) without re-probing the filesystem
                return
            if lv <= 0.0 or not os.path.exists(path):
                _bounded_cache_insert(cache, key, (False, None))
                return
            # EXPERIMENTAL (default OFF): hand the device a file at its OWN
            # sample rate when the user opted into the pre-render A/B.
            # Otherwise the Windows mixer resamples; whether that is audible
            # is undecided (T-1242) and the switch is the experiment.
            base = (device_ready_wav(path)
                    if render_enabled_state() else path) or path
            scaled = scaled_wav_path(base, lv) or base
            _bounded_cache_insert(cache, key, (True, scaled))
            _winsound_play(scaled, sync)
            return True
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
            return False
