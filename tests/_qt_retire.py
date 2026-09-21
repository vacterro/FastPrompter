"""T-1260: actually destroy a Qt object a test is finished with.

``deleteLater()`` only POSTS a DeferredDelete event. Unit tests do not run an
event loop, so in ``pytest tests/`` that event is never delivered and the
object stays alive on the shared QApplication for the whole session. Measured:
``tests/test_audio_settings.py`` alone left 35 514 widgets behind (one full
``SoundSettingsDialog`` per test), and the session peaked at 37 488 live
widgets with 201 armed timers — which is how a later test's real 50 ms QTimer
missed a 5 s watchdog (``test_timer_fire``) and how a ``QTimer(self)`` inside
``VaultTextEdit.__init__`` took the interpreter down with an access violation.

Delivery is RECEIVER-SPECIFIC on purpose. ``sendPostedEvents(None, ...)``
would also destroy objects other test files still own.
"""

from PyQt6 import sip
from PyQt6.QtCore import QEvent
from PyQt6.QtWidgets import QApplication


def retire(*objects):
    """deleteLater() each object AND deliver its DeferredDelete, now.

    Children go with their parent, so passing the top of a tree is enough.
    Already-destroyed objects are skipped instead of raising.
    """
    for obj in objects:
        if obj is None:
            continue
        try:
            if sip.isdeleted(obj):
                continue
            obj.deleteLater()
            QApplication.sendPostedEvents(obj, QEvent.Type.DeferredDelete)
        except (RuntimeError, TypeError):
            continue
