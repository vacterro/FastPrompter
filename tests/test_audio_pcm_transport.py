"""T-1242 P0: temporal integrity + source fidelity of the transient path.

Real-Windows evidence (WASAPI loopback capture, Qt 6.11.1, built-in Space
blip): QSoundEffect -- pooled AND fresh -- dropped the last ~42.5 ms of every
cue and emitted that tail ~42.5 ms BEFORE the next cue.  Transient cues now
play through one fresh QAudioSink per cue fed the exact PCM frames.  These
tests pin the transport contract with a fake sink factory (no device opens):

* a handle means physical playback was requested NOW -- nothing is ever held
  back to start later (Loading is refused, a late Ready replays nothing);
* one accepted cue = one fresh sink = one physical start = one retirement;
* stop / stop_all / REPLACE / invalidation / close leave no playback
  authority behind, so no late signal can make a sound;
* the frames handed to the sink are the file's frames, byte for byte.
"""

from __future__ import annotations

import hashlib
import os
import struct
import sys
import wave
from enum import Enum

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

from fastprompter.core import audio_hub, audio_render  # noqa: E402
from fastprompter.core.audio_hub import (  # noqa: E402
    PCM_POSTROLL_MS,
    AudioHub,
    Bus,
    Outcome,
    PlaybackMode,
    QtSoundTransport,
    SinkRefused,
    StopReason,
    read_pcm_wav,
)

SPACE_SHA256 = "6d2e35cac2c03acf4607bfc51027f918e4019d6fa985e311ba374109b453da9d"


# --------------------------------------------------------------------------
# fakes
# --------------------------------------------------------------------------

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


class State(Enum):
    ActiveState = 0
    SuspendedState = 1
    StoppedState = 2
    IdleState = 3


class Err(Enum):
    NoError = 0
    OpenError = 1
    IOError = 2
    UnderrunError = 3
    FatalError = 4


class FakeSink:
    def __init__(self, pcm, buffer: bytes, factory) -> None:
        self.pcm = pcm
        self.buffer = buffer
        self.factory = factory
        self.stateChanged = _Signal()
        self.volume = None
        self._state = State.StoppedState
        self._error = Err.NoError
        self.start_calls = 0
        self.stop_calls = 0
        self.calls: list[str] = []

    def setVolume(self, value) -> None:
        self.volume = float(value)

    def start(self, _buffer) -> None:
        self.start_calls += 1
        self.factory.physical_starts += 1
        if self.factory.fail_start or self.factory.fail_starts > 0:
            self.factory.fail_starts = max(0, self.factory.fail_starts - 1)
            self._error = Err.OpenError
            self._state = State.StoppedState
            self.stateChanged.emit(self._state)
            return
        self._state = State.ActiveState
        self.stateChanged.emit(self._state)

    def reset(self) -> None:
        # Qt: drop the read-ahead buffer (real QAudioSink.stop() does not)
        self.calls.append("reset")

    def stop(self) -> None:
        self.calls.append("stop")
        self.stop_calls += 1
        if self._state is not State.StoppedState:
            self._state = State.StoppedState
            self.stateChanged.emit(self._state)

    def state(self):
        return self._state

    def error(self):
        return self._error

    # -- test helpers -------------------------------------------------------
    def drain(self) -> None:
        """The device consumed everything: Qt reports Idle."""
        self._state = State.IdleState
        self.stateChanged.emit(self._state)

    def die(self) -> None:
        self._error = Err.FatalError
        self._state = State.StoppedState
        self.stateChanged.emit(self._state)


class FakeTimer:
    def __init__(self, callback) -> None:
        self.callback = callback
        self.stopped = False

    def stop(self) -> None:
        self.stopped = True

    def fire(self) -> None:
        if not self.stopped:
            self.callback()


