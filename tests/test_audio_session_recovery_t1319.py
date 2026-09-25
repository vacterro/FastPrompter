"""T-1319 deterministic long-session audio recovery regressions.

No wall-clock sleep and no physical device.  Fakes model the exact Qt failure
boundaries: silent QSoundEffect start, device error, start exception, close
race, and output-device invalidation.
"""

from __future__ import annotations

import os
import sys
import threading
import wave
from collections import deque
from enum import Enum

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

from fastprompter.core import audio_render  # noqa: E402
from fastprompter.core import sound_manager as sound_manager_module  # noqa: E402
from fastprompter.core.audio_hub import (  # noqa: E402
    AudioHub,
    Bus,
    Outcome,
    QtSoundTransport,
    StopReason,
)
from fastprompter.core.sound_manager import SoundManager  # noqa: E402


class _Signal:
    def __init__(self) -> None:
        self._slots = []

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


class _Status(Enum):
    Null = 0
    Loading = 1
    Ready = 2
    Error = 3


class QSE:
    class Status:
        Null = 0
        Loading = 1
        Ready = 2
        Error = 3

    class Loop:
        Infinite = -2

    playingChanged = None
    created = []
    behavior = "healthy"
    raise_once = False
    synchronous_error = False

    def __init__(self) -> None:
        self.source = None
        self.volume = 1.0
        self.loop_count = 1
        self._status = QSE.Status.Ready
        self._playing = False
        self.play_calls = 0
        self.stop_calls = 0
        self.delete_calls = 0
        self.playingChanged = _Signal()
        QSE.created.append(self)

    def setSource(self, value) -> None:
        self.source = value

    def setVolume(self, value) -> None:
        self.volume = value

    def setLoopCount(self, value) -> None:
        self.loop_count = value

    def status(self):
        return self._status

    def isPlaying(self) -> bool:
        return self._playing

    def errorString(self) -> str:
        return "device lost" if self._status is QSE.Status.Error else ""

    def play(self) -> None:
        self.play_calls += 1
        if self.behavior in ("silent", "delayed"):
            return
        if self.behavior == "raise" and QSE.raise_once:
            QSE.raise_once = False
            raise RuntimeError("fake QSE start failure")
        if QSE.synchronous_error:
            self.die()
            return
        self._playing = True
        self.playingChanged.emit()

    def begin(self) -> None:
        self._playing = True
        self.playingChanged.emit()

    def stop(self) -> None:
        self.stop_calls += 1
        self._playing = False
        self.playingChanged.emit()

    def deleteLater(self) -> None:
        self.delete_calls += 1

    def die(self) -> None:
        self._status = QSE.Status.Error
        self._playing = False
        self.playingChanged.emit()


class _SinkState(Enum):
    Active = 0
    Stopped = 1
    Idle = 2


class _SinkError(Enum):
    NoError = 0
    OpenError = 1
    FatalError = 2


class _Sink:
    def __init__(self, factory) -> None:
        self.factory = factory
        self.stateChanged = _Signal()
        self._state = _SinkState.Stopped
        self._error = _SinkError.NoError
        self.volume = 0.0
        self.calls = []

    def setVolume(self, value) -> None:
        if self.factory.block_set_volume:
            self.factory.set_volume_entered.set()
            if not self.factory.release_set_volume.wait(5):
                raise TimeoutError("test did not release volume")
        self.volume = value

    def start(self, _buffer) -> None:
        self.factory.entered.set()
        if not self.factory.release.wait(5):
            raise TimeoutError("test did not release sink")
        if self.factory.sync_idle:
            self._state = _SinkState.Idle
            self.stateChanged.emit(self._state)
            return
        if self.factory.fail:
            self._error = _SinkError.OpenError
            self._state = _SinkState.Stopped
            self.stateChanged.emit(self._state)
            return
        self._state = _SinkState.Active
        self.stateChanged.emit(self._state)

    def state(self):
        return self._state

    def error(self):
        return self._error

    def reset(self) -> None:
        self.calls.append("reset")

    def stop(self) -> None:
        self.calls.append("stop")
        self._state = _SinkState.Stopped


