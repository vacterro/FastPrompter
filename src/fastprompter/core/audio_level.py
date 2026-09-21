"""Deterministic loudness analysis for Auto Level (T-1242 spec 13-16).

Auto Level answers ONE question: "is this WAV objectively much louder than
the common UI reference, and by how much should it be turned down?"  It is
attenuation-only on purpose:

* boosting a quiet file also boosts its noise floor, and a "+18 dB" answer
  on a hissy sample is exactly the kind of surprise the user asked us not to
  ship;
* the recommendation is written into the VISIBLE per-event Gain, so the user
  can read it, understand it and change it;
* no source WAV is ever rewritten.  Analysis reads; it never writes audio.

The analyzer is pure ``wave`` + ``array``, so it works in the packaged EXE
without extra dependencies.
"""

from __future__ import annotations

import json
import logging
import math
import os
import sys
import tempfile
import threading
import wave
from array import array
from dataclasses import dataclass

logger = logging.getLogger(__name__)

#: Bump when the measurement contract changes so cached results are orphaned.
ANALYZER_VERSION = 1

#: Target ACTIVE RMS.  -18 dBFS is where the shipped UI pack already sits.
TARGET_RMS_DBFS = -18.0

#: Never let a rendered peak reach 0 dBFS.
PEAK_CEILING_DBFS = -1.0

#: Measurement window.  Shorter windows smear a transient into the silence
#: around it; longer ones stop resolving a short blip at all.
WINDOW_S = 0.050

#: A window this far below the file's own peak is genuine silence, not
#: content, and must not drag the RMS down -- a 3 s cue with 2.5 s of tail
#: would otherwise measure as "quiet" and wrongly earn 0 dB.
SILENCE_GATE_DB = -40.0

GAIN_FLOOR_DB = -24.0
_FLOOR_DBFS = -120.0

_CACHE_DIR_NAME = "fastprompter_sound"
_CACHE_FILE = f"loudness_v{ANALYZER_VERSION}.json"
_CACHE_MAX = 512
_cache_lock = threading.RLock()
_cache: dict | None = None


@dataclass(frozen=True)
class Loudness:
    """What the analyzer measured, in the units the tooltip shows."""

    peak_dbfs: float
    active_rms_dbfs: float
    frames: int
    sample_rate: int
    channels: int

    @property
    def recommended_gain_db(self) -> float:
        """Attenuation-only recommendation, clamped to -24..0 dB."""
        by_rms = TARGET_RMS_DBFS - self.active_rms_dbfs
        by_peak = PEAK_CEILING_DBFS - self.peak_dbfs
        return max(GAIN_FLOOR_DB, min(0.0, by_rms, by_peak))

    def as_dict(self) -> dict:
        return {
            "peak_dbfs": round(self.peak_dbfs, 2),
            "active_rms_dbfs": round(self.active_rms_dbfs, 2),
            "recommended_gain_db": round(self.recommended_gain_db, 1),
            "frames": self.frames,
            "sample_rate": self.sample_rate,
            "channels": self.channels,
        }


def _dbfs(amplitude: float) -> float:
    if amplitude <= 0.0:
        return _FLOOR_DBFS
    return max(_FLOOR_DBFS, 20.0 * math.log10(amplitude))


