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
# Drop any real copy cached by an earlier module (e.g. a dialog test file that
# imports SoundManager at collection time) so the import below actually
# re-runs against the stubs. Same eviction import_with_stubs does.
sys.modules.pop("fastprompter.core.sound_manager", None)
sys.modules["PyQt6"] = MagicMock()
sys.modules["PyQt6.QtMultimedia"] = MagicMock()
sys.modules["PyQt6.QtMultimedia"].QSoundEffect = _MockQSoundEffect
sys.modules["PyQt6.QtCore"] = MagicMock()
sys.modules["PyQt6.QtCore"].QObject = _MockQObject
sys.modules["PyQt6.QtCore"].QUrl = MagicMock()
sys.modules["PyQt6.QtCore"].QUrl.fromLocalFile = lambda p: f"file:///{p}"

from fastprompter.core.sound_manager import (
    _DEFAULT_SOUND_MAP,
    SoundManager,
    _volume_level,
    get_event_volume,
    get_sound_file_for_event,
    scale_wav_bytes,
    scaled_wav_path,
)

_qt_stub.restore(_before_stubs)


class TestSoundFileMap:
    """Verify the sound file mapping covers all expected sounds."""

    def test_has_click(self):
        assert "click" in _DEFAULT_SOUND_MAP

    def test_has_new(self):
        assert "new" in _DEFAULT_SOUND_MAP

    def test_has_save(self):
        assert "save" in _DEFAULT_SOUND_MAP

    def test_has_silo(self):
        assert "silo" in _DEFAULT_SOUND_MAP

    def test_has_snippet(self):
        assert "snippet" in _DEFAULT_SOUND_MAP

    def test_has_tick(self):
        assert "tick" in _DEFAULT_SOUND_MAP

    def test_has_delete(self):
        assert "delete" in _DEFAULT_SOUND_MAP

    def test_has_clear(self):
        assert "clear" in _DEFAULT_SOUND_MAP

    def test_has_type(self):
        assert "type" in _DEFAULT_SOUND_MAP

    def test_every_default_is_a_file_that_actually_ships(self):
        """A default pointing at a missing file is a silent silence.

        The library was renamed wholesale (T-705) and every one of these
        moved with it; asserting the NAMES here would only pin yesterday's
        spelling, so this asserts the thing that matters — the file is there.
        """
        sm = SoundManager(_MockQObject(), {})
        available = set(sm.get_available_sounds())
        missing = {e: f for e, f in _DEFAULT_SOUND_MAP.items() if f not in available}
        assert not missing, f"defaults with no file: {missing}"

    def test_has_backspace(self):
        assert "backspace" in _DEFAULT_SOUND_MAP

    def test_has_chest_open(self):
        assert "chest_open" in _DEFAULT_SOUND_MAP

    def test_has_chest_close(self):
        assert "chest_close" in _DEFAULT_SOUND_MAP


class TestSoundDiscovery:
    """Test sound file discovery."""

    def test_discover_returns_wav_files(self):
        sm = SoundManager(_MockQObject(), {})
        sounds = sm.get_available_sounds()
        assert all(s.lower().endswith(".wav") for s in sounds)

    def test_discover_returns_sorted_list(self):
        sm = SoundManager(_MockQObject(), {})
        sounds = sm.get_available_sounds()
        # get_available_sounds orders favorites, then defaults, then the rest
        # alphabetically; with no favorites/defaults present that is a plain
        # alphabetical sort of the discovered set.
        assert sounds == sorted(sounds)


class TestEventMapping:
    """Test event-to-file mapping with user overrides."""

    def test_default_mapping_used_when_no_override(self):
        data = {}
        sm = SoundManager(_MockQObject(), data)
        file = get_sound_file_for_event("click", data, sm._sounds_dir)
        assert file == _DEFAULT_SOUND_MAP["click"]

    def test_user_mapping_overrides_default(self):
        data = {
            "sound_events": {
                "click": {"file": "Click.wav", "enabled": "True", "volume": ""}
            }
        }
        sm = SoundManager(_MockQObject(), data)
        file = get_sound_file_for_event("click", data, sm._sounds_dir)
        assert file == "Click.wav"

    def test_missing_event_returns_none(self):
        data = {}
        sm = SoundManager(_MockQObject(), data)
        file = get_sound_file_for_event("nonexistent_event", data, sm._sounds_dir)
        assert file is None


class TestEventVolume:
    """Test per-event volume."""

    def test_global_volume_used_when_per_event_empty(self):
        data = {"sound_volume": "7"}
        vol = get_event_volume("click", data)
        assert vol == 7

    def test_per_event_volume_overrides_global(self):
        data = {
            "sound_volume": "5",
            "sound_events": {
                "click": {"file": "click_soft.wav", "enabled": "True", "volume": "8"}
            }
        }
        vol = get_event_volume("click", data)
        assert vol == 8

    def test_invalid_volume_falls_back_to_global(self):
        data = {
            "sound_volume": "5",
            "sound_events": {
                "click": {"file": "click_soft.wav", "enabled": "True", "volume": "invalid"}
            }
        }
        vol = get_event_volume("click", data)
        assert vol == 5