class _SinkFactory:
    def __init__(self) -> None:
        self.entered = threading.Event()
        self.release = threading.Event()
        self.fail = False
        self.sync_idle = False
        self.block_set_volume = False
        self.set_volume_entered = threading.Event()
        self.release_set_volume = threading.Event()
        self.sinks = []
        self.retired = []
        self.timers = []

    def open(self, _pcm, _postroll):
        sink = _Sink(self)
        self.sinks.append(sink)
        return sink, object()

    def watchdog(self, _sink, _ms, callback):
        timer = type("Timer", (), {"stop": lambda self: None})()
        self.timers.append((timer, callback))
        return timer

    def retire(self, sink) -> None:
        self.retired.append(sink)

    @staticmethod
    def state_name(value) -> str:
        return value.name

    @staticmethod
    def error_name(sink) -> str:
        return sink.error().name


class _ManualTimer:
    def __init__(self, callback) -> None:
        self.callback = callback
        self.started = False
        self.stopped = False

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.stopped = True

    def fire(self) -> None:
        if self.started and not self.stopped:
            self.callback()


class RecordingTransport:
    capability_mixing = True

    def __init__(self, explode=False) -> None:
        self.explode = explode
        self.calls = 0
        self.closed = 0
        self.stop_all_calls = 0
        self.channels = {}

    def play(self, path, *, volume=1.0, loop=False, on_complete=None, token=""):
        self.calls += 1
        if self.explode:
            raise RuntimeError("backend exploded")
        handle = f"fake-{self.calls}"
        self.channels[handle] = on_complete
        return handle

    def take_failure(self, _token):
        return None

    def stop(self, handle) -> None:
        self.channels.pop(handle, None)

    def stop_all(self) -> None:
        self.stop_all_calls += 1
        self.channels.clear()

    def set_volume(self, _handle, _volume) -> None:
        pass

    def close(self) -> None:
        self.closed += 1
        self.stop_all()


class SynchronousFailureTransport(RecordingTransport):
    def __init__(self) -> None:
        super().__init__()
        self.failure = {
            "reason": StopReason.SOURCE_ERROR.value,
            "transport": type(self).__name__,
        }

    def play(self, path, *, volume=1.0, loop=False, on_complete=None, token=""):
        handle = super().play(path, volume=volume, loop=loop,
                             on_complete=on_complete, token=token)
        if on_complete is not None:
            on_complete()
        return handle

    def take_failure(self, _token):
        detail, self.failure = self.failure, None
        return detail


class FailingOnceTransport(RecordingTransport):
    def __init__(self) -> None:
        super().__init__()
        self.failed = False
        self.failure = None
        self.recoveries = 0

    def play(self, path, *, volume=1.0, loop=False, on_complete=None, token=""):
        if not self.failed:
            self.failed = True
            self.failure = {
                "reason": StopReason.OUTPUT_UNAVAILABLE.value,
                "transport": type(self).__name__,
            }
            return ""
        return super().play(path, volume=volume, loop=loop,
                            on_complete=on_complete, token=token)

    def take_failure(self, _token):
        detail, self.failure = self.failure, None
        return detail

    def recover(self, _reason) -> None:
        self.recoveries += 1


@pytest.fixture(autouse=True)
def reset_audio_state(monkeypatch):
    QSE.created = []
    QSE.behavior = "healthy"
    QSE.raise_once = False
    QSE.synchronous_error = False
    monkeypatch.setattr(audio_render, "_render_enabled", False)
    monkeypatch.setattr(audio_render, "_edge_pad_enabled", False)
    monkeypatch.setattr(audio_render, "_device_rate_cache", audio_render._MISSING)


def _wav(tmp_path, name="cue.wav") -> str:
    path = tmp_path / name
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(8000)
        handle.writeframes(b"\0\0" * 800)
    return str(path)


