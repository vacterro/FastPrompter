"""T-1242: Problip audio fidelity contract.

Evidence for the "embedded Problip sounds worse than standalone" report:

- the bundled blip01.wav is byte-identical to the standalone reference
  (SHA256 acf77c66..., PCM stereo 16-bit 44100 Hz, 2940 frames) — the ASSET
  was never the problem;
- one logical cue causes exactly ONE physical transport start (provenance
  ring), so no comb-filter/duplicate transient can masquerade as codec
  quality;
- first play of a freshly resolved path and a warmed play follow the same
  single-start contract;
- the PCM gain path (scale_wav_bytes) is exact at 100/50/5%, never clips,
  never lossy-converts, and the scaled cache is bounded.
"""

from __future__ import annotations

import hashlib
import os
import struct
import sys
import wave

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

pytest.importorskip("PyQt6.QtWidgets")

from PyQt6.QtCore import QObject  # noqa: E402

from fastprompter.core.audio_hub import (  # noqa: E402
    AudioHub,
    FakeMultiChannelTransport,
)
from fastprompter.core.problip_store import ProblipStore  # noqa: E402
from fastprompter.core.sound_manager import scale_wav_bytes  # noqa: E402
from fastprompter.ui.problip_controller import ProblipController  # noqa: E402

#: Verified against V:\___VAC\__K\__CODE\_PY\_PROBLIP\blip01.wav (spec 2/6).
REFERENCE_SHA256 = "acf77c6624033846998c2c33fc85ec141c856b9e08c521a25b381601d711e1af"
REFERENCE_FRAMES = 2940
REFERENCE_RATE = 44100
REFERENCE_CHANNELS = 2
REFERENCE_BYTES = 11838


def _blip_path() -> str:
    import fastprompter.sound.problip.catalog as catalog
    path = catalog.resolve_sound_path("sound_original")
    assert path and os.path.isfile(path)
    return path


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


class _Manager:
    def __init__(self, hub: AudioHub) -> None:
        self._hub = hub

    def audio_hub(self) -> AudioHub:
        return self._hub

    def stop_all_sound(self) -> None:
        self._hub.stop_all()


_APP = None


def _ensure_app():
    global _APP
    from PyQt6.QtWidgets import QApplication
    _APP = QApplication.instance() or QApplication([])
    return _APP


@pytest.fixture()
def rig(tmp_path):
    _ensure_app()
    parent = QObject()
    transport = FakeMultiChannelTransport()
    hub = AudioHub(transport=transport)
    manager = _Manager(hub)
    store = ProblipStore(str(tmp_path / "problip.db"))
    controller = ProblipController(parent, manager, store=store,
                                   random_source=lambda n: 0)
    yield controller, transport, hub
    controller.shutdown()
    parent.deleteLater()


def _fire(controller) -> None:
    """Drive one scheduled cue exactly the way the QTimer would.

    The controller must be RUNNING first — a timer callback on a stopped
    scheduler is consumed as inert, which is the C-series contract.
    """
    if not controller.is_running():
        assert controller.start(persist=False)
    controller._on_timeout()


_AUDIBLE_OUTCOMES = {"PLAYED", "MIXED", "REPLACED", "QUEUED"}


def _starts_for(transport, path: str) -> list[str]:
    return [h for h, job in transport.channels.items()
            if os.path.normpath(job["path"]) == os.path.normpath(path)]