class FakeSinkFactory:
    def __init__(self) -> None:
        self.sinks: list[FakeSink] = []
        self.retired: list[FakeSink] = []
        self.timers: list[FakeTimer] = []
        self.physical_starts = 0
        self.fail_start = False
        self.fail_starts = 0
        self.refuse: StopReason | None = None

    def open(self, pcm, postroll_ms):
        if self.refuse is not None:
            raise SinkRefused(self.refuse, "fake")
        sink = FakeSink(pcm, pcm.data + pcm.silence(postroll_ms), self)
        self.sinks.append(sink)
        return sink, sink.buffer

    def watchdog(self, _sink, _ms, callback):
        timer = FakeTimer(callback)
        self.timers.append(timer)
        return timer

    def retire(self, sink) -> None:
        self.retired.append(sink)

    @staticmethod
    def state_name(state) -> str:
        return getattr(state, "name", str(state))

    @staticmethod
    def error_name(sink) -> str:
        return sink.error().name


class FakeEffect:
    """Enough QSoundEffect for the loop / fallback path."""

    class Loop:
        Infinite = -2

    class Status:
        Null = 0
        Loading = 1
        Ready = 2
        Error = 3

    playingChanged = None
    statusChanged = None
    made: list = []

    def __init__(self) -> None:
        self._status = FakeEffect.Status.Loading
        self._playing = False
        self.play_calls = 0
        self.playingChanged = _Signal()
        self.statusChanged = _Signal()
        FakeEffect.made.append(self)

    def setSource(self, _url):
        pass

    def setVolume(self, _v):
        pass

    def setLoopCount(self, _n):
        pass

    def status(self):
        return self._status

    def isPlaying(self):
        return self._playing

    def play(self):
        self.play_calls += 1
        self._playing = True
        self.playingChanged.emit()

    def stop(self):
        if self._playing:
            self._playing = False
            self.playingChanged.emit()

    def become(self, status):
        self._status = status
        self.statusChanged.emit()


@pytest.fixture(autouse=True)
def _raw_policy(monkeypatch):
    # RAW is the product default and the fidelity reference.
    monkeypatch.setattr(audio_render, "_render_enabled", False)
    monkeypatch.setattr(audio_render, "_edge_pad_enabled", False)
    FakeEffect.made = []


@pytest.fixture
def sinks():
    return FakeSinkFactory()


@pytest.fixture
def transport(sinks):
    return QtSoundTransport(qsoundeffect_cls=FakeEffect,
                            url_factory=lambda p: p, pcm_sink_factory=sinks)


def _wav(tmp_path, name="cue.wav", *, rate=44100, channels=2, width=2,
         frames=2205, payload=None) -> str:
    path = tmp_path / name
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(width)
        wf.setframerate(rate)
        if payload is None:
            payload = bytes((i * 37) & 0xFF for i in range(frames * channels * width))
        wf.writeframes(payload)
    return str(path)


def _starts(transport, token=None):
    return [e for e in transport.playback_trace()
            if e.get("event") == "pcm_start"
            and (token is None or e.get("token") == token)]


# --------------------------------------------------------------------------
# exact PCM
# --------------------------------------------------------------------------

