"""Share fixtures defined in test_app_smoke.py with the rest of tests_smoke/.

The `win` module-scoped fixture (and the tear-down it relies on) lives in
test_app_smoke.py because that is where the smoke session grew up. Regression
modules that only need a live FastPrompter window should not have to be
collected alongside the 13k-line smoke module to get it, so we re-export it
here. pytest prepends this directory to sys.path before importing the
conftest, so `test_app_smoke` resolves to the same module instance pytest
collects -- no duplicate fixture.
"""

from test_app_smoke import win  # noqa: F401

# Also mute every sound exit at the device level, so running tests from
# tests_smoke/ (or any subdirectory) never plays audio even when the root
# conftest is not loaded.
_FIXTURE_LOADED = False


def _mute_sound_at_device():
    global _FIXTURE_LOADED
    if _FIXTURE_LOADED:
        return
    _FIXTURE_LOADED = True
    try:
        from fastprompter.core import sound_manager as _sm
        from fastprompter.core.sound_manager import SoundManager as _SM

        SoundManager._play_winsound = staticmethod(
            lambda path, level=10: None)

        class _Silent:
            def __init__(self, *a, **k):
                self._volume = 0.0
            def setVolume(self, v):
                self._volume = v
            def setSource(self, src):
                pass
            def play(self):
                pass

        _sm.QSoundEffect = _Silent
    except Exception:
        pass


import pytest


@pytest.fixture(autouse=True, scope="session")
def _smoke_mute_sound():
    _mute_sound_at_device()
    try:
        yield
    finally:
        pass
