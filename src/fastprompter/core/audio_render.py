"""Device-rate WAV pre-rendering (audio quality, A/B evidence pending).

What this module does
---------------------
Every shipped effect is 44100 Hz (the Problip blips) or 22050 Hz (the legacy
pack), while a Windows output device usually mixes at 48000 Hz, so SOMETHING
resamples on every playback.  This module renders each WAV ONCE to the
device's own rate with a band-limited polyphase resampler, caches the result
next to the volume-scaled copies, and lets the transport play a file the
device can open verbatim.

Honest status (T-1242): this whole pipeline is an EXPERIMENT.  The original
fidelity complaint predates it, and a deterministic repeated-play A/B
(spec 6/7) has not yet proven it fixes anything.  Its two switches default
to OFF and it is available only as an Advanced option.  Comments in here
describe what the code does; claims about WHY the audio sounded wrong are
hypotheses until the A/B matrix says otherwise.
"""

from __future__ import annotations

import logging
import math
import os
import struct
import sys
import tempfile
import threading
import wave
from array import array

logger = logging.getLogger(__name__)

# ---- single-flight render registry (T-1242 cache-race fix) ----------------
#
# prewarm_device_cache() renders on a background thread while the first real
# cue may call device_ready_wav() for the SAME key from the UI thread.  With
# no per-key lock both threads wrote the same temp file (``<final>.<PID>.part``
# was PID-only, so two threads in ONE process shared the name) and a
# reproduction with 8 concurrent callers returned 5 rendered paths and 3
# None/fallback answers for the identical source.  Exactly one renderer per
# cache key now; latecomers wait for the published file.  Bounded, because a
# lock per historical WAV would leak: after the flight completes the key is
# dropped from the registry, and the registry itself is capped.
_RENDER_LOCK = threading.Lock()
_RENDER_FLIGHTS: dict[str, threading.Event] = {}
_RENDER_FLIGHTS_MAX = 64


def _flight_claim(key: str) -> tuple[bool, threading.Event | None]:
    """Atomically claim the render slot for ``key``.

    Returns ``(owner, event)``.  The first caller for a key owns the render
    and receives a fresh (unset) Event; every later caller receives the same
    Event and must wait on it, then observe the published file.  The event
    being UNSET means the owner is still rendering, so waiters never mistake
    a brand-new event for a completed flight.
    """
    with _RENDER_LOCK:
        event = _RENDER_FLIGHTS.get(key)
        if event is not None:
            return False, event
        event = threading.Event()
        if len(_RENDER_FLIGHTS) >= _RENDER_FLIGHTS_MAX:
            # drop finished flights first; only then oldest unfinished
            for done in [k for k, e in _RENDER_FLIGHTS.items() if e.is_set()]:
                _RENDER_FLIGHTS.pop(done, None)
        if len(_RENDER_FLIGHTS) >= _RENDER_FLIGHTS_MAX:
            _RENDER_FLIGHTS.pop(next(iter(_RENDER_FLIGHTS)), None)
        _RENDER_FLIGHTS[key] = event
        return True, event


def _flight_release(key: str, event: threading.Event) -> None:
    """Publish completion, then forget the key (bounded registry)."""
    event.set()
    with _RENDER_LOCK:
        if _RENDER_FLIGHTS.get(key) is event:
            _RENDER_FLIGHTS.pop(key, None)

#: Bump when the resampler's output contract changes so old cache entries
#: are naturally orphaned (and pruned by the shared budget) instead of
#: silently replayed.
RENDER_VERSION = 4

#: Silence welded onto the front and back of a short cue (EXPERIMENTAL,
#: default OFF).
#:
#: Hypothesis, not evidence: a very short file makes the output sink start
#: and stop within tens of milliseconds, and IF the sink's own transition
#: clips the first/last milliseconds of such a file, padding moves that
#: transition onto silence.  The padding copies the original samples
#: through untouched between two silent margins.  Whether the clipping it
#: addresses actually happens on real hardware is exactly what the
#: repeated-play A/B matrix has to decide; it ships OFF until then.
EDGE_PAD_HEAD_MS = 18
EDGE_PAD_TAIL_MS = 36