def _qse_transport() -> QtSoundTransport:
    return QtSoundTransport(qsoundeffect_cls=QSE, url_factory=lambda p: p,
                            pcm_sink_factory=None)


def test_silent_qse_start_is_retired_after_startup_grace(tmp_path):
    transport = _qse_transport()
    path = _wav(tmp_path)
    QSE.behavior = "silent"

    first = transport.play(path, token="silent")
    assert first
    with transport._lock:
        transport._effect_start_deadline[first] = 0.0
    second = transport.play(path, token="after-silence")

    assert second
    assert len(transport.active_handles()) == 1
    assert QSE.created[0].stop_calls >= 1


def test_delayed_qse_start_survives_next_request(tmp_path):
    transport = _qse_transport()
    path = _wav(tmp_path)
    QSE.behavior = "delayed"

    first = transport.play(path, token="delayed")
    second = transport.play(path, token="during-startup")

    assert first and second
    assert len(transport.active_handles()) == 2
    QSE.created[0].begin()
    assert len(transport.active_handles()) == 2


def test_qse_watchdog_retires_silent_backend_without_queue_poison(tmp_path):
    timers = []

    def watchdog_factory(_delay, callback):
        timer = _ManualTimer(callback)
        timers.append(timer)
        return timer

    transport = QtSoundTransport(qsoundeffect_cls=QSE,
                                  url_factory=lambda p: p,
                                  pcm_sink_factory=None,
                                  effect_watchdog_factory=watchdog_factory)
    hub = AudioHub(transport=transport)
    path = _wav(tmp_path)
    QSE.behavior = "silent"

    first = hub.play_result(path, event="click", bus=Bus.UI)
    assert first.outcome in (Outcome.PLAYED, Outcome.MIXED)
    timers[0].fire()

    assert transport.active_handles() == []
    assert hub.provenance()[-1]["reason"] == StopReason.SOURCE_NOT_PLAYING.value
    QSE.behavior = "healthy"
    second = hub.play_result(path, event="click", bus=Bus.UI)
    assert second.outcome in (Outcome.PLAYED, Outcome.MIXED)


def test_synchronous_qse_error_never_leaves_phantom_hub_channel(tmp_path):
    transport = _qse_transport()
    hub = AudioHub(transport=transport)
    path = _wav(tmp_path)
    QSE.synchronous_error = True

    result = hub.play_result(path, event="click", bus=Bus.UI)

    assert result.outcome is Outcome.STOPPED
    assert not result.channel
    assert transport.active_handles() == []
    assert hub.active_channels() == []
    assert [entry["reason"] for entry in hub.provenance()
            if entry["outcome"] == "STOPPED"] == [StopReason.SOURCE_ERROR.value]


def test_qse_device_error_is_failure_then_future_play_recovers(tmp_path):
    transport = _qse_transport()
    hub = AudioHub(transport=transport)
    path = _wav(tmp_path)

    first = hub.play_result(path, event="click", bus=Bus.UI)
    assert first.outcome in (Outcome.PLAYED, Outcome.MIXED)
    QSE.created[0].die()

    assert transport.active_handles() == []
    assert hub.provenance()[-1]["reason"] == StopReason.SOURCE_ERROR.value
    assert transport.take_failure(first.request_id) is None

    QSE.behavior = "healthy"
    second = hub.play_result(path, event="click", bus=Bus.UI)
    assert second.outcome in (Outcome.PLAYED, Outcome.MIXED)


def test_qse_start_exception_retires_effect_and_does_not_poison_pool(tmp_path):
    transport = _qse_transport()
    path = _wav(tmp_path)
    QSE.behavior = "raise"
    QSE.raise_once = True

    assert transport.play(path, token="boom") == ""
    assert transport.active_handles() == []
    assert transport.pool_cardinality() == (0, 0)
    assert QSE.created[0].stop_calls >= 1
    assert QSE.created[0].delete_calls >= 1

    QSE.behavior = "healthy"
    assert transport.play(path, token="after-boom")


