"""PERF-004 (SRC-021 audit/11): bounded inactive QSoundEffect resources.

``QtSoundTransport`` had a per-source cap (``POOL_PER_PATH = 4``) but no
GLOBAL bound: a session previewing thousands of unique managed/imported sounds
kept one pool per source forever, because ``stop_all()`` deliberately keeps the
pools.  These tests drive the REAL transport against a contract-compatible fake
QSoundEffect and pin the repaired policy:

* past ``MAX_POOLS`` retained keys, the least-recently-used INACTIVE pool is
  retired (stop + deleteLater + connection dropped);
* active channels, playing effects and the live/ambience layers are NEVER
  evictable -- the bound yields to audible correctness;
* a stale completion from a retired effect can never complete a newer handle;
* STOP ALL stays emergency silence, not cache destruction;
* close()/invalidate_sources() still retire everything.
"""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(
    os.path.join(os.path.dirname(__file__), "../src")))

from fastprompter.core import audio_render  # noqa: E402
from fastprompter.core.audio_hub import QtSoundTransport  # noqa: E402


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


class FakeQSoundEffect:
    """Contract-compatible stand-in: Ready status, honest play/stop/deletion."""

    class Loop:
        Infinite = -2

    class Status:
        Null = 0
        Loading = 1
        Ready = 2
        Error = 3

    playingChanged = None
    created: list = []

    def __init__(self) -> None:
        self._playing = False
        self.playingChanged = _Signal()
        self.play_calls = 0
        self.stop_calls = 0
        self.deleted = False
        FakeQSoundEffect.created.append(self)

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

    def status(self) -> int:
        return FakeQSoundEffect.Status.Ready

    def deleteLater(self) -> None:
        self.deleted = True

    def finish(self) -> None:
        """Simulate the source ending naturally (completion signal)."""
        if self._playing:
            self._playing = False
            self.playingChanged.emit()


@pytest.fixture(autouse=True)
def _no_render_probe(monkeypatch):
    monkeypatch.setattr(audio_render, "device_sample_rate", lambda: None)
    monkeypatch.setattr(audio_render, "_render_enabled", False)
    monkeypatch.setattr(audio_render, "_edge_pad_enabled", False)


@pytest.fixture()
def transport():
    FakeQSoundEffect.created = []
    return QtSoundTransport(qsoundeffect_cls=FakeQSoundEffect,
                            url_factory=lambda p: f"file:///{p}")


def _source(tmp_path, name: str) -> str:
    path = tmp_path / name
    path.write_bytes(b"RIFF....WAVE")
    return str(path)


def _logical_paths(transport) -> set:
    return {os.path.basename(key[0]) for key in transport._pools}


def test_ten_thousand_inactive_sources_stay_under_the_bound(tmp_path, transport):
    bound = transport.MAX_POOLS
    for i in range(10_000):
        effect_handle = transport.play(_source(tmp_path, f"s{i}.wav"))
        assert effect_handle
        # the source finished: pool retained, resource inactive
        FakeQSoundEffect.created[-1].finish()

    pools, effects = transport.pool_cardinality()
    assert pools <= bound, f"{pools} retained pools exceeds MAX_POOLS={bound}"
    assert effects <= bound * transport.POOL_PER_PATH
    assert transport.active_handles() == []


def test_four_active_effects_on_one_source_survive_pressure(tmp_path, transport):
    live = _source(tmp_path, "live.wav")
    handles = [transport.play(live) for _ in range(4)]
    assert all(handles)
    live_effects = list(FakeQSoundEffect.created)

    for i in range(transport.MAX_POOLS * 2):
        other = transport.play(_source(tmp_path, f"p{i}.wav"))
        FakeQSoundEffect.created[-1].finish()
        assert other

    for handle in handles:
        assert handle in transport.active_handles()
    assert all(effect.isPlaying() for effect in live_effects)
    assert "live.wav" in _logical_paths(transport)


def test_looping_ambience_channel_survives_pressure(tmp_path, transport):
    bed = _source(tmp_path, "ambience.wav")
    handle = transport.play(bed, loop=True)
    assert handle

    for i in range(transport.MAX_POOLS * 2):
        transport.play(_source(tmp_path, f"q{i}.wav"))
        FakeQSoundEffect.created[-1].finish()

    assert handle in transport.active_handles()
    assert "ambience.wav" in _logical_paths(transport)


def test_lru_inactive_pool_retires_first(tmp_path, transport, monkeypatch):
    monkeypatch.setattr(QtSoundTransport, "MAX_POOLS", 3)
    for name in ("a.wav", "b.wav", "c.wav"):
        path = _source(tmp_path, name)
        transport.play(path)
        FakeQSoundEffect.created[-1].finish()
    by_name = {os.path.basename(e.source.replace("file:///", "")): e
               for e in FakeQSoundEffect.created}

    # touch A again: recency is now B (oldest) < C < A
    transport.play(str(tmp_path / "a.wav"))
    FakeQSoundEffect.created[-1].finish()

    transport.play(_source(tmp_path, "d.wav"))
    FakeQSoundEffect.created[-1].finish()

    assert by_name["b.wav"].deleted and by_name["b.wav"].stop_calls >= 1
    assert not by_name["a.wav"].deleted
    assert not by_name["c.wav"].deleted
    assert _logical_paths(transport) == {"a.wav", "c.wav", "d.wav"}
    assert transport.pool_cardinality()[0] <= 3


def test_stale_completion_from_evicted_effect_has_zero_authority(
        tmp_path, transport, monkeypatch):
    monkeypatch.setattr(QtSoundTransport, "MAX_POOLS", 1)
    transport.play(_source(tmp_path, "old.wav"))
    evicted_effect = FakeQSoundEffect.created[-1]
    evicted_effect.finish()

    new_handle = transport.play(_source(tmp_path, "new.wav"))
    assert new_handle in transport.active_handles()
    assert evicted_effect.deleted, "the evicted pool was retired"

    completed = []
    transport._completions[new_handle] = lambda: completed.append(new_handle)
    # Simulate the pathological id() collision the guard exists for: stale
    # bookkeeping maps the retired effect's id onto the live handle.
    transport._owner[id(evicted_effect)] = new_handle
    transport._on_playing_changed(evicted_effect)

    assert completed == [], "evicted effect completed a newer handle"
    assert new_handle in transport.active_handles()


def test_stop_all_keeps_the_cache(tmp_path, transport):
    for name in ("a.wav", "b.wav", "c.wav"):
        transport.play(_source(tmp_path, name))
    before = transport.pool_cardinality()
    assert before[0] == 3
    assert transport.active_handles()

    transport.stop_all()

    assert transport.active_handles() == []
    assert transport.pool_cardinality() == before, (
        "STOP ALL must not become mandatory cache destruction")
    assert not any(effect.deleted for effect in FakeQSoundEffect.created)


def test_close_retires_every_resource(tmp_path, transport):
    transport.play(_source(tmp_path, "a.wav"))
    transport.play(_source(tmp_path, "b.wav"), loop=True)
    transport.play(_source(tmp_path, "c.wav"))
    FakeQSoundEffect.created[0].finish()

    transport.close()

    assert transport.pool_cardinality() == (0, 0)
    assert transport.active_handles() == []
    assert transport._pools == {} and transport._bound == {}
    assert all(effect.deleted for effect in FakeQSoundEffect.created)
    assert all(effect.stop_calls >= 1 for effect in FakeQSoundEffect.created)