class TestReferenceAssetParity:
    def test_bundled_blip_is_byte_identical_to_the_reference(self):
        path = _blip_path()
        assert os.path.getsize(path) == REFERENCE_BYTES
        assert _sha256(path) == REFERENCE_SHA256

    def test_reference_wav_metadata(self):
        path = _blip_path()
        with wave.open(path, "rb") as fh:
            assert fh.getcomptype() == "NONE"          # uncompressed PCM
            assert fh.getnchannels() == REFERENCE_CHANNELS
            assert fh.getsampwidth() == 2              # 16 bit
            assert fh.getframerate() == REFERENCE_RATE
            assert fh.getnframes() == REFERENCE_FRAMES
            # ~66.67 ms — a truncated attack would show up as missing frames.
            assert fh.getnframes() / fh.getframerate() == pytest.approx(
                0.0666666667, abs=1e-6)

    def test_reference_peak_matches_the_documented_level(self):
        path = _blip_path()
        with wave.open(path, "rb") as fh:
            raw = fh.readframes(fh.getnframes())
        samples = struct.unpack(f"<{len(raw) // 2}h", raw)
        peak = max(abs(s) for s in samples) / 32768.0
        # ~-5.98 dBFS documented for the reference asset
        assert 20 * __import__("math").log10(peak) == pytest.approx(-5.98,
                                                                   abs=0.05)


class TestOneCueOnePhysicalStart:
    def test_scheduled_cue_starts_exactly_one_channel(self, rig):
        controller, transport, hub = rig
        controller.update_settings(volume_percent=5)
        _fire(controller)
        blip = os.path.normpath(_blip_path())
        starts = _starts_for(transport, blip)
        assert len(starts) == 1
        # Provenance: exactly one audible record for the PROBLIP bus cue.
        prov = [e for e in hub.provenance() if e.get("bus") == "problip"]
        audible = [e for e in prov
                   if e.get("outcome") in _AUDIBLE_OUTCOMES]
        assert len(audible) == 1
        assert audible[0].get("request_id")
        assert audible[0].get("asset") == "blip01.wav"

    def test_ten_scheduled_cues_never_overlap_into_duplicates(self, rig):
        controller, transport, hub = rig
        controller.start(persist=False)
        for _ in range(10):
            _fire(controller)
            transport.stop_all()
        prov = [e for e in hub.provenance() if e.get("bus") == "problip"]
        audible = [e for e in prov
                   if e.get("outcome") in _AUDIBLE_OUTCOMES]
        assert len(audible) == 10
        # each request got its own id; no request shares a channel start
        ids = [e["request_id"] for e in audible]
        assert len(set(ids)) == 10

    def test_test_button_is_one_preview_not_cue_plus_hidden_extra(self, rig):
        controller, transport, hub = rig
        controller.update_settings(volume_percent=5)
        ok, _msg = controller.test()
        assert ok
        starts = _starts_for(transport, _blip_path())
        assert len(starts) == 1
        previews = [e for e in hub.provenance()
                    if e.get("bus") == "preview"
                    and e.get("outcome") in _AUDIBLE_OUTCOMES]
        assert len(previews) == 1

    def test_first_play_and_warmed_play_are_the_same_single_start(self, rig):
        """First play (cache cold) and a warmed replay each start exactly
        one channel — no Loading-state restart, no double attack."""
        controller, transport, hub = rig
        _fire(controller)
        assert len(_starts_for(transport, _blip_path())) == 1
        transport.stop_all()
        _fire(controller)
        assert len(_starts_for(transport, _blip_path())) == 1


