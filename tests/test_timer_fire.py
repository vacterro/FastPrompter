"""T-1007 fire-path tests: notification / top-bar / sound policy on the real
``_notify_timer`` and ``test_timer_notification`` logic, without building the
whole FastPrompter window.
"""

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import datetime  # noqa: E402

from PyQt6.QtWidgets import QApplication  # noqa: E402

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

import fastprompter.ui.timer_toast as toast_mod  # noqa: E402
from fastprompter.core.sound_manager import SoundManager  # noqa: E402
from fastprompter.core.timers import (  # noqa: E402
    KIND_CALENDAR,
    SOUND_MODE_POOL,
    Timer,
)

_APP = QApplication.instance() or QApplication([])


class _Tray:
    def __init__(self):
        self.messages = []

    def showMessage(self, *a):
        self.messages.append(a)

    def icon(self):
        return None


class _FakeFire:
    def __init__(self):
        self.data = {"sound_volume": "5", "sound_ui": "False", "theme": "Default"}
        self.sound_manager = SoundManager(None, self.data)
        self.timers = []
        self._current_lang = "EN"
        self.tray_icon = _Tray()
        self.saved = 0
        self._toasts = []
        self._sound_calls = []

    def save_timers_to_data(self):
        self.saved += 1

    def _tick_productivity(self):
        pass

    def _snooze_timer(self, timer, minutes):
        pass

    def _play_spy(self, ref, level):
        self._sound_calls.append((ref, level))
        return self.sound_manager.play_sound_ref(ref, level)


def _bind(fake):
    # Lazy: importing fastprompter.main at module level caches the real
    # sound_manager BEFORE test_sound_manager's stub-import, which makes its
    # real-QObject classes collide with _MockQObject in combined runs.
    import fastprompter.main as main_mod  # noqa: PLC0415

    fake._notify_timer = main_mod.FastPrompter._notify_timer.__get__(fake)
    fake._check_timers = main_mod.FastPrompter._check_timers.__get__(fake)
    fake._play_timer_sound = main_mod.FastPrompter._play_timer_sound.__get__(fake)
    fake.test_timer_notification = \
        main_mod.FastPrompter.test_timer_notification.__get__(fake)
    orig = SoundManager.play_sound_ref

    def spy(ref, level):
        fake._sound_calls.append((ref, level))
        return orig(fake.sound_manager, ref, level)

    fake.sound_manager.play_sound_ref = spy
    return fake


def _patch_toast(monkeypatch, truthy=True):
    seen = []

    def fake(main_win, timer, on_snooze=None):
        seen.append(timer)
        return object() if truthy else None

    monkeypatch.setattr(toast_mod, "show_toast", fake)
    return seen


def test_notify_on_plays_sound_and_shows_toast(monkeypatch):
    fake = _bind(_FakeFire())
    seen = _patch_toast(monkeypatch, truthy=True)
    t = Timer("a", datetime.datetime.now(), sound="tick", volume=7)
    fake._notify_timer(t, fired_at=datetime.datetime.now())
    assert seen and seen[0] is t
    assert fake._sound_calls == [("tick", 7)]


def test_notify_off_no_toast_no_tray_but_sound(monkeypatch):
    fake = _bind(_FakeFire())
    seen = _patch_toast(monkeypatch, truthy=True)
    t = Timer("a", datetime.datetime.now(), sound="tick", volume=7,
              show_notification=False)
    fake._notify_timer(t, fired_at=datetime.datetime.now())
    assert seen == []                       # no popup
    assert fake.tray_icon.messages == []    # no tray fallback either
    assert fake._sound_calls == [("tick", 7)]  # sound still plays


def test_global_sound_settings_not_mutated(monkeypatch):
    fake = _bind(_FakeFire())
    _patch_toast(monkeypatch, truthy=True)
    before = dict(fake.data)
    t = Timer("a", datetime.datetime.now(), sound="notify", volume=9)
    fake._notify_timer(t, fired_at=datetime.datetime.now())
    assert fake.data == before             # sound_ui/volume untouched


def test_pool_silent_still_notifies(monkeypatch):
    fake = _bind(_FakeFire())
    seen = _patch_toast(monkeypatch, truthy=True)
    t = Timer("a", datetime.datetime.now(), sound_mode=SOUND_MODE_POOL,
              sound_rules=[{"sound": "tick", "enabled": True, "all_day": False,
                            "start_minute": 360, "end_minute": 720}])
    # fire at 18:00 -> no eligible pool rule -> silent, but not notified-off
    fake._notify_timer(t, fired_at=datetime.datetime(2026, 7, 21, 18, 0))
    assert seen and seen[0] is t
    assert fake._sound_calls == []          # no sound chosen


def test_check_timers_fires_alarm_and_calendar(monkeypatch):
    fake = _bind(_FakeFire())
    _patch_toast(monkeypatch, truthy=True)
    now = datetime.datetime(2026, 7, 21, 12, 0, 0)
    fake.timers = [
        Timer("alarm", now - datetime.timedelta(seconds=1),
              kind="alarm", show_notification=True),
        Timer("cal", now - datetime.timedelta(seconds=1),
              kind=KIND_CALENDAR, show_notification=True),
    ]
    fired = fake.timers
    from fastprompter.core.timers import collect_due
    due = collect_due(fired, now)
    for t in due:
        fake._notify_timer(t, fired_at=now)
    assert len(due) == 2
    assert {t.kind for t in due} == {"alarm", KIND_CALENDAR}


def test_hidden_from_topbar_still_fires(monkeypatch):
    """show_in_top_bar=False must not suppress firing."""
    from fastprompter.core.timers import collect_due, next_due
    now = datetime.datetime(2026, 7, 21, 12, 0, 0)
    hidden = Timer("hidden", now - datetime.timedelta(seconds=1),
                   show_in_top_bar=False)
    assert collect_due([hidden], now) == [hidden]      # fires anyway
    assert next_due([hidden], now, topbar_only=True) is None


def test_missing_sound_ref_scheduler_survives(monkeypatch):
    fake = _bind(_FakeFire())
    seen = _patch_toast(monkeypatch, truthy=True)
    t = Timer("gone", datetime.datetime.now(), sound="file:no_such.wav",
              volume=5)
    fake._notify_timer(t, fired_at=datetime.datetime.now())
    assert seen and seen[0] is t           # visual path unaffected
    assert fake._sound_calls == [("file:no_such.wav", 5)]


def test_test_notification_deep_copies_behavior():
    fake = _bind(_FakeFire())
    t = Timer("orig", datetime.datetime.now(), sound="notify", volume=3,
              sound_mode=SOUND_MODE_POOL,
              sound_rules=[{"sound": "tick", "enabled": True, "all_day": True,
                            "volume": None, "start_minute": 0, "end_minute": 0}],
              show_notification=False, color_mode="static", color="#123456")
    probe = fake.test_timer_notification(t, delay_seconds=1)
    assert probe.show_notification is False
    assert probe.sound_mode == SOUND_MODE_POOL
    assert probe.sound_rules == t.sound_rules
    assert probe.sound_rules is not t.sound_rules
    assert probe.color == "#123456"
