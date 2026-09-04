"""Stop the mouse wheel from silently editing a value it is scrolling past.

Qt sends a wheel event to whatever widget is under the pointer, and
``QComboBox`` / ``QAbstractSpinBox`` / ``QSlider`` treat it as "change my
value" even when they do not have focus. In a scrollable panel this is a data
hazard, not a cosmetic one: scrolling the Interval Notifications tab drags the
pointer across the sound combo, the interval spinner and the volume spinner,
and each one silently takes a step. The combo's ``currentIndexChanged`` fires
its live preview, so the user hears a sound they never asked for — reported as
"random sounds during Interval timer notifications" — and the rule's minutes
and volume have quietly changed by the time they stop scrolling.

The fix is the behaviour every careful desktop app uses: a value widget reacts
to the wheel only while it HAS FOCUS (i.e. the user deliberately clicked into
it). Otherwise the event is redirected to the nearest scrollable ancestor, so
the panel scrolls instead. Nothing is swallowed: the wheel always does exactly
one thing, and which thing is decided by focus, not by pointer luck.

Installed once on the application, so a value widget added to any future dialog
inherits the rule without a line of its own.
"""

from __future__ import annotations

from PyQt6.QtCore import QEvent, QObject
from PyQt6.QtWidgets import (
    QAbstractScrollArea,
    QAbstractSpinBox,
    QComboBox,
    QSlider,
    QWidget,
)

# Widgets whose wheel handling mutates a stored value. QAbstractSpinBox covers
# QSpinBox/QDoubleSpinBox/QDateTimeEdit/QTimeEdit; QComboBox covers every combo.
_VALUE_WIDGETS = (QComboBox, QAbstractSpinBox, QSlider)


class WheelGuard(QObject):
    """Application-level filter: unfocused value widgets never eat the wheel."""

    def eventFilter(self, obj, event):
        if event.type() != QEvent.Type.Wheel:
            return False
        if not isinstance(obj, _VALUE_WIDGETS):
            return False
        if obj.hasFocus():
            return False        # deliberate: the user clicked in first
        scroller = self._scrollable_ancestor(obj)
        if scroller is not None:
            # Hand the gesture to the panel the user is actually scrolling.
            # sendEvent, not postEvent: the scroll must land in the same turn,
            # or a fast flurry arrives after the pointer has moved on.
            from PyQt6.QtWidgets import QApplication
            QApplication.sendEvent(scroller.viewport(), event)
        # Consumed either way: without a scrollable ancestor there is nothing
        # to scroll, and letting the event through would still change the value.
        event.accept()
        return True

    @staticmethod
    def _scrollable_ancestor(widget) -> QAbstractScrollArea | None:
        node = widget.parentWidget()
        while isinstance(node, QWidget):
            if isinstance(node, QAbstractScrollArea):
                bar = node.verticalScrollBar()
                if bar is not None and bar.maximum() > bar.minimum():
                    return node
            node = node.parentWidget()
        return None
