"""T-1238-C1 / E1: the ONE application-owned Problip controller.

A remembered Problip must run for a user who never opens Settings, survive
profile switches without losing its timer or statistics, treat a courtesy
skip as "still running" rather than an error, and leave no callback alive
after shutdown.
"""

from __future__ import annotations

import os
import sys

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
from fastprompter.core.problip import CueResult, IntervalMode, ProblipState  # noqa: E402
from fastprompter.core.problip_store import ProblipStore  # noqa: E402
from fastprompter.ui.problip_controller import ProblipController  # noqa: E402


class _Manager:
    """A SoundManager stand-in exposing only the audio-hub facade."""

    def __init__(self, hub: AudioHub) -> None:
        self._hub = hub
        self.stop_all_calls = 0

    def audio_hub(self) -> AudioHub:
        return self._hub

    def stop_all_sound(self) -> None:
        self.stop_all_calls += 1
        self._hub.stop_all()


#: QTimer only really starts with a LIVE QCoreApplication, and the instance
#: must be held: an unreferenced QApplication is collected immediately and
#: every timer in the process silently stops being active.
_APP = None


def _ensure_app():
    global _APP
    from PyQt6.QtWidgets import QApplication

    _APP = QApplication.instance() or QApplication([])
    return _APP


@pytest.fixture()
def rig(tmp_path):
    _ensure_app()
    parent = QObject()
    transport = FakeMultiChannelTransport()
    hub = AudioHub(transport=transport)
    manager = _Manager(hub)
    store = ProblipStore(str(tmp_path / "problip.db"))
    controller = ProblipController(parent, manager, store=store,
                                   random_source=lambda n: 0)
    yield controller, transport, hub, store
    controller.shutdown()
    parent.deleteLater()


def _fire(controller) -> None:
    """Drive one scheduled cue exactly the way the QTimer would."""
    controller._on_timeout()


class TestStartupWithoutSettings:
    def test_a_remembered_problip_starts_without_opening_settings(self, rig):
        controller, _tp, _hub, store = rig
        store.set_run_on_launch(True)
        controller._settings = store.load_settings()
        assert controller.start_if_remembered() is True
        assert controller.is_running()

    def test_a_fresh_install_stays_off(self, rig):
        controller, _tp, _hub, _store = rig
        assert controller.start_if_remembered() is False
        assert controller.state is ProblipState.STOPPED

    def test_starting_arms_exactly_one_timer(self, rig):
        controller, _tp, _hub, _store = rig
        controller.start()
        assert controller.state is ProblipState.STARTING
        assert controller._timer.isActive()
        assert controller.scheduler.timer_armed


class TestScheduledCue:
    def test_a_cue_plays_on_the_problip_bus_and_counts(self, rig):
        controller, transport, hub, _store = rig
        controller.start()
        _fire(controller)
        assert controller.state is ProblipState.RUNNING
        record = hub.provenance()[-1]
        assert record["bus"] == "problip"
        assert transport.channels
        assert controller.stats().total == 1

    def test_a_cue_glows_only_when_glow_is_enabled(self, rig):
        controller, _tp, _hub, _store = rig
        flashes: list[int] = []
        controller.cuePlayed.connect(lambda: flashes.append(1))
        controller.update_settings(blip_glow_enabled=False)
        controller.start()
        _fire(controller)
        assert flashes == []
        controller.update_settings(blip_glow_enabled=True)
        _fire(controller)
        assert flashes == [1]

    def test_a_busy_skip_is_not_an_error_and_counts_nothing(self, rig):
        controller, _tp, hub, _store = rig
        controller.update_settings(playback_mode="skip_busy")
        controller.start()
        hub.play("alarm.wav", event="timer", bus=Bus.ALERT,
                 mode=PlaybackMode.MIX)
        _fire(controller)
        assert controller.state is not ProblipState.ERROR
        assert controller.is_running(), "a skipped cue keeps Problip running"
        assert controller.stats().total == 0, "a skipped cue never counts"
        assert hub.queue_depth(Bus.PROBLIP) == 0, "a skipped cue never queues"
        assert controller._timer.isActive(), "the next interval is armed"

    def test_a_muted_master_mute_is_a_skip_not_an_error(self, rig):
        """T-1244: a cue becoming due while the master mute is ON must be
        a normal SKIPPED outcome -- no physical audio, no delayed replay,
        and the scheduler stays RUNNING with the next interval armed."""
        controller, transport, hub, _store = rig
        controller.start()
        hub.set_muted(True)
        _fire(controller)
        assert controller.state is not ProblipState.ERROR
        assert controller.is_running(), "a muted cue keeps Problip running"
        assert controller.stats().total == 0, "a muted cue never counts"
        assert transport.channels == {}, "no physical audio while muted"
        assert controller._timer.isActive(), "the next interval is armed"
        # Nothing stale may fire later: unmuting must not resurrect the cue.
        hub.set_muted(False)
        assert transport.channels == {}

    def test_an_unplayable_pool_is_a_real_error(self, rig, monkeypatch):
        controller, _tp, _hub, _store = rig
        controller.start()
        monkeypatch.setattr(
            "fastprompter.ui.problip_controller.resolve_sound_path",
            lambda *_a, **_k: None)
        assert controller._play_cue() is CueResult.FAILED

    def test_no_late_replay_backlog_after_many_skips(self, rig):
        controller, _tp, hub, _store = rig
        controller.update_settings(playback_mode="skip_busy")
        controller.start()
        hub.play("alarm.wav", event="timer", bus=Bus.ALERT,
                 mode=PlaybackMode.MIX)
        for _ in range(10):
            _fire(controller)
        assert hub.queue_depth(Bus.PROBLIP) == 0
        assert controller.stats().total == 0


