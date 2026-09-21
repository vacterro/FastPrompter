"""T-1242 spec 3/4/5: repeated playback uses ONE stable source representation.

The user's deterministic reproduction was: playback #1 clean, #2 cut, #3+
coloured -- on the SAME blip01.wav at the SAME volume through the SAME
scheduler.  One mechanism that can produce exactly that is a transport whose
pooled QSoundEffects do not all own the same physical file: the logical-path
pool keyed by ``original`` while a new effect received
``device_ready_wav(path) or path`` meant the SAME logical-path pool could
hold a RAW effect and a RENDERED effect at once, and which one a given play
got depended on allocation order and cache readiness.  These tests pin the
fixed identity model: resolve the physical source FIRST, pool by the
resolved identity, and retire everything on a policy change.
"""

from __future__ import annotations

import os
import sys
import wave

import pytest

sys.path.insert(0, os.path.abspath(
    os.path.join(os.path.dirname(__file__), "../src")))

from fastprompter.core import audio_render  # noqa: E402
from fastprompter.core.audio_hub import QtSoundTransport  # noqa: E402


class _Signal:
    def __init__(self) -> None:
        self._slots = []

    def connect(self, slot) -> None:
        self._slots.append(slot)

    def emit(self, *args) -> None:
        for slot in list(self._slots):
            slot(*args)


class IdentityQSoundEffect:
    """Records the EXACT source file each effect was created with."""

    class Loop:
        Infinite = -2

    playingChanged = None
    created: list = []

    def __init__(self) -> None:
        self.source = None
        self.play_calls = 0
        self._playing = False
        self.playingChanged = _Signal()
        IdentityQSoundEffect.created.append(self)

    def setSource(self, url) -> None:
        self.source = url

    setVolume = lambda self, value: None          # noqa: E731
    setLoopCount = lambda self, count: None       # noqa: E731

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

    def finish(self) -> None:
        if self._playing:
            self._playing = False
            self.playingChanged.emit()


def _wav(tmp_path, name: str, frames: int = 800) -> str:
    path = tmp_path / name
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(22050)
        handle.writeframes(b"\x00\x01" * frames)
    return str(path)


@pytest.fixture()
def transport(monkeypatch):
    IdentityQSoundEffect.created = []
    monkeypatch.setattr(audio_render, "_render_enabled", False)
    return QtSoundTransport(qsoundeffect_cls=IdentityQSoundEffect,
                            url_factory=lambda p: p)


def _effect_source(effect) -> str:
    return str(effect.source)


