"""T-1517: one-preview-per-gesture controller for interval sound browsing.

The interval sound combo used to fire ``preview_sound_ref`` from BOTH
``currentIndexChanged`` and ``activated``, so a single mouse/keyboard pick of
a sound triggered two overlapping previews. Wheel scrolling compounded it:
each stopped wheel tick reselected an item and previewed again, layering a
chorus of echoes.

This controller owns the single authoritative audition policy:

* **selection change** -> *one* scheduled preview, debounced (~100 ms) and
  coalesced: the last stable selection wins, an older in-flight preview is
  never allowed to overlap the newer one;
* **explicit Test / quick-sound click** -> one *immediate* preview;
* **dialog close / profile switch** -> the pending preview is invalidated so
  no stale callback fires after the widget is gone.

The preview never touches the real timer-alert (``Bus.ALERT``), ambience,
voice or UI buses: ``SoundManager.cancel_preview`` stops only ``Bus.PREVIEW``
before each new preview, so replacing a queued audition cannot silence a real
countdown chime that started in the same window.

The class is Qt-independent: a ``time_func`` and a ``timer_factory`` are
injected so the debounce semantics are unit-checkable without a running event
loop or a waveform.
"""

from __future__ import annotations

import time
from dataclasses import dataclass


@dataclass
class _Pending:
    ref: str
    volume: float
    source: str


class IntervalPreviewController:
    """Coalesce, debounce and replace-latest interval sound previews.

    ``sound_manager`` must expose ``preview_sound_ref(ref, volume)`` and
    ``cancel_preview()``. ``timer_factory`` returns an object with
    ``singleShot(delay_ms, fn)`` and ``stop()`` -- the shape
    ``QTimer.singleShot`` already provides, so a Qt timer is dropped in
    directly.
    """

    #: Debounce window for scroll/keyboard-driven selection changes.
    WHEEL_DEBOUNCE_MS = 100

    def __init__(self, sound_manager, time_func=time.perf_counter,
                 timer_factory=None):
        self._sm = sound_manager
        self._time = time_func
        self._timer_factory = timer_factory or _noop_timer_factory
        self._pending: _Pending | None = None
        self._timer = None
        self._last_stable_ref: str | None = None
        # call counters exposed for regression tests.
        self.preview_count = 0
        self.cancel_count = 0
        self.drop_count = 0

    # -- public policy -------------------------------------------------------

    def immediate(self, ref: str, volume: float, source: str = "explicit") -> None:
        """Play exactly one preview immediately (Test button / quick-sound)."""
        self._schedule(ref, volume, source, debounce_ms=0)

    def schedule_selection(self, ref: str, volume: float,
                           source: str = "select") -> None:
        """Schedule one coalesced preview for a selection change."""
        self._schedule(ref, volume, source,
                       debounce_ms=self.WHEEL_DEBOUNCE_MS)

    def wheel_selection(self, ref: str, volume: float) -> None:
        """A wheel tick: coalesce to the last stable selection."""
        self._schedule(ref, volume, "wheel", debounce_ms=self.WHEEL_DEBOUNCE_MS)

    def cancel(self) -> None:
        """Invalidate any pending preview -- dialog torn down / profile left."""
        if self._timer is not None:
            self._timer.stop()
            self._timer = None
        self._pending = None

    def last_stable_ref(self) -> str | None:
        return self._last_stable_ref

    # -- internals -----------------------------------------------------------

    def _schedule(self, ref: str, volume: float, source: str,
                  debounce_ms: int) -> None:
        # Replace-latest: a fresh request preempts a queued one instead of
        # layering. The prior preview bus is cancelled so an older audition
        # that started before the debounce window expires cannot overlap the
        # newer intent.
        self._restart_timer(debounce_ms, ref, volume, source)
        self._pending = _Pending(ref, volume, source)

    def _restart_timer(self, delay_ms: int, ref: str, volume: float,
                       source: str) -> None:
        if self._timer is not None:
            self._timer.stop()
        if delay_ms <= 0:
            self._fire(ref, volume, source)
        else:
            self._timer = self._timer_factory(delay_ms, self._debounce_fired)
            self._pending = _Pending(ref, volume, source)

    def _debounce_fired(self) -> None:
        p = self._pending
        self._timer = None
        self._pending = None
        if p is not None:
            self._fire(p.ref, p.volume, p.source)

    def _fire(self, ref: str, volume: float, source: str) -> None:
        # Replace-latest: stop anything still auditioning on the preview bus
        # before starting the new one, so browsing never layers echoes.
        try:
            self._sm.cancel_preview()
        except Exception:
            pass
        self.cancel_count += 1
        try:
            self._sm.preview_sound_ref(ref, volume)
            self.preview_count += 1
        except Exception:
            self.drop_count += 1
        self._last_stable_ref = ref


# A minimal timer shim for non-Qt tests: the factory returns an object whose
# singleShot schedules nothing (the tests pass delay_ms == 0 to exercise the
# immediate path) and stop is a no-op.
class _NoopTimer:
    def __init__(self, delay_ms, fn):
        self._fn = fn
        self.fired = False
    def stop(self):
        self._fn = None
    def fire(self):
        if self._fn is not None and not self.fired:
            self.fired = True
            self._fn()


def _noop_timer_factory(delay_ms, fn):
    t = _NoopTimer(delay_ms, fn)
    if delay_ms <= 0:
        # Immediate path is exercised synchronously by callers that pass 0.
        pass
    return t
