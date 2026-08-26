"""CORE-001 regression: productivity alarm replay + acknowledge lifecycle.

Exercises the real ``_tick_productivity`` / ``_notify_productivity`` /
``_replay_productivity_alarm`` scheduler on a fake window so we can drive
``time.monotonic`` and spy on sound + tray calls without building the UI.
"""

import os
import sys
import time as _time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QObject  # noqa: E402

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

import fastprompter.main as main_mod  # noqa: E402
from fastprompter.core.pomodoro import (  # noqa: E402
    PHASE_WORK,
    ProductivityTimer,
)


class _Tray(QObject):
    def __init__(self):
        super().__init__()
        self.messages = []

    def showMessage(self, *a):
        self.messages.append(a)

    def icon(self):
        return None


class _FakeWin:
    def __init__(self, **kw):
        self.data = {}
        self._current_lang = "EN"
        self.tray_icon = _Tray()
        self.productivity_timer = ProductivityTimer(**kw)
        self._sound_calls = []
        self.saved = 0
        self._pomo_last_tick = None
        self._pomo_alarm_replay_at = None
        self._POMO_ALARM_REPEAT_SECONDS = 1

        class _SM:
            def play_sound_ref(self, ref, vol):
                self.calls.append((ref, vol))
                return True

        sm = _SM()
        sm.calls = self._sound_calls
        self.sound_manager = sm

    def save_productivity_timer(self):
        self.saved += 1


def _bind(fake):
    fake._tick_productivity = main_mod.FastPrompter._tick_productivity.__get__(fake)
    fake._notify_productivity = main_mod.FastPrompter._notify_productivity.__get__(fake)
    fake._replay_productivity_alarm = \
        main_mod.FastPrompter._replay_productivity_alarm.__get__(fake)
    return fake


def _advance(monkeypatch, clock, seconds):
    clock[0] += seconds
    monkeypatch.setattr(_time, "monotonic", lambda: clock[0])


def _make(monkeypatch, clock, **kw):
    kw.setdefault("work_seconds", 2)
    kw.setdefault("break_seconds", 2)
    fake = _bind(_FakeWin(**kw))
    monkeypatch.setattr(_time, "monotonic", lambda: clock[0])
    return fake


def test_phase_end_once_notifies(monkeypatch):
    clock = [1000.0]
    fake = _make(monkeypatch, clock, work_seconds=2, repeat_alarm=True)
    fake.productivity_timer.start()
    fake._tick_productivity()          # baseline tick (last is None)
    _advance(monkeypatch, clock, 2.0)  # work phase elapses
    fake._tick_productivity()
    assert len(fake._sound_calls) == 1
    assert len(fake.tray_icon.messages) == 1


def test_replay_cadence_sound_only(monkeypatch):
    clock = [1000.0]
    fake = _make(monkeypatch, clock, work_seconds=2, repeat_alarm=True)
    fake.productivity_timer.start()
    fake._tick_productivity()
    _advance(monkeypatch, clock, 2.0)
    fake._tick_productivity()          # phase end -> 1 notify
    tray_after_end = len(fake.tray_icon.messages)
    _advance(monkeypatch, clock, 1.0)  # one repeat interval
    fake._tick_productivity()          # replay (sound only)
    assert len(fake._sound_calls) == 2
    assert len(fake.tray_icon.messages) == tray_after_end  # no new popup


def test_acknowledge_stops_replay(monkeypatch):
    clock = [1000.0]
    fake = _make(monkeypatch, clock, work_seconds=2, repeat_alarm=True)
    fake.productivity_timer.start()
    fake._tick_productivity()
    _advance(monkeypatch, clock, 2.0)
    fake._tick_productivity()
    assert fake.productivity_timer.alarm_pending
    fake.productivity_timer.acknowledge()
    assert not fake.productivity_timer.alarm_pending
    _advance(monkeypatch, clock, 1.0)
    fake._tick_productivity()
    assert len(fake._sound_calls) == 1  # no replay after ack


def test_repeat_false_is_oneshot(monkeypatch):
    clock = [1000.0]
    fake = _make(monkeypatch, clock, work_seconds=2, repeat_alarm=False)
    fake.productivity_timer.start()
    fake._tick_productivity()
    _advance(monkeypatch, clock, 2.0)
    fake._tick_productivity()
    assert len(fake._sound_calls) == 1
    _advance(monkeypatch, clock, 1.0)
    fake._tick_productivity()
    assert len(fake._sound_calls) == 1  # no replay, repeat off


def test_sound_disabled_never_rings(monkeypatch):
    clock = [1000.0]
    fake = _make(monkeypatch, clock, work_seconds=2, repeat_alarm=True,
                 sound_enabled=False)
    fake.productivity_timer.start()
    fake._tick_productivity()
    _advance(monkeypatch, clock, 2.0)
    fake._tick_productivity()
    assert len(fake._sound_calls) == 0
    assert fake.productivity_timer.alarm_pending
    _advance(monkeypatch, clock, 1.0)
    fake._tick_productivity()
    assert len(fake._sound_calls) == 0  # replay gated on sound_enabled


def test_work_alarm_keeps_work_sound_in_break(monkeypatch):
    clock = [1000.0]
    fake = _make(monkeypatch, clock, work_seconds=2, break_seconds=50,
                 work_sound="file:WORK.wav", break_sound="file:BREAK.wav",
                 repeat_alarm=True)
    fake.productivity_timer.start()
    fake._tick_productivity()
    _advance(monkeypatch, clock, 2.0)
    fake._tick_productivity()          # work ends, break starts counting
    assert fake.productivity_timer.alarm_phase == PHASE_WORK
    _advance(monkeypatch, clock, 1.0)
    fake._tick_productivity()          # replay
    refs = [c[0] for c in fake._sound_calls]
    assert refs[0] == "file:WORK.wav"  # initial
    assert refs[1] == "file:WORK.wav"  # replay keeps work sound


def test_disabling_sound_silences_pending(monkeypatch):
    clock = [1000.0]
    fake = _make(monkeypatch, clock, work_seconds=2, repeat_alarm=True)
    fake.productivity_timer.start()
    fake._tick_productivity()
    _advance(monkeypatch, clock, 2.0)
    fake._tick_productivity()
    assert fake.productivity_timer.alarm_pending
    # simulate turning the sound off while the alarm is still pending
    fake.productivity_timer.sound_enabled = False
    fake.productivity_timer.acknowledge()
    assert not fake.productivity_timer.alarm_pending
    _advance(monkeypatch, clock, 1.0)
    fake._tick_productivity()
    assert len(fake._sound_calls) == 1  # only the initial, no replay