class TestPoolIdentity:
    def test_every_effect_in_a_pool_owns_the_same_physical_file(
            self, transport, tmp_path, monkeypatch):
        """THE red test: with the old model the same logical-path pool held
        a raw and a rendered effect depending on cache readiness at
        allocation time.  All ten plays must resolve to ONE representation."""
        path = _wav(tmp_path, "blip.wav")
        monkeypatch.setattr(audio_render, "device_sample_rate", lambda: 48000)
        sources = []
        for _ in range(10):
            transport.play(path)
            IdentityQSoundEffect.created[-1].finish()
        for effect in IdentityQSoundEffect.created:
            sources.append(_effect_source(effect))
        assert len(set(sources)) == 1, (
            f"one logical source produced {len(set(sources))} different "
            f"physical representations: {sorted(set(sources))}")

    def test_render_flip_cannot_mix_representations_in_one_pool(
            self, transport, tmp_path, monkeypatch):
        """Render availability changing between allocations is the exact
        reported defect class.  Within ONE generation the transport keeps a
        stable representation (that is the point); the UI's policy-change
        path calls invalidate_sources(), which retires the old pool so the
        next play gets the new representation -- never a mixed one."""
        path = _wav(tmp_path, "blip.wav")

        rendered_file = tmp_path / "rendered.wav"
        with wave.open(str(rendered_file), "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(48000)
            handle.writeframes(b"\x00\x01" * 400)

        monkeypatch.setattr(audio_render, "device_sample_rate", lambda: 48000)
        monkeypatch.setattr(audio_render, "_render_enabled", True)
        monkeypatch.setattr(audio_render, "device_ready_wav",
                            lambda p, rate=None: str(rendered_file))
        transport.play(path)
        first = _effect_source(IdentityQSoundEffect.created[-1])

        # The cache "becomes unavailable" mid-session (device changed etc):
        # the UI toggle path calls invalidate_sources() when the policy
        # changes (SoundManager.invalidate_cache -> hub.invalidate_sources).
        monkeypatch.setattr(audio_render, "device_ready_wav",
                            lambda p, rate=None: None)
        transport.invalidate_sources()
        transport.play(path)
        second = _effect_source(IdentityQSoundEffect.created[-1])

        assert first != second          # new policy generation: new source
        pool_keys = list(transport._pools)
        # Each physical identity sits in exactly one pool.
        assert len({(k[0], k[1]) for k in pool_keys}) == len(pool_keys)


class TestRepeatedPlayIdentity:
    def test_twenty_repeated_plays_log_one_stable_source(
            self, transport, tmp_path):
        """Spec 3 invariant: unchanged settings -> every repeated playback
        of the same logical sound uses one stable source representation."""
        path = _wav(tmp_path, "blip.wav")
        for index in range(20):
            handle = transport.play(path, token=f"req{index}")
            assert handle, f"play #{index + 1} was refused"
            IdentityQSoundEffect.created[-1].finish()
        plays = [e for e in transport.playback_trace()
                 if e.get("event") == "play"]
        assert len(plays) == 20
        assert len({e["physical"] for e in plays}) == 1
        assert len({e["policy_generation"] for e in plays}) == 1
        assert all(e["rendered"] is False for e in plays)

    def test_playback_trace_records_required_fields(self, transport,
                                                    tmp_path):
        path = _wav(tmp_path, "blip.wav")
        transport.play(path, token="req-1")
        entry = transport.playback_trace()[-1]
        for field in ("logical", "physical", "rendered",
                      "policy_generation", "status_before_play", "handle"):
            assert field in entry, f"trace missing {field}"


class TestPolicyInvalidation:
    def test_invalidate_sources_bumps_the_generation_and_retires_effects(
            self, transport, tmp_path):
        path = _wav(tmp_path, "blip.wav")
        transport.play(path)
        IdentityQSoundEffect.created[-1].finish()
        before = transport.render_policy_generation()
        transport.invalidate_sources()
        assert transport.render_policy_generation() == before + 1
        assert transport._pools == {}
        retirement = transport.retirement_trace()[-1]
        assert retirement["to_generation"] == before + 1

    def test_play_after_invalidation_logs_the_new_generation(
            self, transport, tmp_path):
        path = _wav(tmp_path, "blip.wav")
        transport.play(path)
        transport.invalidate_sources()
        transport.play(path)
        plays = [e for e in transport.playback_trace()
                 if e.get("event") == "play"]
        assert plays[0]["policy_generation"] == 0
        assert plays[1]["policy_generation"] == 1

    def test_ui_toggle_cannot_leave_a_stale_representation_playing(
            self, transport, tmp_path, monkeypatch):
        """Spec 5: the UI turns RAW on while the transport still plays a
        pooled RENDERED effect -- the exact contradiction invalidate_sources
        exists to kill."""
        path = _wav(tmp_path, "blip.wav")
        rendered_file = tmp_path / "rendered.wav"
        with wave.open(str(rendered_file), "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(48000)
            handle.writeframes(b"\x00\x01" * 400)
        monkeypatch.setattr(audio_render, "device_sample_rate", lambda: 48000)
        monkeypatch.setattr(audio_render, "_render_enabled", True)
        monkeypatch.setattr(audio_render, "device_ready_wav",
                            lambda p, rate=None: str(rendered_file))
        transport.play(path)                    # pooled effect: rendered
        monkeypatch.setattr(audio_render, "device_ready_wav",
                            lambda p, rate=None: None)
        transport.invalidate_sources()          # the UI toggle's new call
        transport.play(path)                    # next playback: raw
        physicals = [e["physical"] for e in transport.playback_trace()
                     if e.get("event") == "play"]
        assert physicals[0] == str(rendered_file)
        assert physicals[1] == path
        assert physicals[0] != physicals[1]

    def test_invalidate_fires_a_retirement_record(self, transport, tmp_path):
        path = _wav(tmp_path, "blip.wav")
        transport.play(path)
        transport.invalidate_sources()
        record = transport.retirement_trace()[-1]
        assert record["reason"] == "invalidate_sources"
        assert record["effects"] >= 1
        assert record["to_generation"] == record["from_generation"] + 1


class TestAcquireContract:
    def test_pool_exhaustion_still_refuses(self, transport, tmp_path):
        path = _wav(tmp_path, "blip.wav")
        handles = [transport.play(path)
                   for _ in range(QtSoundTransport.POOL_PER_PATH)]
        assert all(handles)
        assert transport.play(path) == ""

    def test_preload_uses_the_same_resolved_identity(self, transport,
                                                     tmp_path, monkeypatch):
        path = _wav(tmp_path, "blip.wav")
        monkeypatch.setattr(audio_render, "device_sample_rate", lambda: 48000)
        transport.preload([path])
        assert transport.playback_trace()[-1]["physical"] == path
