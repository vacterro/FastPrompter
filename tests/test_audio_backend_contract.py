"""T-1238-C0.1/C0.2 + E1.1: the REAL Qt transport contract.

``FakeMultiChannelTransport`` can hide defects in the packaged backend --
before this suite ``QtSoundTransport.stop()`` was ``pass`` and an exhausted
pool silently restarted an effect the hub still believed was audible.  These
tests drive the actual ``QtSoundTransport`` against a fake QSoundEffect so
the shipped backend is proven, not assumed.
"""

from __future__ import annotations

import os
import sys
import wave

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

from fastprompter.core.audio_hub import QtSoundTransport  # noqa: E402


class _Signal:
    """Minimal Qt-signal stand-in with real connect/emit semantics."""

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


class FakeQSoundEffect:
    """A QSoundEffect stand-in that honours the parts the transport uses."""

    class Loop:
        Infinite = -2

    # Class-level markers so the transport's capability probe passes.
    playingChanged = None

    created: list = []

    def __init__(self) -> None:
        self.source = None
        self.volume = 1.0
        self.loop_count = 1
        self.play_calls = 0
        self.stop_calls = 0
        self._playing = False
        self.playingChanged = _Signal()
        FakeQSoundEffect.created.append(self)

    # -- API the transport calls -------------------------------------------
    def setSource(self, url) -> None:
        self.source = url

    def setVolume(self, value) -> None:
        self.volume = float(value)

    def setLoopCount(self, count) -> None:
        self.loop_count = count

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

    # -- test helper --------------------------------------------------------
    def finish(self) -> None:
        """Simulate the WAV ending naturally."""
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
def transport():
    FakeQSoundEffect.created = []
    return QtSoundTransport(qsoundeffect_cls=FakeQSoundEffect,
                            url_factory=lambda p: f"file:///{p}")


class TestCapabilityProbe:
    def test_a_stand_in_without_the_loop_enum_is_refused(self):
        class Crippled:
            setSource = setVolume = setLoopCount = play = stop = None
            isPlaying = None
            playingChanged = None

        with pytest.raises(Exception):
            QtSoundTransport(qsoundeffect_cls=Crippled, url_factory=str)

    def test_real_binding_exposes_infinite_through_loop_enum(self):
        pytest.importorskip("PyQt6.QtMultimedia")
        from PyQt6.QtMultimedia import QSoundEffect

        # PyQt6 puts it on the nested Loop enum -- probing the class directly
        # is what silently degraded the whole product to NullTransport.
        assert hasattr(QSoundEffect.Loop, "Infinite")


class TestHandles:
    def test_each_play_returns_a_unique_handle(self, transport, tmp_path):
        a = _wav(tmp_path, "a.wav")
        h1 = transport.play(a)
        h2 = transport.play(a)
        assert h1 and h2 and h1 != h2
        assert sorted(transport.active_handles()) == sorted([h1, h2])

    def test_stop_stops_only_that_handle(self, transport, tmp_path):
        a = _wav(tmp_path, "a.wav")
        h1 = transport.play(a)
        h2 = transport.play(a)
        e1, e2 = FakeQSoundEffect.created[0], FakeQSoundEffect.created[1]
        transport.stop(h1)
        assert e1.stop_calls == 1 and e2.stop_calls == 0
        assert transport.active_handles() == [h2]

    def test_stop_all_stops_every_channel(self, transport, tmp_path):
        transport.play(_wav(tmp_path, "a.wav"))
        transport.play(_wav(tmp_path, "b.wav"))
        transport.stop_all()
        assert transport.active_handles() == []
        assert all(e.stop_calls >= 1 for e in FakeQSoundEffect.created)

    def test_natural_completion_removes_the_mapping_and_fires_once(
            self, transport, tmp_path):
        fired: list[int] = []
        handle = transport.play(_wav(tmp_path, "a.wav"),
                                on_complete=lambda: fired.append(1))
        assert transport.active_handles() == [handle]
        FakeQSoundEffect.created[0].finish()
        assert fired == [1]
        assert transport.active_handles() == []

    def test_stale_completion_after_explicit_stop_does_nothing(
            self, transport, tmp_path):
        """C0.1: no stale playingChanged may advance a queue after a stop."""
        fired: list[int] = []
        handle = transport.play(_wav(tmp_path, "a.wav"),
                                on_complete=lambda: fired.append(1))
        transport.stop(handle)
        FakeQSoundEffect.created[0].finish()  # a late signal from the device
        assert fired == []
        assert transport.active_handles() == []


class TestPool:
    def test_pool_exhaustion_refuses_instead_of_stealing(self, transport,
                                                         tmp_path):
        """C0.2: never restart an effect the hub still counts as audible."""
        path = _wav(tmp_path, "a.wav")
        handles = [transport.play(path)
                   for _ in range(QtSoundTransport.POOL_PER_PATH)]
        assert all(handles)
        refused = transport.play(path)
        assert refused == ""
        # No live effect was restarted behind the hub's back.
        assert all(e.play_calls == 1 for e in FakeQSoundEffect.created)
        assert len(transport.active_handles()) == QtSoundTransport.POOL_PER_PATH

    def test_a_finished_effect_is_reused(self, transport, tmp_path):
        path = _wav(tmp_path, "a.wav")
        transport.play(path)
        FakeQSoundEffect.created[0].finish()
        transport.play(path)
        assert len(FakeQSoundEffect.created) == 1  # reused, not reallocated


class TestLoopAndVolume:
    def test_loop_true_reaches_the_infinite_loop_count(self, transport,
                                                       tmp_path):
        transport.play(_wav(tmp_path, "a.wav"), loop=True)
        assert FakeQSoundEffect.created[0].loop_count is FakeQSoundEffect.Loop.Infinite

    def test_loop_false_plays_once(self, transport, tmp_path):
        transport.play(_wav(tmp_path, "a.wav"))
        assert FakeQSoundEffect.created[0].loop_count == 1

    def test_set_volume_reaches_the_actual_effect(self, transport, tmp_path):
        handle = transport.play(_wav(tmp_path, "a.wav"), volume=1.0)
        transport.set_volume(handle, 0.25)
        assert FakeQSoundEffect.created[0].volume == pytest.approx(0.25)

    def test_set_volume_on_a_stopped_channel_is_a_no_op(self, transport,
                                                        tmp_path):
        handle = transport.play(_wav(tmp_path, "a.wav"), volume=1.0)
        transport.stop(handle)
        transport.set_volume(handle, 0.1)
        assert FakeQSoundEffect.created[0].volume == pytest.approx(1.0)

    def test_missing_file_is_refused(self, transport, tmp_path):
        assert transport.play(str(tmp_path / "nope.wav")) == ""
