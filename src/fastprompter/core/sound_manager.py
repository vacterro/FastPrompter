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

# Map sound names to preferred WAV filenames
_SOUND_FILE_MAP: dict[str, str] = {
    "new": "newbutton1.wav",
    "save": "savebutton1.wav",
    "silo": "button1.wav",
    "snippet": "button2.wav",
    "tick": "tickbox1.wav",
    "delete": "delete1.wav",
    "clear": "clear1.wav",
    "type": "type1.wav",
    "click": "button1.wav",
}

# Used when the preferred file isn't shipped yet — drop the preferred
# .wav into the sound/ folder and it takes over automatically.
_SOUND_FALLBACKS: dict[str, str] = {
    "savebutton1.wav": "tickbox3.wav",
    "clear1.wav": "delete1.wav",
    "type1.wav": "tickbox1.wav",
}


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

    def play(self, name: str) -> None:
        """Play a named sound effect.

        Respects the ``sound_ui`` and ``sound_typewriter`` toggles
        and the ``sound_volume`` setting from the data dict.
        Silently does nothing if the corresponding toggle is off or
        the sound file is missing.
        """
        if name == "type":
            if self._data.get("sound_typewriter", "False") != "True":
                return
        elif self._data.get("sound_ui", "False") != "True":
            return

        file_name: str = _SOUND_FILE_MAP.get(name, f"{name}.wav")
        path: str = os.path.join(self._sounds_dir, file_name)
        if not os.path.exists(path) and file_name in _SOUND_FALLBACKS:
            path = os.path.join(self._sounds_dir, _SOUND_FALLBACKS[file_name])
        if name not in _SOUND_FILE_MAP:
            logger.warning("Unknown sound name: %s", name)

        if QSoundEffect is None:
            self._play_winsound(path, _volume_level(self._data))
            return

        # Only cache players for known sound names to prevent unbounded dict growth
        if name in _SOUND_FILE_MAP:
            if name not in self._players:
                self._players[name] = QSoundEffect(self)
            player = self._players[name]
        else:
            player = QSoundEffect(self)

        try:
            player.setVolume(_volume_factor(self._data))

            if os.path.exists(path):
                player.setSource(QUrl.fromLocalFile(path))
                player.play()
        except Exception:
            logger.exception("Failed to play sound")

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

    def play_click(self) -> None:
        """Shortcut for ``play("click")``."""
        self.play("click")

    def play_tick(self) -> None:
        """Shortcut for ``play("tick")``."""
        self.play("tick")