def _read_mono(path: str):
    """(mono float samples, rate, channels) or None when not analyzable."""
    if sys.byteorder != "little":
        return None
    try:
        with wave.open(path, "rb") as wf:
            if wf.getcomptype() != "NONE":
                return None
            width = wf.getsampwidth()
            nch = wf.getnchannels()
            rate = wf.getframerate()
            nframes = wf.getnframes()
            if width not in (1, 2, 4) or nch < 1 or rate <= 0 or nframes <= 0:
                return None
            raw = wf.readframes(nframes)
    except (OSError, wave.Error, EOFError):
        logger.debug("loudness read failed for %s", path, exc_info=True)
        return None
    if width == 1:
        buf = array("B")
        buf.frombytes(raw)
        flat = [(s - 128) * (1.0 / 128.0) for s in buf]
    else:
        code = "h" if width == 2 else "i"
        buf = array(code)
        if buf.itemsize != width:
            return None
        buf.frombytes(raw[: len(raw) - (len(raw) % width)])
        scale = 1.0 / float(1 << (8 * width - 1))
        flat = [s * scale for s in buf]
    usable = (len(flat) // nch) * nch
    if usable <= 0:
        return None
    if nch == 1:
        mono = flat[:usable]
    else:
        mono = [sum(flat[i:i + nch]) / nch for i in range(0, usable, nch)]
    return mono, rate, nch


def measure(path: str) -> Loudness | None:
    """Measure ``path``; None when the file cannot be analyzed truthfully."""
    read = _read_mono(path)
    if read is None:
        return None
    mono, rate, nch = read
    if not mono:
        return None
    # DC removal for MEASUREMENT ONLY -- the source file is never touched.
    mean = sum(mono) / len(mono)
    if abs(mean) > 1e-6:
        mono = [s - mean for s in mono]
    peak = max((abs(s) for s in mono), default=0.0)
    if peak <= 0.0:
        return None                      # digital silence: nothing to level
    window = max(1, int(rate * WINDOW_S))
    gate = peak * (10.0 ** (SILENCE_GATE_DB / 20.0))
    energy = 0.0
    counted = 0
    for start in range(0, len(mono), window):
        chunk = mono[start:start + window]
        if not chunk:
            continue
        acc = 0.0
        for sample in chunk:
            acc += sample * sample
        if math.sqrt(acc / len(chunk)) < gate:
            continue                     # documented silence gate
        energy += acc
        counted += len(chunk)
    if counted == 0:                     # everything gated: use the whole file
        acc = 0.0
        for sample in mono:
            acc += sample * sample
        energy, counted = acc, len(mono)
    active_rms = math.sqrt(energy / counted) if counted else 0.0
    return Loudness(
        peak_dbfs=_dbfs(peak),
        active_rms_dbfs=_dbfs(active_rms),
        frames=len(mono),
        sample_rate=rate,
        channels=nch,
    )


# ---- cache ----------------------------------------------------------------


def _cache_path() -> str:
    return os.path.join(tempfile.gettempdir(), _CACHE_DIR_NAME, _CACHE_FILE)


def _load_cache() -> dict:
    global _cache
    if _cache is not None:
        return _cache
    data: dict = {}
    try:
        with open(_cache_path(), encoding="utf-8") as fh:
            loaded = json.load(fh)
        if isinstance(loaded, dict):
            data = {k: v for k, v in loaded.items() if isinstance(v, dict)}
    except (OSError, ValueError):
        data = {}
    _cache = data
    return data


def _store_cache(digest: str, payload: dict) -> None:
    data = _load_cache()
    data[digest] = payload
    if len(data) > _CACHE_MAX:
        for key in list(data)[: len(data) - _CACHE_MAX]:
            data.pop(key, None)
    path = _cache_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".part"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh)
        os.replace(tmp, path)
    except OSError:
        logger.debug("loudness cache write failed", exc_info=True)


def reset_cache() -> None:
    """Forget the in-process cache (tests)."""
    global _cache
    with _cache_lock:
        _cache = None


def _digest(path: str) -> str | None:
    import hashlib

    digest = hashlib.sha256()
    try:
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(65536), b""):
                digest.update(chunk)
    except OSError:
        return None
    return digest.hexdigest()


def analyze(path: str) -> dict | None:
    """Cached ``measure()`` keyed by source SHA256 + analyzer version.

    Returns the tooltip-ready dict, or None when the file cannot be analyzed
    -- callers must then say "Auto unavailable for this file" rather than
    invent a gain.
    """
    if not path or not os.path.isfile(path):
        return None
    digest = _digest(path)
    with _cache_lock:
        if digest:
            hit = _load_cache().get(digest)
            if isinstance(hit, dict) and "recommended_gain_db" in hit:
                return dict(hit)
        result = measure(path)
        if result is None:
            return None
        payload = result.as_dict()
        if digest:
            _store_cache(digest, payload)
        return payload


def recommended_gain_db(path: str) -> float | None:
    """The visible negative gain Auto Level would store, or None."""
    payload = analyze(path)
    if payload is None:
        return None
    return float(payload["recommended_gain_db"])