#: Only SHORT cues get padded.  A long ambience bed has plenty of runway of
#: its own, and delaying it by 18 ms buys nothing.
EDGE_PAD_MAX_SECONDS = 2.5

#: Shared with sound_manager's scaled-WAV cache: one managed temp directory,
#: one pruning budget.  Names never collide (``_r<rate>`` vs ``_v<level>``).
_CACHE_DIR_NAME = "fastprompter_sound"

# ---------------------------------------------------------------------------
# DSP constants
# ---------------------------------------------------------------------------

#: Taps per polyphase branch.  32 is well past transparent for UI effects
#: while keeping the pure-Python fallback cheap on short blips.
_TAPS = 32

#: Pure-Python rendering cost is linear in output frames.  Without numpy a
#: multi-minute ambience track would block the audio worker for seconds, so
#: long sources keep their original file (the device converts them as before).
#: Output frames per NumPy resample block (PERF-002). The tap matrix is the
#: only large temporary, so it is bounded to RESAMPLE_BLOCK_FRAMES * _TAPS.
RESAMPLE_BLOCK_FRAMES = 65536

#: Duration policy for a device-rate render (PERF-002), applied to BOTH the
#: NumPy and the pure-Python path. A longer source is played RAW instead of
#: rendered: the renderer is an optimisation with a bounded work class, so it
#: must never stall the thread that asked for the sound, and never start an
#: unbounded allocation. The worker limits are larger because a background
#: prewarm is already off the interactive path.
RENDER_MAX_SECONDS = 30.0
RENDER_MAX_SECONDS_WORKER = 120.0

_PURE_PYTHON_MAX_FRAMES = 44100 * 6

#: The same loop on a BACKGROUND thread starves the GUI (the GIL is held for
#: the whole render), so a worker without numpy renders only very short cues
#: and leaves the rest to play unrendered.
_PURE_PYTHON_WORKER_MAX_FRAMES = 44100 // 2

#: A symmetric FIR has a constant group delay of ``(taps - 1) / 2`` input
#: samples.  Output sample ``n`` corresponds to input time
#: ``(n * down) / up``, so the filter's causal output lags that ideal by
#: the delay.  Compensating it exactly (``+ delay * up / down`` output
#: samples) keeps an input impulse at source index ``i`` at the output
#: index nearest ``i * up / down`` (verified against
#: scipy.signal.resample_poly, which is also linear-phase compensated).
#: Without this, a 66 ms transient's attack shifts ~0.35 ms late and the
#: waveform tail loses source transparency -- measured defect T-1242.

