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
            self._play_winsound(path)
            return

        # Only cache players for known sound names to prevent unbounded dict growth
        if name in _SOUND_FILE_MAP:
            if name not in self._players:
                self._players[name] = QSoundEffect(self)
            player = self._players[name]
        else:
            player = QSoundEffect(self)

        try:
            vol: int = int(self._data.get("sound_volume", "5"))
            player.setVolume(vol / 10.0)

            if os.path.exists(path):
                player.setSource(QUrl.fromLocalFile(path))
                player.play()
        except Exception:
            logger.exception("Failed to play sound")

    @staticmethod
    def _play_winsound(path: str) -> None:
        """Fallback WAV playback without QtMultimedia (no volume control)."""
        try:
            import winsound

            if os.path.exists(path):
                winsound.PlaySound(path, winsound.SND_FILENAME | winsound.SND_ASYNC)
        except Exception:
            logger.exception("Failed to play sound via winsound")

    def play_click(self) -> None:
        """Shortcut for ``play("click")``."""
        self.play("click")

    def play_tick(self) -> None:
        """Shortcut for ``play("tick")``."""
        self.play("tick")
