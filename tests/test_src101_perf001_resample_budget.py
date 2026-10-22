"""PERF-001 (SRC-101 / audit/18): an explicit budget on polyphase kernel size.

The kernel table is ``up * _TAPS`` coefficients, where ``up`` is the OUTPUT rate
over the pair's gcd -- a property of the RATE RATIO alone, not of the source.
A 100-frame (200-byte) cue at 44,101 Hz rendered to 48,000 Hz therefore asked
for 48,000 phases = 1,536,000 coefficients, ~124 MB of resident memory and
~1 s of CPU, and a coprime conversion to the accepted 192 kHz output ceiling
would have asked for 6,144,000.  The duration/frame limits cannot see this
dimension at all.

Four claims are pinned here:

* a ratio outside the budget is refused from the WAV HEADER -- before the
  content digest, before any decode -- and the caller plays the source raw;
* the budget also holds if ``_resample`` is reached directly (so no caller can
  sidestep the admission gate);
* every conversion the product supports stays admitted and byte-identical to
  its pre-repair result;
* the process-global kernel cache is bounded by entry count AND by total
  coefficient budget, evicts least-recently-used deterministically, and never
  invalidates a kernel it has already handed to a caller.
"""

import math
import os
import struct
import sys
import time
import wave
from collections import OrderedDict

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

from fastprompter.core import audio_render  # noqa: E402


def _write_wav16(path, samples, rate):
    """Mono 16-bit PCM WAV from one list of integer samples."""
    with wave.open(str(path), "wb") as fh:
        fh.setnchannels(1)
        fh.setsampwidth(2)
        fh.setframerate(rate)
        fh.writeframes(b"".join(struct.pack("<h", int(v)) for v in samples))


def _kernel_coeffs(cache):
    return sum(len(kernel) * len(kernel[0]) for kernel in cache.values())


#: The conversions the product actually supports.  ``up`` for each: 160, 320,
#: 160, 6, 2, 640, 320 -- every one of them two orders of magnitude inside the
#: 2048-phase budget.
_SUPPORTED = [(44100, 48000), (22050, 48000), (48000, 44100), (8000, 48000),
              (44100, 88200), (11025, 48000), (11025, 96000)]


def test_the_audited_coprime_ratio_is_out_of_budget():
    """44,101 and 48,000 are coprime, so the table would be 48,000 phases."""
    assert math.gcd(44101, 48000) == 1
    assert audio_render._resample_admitted(44101, 48000) is False
    assert 48000 // math.gcd(44101, 48000) == 48000
    assert 48000 > audio_render.MAX_RESAMPLE_PHASES


@pytest.mark.parametrize("rate_in,rate_out", _SUPPORTED)
def test_supported_conversions_stay_admitted(rate_in, rate_out):
    assert audio_render._resample_admitted(rate_in, rate_out) is True


@pytest.mark.parametrize("rate_in,rate_out", [(0, 48000), (44100, 0),
                                              (-1, 48000), (48000, -1)])
def test_nonsense_rates_are_not_admitted(rate_in, rate_out):
    assert audio_render._resample_admitted(rate_in, rate_out) is False


def test_a_tiny_odd_rate_wav_takes_the_raw_play_fallback(tmp_path, monkeypatch):
    """The audit's reproduction: 10 ms at 44,101 Hz, refused at header cost.

    Nothing downstream of the header may run for a ratio that can never be
    rendered: not the content digest (cache identity), not the kernel, not the
    resample.  ``device_ready_wav`` returns None and the caller plays the raw
    file exactly as it did before this module existed.
    """
    monkeypatch.setattr(audio_render, "_cache_dir", lambda: str(tmp_path / "cache"))
    monkeypatch.setattr(audio_render, "device_sample_rate", lambda: 48000)
    monkeypatch.setattr(audio_render, "_render_enabled", True)
    monkeypatch.setattr(audio_render, "_edge_pad_enabled", False)

    calls = {"kernel": [], "digest": [], "resample": []}
    real_kernel = audio_render._polyphase_kernel
    real_digest = audio_render._source_digest
    real_resample = audio_render._resample

    def spy_kernel(up, taps, cutoff):
        calls["kernel"].append(up)
        return real_kernel(up, taps, cutoff)

    def spy_digest(path):
        calls["digest"].append(path)
        return real_digest(path)

    def spy_resample(channels, rate_in, rate_out):
        calls["resample"].append((rate_in, rate_out))
        return real_resample(channels, rate_in, rate_out)

    monkeypatch.setattr(audio_render, "_polyphase_kernel", spy_kernel)
    monkeypatch.setattr(audio_render, "_source_digest", spy_digest)
    monkeypatch.setattr(audio_render, "_resample", spy_resample)

    src = tmp_path / "odd_rate.wav"
    _write_wav16(src, [7000] * 441, 44101)          # 441 frames = 10 ms

    started = time.perf_counter()
    assert audio_render.device_ready_wav(str(src)) is None
    elapsed = time.perf_counter() - started

    assert calls == {"kernel": [], "digest": [], "resample": []}
    assert not (tmp_path / "cache").exists(), "no cache path may even be built"
    # Building that table was ~1 s of pure CPU before the repair; a refused
    # render costs two integers.  The bound is only a proxy -- the call
    # assertions above are the exact invariant -- but 0.5 s is huge headroom.
    assert elapsed < 0.5, elapsed


