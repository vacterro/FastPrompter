"""Offscreen tests for the TimerToast stack discipline.

T-1007: simultaneous toasts must be bounded (oldest retired when the stack
would overflow the screen) and profile-owned toasts must close on switch.
"""

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import datetime  # noqa: E402

from PyQt6 import sip  # noqa: E402
from PyQt6.QtCore import QRect  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

from fastprompter.core.timers import Timer  # noqa: E402
from fastprompter.ui import timer_toast as toast_mod  # noqa: E402
from fastprompter.ui.timer_toast import TimerToast  # noqa: E402

_APP = QApplication.instance() or QApplication([])


class _FakeScreen:
    def __init__(self, width, height):
        self._area = QRect(0, 0, width, height)

    def availableGeometry(self):
        return self._area


class _FakeWin:
    _current_lang = "EN"

    def geometry(self):
        return QRect(0, 0, 100, 100)


def _mk_timer(name="t"):
    return Timer(name, datetime.datetime.now() + datetime.timedelta(hours=1))


def test_stack_bounded_retires_oldest(monkeypatch):
    fake_screen = _FakeScreen(800, 600)
    monkeypatch.setattr(QApplication, "primaryScreen", lambda: fake_screen)
    t1 = TimerToast(None, _mk_timer("one"))
    t1.show()
    h = t1.height()
    # a screen that fits EXACTLY two toasts (with the 8px gap between)
    fake_screen._area = QRect(0, 0, 800, 2 * toast_mod._MARGIN
                              + 2 * (h + 8) + 10)
    t2 = TimerToast(None, _mk_timer("two"))
    t2.show()
    t3 = TimerToast(None, _mk_timer("three"))
    t3.show()
    assert t1 not in TimerToast._open       # oldest retired to make room
    assert not t1.isVisible()
    assert t2 in TimerToast._open and t3 in TimerToast._open
    assert not t2.geometry().intersects(t3.geometry())   # never overlap


def test_toasts_stack_above_each_other(monkeypatch):
    fake_screen = _FakeScreen(800, 600)
    monkeypatch.setattr(QApplication, "primaryScreen", lambda: fake_screen)
    t1 = TimerToast(None, _mk_timer("one"))
    t1.show()
    h = t1.height()
    fake_screen._area = QRect(0, 0, 800, 2 * toast_mod._MARGIN
                              + 2 * (h + 8) + 10)
    t2 = TimerToast(None, _mk_timer("two"))
    t2.show()
    assert t2.y() < t1.y()                   # later toast sits above
    assert t2.x() == t1.x()                  # same right edge


def test_close_for_main_closes_only_that_profiles_toasts(monkeypatch):
    fake_screen = _FakeScreen(800, 600)
    monkeypatch.setattr(QApplication, "primaryScreen", lambda: fake_screen)
    win_a, win_b = _FakeWin(), _FakeWin()
    ta = TimerToast(win_a, _mk_timer("a"))
    ta.show()
    tb = TimerToast(win_b, _mk_timer("b"))
    tb.show()
    TimerToast.close_for_main(win_a)
    assert ta not in TimerToast._open
    assert not ta.isVisible()
    assert tb in TimerToast._open
    assert tb.isVisible()


def test_stale_entries_pruned_on_next_place(monkeypatch):
    fake_screen = _FakeScreen(800, 600)
    monkeypatch.setattr(QApplication, "primaryScreen", lambda: fake_screen)
    t1 = TimerToast(None, _mk_timer("stale"))
    t1.show()
    t1.hide()
    t1.deleteLater()                         # destroyed WITHOUT closeEvent
    from PyQt6.QtTest import QTest
    QTest.qWait(40)
    t2 = TimerToast(None, _mk_timer("fresh"))
    t2.show()
    assert t1 not in TimerToast._open        # pruned, though closeEvent never ran
    assert t2 in TimerToast._open
    for t in TimerToast._open:               # no dangling deleted entries
        assert not sip.isdeleted(t)
