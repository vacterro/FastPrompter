"""T-1242: Temporal audio fidelity, zero resurrection, and click suppression tests."""

from __future__ import annotations

import os
import sys
import wave

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

from fastprompter.core.audio_hub import (
    AudioHub,
    FakeMultiChannelTransport,
    Outcome,
    QtSoundTransport,
    StopReason,
    _PoolEntry,
)
from fastprompter.core.sound_manager import SoundManager
from fastprompter.ui.button_sound import ButtonClickSoundFilter


class _Signal:
    def __init__(self) -> None:
        self._slots: list = []

    def connect(self, slot) -> None:
        self._slots.append(slot)

    def disconnect(self, slot=None) -> None:
        if slot is None:
            self._slots.clear()
        elif slot in self._slots:
            self._slots.remove(slot)

    def emit(self, *args) -> None:
        for slot in list(self._slots):
            slot(*args)


class FakeQSoundEffectWithStatus:
    class Loop:
        Infinite = -2

    class Status:
        Null = 0
        Loading = 1
        Ready = 2
        Error = 3

    # Class-level markers so the transport's capability probe passes.
    playingChanged = None
    statusChanged = None

    created: list = []

    def __init__(self) -> None:
        self.source = None
        self.volume = 1.0
        self.loop_count = 1
        self.play_calls = 0
        self.stop_calls = 0
        self._playing = False
        self._status = self.Status.Loading
        self.playingChanged = _Signal()
        self.statusChanged = _Signal()
        FakeQSoundEffectWithStatus.created.append(self)

    def setSource(self, url) -> None:
        self.source = url

    def setVolume(self, value) -> None:
        self.volume = float(value)

    def setLoopCount(self, count) -> None:
        self.loop_count = count

    def status(self) -> int:
        return self._status

    def set_status(self, s: int) -> None:
        self._status = s
        self.statusChanged.emit()

    def play(self) -> None:
        self.play_calls += 1
        self._playing = True
        self.playingChanged.emit()

    def stop(self) -> None:
        self.stop_calls += 1
        if self._playing:
            self._playing = False
            self.playingChanged.emit()

    def isPlaying(self) -> bool:
        return self._playing

    def finish(self) -> None:
        if self._playing:
            self._playing = False
            self.playingChanged.emit()


def _wav(tmp_path, name: str) -> str:
    path = tmp_path / name
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(8000)
        handle.writeframes(b"\x00\x00" * 400)
    return str(path)


@pytest.fixture()
def status_transport():
    FakeQSoundEffectWithStatus.created = []
    return QtSoundTransport(
        qsoundeffect_cls=FakeQSoundEffectWithStatus,
        url_factory=lambda p: f"file:///{p}",
    )


