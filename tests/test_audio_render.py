"""T-1242: audio_render fidelity + cache identity contract.

The out-of-band render patch is audited before anything builds on it:

- cache identity is the SOURCE CONTENT digest (+rate+version), never the
  basename, so builtin:ui/click.wav and user:imported/click.wav can never
  share one rendered file;
- the resampler (if it engages at all) is timing- and amplitude-transparent:
  an impulse stays where it was placed, DC stays DC, stereo stays
  independent, duration is preserved;
- the scaled-WAV cache in sound_manager carries the same identity fix.
"""

from __future__ import annotations

import os
import struct
import sys
import wave
from array import array

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

from fastprompter.core import audio_render  # noqa: E402
from fastprompter.core.sound_manager import scaled_wav_path  # noqa: E402


@pytest.fixture(autouse=True)
def _render_switch_on(monkeypatch):
    """This suite pins the RENDERER's own contract, so both A/B switches are
    pinned ON here.  In the product they default OFF (T-1242 spec 8/9: raw
    playback is the control path until the repeated-play matrix proves the
    renderer); the shipped defaults are pinned in test_audio_render_defaults."""
    monkeypatch.setattr(audio_render, "_render_enabled", True)
    monkeypatch.setattr(audio_render, "_edge_pad_enabled", True)


def _write_wav16(path, channels, rate):
    """Write a 16-bit PCM WAV from a list of per-channel sample lists."""
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


def _read_wav16(path):
    with wave.open(path, "rb") as fh:
        rate = fh.getframerate()
        n = fh.getnframes()
        nch = fh.getnchannels()
        raw = fh.readframes(n)
    samples = struct.unpack(f"<{n * nch}h", raw)
    return [list(samples[i::nch]) for i in range(nch)], rate


@pytest.fixture()
def rate_44100(monkeypatch):
    """Pin the target device rate so tests are hardware-independent."""
    monkeypatch.setattr(audio_render, "device_sample_rate", lambda: 44100)
    return 44100


def test_render_version_is_bumped_after_the_algorithm_change():
    """The cache filename carries a render version; the group-delay fix and
    the digest key are algorithm changes, so v2+ must be pinned."""
    assert audio_render.RENDER_VERSION >= 2


class TestCacheIdentity:
    def test_same_basename_different_content_never_shares_cache(self,
                                                                tmp_path,
                                                                rate_44100,
                                                                monkeypatch):
        monkeypatch.setattr(audio_render, "_CACHE_DIR_NAME",
                            "fp_test_render_identity")
        a = tmp_path / "click.wav"
        b = tmp_path / "sub"
        b.mkdir()
        c = b / "click.wav"
        # Same basename, different PCM content: the old <stem>_r<rate>.wav
        # key collided these two into one file.
        _write_wav16(str(a), [[1000, -1000] * 64], 22050)
        _write_wav16(str(c), [[9000, -9000] * 64], 22050)
        out_a = audio_render.device_ready_wav(str(a), 44100)
        out_c = audio_render.device_ready_wav(str(c), 44100)
        assert out_a and out_c
        assert os.path.normpath(out_a) != os.path.normpath(out_c)
        # And each cache file plays back its own content.
        (cha,), _ = _read_wav16(out_a)
        (chc,), _ = _read_wav16(out_c)
        assert max(abs(v) for v in cha) < max(abs(v) for v in chc)

    def test_cache_key_embeds_the_content_digest(self, tmp_path, rate_44100,
                                                 monkeypatch):
        monkeypatch.setattr(audio_render, "_CACHE_DIR_NAME",
                            "fp_test_render_identity")
        src = tmp_path / "blip.wav"
        _write_wav16(str(src), [[500] * 32], 22050)
        out = audio_render.device_ready_wav(str(src), 44100)
        assert out is not None
        digest = audio_render._source_digest(str(src))
        assert digest and digest in os.path.basename(out)

    def test_unchanged_source_reuses_the_cache_file(self, tmp_path,
                                                    rate_44100, monkeypatch):
        monkeypatch.setattr(audio_render, "_CACHE_DIR_NAME",
                            "fp_test_render_identity")
        src = tmp_path / "blip.wav"
        _write_wav16(str(src), [[700, -700] * 32], 22050)
        first = audio_render.device_ready_wav(str(src), 44100)
        second = audio_render.device_ready_wav(str(src), 44100)
        assert first == second
        assert os.path.isfile(first)

    def test_same_rate_returns_none_no_render_needed(self, tmp_path,
                                                     no_edge_pad,
                                                     rate_44100):
        src = tmp_path / "same.wav"
        _write_wav16(str(src), [[1] * 16], 44100)
        assert audio_render.device_ready_wav(str(src), 44100) is None


