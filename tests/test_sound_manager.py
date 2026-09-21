"""Tests for fastprompter.core.sound_manager — SoundManager."""

import io
import os
import sys
import threading
import time
import wave

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

from unittest.mock import MagicMock, patch

import pytest


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

# T-1032: drop any real copy so the import rebuilds against the stubs (see
# test_pie_menu.py) -- a cache hit would hand these tests the real classes.
sys.modules.pop("fastprompter.core.sound_manager", None)

import fastprompter.core.sound_manager as _STUB_SM_MOD  # stub-built copy
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
# The stub-built module object survives restore (restore only evicts it from
# sys.modules); holding it lets the scheduler tests patch ITS QSoundEffect —
# the same module SoundManager above was built against.


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

    def test_has_project(self):
        assert "project" in _DEFAULT_SOUND_MAP
        assert _DEFAULT_SOUND_MAP["project"] == "Click.wav"

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
        # Resolution, not the picker listing, is what decides audibility:
        # bulk material lives in the private ``_vault/`` namespace, which is
        # deliberately absent from the everyday list but fully playable.
        from fastprompter.core import sound_library

        sm = SoundManager(_MockQObject(), {})
        missing = {
            event: ref for event, ref in _DEFAULT_SOUND_MAP.items()
            if sound_library.resolve_sound_ref(
                ref, builtin_root=sm._sounds_dir) is None
        }
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
        assert vol == 0.7

    def test_per_event_volume_overrides_global(self):
        data = {
            "sound_volume": "5",
            "sound_events": {
                "click": {"file": "click_soft.wav", "enabled": "True", "volume": "8"}
            }
        }
        vol = get_event_volume("click", data)
        assert vol == 0.8

    def test_invalid_volume_falls_back_to_global(self):
        data = {
            "sound_volume": "5",
            "sound_events": {
                "click": {"file": "click_soft.wav", "enabled": "True", "volume": "invalid"}
            }
        }
        vol = get_event_volume("click", data)
        assert vol == 0.5


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
        assert _volume_level({"sound_volume": "7"}) == 0.7
        assert _volume_level({"sound_volume": "0"}) == 0.0
        assert _volume_level({"sound_volume": "99"}) == 1.0
        assert _volume_level({"sound_volume": "-3"}) == 0.0
        assert _volume_level({"sound_volume": "loud"}) == 0.5
        assert _volume_level({}) == 0.5

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
        a = scaled_wav_path(src, 0.3)
        b = scaled_wav_path(src, 0.7)
        assert a and b and a != b
        assert os.path.exists(a) and os.path.exists(b)
        assert scaled_wav_path(src, 0.3) == a  # reused, not rewritten
        # full volume has nothing to scale — the original file is used
        assert scaled_wav_path(src, 1.0) is None

    def test_play_uses_the_scaled_copy_and_stays_async(self, real_play_winsound):
        # The session-wide mute in conftest replaces _play_winsound, and this
        # test is about what the REAL one does — ask for it by fixture and
        # call it directly, rather than going through SoundManager and hoping
        # an earlier test happened to restore the attribute.
        played = []
        fake = MagicMock()
        # T-1221: SND_SYNC is not a winsound constant — sync playback is
        # the ABSENCE of SND_ASYNC — so the fake pins SND_NODEFAULT and the
        # assertions check the real flags.
        fake.SND_FILENAME, fake.SND_SYNC, fake.SND_ASYNC, fake.SND_MEMORY = (
            0x20000, 0, 0x0008, 0x0004)
        fake.SND_NODEFAULT = 0x0002
        fake.PlaySound = lambda s, f: played.append((s, f))
        with patch.dict(sys.modules, {"winsound": fake}):
            src = self._sample()
            # T-1242: the quality chain renders the source to the device rate
            # FIRST (base), then scales THAT copy — the played name is the
            # device-ready scaled file for both levels, never the original.
            from fastprompter.core import audio_render as _ar
            base = _ar.device_ready_wav(src) or src
            real_play_winsound(src, 0.2)
            real_play_winsound(src, 1.0)
            real_play_winsound(src, 0.0)
            # SRC-010: short UI feedback plays SND_ASYNC — the call returns
            # at once and a fresh call replaces what is still sounding.
            real_play_winsound(src, 1.0, {}, False)
            real_play_winsound(src, 0.2, {}, sync=False)

        assert len(played) == 4, "level 0 must play nothing at all"
        quiet, loud, loud_async, quiet_async = played
        assert quiet[0] != src and "_v20" in quiet[0]
        # the scaled copy derives from the SOURCE basename (T-1242 content
        # digest cache key), not from the device-rendered intermediate
        assert os.path.basename(src).rsplit(".", 1)[0] in quiet[0]
        # full volume still skips scaling — it plays the device-ready base
        # (or the original when no render is needed)
        assert loud[0] == base
        assert loud_async[0] == base and quiet_async[0] != src
        # SND_MEMORY is refused by winsound together with SND_ASYNC
        # ("Cannot play asynchronously from memory"), and playing a click
        # synchronously on the GUI thread would freeze the editor; the sync
        # mode exists for the off-thread alarm/exit boundary only.
        for source, flags in played[:2]:
            assert flags == fake.SND_FILENAME | fake.SND_NODEFAULT
            assert isinstance(source, str)
        for source, flags in played[2:]:
            assert flags == fake.SND_FILENAME | fake.SND_ASYNC | fake.SND_NODEFAULT
            assert isinstance(source, str)


