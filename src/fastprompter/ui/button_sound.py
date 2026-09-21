"""Default click sound for every button press (T-1225).

Every ``QAbstractButton`` release that will fire ``clicked`` answers with a
sound: the action's own if its handler plays one, otherwise the default
``click`` event. Catching the release at the application level is the same
trick ScrollSoundFilter uses for wheels — there are hundreds of buttons
across the header, the docks and every dialog, and wiring each
``clicked.connect`` by hand is exactly how "every hotkey has a sound"
degraded into the eleven somebody remembered to edit.

The drop-if-anything-played check runs on a 0 ms single shot: the filter
sees the release BEFORE the button emits ``clicked``, so by the time the
deferred check runs the handler's own sound (if any) is already recorded in
the manager's request counter. One sound per click, never two.
"""

from __future__ import annotations

from PyQt6.QtCore import QEvent, QObject, Qt, QTimer
from PyQt6.QtWidgets import QAbstractButton

from fastprompter.core.logging import logger


class ButtonClickSoundFilter(QObject):
    """Plays the default click for button presses that stayed silent."""

    def __init__(self, sound_manager):
        super().__init__()
        self._sound_manager = sound_manager
        self._armed_seq: int | None = None
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(0)
        self._timer.timeout.connect(self._fire)

    def eventFilter(self, obj, event):
        if (event.type() == QEvent.Type.MouseButtonRelease
                and event.button() == Qt.MouseButton.LeftButton
                and isinstance(obj, QAbstractButton)
                and obj.rect().contains(event.position().toPoint())):
            # Armed BEFORE the button emits clicked, so the handler's own
            # sound lands inside the window this snapshot guards.
            self._armed_seq = self._sound_manager.request_count()
            self._timer.start()
        return False

    def _fire(self):
        seq = self._armed_seq
        self._armed_seq = None
        if seq is None or self._sound_manager.request_count() != seq:
            return          # the click's own handler already made a sound
        try:
            self._sound_manager.play("click")
        except Exception:
            # A click sound is decoration, never a fault surface.
            logger.debug("default button click sound failed", exc_info=True)
