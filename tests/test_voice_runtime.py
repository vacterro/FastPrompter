"""T-1238-C3.6/C3.7/C3.8 + E1: the voice countdown is wired to real deadlines.

The pure CountdownScheduler was tested but unused.  These tests prove the
runtime adapter: it observes deadlines FastPrompter already knows, picks ONE
nearest target, announces only future thresholds, never re-announces after a
restart, and speaks through the AudioHub VOICE bus as one sequence job.
"""

from __future__ import annotations

import os
import sys
import wave

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

pytest.importorskip("PyQt6.QtWidgets")

from PyQt6.QtCore import QObject  # noqa: E402

from fastprompter.core.audio_hub import (  # noqa: E402
    AudioHub,
    Bus,
    FakeMultiChannelTransport,
    PlaybackMode,
)
from fastprompter.core.voice_store import (  # noqa: E402
    VoiceStore,
    parse_thresholds,
    reset_pack_cache,
)
from fastprompter.ui.voice_controller import VoiceController  # noqa: E402

_APP = None


def _ensure_app():
    global _APP
    from PyQt6.QtWidgets import QApplication

    _APP = QApplication.instance() or QApplication([])
    return _APP


class _Manager:
    def __init__(self, hub) -> None:
        self._hub = hub

    def audio_hub(self):
        return self._hub


