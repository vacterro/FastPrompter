"""One audio authority for FastPrompter.

Every audible sound enters through :class:`AudioHub` (installed behind the
SoundManager facade).  The hub coordinates the audio bus model, the
user-facing playback modes (Overlay/Stack/Replace), a real multi-channel
mixing transport, bounded queues, voice sequences, and STOP ALL SOUND.

Design contract (T-1238 appends + T-1238-C0 hardening):

* every audible request carries provenance (request id, bus, mode, asset);
* MIX means genuine simultaneous playback, never rapid WAV replacement;
* the *transient domain* (UI/ALERT/VOICE/PROBLIP/PREVIEW) is one product
  concept: the GLOBAL Stack/Replace setting orders and replaces across it,
  while an EXPLICIT per-event mode override stays scoped to its own bus;
* AMBIENCE is never part of the transient domain -- only STOP ALL SOUND and
  STOP AMBIENCE silence it;
* QUEUE is a bounded FIFO (bounded per bus) and a voice phrase is ONE job;
* REPLACE physically stops what it replaces, including a mid-phrase
  fragment, and clears the obsolete queue entries in scope;
* STOP ALL is emergency silence: nothing stale may ever resume;
* high-rate events coalesce and never flood queues.
"""

from __future__ import annotations

import itertools
import logging
import os
import struct
import threading
import time
from collections import OrderedDict
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol

from fastprompter.core import audio_render

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# User-facing playback modes
# ---------------------------------------------------------------------------


class PlaybackMode(StrEnum):
    """User-visible playback modes plus per-event inheritance."""

    INHERIT = "inherit"
    MIX = "mix"
    QUEUE = "queue"
    REPLACE = "replace"
    #: Scheduled-cue courtesy mode (Problip): never interrupt, never queue.
    SKIP_BUSY = "skip_busy"

    @classmethod
    def coerce(
        cls,
        value: object,
        default: PlaybackMode | None = None,
    ) -> PlaybackMode:
        if isinstance(value, cls):
            return value
        raw = str(value or "").strip().lower()
        try:
            return cls(raw)
        except ValueError:
            return default if default is not None else cls.MIX


class Scope(StrEnum):
    """How far a Stack/Replace decision reaches.

    ``GLOBAL`` is the user's global Overlay/Stack/Replace setting: it orders
    and replaces across the whole transient domain.  ``BUS`` is an explicit
    per-event / per-feature override and stays on its own bus.
    """

    BUS = "bus"
    GLOBAL = "global"


class Bus(StrEnum):
    UI = "ui"
    ALERT = "alert"
    VOICE = "voice"
    PROBLIP = "problip"
    AMBIENCE = "ambience"
    PREVIEW = "preview"


#: The transient domain the global playback mode governs.  AMBIENCE is
#: deliberately absent: it is a long-lived layer, not a transient cue.
TRANSIENT_BUSES = frozenset({
    Bus.UI, Bus.ALERT, Bus.VOICE, Bus.PROBLIP, Bus.PREVIEW,
})

#: Buses whose activity makes a scheduled courtesy cue stand down.
BUSY_BUSES = frozenset({Bus.ALERT, Bus.VOICE})


class BusPriority:
    """Used for channel-limit eviction and diagnostics only."""

    AMBIENCE = 0
    PROBLIP = 1
    UI = 2
    ALERT = 3
    VOICE = 3
    PREVIEW = 4


class Outcome(StrEnum):
    PLAYED = "PLAYED"
    QUEUED = "QUEUED"
    MIXED = "MIXED"
    REPLACED = "REPLACED"
    STOPPED = "STOPPED"
    DROPPED_BUSY = "DROPPED_BUSY"
    DROPPED_CHANNEL_LIMIT = "DROPPED_CHANNEL_LIMIT"
    DROPPED_QUEUE_FULL = "DROPPED_QUEUE_FULL"
    # T-1244: the request never started because the global master mute was
    # ON.  Truthful provenance: a user reporting "the timer fired but I
    # heard nothing" must be diagnosable as muted, not as a missing file,
    # a transport failure or an unexplained STOPPED.
    DROPPED_MUTED = "DROPPED_MUTED"
    COALESCED = "COALESCED"


# T-1242 spec 3: bounded transport failure provenance.  A failed physical
# start must never collapse into an unexplained STOPPED.  Reason codes are
# stable machine tokens; the payload carries no user text, no credential and
# no path dump beyond the normal local diagnostic surface.
class StopReason(StrEnum):
    NONE = "none"
    FILE_MISSING = "FILE_MISSING"
    UNSUPPORTED_FORMAT = "UNSUPPORTED_FORMAT"
    SOURCE_ERROR = "SOURCE_ERROR"
    SOURCE_LOADING = "SOURCE_LOADING"
    EFFECT_PLAY_EXCEPTION = "EFFECT_PLAY_EXCEPTION"
    POOL_EXHAUSTED = "POOL_EXHAUSTED"
    RENDER_FAILED = "RENDER_FAILED"
    TRANSPORT_UNAVAILABLE = "TRANSPORT_UNAVAILABLE"


#: Outcomes that mean "this request will never make a sound".
DROPPED_OUTCOMES = frozenset({
    Outcome.STOPPED, Outcome.DROPPED_BUSY, Outcome.DROPPED_CHANNEL_LIMIT,
    Outcome.DROPPED_QUEUE_FULL, Outcome.DROPPED_MUTED,
})

MAX_TRANSIENT_VOICES = 16
MAX_QUEUE_PER_BUS = 32

# Events that may arrive at humanly impossible rates and must coalesce.
HIGH_RATE_EVENTS = frozenset({
    "typewriter", "backspace", "delete_forward", "delete_selection",
    "hover", "scroll", "typewriter_key", "key_tick", "hover_tick", "type",
})

COALESCE_WINDOW_S = 0.08


class Transport(Protocol):
    """A real multi-channel audio transport.

    Implementations must genuinely play multiple WAVs simultaneously,
    support looping, per-channel volume, individual stops, and a
    completion callback per channel so queues can advance.
    """

    capability_mixing: bool

    def play(
        self,
        path: str,
        *,
        volume: float = 1.0,
        loop: bool = False,
        on_complete: Callable[[], None] | None = None,
        token: str = "",
    ) -> str:
        """Start playing NOW and return a UNIQUE channel handle.

        A handle means physical playback was requested in this call.  When
        the source cannot start now (still loading, no device, unsupported)
        the transport returns ``""`` and files the reason under ``token``;
        it never keeps a request aside to start it later (T-1242 P0).
        """
        ...

    def stop(self, channel: str) -> None:
        """Stop exactly that channel; its completion must not fire."""
        ...

    def stop_all(self) -> None: ...

    def set_volume(self, channel: str, volume: float) -> None:
        """Change one live channel's volume (fades are built on this)."""
        ...


class _FailureRegistry:
    """Bounded token -> failure-detail map shared by transports.

    A refused ``play()`` returns ``""`` and nothing else, so the reason for
    the refusal used to die inside the transport and reach the user as an
    unexplained ``STOPPED``.  The transport now files the detail under the
    request token and the hub collects it exactly once.
    """

    CAPACITY = 64

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._items: dict[str, dict[str, Any]] = {}

    def file(self, token: str, detail: dict[str, Any]) -> None:
        with self._lock:
            if len(self._items) >= self.CAPACITY:
                self._items.pop(next(iter(self._items)), None)
            self._items[token or f"anon{id(detail)}"] = detail

    def take(self, token: str) -> dict[str, Any] | None:
        with self._lock:
            return self._items.pop(token, None)


class NullTransport:
    """Degraded fallback: no real mixing. Truthful about it."""

    capability_mixing = False

    def __init__(self) -> None:
        self._failures = _FailureRegistry()

    def take_failure(self, token: str):
        return self._failures.take(token)

    def preload(self, paths) -> None:
        return None

    def play(self, path, *, volume=1.0, loop=False, on_complete=None, token=""):
        self._failures.file(token, {
            "reason": StopReason.TRANSPORT_UNAVAILABLE.value,
            "transport": "NullTransport",
            "source": os.path.basename(path or ""),
        })
        return ""

    def stop(self, channel):
        pass

    def stop_all(self):
        pass

    def set_volume(self, channel, volume):
        pass


class FakeMultiChannelTransport:
    """Test transport implementing the full transport contract."""

    capability_mixing = True

    def __init__(self) -> None:
        self.channels: dict[str, dict[str, Any]] = {}
        self.stopped: list[str] = []
        self.stop_all_count = 0
        self.volume_calls: list[tuple[str, float]] = []
        self._seq = itertools.count(1)
        self.preloaded: list[str] = []
        self._failures = _FailureRegistry()

    def take_failure(self, token: str):
        return self._failures.take(token)

    def preload(self, paths) -> None:
        self.preloaded.extend(p for p in paths if p)

    def play(self, path, *, volume=1.0, loop=False, on_complete=None, token=""):
        if not path:
            self._failures.file(token, {
                "reason": StopReason.FILE_MISSING.value,
                "transport": "FakeMultiChannelTransport",
            })
            return ""
        handle = f"ch{next(self._seq)}"
        self.channels[handle] = {
            "path": path,
            "volume": volume,
            "loop": loop,
            "on_complete": on_complete,
            "token": token,
        }
        return handle

    def stop(self, channel):
        self.stopped.append(channel)
        self.channels.pop(channel, None)

    def stop_all(self):
        self.stop_all_count += 1
        self.channels.clear()

    def set_volume(self, channel, volume):
        self.volume_calls.append((channel, float(volume)))
        job = self.channels.get(channel)
        if job is not None:
            job["volume"] = float(volume)

    # Test helper: simulate the transport finishing one channel.
    def complete(self, handle: str) -> None:
        job = self.channels.pop(handle, None)
        if job and job["on_complete"] is not None:
            job["on_complete"]()

    def finish_all(self) -> None:
        for handle in list(self.channels):
            self.complete(handle)


#: Class attributes a real QSoundEffect exposes.  A MagicMock/stand-in that
#: lacks them is NOT a mixing backend and must degrade truthfully.
_QSE_REQUIRED = (
    "setSource", "setVolume", "setLoopCount", "play", "stop", "isPlaying",
    "playingChanged",
)