class TestExactPcm:
    def test_int16_frames_are_the_files_frames(self, tmp_path):
        path = _wav(tmp_path)
        with wave.open(path, "rb") as wf:
            frames = wf.readframes(wf.getnframes())
        pcm = read_pcm_wav(path)
        assert pcm.data == frames
        assert (pcm.rate, pcm.channels, pcm.sample_format) == (44100, 2, "s16")
        assert pcm.frames == 2205

    def test_24bit_is_widened_exactly(self, tmp_path):
        samples = [0, 1, -1, 8388607, -8388608, 123456]
        payload = b"".join(s.to_bytes(3, "little", signed=True) for s in samples)
        path = _wav(tmp_path, "w24.wav", channels=1, width=3, payload=payload)
        pcm = read_pcm_wav(path)
        assert pcm.sample_format == "s32" and pcm.source_bits == 24
        widened = struct.unpack(f"<{len(samples)}i", pcm.data)
        assert list(widened) == [s << 8 for s in samples]

    def test_float32_extensible_is_carried_as_float(self, tmp_path):
        data = struct.pack("<4f", 0.0, 0.5, -0.5, 1.0)
        fmt = struct.pack("<HHIIHH", 0xFFFE, 1, 48000, 48000 * 4, 4, 32)
        fmt += struct.pack("<HHI", 22, 32, 4) + struct.pack("<H", 3) + b"\x00" * 14
        body = b"WAVE" + b"fmt " + struct.pack("<I", len(fmt)) + fmt
        body += b"data" + struct.pack("<I", len(data)) + data
        path = tmp_path / "f32.wav"
        path.write_bytes(b"RIFF" + struct.pack("<I", len(body)) + body)
        pcm = read_pcm_wav(str(path))
        assert pcm.sample_format == "f32" and pcm.data == data

    def test_u8_postroll_is_unsigned_silence(self, tmp_path):
        pcm = read_pcm_wav(_wav(tmp_path, "u8.wav", channels=1, width=1,
                                rate=8000))
        assert pcm.silence(10) == b"\x80" * 80

    def test_the_sink_buffer_is_exact_frames_then_silence(self, transport,
                                                          sinks, tmp_path):
        path = _wav(tmp_path)
        assert transport.play(path, token="t")
        pcm = read_pcm_wav(path)
        buf = sinks.sinks[0].buffer
        assert buf[:len(pcm.data)] == pcm.data
        tail = buf[len(pcm.data):]
        assert tail == b"\x00" * len(tail)
        assert len(tail) == 44100 * PCM_POSTROLL_MS // 1000 * 4

    def test_not_a_wav_is_none(self, tmp_path):
        path = tmp_path / "x.wav"
        path.write_bytes(b"ID3 not a riff file at all")
        assert read_pcm_wav(str(path)) is None


# --------------------------------------------------------------------------
# A/B/C/D/E: nothing starts late
# --------------------------------------------------------------------------

class TestNoDeferredStart:
    def test_A_loading_is_refused_with_no_played_channel(self, tmp_path):
        effect_transport = QtSoundTransport(qsoundeffect_cls=FakeEffect,
                                            url_factory=lambda p: p,
                                            pcm_sink_factory=None)
        hub = AudioHub(transport=effect_transport)
        result = hub.play_result(_wav(tmp_path), event="problip_cue",
                                 bus=Bus.PROBLIP)
        assert result.outcome is Outcome.STOPPED and result.channel == ""
        assert hub.active_channels() == []
        assert hub.provenance()[-1]["reason"] == StopReason.SOURCE_LOADING.value
        assert not hasattr(effect_transport, "_pending")

    def test_B_and_C_late_ready_never_starts_the_old_cue(self, tmp_path):
        effect_transport = QtSoundTransport(qsoundeffect_cls=FakeEffect,
                                            url_factory=lambda p: p,
                                            pcm_sink_factory=None)
        hub = AudioHub(transport=effect_transport)
        path_a, path_b = _wav(tmp_path, "a.wav"), _wav(tmp_path, "b.wav")
        effect_transport.preload([path_b])
        FakeEffect.made[0].become(FakeEffect.Status.Ready)
        assert hub.play(path_a, event="a").value == "STOPPED"   # A Loading
        effect_a = FakeEffect.made[1]
        assert hub.play(path_b, event="b") in (Outcome.PLAYED, Outcome.MIXED)
        effect_a.become(FakeEffect.Status.Ready)                  # A late
        assert effect_a.play_calls == 0

    @pytest.mark.parametrize("action", ["stop_all", "invalidate", "close"])
    def test_D_E_G_H_no_late_ready_after_silence(self, tmp_path, action):
        effect_transport = QtSoundTransport(qsoundeffect_cls=FakeEffect,
                                            url_factory=lambda p: p,
                                            pcm_sink_factory=None)
        effect_transport.play(_wav(tmp_path), token="r")
        {"stop_all": effect_transport.stop_all,
         "invalidate": effect_transport.invalidate_sources,
         "close": effect_transport.close}[action]()
        FakeEffect.made[0].become(FakeEffect.Status.Ready)
        assert FakeEffect.made[0].play_calls == 0
        assert effect_transport.active_handles() == []