class TestLoadingRejectionAndResurrection:
    def test_loading_source_is_rejected_truthfully(self, status_transport, tmp_path):
        wav_path = _wav(tmp_path, "cue.wav")
        effect = FakeQSoundEffectWithStatus()
        effect._status = FakeQSoundEffectWithStatus.Status.Loading
        status_transport._pools[(wav_path, wav_path, False, 0)] = [
            _PoolEntry(effect, wav_path, False, 0)
        ]

        handle = status_transport.play(wav_path, token="req_load_1")
        assert handle == "", "Loading source must return empty handle"
        assert effect.play_calls == 0

        failure = status_transport.take_failure("req_load_1")
        assert failure is not None
        assert failure["reason"] == StopReason.SOURCE_LOADING.value

    def test_late_ready_never_starts_playback(self, status_transport, tmp_path):
        wav_path = _wav(tmp_path, "cue2.wav")
        effect = FakeQSoundEffectWithStatus()
        effect._status = FakeQSoundEffectWithStatus.Status.Loading
        status_transport._pools[(wav_path, wav_path, False, 0)] = [
            _PoolEntry(effect, wav_path, False, 0)
        ]

        status_transport.play(wav_path, token="req_load_2")
        assert effect.play_calls == 0

        # Simulate late status change to Ready
        effect.set_status(FakeQSoundEffectWithStatus.Status.Ready)
        assert effect.play_calls == 0, "Late Ready must NEVER trigger deferred play()"
        assert status_transport.active_handles() == []

    def test_ready_source_plays_immediately(self, status_transport, tmp_path):
        wav_path = _wav(tmp_path, "cue3.wav")
        effect = FakeQSoundEffectWithStatus()
        effect._status = FakeQSoundEffectWithStatus.Status.Ready
        status_transport._pools[(wav_path, wav_path, False, 0)] = [
            _PoolEntry(effect, wav_path, False, 0)
        ]

        handle = status_transport.play(wav_path, token="req_ready")
        assert handle.startswith("qtch:")
        assert effect.play_calls == 1
        assert status_transport.active_handles() == [handle]

    def test_stop_all_leaves_no_latent_sound(self, status_transport, tmp_path):
        wav_path = _wav(tmp_path, "cue4.wav")
        effect = FakeQSoundEffectWithStatus()
        effect._status = FakeQSoundEffectWithStatus.Status.Ready
        status_transport._pools[(wav_path, wav_path, False, 0)] = [
            _PoolEntry(effect, wav_path, False, 0)
        ]

        handle = status_transport.play(wav_path)
        assert handle
        status_transport.stop_all()
        assert status_transport.active_handles() == []
        assert effect.stop_calls >= 1

        effect.finish()
        assert status_transport.active_handles() == []

    def test_hub_truthful_failure_on_loading_transient(self, status_transport, tmp_path):
        """AudioHub must report STOPPED (with reason SOURCE_LOADING) when transport refuses Loading."""
        hub = AudioHub(transport=status_transport)
        wav_path = _wav(tmp_path, "cold.wav")
        effect = FakeQSoundEffectWithStatus()
        effect._status = FakeQSoundEffectWithStatus.Status.Loading
        status_transport._pools[(wav_path, wav_path, False, 0)] = [
            _PoolEntry(effect, wav_path, False, 0)
        ]

        result = hub.play_result(wav_path, event="test_cold")
        assert result.outcome == Outcome.STOPPED
        assert result.channel == ""
        assert hub.active_channels() == []

        prov = hub.provenance()
        assert len(prov) == 1
        assert prov[0]["outcome"] == "STOPPED"
        assert prov[0]["reason"] == "SOURCE_LOADING"

    def test_newer_cue_starts_while_older_loading_cue_stays_dead(self, status_transport, tmp_path):
        """Request A is Loading -> dropped. Request B is Ready -> plays.
        When A becomes Ready later, A NEVER plays."""
        hub = AudioHub(transport=status_transport)
        path_a = _wav(tmp_path, "cue_a.wav")
        path_b = _wav(tmp_path, "cue_b.wav")

        eff_a = FakeQSoundEffectWithStatus()
        eff_a._status = FakeQSoundEffectWithStatus.Status.Loading
        status_transport._pools[(path_a, path_a, False, 0)] = [
            _PoolEntry(eff_a, path_a, False, 0)
        ]

        eff_b = FakeQSoundEffectWithStatus()
        eff_b._status = FakeQSoundEffectWithStatus.Status.Ready
        status_transport._pools[(path_b, path_b, False, 0)] = [
            _PoolEntry(eff_b, path_b, False, 0)
        ]

        # Request A arrives and is dropped truthfully
        res_a = hub.play_result(path_a, event="cue_a")
        assert res_a.outcome == Outcome.STOPPED
        assert eff_a.play_calls == 0

        # Request B arrives and plays
        res_b = hub.play_result(path_b, event="cue_b")
        assert res_b.outcome in (Outcome.PLAYED, Outcome.MIXED)
        assert eff_b.play_calls == 1

        # Now A transitions to Ready later
        eff_a.set_status(FakeQSoundEffectWithStatus.Status.Ready)
        assert eff_a.play_calls == 0, "A must NEVER resurrect after B started!"


class TestRequestCounterAndButtonClickSuppression:
    def test_hub_request_count_advances(self, tmp_path):
        transport = FakeMultiChannelTransport()
        hub = AudioHub(transport=transport)
        assert hub.request_count() == 0

        wav_path = _wav(tmp_path, "test.wav")
        res = hub.play_result(wav_path, event="test_event")
        assert res.outcome in (Outcome.PLAYED, Outcome.MIXED)
        assert hub.request_count() == 1

        hub.play_result(wav_path, event="test_event2")
        assert hub.request_count() == 2

    def test_sound_manager_request_count_includes_hub(self, tmp_path):
        transport = FakeMultiChannelTransport()
        hub = AudioHub(transport=transport)
        sm = SoundManager(None, {})
        sm._hub = hub

        initial = sm.request_count()
        wav_path = _wav(tmp_path, "test.wav")
        hub.play(wav_path, event="problip_test")

        assert sm.request_count() == initial + 1

    def test_button_click_filter_suppresses_click_on_hub_sound(self, qapp, tmp_path):
        from PyQt6.QtCore import QEvent, QPointF, Qt
        from PyQt6.QtGui import QMouseEvent
        from PyQt6.QtWidgets import QPushButton

        transport = FakeMultiChannelTransport()
        hub = AudioHub(transport=transport)
        sm = SoundManager(None, {})
        sm._hub = hub

        btn_filter = ButtonClickSoundFilter(sm)
        qapp.installEventFilter(btn_filter)

        btn = QPushButton("Test Problip")
        btn.show()

        played_sounds = []
        orig_play = sm.play

        def mock_sm_play(event, *args, **kwargs):
            played_sounds.append(event)
            return orig_play(event, *args, **kwargs)

        sm.play = mock_sm_play

        wav_path = _wav(tmp_path, "blip.wav")

        def on_clicked():
            hub.play(wav_path, event="problip_test")

        btn.clicked.connect(on_clicked)

        press = QMouseEvent(
            QEvent.Type.MouseButtonPress,
            QPointF(5, 5),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        release = QMouseEvent(
            QEvent.Type.MouseButtonRelease,
            QPointF(5, 5),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        qapp.sendEvent(btn, press)
        qapp.sendEvent(btn, release)
        qapp.processEvents()

        assert "click" not in played_sounds, (
            f"Expected click sound to be suppressed, but got: {played_sounds}"
        )

        qapp.removeEventFilter(btn_filter)
        btn.deleteLater()
