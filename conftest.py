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
import shutil
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "src")))

# One temp root per pytest PROCESS, installed at import time so it is in place
# before any test module runs its own mkdtemp.
#
# The scaled-volume sound cache lives at
# `tempfile.gettempdir()/fastprompter_sound/<stem>_v<level>.wav` — a path that
# is identical for every process on the machine — and the sample the tests
# scale is the SHIPPED click_soft.wav, so the file names collide too. Two
# pytest runs over one worktree then read and truncate each other's cache
# entries: measured 51 phantom failures, `test_cached_file_is_per_level` among
# them, from a run that happened to overlap another. Nothing warned; they look
# exactly like real regressions.
#
# Production keeps the shared cache — being reusable across app runs is the
# whole point of it. Only the tests get a private root.
_TEST_TMP_ROOT = tempfile.mkdtemp(prefix=f"fastprompter-tests-{os.getpid()}-")
tempfile.tempdir = _TEST_TMP_ROOT


def pytest_sessionfinish(session, exitstatus):
    shutil.rmtree(_TEST_TMP_ROOT, ignore_errors=True)


# Filled in by `_mute_sound` at session start, from the value it displaces.
# It cannot be captured at import time: importing sound_manager here would
# cache the real PyQt6-backed module before the Qt-less unit tests install
# their sys.modules stubs, which breaks 28 of them.
_REAL_PLAY_WINSOUND = None


@pytest.fixture
def real_play_winsound(_mute_sound):
    """The genuine `_play_winsound`, for tests that assert on what it does.

    Call it directly rather than through `SoundManager`. The session mute
    below replaces the attribute, and the unit tests re-import
    `sound_manager` behind their PyQt6 stubs, so the class a test file bound
    at import time is not reliably the class anything else patches. Handing
    over the function itself sidesteps both. Depending on `_mute_sound` is
    what guarantees the capture below has run.

    Without this the only route to the real function was an earlier test
    happening to restore it, which is how
    `test_play_uses_the_scaled_copy_and_stays_async` behaved: green in a run
    that included tests_smoke/, red running tests/ on its own, and asserting
    nothing either way.
    """
    if _REAL_PLAY_WINSOUND is None:
        pytest.skip("sound_manager unavailable")
    return _REAL_PLAY_WINSOUND


@pytest.fixture(autouse=True, scope="session")
def _mute_sound():
    global _REAL_PLAY_WINSOUND
    played = []
    try:
        from fastprompter.core import sound_manager
    except Exception:          # pragma: no cover - Qt-less unit runs
        yield played
        return

    real_winsound = sound_manager.SoundManager._play_winsound
    _REAL_PLAY_WINSOUND = real_winsound

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
