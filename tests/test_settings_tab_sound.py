"""The Window/Editor/Clock/Data tabs make a sound when you switch them.

Project tabs and silos have had audible feedback since forever; the settings
tab bar was the one switch in the app that was silent. It gets its OWN event
rather than borrowing `project`, so it stays separately remappable and
separately switchable in the Sound Settings dialog.
"""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from fastprompter.core.sound_manager import _DEFAULT_SOUND_MAP, EVENT_LABELS
from fastprompter.main import FastPrompter


def test_event_is_registered_with_a_shipped_wav():
    assert "settings_tab" in _DEFAULT_SOUND_MAP
    wav = _DEFAULT_SOUND_MAP["settings_tab"]
    sounds = os.path.join(os.path.dirname(__file__), "..", "src", "fastprompter", "sound")
    assert os.path.isfile(os.path.join(sounds, wav)), f"{wav} is not shipped"


def test_event_is_offered_in_the_sound_settings_list():
    assert EVENT_LABELS.get("settings_tab") == "Settings tab switch"


class _Recorder:
    def __init__(self):
        self.played = []

    def play(self, name):
        self.played.append(name)


def _handler(initializing=False):
    """Call the real method against a stand-in, no window build required."""
    stub = type("Stub", (), {})()
    stub._initializing_ui = initializing
    stub.sound_manager = _Recorder()
    stub.play_sound = FastPrompter.play_sound.__get__(stub)
    return stub


def test_switching_a_tab_plays_exactly_one_sound():
    stub = _handler()
    FastPrompter._play_settings_tab_sound(stub, 2)
    assert stub.sound_manager.played == ["settings_tab"]


def test_startup_is_silent():
    """Adding the four pages fires currentChanged before the window is shown."""
    stub = _handler(initializing=True)
    FastPrompter._play_settings_tab_sound(stub, 0)
    assert stub.sound_manager.played == []


def test_a_cleared_tab_bar_is_silent():
    stub = _handler()
    FastPrompter._play_settings_tab_sound(stub, -1)
    assert stub.sound_manager.played == []
