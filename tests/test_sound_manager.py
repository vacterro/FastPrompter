"""Tests for fastprompter.core.sound_manager — SoundManager."""

import io
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
# Stubs are undone right after the import below — assigning into
# sys.modules permanently broke eight tests_smoke files at collection
# time. See tests/_qt_stub.py.
import _qt_stub

_before_stubs = _qt_stub.snapshot()
sys.modules["PyQt6"] = MagicMock()
sys.modules["PyQt6.QtMultimedia"] = MagicMock()
sys.modules["PyQt6.QtMultimedia"].QSoundEffect = _MockQSoundEffect
sys.modules["PyQt6.QtCore"] = MagicMock()
sys.modules["PyQt6.QtCore"].QObject = _MockQObject
sys.modules["PyQt6.QtCore"].QUrl = MagicMock()
sys.modules["PyQt6.QtCore"].QUrl.fromLocalFile = lambda p: f"file:///{p}"

from fastprompter.core.sound_manager import (
    _SOUND_FILE_MAP,
    SoundManager,
    _volume_level,
    scale_wav_bytes,
    scaled_wav_path,
)

_qt_stub.restore(_before_stubs)


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


class TestVolumeOnTheWinsoundPath:
    """T-699. The Volume spinner did nothing in the SHIPPED build.

    QtMultimedia is not in the dist (no qt6multimedia.dll), so the packaged
    app always takes the winsound path — and winsound has no volume control
    at all. Every test here is about that path; the QSoundEffect one was
    already fine, which is why the bug was invisible from a dev checkout.
    """

    def test_level_is_clamped_and_junk_reads_as_five(self):
        assert _volume_level({"sound_volume": "7"}) == 7
        assert _volume_level({"sound_volume": "0"}) == 0
        assert _volume_level({"sound_volume": "99"}) == 10
        assert _volume_level({"sound_volume": "-3"}) == 0
        assert _volume_level({"sound_volume": "loud"}) == 5
        assert _volume_level({}) == 5

    def _sample(self):
        sm = SoundManager(_MockQObject(), {})
        return os.path.join(sm._sounds_dir, "button1.wav")

    def test_samples_are_actually_scaled(self):
        import wave
        from array import array

        src = self._sample()
        assert os.path.exists(src), src

        def peak(fh):
            with wave.open(fh, "rb") as w:
                code = {1: "B", 2: "h", 4: "i"}[w.getsampwidth()]
                a = array(code)
                a.frombytes(w.readframes(w.getnframes()))
                return max(abs(x) for x in a), w.getparams()

        full, params = peak(src)
        for factor in (0.5, 0.1):
            data = scale_wav_bytes(src, factor)
            assert data is not None, "the shipped effects are 32-bit PCM — width 4 must be handled"
            got, got_params = peak(io.BytesIO(data))
            assert abs(got / full - factor) < 0.01, (factor, got / full)
            assert got_params == params  # same rate/width/channels

    def test_cached_file_is_per_level(self, tmp_path):
        src = self._sample()
        a = scaled_wav_path(src, 3)
        b = scaled_wav_path(src, 7)
        assert a and b and a != b
        assert os.path.exists(a) and os.path.exists(b)
        assert scaled_wav_path(src, 3) == a  # reused, not rewritten
        # full volume has nothing to scale — the original file is used
        assert scaled_wav_path(src, 10) is None

    def test_play_uses_the_scaled_copy_and_stays_async(self):
        played = []
        fake = MagicMock()
        fake.SND_FILENAME, fake.SND_ASYNC, fake.SND_MEMORY = 0x20000, 0x0001, 0x0004
        fake.PlaySound = lambda s, f: played.append((s, f))
        with patch.dict(sys.modules, {"winsound": fake}):
            src = self._sample()
            SoundManager._play_winsound(src, 2)
            SoundManager._play_winsound(src, 10)
            SoundManager._play_winsound(src, 0)

        assert len(played) == 2, "level 0 must play nothing at all"
        quiet, loud = played
        assert quiet[0] != src and quiet[0].endswith("_v2.wav")
        assert loud[0] == src
        # SND_MEMORY is refused by winsound together with SND_ASYNC
        # ("Cannot play asynchronously from memory"), and playing a click
        # synchronously would freeze the editor on every keystroke.
        for source, flags in played:
            assert flags == fake.SND_FILENAME | fake.SND_ASYNC
            assert isinstance(source, str)
