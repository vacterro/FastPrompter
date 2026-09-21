"""Tests for AI limit notification customization and flood protection.

Validates:
1. Configurable duration (seconds to auto-close), symbol/emoji, and accent color.
2. Toast presentation with custom symbol, duration, and accent color.
3. Flood protection: single sound playback when multiple rules fire simultaneously.
4. Flood protection: single coalesced summary notification when multiple accounts breach quota.
"""

import os
import time
import unittest
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication, QLabel, QWidget

from fastprompter.core.usage_limits.model import (
    FIVE_HOUR,
    OK,
    WEEKLY,
    AccountRef,
    UsageSnapshot,
    UsageWindow,
)
from fastprompter.core.usage_limits.notifications import notification_key
from fastprompter.ui.timer_toast import show_toast

_APP = QApplication.instance() or QApplication([])


class _State:
    def __init__(self, accounts, snapshots):
        self.accounts = list(accounts)
        self.snapshots = dict(snapshots)
        self.status = "IDLE"


class _Service:
    def __init__(self, accounts, snapshots):
        self._state = _State(accounts, snapshots)

    @property
    def state_copy(self):
        return self._state

    def add_callback(self, cb):
        pass

    def refresh(self):
        pass


class _Gauges:
    class _Signal:
        @staticmethod
        def connect(_cb):
            pass

    _result_ready = _Signal()

    def sync(self):
        pass

    def refresh_view(self):
        pass


class _SoundRecorder:
    def __init__(self):
        self.played = []

    def play_sound_ref(self, ref, volume):
        self.played.append((ref, volume))
        return True

    def get_available_sounds(self):
        return ["newday.wav", "success_levelup.wav"]


class _FakeMainWin(QWidget):
    def __init__(self, accounts, snapshots):
        super().__init__()
        self.data = {
            "limit_notif_duration_sec": 10,
            "limit_notif_symbol": "⚡",
            "limit_notif_color": "#D9B340",
            "limit_notifications": {},
            "limit_notification_state": {},
        }
        self._theme_cache = {}
        self.limit_service = _Service(accounts, snapshots)
        self.limit_gauges = _Gauges()
        self.sound_manager = _SoundRecorder()
        self.shown_popups = []

    def mark_dirty(self, domain=None):
        pass

    def _show_limit_popup(self, title, message, duration_sec=None, color=None, symbol=None):
        self.shown_popups.append({
            "title": title,
            "message": message,
            "duration_sec": duration_sec,
            "color": color,
            "symbol": symbol,
        })


def _make_account(stable, name):
    return AccountRef(
        provider_id="codex",
        stable_id=stable,
        display_name=name,
        source_kind="test",
        source_path=f"X:/{stable}",
    )


class TestToastCustomization(unittest.TestCase):
    def test_toast_accepts_custom_duration_color_and_symbol(self):
        timer = SimpleNamespace(
            name="Test Quota Alert",
            description="5% remaining",
            display_color=lambda: "#E69500",
        )
        toast = show_toast(
            None,
            timer,
            header="FastPrompter Test",
            status="Critical",
            duration_ms=5000,
            accent_color="#C0392B",
            symbol="⚠️",
        )
        try:
            assert toast is not None
            assert toast._auto.isActive()
            assert toast._auto.interval() == 5000

            title_lbl = toast.findChild(QLabel, "TitleLbl")
            assert title_lbl is not None
            assert "⚠️" in title_lbl.text()
            assert "Test Quota Alert" in title_lbl.text()
        finally:
            if toast:
                toast.close()
                toast.deleteLater()
            _APP.processEvents()

    def test_toast_zero_duration_stays_until_dismissed(self):
        timer = SimpleNamespace(
            name="Persistent Alert",
            description="Until dismissed",
        )
        toast = show_toast(
            None,
            timer,
            duration_ms=0,
        )
        try:
            assert toast is not None
            # When duration_ms <= 0, timer is not started so it won't auto close
            assert not toast._auto.isActive()
        finally:
            if toast:
                toast.close()
                toast.deleteLater()
            _APP.processEvents()