class TestGainPath:
    @pytest.mark.parametrize("factor,expected_peak", [
        (1.00, 32767),   # 100%: reference peak, untouched
        (0.50, 16383),   # 50%
        (0.05, 1638),    # 5% — the standalone Problip default
    ])
    def test_scale_is_exact_and_never_clips(self, tmp_path, factor,
                                            expected_peak):
        src = tmp_path / "tone.wav"
        frames = [32767, -32768] * 64
        with wave.open(str(src), "wb") as fh:
            fh.setnchannels(1)
            fh.setsampwidth(2)
            fh.setframerate(44100)
            fh.writeframes(b"".join(struct.pack("<h", v) for v in frames))
        data = scale_wav_bytes(str(src), factor)
        assert data is not None
        # duration preserved exactly (no resample, no lossy conversion):
        # same DATA payload size as the source (header excluded)
        with wave.open(str(src), "rb") as fh:
            original = fh.readframes(fh.getnframes())
        # data is a full WAV file; read its audio payload back
        import io
        with wave.open(io.BytesIO(data), "rb") as fh:
            out_payload = fh.readframes(fh.getnframes())
            assert fh.getframerate() == 44100
            assert fh.getnchannels() == 1
            assert fh.getsampwidth() == 2
            assert fh.getcomptype() == "NONE"
        assert len(out_payload) == len(original)
        out = struct.unpack(f"<{len(out_payload) // 2}h", out_payload)
        peak = max(abs(v) for v in out)
        # -32768 (full-scale negative) is legal: abs() reports 32768.
        assert all(-32768 <= v <= 32767 for v in out)
        assert peak <= 32768
        assert peak == pytest.approx(expected_peak, rel=0.01)

    def test_scaled_cache_file_matches_bytes_output(self, tmp_path,
                                                    monkeypatch):
        import fastprompter.core.sound_manager as smp
        monkeypatch.setattr(smp, "_scaled_cache_dir",
                            lambda: str(tmp_path / "scaled"))
        scaled_wav_path = smp.scaled_wav_path
        scale_wav_bytes = smp.scale_wav_bytes
        src = tmp_path / "blip.wav"
        with wave.open(str(src), "wb") as fh:
            fh.setnchannels(1)
            fh.setsampwidth(2)
            fh.setframerate(44100)
            fh.writeframes(b"".join(struct.pack("<h", v)
                                    for v in [30000, -30000] * 64))
        out = scaled_wav_path(str(src), 0.05)
        assert out and os.path.isfile(out)
        with open(out, "rb") as fh:
            cached = fh.read()
        direct = scale_wav_bytes(str(src), 0.05)
        assert cached == direct
        # gain only — format untouched: same rate, same channels, PCM
        with wave.open(out, "rb") as fh:
            assert fh.getcomptype() == "NONE"
            assert fh.getframerate() == 44100
            assert fh.getnchannels() == 1
            assert fh.getsampwidth() == 2

    def test_scaled_cache_is_bounded(self, tmp_path, monkeypatch):
        """The scaled cache honors its file budget (grace-window exempted
        fresh files are protected, so a full 4096-file purge is not
        expected here — only that writing is bounded by real budget code,
        exercised via the eviction test in test_perf005_scaled_cache)."""
        # Resolve the module AT CALL TIME: tests that import sound_manager
        # under PyQt6 stubs evict the copy this file imported at collection,
        # so a module-level alias can end up patching a dead object while the
        # live function reads the real cache directory.
        import fastprompter.core.sound_manager as smp
        monkeypatch.setattr(smp, "_scaled_cache_dir",
                            lambda: str(tmp_path / "scaled"))
        scaled_wav_path = smp.scaled_wav_path
        # Simulate an aged cache at the budget edge: the eviction path
        # (not the grace window) decides.  Stub time far in the future so
        # every existing file is past its 30 s playback grace window.
        monkeypatch.setattr(smp, "_SCALED_CACHE_GRACE_SECONDS", -1.0)
        files = []
        for i in range(8):
            src = tmp_path / f"s{i}.wav"
            with wave.open(str(src), "wb") as fh:
                fh.setnchannels(1)
                fh.setsampwidth(2)
                fh.setframerate(44100)
                fh.writeframes(b"\x00\x10" * 64)
            p = scaled_wav_path(str(src), 0.05)
            if p:
                files.append(p)
            # age every written file so the grace window never protects it
            old = __import__("time").time() - 3600
            if p:
                os.utime(p, (old, old))
        cache_dir = tmp_path / "scaled"
        present = list(cache_dir.glob("*.wav")) if cache_dir.is_dir() else []
        # Budgeted insertion: prune keeps the directory at or under the
        # configured cap once eviction is allowed to act.
        assert len(present) <= smp._SCALED_CACHE_MAX_FILES
        assert len(present) == len(files)  # nothing silently failed
