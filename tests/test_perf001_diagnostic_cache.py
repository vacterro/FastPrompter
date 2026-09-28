"""PERF-001 (SRC-021): the diagnostic enrichment must be O(1) per request.

`SoundManager._record()` ran on every request -- including ones the AudioHub
later reported as COALESCED/DROPPED -- and enriched each entry by opening and
parsing the source WAV and by SHA-256 hashing the WHOLE file to answer "does a
device-rate render exist". A 2.4 MB custom typewriter sound therefore cost
~1.6 ms of synchronous I/O + CPU per keystroke, after the hub verdict, where
coalescing could not help.

These tests pin the cache that removes it, and the guardrails the audit named:
stable metadata, signature-keyed invalidation, distinguishable paths, and the
unchanged diagnostic payload.
"""

import os
import sys
import time
import wave
from collections import deque

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

from fastprompter.core import audio_render, sound_manager  # noqa: E402


def _write_wav(path, seconds=0.05, rate=22050, channels=1):
    frames = int(rate * seconds)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(b"\x00\x00" * frames * channels)
    return str(path)


def _manager(data=None):
    """A SoundManager built without Qt: `_record`/`invalidate_cache` need only
    these attributes, and constructing the real QObject would drag a QApplication
    into a pure-diagnostics test."""
    manager = sound_manager.SoundManager.__new__(sound_manager.SoundManager)
    manager._data = {} if data is None else data
    manager._provenance = deque(maxlen=256)
    manager._file_cache = {}
    manager._file_sig = {}
    manager._scaled_cache = {}
    manager._pending = deque()
    manager._data_id = id(manager._data)
    return manager


@pytest.fixture(autouse=True)
def _clean_cache():
    sound_manager._diag_cache_clear()
    yield
    sound_manager._diag_cache_clear()


@pytest.fixture(autouse=True)
def _pinned_device_rate(monkeypatch):
    """Pin the mix rate so the cache is measured, not the host's audio hardware.

    `_rendered_path_for` resolves a render identity only when the device rate
    is known, and returns early when it is not. A machine with no output
    device (a headless CI runner) therefore performs no resolve and no digest
    at all, and every count below read zero. The behaviour under test is the
    caching, so the rate is pinned rather than probed.
    """
    monkeypatch.setattr(audio_render, "device_sample_rate", lambda: 48000)


@pytest.fixture
def counters(monkeypatch):
    """Count the expensive work: WAV parses, render-identity resolutions and
    the whole-file SHA-256 that both of them used to perform."""
    counts = {"parse": 0, "resolve": 0, "digest": 0}

    real_parse = sound_manager._read_wav_summary
    real_resolve = sound_manager._resolve_render_identity
    real_digest = audio_render._source_digest

    def parse(path):
        counts["parse"] += 1
        return real_parse(path)

    def resolve(path, target):
        counts["resolve"] += 1
        return real_resolve(path, target)

    def digest(path):
        counts["digest"] += 1
        return real_digest(path)

    monkeypatch.setattr(sound_manager, "_read_wav_summary", parse)
    monkeypatch.setattr(sound_manager, "_resolve_render_identity", resolve)
    monkeypatch.setattr(audio_render, "_source_digest", digest)
    return counts


def test_repeated_requests_never_re_read_the_source(tmp_path, counters):
    """1000 requests to one unchanged WAV: one parse, one digest, then O(1)."""
    wav = _write_wav(tmp_path / "type_key_1.wav")
    manager = _manager()

    for _ in range(1000):
        manager._record({"event": "type", "path": wav, "volume": 0.5}, "PLAYED")

    assert counters["parse"] == 1, counters
    assert counters["resolve"] == 1, counters
    assert counters["digest"] == 1, counters
    log = manager.diagnostic_log()
    assert len(log) == 256, "the provenance log stays bounded at 256 entries"
    assert all(entry["source_wav"].startswith("PCM 16bit 1ch 22050Hz") for entry in log)


def test_large_source_does_not_scale_request_latency(tmp_path, counters):
    """A multi-megabyte custom typewriter sound must cost what a tiny one costs:
    after warm-up the cached request does no I/O at all, so the per-request time
    is the same order of magnitude for a 2.4 MB file and a 4 KB file (the audit
    measured 1.642 ms/request for the large file before this cache)."""
    big = _write_wav(tmp_path / "rain.wav", seconds=55.0)   # ~2.4 MB of PCM
    small = _write_wav(tmp_path / "type_key_1.wav", seconds=0.05)
    assert os.path.getsize(big) > 2_000_000
    assert os.path.getsize(small) < 10_000
    manager = _manager()

    def cached_seconds(path, iterations=2000, samples=5):
        """Fastest of ``samples`` runs, not the first one.

        T-1347: one 2000-iteration sample is ~0.13s of wall clock, and the
        suite's other work can land inside it. Measured red in a full run at
        big=0.2890s vs small=0.1293s -- 3.6% over a 2x ceiling the code never
        approached, and green 3/3 in isolation. The scheduler was being
        measured, not the request path. The MINIMUM of N samples is the
        standard micro-benchmark estimator and it does not move the ceiling
        below: a real return of whole-file work to the request path costs
        600x, which no amount of sampling noise can hide under 2x."""
        manager._record({"event": "type", "path": path}, "PLAYED")   # warm up
        best = None
        for _ in range(samples):
            started = time.perf_counter()
            for _ in range(iterations):
                manager._record({"event": "type", "path": path}, "PLAYED")
            elapsed = time.perf_counter() - started
            best = elapsed if best is None else min(best, elapsed)
        return best

    big_seconds = cached_seconds(big)
    small_seconds = cached_seconds(small)

    assert counters["digest"] == 2, counters          # one per file, ever
    assert counters["parse"] == 2, counters
    # Size-independent: the 600x bigger source may not cost 600x more. A 2x
    # ceiling leaves room for disk-cache noise while still failing loudly if
    # any whole-file work returns to the request path.
    assert big_seconds < small_seconds * 2 + 0.02, (
        f"big={big_seconds:.4f}s small={small_seconds:.4f}s")