class TestLimitSettingsDialogAppearanceControls(unittest.TestCase):
    def setUp(self):
        now = time.time()
        self.acc1 = _make_account("a1", "Claude")
        self.acc2 = _make_account("a2", "Codex")
        snapshots = {
            self.acc1.key: UsageSnapshot(self.acc1, OK, [
                UsageWindow(FIVE_HOUR, 300, True, 10, 90, now + 900),
                UsageWindow(WEEKLY, 10080, True, 20, 80, now + 86400),
            ]),
            self.acc2.key: UsageSnapshot(self.acc2, OK, [
                UsageWindow(FIVE_HOUR, 300, True, 5, 95, now + 900),
                UsageWindow(WEEKLY, 10080, True, 15, 85, now + 86400),
            ]),
        }
        self.win = _FakeMainWin([self.acc1, self.acc2], snapshots)
        from fastprompter.ui.limit_settings_dialog import LimitSettingsDialog
        self.dialog = LimitSettingsDialog(self.win)

    def tearDown(self):
        self.dialog.close()
        self.dialog.deleteLater()
        self.win.deleteLater()
        _APP.processEvents()

    def test_appearance_controls_rendered(self):
        assert hasattr(self.dialog, "cmb_notif_duration")
        assert hasattr(self.dialog, "cmb_notif_symbol")
        assert hasattr(self.dialog, "cmb_notif_color")
        assert hasattr(self.dialog, "btn_test_notif")

    def test_duration_change_persists_to_data(self):
        # Change duration to 30s
        idx = self.dialog.cmb_notif_duration.findData(30)
        assert idx >= 0
        self.dialog.cmb_notif_duration.setCurrentIndex(idx)
        assert self.win.data["limit_notif_duration_sec"] == 30

    def test_symbol_change_persists_to_data(self):
        # Change symbol to Siren
        self.dialog.cmb_notif_symbol.setEditText("🚨")
        assert self.win.data["limit_notif_symbol"] == "🚨"

    def test_color_change_persists_to_data(self):
        # Change color to Crimson Red
        idx = self.dialog.cmb_notif_color.findData("#C0392B")
        assert idx >= 0
        self.dialog.cmb_notif_color.setCurrentIndex(idx)
        assert self.win.data["limit_notif_color"] == "#C0392B"

    def test_test_popup_invokes_show_limit_popup_with_custom_settings(self):
        self.dialog.cmb_notif_symbol.setEditText("★")
        idx_dur = self.dialog.cmb_notif_duration.findData(15)
        self.dialog.cmb_notif_duration.setCurrentIndex(idx_dur)
        idx_col = self.dialog.cmb_notif_color.findData("#27AE60")
        self.dialog.cmb_notif_color.setCurrentIndex(idx_col)

        self.dialog._test_notification_appearance()
        assert len(self.win.shown_popups) == 1
        pop = self.win.shown_popups[0]
        assert pop["symbol"] == "★"
        assert pop["duration_sec"] == 15
        assert pop["color"] == "#27AE60"