# --------------------------------------------------------------------------
# I/J/K: one fresh sink per accepted cue, retired on completion
# --------------------------------------------------------------------------

class TestFreshSinkLifecycle:
    def test_I_each_accepted_cue_gets_its_own_sink(self, transport, sinks,
                                                   tmp_path):
        path = _wav(tmp_path)
        handles = [transport.play(path, token=f"r{i}") for i in range(3)]
        assert len(set(handles)) == 3 and all(handles)
        assert len(sinks.sinks) == 3
        assert len({id(s) for s in sinks.sinks}) == 3
        assert [s.start_calls for s in sinks.sinks] == [1, 1, 1]

    def test_J_drained_sink_retires_and_completes_once(self, transport, sinks,
                                                       tmp_path):
        done = []
        handle = transport.play(_wav(tmp_path), token="r",
                                on_complete=lambda: done.append(1))
        sink = sinks.sinks[0]
        sink.drain()
        assert done == [1]
        assert sinks.retired == [sink] and sink.stop_calls == 1
        assert transport.active_handles() == []
        sink.drain()                      # a stale second Idle
        sinks.timers[0].fire()            # a stale watchdog
        assert done == [1]
        finish = [e for e in transport.playback_trace()
                  if e["event"] == "pcm_finish"]
        assert [(e["handle"], e["reason"]) for e in finish] == [(handle, "drained")]

    def test_K_100_sequential_plays_start_exactly_once_each(self, transport,
                                                           sinks, tmp_path):
        hub = AudioHub(transport=transport)
        path = _wav(tmp_path)
        for index in range(100):
            result = hub.play_result(path, event="problip_cue",
                                     bus=Bus.PROBLIP)
            assert result.outcome is Outcome.PLAYED, index
            sinks.sinks[-1].drain()
        assert sinks.physical_starts == 100
        assert len(sinks.retired) == 100
        assert hub.active_channel_count() == 0
        assert transport.active_handles() == []
        starts = _starts(transport)
        tokens = [e["token"] for e in starts]
        assert len(tokens) == len(set(tokens))       # zero duplicated starts
        for entry in starts:
            assert entry["t_request"] <= entry["t_start"]

    def test_watchdog_retires_a_sink_that_never_drains(self, transport, sinks,
                                                       tmp_path):
        done = []
        transport.play(_wav(tmp_path), on_complete=lambda: done.append(1))
        sinks.timers[0].fire()
        assert done == [1] and transport.active_handles() == []

    def test_a_dying_device_completes_so_queues_advance(self, transport, sinks,
                                                        tmp_path):
        done = []
        transport.play(_wav(tmp_path), on_complete=lambda: done.append(1))
        sinks.sinks[0].die()
        assert done == [1] and transport.active_handles() == []


# --------------------------------------------------------------------------
# F/G/H: stop, stop_all, REPLACE, invalidation, close
# --------------------------------------------------------------------------