def test_replaced_file_refreshes_metadata_exactly_once(tmp_path, counters):
    """A replaced sound must not keep stale duration/format metadata: the next
    request re-reads, and only one request does."""
    wav = tmp_path / "tick.wav"
    _write_wav(wav, seconds=0.05)
    manager = _manager()
    manager._record({"event": "type", "path": str(wav)}, "PLAYED")
    first = manager.diagnostic_log()[-1]["source_wav"]

    _write_wav(wav, seconds=0.60)          # same logical mapping, new content
    os.utime(wav, (time.time() + 1, time.time() + 1))

    manager._record({"event": "type", "path": str(wav)}, "PLAYED")
    refreshed = manager.diagnostic_log()[-1]["source_wav"]
    manager._record({"event": "type", "path": str(wav)}, "PLAYED")

    assert first != refreshed, (first, refreshed)
    assert refreshed.endswith("0.60s"), refreshed
    assert counters["parse"] == 2, counters


def test_same_basename_at_different_paths_stays_distinguishable(tmp_path, counters):
    one = tmp_path / "a"
    two = tmp_path / "b"
    one.mkdir()
    two.mkdir()
    short = _write_wav(one / "click.wav", seconds=0.05)
    long = _write_wav(two / "click.wav", seconds=0.30)
    manager = _manager()

    manager._record({"event": "type", "path": short}, "PLAYED")
    manager._record({"event": "type", "path": long}, "PLAYED")

    summaries = [entry["source_wav"] for entry in manager.diagnostic_log()]
    assert summaries[0].endswith("0.05s")
    assert summaries[1].endswith("0.30s")
    assert counters["parse"] == 2, counters


def test_invalidate_cache_drops_cached_diagnostic_facts(tmp_path, counters):
    """The canonical invalidation point must also drop diagnostic metadata."""
    wav = _write_wav(tmp_path / "click.wav")
    manager = _manager()
    manager._record({"event": "type", "path": wav}, "PLAYED")
    assert counters["parse"] == 1

    manager.invalidate_cache()
    manager._record({"event": "type", "path": wav}, "PLAYED")

    assert counters["parse"] == 2, counters
    assert counters["digest"] == 2, counters


def test_render_identity_tracks_device_rate_and_published_file(tmp_path, monkeypatch, counters):
    """Rendered provenance follows the render identity: a different device rate
    re-resolves, and a publish/unpublish is visible on the next request."""
    wav = _write_wav(tmp_path / "type_key_1.wav")
    monkeypatch.setattr(audio_render, "device_sample_rate", lambda: 48000)
    manager = _manager()

    manager._record({"event": "type", "path": wav}, "PLAYED")
    assert counters["resolve"] == 1
    assert "rendered_path" not in manager.diagnostic_log()[-1]

    # the renderer publishes the render for this exact identity
    rendered = sound_manager._resolve_render_identity(wav, 48000)
    assert rendered and rendered.endswith(f"_r48000_v{audio_render.RENDER_VERSION}.wav")
    os.makedirs(os.path.dirname(rendered), exist_ok=True)
    with open(rendered, "wb") as fh:
        fh.write(b"RIFF")
    counters["resolve"] = 0

    manager._record({"event": "type", "path": wav}, "PLAYED")
    entry = manager.diagnostic_log()[-1]
    assert entry.get("rendered_path") == os.path.basename(rendered)
    assert counters["resolve"] == 0, "published identity must not be re-derived"

    os.remove(rendered)
    manager._record({"event": "type", "path": wav}, "PLAYED")
    assert "rendered_path" not in manager.diagnostic_log()[-1]

    # a different device rate is a different identity, so it re-resolves once
    monkeypatch.setattr(audio_render, "device_sample_rate", lambda: 44100)
    counter_before = counters["resolve"]
    manager._record({"event": "type", "path": wav}, "PLAYED")
    assert counters["resolve"] == counter_before + 1, counters


def test_diagnostic_payload_is_unchanged(tmp_path):
    """The guardrail: existing troubleshooting fields stay intact."""
    wav = _write_wav(tmp_path / "click.wav")
    manager = _manager({"sound_volume": 0.5})
    manager._record({"event": "type", "path": wav, "volume": 0.25}, "COALESCED")

    entry = manager.diagnostic_log()[-1]
    assert entry["event"] == "type"
    assert entry["outcome"] == "COALESCED"
    assert entry["effective_global_volume"] == pytest.approx(0.5, abs=1e-4)
    assert "effective_volume" in entry
    assert "event_gain_db" in entry
    assert entry["source_wav"].startswith("PCM 16bit 1ch")
    assert "monotonic" in entry and "wall" in entry


def test_missing_file_reports_missing_without_caching_a_lie(tmp_path):
    """An absent file is reported MISSING and re-checked after it appears."""
    missing = str(tmp_path / "nope.wav")
    manager = _manager()
    manager._record({"event": "type", "path": missing}, "DROPPED")
    assert manager.diagnostic_log()[-1]["source_wav"] == "MISSING"

    _write_wav(tmp_path / "nope.wav")
    manager._record({"event": "type", "path": missing}, "PLAYED")
    assert manager.diagnostic_log()[-1]["source_wav"].startswith("PCM 16bit 1ch")