@pytest.fixture
def no_edge_pad(monkeypatch):
    """These cases pin the RESAMPLER, not the short-cue silence margins.

    The margins are a separate contract (see TestEdgePadding) and would
    otherwise show up as extra leading/trailing frames in every assertion.
    """
    monkeypatch.setattr(audio_render, "_edge_pad_enabled", False)


class TestResamplerContract:
    def _render(self, tmp_path, channels, src_rate, monkeypatch):
        monkeypatch.setattr(audio_render, "_CACHE_DIR_NAME",
                            "fp_test_render_dsp")
        src = tmp_path / "sig.wav"
        _write_wav16(str(src), channels, src_rate)
        out = audio_render.device_ready_wav(str(src), 44100)
        assert out is not None
        rendered, out_rate = _read_wav16(out)
        assert out_rate == 44100
        return rendered

    def test_impulse_stays_at_its_scaled_position(self, tmp_path, monkeypatch, no_edge_pad):
        # 22050 -> 44100 doubles the timeline: an impulse at source sample
        # 100 must land at output sample ~200 (±2).  The pre-fix causal FIR
        # put it ~0.35 ms late; group delay is now compensated.
        impulse = [0] * 400
        impulse[100] = 30000
        rendered = self._render(tmp_path, [impulse], 22050, monkeypatch)
        peak_index = max(range(len(rendered[0])),
                         key=lambda i: abs(rendered[0][i]))
        assert abs(peak_index - 200) <= 2

    def test_impulse_amplitude_is_band_limited_not_crushed(
            self, tmp_path, monkeypatch):
        # A single-sample impulse carries energy up to Nyquist; ANY correct
        # band-limited resampler attenuates its peak (anti-imaging droop).
        # Passband transparency is proven by the DC/sine tests; here we only
        # require the impulse survives recognisably (no crushing, no gain).
        impulse = [0] * 400
        impulse[100] = 30000
        rendered = self._render(tmp_path, [impulse], 22050, monkeypatch)
        peak = max(abs(v) for v in rendered[0])
        assert 0.85 * 30000 <= peak <= 30000

    def test_dc_is_unity(self, tmp_path, monkeypatch, no_edge_pad):
        rendered = self._render(tmp_path, [[100] * 441], 22050, monkeypatch)
        mean = sum(rendered[0]) / len(rendered[0])
        assert mean == pytest.approx(100, rel=0.05)

    def test_full_scale_sine_keeps_amplitude_without_clipping(
            self, tmp_path, monkeypatch, no_edge_pad):
        import math
        sine = [int(32000 * math.sin(2 * math.pi * 1000 * i / 22050))
                for i in range(2205)]
        rendered = self._render(tmp_path, [sine], 22050, monkeypatch)
        peak = max(abs(v) for v in rendered[0])
        assert peak <= 32767
        assert peak == pytest.approx(32000, rel=0.05)

    def test_stereo_channels_stay_independent(self, tmp_path, monkeypatch, no_edge_pad):
        left = [0] * 400
        left[50] = 20000
        right = [0] * 400
        right[150] = 20000
        rendered = self._render(tmp_path, [left, right], 22050, monkeypatch)
        l_peak = max(range(len(rendered[0])), key=lambda i: abs(rendered[0][i]))
        r_peak = max(range(len(rendered[1])), key=lambda i: abs(rendered[1][i]))
        assert abs(l_peak - 100) <= 2
        assert abs(r_peak - 300) <= 2

    def test_duration_is_preserved(self, tmp_path, monkeypatch, no_edge_pad):
        tone = [1000] * 2205  # exactly 100 ms at 22050
        rendered = self._render(tmp_path, [tone], 22050, monkeypatch)
        expected = round(0.1 * 44100)
        assert len(rendered[0]) == pytest.approx(expected, rel=0.01)