class TestNoLatentAuthority:
    def test_stop_is_silent_and_final(self, transport, sinks, tmp_path):
        done = []
        handle = transport.play(_wav(tmp_path), on_complete=lambda: done.append(1))
        transport.stop(handle)
        sink = sinks.sinks[0]
        assert sink.stop_calls == 1 and sinks.retired == [sink]
        # the read-ahead is dropped BEFORE the stop, or it keeps sounding
        assert sink.calls == ["reset", "stop"]
        sink.drain()
        sinks.timers[0].fire()
        assert done == [], "a stopped channel's completion must never fire"

    @pytest.mark.parametrize("action", ["stop_all", "invalidate_sources", "close"])
    def test_every_silence_path_retires_every_voice(self, transport, sinks,
                                                    tmp_path, action):
        path = _wav(tmp_path)
        done = []
        for i in range(3):
            transport.play(path, token=f"r{i}", on_complete=lambda: done.append(1))
        getattr(transport, action)()
        assert transport.active_handles() == []
        assert len(sinks.retired) == 3
        assert all(s.calls == ["reset", "stop"] for s in sinks.sinks)
        for sink in sinks.sinks:
            sink.drain()
        assert done == []

    def test_close_refuses_every_later_play(self, transport, sinks, tmp_path):
        transport.close()
        assert transport.play(_wav(tmp_path), token="late") == ""
        assert transport.take_failure("late")["reason"] == \
            StopReason.TRANSPORT_UNAVAILABLE.value
        assert sinks.sinks == []

    def test_F_Q_replace_stops_only_physically_active_channels(
            self, transport, sinks, tmp_path):
        hub = AudioHub(transport=transport)
        path = _wav(tmp_path)
        first = hub.play_result(path, event="a", bus=Bus.UI, mode="replace")
        assert first.outcome is Outcome.REPLACED
        # a refused start in between never becomes a channel to replace
        sinks.refuse = StopReason.TRANSPORT_UNAVAILABLE
        refused = hub.play_result(path, event="b", bus=Bus.UI, mode="mix")
        assert refused.outcome is Outcome.STOPPED
        sinks.refuse = None
        second = hub.play_result(path, event="c", bus=Bus.UI, mode="replace")
        assert second.outcome is Outcome.REPLACED
        assert sinks.retired == [sinks.sinks[0]]
        sinks.sinks[0].drain()                     # the replaced cue's tail
        assert [c["request_id"] for c in hub.active_channels()] == \
            [second.request_id]

    def test_hub_close_closes_the_transport(self, transport, sinks, tmp_path):
        hub = AudioHub(transport=transport)
        hub.play(_wav(tmp_path), event="a")
        hub.close()
        assert transport.active_handles() == [] and hub.active_channel_count() == 0
        assert hub.play(_wav(tmp_path, "b.wav"), event="b") is Outcome.STOPPED


# --------------------------------------------------------------------------
# truthful refusals: O/P and device errors
# --------------------------------------------------------------------------

class TestTruthfulRefusal:
    def test_device_start_error_is_not_a_played_channel(self, transport,
                                                       sinks, tmp_path):
        sinks.fail_start = True
        hub = AudioHub(transport=transport)
        result = hub.play_result(_wav(tmp_path), event="x", bus=Bus.ALERT)
        assert result.outcome is Outcome.STOPPED
        entry = hub.provenance()[-1]
        assert entry["reason"] == StopReason.SOURCE_ERROR.value
        assert entry["error"] == "OpenError"
        assert hub.active_channels() == [] and transport.active_handles() == []
        assert sinks.retired == [sinks.sinks[0]]

    def test_O_refused_queue_job_leaves_no_phantom_channel(self, transport,
                                                           sinks, tmp_path):
        hub = AudioHub(transport=transport)
        path = _wav(tmp_path)
        first = hub.play_result(path, event="a", bus=Bus.UI, mode="queue")
        assert first.outcome is Outcome.QUEUED and hub.active_channel_count() == 1
        hub.play_result(path, event="b", bus=Bus.UI, mode="queue")
        hub.play_result(path, event="c", bus=Bus.UI, mode="queue")
        last = hub.play_result(path, event="d", bus=Bus.UI, mode="queue")
        assert hub.queue_depth() == 3
        sinks.fail_starts = 2            # b and c will be refused by the device
        sinks.sinks[0].drain()           # a finishes -> b, c refuse -> d plays
        # the refused jobs never became channels (no phantom blocks the FIFO)
        assert [c["request_id"] for c in hub.active_channels()] == \
            [last.request_id]
        assert hub.queue_depth() == 0
        assert sinks.physical_starts == 4

    def test_P_refused_alert_never_makes_skip_busy_stand_down(
            self, transport, sinks, tmp_path):
        hub = AudioHub(transport=transport)
        path = _wav(tmp_path)
        sinks.fail_start = True
        assert hub.play(path, event="alarm", bus=Bus.ALERT) is Outcome.STOPPED
        sinks.fail_start = False
        cue = hub.play(path, event="problip_cue", bus=Bus.PROBLIP,
                       mode=PlaybackMode.SKIP_BUSY)
        assert cue is Outcome.PLAYED

    def test_unsupported_format_falls_back_with_provenance(self, transport,
                                                           sinks, tmp_path):
        sinks.refuse = StopReason.UNSUPPORTED_FORMAT
        path = _wav(tmp_path)
        assert transport.play(path, token="r") == ""       # QSE is Loading
        assert any(e["event"] == "pcm_fallback" for e in transport.playback_trace())

    def test_L_hub_voice_cap_bounds_live_sinks(self, transport, sinks,
                                               tmp_path):
        hub = AudioHub(transport=transport, max_voices=16)
        path = _wav(tmp_path)
        outcomes = [hub.play(path, event="problip_cue", bus=Bus.PROBLIP)
                    for _ in range(20)]
        assert outcomes.count(Outcome.DROPPED_CHANNEL_LIMIT) == 4
        live = [s for s in sinks.sinks if s not in sinks.retired]
        assert len(live) == 16 == len(transport.active_handles())

    def test_transport_hard_ceiling(self, transport, sinks, tmp_path):
        path = _wav(tmp_path)
        for i in range(audio_hub.MAX_PCM_VOICES):
            assert transport.play(path, token=f"r{i}")
        assert transport.play(path, token="over") == ""
        assert transport.take_failure("over")["reason"] == \
            StopReason.POOL_EXHAUSTED.value


