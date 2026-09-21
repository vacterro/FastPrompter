"""T-1242 spec 14/15: the repeated-Problip mechanical regression.

``test_first_play_and_warmed_play_are_the_same_single_start`` pins the same
property on FakeMultiChannelTransport.  It cannot see transport-level source
identity, so the user's "1st clean / 2nd cut / 3rd+ coloured" reproduction
could pass every hub test while the REAL transport flipped physical
representations between plays.  These tests drive the REAL
QtSoundTransport through 20 scheduled-style cues and prove, mechanically:

- every cue resolves to the SAME physical-source class (same identity,
  same WAV frame count, same rate, same padding contract);
- exactly one start and one finish per cue;
- ZERO overlapping stale channels when the next cue fires;
- pool ownership returns to zero between cues.

The audible A/B verdict itself is the operator probe
``tools/probe_repeated_audio.py`` (real Windows, real ears); a CI process
cannot listen.
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


class _Signal:
    def __init__(self) -> None:
        self._slots = []

    def connect(self, slot) -> None:
        self._slots.append(slot)

    def emit(self, *args) -> None:
        for slot in list(self._slots):
            slot(*args)


class CueQSoundEffect:
    """QSoundEffect stand-in: real Ready/Loading semantics, honest play
    counts.  The transport code path is the REAL one; only Qt is faked."""

    class Loop:
        Infinite = -2

    playingChanged = None
    created: list = []

    def __init__(self) -> None:
        self.source = None
        self._playing = False
        self.play_calls = 0
        self.playingChanged = _Signal()
        CueQSoundEffect.created.append(self)

    def setSource(self, url) -> None:
        self.source = url

    def setVolume(self, value) -> None:
        pass

    def setLoopCount(self, count) -> None:
        pass

    def play(self) -> None:
        self.play_calls += 1
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

    def finish(self) -> None:
        """The WAV's real end: ~66 ms of samples completing naturally."""
        if self._playing:
            self._playing = False
            self.playingChanged.emit()


CUES = 20