class TestTestButton:
    def test_test_uses_the_preview_bus_and_never_counts(self, rig):
        controller, _tp, hub, _store = rig
        ok, name = controller.test()
        assert ok and name
        assert hub.provenance()[-1]["bus"] == "preview"
        assert controller.stats().total == 0

    def test_test_works_while_problip_is_off_and_does_not_arm(self, rig):
        controller, _tp, _hub, store = rig
        assert controller.state is ProblipState.STOPPED
        assert controller.test()[0] is True
        assert not controller._timer.isActive()
        assert store.load_settings().run_on_launch is False


class TestIdentityAcrossProfileSwitches:
    def test_nothing_about_the_runtime_changes_on_a_profile_switch(self, rig):
        controller, _tp, _hub, _store = rig
        controller.start()
        _fire(controller)
        before = (id(controller), id(controller._timer), id(controller.store),
                  id(controller.scheduler), controller.scheduler.generation,
                  controller.stats().total)
        # A profile switch touches profile-owned runtime only; Problip is
        # APPLICATION-global and must not be rebuilt or rearmed by it.
        for _ in range(3):
            controller.settingsChanged.emit(controller.settings)
        after = (id(controller), id(controller._timer), id(controller.store),
                 id(controller.scheduler), controller.scheduler.generation,
                 controller.stats().total)
        assert before == after
        assert controller.is_running()

    def test_a_non_interval_setting_change_never_rearms(self, rig):
        controller, _tp, _hub, _store = rig
        controller.start()
        _fire(controller)
        generation = controller.scheduler.generation
        pending = controller.scheduler.pending_delay_ms
        controller.update_settings(volume_percent=42)
        controller.update_settings(show_counter=False)
        assert controller.scheduler.generation == generation
        assert controller.scheduler.pending_delay_ms == pending

    def test_an_interval_change_rearms_exactly_once(self, rig):
        controller, _tp, _hub, _store = rig
        controller.start()
        _fire(controller)
        controller.set_interval_mode(IntervalMode.FIXED_30S)
        # A mode change re-arms the ONE timer with a fresh wait; it does not
        # start a second one and does not invent a new session.
        assert controller.scheduler.pending_delay_ms == 30_000
        assert controller.scheduler.timer_armed
        assert controller._timer.isActive()


class TestPersistence:
    def test_the_playback_mode_survives_a_restart(self, tmp_path):
        _ensure_app()
        parent = QObject()
        manager = _Manager(AudioHub(transport=FakeMultiChannelTransport()))
        path = str(tmp_path / "problip.db")
        first = ProblipController(parent, manager, store=ProblipStore(path))
        first.update_settings(playback_mode="replace",
                              selected_sound_ids=["sound_bonk"])
        first.shutdown()
        second = ProblipController(parent, manager, store=ProblipStore(path))
        try:
            assert second.settings.playback_mode == "replace"
            assert second.settings.selected_sound_ids == ["sound_bonk"]
        finally:
            second.shutdown()
            parent.deleteLater()

    def test_the_default_playback_mode_is_the_safe_one(self, rig):
        controller, _tp, _hub, _store = rig
        assert controller.settings.playback_mode == "skip_busy"


class TestShutdown:
    def test_shutdown_leaves_no_live_callback(self, rig):
        controller, transport, _hub, _store = rig
        controller.start()
        controller.shutdown()
        assert not controller._timer.isActive()
        # Even a callback that somehow arrives afterwards must be inert.
        controller._on_timeout()
        assert not transport.channels

    def test_shutdown_is_idempotent(self, rig):
        controller, _tp, _hub, _store = rig
        controller.shutdown()
        controller.shutdown()
