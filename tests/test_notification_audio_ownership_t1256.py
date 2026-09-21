"""T-1256: real toast presentation must respect the domain's audio owner."""

from __future__ import annotations

import datetime
import os
import time
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication, QWidget  # noqa: E402

from fastprompter.core.audio_hub import (  # noqa: E402
    AudioHub,
    FakeMultiChannelTransport,
)
from fastprompter.core.pomodoro import PHASE_WORK  # noqa: E402
from fastprompter.core.sound_manager import SoundManager  # noqa: E402
from fastprompter.core.timers import SOUND_MODE_POOL, Timer  # noqa: E402
from fastprompter.core.usage_limits.model import (  # noqa: E402
    FIVE_HOUR,
    AccountRef,
    UsageWindow,
)
from fastprompter.core.usage_limits.notifications import (  # noqa: E402
    LimitAlert,
    normalized_rule,
)
from fastprompter.main import FastPrompter  # noqa: E402
from fastprompter.ui.limit_settings_dialog import LimitSettingsDialog  # noqa: E402
from fastprompter.ui.timer_toast import TimerToast, show_simple_toast  # noqa: E402


class _Sound:
    def __init__(self):
        self.requests = []
        self.result = True

    def play_sound_ref(self, ref, volume):
        self.requests.append(("domain", ref, volume))
        return self.result

    def preview_sound_ref(self, ref, volume):
        self.requests.append(("preview", ref, volume))
        return self.result

    def play_appearance(self, event):
        self.requests.append(("appearance", event))
        return self.result


class _Window(QWidget):
    _check_limit_notifications = FastPrompter._check_limit_notifications
    _show_limit_popup = FastPrompter._show_limit_popup
    _show_in_app_toast = FastPrompter._show_in_app_toast
    _notify_timer = FastPrompter._notify_timer
    _play_timer_sound = FastPrompter._play_timer_sound
    _notify_productivity = FastPrompter._notify_productivity
    _fire_interval_notif = FastPrompter._fire_interval_notif

    def __init__(self):
        super().__init__()
        self.data = {"limit_notifications": {}, "limit_notification_state": {}}
        self._theme_cache = {}
        self._current_lang = "EN"
        self._limit_notifications_initialized = True
        self.limit_service = SimpleNamespace(state_copy=SimpleNamespace(
            accounts=[], snapshots={}))
        self.sound_manager = _Sound()
        self.timers = []
        self._missed_timer_ids = set()

    def mark_dirty(self, *_args):
        pass


@pytest.fixture
def window():
    app = QApplication.instance() or QApplication([])
    host = _Window()
    before = {id(toast) for toast in TimerToast._open}
    yield host
    for toast in list(TimerToast._open):
        if id(toast) not in before:
            toast.close()
            toast.deleteLater()
    host.deleteLater()
    app.processEvents()


def _new_toasts(before):
    return [toast for toast in TimerToast._open if id(toast) not in before]


def _assert_one_toast(window, action):
    before = {id(toast) for toast in TimerToast._open}
    action()
    toasts = _new_toasts(before)
    assert len(toasts) == 1, "the real toast path must present exactly once"
    assert toasts[0].isVisible()
    toasts[0].close()
    return toasts[0]


def test_ai_limit_low_changed_disabled_reset_and_test_keep_one_owner(
        window, monkeypatch, caplog):
    from fastprompter.core.usage_limits import notifications

    account = AccountRef("codex", "account", "Codex", "test", "X:/account")
    quota = UsageWindow(FIVE_HOUR, 300, True, 90, 10, time.time() + 900)
    key = f"{account.key}|{FIVE_HOUR}"

    def fire(kind, rule):
        alert = LimitAlert(kind, key, account, quota, normalized_rule(rule))
        monkeypatch.setattr(
            notifications, "evaluate_limit_notifications",
            lambda *_args, **_kwargs: ([alert], {}),
        )
        _assert_one_toast(window, window._check_limit_notifications)

    rule = {"enabled": "True", "sound_enabled": "True",
            "show_notification": "True", "sound": "file:QUEST.wav",
            "volume": 0.4}
    fire("low", rule)
    assert window.sound_manager.requests == [("domain", "file:QUEST.wav", 0.4)]

    window.sound_manager.requests.clear()
    rule["sound"] = "file:NEWDAY.wav"
    fire("low", rule)
    assert window.sound_manager.requests == [("domain", "file:NEWDAY.wav", 0.4)]

    window.sound_manager.requests.clear()
    rule["sound_enabled"] = "False"
    fire("low", rule)
    assert window.sound_manager.requests == []

    window.sound_manager.requests.clear()
    rule.update({"reset_enabled": "True", "reset_sound_enabled": "True",
                 "reset_sound": "file:success_levelup.wav",
                 "reset_volume": 0.7, "reset_show_notification": "True"})
    fire("reset", rule)
    assert window.sound_manager.requests == [
        ("domain", "file:success_levelup.wav", 0.7)]

    window.sound_manager.requests.clear()
    rule["sound_enabled"] = "True"
    dialog = SimpleNamespace(main_win=window, _rules=lambda: {key: rule})
    _assert_one_toast(
        window, lambda: LimitSettingsDialog._test_rule(dialog, key))
    assert window.sound_manager.requests == [
        ("preview", "file:NEWDAY.wav", 0.4)]

    # A missing WAV or transport refusal never licenses a generic fallback.
    window.sound_manager.requests.clear()
    window.sound_manager.result = False
    fire("low", rule)
    assert window.sound_manager.requests == [("domain", "file:NEWDAY.wav", 0.4)]
    assert "ai_limit_audio domain=low" in caplog.text
    assert f"rule_key={key}" in caplog.text
    assert "stored_ref='file:NEWDAY.wav'" in caplog.text
    assert "resolved_ref='NEWDAY.wav'" in caplog.text
    assert "playback_outcome=NOT_STARTED" in caplog.text


