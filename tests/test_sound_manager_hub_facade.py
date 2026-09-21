"""T-1238-G: SoundManager is the facade over the one AudioHub authority."""

from __future__ import annotations

import pytest

from fastprompter.core.audio_hub import (
    AudioHub,
    Bus,
    FakeMultiChannelTransport,
    Outcome,
    PlaybackMode,
)

qtcore = pytest.importorskip("PyQt6.QtCore")
QtSoundEffect = pytest.importorskip("PyQt6.QtMultimedia", reason="QtMultimedia absent")
from fastprompter.core.sound_manager import SoundManager  # noqa: E402


@pytest.fixture()
def manager(qtbot=None):
    from PyQt6.QtCore import QObject

    parent = QObject()
    data: dict = {}
    sm = SoundManager(parent, data)
    # Inject the deterministic test transport into the hub.
    transport = FakeMultiChannelTransport()
    sm._hub = AudioHub(transport=transport)
    yield sm, transport
    sm.shutdown()
    parent.deleteLater()


class TestFacade:
    def test_sound_manager_owns_one_hub(self, manager):
        sm, _tp = manager
        assert isinstance(sm.audio_hub(), AudioHub)

    def test_stop_all_sound_silences_everything(self, manager):
        sm, tp = manager
        sm._hub.play("a.wav", bus=Bus.UI)
        sm._hub.play("b.wav", bus=Bus.ALERT)
        seq = sm._hub.play_sequence(["x.wav", "y.wav"], bus=Bus.VOICE)
        sm.stop_all_sound()
        assert len(tp.channels) == 0
        assert seq.cancelled
        # Future notifications still allowed.
        assert sm._hub.play("later.wav", bus=Bus.ALERT) is Outcome.PLAYED

    def test_playback_mode_settable(self, manager):
        sm, _tp = manager
        sm.set_playback_mode(PlaybackMode.QUEUE)
        assert sm._hub.global_mode is PlaybackMode.QUEUE
        sm.set_playback_mode("replace")
        assert sm._hub.global_mode is PlaybackMode.REPLACE

    def test_legacy_play_still_governs_named_events(self, manager):
        """The shipped T-1228/SRC-010 policy stays authoritative for play()."""
        sm, _tp = manager
        # Unknown event with no mapping: play() is a silent no-op (existing
        # contract), not a hub crash.
        sm.play("nonexistent_event_xyz")
        assert sm._hub.active_channel_count() == 0