def _wav(path) -> None:
    os.makedirs(os.path.dirname(str(path)), exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(8000)
        handle.writeframes(b"\x00\x00" * 80)


@pytest.fixture()
def rig(tmp_path, monkeypatch):
    _ensure_app()
    # A complete fake VOX pack in an isolated managed library, so nothing
    # here depends on the shipped fragments.
    managed = tmp_path / "managed"
    for token in ("thirty", "minutes", "remaining", "ten", "five", "fifteen",
                  "one", "hour", "warning"):
        _wav(managed / "voice" / "vox" / f"{token}.wav")
    monkeypatch.setattr("fastprompter.core.sound_library.managed_root",
                        lambda: str(managed))
    reset_pack_cache()

    parent = QObject()
    transport = FakeMultiChannelTransport()
    manager = _Manager(AudioHub(transport=transport))
    store = VoiceStore(str(tmp_path / "audio.db"))
    controller = VoiceController(parent, manager, store=store)
    controller.update_settings(enabled=True)
    yield controller, transport, store
    controller.shutdown()
    reset_pack_cache()
    parent.deleteLater()


class TestSettings:
    def test_voice_is_off_until_the_user_enables_it(self, tmp_path):
        _ensure_app()
        store = VoiceStore(str(tmp_path / "audio.db"))
        assert store.load()["enabled"] is False

    def test_settings_survive_a_restart(self, tmp_path):
        _ensure_app()
        path = str(tmp_path / "audio.db")
        VoiceStore(path).save(enabled=True, pack="fvox", mode="queue",
                              thresholds=[1800, 300], volume_percent=55)
        loaded = VoiceStore(path).load()
        assert loaded["enabled"] is True
        assert loaded["pack"] == "fvox"
        assert loaded["mode"] == "queue"
        assert loaded["thresholds"] == [1800, 300]
        assert loaded["volume_percent"] == 55

    def test_unknown_thresholds_are_rejected(self):
        assert parse_thresholds("1800,7,300,notanumber") == [1800, 300]

    def test_disabling_stops_the_tick_and_drops_the_plan(self, rig):
        controller, _tp, _store = rig
        controller.refresh_target(timers=[{"id": "t1", "due": 1_000_000.0}])
        assert controller.scheduler.target is not None
        controller.update_settings(enabled=False)
        assert controller.scheduler.target is None
        assert not controller._timer.isActive()


class TestTargetSelection:
    def test_the_nearest_normal_timer_becomes_the_target(self, rig):
        controller, _tp, _store = rig
        controller.refresh_target(timers=[
            {"id": "far", "due": 5_000.0},
            {"id": "near", "due": 1_000.0},
        ])
        kind, target_id, due = controller.scheduler.target
        assert (kind, target_id, due) == ("TIMER", "near", 1_000.0)

    def test_the_nearest_ai_limit_reset_can_win(self, rig):
        controller, _tp, _store = rig
        controller.refresh_target(
            timers=[{"id": "t", "due": 9_000.0}],
            limits=[{"key": "claude", "reset": 2_000.0}])
        kind, target_id, _due = controller.scheduler.target
        assert (kind, target_id) == ("AI_LIMIT", "claude")

    def test_a_disabled_source_is_never_targeted(self, rig):
        controller, _tp, _store = rig
        controller.update_settings(source_limits=False)
        controller.refresh_target(
            timers=[{"id": "t", "due": 9_000.0}],
            limits=[{"key": "claude", "reset": 2_000.0}])
        assert controller.scheduler.target[0] == "TIMER"

    def test_an_unchanged_target_never_replans(self, rig):
        controller, _tp, _store = rig
        timers = [{"id": "t1", "due": 1_000_000.0}]
        controller.refresh_target(timers=timers)
        generation = controller.scheduler.generation
        for _ in range(5):
            controller.refresh_target(timers=timers)
        assert controller.scheduler.generation == generation

    def test_a_moved_deadline_invalidates_the_old_plan(self, rig):
        controller, _tp, _store = rig
        controller.refresh_target(timers=[{"id": "t1", "due": 1_000_000.0}])
        generation = controller.scheduler.generation
        controller.refresh_target(timers=[{"id": "t1", "due": 2_000_000.0}])
        assert controller.scheduler.generation > generation

    def test_losing_every_deadline_clears_the_target(self, rig):
        controller, _tp, _store = rig
        controller.refresh_target(timers=[{"id": "t1", "due": 1_000_000.0}])
        controller.refresh_target(timers=[], limits=[])
        assert controller.scheduler.target is None


class TestAnnouncement:
    def test_a_phrase_enters_the_voice_bus_as_one_sequence(self, rig):
        controller, transport, _store = rig
        ok, _detail = controller.test_phrase(1800)
        assert ok
        assert len(transport.channels) == 1, "a phrase is ONE job, not three"
        job = next(iter(transport.channels.values()))
        assert job["path"].endswith("thirty.wav")
        hub = controller._sound_manager.audio_hub()
        assert hub.active_sequences(Bus.VOICE)

    def test_a_newer_phrase_replaces_the_previous_one(self, rig):
        controller, transport, _store = rig
        controller.update_settings(mode="replace")
        controller.test_phrase(1800)
        first = next(iter(transport.channels))
        controller.test_phrase(600)
        assert first in transport.stopped
        assert len(transport.channels) == 1

    def test_a_missing_pack_stays_silent_instead_of_faking(self, rig,
                                                           monkeypatch):
        controller, transport, _store = rig
        controller.update_settings(pack="gman")
        reset_pack_cache()
        ok, message = controller.test_phrase(1800)
        assert ok is False and message
        assert transport.channels == {}

    def test_no_catch_up_speech_for_a_passed_threshold(self, rig):
        controller, transport, _store = rig
        # Everything except the 5-minute mark is already in the past.
        controller.refresh_target(timers=[
            {"id": "t", "due": controller.scheduler._clock() + 400}])
        planned = [seconds for seconds in controller.scheduler._scheduled]
        assert planned == [300]

    def test_exactly_once_across_a_restart(self, rig, tmp_path):
        controller, _tp, store = rig
        clock = {"now": 1_000.0}
        controller._scheduler._clock = lambda: clock["now"]
        due = clock["now"] + 1900
        controller.refresh_target(timers=[{"id": "t", "due": due}])
        clock["now"] = due - 1800 + 1
        first = controller.scheduler.announce()
        assert 1800 in first
        again = controller.scheduler.announce()
        assert 1800 not in again


class TestPlaybackMode:
    def test_inherit_uses_the_global_setting(self, rig):
        controller, transport, _store = rig
        controller.update_settings(mode="inherit")
        hub = controller._sound_manager.audio_hub()
        hub.set_global_mode(PlaybackMode.MIX)
        controller.test_phrase(1800)
        assert transport.channels


class TestShutdown:
    def test_shutdown_stops_the_tick_and_the_plan(self, rig):
        controller, _tp, _store = rig
        controller.refresh_target(timers=[{"id": "t", "due": 1_000_000.0}])
        controller.shutdown()
        assert not controller._timer.isActive()
        assert controller.scheduler.target is None
        controller.shutdown()  # idempotent
