"""Tests for T-1175: settings panel scrolling, scroll-tick sound,
limit-gauges click contract, and the compact LimitSettingsDialog."""

import unittest

from PyQt6.QtCore import QEvent, QPoint, QPointF, Qt
from PyQt6.QtGui import QMouseEvent, QWheelEvent
from PyQt6.QtWidgets import QApplication, QDialog, QScrollArea, QVBoxLayout, QWidget

from fastprompter.core.sound_manager import _DEFAULT_SOUND_MAP, EVENT_LABELS


class _FakeSoundManager:
    def __init__(self):
        self.played = []

    def play(self, name):
        self.played.append(name)


class TestScrollSound(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def _make_wheel(self, dy=120):
        wheel = QWheelEvent(
            QPointF(4, 4), QPointF(4, 4),
            QPoint(0, dy), QPoint(0, dy),
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
            Qt.ScrollPhase.ScrollUpdate, False)
        return wheel

    def test_wheel_inside_dialog_queues_sound(self):
        from fastprompter.ui.scroll_sound import ScrollSoundFilter

        sm = _FakeSoundManager()
        dlg = QDialog()
        inner = QWidget(dlg)
        lay = QVBoxLayout(dlg)
        lay.addWidget(inner)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        sc_inside = QWidget()
        sc_inside.setMinimumHeight(800)
        scroll.setWidget(sc_inside)
        inner_layout = QVBoxLayout(inner)
        inner_layout.addWidget(scroll)

        entry = ScrollSoundFilter(sm, main_win=None)
        wheel = self._make_wheel()
        filtered = entry.eventFilter(sc_inside, wheel)
        self.assertFalse(filtered)
        # The debounce timer must be armed.
        self.assertTrue(entry._timer.isActive() or entry._pending)
        dlg.deleteLater()

    def test_wheel_outside_dialog_is_silent(self):
        from fastprompter.ui.scroll_sound import ScrollSoundFilter

        sm = _FakeSoundManager()
        root = QWidget()
        entry = ScrollSoundFilter(sm, main_win=None)
        wheel = self._make_wheel()
        filtered = entry.eventFilter(root, wheel)
        self.assertFalse(filtered)
        self.assertFalse(entry._pending)
        self.assertFalse(entry._timer.isActive())
        root.deleteLater()

    def test_debounce_coalesces_fast_scroll(self):
        from fastprompter.ui.scroll_sound import ScrollSoundFilter

        sm = _FakeSoundManager()
        dlg = QDialog()
        inner = QWidget(dlg)
        lay = QVBoxLayout(dlg)
        lay.addWidget(inner)
        entry = ScrollSoundFilter(sm, main_win=None)
        for _ in range(12):
            entry.eventFilter(inner, self._make_wheel())
        self.assertTrue(entry._pending)
        # One pending burst only; timer does not re-arm to another interval.
        self.assertTrue(entry._timer.isActive())
        entry._timer.stop()
        entry._fire()
        self.assertEqual(len(sm.played), 1)
        self.assertEqual(sm.played[0], "scroll")
        dlg.deleteLater()

    def test_scroll_event_is_registered(self):
        self.assertIn("scroll", EVENT_LABELS)
        self.assertEqual(_DEFAULT_SOUND_MAP["scroll"], "click_hint.wav")


class _FakeService:
    def __init__(self):
        self.refresh_count = 0
        self.state_copy = _FakeState()
        self._callbacks = []

    def add_callback(self, cb):
        self._callbacks.append(cb)

    def refresh(self):
        self.refresh_count += 1


class _FakeAccount:
    key = "codex:test"
    display_name = "Codex Test"
    provider_id = "codex"
    source_path = ""


class _FakeState:
    accounts = []
    snapshots = {}


class _FakeMainWin:
    def __init__(self):
        self.data = {}
        self.opened = False

    def open_limit_settings_dialog(self):
        self.opened = True


class TestLimitGaugesClick(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def test_single_click_opens_settings(self):
        from fastprompter.ui.limit_gauges import LimitGauges

        win = _FakeMainWin()
        svc = _FakeService()
        gauges = LimitGauges(win, svc)
        event = QMouseEvent(
            QEvent.Type.MouseButtonPress,
            QPointF(1, 1),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier)
        gauges.mousePressEvent(event)
        self.assertTrue(win.opened)
        self.assertEqual(svc.refresh_count, 0)
        gauges.deleteLater()

    def test_double_click_refreshes(self):
        from fastprompter.ui.limit_gauges import LimitGauges

        win = _FakeMainWin()
        svc = _FakeService()
        gauges = LimitGauges(win, svc)
        event = QMouseEvent(
            QEvent.Type.MouseButtonDblClick,
            QPointF(1, 1),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier)
        gauges.mouseDoubleClickEvent(event)
        self.assertFalse(win.opened)
        self.assertEqual(svc.refresh_count, 1)
        gauges.deleteLater()

    def test_tooltip_mentions_settings(self):
        from fastprompter.ui.limit_gauges import LimitGauges

        win = _FakeMainWin()
        svc = _FakeService()
        gauges = LimitGauges(win, svc)
        self.assertIn("settings", gauges.toolTip().lower())
        gauges.deleteLater()

    def test_ctrl_click_cycles_style(self):
        from fastprompter.ui.limit_gauges import LimitGauges

        win = _FakeMainWin()
        svc = _FakeService()
        gauges = LimitGauges(win, svc)
        self.assertEqual(gauges._style(), "bars")

        event = QMouseEvent(
            QEvent.Type.MouseButtonPress,
            QPointF(1, 1),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.ControlModifier)

        # bars -> dots -> stack -> bars, and never opens the settings dialog
        for expected in ("dots", "stack", "bars"):
            gauges.mousePressEvent(event)
            self.assertEqual(win.data["limit_gauges_style"], expected)
            self.assertEqual(gauges._style(), expected)
            self.assertFalse(win.opened)
        gauges.deleteLater()


class TestSettingsGearEasterEgg(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def test_gear_button_toggles_settings_without_rotation(self):
        from fastprompter.main import FastPrompter, _SettingsGearButton
        import fastprompter.core.state as state_mod
        state_mod.get_db_path = lambda p=1: ":memory:"
        state_mod.run_portable_backup = lambda d, p=1: None
        FastPrompter.setup_single_instance_server = lambda s: None
        FastPrompter.register_all_hotkeys = lambda s: None
        FastPrompter.unregister_all_hotkeys = lambda s: None
        FastPrompter._init_limit_service = lambda s: None

        w = FastPrompter()
        self.assertIsInstance(w.btn_settings_toggle, _SettingsGearButton)
        self.assertIsInstance(w.btn_settings_toggle_right, _SettingsGearButton)
        self.assertFalse(hasattr(w.btn_settings_toggle, "_angle"))

        was_hidden = w.mini_settings_frame.isHidden()
        w.toggle_mini_settings()
        self.assertEqual(w.mini_settings_frame.isHidden(), not was_hidden)
        w.close()
        w.deleteLater()


class TestSettingsExitButton(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def test_settings_exit_buttons_trigger_quit(self):
        from fastprompter.main import FastPrompter
        import fastprompter.core.state as state_mod
        state_mod.get_db_path = lambda p=1: ":memory:"
        state_mod.run_portable_backup = lambda d, p=1: None
        FastPrompter.setup_single_instance_server = lambda s: None
        FastPrompter.register_all_hotkeys = lambda s: None
        FastPrompter.unregister_all_hotkeys = lambda s: None
        FastPrompter._init_limit_service = lambda s: None

        quit_calls = []
        FastPrompter.quit_app = lambda s: quit_calls.append(True)

        w = FastPrompter()
        w._ensure_settings_built()

        # Both exit buttons exist with correct labels
        self.assertTrue(hasattr(w, "btn_exit"))
        self.assertTrue(hasattr(w, "btn_exit_app"))
        self.assertEqual(w.btn_exit.text(), "Exit")
        self.assertEqual(w.btn_exit_app.text(), "Exit FastPrompter")

        w.btn_exit.click()
        self.assertEqual(len(quit_calls), 1)

        w.btn_exit_app.click()
        self.assertEqual(len(quit_calls), 2)

        w.close()
        w.deleteLater()