#: QSoundEffect source-load states.  A *Loading* source is refused at request
#: time (T-1242 P0): a late sound is not the same sound, so a Ready transition
#: only makes the effect available to a FUTURE request -- it never replays an
#: old one.
_STATUS_NAMES = ("Null", "Loading", "Ready", "Error")


def _status_values(qsoundeffect_cls) -> dict[Any, str]:
    """Map the backend's Status enum values to our stable names.

    Returns ``{}`` when the binding exposes no usable Status enum -- the
    transport then keeps the legacy "play immediately" behaviour instead of
    guessing that an unknown value means Loading.
    """
    holder = getattr(qsoundeffect_cls, "Status", None)
    out: dict[Any, str] = {}
    for name in _STATUS_NAMES:
        value = getattr(holder, name, None) if holder is not None else None
        if value is None:
            value = getattr(qsoundeffect_cls, name, None)
        if value is not None:
            out[value] = name
    return out if len(out) >= 3 else {}


def _infinite_loop_value(qsoundeffect_cls):
    """The backend's "loop forever" loop count.

    PyQt6 exposes it as ``QSoundEffect.Loop.Infinite``; older/other bindings
    put it directly on the class.  Guessing wrong here is how a "rich"
    backend silently became NullTransport for the whole product, so the
    value is resolved explicitly and a stand-in without it is refused.
    """
    loop_enum = getattr(qsoundeffect_cls, "Loop", None)
    value = getattr(loop_enum, "Infinite", None)
    if value is None:
        value = getattr(qsoundeffect_cls, "Infinite", None)
    if value is None:
        raise RuntimeError("QSoundEffect has no Infinite loop count")
    # PyQt6 hands back an enum MEMBER here, and setLoopCount() wants a plain
    # int -- passing the member raised TypeError, which the transport turned
    # into EFFECT_PLAY_EXCEPTION and every looping ambience layer into
    # silence (T-1242).
    raw = getattr(value, "value", value)      # a plain enum is NOT an int here
    try:
        return int(raw)
    except (TypeError, ValueError):
        return value


# ---------------------------------------------------------------------------
# Source-faithful PCM playback for transient one-shots (T-1242 P0)
# ---------------------------------------------------------------------------
#
# Measured on real Windows (Qt 6.11.1, WASAPI loopback capture of the built-in
# Space blip): QSoundEffect -- pooled AND fresh alike -- drops the last
# ~42.5 ms (one 2048-frame engine period) of every cue, keeps that tail in its
# shared engine, and emits it ~42.5 ms BEFORE the next QSoundEffect cue starts
# (normalized correlation 0.95-0.97 against the lost source tail).  That is
# the reported "chopped / frozen fragment leaks into the next cue" defect, and
# it lives below the pool, so no pool policy can fix it.  One fresh QAudioSink
# per cue fed the exact PCM frames played the source with the same residual as
# the winsound reference and no loss or leak.

#: Silence the transport appends AFTER the last source frame, inside its own
#: playback buffer only (the file and its frames are never touched).
#: QAudioSink reports Idle when the last byte has been handed to the OS mixer,
#: not when it has been heard; stopping at that moment discarded the final
#: ~20 ms of every cue.  With the post-roll, what the stop discards is
#: guaranteed to be this silence, never the source.
PCM_POSTROLL_MS = 100
#: A voice that never reports Idle (device vanished, driver hang) is retired
#: this long after its expected end so no phantom channel stays "active".
PCM_WATCHDOG_GRACE_MS = 1500
#: Hard ceiling on simultaneously alive sinks, above the hub's own voice cap.
MAX_PCM_VOICES = 32
#: Bigger sources are not transient cues; they keep the QSoundEffect path.
PCM_MAX_SOURCE_BYTES = 16 * 1024 * 1024
#: Decoded-PCM cache budget (bytes) -- the hot set is a few MB at most.
PCM_CACHE_BUDGET = 48 * 1024 * 1024

_WAVE_FORMAT_PCM = 0x0001
_WAVE_FORMAT_IEEE_FLOAT = 0x0003
_WAVE_FORMAT_EXTENSIBLE = 0xFFFE