def _shell_manager(transport) -> SoundManager:
    manager = SoundManager.__new__(SoundManager)
    manager._data = {"sound_events": {}}
    manager._data_id = id(manager._data)
    manager._sounds_dir = ""
    manager._provenance = deque(maxlen=256)
    manager._transport_trace = deque(maxlen=256)
    manager._request_seq = 0
    manager._closed = False
    manager._current = None
    manager._pending = deque()
    manager._players = {}
    manager._short_player = None
    manager._worker = None
    manager._scaled_cache = {}
    manager._poll_timer = _ManualTimer(lambda: None)
    manager._qt_seen_playing = False
    manager._starting = False
    manager._finished = deque(maxlen=256)
    manager._hub = AudioHub(transport=transport)
    manager._record = lambda request, outcome: manager._provenance.append(
        dict(request, outcome=outcome))
    manager._trace_transport = lambda *args, **kwargs: None
    manager._play_winsound = lambda *args, **kwargs: True
    manager._hub_degraded = False
    return manager


def test_rich_backend_failure_degrades_once_then_recovers_without_duplicate():
    transport = FailingOnceTransport()
    manager = _shell_manager(transport)
    fallback_calls = []
    manager._start_request = lambda request, force_winsound=False: (
        fallback_calls.append((request, force_winsound)) or True
    )

    def request(token):
        return {
            "id": token, "event": "click", "path": "cue.wav",
            "volume": 1.0, "policy": "STACK_SHORT", "source": "test",
            "dedupe_key": None, "profile": manager._data_id, "silo": None,
            "requested_at": 0.0,
        }

    assert manager._start_request_hub(request("first"))
    assert transport.recoveries == 1
    assert len(fallback_calls) == 1
    assert fallback_calls[0][1] is True
    assert manager._hub_degraded is True
    direct = manager._hub.play_result("cue.wav", event="direct", bus=Bus.VOICE)
    sequence = manager._hub.play_sequence(["one.wav", "two.wav"], bus=Bus.VOICE)
    channel = manager._hub.start_channel("bed.wav", bus=Bus.AMBIENCE)
    assert direct.outcome is Outcome.STOPPED
    assert sequence.cancelled
    assert channel.outcome is Outcome.STOPPED
    assert [
        entry["reason"] for entry in manager._hub.provenance()[-3:]
    ] == [StopReason.LEGACY_FALLBACK_ACTIVE.value] * 3
    assert transport.calls == 0
    assert manager._start_request_hub(request("second"))
    assert len(fallback_calls) == 1
    assert transport.calls == 1
    assert manager._hub_degraded is False


def test_legacy_owner_arms_before_transport_recovery_returns():
    transport = FailingOnceTransport()
    manager = _shell_manager(transport)
    fallback_calls = []
    manager._start_request = lambda request, force_winsound=False: (
        fallback_calls.append((request, force_winsound)) or True
    )
    original_recover = manager._hub.recover
    probes = []

    def recover_then_probe(reason):
        original_recover(reason)
        probes.append(manager._hub.play_result(
            "cue.wav", event="direct-after-recover", bus=Bus.VOICE))

    manager._hub.recover = recover_then_probe
    request = {
        "id": "race", "event": "click", "path": "cue.wav",
        "volume": 1.0, "policy": "STACK_SHORT", "source": "test",
        "dedupe_key": None, "profile": manager._data_id, "silo": None,
        "requested_at": 0.0,
    }

    assert manager._start_request_hub(request)
    assert len(fallback_calls) == 1
    assert fallback_calls[0][1] is True
    assert len(probes) == 1
    assert probes[0].outcome is Outcome.STOPPED
    assert manager._hub.provenance()[-1]["reason"] == (
        StopReason.LEGACY_FALLBACK_ACTIVE.value)
    assert transport.calls == 0


def test_short_winsound_fallback_keeps_owner_until_duration(monkeypatch):
    transport = FailingOnceTransport()
    manager = _shell_manager(transport)
    monkeypatch.setattr(sound_manager_module, "QSoundEffect", None)
    monkeypatch.setattr(
        sound_manager_module, "_wav_duration_ms", lambda _path: 10_000)

    manager._start_request_hub(_fallback_request("first"))
    manager._start_request_hub(_fallback_request("second"))

    assert transport.calls == 0
    assert manager._current is not None
    assert manager._current["id"] == "second"


