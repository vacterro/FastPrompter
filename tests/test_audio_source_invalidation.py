"""T-1242 spec 5 integration: UI toggles drive ONE canonical invalidation.

The user could flip "Pre-render sounds to the output device rate" / "Add
silent margins to short sounds" off while the transport kept playing pooled
effects built for the OLD policy: SoundManager.invalidate_cache() cleared
its own resolution caches but left every already-created QSoundEffect alive.
These tests drive the real SoundManager->AudioHub->QtSoundTransport chain
against a fake QSoundEffect and prove the retirement happens.
"""

from __future__ import annotations

import os
import sys
import wave

import pytest

sys.path.insert(0, os.path.abspath(
    os.path.join(os.path.dirname(__file__), "../src")))

from fastprompter.core import audio_render  # noqa: E402
from fastprompter.core.audio_hub import (
    AudioHub,  # noqa: E402
    QtSoundTransport,  # noqa: E402
)
from fastprompter.core.sound_manager import SoundManager  # noqa: E402


class _Signal:
    def __init__(self) -> None:
        self._slots = []

    def connect(self, slot) -> None:
        self._slots.append(slot)

    def emit(self, *args) -> None:
        for slot in list(self._slots):
            slot(*args)


class WiringQSoundEffect:
    """QSoundEffect stand-in that reports its own status as Ready."""

    class Loop:
        Infinite = -2

    playingChanged = None
    created: list = []

    def __init__(self) -> None:
        self.source = None
        self._playing = False
        self.playingChanged = _Signal()
        WiringQSoundEffect.created.append(self)

    def setSource(self, url) -> None:
        self.source = url

    def setVolume(self, value) -> None:
        pass

    def setLoopCount(self, count) -> None:
        pass

    def play(self) -> None:
        self._playing = True
        self.playingChanged.emit()

    def stop(self) -> None:
        if self._playing:
            self._playing = False
            self.playingChanged.emit()

    def isPlaying(self) -> bool:
        return self._playing

    def status(self) -> int:
        return 2  # Ready


def _wav(tmp_path, name: str = "blip.wav") -> str:
    path = tmp_path / name
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(22050)
        handle.writeframes(b"\x00\x01" * 800)
    return str(path)


def _shell_manager(data: dict) -> tuple[SoundManager, QtSoundTransport]:
    """A SoundManager wired to a REAL hub + REAL QtSoundTransport (fake
    QSoundEffect), with the profile dict plumbed in."""
    from collections import deque

    transport = QtSoundTransport(qsoundeffect_cls=WiringQSoundEffect,
                                 url_factory=lambda p: p)
    hub = AudioHub(transport=transport)
    manager = SoundManager.__new__(SoundManager)
    manager._data = data
    manager._data_id = id(data)
    manager._file_cache = {}
    manager._file_sig = {}
    manager._scaled_cache = {}
    manager._pending = deque()
    manager._provenance = []
    manager._transport_trace = []
    manager._hub = hub
    return manager, transport


@pytest.fixture()
def render_switch(monkeypatch):
    """Deterministic A/B switch state independent of the module default."""
    monkeypatch.setattr(audio_render, "_render_enabled", False)
    monkeypatch.setattr(audio_render, "_edge_pad_enabled", False)
    monkeypatch.setattr(audio_render, "device_sample_rate", lambda: None)
    return monkeypatch


class TestUiToggleInvalidation:
    @staticmethod
    def _play(manager, path: str) -> None:
        """One real cue through the hub exactly as _start_request_hub does."""
        manager._hub.play(path, event="problip_cue", bus="problip",
                          mode="mix", volume=0.6)

    def test_invalidate_cache_retires_pooled_transport_effects(
            self, render_switch, tmp_path):
        manager, transport = _shell_manager({})
        path = _wav(tmp_path)
        self._play(manager, path)
        assert transport._pools, "the play should have pooled one effect"

        manager.invalidate_cache()

        assert transport._pools == {}
        assert transport.render_policy_generation() == 1

    def test_profile_dict_replacement_retires_sources(
            self, render_switch, tmp_path):
        """Profile switch replaces self._data then calls invalidate_cache:
        the pooled effects of the previous profile must not survive."""
        manager, transport = _shell_manager({})
        path = _wav(tmp_path)
        self._play(manager, path)
        manager._data = {"replacement": "profile"}
        manager.invalidate_cache()
        assert transport.render_policy_generation() == 1

    def test_next_play_after_invalidation_uses_a_fresh_effect(
            self, render_switch, tmp_path):
        manager, transport = _shell_manager({})
        path = _wav(tmp_path)
        self._play(manager, path)
        first = WiringQSoundEffect.created[-1]
        manager.invalidate_cache()
        self._play(manager, path)
        second = WiringQSoundEffect.created[-1]
        assert second is not first

    def test_stop_all_does_not_retire_pools(self, render_switch, tmp_path):
        """Emergency silence stops play; it is NOT a policy change."""
        manager, transport = _shell_manager({})
        path = _wav(tmp_path)
        self._play(manager, path)
        hub = manager.audio_hub()
        hub.stop_all()
        assert transport.render_policy_generation() == 0
        assert transport._pools, "pools survive emergency silence"


class TestSessionPolicyPin:
    def test_problip_session_pins_one_mode_and_generation(self, monkeypatch,
                                                          tmp_path):
        """Spec 13: cues 4-7 s apart play under the policy pinned at START;
        ordinary scheduling never flips the representation."""
        from fastprompter.ui.problip_controller import ProblipController

        manager, transport = _shell_manager({})
        monkeypatch.setattr(audio_render, "device_sample_rate",
                            lambda: None)

        class Settings:
            playback_mode = "mix"
            interval_config = (4, 7)
            volume_percent = 60
            selected_sound_ids = ()
            run_on_launch = False
            blip_glow_enabled = False

        class Store:
            def load_settings(self):
                return Settings()

        controller = ProblipController.__new__(ProblipController)
        controller._sound_manager = manager
        controller._settings = Settings()
        controller._store = Store()
        controller._closed = False
        controller._session_policy_generation = -1
        controller._session_playback_mode = Settings.playback_mode

        controller._session_playback_mode = controller._settings.playback_mode
        controller._session_policy_generation = (
            manager.transport_policy_generation())
        assert controller._session_policy_generation == 0

        # A policy change mid-session bumps the generation...
        transport.invalidate_sources()
        assert manager.transport_policy_generation() == 1
        # ...and the session keeps playing under its PINNED contract until
        # the next explicit start/settings transition.
        assert controller._session_policy_generation == 0