class TestScaledCacheIdentity:
    def test_scaled_cache_uses_content_digest_not_basename(self, tmp_path,
                                                           monkeypatch):
        monkeypatch.setattr("fastprompter.core.sound_manager._scaled_cache_dir",
                            lambda: str(tmp_path / "scaled"))
        a = tmp_path / "ding.wav"
        b_dir = tmp_path / "other"
        b_dir.mkdir()
        b = b_dir / "ding.wav"
        _write_wav16(str(a), [[20000, -20000] * 100], 44100)
        _write_wav16(str(b), [[1000, -1000] * 100], 44100)
        pa = scaled_wav_path(str(a), 0.5)
        pb = scaled_wav_path(str(b), 0.5)
        assert pa and pb
        assert os.path.normpath(pa) != os.path.normpath(pb)
        (cha,), _ = _read_wav16(pa)
        (chb,), _ = _read_wav16(pb)
        # each cache holds ITS OWN source, halved
        assert max(abs(v) for v in cha) == pytest.approx(10000, rel=0.02)
        assert max(abs(v) for v in chb) == pytest.approx(500, rel=0.02)


class TestEdgePadding:
    """Short cues get silent margins so the output sink's own start/stop
    transition lands on silence instead of on the transient (user-reported:
    "the blip is cut at the beginning and the end")."""

    def _render_and_read(self, tmp_path, monkeypatch, frames, rate,
                         target=48000):
        monkeypatch.setattr(audio_render, "_cache_dir",
                            lambda: str(tmp_path / "cache"))
        src = tmp_path / "cue.wav"
        _write_wav16(str(src), [frames], rate)
        out = audio_render.device_ready_wav(str(src), target)
        assert out is not None
        with wave.open(out, "rb") as wf:
            data = array("h")
            data.frombytes(wf.readframes(wf.getnframes()))
            return list(data), wf.getframerate()

    def test_a_short_cue_gains_silent_margins(self, tmp_path, monkeypatch):
        frames = [12000, -12000] * 500          # ~45 ms at 22050
        rendered, rate = self._render_and_read(tmp_path, monkeypatch,
                                               frames, 22050)
        head = int(round(rate * audio_render.EDGE_PAD_HEAD_MS / 1000))
        tail = int(round(rate * audio_render.EDGE_PAD_TAIL_MS / 1000))
        assert head > 0 and tail > 0
        assert all(v == 0 for v in rendered[:head])
        assert all(v == 0 for v in rendered[-tail:])

    def test_the_margins_are_silence_not_a_fade(self, tmp_path, monkeypatch):
        frames = [12000] * 400
        rendered, rate = self._render_and_read(tmp_path, monkeypatch,
                                               frames, 22050)
        head = int(round(rate * audio_render.EDGE_PAD_HEAD_MS / 1000))
        assert set(rendered[:head]) == {0}
        # the first real sample is full level, not a ramp
        assert abs(rendered[head + 40]) > 10000

    def test_the_audio_between_the_margins_is_untouched(self, tmp_path,
                                                        monkeypatch):
        frames = [8000, -8000] * 300
        padded, rate = self._render_and_read(tmp_path, monkeypatch,
                                             frames, 22050)
        monkeypatch.setattr(audio_render, "_edge_pad_enabled", False)
        bare_dir = tmp_path / "b"
        bare_dir.mkdir()
        bare, _rate = self._render_and_read(bare_dir, monkeypatch,
                                            frames, 22050)
        head = int(round(rate * audio_render.EDGE_PAD_HEAD_MS / 1000))
        assert padded[head:head + len(bare)] == bare

    def test_a_long_source_is_not_padded(self, tmp_path, monkeypatch):
        seconds = audio_render.EDGE_PAD_MAX_SECONDS + 1.0
        frames = [1000] * int(22050 * seconds)
        rendered, rate = self._render_and_read(tmp_path, monkeypatch,
                                               frames, 22050)
        assert rendered[0] != 0

    def test_the_switch_turns_the_margins_off(self, tmp_path, monkeypatch):
        monkeypatch.setattr(audio_render, "_edge_pad_enabled", False)
        rendered, _rate = self._render_and_read(tmp_path, monkeypatch,
                                                [9000] * 400, 22050)
        assert rendered[0] != 0

    def test_padding_alone_is_enough_to_earn_a_render(self, tmp_path,
                                                      monkeypatch):
        """A file ALREADY at the device rate still gets its margins."""
        monkeypatch.setattr(audio_render, "_cache_dir",
                            lambda: str(tmp_path / "cache"))
        src = tmp_path / "same.wav"
        _write_wav16(str(src), [[7000] * 400], 48000)
        out = audio_render.device_ready_wav(str(src), 48000)
        assert out is not None
        with wave.open(out, "rb") as wf:
            assert wf.getframerate() == 48000
            assert wf.getnframes() > 400

    def test_the_cache_name_records_whether_it_is_padded(self, tmp_path,
                                                         monkeypatch):
        monkeypatch.setattr(audio_render, "_cache_dir",
                            lambda: str(tmp_path / "cache"))
        src = tmp_path / "c.wav"
        _write_wav16(str(src), [[7000] * 400], 22050)
        padded = audio_render.device_ready_wav(str(src), 48000)
        monkeypatch.setattr(audio_render, "_edge_pad_enabled", False)
        bare = audio_render.device_ready_wav(str(src), 48000)
        assert padded != bare