def test_fallback_duration_completes_while_long_worker_exists(monkeypatch):
    clock = [100.0]
    monkeypatch.setattr(sound_manager_module.time, "monotonic", lambda: clock[0])
    manager = _shell_manager(RecordingTransport())
    manager._current = _fallback_request("fallback")
    manager._current["fallback_until"] = 105.0
    manager._worker = sound_manager_module._SerialWavWorker(
        lambda *_args: True)

    clock[0] = 106.0
    manager._poll_transport()

    assert manager._current is None
    manager._worker.close()
    manager._worker.thread.join(5)


def test_legacy_worker_stop_always_follows_dispatched_wav():
    trace_started = threading.Event()
    release = threading.Event()
    device_order = []

    def trace(operation, request=None, reason=None):
        if operation == "START_WAV":
            trace_started.set()
            assert release.wait(5)

    def play(*args):
        device_order.append(("start", args[0]))
        return True

    worker = sound_manager_module._SerialWavWorker(play, trace=trace)
    worker.submit((1, "stale.wav", 1.0, {}, True))
    assert trace_started.wait(5)

    def stop():
        worker.drop_pending()
        device_order.append(("stop", None))

    stopper = threading.Thread(target=stop)
    stopper.start()
    release.set()
    worker.close()
    worker.thread.join(5)
    stopper.join(5)

    assert not worker.thread.is_alive()
    assert not stopper.is_alive()
    assert device_order == [("stop", None)]


def _fallback_request(token):
    return {
        "id": token, "event": "click", "path": "cue.wav",
        "volume": 1.0, "policy": "STACK_SHORT", "source": "test",
        "dedupe_key": None, "profile": 1, "silo": None,
        "requested_at": 0.0,
    }


def test_synchronous_completion_advances_queue_and_sequence():
    transport = RecordingTransport()
    hub = AudioHub(transport=transport)
    original_play = transport.play
    first_play = True

    def play(path, *, volume=1.0, loop=False, on_complete=None, token=""):
        nonlocal first_play
        handle = original_play(path, volume=volume, loop=loop,
                               on_complete=on_complete, token=token)
        if on_complete is not None and first_play:
            first_play = False
            on_complete()
        return handle

    transport.play = play
    first = hub.play_result("cue.wav", event="first", bus=Bus.UI)
    queued = hub.play_result("cue.wav", event="next", bus=Bus.UI, mode="queue")
    sequence = hub.play_sequence(["one.wav", "two.wav"], bus=Bus.VOICE,
                                mode="queue")

    assert first.outcome in (Outcome.PLAYED, Outcome.MIXED)
    assert queued.outcome is Outcome.QUEUED
    assert sequence.started is True
    assert transport.calls >= 2


def test_hub_records_backend_exception_instead_of_raising():
    transport = RecordingTransport(explode=True)
    hub = AudioHub(transport=transport)

    result = hub.play_result("cue.wav", event="click", bus=Bus.UI)

    assert result.outcome is Outcome.STOPPED
    assert hub.provenance()[-1]["reason"] == "BACKEND_EXCEPTION"


def test_transport_swap_closes_old_backend():
    old = RecordingTransport()
    new = RecordingTransport()
    hub = AudioHub(transport=old)
    hub.play_result("cue.wav", event="click", bus=Bus.UI)

    hub.set_transport(new)

    assert old.closed == 1
    assert old.channels == {}


def test_hub_close_is_terminal_for_play_and_preload():
    transport = RecordingTransport()
    hub = AudioHub(transport=transport)
    hub.close()

    result = hub.play_result("cue.wav", event="click", bus=Bus.UI)
    hub.preload(["cue.wav"])

    assert result.outcome is Outcome.STOPPED
    assert transport.calls == 0
    assert hub.provenance()[-1]["reason"] == StopReason.TRANSPORT_UNAVAILABLE.value


