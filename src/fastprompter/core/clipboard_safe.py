"""QClipboard wrapper for the focus-stealing watcher sender.

The one clipboard race that matters: FastPrompter saves the user's
clipboard, writes its own prompt, pastes, and must put the old text back.
If the user copies something NEW during the restore delay, restoring would
overwrite their copy. Content equality alone cannot tell "the user copied
the SAME text we wrote" from "our write is still there" — so on Windows the
restore is gated on the OS clipboard REVISION (GetClipboardSequenceNumber),
which changes on every clipboard mutation. When the revision is unavailable,
the conservative content-equality fallback applies.

The decision logic is the Qt-free ``should_restore_clipboard`` in
``core/watcher/sender.py``; this class supplies the QClipboard reality, the
revision token and the delayed check. Qt is imported lazily so the class
stays unit-testable with an injected clipboard object, revision function and
timer factory.
"""

from __future__ import annotations

import sys

from fastprompter.core.watcher.sender import should_restore_clipboard


def clipboard_revision():
    """The Windows clipboard sequence number, or None when unavailable.

    The sequence increments on every clipboard write, so it can distinguish
    "the user copied the same text again" from "our write is still there".
    Returns None off-Windows or when the API cannot be reached — callers then
    fall back to conservative content comparison.
    """
    if sys.platform != "win32":
        return None
    try:
        import ctypes
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.GetClipboardSequenceNumber.argtypes = []
        user32.GetClipboardSequenceNumber.restype = ctypes.c_uint
        return int(user32.GetClipboardSequenceNumber())
    except Exception:
        return None


class QtClipboard:
    """A clipboard object the watcher sender can own and safely restore."""

    def __init__(self, clipboard=None, timer_factory=None, revision_fn=None):
        self._clip = clipboard
        self._timer_factory = timer_factory
        self._revision_fn = revision_fn or clipboard_revision
        self._own_write = None     # the last text WE put on the clipboard
        self._own_revision = None  # its OS revision right after our write

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
        # Capture the revision AFTER the write. Qt may hand the text to the
        # native clipboard on the next event-loop turn, so the read is
        # scheduled on turn 0: by the time restore_if_unchanged runs (delay
        # ms later) the revision reflects our own write.
        self._own_revision = None

        def _capture():
            self._own_revision = self._revision_fn()

        if self._timer_factory is not None:
            self._timer_factory(0, _capture)
        else:
            from PyQt6.QtCore import QTimer
            QTimer.singleShot(0, _capture)

    def restore_if_unchanged(self, previous, delay_ms):
        """Restore `previous` after `delay_ms` — but only if the clipboard
        still holds OUR OWN write.

        Primary gate: the OS clipboard revision must be unchanged since our
        write — a user copying ANYTHING (even the same text) bumps it and the
        restore is skipped. Fallback (revision unavailable): content equality.
        """
        if previous is None:
            return
        own = self._own_write
        own_revision = self._own_revision
        delay = max(0, int(delay_ms))

        def _maybe_restore():
            if not self._is_still_ours(own, own_revision):
                return          # the user's newer copy wins, untouched
            try:
                self._clipboard().setText(previous)
            except Exception:
                pass

        if self._timer_factory is not None:
            self._timer_factory(delay, _maybe_restore)
        else:
            from PyQt6.QtCore import QTimer
            QTimer.singleShot(delay, _maybe_restore)

    def _is_still_ours(self, own, own_revision):
        rev = self._revision_fn()
        if own_revision is not None and rev is not None:
            # revision is authoritative: ANY clipboard change (including a
            # user re-copying the same text) means "not ours any more"
            return rev == own_revision
        # conservative fallback: content must still equal our own write
        return should_restore_clipboard(self.get_text(), own)
