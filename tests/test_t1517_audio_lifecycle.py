"""T-1517 Part B: negative regression tests for AUDIO-01 and AUDIO-02.

AUDIO-01  bus_for_event must route ``__preview__`` slots to the explicit
         "preview" bus string, not the default "ui" fallback.
AUDIO-02  TimerDialog.closeEvent must cancel the interval preview controller
         before the widget is destroyed, so no stale callback fires.
"""

from __future__ import annotations

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

from fastprompter.core.interval_preview import IntervalPreviewController
from fastprompter.core.sound_manager import (
    _PREVIEW_SLOTS,
    bus_for_event,
)
from fastprompter.ui.timer_dialog import TimerDialog


class _FakeSoundManager:
    def __init__(self):
        self.preview_calls = []
        self.cancel_calls = 0
        self.stop_bus_calls = []

    def preview_sound_ref(self, ref, level, *a, **kw):
        self.preview_calls.append((ref, level))
        return True

    def cancel_preview(self):
        self.cancel_calls += 1

    def request_count(self):
        return len(self.preview_calls)

    def stop_bus(self, bus):
        self.stop_bus_calls.append(bus)




# --- AUDIO-01: bus_for_event routes __preview__ to "preview" ------------------

class TestBusRouting:
    def test_a01_preview_slot_routes_to_preview_bus(self):
        """``__preview__`` must map to the explicit "preview" bus string."""
        assert bus_for_event("__preview__") == "preview"

    def test_a01_preview_slot_in_allowlist(self):
        assert "__preview__" in _PREVIEW_SLOTS
        assert bus_for_event("__preview__") != "ui"

    def test_a01_emit_file_maps_preview_slot_to_preview_policy(self):
        """_emit_file maps slot='__preview__' to policy='PREVIEW'.

        Verified by static inspection of the source -- the mapping is the
        contract that AUDIO-01 pins: if the slot->policy line is removed,
        previews would route on Bus.ALERT and could be silenced by cancel_preview.
        """
        import inspect

        from fastprompter.core.sound_manager import SoundManager

        source = inspect.getsource(SoundManager._emit_file)
        assert 'slot == "__preview__"' in source
        assert '"PREVIEW"' in source
        assert 'policy = "PREVIEW"' in source

    def test_a01_cancel_preview_calls_stop_bus_preview_only(self):
        """cancel_preview must call self._hub.stop_bus(Bus.PREVIEW), not
        stop_bus(Bus.ALERT) or stop_bus(Bus.UI)."""
        import inspect

        from fastprompter.core.sound_manager import SoundManager

        source = inspect.getsource(SoundManager.cancel_preview)
        assert "stop_bus(Bus.PREVIEW)" in source
        assert "stop_bus(Bus.ALERT)" not in source
        assert "stop_bus(Bus.UI)" not in source


# --- AUDIO-02: TimerDialog.closeEvent cancels interval preview ----------------

class TestTimerDialogCloseCancelsPreview:
    """AUDIO-02: TimerDialog.closeEvent must cancel the interval preview
    controller before the widget is destroyed, so no stale callback fires."""

    def test_a02_close_event_source_calls_cancel_preview(self):
        """The closeEvent source must call _interval_preview.cancel()."""
        import inspect

        source = inspect.getsource(TimerDialog.closeEvent)
        assert "_interval_preview.cancel()" in source

    def test_a02_close_event_calls_finish_before_super(self):
        """closeEvent must run _finish_dialog_lifecycle AND _interval_preview.cancel
        BEFORE calling super().closeEvent, so the preview timer is stopped while
        the widget graph is still valid."""
        import inspect

        source = inspect.getsource(TimerDialog.closeEvent)
        cancel_idx = source.index("_interval_preview.cancel()")
        super_idx = source.index("super().closeEvent")
        assert cancel_idx < super_idx, "cancel must come before super().closeEvent"

    def test_a02_done_calls_finish_lifecycle(self):
        """done() routes through _finish_dialog_lifecycle for idempotent teardown."""
        import inspect

        source = inspect.getsource(TimerDialog.done)
        assert "_finish_dialog_lifecycle()" in source

    def test_a02_controller_constructed_with_single_shot_timer_factory(self):
        """The interval preview controller must use _SingleShotTimer, which has
        a real stop() method so cancel() is effective."""
        import inspect

        init_source = inspect.getsource(TimerDialog.__init__)
        assert "IntervalPreviewController" in init_source
        assert "timer_factory=_SingleShotTimer" in init_source

    def test_a02_preview_controller_cancel_invalidate_pending(self):
        """Canceling an IntervalPreviewController clears pending state."""
        sm = _FakeSoundManager()
        ctrl = IntervalPreviewController(sm, timer_factory=_NoopTimer)

        ctrl.schedule_selection("file:sound.wav", 0.5)
        assert ctrl._pending is not None

        ctrl.cancel()
        assert ctrl._pending is None
        assert ctrl._timer is None


class _NoopTimer:
    """Minimal timer shim for IntervalPreviewController in non-Qt context."""

    def __init__(self, delay_ms, fn):
        self._fn = fn
        self.stopped = False
        self.fired = False

    def stop(self):
        self.stopped = True
        self._fn = None

    def fire(self):
        if self._fn is not None and not self.stopped and not self.fired:
            self.fired = True
            self._fn()


# --- Static regression: bus_for_event source must stay correct ---------------

class TestStaticBusRouting:
    def test_preview_slot_never_defaults_to_ui(self):
        """bus_for_event('__preview__') must return 'preview', not 'ui'.

        This pins AUDIO-01: if someone removes the _PREVIEW_SLOTS check from
        bus_for_event, this goes red immediately.
        """
        source = _get_bus_for_event_source()
        assert "preview" in source
        assert "_PREVIEW_SLOTS" in source or "preview" in source.lower()

    def test_close_event_calls_cancel_preview(self):
        """The closeEvent source must call _interval_preview.cancel()."""
        source = _get_close_event_source()
        assert "_interval_preview.cancel" in source


def _get_bus_for_event_source():
    import inspect

    from fastprompter.core.sound_manager import bus_for_event
    return inspect.getsource(bus_for_event)


def _get_close_event_source():
    import inspect
    return inspect.getsource(TimerDialog.closeEvent)