def test_unknown_device_rate_is_retried_after_endpoint_returns(monkeypatch):
    from PyQt6.QtMultimedia import QMediaDevices

    class Format:
        def sampleRate(self):
            return 48000

    class Device:
        def preferredFormat(self):
            return Format()

    calls = []

    def default_output():
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("endpoint asleep")
        return Device()

    monkeypatch.setattr(audio_render, "_device_rate_cache", audio_render._MISSING)
    monkeypatch.setattr(QMediaDevices, "defaultAudioOutput", staticmethod(default_output))
    assert audio_render.device_sample_rate() is None
    assert audio_render.device_sample_rate() == 48000


def test_output_device_change_clears_rate_and_resolved_source_cache(tmp_path):
    transport = _qse_transport()
    path = _wav(tmp_path)
    transport.play(path, token="before-device-change")
    assert transport._resolved
    audio_render._device_rate_cache = 44100

    transport._on_audio_outputs_changed()

    assert audio_render._device_rate_cache is audio_render._MISSING
    assert transport._resolved == {}


def test_close_race_never_registers_a_voice_after_snapshot(tmp_path):
    factory = _SinkFactory()
    transport = QtSoundTransport(qsoundeffect_cls=QSE,
                                  url_factory=lambda p: p,
                                  pcm_sink_factory=factory)
    path = _wav(tmp_path)
    result = []

    def play() -> None:
        result.append(transport.play(path, token="racing"))

    worker = threading.Thread(target=play)
    worker.start()
    assert factory.entered.wait(5)
    transport.close()
    factory.release.set()
    worker.join(5)

    assert not worker.is_alive()
    assert result == [""]
    assert transport.active_handles() == []
    assert factory.retired


def test_close_during_volume_admission_never_starts_retired_sink(tmp_path):
    factory = _SinkFactory()
    factory.release.set()
    factory.block_set_volume = True
    transport = QtSoundTransport(qsoundeffect_cls=QSE,
                                  url_factory=lambda p: p,
                                  pcm_sink_factory=factory)
    result = []
    worker = threading.Thread(
        target=lambda: result.append(
            transport.play(_wav(tmp_path), token="volume-race")))
    worker.start()

    assert factory.set_volume_entered.wait(5)
    transport.close()
    factory.release_set_volume.set()
    worker.join(5)

    assert not worker.is_alive()
    assert result == [""]
    assert transport.active_handles() == []
    assert factory.sinks[0].state() is _SinkState.Stopped
    assert factory.sinks[0].calls[-1] == "stop"


def test_synchronous_pcm_idle_delivers_callback_without_phantom(tmp_path):
    factory = _SinkFactory()
    factory.release.set()
    factory.sync_idle = True
    transport = QtSoundTransport(qsoundeffect_cls=QSE,
                                  url_factory=lambda p: p,
                                  pcm_sink_factory=factory)
    completed = []
    handle = transport.play(_wav(tmp_path), token="sync-idle",
                            on_complete=lambda: completed.append(True))

    assert handle == ""
    assert completed == [True]
    assert transport.active_handles() == []
    assert transport.take_failure("sync-idle") is None


def test_repeated_logical_idle_and_churn_keeps_future_playback_available(tmp_path):
    factory = _SinkFactory()
    factory.release.set()
    transport = QtSoundTransport(qsoundeffect_cls=QSE,
                                  url_factory=lambda p: p,
                                  pcm_sink_factory=factory)
    path = _wav(tmp_path)
    for index in range(200):
        assert transport.play(path, token=f"idle-{index}")
        factory.sinks[-1].stateChanged.emit(_SinkState.Idle)
    assert transport.play(path, token="after-churn")
    assert len(transport.playback_trace()) <= QtSoundTransport.PLAYBACK_TRACE_CAPACITY
    assert len(transport.retirement_trace()) <= QtSoundTransport.PLAYBACK_TRACE_CAPACITY
