"""PERF-004 regression: _update_date_label must gate all visual work on the
main window being visible, while the scheduler (_check_timers) stays alive on
the shared 1 Hz timer; showEvent performs one immediate catch-up.

The deterministic core is the gate itself: bound to a fake host, the method
must do nothing when the window is hidden and full visual work when visible.
"""

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

import fastprompter.main as main_mod  # noqa: E402

from PyQt6.QtWidgets import QApplication  # noqa: E402

_APP = QApplication.instance() or QApplication([])


class _Lbl:
    def __init__(self):
        self._visible = True
        self._text = ""

    def setVisible(self, v):
        self._visible = v

    def setText(self, t):
        self._text = t

    def text(self):
        return self._text

    def setMinimumWidth(self, w):
        pass

    def setMaximumWidth(self, w):
        pass

    def setAlignment(self, a):
        pass

    def setStyleSheet(self, s):
        pass

    def minimumWidth(self):
        return 0

    def font(self):
        from PyQt6.QtGui import QFont
        return QFont()


class _Clock:
    def sync(self):
        self.calls = getattr(self, "calls", 0) + 1


class _Host:
    def __init__(self, visible):
        self._visible_state = visible
        self.data = {"show_date_rect": "True", "date_seconds": "True",
                     "date_daypart": "True", "date_text_month": "False",
                     "date_ampm": "False", "date_emoji": "False"}
        self.lbl_date = _Lbl()
        self.analog_clock = _Clock()
        self._header_ultra = False
        self._header_dense = False
        self._current_lang = "EN"
        self._missed_timer_ids = set()
        self.timers = []
        self.visual = {"label": 0}

    def isVisible(self):
        return self._visible_state

    def _clock_time_fmt(self, show_secs=False):
        return "%H:%M:%S" if show_secs else "%H:%M"

    def _day_part(self, hour):
        return "Morning"

    def _missed_attention(self):
        return []

    def _apply_date_alert_style(self):
        self.visual["label"] += 1

    def _update_timer_label(self):
        self.visual["label"] += 1


def _bind(host):
    host._update_date_label = main_mod.FastPrompter._update_date_label.__get__(host)
    return host


def test_hidden_does_no_visual_work():
    h = _bind(_Host(visible=False))
    h._update_date_label()
    assert h.visual["label"] == 0, "hidden window must not repaint labels"
    assert h.lbl_date.text() == "", "hidden window must not format/set date text"
    assert getattr(h.analog_clock, "calls", 0) == 0, "hidden: no clock sync"


def test_visible_does_full_visual_work():
    h = _bind(_Host(visible=True))
    h._update_date_label()
    assert h.visual["label"] >= 2, "visible: alert style + timer label run"
    assert h.lbl_date.text() != "", "visible: date text formatted"


def test_scheduler_not_gated():
    # the PERF-004 contract is that date_timer stays connected to _check_timers
    # unconditionally; only the visual callback is gated. Verify the timer
    # wiring in FastPrompter.__init__ still binds _check_timers to date_timer.
    import inspect
    src = inspect.getsource(main_mod.FastPrompter.__init__)
    assert "date_timer.timeout.connect(self._update_date_label)" in src
    assert "date_timer.timeout.connect(self._check_timers)" in src


def test_show_event_catch_up():
    import inspect
    src = inspect.getsource(main_mod.FastPrompter.showEvent)
    assert "_update_date_label()" in src, \
        "showEvent must perform an immediate visual catch-up"
