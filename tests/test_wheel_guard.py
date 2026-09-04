"""An unfocused combo/spin must not eat the mouse wheel.

Reported as "random sounds during Interval Notifications": scrolling that tab
dragged the pointer across the rule's sound combo, which stepped its index,
fired the live preview, and played a sound nobody asked for — while the same
gesture also nudged the interval and the volume spinners.
"""

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QPoint, QPointF, Qt
from PyQt6.QtGui import QWheelEvent
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QScrollArea,
    QSlider,
    QSpinBox,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
)

from fastprompter.ui.wheel_guard import WheelGuard

_APP = QApplication.instance() or QApplication([])


def _wheel(widget, notches=-1):
    return QWheelEvent(
        QPointF(widget.rect().center()),
        QPointF(widget.mapToGlobal(widget.rect().center())),
        QPoint(0, notches * 40),
        QPoint(0, notches * 120),
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.NoScrollPhase,
        False,
    )


class TestWheelGuard(unittest.TestCase):
    def setUp(self):
        self.guard = WheelGuard()
        _APP.installEventFilter(self.guard)
        self.dialog = QDialog()
        outer = QVBoxLayout(self.dialog)
        self.area = QScrollArea()
        self.area.setWidgetResizable(True)
        host = QWidget()
        lay = QVBoxLayout(host)
        self.combo = QComboBox()
        self.combo.addItems([f"sound {i}" for i in range(12)])
        self.spin = QSpinBox()
        self.spin.setRange(1, 10080)
        self.spin.setValue(60)
        self.volume = QDoubleSpinBox()
        self.volume.setRange(0.0, 1.0)
        self.volume.setSingleStep(0.05)
        self.volume.setValue(0.05)
        self.time = QTimeEdit()
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, 100)
        self.slider.setValue(50)
        for widget in (self.combo, self.spin, self.volume, self.time,
                       self.slider):
            lay.addWidget(widget)
        for _ in range(40):
            lay.addWidget(QComboBox())
        self.area.setWidget(host)
        outer.addWidget(self.area)
        self.dialog.resize(320, 200)
        self.dialog.show()
        _APP.processEvents()

    def tearDown(self):
        _APP.removeEventFilter(self.guard)
        self.dialog.close()
        self.dialog.deleteLater()
        _APP.processEvents()

    def _send(self, widget, notches=-1):
        _APP.sendEvent(widget, _wheel(widget, notches))
        _APP.processEvents()

    def test_scrolling_past_a_combo_does_not_change_it(self):
        fired = []
        self.combo.currentIndexChanged.connect(lambda i: fired.append(i))
        index = self.combo.currentIndex()
        self._send(self.combo)
        assert fired == []
        assert self.combo.currentIndex() == index

    def test_scrolling_past_the_spinners_does_not_edit_them(self):
        self._send(self.spin)
        self._send(self.volume)
        assert self.spin.value() == 60
        assert abs(self.volume.value() - 0.05) < 1e-9

    def test_a_slider_and_a_time_edit_are_guarded_too(self):
        self._send(self.slider)
        assert self.slider.value() == 50
        before = self.time.time()
        self._send(self.time)
        assert self.time.time() == before

    def test_the_panel_scrolls_instead(self):
        bar = self.area.verticalScrollBar()
        assert bar.maximum() > bar.minimum(), "the fixture must be scrollable"
        before = bar.value()
        self._send(self.combo)
        assert bar.value() > before

    def test_a_focused_widget_still_takes_the_wheel(self):
        """Focus is the user's explicit "I am editing this" signal."""
        self.combo.setFocus()
        _APP.processEvents()
        index = self.combo.currentIndex()
        bar = self.area.verticalScrollBar()
        before = bar.value()
        self._send(self.combo)
        assert self.combo.currentIndex() != index
        assert bar.value() == before

    def test_a_plain_widget_is_left_alone(self):
        """The guard must not touch anything that is not a value widget."""
        seen = []

        class _Probe(QWidget):
            def wheelEvent(self, event):
                seen.append(event.angleDelta().y())
                event.accept()

        probe = _Probe(self.dialog)
        probe.resize(40, 20)
        probe.show()
        _APP.processEvents()
        self._send(probe)
        assert seen and seen[0] != 0
        probe.deleteLater()

    def test_without_a_scrollable_ancestor_the_value_is_still_protected(self):
        """A dialog that does not scroll must not silently edit either."""
        plain = QDialog()
        lay = QVBoxLayout(plain)
        combo = QComboBox()
        combo.addItems(["a", "b", "c"])
        lay.addWidget(combo)
        # A shown dialog hands focus to its first focusable child, which would
        # make this the deliberate-edit case instead of the pointer-luck one.
        anchor = QSpinBox()
        lay.addWidget(anchor)
        plain.show()
        anchor.setFocus()
        _APP.processEvents()
        try:
            assert not combo.hasFocus()
            index = combo.currentIndex()
            _APP.sendEvent(combo, _wheel(combo))
            _APP.processEvents()
            assert combo.currentIndex() == index
        finally:
            plain.close()
            plain.deleteLater()
            _APP.processEvents()


class TestScrollSoundStillWorks(unittest.TestCase):
    """The guard redirects the wheel; it must not silence the scroll tick."""

    def test_the_debounced_scroll_tick_survives_the_redirect(self):
        from fastprompter.ui.scroll_sound import ScrollSoundFilter

        class _Sounds:
            def __init__(self):
                self.played = []

            def play(self, name):
                self.played.append(name)

        sounds = _Sounds()
        scroll_filter = ScrollSoundFilter(sounds)
        guard = WheelGuard()
        _APP.installEventFilter(scroll_filter)
        _APP.installEventFilter(guard)
        dialog = QDialog()
        outer = QVBoxLayout(dialog)
        area = QScrollArea()
        area.setWidgetResizable(True)
        host = QWidget()
        lay = QVBoxLayout(host)
        combo = QComboBox()
        combo.addItems(["a", "b", "c"])
        lay.addWidget(combo)
        for _ in range(40):
            lay.addWidget(QComboBox())
        area.setWidget(host)
        outer.addWidget(area)
        dialog.resize(300, 180)
        dialog.show()
        _APP.processEvents()
        try:
            _APP.sendEvent(combo, _wheel(combo))
            _APP.processEvents()
            scroll_filter._timer.stop()
            scroll_filter._fire()
            assert sounds.played == ["scroll"]
        finally:
            _APP.removeEventFilter(scroll_filter)
            _APP.removeEventFilter(guard)
            dialog.close()
            dialog.deleteLater()
            _APP.processEvents()