# --------------------------------------------------------------------------
# M/N: RAW identity, volume, one start per Problip action
# --------------------------------------------------------------------------

class TestSourceIdentity:
    def test_M_raw_space_plays_its_own_file_unrendered(self, transport, sinks):
        from fastprompter.sound.problip.catalog import resolve_sound_path

        path = resolve_sound_path("sound_space")
        assert path and os.path.basename(path) == "blip_space.wav"
        with open(path, "rb") as fh:
            assert hashlib.sha256(fh.read()).hexdigest() == SPACE_SHA256
        handle = transport.play(path, volume=0.35, token="space")
        assert handle
        (start,) = _starts(transport, "space")
        assert start["logical"] == start["physical"] == path
        assert start["rendered"] is False
        assert start["format"] == "44100Hz/2ch/s16"
        assert start["frames"] == 22050
        # volume is amplitude on the transport; the frames stay the file's
        sink = sinks.sinks[0]
        assert sink.volume == pytest.approx(0.35)
        with wave.open(path, "rb") as wf:
            assert sink.buffer.startswith(wf.readframes(wf.getnframes()))

    def test_N_one_problip_test_is_one_physical_start(self, transport, sinks,
                                                      tmp_path):
        pytest.importorskip("PyQt6.QtWidgets")
        from PyQt6.QtCore import QObject
        from PyQt6.QtWidgets import QApplication

        from fastprompter.core.problip_store import ProblipStore
        from fastprompter.ui.problip_controller import ProblipController

        app = QApplication.instance() or QApplication([])
        assert app is not None
        hub = AudioHub(transport=transport)

        class _Manager:
            def audio_hub(self):
                return hub

            def stop_all_sound(self):
                hub.stop_all()

        parent = QObject()
        controller = ProblipController(
            parent, _Manager(), store=ProblipStore(str(tmp_path / "p.db")),
            random_source=lambda n: 0)
        try:
            controller.update_settings(selected_sound_ids=["sound_space"])
            ok, _name = controller.test()
            assert ok
            assert sinks.physical_starts == 1
            assert len(hub.provenance()) == 1
            (start,) = _starts(transport)
            assert os.path.basename(start["physical"]) == "blip_space.wav"
        finally:
            controller.shutdown()
