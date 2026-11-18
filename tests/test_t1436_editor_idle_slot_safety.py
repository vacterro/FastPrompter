"""T-1436: the idle-capture slot must not raise into the Qt event loop.

``VaultTextEdit`` arms a 2 s single-shot timer on every scrollbar change whose
timeout calls ``main_win.capture_silo_state()``. Qt delivers that slot from the
event loop, so a raised exception has no caller to reach: PyQt6 escalates it to
``qFatal()`` and the interpreter dies inside whatever unrelated code pumped the
loop next. Measured in the T-1435 full run as a ``CALL ERROR`` reported against
``tests/test_t1461_control_rendering.py`` -- a rendering suite that has nothing
to do with editors -- with the traceback pointing at ``ui/editor.py:4444`` and
``AttributeError: '_Owner' object has no attribute 'capture_silo_state'``.

The owner reaching the slot without the method is not hypothetical: eleven test
files build an editor over a minimal main-window double, and a real window that
is mid-teardown can be in the same shape. The slot therefore has to ask whether
the owner can still service the capture instead of assuming it.
"""

from PyQt6.QtCore import QEvent
from PyQt6.QtWidgets import QApplication

from fastprompter.ui.editor import VaultTextEdit


class _OwnerWithoutCapture:
    """A main-window double that cannot service the idle capture."""

    def __init__(self):
        self.data = {}
        self.dirty_reasons = []

    def mark_dirty(self, reason):
        self.dirty_reasons.append(reason)


class _OwnerWithCapture(_OwnerWithoutCapture):
    def __init__(self):
        super().__init__()
        self.captures = 0

    def capture_silo_state(self):
        self.captures += 1


def _editor(owner):
    w = VaultTextEdit(owner)
    w.resize(200, 80)
    return w


def _retire(widget):
    widget.deleteLater()
    QApplication.sendPostedEvents(widget, QEvent.Type.DeferredDelete)


def test_the_slot_is_silent_when_the_owner_cannot_capture(qapp):
    """The exact shape that aborted the run: an owner with no such method."""
    owner = _OwnerWithoutCapture()
    w = _editor(owner)
    try:
        w._on_idle_timeout()          # must not raise
        assert owner.dirty_reasons == [], (
            "a failed capture must not mark the profile dirty either")
    finally:
        w._idle_timer.stop()
        _retire(w)


def test_the_slot_still_captures_for_a_real_owner(qapp):
    """The guard must not turn the feature off for a production-shaped owner."""
    owner = _OwnerWithCapture()
    w = _editor(owner)
    try:
        w._on_idle_timeout()
        assert owner.captures == 1
        assert owner.dirty_reasons == ["settings"]
    finally:
        w._idle_timer.stop()
        _retire(w)


def test_an_owner_that_vanished_is_tolerated(qapp):
    """A torn-down window leaves ``main_win`` as ``None``."""
    owner = _OwnerWithoutCapture()
    w = _editor(owner)
    try:
        w.main_win = None
        w._on_idle_timeout()          # must not raise
    finally:
        w._idle_timer.stop()
        _retire(w)


def test_a_capture_that_raises_does_not_escape_the_slot(qapp):
    """A raising capture is still a slot exception, so it must not propagate.

    This is the half of the defect the T-1435 evidence did not name: the
    original code also called ``capture_silo_state`` unconditionally, so any
    exception from inside it reached the event loop the same way.
    """

    class _Exploding(_OwnerWithCapture):
        def capture_silo_state(self):
            raise RuntimeError("boom")

    owner = _Exploding()
    w = _editor(owner)
    try:
        w._on_idle_timeout()          # must not raise
    finally:
        w._idle_timer.stop()
        _retire(w)


def test_a_mark_dirty_that_raises_does_not_escape_the_slot(qapp):
    """The sibling call has the same exposure and owed the same guard.

    ``mark_dirty`` runs in the same slot and reaches the same event loop, so an
    earlier version of this fix that guarded only the capture left the second
    half of the defect in place.
    """

    class _BadBookkeeping(_OwnerWithCapture):
        def mark_dirty(self, reason):
            raise RuntimeError("bookkeeping blew up")

    owner = _BadBookkeeping()
    w = _editor(owner)
    try:
        w._on_idle_timeout()          # must not raise
        assert owner.captures == 1, "the capture itself had already succeeded"
    finally:
        w._idle_timer.stop()
        _retire(w)
