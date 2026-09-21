"""T-1225: default click sound on every button press that stayed silent.

The filter arms on a left-button release inside a button, then fires on a
0 ms single shot; if the click's own handler already played any sound, the
default is dropped. One sound per click, never two.
"""

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

from PyQt6.QtCore import QPointF, Qt  # noqa: E402
from PyQt6.QtGui import QMouseEvent  # noqa: E402
from PyQt6.QtTest import QTest  # noqa: E402
from PyQt6.QtWidgets import QLabel, QPushButton  # noqa: E402

from fastprompter.ui.button_sound import ButtonClickSoundFilter  # noqa: E402


class _FakeSoundManager:
    def __init__(self):
        self.count = 0
        self.played = []

    def request_count(self):
        return self.count

    def play(self, name, **_kw):
        self.count += 1
        self.played.append(name)


def _release(pos=QPointF(5, 5),
             button=Qt.MouseButton.LeftButton):
    return QMouseEvent(
        QMouseEvent.Type.MouseButtonRelease, pos, pos,
        button, Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier)


def _press(pos=QPointF(5, 5)):
    return QMouseEvent(
        QMouseEvent.Type.MouseButtonPress, pos, pos,
        Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier)


def test_silent_button_gets_default_click(qapp):
    sm = _FakeSoundManager()
    flt = ButtonClickSoundFilter(sm)
    btn = QPushButton("X")
    flt.eventFilter(btn, _release())
    qapp.processEvents()
    assert sm.played == ["click"]


def test_action_sound_wins_over_default_click(qapp):
    sm = _FakeSoundManager()
    flt = ButtonClickSoundFilter(sm)
    qapp.installEventFilter(flt)
    btn = QPushButton("X")
    btn.clicked.connect(lambda: sm.play("snippet"))
    btn.show()
    try:
        QTest.mouseClick(btn, Qt.MouseButton.LeftButton)
        qapp.processEvents()
    finally:
        qapp.removeEventFilter(flt)
    assert sm.played == ["snippet"]


def test_release_outside_button_never_clicks(qapp):
    sm = _FakeSoundManager()
    flt = ButtonClickSoundFilter(sm)
    btn = QPushButton("X")
    btn.resize(30, 20)
    flt.eventFilter(btn, _release(pos=QPointF(500, 500)))
    qapp.processEvents()
    assert sm.played == []


def test_right_button_and_press_events_are_ignored(qapp):
    sm = _FakeSoundManager()
    flt = ButtonClickSoundFilter(sm)
    btn = QPushButton("X")
    flt.eventFilter(btn, _release(button=Qt.MouseButton.RightButton))
    flt.eventFilter(btn, _press())
    qapp.processEvents()
    assert sm.played == []


def test_non_button_objects_are_ignored(qapp):
    sm = _FakeSoundManager()
    flt = ButtonClickSoundFilter(sm)
    flt.eventFilter(QLabel("not a button"), _release())
    qapp.processEvents()
    assert sm.played == []


def test_two_rapid_clicks_before_loop_coalesce_to_one(qapp):
    sm = _FakeSoundManager()
    flt = ButtonClickSoundFilter(sm)
    btn = QPushButton("X")
    flt.eventFilter(btn, _release())
    flt.eventFilter(btn, _release())
    qapp.processEvents()
    assert sm.played == ["click"]