class TestFloodProtection(unittest.TestCase):
    def test_single_sound_and_coalesced_toast_when_multiple_alerts_fire(self):
        from fastprompter.main import FastPrompter

        now = time.time()
        acc1 = _make_account("a1", "Claude")
        acc2 = _make_account("a2", "Codex")
        acc3 = _make_account("a3", "Antigravity")
        accounts = [acc1, acc2, acc3]

        snapshots = {
            acc1.key: UsageSnapshot(acc1, OK, [
                UsageWindow(FIVE_HOUR, 300, True, 90, 10, now + 900),
            ]),
            acc2.key: UsageSnapshot(acc2, OK, [
                UsageWindow(FIVE_HOUR, 300, True, 95, 5, now + 900),
            ]),
            acc3.key: UsageSnapshot(acc3, OK, [
                UsageWindow(FIVE_HOUR, 300, True, 92, 8, now + 900),
            ]),
        }

        # Mock window mimicking main.py environment
        win = _FakeMainWin(accounts, snapshots)
        win._limit_notifications_initialized = False
        win.sound_manager = _SoundRecorder()

        # Configure all 3 accounts with active alert rules and sound
        for acc in accounts:
            key = notification_key(acc.key, FIVE_HOUR)
            win.data["limit_notifications"][key] = {
                "enabled": "True",
                "threshold": 20.0,
                "sound_enabled": "True",
                "sound": "file:newday.wav",
                "volume": 0.5,
                "show_notification": "True",
            }

        # Run real FastPrompter._check_limit_notifications
        FastPrompter._check_limit_notifications(win)

        # Flood protection 1: sound should play at most ONCE, not 3 times
        assert len(win.sound_manager.played) == 1

        # Flood protection 2: notifications must be coalesced into ONE combined popup, not 3 popups
        assert len(win.shown_popups) == 1
        summary_pop = win.shown_popups[0]
        assert "3 quota alerts" in summary_pop["title"]
        assert "Claude" in summary_pop["message"]
        assert "Codex" in summary_pop["message"]
        assert "Antigravity" in summary_pop["message"]

    def test_single_alert_shows_individual_popup(self):
        from fastprompter.main import FastPrompter

        now = time.time()
        acc1 = _make_account("a1", "Claude")
        accounts = [acc1]
        snapshots = {
            acc1.key: UsageSnapshot(acc1, OK, [
                UsageWindow(FIVE_HOUR, 300, True, 90, 10, now + 900),
            ]),
        }
        win = _FakeMainWin(accounts, snapshots)
        win._limit_notifications_initialized = False
        key = notification_key(acc1.key, FIVE_HOUR)
        win.data["limit_notifications"][key] = {
            "enabled": "True",
            "threshold": 20.0,
            "sound_enabled": "True",
            "sound": "file:newday.wav",
            "volume": 0.5,
            "show_notification": "True",
        }

        FastPrompter._check_limit_notifications(win)
        assert len(win.sound_manager.played) == 1
        assert len(win.shown_popups) == 1
        pop = win.shown_popups[0]
        assert "AI limit: Claude" in pop["title"]
        assert "10.0% remaining" in pop["message"]

    def test_show_limit_popup_reads_profile_defaults(self):
        from fastprompter.main import FastPrompter

        toasts_created = []

        def fake_show_toast(win, obj, **kwargs):
            toasts_created.append((obj, kwargs))
            return SimpleNamespace()

        import fastprompter.ui.timer_toast as tt
        orig_show = tt.show_toast
        tt.show_toast = fake_show_toast
        try:
            win = _FakeMainWin([], {})
            win.data["limit_notif_duration_sec"] = 25
            win.data["limit_notif_color"] = "#E69500"
            win.data["limit_notif_symbol"] = "🔔"

            FastPrompter._show_limit_popup(win, "Alert Title", "Alert Body")

            assert len(toasts_created) == 1
            obj, kwargs = toasts_created[0]
            assert obj.name == "Alert Title"
            assert obj.description == "Alert Body"
            assert kwargs["duration_ms"] == 25000
            assert kwargs["accent_color"] == "#E69500"
            assert kwargs["symbol"] == "🔔"
        finally:
            tt.show_toast = orig_show


class TestToastClickableDuringModalDialog(unittest.TestCase):
    def test_toast_clickable_when_limit_settings_dialog_open(self):
        from PyQt6.QtCore import Qt
        from PyQt6.QtTest import QTest
        from PyQt6.QtWidgets import QPushButton

        from fastprompter.core.usage_limits.model import AccountRef
        from fastprompter.ui.limit_settings_dialog import LimitSettingsDialog
        from fastprompter.ui.timer_toast import show_toast

        win = _FakeMainWin([], {})
        dialog = LimitSettingsDialog(win)
        try:
            assert dialog.windowModality() == Qt.WindowModality.WindowModal

            acc = AccountRef("claude", "test_acc", "Test Acc", "auto_default")
            dismissed = []
            toast = show_toast(win, acc, on_dismiss=lambda _t: dismissed.append(True),
                               header="Test Header", status="Test Status")
            assert toast is not None
            assert toast.windowModality() == Qt.WindowModality.NonModal

            # Toast should be visible and clickable
            btn_dismiss = [b for b in toast.findChildren(QPushButton) if "Dismiss" in b.text()][0]
            QTest.mouseClick(btn_dismiss, Qt.MouseButton.LeftButton)
            assert len(dismissed) == 1
            assert not toast.isVisible()
        finally:
            dialog.close()

    def test_toast_clickable_when_generic_modal_dialog_open(self):
        from PyQt6.QtCore import Qt
        from PyQt6.QtTest import QTest
        from PyQt6.QtWidgets import QDialog

        from fastprompter.core.usage_limits.model import AccountRef
        from fastprompter.ui.timer_toast import show_toast

        win = _FakeMainWin([], {})
        dlg = QDialog(win)
        dlg.setWindowModality(Qt.WindowModality.ApplicationModal)
        dlg.show()
        try:
            acc = AccountRef("codex", "test_codex", "Codex", "auto_default")
            toast = show_toast(win, acc, header="Alert", status="Active")
            assert toast is not None
            # Click background of toast -> closes it via mousePressEvent
            QTest.mouseClick(toast, Qt.MouseButton.LeftButton)
            assert not toast.isVisible()
        finally:
            dlg.close()


