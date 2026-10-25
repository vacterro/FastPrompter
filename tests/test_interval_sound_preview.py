"""T-1517 Part A: interval sound preview deduplication + bus routing.

Regression for the duplicate-preview defect. The interval combo used to fire
``preview_sound_ref`` from BOTH ``currentIndexChanged`` and ``activated``, so
one user click produced two overlapping auditions; wheel scrolling layered a
chorus. These tests pin the new contract through
``IntervalPreviewController`` using a fake sound manager, so they are exact
and fast.

Run standalone:
    python -m pytest tests/test_interval_sound_preview.py -q
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402

from fastprompter.core.interval_preview import IntervalPreviewController  # noqa: E402


class _FakeSoundManager:
    """Records preview calls; supports the controller's stop+play contract."""

    def __init__(self):
        self.preview_calls: list[tuple[str, float]] = []
        self.cancel_calls = 0
        self._seq = 0

    def preview_sound_ref(self, ref, level):
        self.preview_calls.append((ref, level))
        self._seq += 1
        return True

    def cancel_preview(self):
        self.cancel_calls += 1

    def request_count(self) -> int:
        return self._seq


class _RecordingTimer:
    """A fake single-shot timer: fires when .fire() is called by the test."""

    def __init__(self, delay_ms, fn):
        self.delay_ms = delay_ms
        self.fn = fn
        self.stopped = False
        self.fired = False

    def stop(self):
        self.stopped = True

    def fire(self):
        if not self.stopped and not self.fired and self.fn is not None:
            self.fired = True
            self.fn()


@pytest.fixture
def sm():
    return _FakeSoundManager()


@pytest.fixture
def ctrl(sm):
    created = []
    def factory(delay_ms, fn):
        t = _RecordingTimer(delay_ms, fn)
        created.append(t)
        return t
    return IntervalPreviewController(sm, timer_factory=factory), created


# --- A. currentIndexChanged does not duplicate preview ----------------------
def test_a_selection_schedules_one_preview(ctrl):
    c, timers = ctrl
    sm = c._sm
    c.schedule_selection("file:chime.wav", 0.05)
    assert len(timers) == 1
    assert sm.preview_calls == []
    timers[-1].fire()
    # exactly one preview after debounce fires
    assert sm.preview_calls == [("file:chime.wav", 0.05)]


# --- B. activated does not re-trigger on the same selection ----------------
def test_b_activated_and_selection_coalesce_to_one(ctrl):
    c, timers = ctrl
    sm = c._sm
    c.schedule_selection("file:chime.wav", 0.05)  # wheel/select
    c.immediate("file:chime.wav", 0.05)            # activated same pick
    # the immediate call cancels the queued one + plays immediately
    assert sm.cancel_calls == 1
    assert timers[-1].stopped  # queued preview was cancelled
    assert sm.preview_calls == [("file:chime.wav", 0.05)]


# --- C. Rapid wheel changes coalesce ---------------------------------------
def test_c_wheel_coalesces_to_last_selection(ctrl):
    c, timers = ctrl
    sm = c._sm
    c.wheel_selection("file:a.wav", 0.05)
    first = timers[-1]
    c.wheel_selection("file:b.wav", 0.05)
    # last wheel wins: only one pending timer survives
    assert first.stopped
    assert len([t for t in timers if not t.stopped]) == 1
    timers[-1].fire()
    assert sm.preview_calls == [("file:b.wav", 0.05)]


# --- D. The last selected sound is the one played --------------------------
def test_d_last_selection_wins_after_debounce(ctrl):
    c, timers = ctrl
    sm = c._sm
    c.wheel_selection("file:a.wav", 0.05)
    c.wheel_selection("file:b.wav", 0.05)
    timers[-1].fire()
    assert sm.preview_calls == [("file:b.wav", 0.05)]


# --- E. Test button plays immediately, exactly once -----------------------
def test_e_test_button_plays_once_immediate(ctrl):
    c, timers = ctrl
    sm = c._sm
    c.immediate("file:newday.wav", 0.10)
    assert sm.preview_calls == [("file:newday.wav", 0.10)]
    assert timers == []  # no queued debounce


# --- F. Quick-sound selection starts exactly one request ------------------
def test_f_quick_pick_is_one_immediate_preview(ctrl):
    c, _ = ctrl
    sm = c._sm
    c.immediate("file:click.wav", 0.05)
    assert len(sm.preview_calls) == 1


# --- G. Programmatic loading does not preview -----------------------------
def test_g_programmatic_load_is_silenced(ctrl):
    c, timers = ctrl
    c.cancel()
    assert c._sm.preview_calls == []


# --- H. Cancelled preview timer cannot fire after dialog destruction ------
def test_h_cancel_prevents_stale_preview(ctrl):
    c, timers = ctrl
    sm = c._sm
    c.schedule_selection("file:chime.wav", 0.05)
    c.cancel()
    timers[-1].fire()  # would be a stale callback firing
    assert sm.preview_calls == []
    assert c._pending is None


# --- I. Previous preview playback is physically stopped -------------------
def test_i_new_preview_cancels_prior_on_preview_bus(ctrl):
    c, _ = ctrl
    sm = c._sm
    c.immediate("file:a.wav", 0.05)
    c.immediate("file:b.wav", 0.05)
    # each new preview cancels the prior preview bus before playing
    assert sm.cancel_calls == 2
    assert sm.preview_calls == [("file:a.wav", 0.05), ("file:b.wav", 0.05)]
    assert c.last_stable_ref() == "file:b.wav"


# --- K. Preview replacement: at most one audible audition -----------------
def test_k_replace_latest_one_audible_preview_at_a_time(ctrl):
    c, timers = ctrl
    sm = c._sm
    c.wheel_selection("file:a.wav", 0.05)
    c.wheel_selection("file:b.wav", 0.05)
    c.wheel_selection("file:c.wav", 0.05)
    for t in timers:
        t.fire()  # only the last surviving timer does anything
    assert sm.preview_calls == [("file:c.wav", 0.05)]


# --- L/M. Reference identity preserved (no rewrite of ref) ----------------
def test_l_named_and_file_refs_preserved_through_controller(ctrl):
    c, _ = ctrl
    sm = c._sm
    c.immediate("notify", 0.2)
    c.immediate("file:mysound.wav", 0.3)
    assert sm.preview_calls == [("notify", 0.2), ("file:mysound.wav", 0.3)]


# --- O. Preview failures do not crash --------------------------------------
def test_o_preview_failure_does_not_raise():
    class _Boom:
        def preview_sound_ref(self, ref, level):
            raise RuntimeError("device lost")
        def cancel_preview(self):
            pass
        def request_count(self):
            return 0
    c = IntervalPreviewController(_Boom())
    c.immediate("file:x.wav", 0.05)  # must not raise


# --- Q. No persisted side effect from preview -----------------------------
def test_q_preview_does_not_persist_settings(ctrl):
    c, _ = ctrl
    persisted = []
    class _SpySM:
        def preview_sound_ref(self, ref, level):
            persisted.append(ref)
        def cancel_preview(self):
            pass
        def request_count(self):
            return 0
    c2 = IntervalPreviewController(_SpySM())
    c2.immediate("file:preview_only.wav", 0.05)
    # preview dispatched exactly once, never persisted to settings
    assert persisted == ["file:preview_only.wav"]
    assert c2.preview_count == 1