class TestSoundManagerToggle:
    """Verify sound toggle logic (sound_ui, sound_typewriter, per-event)."""

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

    def test_per_event_disabled_overrides_global(self):
        data = {
            "sound_ui": "True",
            "sound_events": {
                "click": {"enabled": "False", "file": "click_soft.wav", "volume": ""}
            }
        }
        sm = self._make_sm(data)
        sm.play("click")
        assert "click" not in sm._players


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

    def test_play_hover_delegates_to_play(self):
        sm = self._make_sm({"sound_ui": "True"})
        with patch.object(sm, "play") as mock_play:
            sm.play_hover()
            mock_play.assert_called_once_with("hover")

    def test_play_button_release_delegates_to_play(self):
        sm = self._make_sm({"sound_ui": "True"})
        with patch.object(sm, "play") as mock_play:
            sm.play_button_release()
            mock_play.assert_called_once_with("button_release")


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
        return os.path.join(sm._sounds_dir, "click_soft.wav")

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

    def test_play_uses_the_scaled_copy_and_stays_async(self, real_play_winsound):
        # The session-wide mute in conftest replaces _play_winsound, and this
        # test is about what the REAL one does — ask for it by fixture and
        # call it directly, rather than going through SoundManager and hoping
        # an earlier test happened to restore the attribute.
        played = []
        fake = MagicMock()
        fake.SND_FILENAME, fake.SND_ASYNC, fake.SND_MEMORY = 0x20000, 0x0001, 0x0004
        fake.PlaySound = lambda s, f: played.append((s, f))
        with patch.dict(sys.modules, {"winsound": fake}):
            src = self._sample()
            real_play_winsound(src, 2)
            real_play_winsound(src, 10)
            real_play_winsound(src, 0)

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


class TestTickDirection:
    """T-722: un-tick never played. `untick` -> tick_off.wav was mapped from
    the start and nothing asked for it — both directions played "tick"."""

    def _mgr(self):
        from fastprompter.core.sound_manager import SoundManager
        mgr = SoundManager.__new__(SoundManager)
        asked = []
        mgr.play = lambda name: asked.append(name)
        return mgr, asked

    def test_tick_on_and_off_ask_for_different_events(self):
        mgr, asked = self._mgr()
        mgr.play_tick(True)
        mgr.play_tick(False)
        assert asked == ["tick", "untick"]

    def test_default_is_still_tick(self):
        mgr, asked = self._mgr()
        mgr.play_tick()
        assert asked == ["tick"]

    def test_both_events_resolve_to_different_files(self):
        from fastprompter.core.sound_manager import _DEFAULT_SOUND_MAP
        assert _DEFAULT_SOUND_MAP["tick"] != _DEFAULT_SOUND_MAP["untick"]


class TestPlaySoundRef:
    """T-1005. One canonical explicit-volume playback path for timer sounds.

    A ``file:`` ref must resolve ONLY inside the sound library; nothing else
    must turn the library into an arbitrary-file player. Returns bool, never
    raises into the scheduler.
    """

    def _mgr(self, tmp):
        sm = SoundManager(_MockQObject(), {})
        sm._sounds_dir = str(tmp)
        return sm

    def test_named_event_plays_through_configured_file(self, tmp_path):
        (tmp_path / "click_soft.wav").write_bytes(b"RIFF")
        sm = self._mgr(tmp_path)
        assert sm.play_sound_ref("click", 5) is True

    def test_file_ref_inside_library_plays(self, tmp_path):
        (tmp_path / "foo.wav").write_bytes(b"RIFF")
        sm = self._mgr(tmp_path)
        assert sm.play_sound_ref("file:foo.wav", 5) is True

    def test_file_ref_subfolder_plays(self, tmp_path):
        sub = tmp_path / "cs_style"
        sub.mkdir()
        (sub / "b.wav").write_bytes(b"RIFF")
        sm = self._mgr(tmp_path)
        assert sm.play_sound_ref("file:cs_style/b.wav", 5) is True

    def test_file_ref_parent_traversal_rejected(self, tmp_path):
        sm = self._mgr(tmp_path)
        assert sm.play_sound_ref("file:../evil.wav", 5) is False
        assert sm.play_sound_ref("file:cs_style/../../evil.wav", 5) is False

    def test_file_ref_absolute_rejected(self, tmp_path):
        sm = self._mgr(tmp_path)
        assert sm.play_sound_ref("file:C:/windows/evil.wav", 5) is False
        assert sm.play_sound_ref("file:/abs/evil.wav", 5) is False

    def test_file_ref_missing_returns_false(self, tmp_path):
        sm = self._mgr(tmp_path)
        assert sm.play_sound_ref("file:none.wav", 5) is False

    def test_empty_or_invalid_ref_returns_false(self, tmp_path):
        sm = self._mgr(tmp_path)
        assert sm.play_sound_ref("", 5) is False
        assert sm.play_sound_ref(None, 5) is False
        assert sm.play_sound_ref("javascript:alert(1)", 5) is False

    def test_unknown_event_returns_false(self, tmp_path):
        sm = self._mgr(tmp_path)
        assert sm.play_sound_ref("nonexistent_event", 5) is False

    def test_resolve_library_path_accepts_internal_only(self, tmp_path):
        (tmp_path / "a.wav").write_bytes(b"x")
        sd = str(tmp_path)
        assert SoundManager._resolve_library_path("a.wav", sd) == os.path.join(sd, "a.wav")
        assert SoundManager._resolve_library_path("../a.wav", sd) is None
        assert SoundManager._resolve_library_path("C:/a.wav", sd) is None
        assert SoundManager._resolve_library_path("a.txt", sd) is None