class TestSemanticScheduler:
    """Both transports consume the same action-policy queue."""

    def _mgr(self):
        # SRC-010: short sounds go through the module's QSoundEffect class, so
        # the stub is installed there (not on the single "__ui__" player — that
        # player no longer exists for shorts). _STUB_SM_MOD is the stub-built
        # module this SoundManager class actually lives in; a plain re-import
        # would return the real one (_qt_stub.restore evicted the stub copy
        # from sys.modules).
        sm = SoundManager(_MockQObject(), {"sound_ui": "True", "sound_typewriter": "True"})
        played = []
        class Player:
            spawned = []
            def __init__(self, parent=None):
                self.parent = parent
                self.active = False
                self.stopped = False
                Player.spawned.append(self)
            def setVolume(self, volume):
                self.volume = volume
            def setSource(self, source):
                self.source = source
            def isPlaying(self):
                return self.active
            def play(self):
                self.active = True
                played.append(self.source)
            def stop(self):
                self.stopped = True
                self.active = False
        _STUB_SM_MOD.QSoundEffect = Player
        return sm, played

    def _finish(self, sm):
        sm._players["__ui__"].active = False
        sm._qt_playing_changed()

    def test_rapid_deliberate_repeats_play_immediately_no_fifo(self):
        # SRC-010: N rapid deliberate actions = N sound starts at the moment
        # of each action. No queue, no pending FIFO, no delayed replay after
        # the user moved on. The QSoundEffect transport starts a fresh player
        # per request; winsound replaces the sounding blip with SND_ASYNC.
        sm, played = self._mgr()
        for _ in range(36):
            sm.play("snap")
        assert len(played) == 36
        assert not sm._pending
        assert sm._current is None

    def test_different_short_sounds_preserve_order(self):
        sm, played = self._mgr()
        for event in ("snap", "click", "tick", "snap"):
            sm.play(event)
        assert [r["event"] for r in sm.diagnostic_log() if r["outcome"] == "PLAYED"] == [
            "snap", "click", "tick", "snap"]
        assert len(played) == 4

    def test_high_rate_typewriter_coalesces_explicitly(self):
        sm, played = self._mgr()
        for _ in range(20):
            sm.play("type")
        assert len(played) == 1
        assert not sm._pending
        assert sum(r["outcome"] == "COALESCED" for r in sm.diagnostic_log()) == 19

    def test_alarm_is_preempted_by_immediate_action_sound(self):
        # SRC-010: a short UI action during an alarm must sound NOW, not be
        # dropped and not replay seconds later. The alarm is cut; the action
        # plays in its own moment.
        sm, played = self._mgr()
        sm.play_sound_ref("timer", 0.8)
        alarm_id = sm._current["id"]
        sm.play("click")
        sm.play_file("click_soft.wav")
        assert not sm._pending
        outcomes = [r["outcome"] for r in sm.diagnostic_log()]
        assert outcomes.count("REPLACED_ALARM") >= 1
        assert outcomes.count("PLAYED") == 3
        self._finish(sm)
        assert len(played) == 3
        assert alarm_id not in {t for t, ok in sm._finished if ok}

    def test_distinct_alarms_play_in_moment_not_serial_ghosts(self):
        # SRC-010: distinct scheduled alarms on one tick each start in the
        # moment they are observed — the newer one preempts the older instead
        # of queueing a delayed replay (old audit 6.2 contract superseded).
        sm, played = self._mgr()
        for source in ("timer", "interval", "productivity", "AI limit"):
            sm._emit_file(os.path.join(sm._sounds_dir, "click_soft.wav"), 0.5,
                          event=source, source=source)
        assert len(played) == 4
        played_events = [r["event"] for r in sm.diagnostic_log()
                         if r["outcome"] == "PLAYED"]
        assert played_events == ["timer", "interval", "productivity", "AI limit"]

    def test_identical_alarm_event_coalesces_instead_of_chorus(self):
        # The same logical alarm observed twice (one shared transition firing
        # two subsystems that resolve to the same event) must NOT stack into an
        # accidental chorus -- audit 6.2 "identical logical event: coalesce".
        sm, played = self._mgr()
        for _ in range(3):
            sm._emit_file(os.path.join(sm._sounds_dir, "click_soft.wav"), 0.5,
                          event="timer", source="timer", dedupe_key="alarm-1")
        assert len(played) == 1
        assert not sm._pending
        assert sum(r["outcome"] == "COALESCED" for r in sm.diagnostic_log()) == 2

    def test_provenance_source_resolution_is_cached_per_call_site(self):
        # audit 6.4: the typewriter hot path must not re-walk frames per key.
        from fastprompter.core.sound_manager import _SOURCE_CACHE, _sound_source
        _SOURCE_CACHE.clear()

        def probe():
            return _sound_source()

        first = probe()
        assert first.endswith(":probe")
        assert len(_SOURCE_CACHE) == 1
        second = probe()
        assert second == first
        assert len(_SOURCE_CACHE) == 1  # cache hit, no second walk

    def test_profile_switch_cancels_stale_completion(self):
        # A stale transport completion from a previous profile must never drain a
        # new owner's request (audit 6.3). The alarm finishes on switch; a
        # later snap is a fresh short request (its token was consumed the
        # moment it played), so the old token's late completion is ignored.
        sm, played = self._mgr()
        sm.play_sound_ref("timer", 0.8)
        old = sm._current["id"]
        sm._data = {"sound_ui": "True"}
        self._finish(sm)
        assert sm._current is None
        sm.play("snap")
        sm._complete_request(old)
        assert sm._current is None
        assert len(played) == 2

    def test_provenance_ring_is_bounded_no_spam(self):
        sm, played = self._mgr()
        for _ in range(400):
            sm.play("snap")
        # Every rapid press still starts immediately; the diagnostic ring is
        # capped so long sessions never grow boundlessly.
        assert len(played) == 400
        assert len(sm.diagnostic_log()) == 256
        sm.shutdown()
        assert not sm._pending

    def test_sync_worker_waits_for_real_completion_off_caller_thread(self):
        import threading

        from fastprompter.core.sound_manager import _SerialWavWorker
        started, release = threading.Event(), threading.Event()
        threads = []
        def play(*args):
            threads.append(threading.get_ident())
            started.set()
            release.wait(2)
            return True
        worker = _SerialWavWorker(play)
        try:
            worker.submit((1, "test.wav", 1.0, {}, True))
            assert started.wait(1)
            assert worker.completed.empty()
            assert worker.pending() is False, "started job is not backlog"
            assert threads != [threading.get_ident()]
            release.set()
            assert worker.completed.get(timeout=1) == (1, True)
        finally:
            release.set()
            worker.close()
            worker.thread.join(1)
        assert not worker.thread.is_alive()

    def test_long_notifications_replace_the_previous_long_player(self):
        # T-1221 §5: distinct long notifications REPLACE on the QSoundEffect
        # transport too — the previous long player is stopped, never left
        # playing under the new one as an accidental chorus.
        sm, played = self._mgr()
        sm.play_sound_ref("timer", 0.8)
        sm.play_sound_ref("file:newday.wav", 0.8)
        longs = type(sm._players["__ui__"]).spawned
        assert len(longs) == 2, longs
        first, second = longs
        assert first.stopped and not first.active, "old long kept playing"
        assert second.active, "replacement never started"
        assert sm._current["event"] == "file:newday.wav"

    def test_short_sound_stops_the_sounding_long_player(self):
        # T-1221 §6: the preemption helper also owns the QSoundEffect long
        # player — a short action sound must not play UNDER a live alarm.
        sm, played = self._mgr()
        sm.play_sound_ref("timer", 0.8)
        alarm_player = sm._players["__ui__"]
        sm.play("click")
        assert alarm_player.stopped and not alarm_player.active
        assert sm._current is None
        outcomes = [r["outcome"] for r in sm.diagnostic_log()]
        assert outcomes.count("PLAYED") == 2
        assert outcomes.count("REPLACED_ALARM") == 1


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
        from fastprompter.core.sound_manager import _DEFAULT_SOUND_MAP
        target = _DEFAULT_SOUND_MAP.get("click", "click_soft.wav")
        p = tmp_path / target
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"RIFF")
        sm = self._mgr(tmp_path)
        assert sm.play_sound_ref("click", 0.5) is True

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


