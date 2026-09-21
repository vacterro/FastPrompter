"""T-1242 spec 13-16: Auto Level is deterministic, attenuation-only analysis.

It must never boost, never rewrite a source WAV, never invent a gain for a
file it cannot read, and it must show its own arithmetic.
"""

import hashlib
import math
import struct
import wave

import pytest

from fastprompter.core import audio_level


def _write_wav(path, samples, rate=44100, channels=1, width=2):
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(width)
        wf.setframerate(rate)
        frames = bytearray()
        for value in samples:
            clipped = max(-1.0, min(1.0, value))
            frames += struct.pack("<h", int(clipped * 32767))
        wf.writeframes(bytes(frames))
    return str(path)


def _sine(amplitude, seconds=0.5, rate=44100, freq=440.0):
    count = int(rate * seconds)
    return [amplitude * math.sin(2 * math.pi * freq * i / rate)
            for i in range(count)]


@pytest.fixture(autouse=True)
def _fresh_cache():
    audio_level.reset_cache()
    yield
    audio_level.reset_cache()


class TestMeasurement:
    def test_a_full_scale_sine_measures_near_zero_dbfs_peak(self, tmp_path):
        path = _write_wav(tmp_path / "loud.wav", _sine(0.99))
        result = audio_level.measure(path)
        assert result is not None
        assert result.peak_dbfs == pytest.approx(0.0, abs=0.2)
        # A sine's RMS is peak/sqrt(2) = -3 dB below peak.
        assert result.active_rms_dbfs == pytest.approx(-3.0, abs=0.3)

    def test_a_quiet_sine_measures_quiet(self, tmp_path):
        path = _write_wav(tmp_path / "quiet.wav", _sine(0.05))
        result = audio_level.measure(path)
        assert result.peak_dbfs == pytest.approx(-26.0, abs=0.5)

    def test_digital_silence_is_not_analyzable_rather_than_minus_infinity(
            self, tmp_path):
        path = _write_wav(tmp_path / "silence.wav", [0.0] * 4410)
        assert audio_level.measure(path) is None

    def test_a_long_silent_tail_does_not_drag_the_active_rms_down(self, tmp_path):
        loud = _sine(0.7, seconds=0.3)
        with_tail = loud + [0.0] * int(44100 * 3.0)
        a = audio_level.measure(_write_wav(tmp_path / "a.wav", loud))
        b = audio_level.measure(_write_wav(tmp_path / "b.wav", with_tail))
        assert b.active_rms_dbfs == pytest.approx(a.active_rms_dbfs, abs=1.0)

    def test_a_dc_offset_is_removed_for_measurement(self, tmp_path):
        biased = [0.5 + v for v in _sine(0.2)]
        result = audio_level.measure(_write_wav(tmp_path / "dc.wav", biased))
        clean = audio_level.measure(_write_wav(tmp_path / "clean.wav", _sine(0.2)))
        assert result.active_rms_dbfs == pytest.approx(
            clean.active_rms_dbfs, abs=0.5)

    def test_stereo_is_accepted(self, tmp_path):
        rate = 44100
        interleaved = []
        for value in _sine(0.5, seconds=0.2):
            interleaved.extend((value, value))
        path = _write_wav(tmp_path / "st.wav", interleaved, rate=rate,
                          channels=2)
        result = audio_level.measure(path)
        assert result is not None
        assert result.channels == 2


class TestRecommendation:
    def test_a_loud_file_earns_negative_compensation(self, tmp_path):
        path = _write_wav(tmp_path / "loud.wav", _sine(0.99))
        gain = audio_level.recommended_gain_db(path)
        assert gain < -10.0

    def test_a_quiet_file_is_never_boosted(self, tmp_path):
        path = _write_wav(tmp_path / "quiet.wav", _sine(0.02))
        assert audio_level.recommended_gain_db(path) == 0.0

    def test_the_recommendation_never_exceeds_zero(self, tmp_path):
        for amplitude in (0.001, 0.01, 0.1, 0.3, 0.6, 0.99):
            path = _write_wav(tmp_path / f"s{amplitude}.wav", _sine(amplitude))
            assert audio_level.recommended_gain_db(path) <= 0.0

    def test_the_recommendation_never_goes_below_the_floor(self, tmp_path):
        # A full-scale square wave: the loudest thing 16-bit PCM can carry.
        square = [0.999 if (i // 20) % 2 == 0 else -0.999 for i in range(44100)]
        path = _write_wav(tmp_path / "max.wav", square)
        gain = audio_level.recommended_gain_db(path)
        assert gain is not None
        assert gain >= audio_level.GAIN_FLOOR_DB

    def test_the_peak_ceiling_binds_when_it_is_stricter(self, tmp_path):
        # A short full-scale click: its ACTIVE rms is modest but the peak is
        # at 0 dBFS, so the ceiling must be what decides.
        samples = [0.0] * 2205 + [0.999, -0.999] * 1102 + [0.0] * 2205
        path = _write_wav(tmp_path / "click.wav", samples)
        result = audio_level.measure(path)
        gain = result.recommended_gain_db
        assert gain <= audio_level.PEAK_CEILING_DBFS - result.peak_dbfs + 1e-6

    def test_the_recommendation_is_deterministic(self, tmp_path):
        path = _write_wav(tmp_path / "d.wav", _sine(0.8))
        first = audio_level.measure(path).recommended_gain_db
        audio_level.reset_cache()
        assert audio_level.measure(path).recommended_gain_db == first


class TestSourceIntegrity:
    def test_analysis_never_mutates_the_source_wav(self, tmp_path):
        path = _write_wav(tmp_path / "src.wav", _sine(0.9))
        before = hashlib.sha256(open(path, "rb").read()).hexdigest()
        audio_level.analyze(path)
        audio_level.reset_cache()
        audio_level.analyze(path)
        after = hashlib.sha256(open(path, "rb").read()).hexdigest()
        assert after == before


class TestUnanalyzable:
    def test_a_missing_file_yields_none_not_a_guessed_gain(self, tmp_path):
        assert audio_level.analyze(str(tmp_path / "nope.wav")) is None
        assert audio_level.recommended_gain_db(str(tmp_path / "nope.wav")) is None

    def test_a_non_wav_file_yields_none(self, tmp_path):
        path = tmp_path / "junk.wav"
        path.write_bytes(b"not a riff at all")
        assert audio_level.analyze(str(path)) is None


class TestCache:
    def test_the_result_is_cached_by_content_digest(self, tmp_path, monkeypatch):
        path = _write_wav(tmp_path / "c.wav", _sine(0.5))
        first = audio_level.analyze(path)
        calls = []
        monkeypatch.setattr(audio_level, "measure",
                            lambda p: calls.append(p))
        again = audio_level.analyze(path)
        assert again == first
        assert calls == []          # served from the cache, no re-scan

    def test_changing_the_file_contents_invalidates_naturally(self, tmp_path):
        path = tmp_path / "v.wav"
        _write_wav(path, _sine(0.05))
        quiet = audio_level.analyze(str(path))
        _write_wav(path, _sine(0.99))
        loud = audio_level.analyze(str(path))
        assert loud["peak_dbfs"] > quiet["peak_dbfs"] + 10

    def test_the_payload_carries_the_numbers_the_tooltip_shows(self, tmp_path):
        path = _write_wav(tmp_path / "t.wav", _sine(0.9))
        payload = audio_level.analyze(path)
        assert set(payload) >= {"peak_dbfs", "active_rms_dbfs",
                                "recommended_gain_db", "sample_rate",
                                "channels", "frames"}
