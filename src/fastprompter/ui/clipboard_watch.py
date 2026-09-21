"""QClipboard observation generation — T-1269 append A2.

The OS generation counter (``core.win_clipboard``) says what the clipboard
GENERATION is; this says what the Qt side of the same boundary OBSERVED. The
two can disagree in a way that matters for the operator's report:

* the OS counter moved and Qt never signalled ``changed``/``dataChanged`` —
  the notification was lost or Qt's clipboard owner is not the one that
  rewrote the payload;
* Qt signalled and the OS counter did not move — the notification is about the
  same generation (a re-announcement), not a new payload.

Both counters ride in every paste record. Nothing here reads clipboard content.
"""

from __future__ import annotations

import time

from PyQt6.QtCore import QObject

_WATCH = None


class ClipboardWatch(QObject):
    """Counts ``changed``/``dataChanged`` notifications since it attached.

    The counters are monotonic for the lifetime of the process. They are
    deliberately NOT reset by any paste: "how many clipboard notifications has
    FastPrompter seen" is the question, and a restart-relative baseline would
    answer a different one.
    """

    def __init__(self, clipboard, parent=None):
        super().__init__(parent)
        self._clipboard = clipboard
        self.changed_count = 0
        self.data_changed_count = 0
        self.last_change_monotonic = None
        self.attached = False
        try:
            clipboard.changed.connect(self._on_changed)
            clipboard.dataChanged.connect(self._on_data_changed)
            self.attached = True
        except Exception:
            self.attached = False

    def _on_changed(self):
        self.changed_count += 1
        self.last_change_monotonic = time.monotonic()

    def _on_data_changed(self):
        self.data_changed_count += 1
        self.last_change_monotonic = time.monotonic()

    def snapshot(self):
        """Bounded state: counts and the last notification instant, no content."""
        return {
            "attached": bool(self.attached),
            "clipboard_id": id(self._clipboard),
            "changed_count": int(self.changed_count),
            "data_changed_count": int(self.data_changed_count),
            "generation": int(self.changed_count + self.data_changed_count),
            "last_change_monotonic": self.last_change_monotonic,
        }


def clipboard_watch(clipboard=None):
    """The process-wide watcher for ``clipboard`` (attached lazily, once).

    Kept as a module-level singleton so several paste attempts share one
    notification baseline, and so the QObject outlives the connection (a
    garbage-collected receiver would silently stop counting).
    """
    global _WATCH
    if _WATCH is not None:
        return _WATCH
    if clipboard is None:
        from PyQt6.QtWidgets import QApplication
        clipboard = QApplication.clipboard()
    if clipboard is None:
        return None
    _WATCH = ClipboardWatch(clipboard)
    return _WATCH


def clipboard_watch_snapshot(clipboard=None):
    """Convenience: the watcher's snapshot, or an unattached one on failure."""
    try:
        watch = clipboard_watch(clipboard)
        if watch is None:
            return {"attached": False, "generation": None}
        return watch.snapshot()
    except Exception:
        return {"attached": False, "generation": None}
