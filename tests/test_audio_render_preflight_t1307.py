"""PERF-001 (audit/12, SRC-041 R007): oversized WAV rejection is CHEAP.

The duration policy used to run AFTER a full hash and a full decode: a
60-second source was read end-to-end twice before being rejected. Every
eligibility decision now comes from a bounded RIFF-header preflight, and the
reader itself enforces a defensive frame ceiling. These tests instrument
``_source_digest`` and ``_read_wav`` with call counters and prove both are
untouched for rejected sources.
"""

import os
import struct
import threading
import wave

import pytest

from fastprompter.core import audio_render as ar


def _write_pcm16(path, seconds, rate=44100, nch=2):
    nframes = max(1, int(seconds * rate))
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(nch)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(b"\x00\x00" * nch * nframes)


def _write_sparse_header(path, seconds, rate=44100, nch=2, width=2):
    """A WAV whose HEADER claims ``seconds`` while the payload is tiny.

    Proves rejection decisions come from metadata: the payload this file
    actually carries (64 bytes) is far below what the header promises.
    """
    nframes = int(seconds * rate)
    data_size = nframes * nch * width
    byte_rate = rate * nch * width
    block = nch * width
    fmt = struct.pack("<HHIIHH", 1, nch, rate, byte_rate, block, width * 8)
    blob = (b"RIFF" + struct.pack("<I", 36 + data_size) + b"WAVE"
            + b"fmt " + struct.pack("<I", 16) + fmt
            + b"data" + struct.pack("<I", data_size) + b"\x00" * 64)
    path.write_bytes(blob)


@pytest.fixture(autouse=True)
def _render_env(tmp_path, monkeypatch):
    monkeypatch.setattr(ar, "_render_enabled", True)
    monkeypatch.setattr(ar, "_edge_pad_enabled", False)
    monkeypatch.setattr(ar, "_cache_dir", lambda: str(tmp_path / "cache"))
    yield


@pytest.fixture
def counters(monkeypatch):
    calls = {"digest": 0, "read": 0}
    real_digest = ar._source_digest
    real_read = ar._read_wav

    def digest(path):
        calls["digest"] += 1
        return real_digest(path)

    def read(path, max_frames=None):
        calls["read"] += 1
        return real_read(path, max_frames=max_frames)

    monkeypatch.setattr(ar, "_source_digest", digest)
    monkeypatch.setattr(ar, "_read_wav", read)
    return calls


class TestCheapRejection:
    def test_oversized_different_rate_rejected_before_digest_or_decode(
            self, tmp_path, counters):
        src = tmp_path / "big.wav"
        _write_sparse_header(src, seconds=60, rate=44100, nch=2)

        assert ar.device_ready_wav(str(src), rate=48000) is None
        assert counters == {"digest": 0, "read": 0}, \
            "rejection must not hash or decode the payload"

    def test_worker_route_uses_worker_budget_before_digest_or_decode(
            self, tmp_path, counters, monkeypatch):
        # Main-thread budget would allow the 2 s source; the worker budget
        # must reject it — in a real worker thread.
        monkeypatch.setattr(ar, "RENDER_MAX_SECONDS", 3600.0)
        monkeypatch.setattr(ar, "RENDER_MAX_SECONDS_WORKER", 0.5)
        src = tmp_path / "worker_big.wav"
        _write_sparse_header(src, seconds=2, rate=44100, nch=2)

        outcome = {}

        def run():
            outcome["result"] = ar.device_ready_wav(str(src), rate=48000)

        thread = threading.Thread(target=run)
        thread.start()
        thread.join(5.0)

        assert outcome["result"] is None
        assert counters == {"digest": 0, "read": 0}

    def test_equal_rate_over_edge_pad_window_rejected_from_metadata(
            self, tmp_path, counters, monkeypatch):
        monkeypatch.setattr(ar, "_edge_pad_enabled", True)
        src = tmp_path / "long_bed.wav"
        _write_sparse_header(src, seconds=3.0, rate=48000, nch=2)

        assert ar.device_ready_wav(str(src), rate=48000) is None
        assert counters == {"digest": 0, "read": 0}

    def test_pure_python_over_limit_rejected_before_digest_or_decode(
            self, tmp_path, counters, monkeypatch):
        monkeypatch.setattr(ar, "_numpy_if_safe", lambda: None)
        src = tmp_path / "pure_python.wav"
        _write_sparse_header(src, seconds=7.0, rate=44100, nch=2)

        assert ar.device_ready_wav(str(src), rate=48000) is None
        assert counters == {"digest": 0, "read": 0}


class TestEligibleSourcesUnchanged:
    def test_short_source_digests_once_renders_and_reuses_cache(
            self, tmp_path, counters):
        src = tmp_path / "short.wav"
        _write_pcm16(src, seconds=0.5, rate=44100, nch=2)

        first = ar.device_ready_wav(str(src), rate=48000)
        assert first and os.path.exists(first)
        assert counters["digest"] == 1
        assert counters["read"] == 1

        second = ar.device_ready_wav(str(src), rate=48000)
        assert second == first
        # The cache key IS the content digest, so a warm lookup still hashes
        # the source (pre-existing identity contract); what it must NOT do is
        # decode or re-render.
        assert counters["digest"] == 2
        assert counters["read"] == 1

    def test_equal_rate_short_source_still_pads_when_asked(
            self, tmp_path, counters, monkeypatch):
        monkeypatch.setattr(ar, "_edge_pad_enabled", True)
        src = tmp_path / "short_equal.wav"
        _write_pcm16(src, seconds=0.5, rate=48000, nch=1)

        out = ar.device_ready_wav(str(src), rate=48000)
        assert out and os.path.exists(out)
        with wave.open(out, "rb") as wf:
            assert wf.getnframes() > int(0.5 * 48000)

    def test_read_wav_enforces_defensive_max_frames_from_header(self,
                                                                tmp_path):
        src = tmp_path / "one_second.wav"
        _write_pcm16(src, seconds=1.0, rate=44100, nch=1)

        assert ar._read_wav(str(src), max_frames=100) is None
        decoded = ar._read_wav(str(src), max_frames=44100 + 10)
        assert decoded is not None
        channels, rate = decoded
        assert rate == 44100 and len(channels[0]) == 44100