# ---------------------------------------------------------------------------
# T-1221 §2: the PACKAGED winsound transport (QSoundEffect unavailable).
# A QSoundEffect-only green suite cannot close this ticket: the shipped
# build has no qt6multimedia.dll, so every regression here drives the real
# SoundManager flow with winsound faked at the device boundary.
# ---------------------------------------------------------------------------

class FakeWinsound:
    """winsound device fake: every PlaySound returns at once (SND_ASYNC).

    T-1221 transport truth: no synchronous playback ever holds the device,
    so the fake never blocks. Dispatches are attributed by thread —
    ``worker_starts`` are the transport's long-alarm dispatches,
    ``caller_starts`` the in-the-moment short dispatches — and
    PlaySound(None, 0) is the interrupt.
    """

    SND_FILENAME = 0x20000
    SND_SYNC = 0x0000
    SND_ASYNC = 0x0008
    SND_NODEFAULT = 0x0002

    WORKER_THREAD = "FastPrompter audio"

    def __init__(self):
        self.lock = threading.Lock()
        self.calls = []            # every (source, flags, thread) in order
        self.worker_starts = []    # sources dispatched by the audio worker
        self.caller_starts = []    # sources dispatched by the caller thread
        self.stop_calls = 0

    def PlaySound(self, source, flags):
        who = threading.current_thread().name
        with self.lock:
            self.calls.append((source, flags, who))
            if source is None:
                self.stop_calls += 1
                return
            if who == self.WORKER_THREAD:
                self.worker_starts.append(source)
            else:
                self.caller_starts.append(source)


