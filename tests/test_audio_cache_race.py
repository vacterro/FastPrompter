"""T-1242 cache-race regressions: single-flight render + scaled caches.

prewarm_device_cache() runs on a daemon thread while the first real cue may
call device_ready_wav() for the SAME key.  Before the fix the temp filename
was PID-only (two threads in one process shared it) and there was no per-key
lock: 8 concurrent callers for one blip returned 5 rendered paths and 3
None/fallback answers.  Every caller must now resolve the same valid final
file, and scaled_wav_path() must obey the same single-flight discipline.
"""

from __future__ import annotations

import os
import struct
import sys
import wave
from concurrent.futures import ThreadPoolExecutor

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

from fastprompter.core import (
    audio_render,  # noqa: E402
    sound_manager,  # noqa: E402
)


def _write_wav16(path, channels, rate):
    frames = len(channels[0])
    with wave.open(path, "wb") as fh:
        fh.setnchannels(len(channels))
        fh.setsampwidth(2)
        fh.setframerate(rate)
        interleaved = bytearray()
        for i in range(frames):
            for ch in channels:
                v = max(-32768, min(32767, int(round(ch[i]))))
                interleaved += struct.pack("<h", v)
        fh.writeframes(bytes(interleaved))


def _valid_wav(path):
    try:
        with wave.open(path, "rb") as fh:
            return fh.getnframes() > 0 and fh.getframerate() > 0
    except (wave.Error, EOFError, OSError):
        return False


@pytest.fixture(autouse=True)
def _isolated_caches(tmp_path, monkeypatch):
    monkeypatch.setattr(audio_render, "_CACHE_DIR_NAME",
                        "fp_test_render_race")
    monkeypatch.setattr(sound_manager, "_scaled_cache_dir",
                        lambda: str(tmp_path / "scaled"))
    # This suite exercises the renderer's own single-flight contract, so the
    # A/B master switch is pinned ON (the product default is OFF, T-1242
    # spec 8/9; the default itself is pinned in test_audio_render_defaults).
    monkeypatch.setattr(audio_render, "_render_enabled", True)
    monkeypatch.setattr(audio_render, "_edge_pad_enabled", False)
    yield


def _run_concurrent(fn, workers):
    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(lambda _: fn(), range(workers)))


class TestDeviceRenderSingleFlight:
    def test_16_concurrent_same_key_resolve_one_valid_file(self, tmp_path):
        src = tmp_path / "blip.wav"
        _write_wav16(str(src), [[9000, -9000] * 64], 22050)
        results = _run_concurrent(
            lambda: audio_render.device_ready_wav(str(src), 44100), 16)
        paths = {os.path.normcase(os.path.normpath(p)) for p in results if p}
        assert len(paths) == 1, f"callers saw divergent outputs: {results}"
        final = paths.pop()
        assert _valid_wav(final)
        # no leftover temp files from lost races
        leftovers = [n for n in os.listdir(os.path.dirname(final))
                     if n.endswith(".part")]
        assert not leftovers

    def test_latecomer_observes_published_result(self, tmp_path, monkeypatch):
        src = tmp_path / "late.wav"
        _write_wav16(str(src), [[1000, -1000] * 32], 22050)
        first = audio_render.device_ready_wav(str(src), 44100)
        assert first and os.path.isfile(first)
        monkeypatch.setattr(audio_render, "_resample", None)  # would crash if re-run
        again = audio_render.device_ready_wav(str(src), 44100)
        assert os.path.normcase(again or "") == os.path.normcase(first)

    def test_render_registry_is_bounded(self):
        audio_render._RENDER_FLIGHTS.clear()
        events = []
        for index in range(200):
            _owner, event = audio_render._flight_claim(f"k{index}")
            events.append(event)
        assert len(audio_render._RENDER_FLIGHTS) <= audio_render._RENDER_FLIGHTS_MAX
        for e in events:
            e.set()


class TestScaledCacheSingleFlight:
    def test_16_concurrent_same_key_no_partial_file(self, tmp_path):
        src = tmp_path / "ding.wav"
        _write_wav16(str(src), [[20000, -20000] * 100], 44100)
        results = _run_concurrent(
            lambda: sound_manager.scaled_wav_path(str(src), 0.5), 16)
        paths = {os.path.normcase(os.path.normpath(p)) for p in results if p}
        assert len(paths) == 1, f"callers saw divergent outputs: {results}"
        final = paths.pop()
        assert _valid_wav(final)
        scaled_dir = str(tmp_path / "scaled")
        leftovers = [n for n in os.listdir(scaled_dir) if n.endswith(".part")]
        assert not leftovers

    def test_scaled_registry_is_bounded(self):
        sound_manager._SCALED_FLIGHTS.clear()
        events = []
        for index in range(200):
            _owner, event = sound_manager._scaled_claim(f"k{index}")
            events.append(event)
        assert len(sound_manager._SCALED_FLIGHTS) <= sound_manager._SCALED_FLIGHTS_MAX
        for e in events:
            e.set()


class TestNoRateGuess:
    def test_unknown_device_rate_returns_none_not_48000(self, monkeypatch):
        # spec 7: without a verified probe the caller plays the original;
        # a guessed 48000 would double-resample 44100 -> 48000 -> 44100.
        monkeypatch.setattr(audio_render, "_device_rate_cache",
                            audio_render._MISSING)
        calls = []
        import types

        qtmm = types.ModuleType("PyQt6.QtMultimedia")
        qtmm.QMediaDevices = None  # attribute lookup must fail -> None path

        class _Boom:
            def __getattr__(self, name):
                raise RuntimeError("no QtMultimedia")

        import builtins
        real_import = builtins.__import__

        def fake_import(name, *a, **k):
            if name == "PyQt6.QtMultimedia":
                calls.append(name)
                raise ImportError("no QtMultimedia in packaged build")
            return real_import(name, *a, **k)

        monkeypatch.setattr(builtins, "__import__", fake_import)
        assert audio_render.device_sample_rate() is None