class TestPurePythonResamplerMatchesNumpy:
    """The numpy-free renderer must be the SAME filter, not a similar one.

    numpy is not a declared dependency and ``_numpy_if_safe()`` refuses to
    import it from a worker thread, so the pure-Python branch is what a
    packaged build (and every render started off the main thread before
    numpy is resolved) actually runs -- for short cues, i.e. the Problip
    blips.  It read its polyphase branch as ``x[start + k]`` instead of
    ``x[start - k]``, which walks the kernel backwards through the source:
    a different, phase-scrambled filter whose output was then cached on
    disk and replayed ("sounds like it is coming out of a bucket").
    """

    @staticmethod
    def _pure(channels, rate_in, rate_out, monkeypatch):
        monkeypatch.setattr(audio_render, "_numpy_if_safe", lambda: None)
        return audio_render._resample(channels, rate_in, rate_out)

    @pytest.mark.parametrize("rate_in,rate_out",
                             [(44100, 48000), (22050, 48000), (48000, 44100)])
    def test_pure_python_equals_the_numpy_path(self, rate_in, rate_out,
                                               monkeypatch):
        import math

        if audio_render._numpy_if_safe() is None:
            pytest.skip("numpy unavailable; nothing to compare against")
        source = [[math.sin(2.0 * math.pi * 1000.0 * i / rate_in)
                   for i in range(rate_in // 10)]]
        fast = audio_render._resample(source, rate_in, rate_out)
        slow = self._pure(source, rate_in, rate_out, monkeypatch)
        assert len(slow[0]) == len(fast[0])
        assert max(abs(a - b) for a, b in zip(fast[0], slow[0])) < 1e-9

    def test_pure_python_reproduces_the_input_sine(self, monkeypatch):
        """Independent of numpy: 1 kHz in, 1 kHz out, same amplitude."""
        import math

        rate_in, rate_out = 44100, 48000
        source = [[math.sin(2.0 * math.pi * 1000.0 * i / rate_in)
                   for i in range(rate_in // 10)]]
        out = self._pure(source, rate_in, rate_out, monkeypatch)[0]
        ideal = [math.sin(2.0 * math.pi * 1000.0 * i / rate_out)
                 for i in range(len(out))]
        body = slice(200, len(out) - 200)
        worst = max(abs(a - b) for a, b in zip(out[body], ideal[body]))
        assert worst < 0.01, f"pure-Python resampler is not transparent: {worst}"
