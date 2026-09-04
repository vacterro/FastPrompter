"""Copying one alert section's settings onto the others."""

import os
import time
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication, QWidget

from fastprompter.core.usage_limits.model import (
    FIVE_HOUR,
    OK,
    WEEKLY,
    AccountRef,
    UsageSnapshot,
    UsageWindow,
)
from fastprompter.core.usage_limits.notifications import notification_key

_APP = QApplication.instance() or QApplication([])


class _State:
    def __init__(self, accounts, snapshots):
        self.accounts = list(accounts)
        self.snapshots = dict(snapshots)
        self.status = "IDLE"


class _Service:
    def __init__(self, accounts, snapshots):
        self._state = _State(accounts, snapshots)
        self.refresh_count = 0

    @property
    def state_copy(self):
        return self._state

    def add_callback(self, cb):
        pass

    def refresh(self):
        self.refresh_count += 1

    def discover(self):
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


class _Sounds:
    def play_sound_ref(self, ref, volume):
        return True

    def get_available_sounds(self):
        return ["newday.wav", "success_levelup.wav"]


class _MainWin(QWidget):
    def __init__(self, accounts, snapshots):
        super().__init__()
        self.data = {}
        self._theme_cache = {}
        self.limit_service = _Service(accounts, snapshots)
        self.limit_gauges = _Gauges()
        self.sound_manager = _Sounds()
        self.checked = 0

    def mark_dirty(self, domain=None):
        pass

    def _check_limit_notifications(self):
        self.checked += 1


def _account(stable, name):
    return AccountRef(provider_id="codex", stable_id=stable,
                      display_name=name, source_kind="test",
                      source_path=f"X:/{stable}")