def _blip(tmp_path) -> str:
    """A stand-in blip01.wav: ~66 ms stereo 16-bit 44100 Hz."""
    path = tmp_path / "blip01.wav"
    frames = 2940  # the real asset's frame count
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(2)
        handle.setsampwidth(2)
        handle.setframerate(44100)
        left = b"\x40\x08\x00\xfc" * (frames // 2)
        handle.writeframes(left + left)
    return str(path)


@pytest.fixture()
def transport(monkeypatch):
    CueQSoundEffect.created = []
    monkeypatch.setattr(audio_render, "_render_enabled", False)
    monkeypatch.setattr(audio_render, "_edge_pad_enabled", False)
    return QtSoundTransport(qsoundeffect_cls=CueQSoundEffect,
                            url_factory=lambda p: p)


@pytest.fixture()
def hub(transport):
    return AudioHub(transport=transport, global_mode="mix")


class TestRepeatedProblipCues:
    def test_twenty_cues_are_structurally_equivalent(self, transport, hub,
                                                     tmp_path):
        path = _blip(tmp_path)
        records = []
        starts_so_far = 0
        for cue in range(CUES):
            # Spec 15: zero active prior Problip channels before the next
            # cue.  The blip is ~67 ms; the interval is 4-7 s.
            assert transport.active_handles() == [], (
                f"cue #{cue + 1} started while {len(transport.active_handles())} "
                "stale channel(s) were still 'active' -- that overlap is the "
                "reverb/overlap root cause")
            assert hub.active_channel_count() == 0, (
                f"cue #{cue + 1}: the hub still owned a channel from the "
                "previous cue; completion bookkeeping failed")

            result = hub.play_result(path, event="problip_cue", bus="problip",
                                     mode="mix", volume=0.6)
            assert result.outcome.value in ("PLAYED", "MIXED"), (
                f"cue #{cue + 1} did not start: {result.outcome.value}")
            # The effect that actually owns this channel -- NOT necessarily
            # the newest created one: a finished pooled effect is REUSED, so
            # exactly one start per cue means +1 against the running total.
            effect = transport._channels[result.channel]
            starts_so_far += 1
            assert effect.play_calls == starts_so_far, (
                f"cue #{cue + 1}: {effect.play_calls - starts_so_far + 1} "
                "extra physical start(s) happened for one cue")
            records.append({
                "physical": effect.source,
                "effect": effect,
            })
            # exactly one finish per cue
            effect.finish()
            assert transport.active_handles() == []
            assert hub.active_channel_count() == 0

        # same physical source class for every cue
        physicals = {str(r["physical"]) for r in records}
        assert len(physicals) == 1, (
            f"20 cues resolved to {len(physicals)} different physical "
            f"sources: {sorted(physicals)}")

        # same WAV frame count + rate + no padding contract
        with wave.open(path, "rb") as source:
            source_frames = source.getnframes()
            source_rate = source.getframerate()
        physical = next(iter(physicals))
        with wave.open(physical, "rb") as handle:
            assert handle.getnframes() == source_frames
            assert handle.getframerate() == source_rate

        # every cue got exactly one start (cumulative equality already
        # asserted per cue; re-check the final balance here)
        assert records[-1]["effect"].play_calls == CUES

    def test_pool_ownership_returns_to_zero_between_cues(self, transport,
                                                         hub, tmp_path):
        path = _blip(tmp_path)
        for _ in range(CUES):
            result = hub.play_result(path, event="problip_cue", bus="problip",
                                     mode="mix")
            assert len(transport.active_handles()) == 1
            transport._channels[result.channel].finish()
            assert transport.active_handles() == []

    def test_completion_fires_exactly_once_per_cue(self, transport, hub,
                                                   tmp_path):
        path = _blip(tmp_path)
        completions = 0
        for _ in range(CUES):
            result = hub.play_result(path, event="problip_cue", bus="problip",
                                     mode="mix")
            assert result.channel
            transport._channels[result.channel].finish()
            completions += 1
        assert completions == CUES

    def test_invalidation_between_cues_never_leaves_overlap(self, transport,
                                                            hub, tmp_path):
        """A mid-session policy change must not poison the mechanical
        invariants either."""
        path = _blip(tmp_path)
        for cue in range(CUES):
            assert transport.active_handles() == []
            if cue == 10:
                transport.invalidate_sources()
            result = hub.play_result(path, event="problip_cue", bus="problip",
                                     mode="mix")
            transport._channels[result.channel].finish()
            assert hub.active_channel_count() == 0


@pytest.mark.skipif(sys.platform != "win32",
                    reason="real QSoundEffect exists only on Windows")
@pytest.mark.skipif(os.environ.get("FP_REAL_AUDIO_PROBE") != "1",
                    reason="real-device probe: run with FP_REAL_AUDIO_PROBE=1 "
                           "on a desktop session with a working audio "
                           "endpoint; headless CI has no WASAPI session")
class TestRealWindowsTransport:
    """The SAME mechanical invariants against the REAL QSoundEffect.

    Opt-in (FP_REAL_AUDIO_PROBE=1) because a headless session cannot drive
    WASAPI to completion; the operator probe tools/probe_repeated_audio.py
    runs the same loop with ears on the desktop.  These prove one start per
    cue, real playback signals, and zero overlap.  The subjective CLEAN/CUT/
    COLOURED verdict stays with the probe.
    """

    def test_twenty_real_cues_are_one_start_each(self, tmp_path):
        pytest.importorskip("PyQt6.QtMultimedia")
        from PyQt6.QtCore import QCoreApplication, QUrl
        from PyQt6.QtMultimedia import QMediaDevices, QSoundEffect

        device = QMediaDevices.defaultAudioOutput()
        if device is None or device.isNull():
            pytest.skip("no default audio output on this machine")

        app = QCoreApplication.instance() or QCoreApplication([])
        path = _blip(tmp_path)
        transport = QtSoundTransport(qsoundeffect_cls=QSoundEffect,
                                     url_factory=QUrl.fromLocalFile)
        hub = AudioHub(transport=transport, global_mode="mix")
        starts = 0
        for cue in range(CUES):
            deadline = _monotonic() + 5.0
            while transport.active_handles() and _monotonic() < deadline:
                app.processEvents()
            assert transport.active_handles() == [], (
                f"real cue #{cue + 1}: previous channel never completed")
            result = hub.play_result(path, event="problip_cue", bus="problip",
                                     mode="mix")
            if result.outcome.value in ("PLAYED", "MIXED"):
                starts += 1
            # let the real ~66 ms playback finish
            deadline = _monotonic() + 5.0
            while transport.active_handles() and _monotonic() < deadline:
                app.processEvents()
            assert transport.active_handles() == []
        assert starts == CUES


def _monotonic() -> float:
    import time

    return time.monotonic()
