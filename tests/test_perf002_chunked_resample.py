"""PERF-002 (SRC-021): the device-rate resampler must not allocate
duration-sized tap matrices, and an oversized source must play raw.

Before this fix the NumPy path built a complete ``(n_out, 32)`` int64 index
array, advanced-indexed the source into another ``(n_out, 32)`` float64 matrix
and multiplied it by the phase kernels: one such matrix at 60 s / 48 kHz is
~703 MiB, and nothing bounded the NumPy path's duration at all (only the pure
Python path had a frame limit). These tests pin:

* sample-for-sample identity with the pre-fix whole-array formula, at real
  block size AND at a tiny block size that forces a seam every 64 frames,
* block-sized temporaries (no temporary scales with n_out),
* impulses and sines exactly on block boundaries, and stereo independence,
* the duration policy on BOTH paths, including "oversized on the requesting
  thread renders nothing, so playback falls back to the raw file".
"""

import math
import os
import sys
import threading
import wave

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

from fastprompter.core import audio_render  # noqa: E402

np = pytest.importorskip("numpy", reason="the chunked path is the NumPy path")

if audio_render._numpy_if_safe() is None:
    pytest.skip("NumPy is not usable in this environment", allow_module_level=True)


def _reference_resample(channels, rate_in, rate_out):
    """The pre-PERF-002 whole-array formula, verbatim, as the oracle."""
    g = math.gcd(rate_in, rate_out)
    up, down = rate_out // g, rate_in // g
    cutoff = 0.5 / max(up, down)
    kernel = audio_render._polyphase_kernel(up, audio_render._TAPS, cutoff)
    n_in = len(channels[0])
    n_out = (n_in * up + down - 1) // down
    delay = audio_render._TAPS // 2
    khat = np.asarray(kernel, dtype=np.float64)
    n = np.arange(n_out, dtype=np.int64)
    m = n * down
    phase = (m % up).astype(np.int64)
    start = (m // up).astype(np.int64) + delay
    pad = audio_render._TAPS
    taps_idx = np.arange(audio_render._TAPS, dtype=np.int64)
    out = []
    for data in channels:
        x = np.asarray(data, dtype=np.float64)
        xp = np.concatenate((np.zeros(pad + delay, dtype=np.float64), x,
                             np.zeros(pad + delay, dtype=np.float64)))
        idx = (start[:, None] + pad + delay) - taps_idx[None, :]
        np.clip(idx, 0, len(xp) - 1, out=idx)
        out.append((xp[idx] * khat[phase]).sum(axis=1).tolist())
    return out


def _tone(n, rate, freq=1000.0, amp=0.6):
    return [amp * math.sin(2.0 * math.pi * freq * i / rate) for i in range(n)]


@pytest.mark.parametrize("rate_in,rate_out", [(44100, 48000), (22050, 48000),
                                             (48000, 44100), (44100, 88200),
                                             (8000, 48000)])
def test_chunked_output_is_identical_to_the_whole_array_formula(rate_in, rate_out):
    channels = [_tone(int(rate_in * 0.35), rate_in), _tone(int(rate_in * 0.35), rate_in, 700.0, 0.4)]
    expected = _reference_resample(channels, rate_in, rate_out)
    got = audio_render._resample(channels, rate_in, rate_out)

    assert len(got) == len(expected)
    for channel_got, channel_expected in zip(got, expected):
        assert len(channel_got) == len(channel_expected)
        for index, (a, b) in enumerate(zip(channel_got, channel_expected)):
            assert a == pytest.approx(b, abs=1e-12), f"{rate_in}->{rate_out} sample {index}"


def test_tiny_block_size_still_matches_the_reference(monkeypatch):
    """A 64-frame block forces a boundary every 64 output frames: if block
    edges reset phase or filter state, this fails loudly."""
    monkeypatch.setattr(audio_render, "RESAMPLE_BLOCK_FRAMES", 64)
    rate_in = 22050
    channels = [_tone(rate_in, rate_in)]
    expected = _reference_resample(channels, rate_in, 48000)
    got = audio_render._resample(channels, rate_in, 48000)
    assert got[0] == pytest.approx(expected[0], abs=1e-12)


def test_impulses_on_block_boundaries_are_not_smeared(monkeypatch):
    monkeypatch.setattr(audio_render, "RESAMPLE_BLOCK_FRAMES", 64)
    rate_in, rate_out = 22050, 48000
    n = 4096
    data = [0.0] * n
    for position in (63, 64, 128, 255, 256, 1024):
        data[position] = 1.0
    expected = _reference_resample([data], rate_in, rate_out)
    got = audio_render._resample([data], rate_in, rate_out)
    assert got[0] == pytest.approx(expected[0], abs=1e-12)
    # the impulse energy is still where the reference puts it, not at a seam
    peak = max(range(len(got[0])), key=lambda i: abs(got[0][i]))
    peak_ref = max(range(len(expected[0])), key=lambda i: abs(expected[0][i]))
    assert peak == peak_ref


def test_temporaries_are_block_sized(monkeypatch):
    """The audit's core claim: no temporary scales with n_out."""
    block = 512
    monkeypatch.setattr(audio_render, "RESAMPLE_BLOCK_FRAMES", block)
    rate_in = 44100
    seconds = 1.5
    channels = [_tone(int(rate_in * seconds), rate_in)]
    n_out = math.ceil(len(channels[0]) * 48000 / rate_in)

    shapes = []

    class _NumpyProxy:
        """Forwards to real NumPy, but records every tap-matrix clip."""

        def __getattr__(self, name):
            return getattr(np, name)

        def clip(self, a, *args, **kwargs):
            shapes.append(tuple(a.shape))
            return np.clip(a, *args, **kwargs)

    monkeypatch.setattr(audio_render, "_numpy_if_safe", lambda: _NumpyProxy())
    out = audio_render._resample(channels, rate_in, 48000)

    assert len(out[0]) == n_out
    assert shapes, "the tap matrix must go through np.clip"
    assert all(shape[0] <= block for shape in shapes), shapes[:3]
    assert all(shape[1] == audio_render._TAPS for shape in shapes), shapes[:3]
    assert len(shapes) == math.ceil(n_out / block), (len(shapes), n_out, block)


def test_stereo_channels_stay_independent(monkeypatch):
    monkeypatch.setattr(audio_render, "RESAMPLE_BLOCK_FRAMES", 128)
    rate_in = 44100
    left = _tone(rate_in // 2, rate_in, 440.0, 0.7)
    right = [0.0] * (rate_in // 2)
    expected = _reference_resample([left, right], rate_in, 48000)
    got = audio_render._resample([left, right], rate_in, 48000)

    assert got[0] == pytest.approx(expected[0], abs=1e-12)
    assert got[1] == pytest.approx(expected[1], abs=1e-12)
    assert any(abs(v) > 0.1 for v in got[0])
    assert all(v == 0.0 for v in got[1])


def _write_wav(path, seconds, rate=22050):
    frames = int(rate * seconds)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(b"\x00\x00" * frames)
    return str(path)


@pytest.fixture
def render_env(tmp_path, monkeypatch):
    monkeypatch.setattr(audio_render, "_cache_dir", lambda: str(tmp_path / "cache"))
    monkeypatch.setattr(audio_render, "device_sample_rate", lambda: 48000)
    monkeypatch.setattr(audio_render, "_render_enabled", True)
    monkeypatch.setattr(audio_render, "_edge_pad_enabled", False)
    return tmp_path


def test_oversized_source_is_not_rendered_on_the_requesting_thread(tmp_path, render_env, monkeypatch):
    """First playback of a large uncached sound must fall back to the raw file
    instead of rendering the whole thing on the calling thread."""
    monkeypatch.setattr(audio_render, "RENDER_MAX_SECONDS", 1.0)
    monkeypatch.setattr(audio_render, "RENDER_MAX_SECONDS_WORKER", 3.0)
    long_source = _write_wav(tmp_path / "long.wav", 1.5)
    short_source = _write_wav(tmp_path / "short.wav", 0.4)

    assert audio_render.device_ready_wav(long_source) is None
    published = audio_render.device_ready_wav(short_source)
    assert published and os.path.exists(published)


def test_oversized_source_still_renders_on_a_worker(tmp_path, render_env, monkeypatch):
    """The background prewarm path keeps its larger budget."""
    monkeypatch.setattr(audio_render, "RENDER_MAX_SECONDS", 1.0)
    monkeypatch.setattr(audio_render, "RENDER_MAX_SECONDS_WORKER", 3.0)
    source = _write_wav(tmp_path / "medium.wav", 1.5)

    result = {}

    def worker():
        result["path"] = audio_render.device_ready_wav(source)

    thread = threading.Thread(target=worker)
    thread.start()
    thread.join(timeout=60)
    assert result.get("path") and os.path.exists(result["path"])


def test_policy_applies_to_the_pure_python_path_too(tmp_path, render_env, monkeypatch):
    """Both paths share the duration policy; the pure-Python path keeps its
    own frame limit on top of it."""
    source = _write_wav(tmp_path / "two_seconds.wav", 2.0)     # 44100 frames @22.05k
    monkeypatch.setattr(audio_render, "_numpy_if_safe", lambda: None)
    monkeypatch.setattr(audio_render, "RENDER_MAX_SECONDS", 30.0)
    monkeypatch.setattr(audio_render, "RENDER_MAX_SECONDS_WORKER", 120.0)

    # (a) the pure-Python frame limit alone refuses it
    monkeypatch.setattr(audio_render, "_PURE_PYTHON_MAX_FRAMES", 1000)
    assert audio_render.device_ready_wav(source) is None

    # (b) with a raised frame limit the render happens...
    monkeypatch.setattr(audio_render, "_PURE_PYTHON_MAX_FRAMES", 4_000_000)
    published = audio_render.device_ready_wav(source)
    assert published and os.path.exists(published)

    # (c) ...unless the shared duration policy is stricter, which proves the
    # policy is not just a NumPy-path guard.
    monkeypatch.setattr(audio_render, "RENDER_MAX_SECONDS", 0.1)
    assert audio_render._render_device_wav(source, str(tmp_path / "out.wav"),
                                          str(tmp_path), 48000) is None
    assert not os.path.exists(tmp_path / "out.wav")