class TestCopyAlertSettings(unittest.TestCase):
    def setUp(self):
        now = time.time()
        self.first = _account("c1", "Codex 1")
        self.second = _account("c2", "Codex 2")
        snapshots = {
            a.key: UsageSnapshot(a, OK, [
                UsageWindow(FIVE_HOUR, 300, True, 40, 60, now + 900),
                UsageWindow(WEEKLY, 10080, True, 50, 50, now + 86400),
            ]) for a in (self.first, self.second)
        }
        self.win = _MainWin([self.first, self.second], snapshots)
        from fastprompter.ui.limit_settings_dialog import LimitSettingsDialog
        self.dialog = LimitSettingsDialog(self.win)

    def tearDown(self):
        self.dialog.close()
        self.dialog.deleteLater()
        self.win.deleteLater()
        _APP.processEvents()

    def _key(self, account, window_key):
        return notification_key(account.key, window_key)

    def test_every_rendered_section_is_offered_as_a_source(self):
        labels = [self.dialog.cmb_copy_from.itemText(i)
                  for i in range(self.dialog.cmb_copy_from.count())]
        keys = [self.dialog.cmb_copy_from.itemData(i)
                for i in range(self.dialog.cmb_copy_from.count())]
        assert len(labels) == 4          # two accounts x two windows
        assert keys[0] == self._key(self.first, FIVE_HOUR)
        assert "Codex 1" in labels[0] and "5 hours" in labels[0]
        assert self.dialog.btn_copy_to_all.isEnabled()

    def test_apply_to_all_copies_every_field_exactly(self):
        source = self._key(self.first, FIVE_HOUR)
        self.dialog._set_rule(source, "enabled", True)
        self.dialog._set_rule(source, "threshold", 42.5)
        self.dialog._set_rule(source, "sound", "file:newday.wav")
        self.dialog._set_rule(source, "volume", 0.31)
        self.dialog._set_rule(source, "show_notification", False)
        self.dialog._set_rule(source, "reset_enabled", True)
        self.dialog._set_rule(source, "reset_sound", "file:success_levelup.wav")
        self.dialog._set_rule(source, "reset_volume", 0.77)
        self.dialog._set_rule(source, "reset_show_notification", False)

        index = self.dialog.cmb_copy_from.findData(source)
        self.dialog.cmb_copy_from.setCurrentIndex(index)
        self.dialog._copy_rule_to_all()

        rules = self.win.data["limit_notifications"]
        template = rules[source]
        for account in (self.first, self.second):
            for window_key in (FIVE_HOUR, WEEKLY):
                key = self._key(account, window_key)
                assert rules[key] == template, key

    def test_the_source_section_is_not_touched(self):
        source = self._key(self.second, WEEKLY)
        self.dialog._set_rule(source, "threshold", 12.5)
        self.dialog.cmb_copy_from.setCurrentIndex(
            self.dialog.cmb_copy_from.findData(source))
        self.dialog._copy_rule_to_all()
        assert self.win.data["limit_notifications"][source]["threshold"] == 12.5

    def test_copying_clears_the_targets_suppression_state(self):
        """A copied threshold must get one honest chance to fire."""
        source = self._key(self.first, FIVE_HOUR)
        target = self._key(self.second, WEEKLY)
        self.win.data["limit_notification_state"] = {
            target: {"low_alerted": 20.0, "remaining": 5.0},
        }
        self.dialog._set_rule(source, "enabled", True)
        self.dialog.cmb_copy_from.setCurrentIndex(
            self.dialog.cmb_copy_from.findData(source))
        self.dialog._copy_rule_to_all()
        assert target not in self.win.data["limit_notification_state"]

    def test_copying_reevaluates_the_alerts_once(self):
        before = self.win.checked
        self.dialog._copy_rule_to_all()
        assert self.win.checked == before + 1

    def test_the_hint_names_how_many_sections_were_written(self):
        self.dialog._copy_rule_to_all()
        text = self.dialog.lbl_copy_hint.text()
        assert "3 other section" in text

    def test_the_rows_are_rebuilt_so_the_widgets_show_the_copy(self):
        source = self._key(self.first, FIVE_HOUR)
        self.dialog._set_rule(source, "threshold", 33.0)
        self.dialog.cmb_copy_from.setCurrentIndex(
            self.dialog.cmb_copy_from.findData(source))
        self.dialog._copy_rule_to_all()
        from PyQt6.QtWidgets import QDoubleSpinBox
        spins = self.dialog.alert_scroll.widget().findChildren(QDoubleSpinBox)
        thresholds = [s.value() for s in spins if s.suffix() == " %"]
        assert thresholds and all(v == 33.0 for v in thresholds)


class TestCopyControlsWithoutTargets(unittest.TestCase):
    def test_a_single_section_disables_the_copy_controls(self):
        now = time.time()
        account = _account("solo", "Codex Free")
        snapshots = {account.key: UsageSnapshot(account, OK, [
            UsageWindow("monthly", 43200, True, 40, 60, now + 900)])}
        win = _MainWin([account], snapshots)
        from fastprompter.ui.limit_settings_dialog import LimitSettingsDialog
        dialog = LimitSettingsDialog(win)
        try:
            assert dialog.cmb_copy_from.count() == 1
            assert not dialog.btn_copy_to_all.isEnabled()
            assert "nothing to copy" in dialog.lbl_copy_hint.text().lower()
            # and pressing it anyway must be a no-op, not a crash
            dialog._copy_rule_to_all()
        finally:
            dialog.close()
            dialog.deleteLater()
            win.deleteLater()
            _APP.processEvents()

    def test_no_accounts_leaves_the_controls_dead_but_alive(self):
        win = _MainWin([], {})
        from fastprompter.ui.limit_settings_dialog import LimitSettingsDialog
        dialog = LimitSettingsDialog(win)
        try:
            assert dialog.cmb_copy_from.count() == 0
            assert not dialog.btn_copy_to_all.isEnabled()
            dialog._copy_rule_to_all()
        finally:
            dialog.close()
            dialog.deleteLater()
            win.deleteLater()
            _APP.processEvents()
