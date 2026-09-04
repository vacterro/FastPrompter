"""Tray context-menu toggles delegate to the canonical handlers and read
state from the live sources. Pure logic, no QApplication needed."""

from fastprompter.ui.tray_mixin import TrayMixin


class _Win(TrayMixin):
    def __init__(self):
        self.data = {
            "always_on_top": "True",
            "close_on_focus_loss": "False",
            "tray_visible": "True",
        }
        self.cb_focus = None
        self.cb_tray = None
        self.dirty = 0
        self.pins = []
        self.aot = []
        self.tray = []

    def mark_dirty(self, *a, **k):
        self.dirty += 1

    def _pin_top_toggled(self, checked):
        self.pins.append(checked)

    def toggle_aot(self, checked):
        self.aot.append(checked)

    def on_tray_toggled(self, checked):
        self.tray.append(checked)
        self.data["tray_visible"] = str(checked)


def test_tray_state_reads_data():
    w = _Win()
    assert w._tray_state() == (True, False, True)


def test_aot_prefers_pin_top_handler():
    w = _Win()
    w._on_tray_aot(True)
    assert w.pins == [True]


def test_aot_falls_back_to_toggle_aot():
    w = _Win()
    w._pin_top_toggled = None
    w._on_tray_aot(False)
    assert w.aot == [False]


def test_focus_data_branch_persists():
    w = _Win()
    w._on_tray_focus(True)
    assert w.data["close_on_focus_loss"] == "True"
    assert w.dirty == 1


def test_icon_data_branch_delegates():
    w = _Win()
    w._on_tray_icon(False)
    assert w.tray == [False]
    assert w.data["tray_visible"] == "False"
