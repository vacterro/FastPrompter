"""T-1228: one logical notification = one app-owned audible sound.

The audible half of a notification is owned solely by SoundManager; the
visual half is the app's own in-app toast and must never call an OS
notification API (whose sound cannot be silenced and can race the WAV).
"""

import datetime
import os
import sys
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

from PyQt6.QtWidgets import QApplication  # noqa: E402

import fastprompter.main as main_mod  # noqa: E402
import fastprompter.ui.timer_toast as tt  # noqa: E402
from fastprompter.core.pomodoro import PHASE_WORK  # noqa: E402
from fastprompter.core.timers import Timer  # noqa: E402


class _Sound:
    def __init__(self):
        self.calls = []
        self.appearance_calls = []

    def play_sound_ref(self, ref, vol):
        self.calls.append((ref, vol))
        return True

    def play_appearance(self, event):
        self.appearance_calls.append(event)
        return True


class _Tray:
    def __init__(self):
        self.messages = []

    def showMessage(self, *a):
        self.messages.append(a)

    def icon(self):
        return None


class _Win:
    def __init__(self):
        self.data = {}
        self._current_lang = "EN"
        self.sound_manager = _Sound()
        self.tray_icon = _Tray()
        self._status = []
        self.timers = []
        self._missed_timer_ids = set()

    def statusBar(self):
        outer = self

        class _Status:
            def showMessage(self, msg, ms=0):
                outer._status.append(msg)

        return _Status()

    def _persist_missed_ids(self):
        pass

    def _ack_missed(self, timer):
        pass


def _bind(fake):
    for name in (
        "_fire_interval_notif",
        "_notify_productivity",
        "_show_in_app_toast",
        "_show_limit_popup",
        "_notify_timer",
    ):
        setattr(fake, name, getattr(main_mod.FastPrompter, name).__get__(fake))
    return fake


def _spy_simple(monkeypatch):
    seen = []
    monkeypatch.setattr(
        tt, "show_simple_toast",
        lambda *a, **k: seen.append((a, k)) or object())
    return seen


def _spy_toast(monkeypatch, result):
    seen = []
    monkeypatch.setattr(
        tt, "show_toast",
        lambda *a, **k: seen.append((a, k)) or result)
    return seen


def test_interval_visual_is_silent_in_app_toast(monkeypatch):
    fake = _bind(_Win())
    seen = _spy_simple(monkeypatch)
    rule = {"id": "r", "name": "Morning", "sound": "file:NEWDAY.wav",
            "volume": 0.5, "show_notification": True}
    fake._fire_interval_notif(rule)
    assert fake.sound_manager.calls == [("file:NEWDAY.wav", 0.5)]
    assert len(seen) == 1, "interval visual must be an in-app toast"
    assert fake.tray_icon.messages == [], "interval must not use OS tray audio"


def test_interval_requests_only_configured_sound(monkeypatch):
    fake = _bind(_Win())
    _spy_simple(monkeypatch)
    rule = {"id": "r", "name": "Hourly", "sound": "file:NEWDAY.wav",
            "volume": 0.5, "show_notification": True}
    fake._fire_interval_notif(rule)
    refs = [c[0] for c in fake.sound_manager.calls]
    assert refs == ["file:NEWDAY.wav"], refs
    assert not any(r in ("click", "copy", "select_all", "pop.wav")
                   for r in refs)


def test_productivity_visual_is_silent_in_app_toast(monkeypatch):
    fake = _bind(_Win())
    fake.productivity_timer = SimpleNamespace(
        sound_enabled=True, work_sound="file:QUEST.wav", volume=0.05,
        describe=lambda: "work done")
    seen = _spy_simple(monkeypatch)
    fake._notify_productivity(PHASE_WORK)
    assert fake.sound_manager.calls == [("file:QUEST.wav", 0.05)]
    assert len(seen) == 1
    assert fake.tray_icon.messages == []


def test_timer_uses_toast_and_never_tray(monkeypatch):
    fake = _bind(_Win())
    fake._play_timer_sound = lambda timer, fired_at=None: True
    seen = _spy_toast(monkeypatch, object())
    t = Timer("a", datetime.datetime.now(), sound="tick", volume=0.7)
    fake._notify_timer(t, fired_at=datetime.datetime.now())
    assert len(seen) == 1
    assert fake.tray_icon.messages == []


def test_timer_real_toast_keeps_one_audible_owner():
    app = QApplication.instance() or QApplication([])
    fake = _bind(_Win())
    fake._play_timer_sound = lambda _timer, fired_at=None: (
        fake.sound_manager.play_sound_ref("file:QUEST.wav", 0.4))
    before = {id(toast) for toast in tt.TimerToast._open}
    timer = Timer("a", datetime.datetime.now(), sound="file:QUEST.wav")
    try:
        fake._notify_timer(timer, fired_at=datetime.datetime.now())
        shown = [toast for toast in tt.TimerToast._open if id(toast) not in before]
        assert len(shown) == 1
        assert shown[0].isVisible()
        assert fake.sound_manager.calls == [("file:QUEST.wav", 0.4)]
        assert fake.sound_manager.appearance_calls == []
    finally:
        for toast in list(tt.TimerToast._open):
            if id(toast) not in before:
                toast.close()
                toast.deleteLater()
        app.processEvents()


def test_timer_fallback_is_silent_status_not_tray(monkeypatch):
    fake = _bind(_Win())
    fake._play_timer_sound = lambda timer, fired_at=None: True
    _spy_toast(monkeypatch, None)
    t = Timer("a", datetime.datetime.now(), sound="tick")
    fake._notify_timer(t, fired_at=datetime.datetime.now())
    assert fake.tray_icon.messages == [], "no OS-audible timer fallback"
    assert fake._status, "silent status-bar fallback expected"


def test_limit_popup_prefers_silent_toast(monkeypatch):
    fake = _bind(_Win())
    seen = _spy_toast(monkeypatch, object())
    fake._show_limit_popup("Limit", "Reached")
    assert len(seen) == 1
    assert fake.tray_icon.messages == []


def test_limit_popup_fallback_is_silent_status_not_tray(monkeypatch):
    fake = _bind(_Win())
    _spy_toast(monkeypatch, None)
    fake._show_limit_popup("Limit", "Reached")
    assert fake.tray_icon.messages == [], "no OS-audible limit fallback"
    assert fake._status, "silent status-bar fallback expected"
