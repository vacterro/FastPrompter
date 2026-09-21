"""Six-sound catalog used by embedded Problip.

The catalog owns stable product IDs and filenames, but deliberately does not
own playback.  SoundManager remains the only audio transport authority.
"""

from __future__ import annotations

import os
import random
import wave
from dataclasses import dataclass
from typing import Any

from fastprompter.core.problip import DEFAULT_SOUND_ID, SOUND_IDS
from fastprompter.core.sound_library import (
    USER_PREFIX,
    resolve_sound_ref,
)
from fastprompter.utils.paths import get_resource_path

#: Persisted pool-token prefix that pins a built-in explicitly (T-1242).
BUILTIN_ID_PREFIX = "builtin-id:"


@dataclass(frozen=True)
class SoundEntry:
    """A stable Problip sound choice and its bundled WAV filename."""

    sound_id: str
    display_name: str
    filename: str

    @property
    def id(self) -> str:
        """Source-compatible alias for Android's ``SoundEntry.id``."""
        return self.sound_id

    @property
    def name(self) -> str:
        return self.display_name


SOUND_CATALOG: tuple[SoundEntry, ...] = (
    SoundEntry(DEFAULT_SOUND_ID, "Original Blip", "blip01.wav"),
    SoundEntry("sound_glass", "Glass", "blip_glass.wav"),
    SoundEntry("sound_wood", "Wood", "blip_wood.wav"),
    SoundEntry("sound_soft_bell", "Soft Bell", "blip_soft_bell.wav"),
    SoundEntry("sound_bonk", "Bonk", "blip_bonk.wav"),
    SoundEntry("sound_space", "Space", "blip_space.wav"),
)


class SoundCatalog:
    """Stable catalog facade with no Qt or SoundManager dependency."""

    all = SOUND_CATALOG

    @classmethod
    def by_id(cls, sound_id: object) -> SoundEntry | None:
        return next((entry for entry in cls.all if entry.sound_id == sound_id), None)

    @classmethod
    def ids(cls) -> tuple[str, ...]:
        return tuple(entry.sound_id for entry in cls.all)


@dataclass(frozen=True)
class SoundPoolStatus:
    """Truthful resolution result for the currently selected sound pool."""

    selected_ids: tuple[str, ...]
    playable_ids: tuple[str, ...]
    missing_ids: tuple[str, ...] = ()
    invalid_ids: tuple[str, ...] = ()

    @property
    def playable(self) -> bool:
        return bool(self.playable_ids)

    @property
    def warning(self) -> str | None:
        if self.missing_ids:
            return "Some selected Problip sounds are unavailable"
        if self.invalid_ids:
            return "Some selected Problip sounds are unknown"
        return None

    @property
    def error(self) -> str | None:
        if not self.playable_ids:
            return "No selected Problip sound can be played"
        return None


def sound_directory() -> str:
    """Return the bundled Problip sound directory."""
    return get_resource_path("sound", "problip")


def resolve_sound_path(sound_id: object, base_dir: str | os.PathLike[str] | None = None) -> str | None:
    """Resolve a pool token to a contained, existing WAV file.

    Accepts the legacy bare built-in IDs, the explicit ``builtin-id:<id>``
    form and managed-library ``user:<rel>`` refs.  Anything else (including
    absolute paths and traversal) resolves to None -- the pool can never
    become an arbitrary file player.
    """
    token = str(sound_id or "")
    if token.startswith(BUILTIN_ID_PREFIX):
        token = token[len(BUILTIN_ID_PREFIX):]
    if token.startswith(USER_PREFIX):
        path = resolve_sound_ref(token)
        if path and _is_playable_wav(path):
            return path
        return None
    entry = SoundCatalog.by_id(token)
    if entry is None:
        return None
    root = os.path.abspath(os.fspath(base_dir) if base_dir is not None else sound_directory())
    path = os.path.abspath(os.path.join(root, entry.filename))
    if path != root and not path.startswith(root + os.sep):
        return None
    if not os.path.isfile(path) or not _is_playable_wav(path):
        return None
    return path