def _resample(channels: list[list[float]], rate_in: int, rate_out: int) -> list[list[float]]:
    """Band-limited rational resample of each channel, -1.0..1.0 floats.

    Linear-phase (symmetric kernel), so group delay is a known constant and
    is compensated exactly; output length is the nominal resampled length
    of the SOURCE content (``ceil(n_in * up / down)``), matching what a
    trusted offline reference produces.
    """
    g = math.gcd(rate_in, rate_out)
    up, down = rate_out // g, rate_in // g
    cutoff = 0.5 / max(up, down)
    kernel = _polyphase_kernel(up, _TAPS, cutoff)
    n_in = len(channels[0])
    n_out = (n_in * up + down - 1) // down
    if n_out <= 0:
        return [[] for _ in channels]

    # Group-delay compensation: the polyphase reader reaches the impulse
    # center with ``start = m // up + S`` and tap index ``S`` mapping to the
    # prototype's central tap, which places an input impulse at source
    # index ``i`` at the output index nearest ``i * up / down`` -- the same
    # convention as scipy.signal.resample_poly.  Measured across 44.1->48,
    # 22.05->48, 48->44.1 and 2x integer upsampling: impulse peak within 1
    # output sample of ideal, sine amplitude unity through 18 kHz, DC unity.
    # Without this, a 66 ms transient's attack shifts late and the waveform
    # tail is not source-transparent (defect T-1242).
    _DELAY_TAPS = _TAPS // 2

    np = _numpy_if_safe()

    if np is not None:
        khat = np.asarray(kernel, dtype=np.float64)            # (up, taps)
        pad = _TAPS
        taps_idx = np.arange(_TAPS, dtype=np.int64)
        block = max(1, int(RESAMPLE_BLOCK_FRAMES))
        out: list[list[float]] = []
        for data in channels:
            x = np.asarray(data, dtype=np.float64)
            # Left AND right pad so ``start - k`` never wraps around to the
            # file's tail and the final transient can be rendered fully.
            xp = np.concatenate((np.zeros(pad + _DELAY_TAPS, dtype=np.float64),
                                 x, np.zeros(pad + _DELAY_TAPS,
                                             dtype=np.float64)))
            # PERF-002: the tap matrix is the only large temporary, so it is
            # built per BLOCK of output frames. Each output sample is still
            # the same 32-tap reduction of the same padded source, because
            # the rational phase and the read start are derived from the
            # ABSOLUTE output index -- never from a block-relative counter.
            # A block edge therefore carries no filter reset, no seam and no
            # delay shift, and the result is bit-identical to the whole-array
            # form (compared sample-for-sample in
            # tests/test_perf002_chunked_resample.py). Only the peak size of
            # the index/sample temporaries changes: block * _TAPS instead of
            # n_out * _TAPS, where the audit measured ~703 MiB for one such
            # matrix at 60 s / 48 kHz.
            y = np.empty(n_out, dtype=np.float64)
            for begin in range(0, n_out, block):
                end = min(begin + block, n_out)
                n = np.arange(begin, end, dtype=np.int64)
                m = n * down
                phase = m % up
                start = (m // up) + _DELAY_TAPS               # delay compensation
                idx = (start[:, None] + pad + _DELAY_TAPS) - taps_idx[None, :]
                np.clip(idx, 0, len(xp) - 1, out=idx)
                y[begin:end] = (xp[idx] * khat[phase]).sum(axis=1)
            out.append(y.tolist())
        return out

    result: list[list[float]] = []
    taps = _TAPS
    for data in channels:
        y = [0.0] * n_out
        for n in range(n_out):
            m = n * down
            phase = kernel[m % up]
            start = m // up + _DELAY_TAPS  # delay compensation
            acc = 0.0
            for k in range(taps):
                # Polyphase branch k reads x[start - k] -- the SAME
                # convention as the numpy path above.  Reading ``start + k``
                # walks the kernel backwards through the source, which is a
                # different (phase-scrambled) filter: measured 1.68 peak
                # error against an ideal 1 kHz sine where the numpy path
                # scores 0.0004.  That is the "sound like from a bucket"
                # defect -- the pure-Python renderer is the one a worker
                # thread without numpy uses for short cues (the Problip
                # blips), and its output went into the on-disk cache.
                i = start - k
                if i < 0:
                    continue           # left pad: silence before the file
                if i >= len(data):
                    continue           # right pad: source-transparent silence
                acc += phase[k] * data[i]
            y[n] = acc
        result.append(y)
    return result

def _numpy_if_safe():
    """numpy -- but NEVER imported from a background thread.

    Rendering runs on a daemon worker.  Importing a large package there while
    the main thread reads ``sys.modules`` hands unrelated code a partially
    initialized module ("most likely due to a circular import"), which is
    exactly what a concurrent render did to the test suite.  On the main
    thread we import normally; on a worker we only use an import that
    somebody else already finished.  The pure-Python path is the fallback,
    and it is bounded by ``_PURE_PYTHON_MAX_FRAMES``.
    """
    module = sys.modules.get("numpy")
    if module is not None:
        spec = getattr(module, "__spec__", None)
        if spec is not None and getattr(spec, "_initializing", False):
            return None                  # another thread is mid-import
        return module
    if threading.current_thread() is not threading.main_thread():
        return None
    try:
        import numpy

        return numpy
    except Exception:
        return None


def ensure_numpy() -> bool:
    """Resolve numpy NOW, on the caller's (main) thread.

    Render workers must never import it themselves (see ``_numpy_if_safe``),
    but they also must not fall back to the pure-Python resampler: that loop
    holds the GIL for whole seconds per file and starves the GUI thread --
    measured, opening Sound Settings went 1.0 s -> 4.8 s while a preload
    sweep was running.  Callers that are about to start a worker call this
    first so the worker finds numpy already imported.
    """
    return _numpy_if_safe() is not None


_MISSING = object()
_device_rate_cache: object = _MISSING

_kernel_cache: dict[tuple[int, int, int], list[list[float]]] = {}


def _cache_dir() -> str:
    import tempfile

    return os.path.join(tempfile.gettempdir(), _CACHE_DIR_NAME)


def device_sample_rate() -> int | None:
    """The default output device's own mix rate, or None when unknowable.

    Cached for the process: the value is a property of the audio hardware,
    and probing QMediaDevices on every blip would put Qt multimedia work on
    the typing hot path.
    """
    global _device_rate_cache
    if _device_rate_cache is not _MISSING:
        return _device_rate_cache  # type: ignore[return-value]
    rate: int | None = None
    try:
        from PyQt6.QtMultimedia import QMediaDevices

        device = QMediaDevices.defaultAudioOutput()
        value = int(device.preferredFormat().sampleRate())
        if 8000 <= value <= 192000:
            rate = value
    except Exception:
        logger.debug("device sample rate probe failed", exc_info=True)
        rate = None
    if rate is None:
        # T-1242 (spec 7): NEVER guess the device rate.  A Windows endpoint
        # can be configured to 44100, 48000, 96000...; pre-rendering to a
        # guessed rate would insert a second resample (44100 -> guessed 48000
        # -> actual 44100) that is strictly worse than playing the original.
        # Without a verified probe the caller plays the source file as-is.
        logger.debug("device sample rate unknown; playing sources unrendered")
        rate = None
    _device_rate_cache = rate
    return rate


def reset_device_sample_rate() -> None:
    """Forget the probed rate (device changed, or a test wants a fresh read)."""
    global _device_rate_cache
    _device_rate_cache = _MISSING


# ---- resampler ------------------------------------------------------------


def _polyphase_kernel(up: int, taps: int, cutoff: float) -> list[list[float]]:
    """``kernel[phase][k]`` for a windowed-sinc interpolation filter.

    ``cutoff`` is the normalized transition point of the *upsampled* stream,
    so downsampling gets its anti-alias filter from the same code path as
    upsampling gets its image rejection.
    """
    key = (up, taps, int(cutoff * 1_000_000))
    cached = _kernel_cache.get(key)
    if cached is not None:
        return cached
    length = taps * up
    center = (length - 1) / 2.0
    coeffs = [0.0] * length
    for j in range(length):
        x = j - center
        if x == 0.0:
            value = 2.0 * cutoff
        else:
            value = math.sin(2.0 * math.pi * cutoff * x) / (math.pi * x)
        # Blackman window: ~ -58 dB sidelobes, plenty for 16-bit UI audio.
        w = (0.42
             - 0.5 * math.cos(2.0 * math.pi * j / (length - 1))
             + 0.08 * math.cos(4.0 * math.pi * j / (length - 1)))
        coeffs[j] = value * w
    kernel = [[coeffs[p + k * up] for k in range(taps)] for p in range(up)]
    # Zero-stuffing by ``up`` divides amplitude by ``up``.  Normalizing each
    # phase to unit sum gives it back AND guarantees a DC input comes out at
    # exactly unity, so no rendered file is quieter than its source.
    for phase in kernel:
        total = sum(phase)
        if total:
            scale = 1.0 / total
            for k in range(len(phase)):
                phase[k] *= scale
    _kernel_cache[key] = kernel
    return kernel


# ---- WAV IO ---------------------------------------------------------------


def _read_wav(path: str):
    """(channels as float lists, framerate) or None when not safely rewritable."""
    if sys.byteorder != "little":
        return None
    try:
        with wave.open(path, "rb") as wf:
            if wf.getcomptype() != "NONE":
                return None
            width = wf.getsampwidth()
            nch = wf.getnchannels()
            rate = wf.getframerate()
            if width not in (1, 2, 4) or nch < 1 or rate <= 0:
                return None
            nframes = wf.getnframes()
            if nframes <= 0:
                return None
            frames = wf.readframes(nframes)
    except (OSError, wave.Error, EOFError):
        logger.debug("resample skipped for %s", path, exc_info=True)
        return None

    if width == 1:
        raw = array("B")
        raw.frombytes(frames)
        # 8-bit WAV samples are UNSIGNED with silence at 128.
        flat = [(s - 128) * (1.0 / 128.0) for s in raw]
    else:
        code = "h" if width == 2 else "i"
        raw = array(code)
        if raw.itemsize != width:
            return None
        raw.frombytes(frames[: len(frames) - (len(frames) % width)])
        scale = 1.0 / float(1 << (8 * width - 1))
        flat = [s * scale for s in raw]

    usable = (len(flat) // nch) * nch
    channels = [flat[c:usable:nch] for c in range(nch)]
    if not channels or not channels[0]:
        return None
    return channels, rate


def _write_wav16(path: str, channels: list[list[float]], rate: int) -> None:
    n = len(channels[0])
    nch = len(channels)
    out = array("h", bytes(2 * n * nch))
    for c, data in enumerate(channels):
        for i in range(n):
            v = data[i]
            v = int(v * 32767.0 + (0.5 if v >= 0 else -0.5))
            if v > 32767:
                v = 32767
            elif v < -32768:
                v = -32768
            out[i * nch + c] = v
    # T-1242: the temp name must be unique PER THREAD, not per process --
    # "<final>.<PID>.part" collided between the prewarm thread and the first
    # cue, and one thread's partial file replaced the other's output.
    fd, tmp = tempfile.mkstemp(prefix=f"{os.path.basename(path)}.",
                               suffix=".part", dir=os.path.dirname(path) or None)
    try:
        with os.fdopen(fd, "wb") as raw:
            with wave.open(raw, "wb") as wf:
                wf.setnchannels(nch)
                wf.setsampwidth(2)
                wf.setframerate(rate)
                wf.writeframes(out.tobytes())
            raw.flush()
            os.fsync(raw.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def _source_rate(path: str) -> int | None:
    """Read only the fmt chunk: cheap enough for the per-playback fast path."""
    try:
        with open(path, "rb") as fh:
            head = fh.read(4096)
    except OSError:
        return None
    if len(head) < 44 or head[:4] != b"RIFF" or head[8:12] != b"WAVE":
        return None
    i = 12
    while i + 8 <= len(head):
        cid = head[i:i + 4]
        size = struct.unpack("<I", head[i + 4:i + 8])[0]
        if cid == b"fmt " and i + 8 + 16 <= len(head):
            return struct.unpack("<I", head[i + 12:i + 16])[0] or None
        i += 8 + size + (size % 2)
    return None


# ---- public entry point ---------------------------------------------------


def _source_digest(path: str) -> str | None:
    """Short SHA256 over the file content -- the authoritative cache identity.

    Two different WAVs that happen to share a basename (``builtin:ui/click``
    vs ``user:imported/click``) must never share one rendered file, so the
    key is derived from WHAT THE FILE CONTAINS, not what it is called.  A
    16-hex-char truncation keeps filenames short while making a collision
    practically impossible for this cache's lifetime.
    """
    import hashlib

    digest = hashlib.sha256()
    try:
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(65536), b""):
                digest.update(chunk)
    except OSError:
        return None
    return digest.hexdigest()[:16]


#: Master switch for the device-rate pre-render (EXPERIMENTAL, default
#: OFF).  It exists so a user who hears colouration can A/B the renderer
#: against the raw source WAVs without a rebuild.  The original fidelity
#: complaint was never proven to be a resampler defect: raw playback #1 was
#: reported correct while #2+ degraded under unchanged settings, which is
#: not a static-quality signature at all.  The renderer ships OFF and earns
#: its default only if the repeated-play matrix shows RAW playback is
#: actually inconsistent while RENDER-only is stable and clean.
_render_enabled = False
_edge_pad_enabled = False


def set_edge_pad_enabled(enabled: bool) -> None:
    """A/B switch for the short-cue silence margins."""
    global _edge_pad_enabled
    _edge_pad_enabled = bool(enabled)


def edge_pad_enabled() -> bool:
    return _edge_pad_enabled


def _pad_frames(rate: int, milliseconds: int) -> int:
    return max(0, int(round(rate * milliseconds / 1000.0)))


def _wants_edge_pad(frames: int, rate: int) -> bool:
    if not _edge_pad_enabled or rate <= 0 or frames <= 0:
        return False
    return (frames / float(rate)) <= EDGE_PAD_MAX_SECONDS


def set_render_enabled(enabled: bool) -> None:
    global _render_enabled
    _render_enabled = bool(enabled)


def render_enabled() -> bool:
    return _render_enabled


def device_ready_wav(path: str, rate: int | None = None) -> str | None:
    """A cached copy of ``path`` already at the output device's sample rate.

    Returns ``None`` when no rendering is needed or possible -- the caller
    then uses the original file, exactly as before this module existed.

    Cache identity is the source CONTENT digest + target rate + render
    version, never the basename: two same-named files from different
    libraries can never collide (T-1242).
    """
    if not path or not _render_enabled:
        return None
    target = rate if rate is not None else device_sample_rate()
    if not target:
        return None
    target = int(target)
    try:
        src_rate = _source_rate(path)
        if src_rate is None:
            return None
        if src_rate == target and not _edge_pad_enabled:
            return None
        digest = _source_digest(path)
        if not digest:
            return None
        cache_dir = _cache_dir()
        # <short-content-hash> is authoritative; the stem is decoration only.
        stem = os.path.splitext(os.path.basename(path))[0][:24]
        pad = "p" if _edge_pad_enabled else "n"
        out = os.path.join(
            cache_dir,
            f"{stem}_{digest}_r{target}{pad}_v{RENDER_VERSION}.wav")
        # The cache key IS the published filename: content digest + target
        # rate + render version.  (T-1242 defect: this name was missing, so
        # every cold source raised NameError inside the transport's broad
        # ``except Exception`` and became an unexplained STOPPED.)
        key = out
        # Fast path: a previous flight (this thread's or another's) already
        # published a validated file.
        if os.path.exists(out):
            return out
        owner, flight = _flight_claim(key)
        if not owner:
            if not flight.wait(timeout=30.0):
                # Another render is wedged; fall back to the original file.
                return None
            return out if os.path.exists(out) else None
        try:
            return _render_device_wav(path, out, cache_dir, target)
        finally:
            _flight_release(key, flight)
    except (OSError, wave.Error, ValueError, MemoryError):
        logger.debug("device-rate render failed for %s", path, exc_info=True)
        return None
    except Exception:
        # Defensive: rendering is an OPTIMISATION.  A bug in here must
        # degrade to "play the original file", never to silence -- the
        # T-1242 NameError proved a narrow except turns a render defect
        # into an unexplained STOPPED three layers away.
        logger.warning("device-rate render aborted for %s", path, exc_info=True)
        return None


def _render_device_wav(path: str, out: str, cache_dir: str, target: int):
    """The one renderer for a cache key. Caller holds the flight."""
    try:
        os.makedirs(cache_dir, exist_ok=True)
        read = _read_wav(path)
        if read is None:
            return None
        channels, src_rate = read
        if src_rate == target:
            # Nothing to resample -- but a short cue may still need its
            # silence margins, and that is worth one cached copy.
            if not _wants_edge_pad(len(channels[0]), target):
                return None
            _write_wav16(out, _with_edge_padding(channels, target), target)
            return out
        has_numpy = _numpy_if_safe() is not None
        frames_in = len(channels[0])
        on_worker = threading.current_thread() is not threading.main_thread()
        # PERF-002: the policy covers BOTH paths. Before this, only the
        # pure-Python path had a frame limit while the NumPy path started a
        # 60 s render whose tap matrix alone measured ~703 MiB, and an
        # ordinary ambience-length source could ask for gigabytes. A source
        # beyond the limit is played raw -- the caller gets the original
        # file, never silence and never a multi-second stall.
        max_seconds = RENDER_MAX_SECONDS_WORKER if on_worker else RENDER_MAX_SECONDS
        if frames_in > max(1, int(src_rate * max_seconds)):
            logger.debug(
                "device-rate render skipped: %s is longer than the %.0fs "
                "render policy", path, max_seconds)
            return None
        if not has_numpy:
            # A worker holding the GIL for seconds is worse than an
            # unrendered file: the UI freezes and the user blames the app.
            limit = (_PURE_PYTHON_WORKER_MAX_FRAMES if on_worker
                     else _PURE_PYTHON_MAX_FRAMES)
            if frames_in > limit:
                return None
        rendered = _resample(channels, src_rate, target)
        if not rendered or not rendered[0]:
            return None
        if _wants_edge_pad(len(rendered[0]), target):
            rendered = _with_edge_padding(rendered, target)
        _write_wav16(out, rendered, target)
        return out
    except (OSError, wave.Error, ValueError, MemoryError):
        logger.debug("device-rate render failed for %s", path, exc_info=True)
        return None


def _with_edge_padding(channels: list[list[float]],
                       rate: int) -> list[list[float]]:
    """The same audio with digital silence welded to both ends.

    Sample values are copied verbatim; nothing is faded, scaled or trimmed.
    """
    head = [0.0] * _pad_frames(rate, EDGE_PAD_HEAD_MS)
    tail = [0.0] * _pad_frames(rate, EDGE_PAD_TAIL_MS)
    if not head and not tail:
        return channels
    return [head + data + tail for data in channels]


def prewarm_device_cache(paths, rate: int | None = None) -> None:
    """Render ``paths`` to the device rate on a background daemon thread.

    T-1242 contract correction: this ONLY renders WAV files to disk.  It
    does NOT instantiate or preload any QSoundEffect and therefore does NOT
    prevent the first playback from passing through Qt's Loading state --
    that is the transport's own source-load cycle (see
    QtSoundTransport.preload in audio_hub.py).  What it does remove is the
    render cost from whichever thread plays first.
    """
    import threading

    items = [p for p in paths if p]
    if not items:
        return
    ensure_numpy()          # must happen on THIS thread, not the worker's

    def _run() -> None:
        import time as _time

        for item in items:
            try:
                device_ready_wav(item, rate)
            except Exception:
                logger.debug("prewarm failed for %s", item, exc_info=True)
            _time.sleep(0.005)     # give the GUI thread air between files

    threading.Thread(target=_run, name="FastPrompter audio prewarm",
                     daemon=True).start()
