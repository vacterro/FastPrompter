"""Subtle audio feedback when the user scrolls a panel.

Plays the ``scroll`` sound event from the sound library, debounced so a
fast wheel flurry becomes one tick per ~80 ms instead of a machine-gun
of overlapping clips. Honours the global ``sound_ui`` toggle via the
sound manager — when the user has switched UI sounds off, this filter
becomes a no-op as well.

Why an event filter and not per-widget ``valueChanged`` wiring: there
are dozens of ``QScrollArea`` widgets scattered through the app, and a
new one in any dialog would need to remember to attach itself. Catching
``QEvent.Type.Wheel`` at the application level reaches them all without
adding a single line to the dialogs themselves.
"""

from __future__ import annotations

from PyQt6.QtCore import QEvent, QObject, QTimer
from PyQt6.QtWidgets import QDialog, QWidget

_DEBOUNCE_MS = 80


class ScrollSoundFilter(QObject):
    """Wheel-event filter that plays a debounced scroll sound.

    Deliberately scoped to settings surfaces: the wheel event only counts
    when it lands inside the mini-settings frame or any modal dialog, so
    scrolling the main editor does not tick. ``mini_frame`` may be None,
    in which case only dialogs count.
    """

    def __init__(self, sound_manager, main_win=None):
        super().__init__()
        self._sound_manager = sound_manager
        self._main_win = main_win
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(_DEBOUNCE_MS)
        self._timer.timeout.connect(self._fire)
        self._pending = False

    def _in_settings_surface(self, obj):
        widget = obj if isinstance(obj, QWidget) else None
        if widget is None:
            node = obj.parent() if obj is not None else None
            while node is not None:
                if isinstance(node, QWidget):
                    widget = node
                    break
                node = node.parent()
        if widget is None:
            return False
        mini_frame = getattr(self._main_win, "mini_settings_frame", None) \
            if self._main_win is not None else None
        node = widget
        while node is not None:
            if isinstance(node, QDialog):
                return True
            if mini_frame is not None and node is mini_frame:
                return True
            node = node.parentWidget()
        return False

    def eventFilter(self, obj, event):
        if event.type() != QEvent.Type.Wheel:
            return False
        if not self._in_settings_surface(obj):
            return False
        wheel = event  # type: QWheelEvent
        # Only count wheel events with a non-zero pixel delta — the angle
        # delta is set even by trackpad gestures, but it is the angle delta
        # that decides how much the view actually moved. ``angleDelta().y()``
        # is positive on a downward wheel; ``pixelDelta().y()`` is the same
        # direction in physical pixels. Either alone is enough.
        if wheel.angleDelta().y() == 0 and wheel.pixelDelta().y() == 0:
            return False
        self._pending = True
        if not self._timer.isActive():
            self._timer.start()
        return False

    def _fire(self):
        if not self._pending:
            return
        self._pending = False
        try:
            self._sound_manager.play("scroll")
        except Exception:
            # A scroll sound is decoration, never a fault surface.
            pass