def test_timer_productivity_interval_and_explicit_silence_stay_silent(window):
    timer = Timer("alarm", datetime.datetime.now(), sound="file:QUEST.wav",
                  volume=0.6)
    _assert_one_toast(window, lambda: window._notify_timer(timer))
    assert window.sound_manager.requests == [("domain", "file:QUEST.wav", 0.6)]

    window.sound_manager.requests.clear()
    silent_timer = Timer("silent", datetime.datetime.now(),
                         sound_mode=SOUND_MODE_POOL, sound_rules=[])
    _assert_one_toast(window, lambda: window._notify_timer(silent_timer))
    assert window.sound_manager.requests == []

    window.productivity_timer = SimpleNamespace(
        sound_enabled=True, work_sound="file:QUEST.wav", volume=0.2,
        describe=lambda: "work done",
    )
    _assert_one_toast(window, lambda: window._notify_productivity(PHASE_WORK))
    assert window.sound_manager.requests == [("domain", "file:QUEST.wav", 0.2)]

    window.sound_manager.requests.clear()
    window.productivity_timer.sound_enabled = False
    _assert_one_toast(window, lambda: window._notify_productivity(PHASE_WORK))
    assert window.sound_manager.requests == []

    rule = {"name": "Hourly", "sound": "file:NEWDAY.wav", "volume": 0.5,
            "show_notification": True}
    _assert_one_toast(window, lambda: window._fire_interval_notif(rule))
    assert window.sound_manager.requests == [("domain", "file:NEWDAY.wav", 0.5)]


def test_generic_toast_needs_explicit_appearance_audio_opt_in(window):
    _assert_one_toast(window, lambda: show_simple_toast(window, "Generic", "silent"))
    assert window.sound_manager.requests == []
    _assert_one_toast(
        window, lambda: show_simple_toast(
            window, "Generic", "audible", appearance_audio=True))
    assert window.sound_manager.requests == [("appearance", "notification_show")]


def test_generic_opt_in_remap_master_mute_and_stop_all(window, tmp_path,
                                                        monkeypatch):
    monkeypatch.setattr("fastprompter.utils.paths.get_data_dir",
                        lambda: str(tmp_path))
    monkeypatch.setattr("fastprompter.core.sound_library.managed_root",
                        lambda: str(tmp_path / "sound_library"))
    data = {"sound_ui": "True", "sound_events": {
        "notification_show": {"file": "blip01.wav", "enabled": "True"},
    }}
    manager = SoundManager(window, data)
    transport = FakeMultiChannelTransport()
    manager._hub = AudioHub(transport=transport)
    window.sound_manager = manager

    _assert_one_toast(window, lambda: show_simple_toast(
        window, "Generic", "remapped", appearance_audio=True))
    assert len(transport.channels) == 1
    assert os.path.basename(next(iter(transport.channels.values()))["path"]) == "blip01.wav"

    manager.stop_all_sound()
    assert transport.channels == {}
    assert manager.master_muted() is False

    # A fresh appearance while muted must not restore the stopped sound.
    manager._appearance_last_emit["notification_show"] -= 10.0
    manager.set_master_muted(True)
    _assert_one_toast(window, lambda: show_simple_toast(
        window, "Generic", "muted", appearance_audio=True))
    assert transport.channels == {}