@dataclass(frozen=True)
class PcmSource:
    """The exact frames of one WAV and the format that plays them unchanged."""

    path: str
    data: bytes
    channels: int
    rate: int
    #: "u8" | "s16" | "s32" | "f32" -- the QAudioFormat sample format.
    sample_format: str
    bytes_per_frame: int
    frames: int
    #: Bits per sample as stored in the file (24-bit is carried exactly in a
    #: 32-bit container: value << 8, no rounding, no scaling).
    source_bits: int
    signature: tuple[int, int] = (0, 0)

    @property
    def duration_ms(self) -> int:
        return int(round(self.frames * 1000 / self.rate)) if self.rate else 0

    def silence(self, milliseconds: int) -> bytes:
        frames = max(0, self.rate * int(milliseconds) // 1000)
        zero = b"\x80" if self.sample_format == "u8" else b"\x00"
        return zero * (frames * self.bytes_per_frame)


def _file_signature(path: str) -> tuple[int, int] | None:
    try:
        st = os.stat(path)
    except OSError:
        return None
    return (int(st.st_mtime_ns), int(st.st_size))


def read_pcm_wav(path: str) -> PcmSource | None:
    """Decode one RIFF/WAVE file to its exact PCM frames, or ``None``.

    Supports integer PCM (8/16/24/32-bit), IEEE float32 and
    WAVE_FORMAT_EXTENSIBLE wrappers of both.  No resampling, no gain, no
    dither: the frames that come out are the frames in the file.
    """
    signature = _file_signature(path)
    if signature is None or signature[1] > PCM_MAX_SOURCE_BYTES:
        return None
    try:
        with open(path, "rb") as handle:
            blob = handle.read(PCM_MAX_SOURCE_BYTES + 1)
    except OSError:
        return None
    if len(blob) < 12 or blob[:4] != b"RIFF" or blob[8:12] != b"WAVE":
        return None
    fmt_chunk = data_chunk = None
    pos = 12
    while pos + 8 <= len(blob):
        chunk_id = blob[pos:pos + 4]
        size = int.from_bytes(blob[pos + 4:pos + 8], "little")
        body = blob[pos + 8:pos + 8 + size]
        if chunk_id == b"fmt " and fmt_chunk is None:
            fmt_chunk = body
        elif chunk_id == b"data" and data_chunk is None:
            data_chunk = body
        if fmt_chunk is not None and data_chunk is not None:
            break
        pos += 8 + size + (size & 1)
    if fmt_chunk is None or data_chunk is None or len(fmt_chunk) < 16:
        return None
    tag, channels, rate, _byte_rate, block_align, bits = struct.unpack(
        "<HHIIHH", fmt_chunk[:16])
    if tag == _WAVE_FORMAT_EXTENSIBLE:
        if len(fmt_chunk) < 26:
            return None
        tag = int.from_bytes(fmt_chunk[24:26], "little")  # SubFormat GUID
    if channels < 1 or channels > 8 or not 1000 <= rate <= 384000:
        return None
    if block_align < channels or block_align % channels:
        return None
    width = block_align // channels
    frames = len(data_chunk) // block_align
    if frames <= 0:
        return None
    data = data_chunk[:frames * block_align]
    if tag == _WAVE_FORMAT_PCM and width in (1, 2, 4):
        sample_format = {1: "u8", 2: "s16", 4: "s32"}[width]
    elif tag == _WAVE_FORMAT_PCM and width == 3:
        # Exact widening: 24-bit little-endian into the top of an int32.
        wide = bytearray(len(data) // 3 * 4)
        wide[1::4] = data[0::3]
        wide[2::4] = data[1::3]
        wide[3::4] = data[2::3]
        data, width, sample_format = bytes(wide), 4, "s32"
    elif tag == _WAVE_FORMAT_IEEE_FLOAT and width == 4:
        sample_format = "f32"
    else:
        return None
    return PcmSource(
        path=path, data=data, channels=channels, rate=rate,
        sample_format=sample_format, bytes_per_frame=width * channels,
        frames=frames, source_bits=int(bits) or width * 8,
        signature=signature)


class SinkRefused(Exception):
    """A sink factory could not physically start a voice NOW."""

    def __init__(self, reason: StopReason, detail: str = "") -> None:
        super().__init__(reason.value)
        self.reason = reason
        self.detail = detail


class _QtPcmSinkFactory:
    """One fresh QAudioSink + QBuffer per accepted cue (GUI thread only).

    Nothing is reused between cues: a sink is born for one cue, is fed that
    cue's exact frames plus the post-roll, and is deleted once it drained.
    """

    def __init__(self) -> None:
        from PyQt6 import sip
        from PyQt6.QtCore import QBuffer, QByteArray, QIODevice, QTimer
        from PyQt6.QtMultimedia import QAudioFormat, QAudioSink, QMediaDevices

        self._sip = sip
        self._QBuffer = QBuffer
        self._QByteArray = QByteArray
        self._read_only = QIODevice.OpenModeFlag.ReadOnly
        self._QTimer = QTimer
        self._QAudioFormat = QAudioFormat
        self._QAudioSink = QAudioSink
        self._QMediaDevices = QMediaDevices
        fmt = QAudioFormat.SampleFormat
        self._formats = {"u8": fmt.UInt8, "s16": fmt.Int16,
                         "s32": fmt.Int32, "f32": fmt.Float}

    def open(self, pcm: PcmSource, postroll_ms: int):
        """Return ``(sink, buffer)`` ready to start; raise SinkRefused."""
        device = self._QMediaDevices.defaultAudioOutput()
        if device is None or device.isNull():
            raise SinkRefused(StopReason.TRANSPORT_UNAVAILABLE, "no output")
        fmt = self._QAudioFormat()
        fmt.setSampleRate(pcm.rate)
        fmt.setChannelCount(pcm.channels)
        fmt.setSampleFormat(self._formats[pcm.sample_format])
        if not device.isFormatSupported(fmt):
            raise SinkRefused(StopReason.UNSUPPORTED_FORMAT,
                              f"{pcm.rate}Hz/{pcm.channels}ch/"
                              f"{pcm.sample_format}")
        sink = self._QAudioSink(device, fmt)
        # The buffer is the sink's CHILD: it can never be deleted while the
        # sink still reads from it, and it dies with the sink.
        buffer = self._QBuffer(sink)
        buffer.setData(self._QByteArray(pcm.data + pcm.silence(postroll_ms)))
        buffer.open(self._read_only)
        return sink, buffer

    def watchdog(self, sink, milliseconds: int, callback):
        timer = self._QTimer(sink)          # dies with the sink
        timer.setSingleShot(True)
        timer.timeout.connect(callback)
        timer.start(max(1, int(milliseconds)))
        return timer

    def retire(self, sink) -> None:
        """Hand the stopped sink to Qt for deferred deletion.

        Deleting a QAudioSink from inside its own stateChanged slot is what
        deleteLater exists for; ownership moves to C++ first so the Python
        wrapper going away can never delete it early.
        """
        try:
            self._sip.transferto(sink, None)
        except Exception:
            pass
        try:
            sink.deleteLater()
        except Exception:
            pass

    @staticmethod
    def state_name(state) -> str:
        return str(getattr(state, "name", state))

    @staticmethod
    def error_name(sink) -> str:
        try:
            error = sink.error()
        except Exception:
            return "UnknownError"
        return str(getattr(error, "name", error))


@dataclass
class _PcmVoice:
    """One physically started PCM cue: exactly one sink, never reused."""

    handle: str
    token: str
    logical: str
    physical: str
    rendered: bool
    sink: Any
    buffer: Any
    on_complete: Callable[[], None] | None
    t_request: float
    t_start: float = 0.0
    watchdog: Any = None


@dataclass
class _PoolEntry:
    """One pooled QSoundEffect and the physical identity it was born with.

    A pooled effect must never outlive the policy generation it was created
    under (T-1242 spec 4/5): a new generation invalidates the whole pool.
    """

    effect: Any
    physical_path: str
    rendered: bool
    policy_generation: int


class QtSoundTransport:
    """The canonical Qt backend.

    Transient one-shot cues (every UI / ALERT / VOICE / PROBLIP / PREVIEW
    request) play through a FRESH QAudioSink fed the source's exact PCM
    frames (T-1242 P0).  Looping long-lived layers (ambience) and sources the
    PCM path cannot carry keep the QSoundEffect pool, keyed by the RESOLVED
    physical source (T-1242 spec 4).

    The one contract both paths share: a returned handle means physical
    playback was requested NOW.  A source that cannot start now (QSoundEffect
    still Loading, no device, unsupported format...) is refused with a
    recorded reason; nothing is held back to start later, so no obsolete cue
    can ever begin after a newer one.  ``stop(handle)`` is a real stop and a
    completion arriving after it can never advance a queue.
    """

    capability_mixing = True
    POOL_PER_PATH = 4
    #: PERF-004 (SRC-021): global bound on retained QSoundEffect pool KEYS.
    #: ``POOL_PER_PATH`` alone bounds a single source, not a session: a user
    #: previewing thousands of imported/managed sounds kept one pool per
    #: source forever (``stop_all()`` deliberately keeps pools).  Past this
    #: many keys, the least-recently-used INACTIVE pool is retired down to the
    #: bound.  Active channels, playing effects and the ambience/live layers
    #: are never evictable, so the bound can be exceeded while more than this
    #: many sources are genuinely audible -- correctness outranks the cache.
    MAX_POOLS = 128
    PLAYBACK_TRACE_CAPACITY = 128

    def __init__(self, qsoundeffect_cls=None, url_factory=None,
                 pcm_sink_factory: Any = "auto") -> None:
        real_binding = qsoundeffect_cls is None
        if qsoundeffect_cls is None:
            from PyQt6.QtMultimedia import QSoundEffect

            qsoundeffect_cls = QSoundEffect
        # Strict capability probe -- a stub without the real enum/signals is
        # not a mixing backend and must not be presented as one.
        missing = [a for a in _QSE_REQUIRED if not hasattr(qsoundeffect_cls, a)]
        if missing:
            raise RuntimeError(f"QSoundEffect lacks {missing}")
        self._infinite = _infinite_loop_value(qsoundeffect_cls)
        if url_factory is None:
            from PyQt6.QtCore import QUrl

            url_factory = QUrl.fromLocalFile
        self._url = url_factory
        self._QSE = qsoundeffect_cls
        self._status_map = _status_values(qsoundeffect_cls)
        self._lock = threading.RLock()
        # T-1242 P0: the PCM sink path is the product path whenever the REAL
        # QtMultimedia binding is in use.  Test stand-ins for QSoundEffect get
        # no sink unless a test injects one, so a unit test never opens a
        # real audio device behind a fake.
        if pcm_sink_factory == "auto":
            real_binding = real_binding or (
                getattr(qsoundeffect_cls, "__name__", "") == "QSoundEffect"
                and "QtMultimedia" in getattr(qsoundeffect_cls, "__module__",
                                              ""))
            pcm_sink_factory = None
            if real_binding:
                try:
                    pcm_sink_factory = _QtPcmSinkFactory()
                except Exception:
                    logger.debug("QAudioSink unavailable; QSoundEffect only",
                                 exc_info=True)
        self._sinks = pcm_sink_factory
        self._voices: dict[str, _PcmVoice] = {}
        self._pcm_cache: dict[str, PcmSource] = {}
        self._pcm_cache_bytes = 0
        # T-1242 spec 4: pools are keyed by the RESOLVED physical identity,
        # never by the logical path alone.
        self._pools: dict[tuple[str, str, bool, int], list[_PoolEntry]] = {}
        # PERF-004: recency order of pool keys (LRU eviction under MAX_POOLS).
        self._pool_order: OrderedDict = OrderedDict()
        self._resolved: dict[str, tuple[str, bool]] = {}
        self._policy_generation = 0
        self._playback_log: list[dict[str, Any]] = []
        self._retirements: list[dict[str, Any]] = []
        self._channels: dict[str, Any] = {}        # handle -> effect
        self._owner: dict[int, str] = {}           # id(effect) -> handle
        self._completions: dict[str, Callable[[], None]] = {}
        # PERF-004: id(effect) -> (effect, connection). Holding the effect
        # reference prevents id() reuse while a connection is live, so a
        # stale signal can never be read as a newer effect's completion; the
        # handler is retained so retirement can disconnect it.
        self._bound: dict[int, tuple[Any, Callable[[], None]]] = {}
        self._failures = _FailureRegistry()
        self._last_acquire_reason = StopReason.NONE
        self._seq = itertools.count(1)
        self._closed = False

    @property
    def pcm_sink_active(self) -> bool:
        """True when transient cues play through the PCM sink path."""
        return self._sinks is not None

    # -- failure provenance ---------------------------------------------------

    def take_failure(self, token: str):
        """Pop the recorded detail for one refused request (or None)."""
        return self._failures.take(token)

    # -- source identity (T-1242 spec 3/4/5) ---------------------------------

    def render_policy_generation(self) -> int:
        """Which render-policy generation the pools were built for."""
        with self._lock:
            return self._policy_generation

    def _resolve_physical(self, path: str) -> tuple[str, bool]:
        """Resolve the ONE physical source for ``path`` under current policy.

        Returns ``(physical_path, rendered_flag)``.  Resolution happens
        BEFORE any pool lookup so a newly created effect can never receive a
        different file than the pooled ones it joins.  With the experimental
        render switch OFF (the default) this is always the original file.  A
        render failure degrades to the original file -- playing raw beats
        refusing -- and the fallback is logged, never silent.
        """
        with self._lock:
            cached = self._resolved.get(path)
        if cached is not None:
            return cached
        try:
            physical = audio_render.device_ready_wav(path)
        except Exception:
            logger.debug("device render probe failed for %s", path,
                         exc_info=True)
            physical = None
        rendered = bool(physical) and os.path.isfile(physical)
        if not rendered:
            render_requested = False
            try:
                rate = audio_render.device_sample_rate()
                render_requested = bool(
                    audio_render.render_enabled() and rate
                    and audio_render._source_rate(path)
                    and audio_render._source_rate(path) != rate)
            except Exception:
                render_requested = False
            if render_requested:
                self._log({
                    "event": "render_fallback",
                    "logical": path,
                    "reason": StopReason.RENDER_FAILED.value,
                })
            physical = path
        resolved = (physical, rendered)
        with self._lock:
            # bounded: one entry per distinct logical source
            if len(self._resolved) >= 256:
                self._resolved.clear()
            self._resolved[path] = resolved
        return resolved

    def _log(self, entry: dict[str, Any]) -> None:
        entry.setdefault("monotonic", time.monotonic())
        with self._lock:
            self._playback_log.append(entry)
            if len(self._playback_log) > self.PLAYBACK_TRACE_CAPACITY:
                del self._playback_log[:len(self._playback_log)
                                       - self.PLAYBACK_TRACE_CAPACITY]

    def playback_trace(self) -> list[dict[str, Any]]:
        """Bounded physical-source provenance for the last plays (spec 3).

        Every accepted PCM cue leaves ``pcm_start`` (request time, physical
        start time, logical/physical source, rendered flag, format) and one
        ``pcm_finish`` entry, so request -> physical start -> finish can be
        checked per token.
        """
        with self._lock:
            return [dict(entry) for entry in self._playback_log]

    def retirement_trace(self) -> list[dict[str, Any]]:
        """Every pool retirement: when, why, how many effects died."""
        with self._lock:
            return [dict(entry) for entry in self._retirements]

    def invalidate_sources(self) -> None:
        """Retire every pooled QSoundEffect and every live PCM voice (spec 5).

        Called when the render policy, edge padding, output-device rate or a
        managed sound file changes.  Playing channels are stopped because
        their physical representation is retired; future playback re-resolves
        under the NEW policy generation.  No retired effect or voice keeps any
        authority to make a sound.
        """
        voices = self._take_all_voices()
        with self._lock:
            effects: list[Any] = list(self._channels.values())
            self._channels.clear()
            self._owner.clear()
            self._completions.clear()
            for members in self._pools.values():
                effects.extend(entry.effect for entry in members)
            retired = len(effects) + len(voices)
            self._pools.clear()
            self._pool_order.clear()
            bound = list(self._bound.values())
            self._bound.clear()
            self._resolved.clear()
            self._pcm_cache.clear()
            self._pcm_cache_bytes = 0
            old_generation = self._policy_generation
            self._policy_generation += 1
        for effect, handler in bound:
            try:
                effect.playingChanged.disconnect(handler)
            except Exception:
                pass
        for voice in voices:
            self._silence_voice(voice, "invalidated")
        for effect in effects:
            try:
                effect.stop()
            except Exception:
                pass
            delete_later = getattr(effect, "deleteLater", None)
            if callable(delete_later):
                try:
                    delete_later()
                except Exception:
                    pass
        with self._lock:
            self._retirements.append({
                "monotonic": time.monotonic(),
                "reason": "invalidate_sources",
                "from_generation": old_generation,
                "to_generation": old_generation + 1,
                "effects": retired,
            })
            if len(self._retirements) > self.PLAYBACK_TRACE_CAPACITY:
                del self._retirements[:len(self._retirements)
                                       - self.PLAYBACK_TRACE_CAPACITY]
        logger.debug("audio transport retired %d sources (gen %d)",
                     retired, old_generation + 1)

    def close(self) -> None:
        """Transport shutdown: silence everything and refuse all future play.

        After close() no stale signal, watchdog or late Ready can produce a
        sound -- there is nothing left that holds playback authority.
        """
        with self._lock:
            self._closed = True
        self.invalidate_sources()

    def _status_name(self, effect) -> str:
        """Our stable name for the effect's source status ("" = unknown)."""
        if not self._status_map:
            return ""
        try:
            return self._status_map.get(effect.status(), "")
        except Exception:
            return ""

    def _error_string(self, effect) -> str:
        for attr in ("errorString", "error"):
            fn = getattr(effect, attr, None)
            if fn is None:
                continue
            try:
                value = fn()
            except Exception:
                continue
            if value:
                return str(value)[:200]
        return ""

    def _fail(self, token, path, reason, effect=None, exc=None,
              **extra: Any) -> None:
        detail: dict[str, Any] = {
            "reason": (reason.value if isinstance(reason, StopReason)
                       else str(reason)),
            "transport": "QtSoundTransport",
            "source": os.path.basename(path or ""),
            "file_exists": bool(path) and os.path.isfile(path),
        }
        if effect is not None:
            status = self._status_name(effect)
            if status:
                detail["status"] = status
            error = self._error_string(effect)
            if error:
                detail["error"] = error
        if exc is not None:
            detail["exception"] = type(exc).__name__   # TYPE only, no message
        detail.update(extra)
        self._failures.file(token, detail)

    # -- Transport contract --------------------------------------------------

    def preload(self, paths) -> None:
        """Warm sources so the first real cue can start immediately.

        With the PCM path this decodes the exact frames into the bounded
        cache; otherwise it creates (never starts) one pooled QSoundEffect per
        path.  Must be called from the GUI thread.
        """
        for path in paths or ():
            if not path or not os.path.isfile(path):
                continue
            try:
                if self._sinks is not None:
                    physical, _rendered = self._resolve_physical(path)
                    self._pcm_for(physical)
                else:
                    with self._lock:
                        self._acquire(path, token="preload")
            except Exception:
                continue

    def play(self, path, *, volume=1.0, loop=False, on_complete=None, token=""):
        t_request = time.perf_counter()
        if self._closed:
            self._fail(token, path, StopReason.TRANSPORT_UNAVAILABLE,
                       closed=True)
            return ""
        if not path or not os.path.isfile(path):
            self._fail(token, path, StopReason.FILE_MISSING)
            return ""
        if not loop and self._sinks is not None:
            physical, rendered = self._resolve_physical(path)
            pcm = self._pcm_for(physical)
            if pcm is not None:
                handle = self._play_pcm(path, physical, rendered, pcm, volume,
                                        on_complete, token, t_request)
                if handle is not None:
                    return handle            # started NOW, or truthfully ""
            # Not carriable as exact PCM (codec, size, device refused the
            # format): the QSoundEffect path below, with its provenance.
            self._log({"event": "pcm_fallback", "logical": path,
                       "physical": physical, "rendered": rendered,
                       "token": token})
        return self._play_effect(path, volume, loop, on_complete, token)

    # -- PCM sink path ---------------------------------------------------------

    def _pcm_for(self, physical: str) -> PcmSource | None:
        """Exact decoded frames for ``physical`` (bounded, file-change safe)."""
        signature = _file_signature(physical)
        if signature is None:
            return None
        with self._lock:
            cached = self._pcm_cache.get(physical)
            if cached is not None and cached.signature == signature:
                # LRU touch
                self._pcm_cache.pop(physical)
                self._pcm_cache[physical] = cached
                return cached
        pcm = read_pcm_wav(physical)
        if pcm is None:
            return None
        with self._lock:
            old = self._pcm_cache.pop(physical, None)
            if old is not None:
                self._pcm_cache_bytes -= len(old.data)
            while (self._pcm_cache
                   and self._pcm_cache_bytes + len(pcm.data) > PCM_CACHE_BUDGET):
                evicted = self._pcm_cache.pop(next(iter(self._pcm_cache)))
                self._pcm_cache_bytes -= len(evicted.data)
            if len(pcm.data) <= PCM_CACHE_BUDGET:
                self._pcm_cache[physical] = pcm
                self._pcm_cache_bytes += len(pcm.data)
        return pcm

    def _play_pcm(self, logical, physical, rendered, pcm: PcmSource, volume,
                  on_complete, token, t_request) -> str | None:
        """Start ONE fresh sink now.  ``None`` = use the fallback path."""
        with self._lock:
            if len(self._voices) >= MAX_PCM_VOICES:
                self._fail(token, logical, StopReason.POOL_EXHAUSTED,
                           backend="pcm_sink")
                return ""
            handle = f"qtch:{next(self._seq)}"
        try:
            sink, buffer = self._sinks.open(pcm, PCM_POSTROLL_MS)
        except SinkRefused as refused:
            if refused.reason is StopReason.UNSUPPORTED_FORMAT:
                return None
            self._fail(token, logical, refused.reason, backend="pcm_sink",
                       error=refused.detail)
            return ""
        except Exception as exc:
            self._fail(token, logical, StopReason.EFFECT_PLAY_EXCEPTION,
                       exc=exc, backend="pcm_sink")
            return ""
        # The completion is attached only once the start is confirmed: a
        # device that fails inside start() must not complete a channel the
        # hub never saw.
        voice = _PcmVoice(handle, token, logical, physical, rendered, sink,
                          buffer, None, t_request)
        with self._lock:
            self._voices[handle] = voice
        try:
            sink.setVolume(max(0.0, min(1.0, float(volume))))
            sink.stateChanged.connect(
                lambda state, h=handle: self._on_sink_state(h, state))
            sink.start(buffer)
            voice.t_start = time.perf_counter()
            error = self._sinks.error_name(sink)
            state = self._sinks.state_name(sink.state())
        except Exception as exc:
            self._drop_voice(handle)
            self._fail(token, logical, StopReason.EFFECT_PLAY_EXCEPTION,
                       exc=exc, backend="pcm_sink")
            return ""
        if error != "NoError" or "Stopped" in state:
            # The device refused to start: NOT a played channel.
            self._drop_voice(handle)
            self._fail(token, logical, StopReason.SOURCE_ERROR,
                       backend="pcm_sink", error=error, state=state)
            return ""
        with self._lock:
            if handle not in self._voices:     # stopped re-entrantly
                return ""
            voice.on_complete = on_complete
        try:
            voice.watchdog = self._sinks.watchdog(
                sink, pcm.duration_ms + PCM_POSTROLL_MS + PCM_WATCHDOG_GRACE_MS,
                lambda h=handle: self._finish_voice(h, "watchdog"))
        except Exception:
            voice.watchdog = None
        self._log({
            "event": "pcm_start",
            "backend": "pcm_sink",
            "token": token,
            "handle": handle,
            "logical": logical,
            "physical": physical,
            "rendered": rendered,
            "policy_generation": self._policy_generation,
            "format": f"{pcm.rate}Hz/{pcm.channels}ch/{pcm.sample_format}",
            "source_bits": pcm.source_bits,
            "frames": pcm.frames,
            "volume": round(max(0.0, min(1.0, float(volume))), 4),
            "t_request": t_request,
            "t_start": voice.t_start,
        })
        return handle

    def _on_sink_state(self, handle: str, state) -> None:
        name = self._sinks.state_name(state) if self._sinks else str(state)
        if "Idle" in name:
            # The exact frames AND the post-roll were handed to the mixer;
            # the only thing a stop can discard now is post-roll silence.
            self._finish_voice(handle, "drained")
        elif "Stopped" in name:
            with self._lock:
                voice = self._voices.get(handle)
            if voice is None:
                return          # our own stop(): a stale signal, ignore
            error = self._sinks.error_name(voice.sink) if self._sinks else ""
            self._finish_voice(handle, f"stopped:{error}")

    def _finish_voice(self, handle: str, reason: str) -> None:
        """Natural end (or dead device): retire the sink, then complete."""
        with self._lock:
            voice = self._voices.pop(handle, None)
        if voice is None:
            return              # stopped / retired already: stale, ignore
        callback = voice.on_complete
        self._retire_sink(voice)
        self._log({"event": "pcm_finish", "handle": handle,
                   "token": voice.token, "reason": reason,
                   "t_finish": time.perf_counter()})
        if callback is not None:
            try:
                callback()
            except Exception:
                logger.debug("transport completion callback failed",
                             exc_info=True)

    def _drop_voice(self, handle: str) -> _PcmVoice | None:
        """Remove a voice's authority and physically retire its sink."""
        with self._lock:
            voice = self._voices.pop(handle, None)
        if voice is not None:
            self._retire_sink(voice)
        return voice

    def _take_all_voices(self) -> list[_PcmVoice]:
        with self._lock:
            voices = list(self._voices.values())
            self._voices.clear()
        return voices

    def _silence_voice(self, voice: _PcmVoice, reason: str) -> None:
        self._retire_sink(voice)
        self._log({"event": "pcm_stop", "handle": voice.handle,
                   "token": voice.token, "reason": reason,
                   "t_finish": time.perf_counter()})

    def _retire_sink(self, voice: _PcmVoice) -> None:
        timer, voice.watchdog = voice.watchdog, None
        if timer is not None:
            try:
                timer.stop()
            except Exception:
                pass
        try:
            voice.sink.stateChanged.disconnect()
        except Exception:
            pass
        # reset() BEFORE stop(): measured on real Windows, QAudioSink pulls
        # ~300 ms of the buffer ahead, and stop() alone lets that read-ahead
        # play out -- a STOP ALL at +150 ms still sounded until +410 ms.
        # reset() drops the read-ahead, so silence starts now.  At a natural
        # end the only thing it can drop is post-roll silence.
        for name in ("reset", "stop"):
            try:
                getattr(voice.sink, name)()
            except Exception:
                pass
        if self._sinks is not None:
            try:
                self._sinks.retire(voice.sink)
            except Exception:
                pass
        voice.on_complete = None

    # -- QSoundEffect path (loops + fallback) ------------------------------------

    def _play_effect(self, path, volume, loop, on_complete, token) -> str:
        with self._lock:
            effect, entry = self._acquire(path, token=token)
            if effect is None:
                # pool exhausted, or the source could not be attached at all
                self._fail(token, path, self._last_acquire_reason)
                return ""
            status = self._status_name(effect)
            trace = {
                "event": "play",
                "backend": "qsoundeffect",
                "token": token,
                "logical": path,
                "physical": entry.physical_path,
                "rendered": entry.rendered,
                "policy_generation": entry.policy_generation,
                "handle": "",
                "effect": id(effect),
                "status_before_play": status,
            }
            self._log(trace)
            if status == "Error":
                self._fail(token, path, StopReason.SOURCE_ERROR, effect)
                return ""
            if status == "Loading":
                # T-1242 P0: refuse NOW.  The Ready transition later only
                # makes this effect available to a future request.
                self._fail(token, path, StopReason.SOURCE_LOADING, effect)
                return ""
            handle = f"qtch:{next(self._seq)}"
            try:
                effect.setVolume(max(0.0, min(1.0, float(volume))))
                effect.setLoopCount(self._infinite if loop else 1)
                self._channels[handle] = effect
                self._owner[id(effect)] = handle
                if on_complete is not None:
                    self._completions[handle] = on_complete
                self._bind(effect)
                effect.play()
                trace["handle"] = handle
                return handle
            except Exception as exc:
                self._forget(handle)
                self._fail(token, path, StopReason.EFFECT_PLAY_EXCEPTION,
                           effect, exc)
                return ""

    def stop(self, channel):
        voice = self._drop_voice(channel)
        if voice is not None:
            self._log({"event": "pcm_stop", "handle": channel,
                       "token": voice.token, "reason": "stop",
                       "t_finish": time.perf_counter()})
            return
        with self._lock:
            effect = self._forget(channel)
        if effect is None:
            return
        try:
            effect.stop()
        except Exception:
            pass

    def stop_all(self):
        voices = self._take_all_voices()
        for voice in voices:
            self._silence_voice(voice, "stop_all")
        with self._lock:
            effects = list(self._channels.values())
            self._channels.clear()
            self._owner.clear()
            self._completions.clear()
            # Emergency silence, NOT invalidation: the pools stay (each
            # effect still owns its own physical source) and only play is
            # stopped.  No transport state holds a deferred start, so nothing
            # can become audible after this returns.
            for members in self._pools.values():
                effects.extend(entry.effect for entry in members)
        for effect in effects:
            try:
                effect.stop()
            except Exception:
                pass

    def set_volume(self, channel, volume):
        level = max(0.0, min(1.0, float(volume)))
        with self._lock:
            voice = self._voices.get(channel)
            effect = None if voice is not None else self._channels.get(channel)
        target = voice.sink if voice is not None else effect
        if target is None:
            return
        try:
            target.setVolume(level)
        except Exception:
            pass

    def active_handles(self) -> list[str]:
        with self._lock:
            return sorted(set(self._channels) | set(self._voices))

    # -- internals -----------------------------------------------------------

    def _forget(self, handle: str):
        """Drop every trace of one effect channel; returns its effect."""
        effect = self._channels.pop(handle, None)
        self._completions.pop(handle, None)
        if effect is not None and self._owner.get(id(effect)) == handle:
            self._owner.pop(id(effect), None)
        return effect

    # -- PERF-004 pool budget ------------------------------------------------

    def _touch_pool(self, pool_key) -> None:
        """Mark ``pool_key`` as most-recently-used (caller holds the lock)."""
        self._pool_order.pop(pool_key, None)
        self._pool_order[pool_key] = None

    def _pool_evictable(self, pool_key) -> bool:
        """True when NO member holds playback authority (caller holds lock).

        An active channel (``_owner``) or an effect that reports
        ``isPlaying()`` is never evictable; an effect whose state cannot be
        asked is treated as playing and kept -- a cache bound must never
        gamble with live audio.
        """
        for entry in self._pools.get(pool_key) or ():
            effect = entry.effect
            if id(effect) in self._owner:
                return False
            try:
                if effect.isPlaying():
                    return False
            except Exception:
                return False
        return True

    def _retire_pool_locked(self, pool_key) -> int:
        """Remove one pool and physically retire its effects (caller holds lock)."""
        entries = self._pools.pop(pool_key, [])
        self._pool_order.pop(pool_key, None)
        for entry in entries:
            effect = entry.effect
            self._owner.pop(id(effect), None)
            self._unbind(effect)
            try:
                effect.stop()
            except Exception:
                pass
            delete_later = getattr(effect, "deleteLater", None)
            if callable(delete_later):
                try:
                    delete_later()
                except Exception:
                    pass
        return len(entries)

    def _evict_pools_for_capacity(self) -> int:
        """Retire least-recently-used inactive pools past ``MAX_POOLS``.

        Called before a NEW pool key is created.  Only fully inactive pools
        are candidates, oldest first; if every retained pool is audible the
        bound is deliberately exceeded rather than evicting live audio.
        """
        retired = 0
        while len(self._pools) >= self.MAX_POOLS:
            victim = None
            for key in list(self._pool_order):
                if key not in self._pools:
                    self._pool_order.pop(key, None)
                    continue
                if self._pool_evictable(key):
                    victim = key
                    break
            if victim is None:
                break
            retired += self._retire_pool_locked(victim)
        if retired:
            self._retirements.append({
                "monotonic": time.monotonic(),
                "reason": "pool_evict",
                "pools": len(self._pools),
                "effects": retired,
            })
            if len(self._retirements) > self.PLAYBACK_TRACE_CAPACITY:
                del self._retirements[:len(self._retirements)
                                       - self.PLAYBACK_TRACE_CAPACITY]
        return retired

    def pool_cardinality(self) -> tuple[int, int]:
        """(pool keys, effects) -- lets tests assert the bound without poking
        at private containers."""
        with self._lock:
            effects = sum(len(members) for members in self._pools.values())
            return len(self._pools), effects

    def _acquire(self, path, token: str = ""):
        """Return ``(effect, pool entry)`` for one play, or ``(None, None)``.

        The physical source is resolved FIRST; the pool is keyed by the
        resolved identity plus the policy generation, so every effect a
        caller can receive plays the same bytes (T-1242 spec 4).  A pooled
        effect that is still Loading is returned as-is: the caller refuses
        the request instead of creating more Loading effects.
        """
        self._last_acquire_reason = StopReason.POOL_EXHAUSTED
        physical, rendered = self._resolve_physical(path)
        with self._lock:
            generation = self._policy_generation
        pool_key = (path, physical, rendered, generation)
        with self._lock:
            if pool_key not in self._pools:
                # PERF-004: a new source is about to retain one more pool;
                # keep the global inactive budget before growing past it.
                self._evict_pools_for_capacity()
            pool = self._pools.setdefault(pool_key, [])
            self._touch_pool(pool_key)
        free: list[_PoolEntry] = []
        for entry in pool:
            effect = entry.effect
            if id(effect) in self._owner:
                continue  # an active channel owns it
            try:
                if effect.isPlaying():
                    continue
            except Exception:
                continue
            free.append(entry)
        if free:
            ready = [e for e in free
                     if self._status_name(e.effect) in ("", "Ready")]
            chosen = ready[0] if ready else free[0]
            self._last_acquire_reason = StopReason.NONE
            return chosen.effect, chosen
        if len(pool) < self.POOL_PER_PATH:
            try:
                self._last_acquire_reason = StopReason.UNSUPPORTED_FORMAT
                effect = self._QSE()
                # One effect owns ONE physical representation for its whole
                # life; a pooled effect's source is never re-resolved.
                effect.setSource(self._url(physical))
                effect.setVolume(1.0)
                entry = _PoolEntry(effect, physical, rendered, generation)
                pool.append(entry)
                if token:
                    self._log({
                        "event": "pool_create",
                        "logical": path,
                        "physical": physical,
                        "rendered": rendered,
                        "policy_generation": generation,
                        "handle": "",
                        "effect": id(effect),
                        "status_before_play": self._status_name(effect),
                    })
                self._last_acquire_reason = StopReason.NONE
                return effect, entry
            except Exception:
                return None, None
        self._last_acquire_reason = StopReason.POOL_EXHAUSTED
        return None, None  # C0.2: refuse rather than restart a busy effect

    def _bind(self, effect) -> None:
        with self._lock:
            entry = self._bound.get(id(effect))
            if entry is not None and entry[0] is effect:
                return

        def _changed(*_args) -> None:
            self._on_playing_changed(effect)

        try:
            effect.playingChanged.connect(_changed)
        except Exception:
            return
        with self._lock:
            # PERF-004: retaining the effect reference keeps id() from being
            # reused while the connection is live; retaining the handler lets
            # retirement disconnect it.
            self._bound[id(effect)] = (effect, _changed)

    def _unbind(self, effect) -> None:
        """Drop one playing-changed connection; a stale emitter keeps zero
        authority.  Safe on an effect that was never bound."""
        entry = self._bound.pop(id(effect), None)
        if entry is None or entry[0] is not effect:
            return
        try:
            effect.playingChanged.disconnect(entry[1])
        except Exception:
            pass

    def _on_playing_changed(self, effect) -> None:
        try:
            if effect.isPlaying():
                return
        except Exception:
            return
        with self._lock:
            handle = self._owner.get(id(effect))
            if handle is None:
                return  # explicitly stopped already: a stale signal, ignore
            if self._channels.get(handle) is not effect:
                # PERF-004: a retired effect whose id() was reused must never
                # complete the newer handle that now owns that id.
                return
            callback = self._completions.pop(handle, None)
            self._channels.pop(handle, None)
            self._owner.pop(id(effect), None)
        if callback is not None:
            callback()


def _make_default_transport() -> Transport:
    """Canonical packaged backend selection.

    Qt multimedia is the rich backend when importable and functional; the
    null transport is the truthful degraded fallback (no mixing, no
    ambience).  Never silently present NullTransport as MIX-capable.
    """
    try:
        return QtSoundTransport()
    except Exception:
        return NullTransport()


@dataclass
class PlayResult:
    """Provenance of one playback request, including its physical channel.

    Long-lived callers (ambience layers) need a durable identity they can
    later fade and stop; transient callers only look at ``outcome``.
    """

    outcome: Outcome
    request_id: str = ""
    channel: str = ""

    def __bool__(self) -> bool:  # pragma: no cover - convenience only
        return self.outcome not in DROPPED_OUTCOMES


@dataclass
class AudioSequence:
    """One logical multi-fragment audio job (e.g. 'thirty minutes remaining').

    A sequence is ONE queueable job: under Stack its fragments stay
    contiguous, under Replace the whole phrase (including the fragment
    currently sounding) is stopped.
    """

    fragments: list[str]
    mode: PlaybackMode = PlaybackMode.MIX
    volume: float = 1.0
    request_id: str = ""
    cancelled: bool = False
    bus: Bus = Bus.VOICE
    index: int = 0
    channel: str = ""
    generation: int = 0
    started: bool = False

    def __len__(self) -> int:
        return len(self.fragments)


@dataclass
class _PendingJob:
    path: str
    volume: float
    request_id: str
    event: str
    bus: Bus
    mode: PlaybackMode
    scope: Scope = Scope.BUS
    loop: bool = False
    sequence: AudioSequence | None = None
    allow_while_muted: bool = False


@dataclass
class _ActiveChannel:
    handle: str
    bus: Bus
    request_id: str
    event: str
    priority: int
    sequence_id: str = ""
    sequence_generation: int = 0
    long_lived: bool = False
    started_monotonic: float = field(default_factory=time.monotonic)


class _ProvenanceLog:
    """Bounded diagnostic ring; no user text, no permanent disk log."""

    def __init__(self, capacity: int = 256) -> None:
        self._entries: list[dict[str, Any]] = []
        self._capacity = capacity

    def record(self, **kwargs: Any) -> None:
        self._entries.append(kwargs)
        if len(self._entries) > self._capacity:
            del self._entries[: len(self._entries) - self._capacity]

    def snapshot(self) -> list[dict[str, Any]]:
        return list(self._entries)

    def clear(self) -> None:
        self._entries.clear()


class AudioHub:
    """The single audio authority behind the SoundManager facade."""

    def __init__(
        self,
        transport: Transport | None = None,
        *,
        global_mode: PlaybackMode | str = PlaybackMode.MIX,
        max_voices: int = MAX_TRANSIENT_VOICES,
        max_queue: int = MAX_QUEUE_PER_BUS,
    ) -> None:
        self._lock = threading.RLock()
        self._transport: Transport = (
            transport if transport is not None else _make_default_transport())
        self._global_mode = PlaybackMode.coerce(global_mode, PlaybackMode.MIX)
        self._max_voices = max(1, int(max_voices))
        self._max_queue = max(1, int(max_queue))
        self._channels: dict[str, _ActiveChannel] = {}
        # ONE chronological transient queue; each job remembers its bus so a
        # bus-scoped override still behaves per bus (C0.4/C0.5).
        self._queue: list[_PendingJob] = []
        self._sequences: dict[str, AudioSequence] = {}
        self._last_coalesce: dict[str, float] = {}
        self._provenance = _ProvenanceLog()
        self._stop_all_epoch = 0
        self._requests = itertools.count(1)
        self._request_counter = 0
        self._dropped_channel_limit = 0
        self._dropped_queue_full = 0
        self._dropped_busy = 0
        self._dropped_muted = 0
        self._coalesced = 0
        # T-1244: the global master mute.  While ON, every hub entry point
        # fails closed -- no caller can bypass master mute by addressing the
        # hub directly (Problip, Voice, Ambience, previews all enter here).
        self._muted = False

    def request_count(self) -> int:
        """Monotonic count of playback requests handled by this hub."""
        with self._lock:
            return self._request_counter

    # -- configuration -------------------------------------------------------

    def set_muted(self, muted: bool) -> None:
        """T-1244: engage or release the global master mute.

        Engaging mutes physically silences EVERYTHING the hub owns right
        now -- transient channels, queued jobs, voice sequences and
        long-lived ambience channels -- through the ONE existing STOP ALL
        mechanism, so no stale callback can ever resume after unmute.
        """
        muted = bool(muted)
        with self._lock:
            if self._muted == muted:
                return
            self._muted = muted
        if muted:
            self.stop_all()

    def is_muted(self) -> bool:
        """True while the global master mute is engaged."""
        with self._lock:
            return self._muted

    def set_global_mode(self, mode: PlaybackMode | str) -> None:
        with self._lock:
            resolved = PlaybackMode.coerce(mode, PlaybackMode.MIX)
            if resolved in (PlaybackMode.INHERIT, PlaybackMode.SKIP_BUSY):
                resolved = PlaybackMode.MIX  # no global "inherit from itself"
            self._global_mode = resolved

    @property
    def global_mode(self) -> PlaybackMode:
        return self._global_mode

    @property
    def transport(self) -> Transport:
        return self._transport

    def set_transport(self, transport: Transport) -> None:
        """Swap the backend (packaging/degradation probe, tests)."""
        with self._lock:
            self.stop_all()
            self._transport = transport

    def invalidate_sources(self) -> None:
        """Retire every pooled transport source (T-1242 spec 5).

        Render-policy changes (pre-render switch, edge padding, output rate,
        managed file replacement) must retire already-created QSoundEffect
        pool entries; otherwise the UI can say RAW while the transport keeps
        playing RENDERED.  Transports without the concept ignore it.
        """
        invalidate = getattr(self._transport, "invalidate_sources", None)
        if callable(invalidate):
            try:
                invalidate()
            except Exception:
                logger.debug("transport source invalidation failed",
                             exc_info=True)

    def transport_policy_generation(self) -> int:
        """The transport's render-policy generation (T-1242 spec 13).

        Problip pins this at START.  -1 when the transport has no such
        concept (fakes, NullTransport).
        """
        generation = getattr(self._transport, "render_policy_generation",
                             None)
        return generation() if callable(generation) else -1

    @property
    def capability_mixing(self) -> bool:
        return bool(getattr(self._transport, "capability_mixing", False))

    def diagnostics(self) -> dict[str, Any]:
        with self._lock:
            depths = {b.value: 0 for b in Bus}
            for job in self._queue:
                depths[job.bus.value] += 1
            return {
                "active_channels": len(self._channels),
                "transient_channels": sum(
                    1 for c in self._channels.values()
                    if c.bus in TRANSIENT_BUSES),
                "queue_depths": depths,
                "queue_depth": len(self._queue),
                "active_sequences": len(self._sequences),
                "dropped_channel_limit": self._dropped_channel_limit,
                "dropped_queue_full": self._dropped_queue_full,
                "dropped_busy": self._dropped_busy,
                "dropped_muted": self._dropped_muted,
                "muted": self._muted,
                "coalesced": self._coalesced,
                "stop_all_epoch": self._stop_all_epoch,
                "global_mode": self._global_mode.value,
                "capability_mixing": self.capability_mixing,
            }

    def provenance(self) -> list[dict[str, Any]]:
        return self._provenance.snapshot()

    def active_channel_count(self) -> int:
        with self._lock:
            return len(self._channels)

    def active_channels(self) -> list[dict[str, Any]]:
        with self._lock:
            return [
                {"handle": c.handle, "bus": c.bus.value, "event": c.event,
                 "request_id": c.request_id, "long_lived": c.long_lived}
                for c in self._channels.values()
            ]

    def queue_depth(self, bus: Bus | str | None = None) -> int:
        with self._lock:
            if bus is None:
                return len(self._queue)
            target = Bus(bus) if isinstance(bus, str) else bus
            return sum(1 for job in self._queue if job.bus is target)

    def transient_busy(self, buses: Iterable[Bus] | None = None) -> bool:
        """Is any transient channel (optionally restricted) sounding now?"""
        targets = frozenset(buses) if buses is not None else TRANSIENT_BUSES
        with self._lock:
            return any(c.bus in targets for c in self._channels.values())

    # -- core entry point ------------------------------------------------------

    def play(
        self,
        path: str,
        *,
        event: str = "",
        bus: Bus | str = Bus.UI,
        mode: PlaybackMode | str | None = None,
        volume: float = 1.0,
        priority: int | None = None,
        loop: bool = False,
        allow_while_muted: bool = False,
    ) -> Outcome:
        """Play one transient cue; returns the outcome only (compat API)."""
        return self.play_result(
            path, event=event, bus=bus, mode=mode, volume=volume,
            priority=priority, loop=loop,
            allow_while_muted=allow_while_muted).outcome

    def play_result(
        self,
        path: str,
        *,
        event: str = "",
        bus: Bus | str = Bus.UI,
        mode: PlaybackMode | str | None = None,
        volume: float = 1.0,
        priority: int | None = None,
        loop: bool = False,
        allow_while_muted: bool = False,
    ) -> PlayResult:
        """Play one cue and return outcome + request id + channel handle.

        While the master mute is engaged every request fails closed as
        ``DROPPED_MUTED`` -- unless the caller explicitly claims the
        mute-cue escape hatch (``allow_while_muted=True``), which is
        reserved for the canonical mute ON/OFF confirmation route.

        The mute decision is made while holding the SAME lock that protects
        queue/channel admission, so a request that passes the gate can never
        start after ``set_muted(True)`` has completed (T-1244 A1): either
        the request wins the lock and admits itself before the mute set,
        or the mute wins and the request is dropped -- never both.
        """
        with self._lock:
            self._request_counter += 1
            request_id = f"req{next(self._requests)}"
            bus = Bus(bus) if isinstance(bus, str) else bus
            resolved, scope = self._resolve_mode(mode)
            # The AUTHORITATIVE mute gate.  Checked under _lock together with
            # queue/channel admission, so the mute cannot become active
            # between "request passed the gate" and "request starts".
            if self._muted and not allow_while_muted:
                self._dropped_muted += 1
                self._record(request_id, event, bus, resolved, path,
                             Outcome.DROPPED_MUTED)
                return PlayResult(Outcome.DROPPED_MUTED, request_id)
            if event in HIGH_RATE_EVENTS and self._coalesce(event):
                self._record(request_id, event, bus, resolved, path,
                             Outcome.COALESCED)
                return PlayResult(Outcome.COALESCED, request_id)
            epoch = self._stop_all_epoch
            if resolved is PlaybackMode.SKIP_BUSY:
                if self.transient_busy(BUSY_BUSES):
                    self._dropped_busy += 1
                    self._record(request_id, event, bus, resolved, path,
                                 Outcome.DROPPED_BUSY)
                    return PlayResult(Outcome.DROPPED_BUSY, request_id)
                resolved = PlaybackMode.MIX
            if resolved is PlaybackMode.QUEUE:
                return self._enqueue(
                    _PendingJob(path, volume, request_id, event, bus, resolved,
                                scope, loop,
                                allow_while_muted=allow_while_muted))
            if resolved is PlaybackMode.REPLACE:
                return self._replace(path, volume, request_id, event, bus,
                                     resolved, scope, priority, loop,
                                     allow_while_muted)
            return self._mix(path, volume, request_id, event, bus, resolved,
                             epoch, priority, loop, allow_while_muted)

    def start_channel(
        self,
        path: str,
        *,
        event: str = "",
        bus: Bus | str = Bus.AMBIENCE,
        volume: float = 1.0,
        loop: bool = False,
    ) -> PlayResult:
        """Start ONE long-lived channel outside the transient queue domain.

        Ambience layers use this: they are not transient cues, so the global
        Stack/Replace setting must not order or replace them, but they still
        need a durable channel identity for fades and STOP AMBIENCE.
        """
        bus = Bus(bus) if isinstance(bus, str) else bus
        with self._lock:
            self._request_counter += 1
        request_id = f"amb{next(self._requests)}"
        with self._lock:
            if self._muted:
                # T-1244: ambience cannot start (or restart on an evaluate
                # tick) while master mute is ON.  The logical rule stays
                # enabled; only the physical channel is refused.
                self._dropped_muted += 1
                self._record(request_id, event, bus, PlaybackMode.MIX, path,
                             Outcome.DROPPED_MUTED)
                return PlayResult(Outcome.DROPPED_MUTED, request_id)
            return self._start_channel(
                path, volume, request_id, event, bus, PlaybackMode.MIX, None,
                replace=False, loop=loop, long_lived=True)

    def set_channel_volume(self, handle: str, volume: float) -> None:
        """Change one live channel's volume (fade drivers use this)."""
        if not handle:
            return
        with self._lock:
            if handle not in self._channels:
                return
        try:
            self._transport.set_volume(handle, max(0.0, min(1.0, float(volume))))
        except Exception:
            pass

    def stop_channel_handle(self, handle: str) -> None:
        """Physically stop exactly one channel by its transport handle."""
        if not handle:
            return
        with self._lock:
            channel = self._channels.pop(handle, None)
            self._transport.stop(handle)
        if channel is not None and channel.bus in TRANSIENT_BUSES:
            self._drain_queue()

    def channel_alive(self, handle: str) -> bool:
        """True while the hub still owns this channel (T-1244 liveness).

        Long-lived owners (ambience layers) use this to notice that an
        external STOP ALL -- e.g. the master mute -- retired their channel
        underneath them, so a later evaluation can restart cleanly instead
        of believing a dead handle is still audible.
        """
        if not handle:
            return False
        with self._lock:
            return handle in self._channels

    def stop_bus(self, bus: Bus | str) -> None:
        """Stop every channel and pending job on one bus."""
        target = Bus(bus) if isinstance(bus, str) else bus
        with self._lock:
            self._stop_scope({target})

    # -- mode resolution --------------------------------------------------------

    def _resolve_mode(
        self, mode: PlaybackMode | str | None,
    ) -> tuple[PlaybackMode, Scope]:
        """Resolve the effective mode and how far its decision reaches.

        An inherited mode is the user's GLOBAL setting and therefore acts on
        the whole transient domain; an explicit per-event override acts on
        its own bus only.
        """
        if mode is None:
            return self._global_mode, Scope.GLOBAL
        coerced = PlaybackMode.coerce(mode, self._global_mode)
        if coerced is PlaybackMode.INHERIT:
            return self._global_mode, Scope.GLOBAL
        return coerced, Scope.BUS

    def _scope_targets(self, bus: Bus, scope: Scope) -> frozenset[Bus]:
        if scope is Scope.GLOBAL and bus in TRANSIENT_BUSES:
            return TRANSIENT_BUSES
        return frozenset({bus})

    # -- mode implementations ----------------------------------------------------

    def _mix(self, path, volume, request_id, event, bus, mode, epoch, priority,
             loop, allow_while_muted=False) -> PlayResult:
        if len(self._channels) >= self._max_voices:
            incoming = (priority if priority is not None
                        else _default_priority(bus))
            if not self._evict_one(incoming):
                self._dropped_channel_limit += 1
                self._record(request_id, event, bus, mode, path,
                             Outcome.DROPPED_CHANNEL_LIMIT)
                return PlayResult(Outcome.DROPPED_CHANNEL_LIMIT, request_id)
        if epoch != self._stop_all_epoch:
            return PlayResult(Outcome.STOPPED, request_id)
        return self._start_channel(path, volume, request_id, event, bus, mode,
                                   priority, replace=False, loop=loop,
                                   allow_while_muted=allow_while_muted)

    def _start_channel(self, path, volume, request_id, event, bus, mode,
                       priority, replace, loop=False, long_lived=False,
                       sequence: AudioSequence | None = None,
                       allow_while_muted=False) -> PlayResult:
        # The completion callback only knows the handle after play() returns;
        # a mutable cell bridges the gap and self-removes the channel.
        cell: dict[str, Callable[[], None]] = {}
        epoch = self._stop_all_epoch

        def _on_complete() -> None:
            if epoch != self._stop_all_epoch:
                return  # STOP ALL happened: nothing stale may resume
            done = cell.get("done")
            if done is not None:
                done()

        handle = self._transport.play(
            path, volume=volume, loop=loop, token=request_id,
            on_complete=_on_complete)
        if not handle:
            # T-1242 spec 3: a refused physical start is never an unexplained
            # STOPPED -- the transport's own reason travels with the record.
            self._record(request_id, event, bus, mode, path, Outcome.STOPPED,
                         **self._failure_detail(request_id, path))
            return PlayResult(Outcome.STOPPED, request_id)
        # T-1244 A1: the mute gate is atomic with admission under _lock, but
        # the physical start itself can still overlap a mute that engages
        # reentrantly (a transport that calls set_muted() from inside its own
        # play(), or any future async backend).  A channel must NEVER register
        # after the master mute became active: stop it and report truthfully.
        if self._muted and not allow_while_muted:
            try:
                self._transport.stop(handle)
            except Exception:
                pass
            self._record(request_id, event, bus, mode, path, Outcome.STOPPED,
                         reason="muted_mid_admission")
            return PlayResult(Outcome.STOPPED, request_id)

        def _done(handle=handle) -> None:
            self._channel_finished(handle)

        cell["done"] = _done
        self._channels[handle] = _ActiveChannel(
            handle, bus, request_id, event,
            priority if priority is not None else _default_priority(bus),
            sequence_id=sequence.request_id if sequence is not None else "",
            sequence_generation=sequence.generation if sequence is not None else 0,
            long_lived=long_lived)
        if sequence is not None:
            sequence.channel = handle
            sequence.started = True
        others = len(self._channels) > 1
        if replace:
            outcome = Outcome.REPLACED
        else:
            outcome = Outcome.MIXED if others else Outcome.PLAYED
        self._record(request_id, event, bus, mode, path, outcome)
        return PlayResult(outcome, request_id, handle)

    # -- the one transient queue ---------------------------------------------------

    def _enqueue(self, job: _PendingJob) -> PlayResult:
        if self.queue_depth(job.bus) >= self._max_queue:
            self._dropped_queue_full += 1
            self._record(job.request_id, job.event, job.bus, job.mode,
                         job.path, Outcome.DROPPED_QUEUE_FULL)
            return PlayResult(Outcome.DROPPED_QUEUE_FULL, job.request_id)
        self._queue.append(job)
        self._drain_queue(locked=True)
        self._record(job.request_id, job.event, job.bus, job.mode, job.path,
                     Outcome.QUEUED, queue_position=self.queue_depth(job.bus))
        return PlayResult(Outcome.QUEUED, job.request_id)

    def _eligible(self, job: _PendingJob) -> bool:
        if job.scope is Scope.GLOBAL:
            return not any(c.bus in TRANSIENT_BUSES
                           for c in self._channels.values())
        return not self._bus_has_active(job.bus)

    def _drain_queue(self, locked: bool = False) -> None:
        """Start whatever the queue now allows, in chronological order."""
        if not locked:
            with self._lock:
                self._drain_queue(locked=True)
            return
        progress = True
        while progress and self._queue:
            progress = False
            for index, job in enumerate(list(self._queue)):
                if self._eligible(job):
                    self._queue.pop(index)
                    self._start_job(job)
                    progress = True
                    break
                if job.scope is Scope.GLOBAL:
                    return  # a global-order job blocks the whole FIFO
        return

    def _start_job(self, job: _PendingJob) -> None:
        if job.sequence is not None:
            self._start_sequence_fragment(job.sequence)
            return
        self._start_channel(job.path, job.volume, job.request_id, job.event,
                            job.bus, job.mode, None, replace=False,
                            loop=job.loop,
                            allow_while_muted=job.allow_while_muted)

    def _replace(self, path, volume, request_id, event, bus, mode, scope,
                 priority, loop, allow_while_muted=False) -> PlayResult:
        self._stop_scope(self._scope_targets(bus, scope))
        return self._start_channel(path, volume, request_id, event, bus, mode,
                                   priority, replace=True, loop=loop,
                                   allow_while_muted=allow_while_muted)

    def _stop_scope(self, targets: Iterable[Bus]) -> None:
        """Physically silence a scope: channels, queued jobs and sequences."""
        target_set = frozenset(targets)
        self._cancel_sequences(target_set)
        for handle, channel in list(self._channels.items()):
            if channel.bus in target_set:
                self._channels.pop(handle, None)
                self._transport.stop(handle)
        self._queue[:] = [j for j in self._queue if j.bus not in target_set]

    def _evict_one(self, incoming_priority: int) -> bool:
        """Drop the lowest-priority active channel when allowed."""
        candidates = [c for c in self._channels.values() if not c.long_lived]
        if not candidates:
            return False
        lowest = min(candidates,
                     key=lambda c: (c.priority, -c.started_monotonic))
        if lowest.priority >= incoming_priority:
            return False  # never evict equal-or-higher priority
        self._channels.pop(lowest.handle, None)
        self._transport.stop(lowest.handle)
        return True

    def _bus_has_active(self, bus: Bus) -> bool:
        return any(c.bus is bus for c in self._channels.values())

    def _channel_finished(self, handle: str) -> None:
        advance: AudioSequence | None = None
        with self._lock:
            channel = self._channels.pop(handle, None)
            if channel is None:
                return  # already stopped explicitly: a stale completion
            if channel.sequence_id:
                seq = self._sequences.get(channel.sequence_id)
                if (seq is not None and not seq.cancelled
                        and seq.generation == channel.sequence_generation):
                    seq.channel = ""
                    seq.index += 1
                    if seq.index < len(seq.fragments):
                        advance = seq
                    else:
                        self._sequences.pop(seq.request_id, None)
        if advance is not None:
            with self._lock:
                self._start_sequence_fragment(advance)
            return
        self._drain_queue()

    def stop_channel(self, request_id: str) -> None:
        with self._lock:
            for handle, ch in list(self._channels.items()):
                if ch.request_id == request_id:
                    self._channels.pop(handle, None)
                    self._transport.stop(handle)
        self._drain_queue()

    # -- sequences ---------------------------------------------------------------

    def play_sequence(
        self,
        fragments: list[str],
        *,
        bus: Bus | str = Bus.VOICE,
        mode: PlaybackMode | str | None = None,
        volume: float = 1.0,
        event: str = "voice_phrase",
    ) -> AudioSequence:
        """Play fragments as ONE logical job.

        Under Stack the phrase is one queue entry, so no ordinary click can
        land between "thirty" and "minutes".  Under Replace the previous
        phrase in scope is physically stopped mid-fragment.  STOP ALL kills
        it, and nothing stale can resume after the epoch changes.
        """
        bus = Bus(bus) if isinstance(bus, str) else bus
        resolved, scope = self._resolve_mode(mode)
        if resolved is PlaybackMode.SKIP_BUSY:
            resolved = PlaybackMode.MIX
        request_id = f"seq{next(self._requests)}"
        seq = AudioSequence(fragments=list(fragments), mode=resolved,
                            volume=volume, request_id=request_id, bus=bus)
        with self._lock:
            if not seq.fragments:
                return seq
            if self._muted:
                # T-1244: a voice phrase is a queue/sequence job like any
                # other -- cancelled, recorded as DROPPED_MUTED, and no
                # fragment may ever start (no stale replay after unmute).
                self._dropped_muted += 1
                seq.cancelled = True
                seq.generation += 1
                self._record(request_id, event, bus, resolved,
                             seq.fragments[0], Outcome.DROPPED_MUTED)
                return seq
            if resolved is PlaybackMode.REPLACE:
                self._stop_scope(self._scope_targets(bus, scope))
            self._sequences[request_id] = seq
            if resolved is PlaybackMode.QUEUE:
                job = _PendingJob(seq.fragments[0], volume, request_id, event,
                                  bus, resolved, scope, False, seq)
                if self.queue_depth(bus) >= self._max_queue:
                    self._dropped_queue_full += 1
                    self._sequences.pop(request_id, None)
                    seq.cancelled = True
                    self._record(request_id, event, bus, resolved,
                                 seq.fragments[0], Outcome.DROPPED_QUEUE_FULL)
                    return seq
                self._queue.append(job)
                self._record(request_id, event, bus, resolved,
                             seq.fragments[0], Outcome.QUEUED,
                             queue_position=self.queue_depth(bus))
                self._drain_queue(locked=True)
                return seq
            self._start_sequence_fragment(seq)
        return seq

    def _start_sequence_fragment(self, seq: AudioSequence) -> None:
        if seq.cancelled or seq.index >= len(seq.fragments):
            self._sequences.pop(seq.request_id, None)
            return
        result = self._start_channel(
            seq.fragments[seq.index], seq.volume, seq.request_id,
            f"voice:{seq.index}", seq.bus, seq.mode, None, replace=False,
            sequence=seq)
        if not result.channel:
            self._sequences.pop(seq.request_id, None)
            seq.cancelled = True

    def active_sequences(self, bus: Bus | None = None) -> list[AudioSequence]:
        with self._lock:
            return [s for s in self._sequences.values()
                    if bus is None or s.bus is bus]

    def cancel_sequences(self, bus: Bus | str | None = None) -> None:
        with self._lock:
            if bus is None:
                self._cancel_sequences(None)
            else:
                target = Bus(bus) if isinstance(bus, str) else bus
                self._cancel_sequences(frozenset({target}))
        self._drain_queue()

    def _cancel_sequences(self, buses: frozenset[Bus] | None) -> None:
        """Cancel sequences in scope AND physically stop their fragment."""
        for request_id, seq in list(self._sequences.items()):
            if buses is not None and seq.bus not in buses:
                continue
            seq.cancelled = True
            seq.generation += 1
            handle = seq.channel
            seq.channel = ""
            if handle:
                self._channels.pop(handle, None)
                self._transport.stop(handle)
            self._sequences.pop(request_id, None)
        self._queue[:] = [
            j for j in self._queue
            if j.sequence is None or (buses is not None and j.bus not in buses)
        ]

    # -- STOP ALL -----------------------------------------------------------------

    def stop_all(self) -> None:
        """Emergency silence. Nothing stale may resume."""
        with self._lock:
            self._stop_all_epoch += 1
            self._channels.clear()
            self._queue.clear()
            for seq in self._sequences.values():
                seq.cancelled = True
                seq.generation += 1
                seq.channel = ""
            self._sequences.clear()
            self._last_coalesce.clear()
        self._transport.stop_all()

    def close(self) -> None:
        """Shutdown: STOP ALL, then retire the transport for good.

        After close() no queued job, sequence, late completion or transport
        signal can make a sound; the transport refuses every later play.
        """
        self.stop_all()
        close = getattr(self._transport, "close", None)
        if callable(close):
            try:
                close()
            except Exception:
                logger.debug("transport close failed", exc_info=True)

    # -- coalescing ------------------------------------------------------------------

    def _coalesce(self, event: str) -> bool:
        now = time.monotonic()
        last = self._last_coalesce.get(event)
        self._last_coalesce[event] = now
        if last is not None and (now - last) < COALESCE_WINDOW_S:
            self._coalesced += 1
            return True
        return False

    def _failure_detail(self, request_id: str, path: str) -> dict[str, Any]:
        """Whatever the transport recorded about this refused start."""
        take = getattr(self._transport, "take_failure", None)
        detail = None
        if callable(take):
            try:
                detail = take(request_id)
            except Exception:
                detail = None
        if not isinstance(detail, dict):
            detail = {
                "reason": StopReason.TRANSPORT_UNAVAILABLE.value,
                "transport": type(self._transport).__name__,
                "file_exists": bool(path) and os.path.isfile(path),
            }
        detail.pop("source", None)     # already carried as ``asset``
        return detail

    def preload(self, paths: Iterable[str]) -> None:
        """Ask the transport to warm the given sources (never plays them)."""
        warm = getattr(self._transport, "preload", None)
        if not callable(warm):
            return
        try:
            warm(list(paths))
        except Exception:
            pass

    def _record(self, request_id, event, bus, mode, asset, outcome,
                queue_position: int | None = None, **extra: Any) -> None:
        self._provenance.record(
            request_id=request_id, event=event, bus=bus.value,
            mode=mode.value, asset=os.path.basename(asset or ""),
            outcome=outcome.value, queue_position=queue_position,
            monotonic=time.monotonic(), **extra)


def _default_priority(bus: Bus) -> int:
    return {
        Bus.AMBIENCE: BusPriority.AMBIENCE,
        Bus.PROBLIP: BusPriority.PROBLIP,
        Bus.UI: BusPriority.UI,
        Bus.ALERT: BusPriority.ALERT,
        Bus.VOICE: BusPriority.VOICE,
        Bus.PREVIEW: BusPriority.PREVIEW,
    }.get(bus, BusPriority.UI)
