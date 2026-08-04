"""Test-wide setup that applies to both tests/ and tests_smoke/.

Silence. The suite builds the real window hundreds of times and every click,
tick and typewriter key it simulates went straight to the speakers — a
cacophony out of nowhere for anyone running the tests, and on the winsound
path each one also writes a scaled copy of the wav to the temp folder.

Muting happens at the two places sound actually LEAVES the app, not at
`play()`: the enable/volume/mapping logic is what several tests assert on,
so it has to keep running exactly as it does in production. Only the final
"make a noise" call is neutered.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "src")))


@pytest.fixture(autouse=True, scope="session")
def _mute_sound():
    played = []
    try:
        from fastprompter.core import sound_manager
    except Exception:          # pragma: no cover - Qt-less unit runs
        yield played
        return

    real_winsound = sound_manager.SoundManager._play_winsound

    def _silent_winsound(path, level=10):
        played.append((path, level))

    sound_manager.SoundManager._play_winsound = staticmethod(_silent_winsound)

    # QSoundEffect is the other exit. Tests that stub PyQt6 never reach it,
    # and the ones that do only need play() not to hit the audio device.
    real_effect = getattr(sound_manager, "QSoundEffect", None)
    if real_effect is not None:
        class _SilentEffect:
            def __init__(self, *a, **k):
                self._volume = 0.0

            def setVolume(self, v):
                self._volume = v

            def setSource(self, src):
                played.append((str(src), self._volume))

            def play(self):
                pass

        sound_manager.QSoundEffect = _SilentEffect

    try:
        yield played
    finally:
        sound_manager.SoundManager._play_winsound = real_winsound
        if real_effect is not None:
            sound_manager.QSoundEffect = real_effect