def _is_playable_wav(path: str) -> bool:
    """Validate enough PCM structure to avoid claiming corrupt audio is ON."""
    try:
        with wave.open(path, "rb") as source:
            if source.getcomptype() != "NONE":
                return False
            if source.getnchannels() < 1 or source.getframerate() <= 0:
                return False
            if source.getsampwidth() not in (1, 2, 4):
                return False
            frame_width = source.getnchannels() * source.getsampwidth()
            if frame_width <= 0 or source.getnframes() <= 0:
                return False
            # Read one frame at the boundary so truncated data is rejected by
            # wave rather than being treated as an existing-but-silent asset.
            source.readframes(1)
            return True
    except (OSError, EOFError, wave.Error):
        return False


def _normalize_selected(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        # The store normally decodes JSON before this boundary; accepting a
        # comma-separated fallback makes this helper safe for direct callers
        # without introducing a second persistence format.
        value = [part.strip() for part in value.split(",") if part.strip()]
    if not isinstance(value, (list, tuple, set, frozenset)):
        value = ()
    result: list[str] = []
    for token in value:
        if not isinstance(token, str) or not token or token in result:
            continue
        if token in SOUND_IDS or token.startswith(BUILTIN_ID_PREFIX) \
                or token.startswith(USER_PREFIX):
            result.append(token)
    return tuple(result)


def inspect_sound_pool(
    selected_ids: Any,
    base_dir: str | os.PathLike[str] | None = None,
) -> SoundPoolStatus:
    """Resolve all selected tokens without silently rewriting user selection.

    Built-ins (bare or ``builtin-id:``) and managed ``user:`` refs are
    validated the same way: a token that cannot resolve to a playable WAV
    stays selected and is reported missing -- never silently replaced by
    Original.  Unknown token shapes are reported invalid.
    """
    if isinstance(selected_ids, str):
        raw_ids = [part.strip() for part in selected_ids.split(",") if part.strip()]
    elif isinstance(selected_ids, (list, tuple, set, frozenset)):
        raw_ids = list(selected_ids)
    else:
        raw_ids = []
    selected = tuple(dict.fromkeys(item for item in raw_ids if isinstance(item, str)))

    def _shape(token: str) -> str:
        if token in SOUND_IDS or token.startswith(BUILTIN_ID_PREFIX):
            return "builtin"
        if token.startswith(USER_PREFIX):
            return "user"
        return "invalid"

    invalid = tuple(t for t in selected if _shape(t) == "invalid")
    known = tuple(t for t in selected if _shape(t) != "invalid")
    playable = tuple(t for t in known if resolve_sound_path(t, base_dir) is not None)
    missing = tuple(t for t in known if t not in playable)
    return SoundPoolStatus(
        selected_ids=selected,
        playable_ids=playable,
        missing_ids=missing,
        invalid_ids=invalid,
    )


def choose_playable_sound(
    playable_ids: Any,
    random_source: object | None = None,
) -> SoundEntry | None:
    """Choose uniformly from the currently playable pool; repeats are allowed.

    The pool may contain built-ins AND managed custom sounds: one selected
    custom file is enough for 'always play my own sound'.  A custom ref has
    no SoundEntry, so it is returned as a lightweight entry carrying its
    persisted token.
    """
    ids = tuple(dict.fromkeys(
        item for item in playable_ids
        if isinstance(item, str)
        and (item in SOUND_IDS or item.startswith(BUILTIN_ID_PREFIX)
             or item.startswith(USER_PREFIX))))
    if not ids:
        return None
    try:
        if random_source is None:
            index = random.randrange(len(ids))
        elif callable(random_source):
            index = int(random_source(len(ids)))
        elif hasattr(random_source, "randrange"):
            index = int(random_source.randrange(len(ids)))
        elif hasattr(random_source, "next_int"):
            index = int(random_source.next_int(0, len(ids) - 1))
        else:
            index = random.randrange(len(ids))
    except (TypeError, ValueError, OverflowError, AttributeError):
        index = random.randrange(len(ids))
    token = ids[index % len(ids)]
    entry = SoundCatalog.by_id(
        token[len(BUILTIN_ID_PREFIX):] if token.startswith(BUILTIN_ID_PREFIX)
        else token)
    if entry is not None:
        return entry
    return SoundEntry(token, token[len(USER_PREFIX):], "")


# Friendly aliases for controller/test callers.
SOUND_ENTRIES = SOUND_CATALOG
get_sound_entry = SoundCatalog.by_id
