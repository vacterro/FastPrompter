"""Tests for fastprompter.core.sound_manager — SoundManager."""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

from unittest.mock import MagicMock, patch


# Build minimal Qt stubs so SoundManager can be imported without real PyQt6
class _MockQObject:
    """Stand-in for QObject — accepts parent arg, stores it."""

    def __init__(self, parent=None):
        self._parent = parent

    def parent(self):
        return self._parent


class _MockQSoundEffect:
    """Stand-in for QSoundEffect — stores parent only."""

    def __init__(self, parent=None):
        self.parent = parent
        self._source = None
        self._volume = 0.0

    def setSource(self, source):
        self._source = source

    def setVolume(self, vol):
        self._volume = vol

    def play(self):
        pass


# Patch modules before importing SoundManager
sys.modules["PyQt6"] = MagicMock()
sys.modules["PyQt6.QtMultimedia"] = MagicMock()
sys.modules["PyQt6.QtMultimedia"].QSoundEffect = _MockQSoundEffect
sys.modules["PyQt6.QtCore"] = MagicMock()
sys.modules["PyQt6.QtCore"].QObject = _MockQObject
sys.modules["PyQt6.QtCore"].QUrl = MagicMock()
sys.modules["PyQt6.QtCore"].QUrl.fromLocalFile = lambda p: f"file:///{p}"

from fastprompter.core.sound_manager import _SOUND_FILE_MAP, SoundManager


class TestSoundFileMap:
    """Verify the sound file mapping covers all expected sounds."""

    def test_has_click(self):
        assert "click" in _SOUND_FILE_MAP

    def test_has_new(self):
        assert "new" in _SOUND_FILE_MAP

    def test_has_save(self):
        assert "save" in _SOUND_FILE_MAP

    def test_has_silo(self):
        assert "silo" in _SOUND_FILE_MAP

    def test_has_snippet(self):
        assert "snippet" in _SOUND_FILE_MAP

    def test_has_tick(self):
        assert "tick" in _SOUND_FILE_MAP

    def test_has_delete(self):
        assert "delete" in _SOUND_FILE_MAP

    def test_has_clear(self):
        assert "clear" in _SOUND_FILE_MAP

    def test_has_type(self):
        assert "type" in _SOUND_FILE_MAP

    def test_clear_maps_to_clear1(self):
        assert _SOUND_FILE_MAP["clear"] == "clear1.wav"

    def test_delete_maps_to_delete1(self):
        assert _SOUND_FILE_MAP["delete"] == "delete1.wav"

    def test_missing_files_have_fallbacks(self):
        from fastprompter.core.sound_manager import _SOUND_FALLBACKS

        assert _SOUND_FALLBACKS["clear1.wav"] == "delete1.wav"
        assert _SOUND_FALLBACKS["savebutton1.wav"] == "tickbox3.wav"
        assert _SOUND_FALLBACKS["type1.wav"] == "tickbox1.wav"


class TestSoundManagerToggle:
    """Verify sound toggle logic (sound_ui, sound_typewriter)."""

    def _make_sm(self, data=None):
        return SoundManager(_MockQObject(), data or {})

    def test_play_ui_sound_when_toggle_off_does_nothing(self):
        sm = self._make_sm({"sound_ui": "False"})
        sm._players = {}
        # Should not crash or create a player
        sm.play("click")
        assert "click" not in sm._players

    def test_play_ui_sound_when_toggle_on_proceeds(self):
        sm = self._make_sm({"sound_ui": "True"})
        # _players dict is empty, play() will create a new player
        assert "click" not in sm._players

    def test_play_typewriter_sound_when_toggle_off_does_nothing(self):
        sm = self._make_sm({"sound_typewriter": "False"})
        sm.play("type")
        assert "type" not in sm._players

    def test_play_typewriter_sound_when_toggle_on_proceeds(self):
        sm = self._make_sm({"sound_typewriter": "True", "sound_ui": "False"})
        # Toggle on -> should proceed to create player
        assert "type" not in sm._players

    def test_play_ui_sound_defaults_to_off(self):
        sm = self._make_sm({})
        sm.play("snippet")
        assert "snippet" not in sm._players

    def test_play_typewriter_sound_defaults_to_off(self):
        sm = self._make_sm({})
        sm.play("type")
        assert "type" not in sm._players


class TestSoundManagerVolume:
    """Verify volume parsing."""

    def _make_sm(self, data=None):
        return SoundManager(_MockQObject(), data or {})

    def test_default_volume_is_5(self):
        sm = self._make_sm({"sound_ui": "True"})
        assert sm._data.get("sound_volume", "5") == "5"

    def test_custom_volume(self):
        sm = self._make_sm({"sound_ui": "True", "sound_volume": "8"})
        assert sm._data.get("sound_volume") == "8"

    def test_volume_0_is_accepted(self):
        sm = self._make_sm({"sound_ui": "True", "sound_volume": "0"})
        vol = int(sm._data.get("sound_volume", "5"))
        assert vol == 0

    def test_volume_10_is_accepted(self):
        sm = self._make_sm({"sound_ui": "True", "sound_volume": "10"})
        vol = int(sm._data.get("sound_volume", "5"))
        assert vol == 10


class TestSoundManagerShortcuts:
    """Verify play_click() and play_tick() shortcut methods."""

    def _make_sm(self, data=None):
        return SoundManager(_MockQObject(), data or {})

    def test_play_click_delegates_to_play(self):
        sm = self._make_sm({"sound_ui": "True"})
        with patch.object(sm, "play") as mock_play:
            sm.play_click()
            mock_play.assert_called_once_with("click")

    def test_play_tick_delegates_to_play(self):
        sm = self._make_sm({"sound_ui": "True"})
        with patch.object(sm, "play") as mock_play:
            sm.play_tick()
            mock_play.assert_called_once_with("tick")


class TestSoundManagerInit:
    """Verify SoundManager initialization."""

    def test_parent_is_set(self):
        parent = _MockQObject()
        sm = SoundManager(parent, {})
        assert sm.parent() == parent

    def test_players_is_empty_dict(self):
        sm = SoundManager(_MockQObject(), {})
        assert sm._players == {}

    def test_sounds_dir_ends_with_sound(self):
        sm = SoundManager(_MockQObject(), {})
        assert sm._sounds_dir.endswith("sound")

    def test_data_is_stored(self):
        data = {"sound_ui": "True", "sound_volume": "7"}
        sm = SoundManager(_MockQObject(), data)
        assert sm._data is data