@pytest.mark.parametrize("rate_in,rate_out", [(44101, 192000), (48001, 192000),
                                              (96001, 192000), (44101, 96000)])
def test_a_coprime_source_near_the_192khz_ceiling_stays_bounded(rate_in, rate_out):
    """The output ceiling must not be usable to request a 192,000-phase table."""
    assert audio_render._resample_admitted(rate_in, rate_out) is False
    started = time.perf_counter()
    assert audio_render._resample([[0.5] * 64], rate_in, rate_out) == []
    assert time.perf_counter() - started < 0.5


def test_the_budget_only_refuses_it_never_changes_an_admitted_result(monkeypatch):
    """Fidelity guardrail: an admitted conversion is unaffected by the budget."""
    source = [[math.sin(2.0 * math.pi * 1000.0 * i / 44100)
               for i in range(441)]]
    monkeypatch.setattr(audio_render, "_numpy_if_safe", lambda: None)
    admitted = audio_render._resample(source, 44100, 48000)

    monkeypatch.setattr(audio_render, "MAX_RESAMPLE_PHASES", 1 << 30)
    unbudgeted = audio_render._resample(source, 44100, 48000)

    assert admitted == unbudgeted
    assert len(admitted[0]) == math.ceil(len(source[0]) * 48000 / 44100)


def test_the_kernel_cache_is_bounded_by_entry_count(monkeypatch):
    monkeypatch.setattr(audio_render, "_kernel_cache", OrderedDict())
    limit = audio_render._KERNEL_CACHE_MAX_ENTRIES
    first_up, extra = 2, 5
    for up in range(first_up, first_up + limit + extra):
        audio_render._polyphase_kernel(up, audio_render._TAPS, 0.5 / up)

    cache = audio_render._kernel_cache
    assert len(cache) == limit
    # Least recently used went first, so the survivors are the NEWEST inserts:
    # eviction is deterministic, not arbitrary.
    assert sorted(key[0] for key in cache) == list(
        range(first_up + extra, first_up + limit + extra))


def test_the_kernel_cache_is_bounded_by_its_coefficient_budget(monkeypatch):
    monkeypatch.setattr(audio_render, "_kernel_cache", OrderedDict())
    monkeypatch.setattr(audio_render, "_KERNEL_CACHE_MAX_COEFFS", 1000)
    for up in range(2, 12):                 # up * _TAPS coefficients each
        audio_render._polyphase_kernel(up, audio_render._TAPS, 0.5 / up)

    cache = audio_render._kernel_cache
    assert _kernel_coeffs(cache) <= 1000
    assert 1 <= len(cache) < 10, "the coefficient budget really evicted entries"
    # The largest tables are what survive a coefficient-budget trim.
    assert sorted(key[0] for key in cache) == [9, 10, 11]


def test_many_distinct_admissible_ratios_stay_inside_the_documented_budget(
        tmp_path, monkeypatch):
    """Cache pressure through the real public entry point.

    A long session of unusual-but-legal ratios must not grow the
    process-global cache past its documented bounds.  Driven through
    ``device_ready_wav`` so the admission gate and the cache interact exactly
    as they do in production.
    """
    monkeypatch.setattr(audio_render, "_cache_dir", lambda: str(tmp_path / "cache"))
    monkeypatch.setattr(audio_render, "_render_enabled", True)
    monkeypatch.setattr(audio_render, "_edge_pad_enabled", False)
    monkeypatch.setattr(audio_render, "_kernel_cache", OrderedDict())

    pairs = _SUPPORTED + [(11025, 96000), (16000, 48000), (32000, 44100),
                          (24000, 48000), (11025, 44100), (12000, 48000)]
    for rate_in, rate_out in pairs:
        src = tmp_path / f"cue_{rate_in}_{rate_out}.wav"
        _write_wav16(src, [7000] * 64, rate_in)
        assert audio_render.device_ready_wav(str(src), rate_out) is not None

    cache = audio_render._kernel_cache
    assert len(cache) <= audio_render._KERNEL_CACHE_MAX_ENTRIES
    assert _kernel_coeffs(cache) <= audio_render._KERNEL_CACHE_MAX_COEFFS
    # Every one of those ratios really was admitted and cached at least once.
    assert {key[0] for key in cache} == {
        rate_out // math.gcd(rate_in, rate_out) for rate_in, rate_out in pairs}


def test_eviction_never_invalidates_a_kernel_already_handed_out(monkeypatch):
    """Eviction drops the MAP's claim; a caller's own reference stays valid."""
    monkeypatch.setattr(audio_render, "_kernel_cache", OrderedDict())
    first = audio_render._polyphase_kernel(3, audio_render._TAPS, 0.5 / 3)
    snapshot = [row[:] for row in first]

    limit = audio_render._KERNEL_CACHE_MAX_ENTRIES
    for up in range(4, 4 + limit + 2):
        audio_render._polyphase_kernel(up, audio_render._TAPS, 0.5 / up)

    assert first == snapshot, "an in-flight render lost its kernel"
    rebuilt = audio_render._polyphase_kernel(3, audio_render._TAPS, 0.5 / 3)
    assert rebuilt is not first, "the entry really was evicted"
    assert rebuilt == snapshot, "and rebuilding yields the same filter"
