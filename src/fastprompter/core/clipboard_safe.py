"""QClipboard wrapper for the focus-stealing watcher sender.

The one clipboard race that matters: FastPrompter saves the user's
clipboard, writes its own prompt, pastes, and must put the old text back.
If the user copies something NEW during the restore delay, restoring would
overwrite their copy. So restoration is conditional — it runs only while the
clipboard still holds FastPrompter's own write.

The decision logic is the Qt-free ``should_restore_clipboard`` in
``core/watcher/sender.py``; this class only supplies the QClipboard reality
and the delayed check. Qt is imported lazily so the class stays unit-testable
with an injected clipboard object and timer factory.
"""

from __future__ import annotations

from fastprompter.core.watcher.sender import should_restore_clipboard


class QtClipboard:
    """A clipboard object the watcher sender can own and safely restore."""

    def __init__(self, clipboard=None, timer_factory=None):
        self._clip = clipboard
        self._timer_factory = timer_factory
        self._own_write = None     # the last text WE put on the clipboard

    def _clipboard(self):
        if self._clip is None:
            from PyQt6.QtWidgets import QApplication
            self._clip = QApplication.clipboard()
        return self._clip

    def get_text(self):
        return self._clipboard().text() or ""

    def set_text(self, text):
        self._own_write = text or ""
        self._clipboard().setText(self._own_write)

    def restore_if_unchanged(self, previous, delay_ms):
        """Restore `previous` after `delay_ms` — but only if the clipboard
        still holds our own write. A user's newer copy is never overwritten."""
        if previous is None:
            return
        own = self._own_write
        delay = max(0, int(delay_ms))

        def _maybe_restore():
            if should_restore_clipboard(self.get_text(), own):
                try:
                    self._clipboard().setText(previous)
                except Exception:
                    pass

        if self._timer_factory is not None:
            self._timer_factory(delay, _maybe_restore)
        else:
            from PyQt6.QtCore import QTimer
            QTimer.singleShot(delay, _maybe_restore)