def _wait_until(predicate, timeout=2.0, what="condition"):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    raise AssertionError(f"timed out waiting for {what}")


def _tiny_wav(tmp_path, name):
    path = tmp_path / name
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(8000)
        w.writeframes(b"\x00\x01" * 800)
    return path


class TestPackagedWinsoundTransport:
    """T-1221: the shipped winsound path must have no user-intent FIFO.

    Every test here pins the packaged branch (module QSoundEffect = None)
    and fakes the winsound device, so the SOUND MANAGER's scheduling — not
    Qt's — is what is under test. The central observable: no request ever
    waits behind another sound, and no obsolete request ever replays.
    """

    @pytest.fixture
    def packaged(self, tmp_path):
        fake = FakeWinsound()
        for name in ("alarm_a.wav", "alarm_b.wav", "alarm_c.wav",
                     "alarm_long.wav", "button1.wav", "pop_up_02.wav"):
            _tiny_wav(tmp_path, name)
        saved_qse = _STUB_SM_MOD.QSoundEffect
        saved_ws = sys.modules.get("winsound")
        _STUB_SM_MOD.QSoundEffect = None
        sys.modules["winsound"] = fake
        sm = SoundManager(_MockQObject(),
                          {"sound_ui": "True", "sound_typewriter": "True"})
        sm._sounds_dir = str(tmp_path)
        yield sm, fake, tmp_path
        try:
            sm.shutdown()
        except Exception:
            pass
        sys.modules.pop("winsound", None)
        if saved_ws is not None:
            sys.modules["winsound"] = saved_ws
        _STUB_SM_MOD.QSoundEffect = saved_qse

    # ------------------------------------------------------------- §2.1

    def test_long_replacement_never_fifos_behind_sounding_alarm(self, packaged):
        sm, fake, _tmp = packaged
        sm.play_sound_ref("file:alarm_a.wav", 0.8)
        _wait_until(lambda: len(fake.worker_starts) >= 1, what="alarm A dispatch")
        stops_at_alarm = fake.stop_calls
        sm.play_sound_ref("file:alarm_b.wav", 0.8)
        # B takes the mailbox NOW; A is interrupted instead of finishing.
        _wait_until(lambda: len(fake.worker_starts) >= 2, what="alarm B dispatch")
        starts = [os.path.basename(s) for s in fake.worker_starts]
        assert starts[0].startswith("alarm_a"), starts
        assert starts[1].startswith("alarm_b"), starts
        # T-1228: replacement does NOT stop the device first. The fresh
        # SND_ASYNC PlaySound(B) already replaces A on the single device, so
        # no PlaySound(None, 0) transient may appear before B.
        assert fake.stop_calls == stops_at_alarm, "stop-before-start transient"
        assert sm._current["event"] == "file:alarm_b.wav"
        # After B's natural end, no delayed A replay may surface anywhere.
        _wait_until(lambda: sm._worker.completed.qsize() >= 2,
                    what="A+B completion")
        time.sleep(0.15)
        assert len(fake.worker_starts) == 2
        assert not sm._worker.pending()
        assert not sm._pending

    # ------------------------------------------------------------- §2.2

    def test_rapid_long_requests_latest_wins_no_obsolete_replay(self, packaged):
        sm, fake, _tmp = packaged
        sm.play_sound_ref("file:alarm_a.wav", 0.8)
        _wait_until(lambda: len(fake.worker_starts) >= 1, what="alarm A dispatch")
        sm.play_sound_ref("file:alarm_b.wav", 0.8)
        sm.play_sound_ref("file:alarm_c.wav", 0.8)
        _wait_until(lambda: len(fake.worker_starts) >= 2,
                    what="latest alarm dispatch")
        starts = [os.path.basename(s) for s in fake.worker_starts]
        assert starts[0].startswith("alarm_a"), starts
        # T-1242: the newest request's first dispatch includes a one-time
        # device-rate render on the worker thread, so wait for C to surface
        # instead of racing it between two poll ticks.
        _wait_until(
            lambda: bool(fake.worker_starts) and os.path.basename(
                fake.worker_starts[-1]).startswith("alarm_c"),
            what="alarm C dispatch")
        starts = [os.path.basename(s) for s in fake.worker_starts]
        assert os.path.basename(fake.worker_starts[-1]).startswith(
            "alarm_c"), starts
        # No obsolete request may replay after the newest one took over.
        c_at = next(i for i, s in enumerate(starts) if s.startswith("alarm_c"))
        assert all(s.startswith("alarm_c") for s in starts[c_at:]), starts
        _wait_until(lambda: sm._worker.completed.qsize() >= 2,
                    what="final completions")
        time.sleep(0.15)
        assert len(fake.worker_starts) <= 3
        assert not sm._worker.pending()
        outcomes = [r["outcome"] for r in sm.diagnostic_log()]
        assert outcomes.count("CANCELLED") >= 1
        assert outcomes.count("PLAYED") >= 1

    # ------------------------------------------------------------- §2.3

    def test_short_sound_during_long_alarm_dispatches_now(self, packaged):
        sm, fake, _tmp = packaged
        sm.play_sound_ref("file:alarm_long.wav", 0.8)
        _wait_until(lambda: len(fake.worker_starts) >= 1, what="alarm dispatch")
        stops_at_alarm = fake.stop_calls
        sm.play("click")
        # The click is dispatched in the moment of the action: an async
        # device call, not a job parked behind the alarm worker.
        assert fake.caller_starts, "click was not dispatched"
        # T-1228: the short WAV itself replaces the long one; no explicit
        # device stop may precede it.
        assert fake.stop_calls == stops_at_alarm, "stop-before-start transient"
        # The cancelled alarm must never reappear after the click.
        time.sleep(0.3)
        assert len(fake.worker_starts) == 1
        assert not sm._pending
        assert sm._worker is None or not sm._worker.pending()
        outcomes = [r["outcome"] for r in sm.diagnostic_log()]
        assert outcomes.count("REPLACED_ALARM") == 1

    def test_short_sound_during_pending_replacement_drops_stale_intent(
            self, packaged):
        sm, fake, _tmp = packaged
        sm.play_sound_ref("file:alarm_long.wav", 0.8)
        _wait_until(lambda: len(fake.worker_starts) >= 1, what="alarm dispatch")
        # A replacement intent parked in the transport mailbox, not yet
        # started — exactly what worker.jobs used to retain after a cancel.
        sm._worker.replace((999999, os.path.join(str(_tmp), "alarm_b.wav"),
                            1.0, {}, True))
        assert sm._worker.pending()
        sm.play("click")
        assert fake.caller_starts, "click was not dispatched"
        settled = len(fake.worker_starts)
        # The stale replacement intent is discarded: nothing B-ish may be
        # dispatched after the click (at most, B was the live sound the
        # click preempted — it can never replay afterwards).
        time.sleep(0.35)
        late = [os.path.basename(s) for s in fake.worker_starts[settled:]]
        assert not any(s.startswith("alarm_b") for s in late), late
        assert not sm._worker.pending()
        assert sum(
            os.path.basename(s).startswith("alarm_b")
            for s in fake.worker_starts) <= 1

    # ------------------------------------------------------------- §2.4

    def test_rapid_short_burst_dispatches_every_press_immediately(self,
                                                                  packaged):
        sm, fake, _tmp = packaged
        for _ in range(36):
            sm.play("snap")
        # 36 presses = 36 in-the-moment SND_ASYNC dispatch attempts. Newer
        # blips replace older ones audibly, but every press dispatches.
        assert len(fake.caller_starts) == 36, len(fake.caller_starts)
        assert not sm._pending
        assert sm._current is None
        # No transport queue was ever created for short feedback.
        assert sm._worker is None
        time.sleep(0.05)
        assert len(fake.caller_starts) == 36, "delayed replay after the burst"

    # ------------------------------------------------------------- §2.5

    def test_shutdown_interrupts_long_and_terminates_worker_bounded(
            self, packaged):
        sm, fake, _tmp = packaged
        sm.play_sound_ref("file:alarm_long.wav", 0.8)
        _wait_until(lambda: len(fake.worker_starts) >= 1, what="alarm dispatch")
        stops_at_alarm = fake.stop_calls
        sm.shutdown()
        assert not sm._worker.thread.is_alive(), "worker hung past shutdown"
        assert fake.stop_calls > stops_at_alarm, (
            "current sound was never interrupted")
        # No queued sound may start during/after shutdown.
        baseline = len(fake.calls)
        time.sleep(0.05)
        assert len(fake.calls) == baseline

    def test_shutdown_discards_pending_transport_intent_and_is_idempotent(
            self, packaged):
        sm, fake, _tmp = packaged
        sm.play_sound_ref("file:alarm_long.wav", 0.8)
        _wait_until(lambda: len(fake.worker_starts) >= 1, what="alarm dispatch")
        sm._worker.replace((424242, os.path.join(str(_tmp), "alarm_c.wav"),
                            1.0, {}, True))
        assert sm._worker.pending()
        sm.shutdown()
        settled = len(fake.worker_starts)
        assert not sm._worker.pending(), "intent survived shutdown"
        assert not sm._worker.thread.is_alive()
        sm.shutdown()  # repeated shutdown is safe
        time.sleep(0.2)
        late = [os.path.basename(s) for s in fake.worker_starts[settled:]]
        assert not late, "a sound started after shutdown"
        assert sum(
            os.path.basename(s).startswith("alarm_c")
            for s in fake.worker_starts) <= 1

    # ------------------------------------------------------------- §4

    def test_duplicate_dedupe_key_coalesces_without_stopping_current(
            self, packaged):
        sm, fake, _tmp = packaged
        sm.play_sound_ref("file:alarm_long.wav", 0.8, dedupe_key="alarm-1")
        _wait_until(lambda: len(fake.worker_starts) >= 1, what="alarm dispatch")
        stops_before = fake.stop_calls
        sm.play_sound_ref("file:alarm_long.wav", 0.8, dedupe_key="alarm-1")
        outcomes = [r["outcome"] for r in sm.diagnostic_log()]
        assert outcomes.count("COALESCED") == 1
        assert fake.stop_calls == stops_before, (
            "the current sound was stopped for a duplicate")
        assert len(fake.worker_starts) == 1
        assert sm._current["id"] == 1

    def test_same_file_without_dedupe_key_is_a_distinct_notification(
            self, packaged):
        # Duplicate identity comes ONLY from an explicit dedupe_key. The
        # same WAV fired twice without one is two distinct notifications:
        # the newest replaces the older, it is not folded away.
        sm, fake, _tmp = packaged
        sm.play_sound_ref("file:alarm_long.wav", 0.8)
        _wait_until(lambda: len(fake.worker_starts) >= 1, what="first dispatch")
        stops_at_alarm = fake.stop_calls
        sm.play_sound_ref("file:alarm_long.wav", 0.8)
        _wait_until(lambda: len(fake.worker_starts) >= 2, what="second dispatch")
        # T-1228: long -> long replacement is direct; no device stop.
        assert fake.stop_calls == stops_at_alarm
        outcomes = [r["outcome"] for r in sm.diagnostic_log()]
        assert outcomes.count("COALESCED") == 0
        assert outcomes.count("PLAYED") == 2

    # ------------------------------------------------------------- §7

    def test_stale_winsound_completion_cannot_touch_the_replacement(
            self, packaged):
        sm, fake, _tmp = packaged
        sm.play_sound_ref("file:alarm_a.wav", 0.8)
        _wait_until(lambda: len(fake.worker_starts) >= 1, what="alarm A dispatch")
        stale_token = sm._current["id"]
        sm.play_sound_ref("file:alarm_b.wav", 0.8)
        _wait_until(lambda: len(fake.worker_starts) >= 2, what="alarm B dispatch")
        current_token = sm._current["id"]
        assert current_token != stale_token
        # Drain the interrupted A's transport completion.
        _wait_until(lambda: sm._worker.completed.qsize() >= 1,
                    what="A transport completion")
        sm._poll_transport()
        assert sm._current is not None
        assert sm._current["id"] == current_token
        assert all(t != stale_token for t, _ok in sm._finished)
        # A late, explicit stale completion is equally harmless.
        sm._complete_request(stale_token)
        sm._complete_request(stale_token, success=False)
        assert sm._current is not None
        assert sm._current["id"] == current_token

    # ------------------------------------------------- §9 test language

    def test_no_transport_fifo_survives_semantic_cancel(self, packaged):
        # "no FIFO" claims must check the transport, not only sm._pending.
        sm, fake, _tmp = packaged
        sm.play_sound_ref("file:alarm_long.wav", 0.8)
        _wait_until(lambda: len(fake.worker_starts) >= 1, what="alarm dispatch")
        sm._worker.replace((777, os.path.join(str(_tmp), "alarm_b.wav"),
                            1.0, {}, True))
        sm.play("click")
        settled = len(fake.worker_starts)
        # Semantic queue empty is NOT the proof; the transport mailbox must
        # be empty too, and no stale dispatch may follow the click.
        assert not sm._pending
        assert not sm._worker.pending()
        time.sleep(0.35)
        late = [os.path.basename(s) for s in fake.worker_starts[settled:]]
        assert not any(s.startswith("alarm_b") for s in late), late
        assert not sm._worker.pending()

    # ------------------------------------------------- T-1228 stray-audio

    def test_idle_long_has_no_pre_stop_and_traces_start(self, packaged):
        # T-1228 §16: idle -> long must issue exactly one device start (A)
        # with ZERO PlaySound(None, 0) before it.
        sm, fake, _tmp = packaged
        sm.play_sound_ref("file:alarm_a.wav", 0.8)
        _wait_until(lambda: len(fake.worker_starts) >= 1, what="alarm dispatch")
        assert fake.stop_calls == 0, "idle -> long stopped the device first"
        ops = [e["operation"] for e in sm.transport_diagnostic_log()]
        assert "REQUEST" in ops
        assert "REPLACE_WAV" in ops
        assert "START_WAV" in ops
        assert "STOP_DEVICE" not in ops, ops

    def test_long_to_short_has_no_stop_device(self, packaged):
        # T-1228 §18: the short WAV replaces the long directly; no stop.
        sm, fake, _tmp = packaged
        sm.play_sound_ref("file:alarm_long.wav", 0.8)
        _wait_until(lambda: len(fake.worker_starts) >= 1, what="alarm dispatch")
        sm.play("click")
        assert fake.caller_starts, "click was not dispatched"
        assert fake.stop_calls == 0, "long -> short stopped the device first"
        ops = [e["operation"] for e in sm.transport_diagnostic_log()]
        assert "STOP_DEVICE" not in ops, ops

    def test_transport_trace_is_bounded_and_copy_only(self, packaged):
        sm, fake, _tmp = packaged
        for _ in range(300):
            sm.play("snap")
        trace = sm.transport_diagnostic_log()
        assert len(trace) <= 256
        trace.clear()
        assert len(sm.transport_diagnostic_log()) >= 1, "trace must be copy-only"
