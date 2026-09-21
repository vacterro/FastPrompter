"""T-1260: coverage for the abandoned-idle-timer safety net in conftest.

The net exists because an armed ``VaultTextEdit._idle_timer` whose owner cannot
service ``capture_silo_state()`` does not fail a later test -- PyQt6 turns the
exception raised inside the slot into ``qFatal()`` and the interpreter aborts.
A safety net that silently does the wrong thing is worse than none, so the
decision rule is pinned here rather than asserted in a docstring:

* an abandoned editor's timer IS disarmed, at real fixture teardown;
* a production-shaped owner (one that HAS ``capture_silo_state``) is NOT;
* unrelated ``QWidget``/``QObject`` instances are never touched;
* nothing process-wide is drained or cleared.
"""

from types import SimpleNamespace

import pytest
from _timer_isolation import abandoned_idle_timer
from PyQt6 import sip
from PyQt6.QtCore import QEvent, QObject, QTimer
from PyQt6.QtWidgets import QApplication, QWidget

from fastprompter.ui.editor import VaultTextEdit

_LONG_MS = 60_000  # only the deadline is stretched; the arming is real


def _editor(qapp, owner):
    w = VaultTextEdit(owner)
    w.resize(200, 80)
    w.setPlainText("\n".join(f"line {i}" for i in range(200)))
    w.show()
    qapp.processEvents()
    bar = w.verticalScrollBar()
    bar.setValue(bar.maximum())          # the real arming path: valueChanged
    qapp.processEvents()
    assert w._idle_timer.isActive(), "scrolling must arm the idle timer"
    return w


def _retire(widget):
    widget.deleteLater()
    # Receiver-specific delivery only. A process-wide DeferredDelete drain
    # would destroy objects another test still owns.
    QApplication.sendPostedEvents(widget, QEvent.Type.DeferredDelete)


# --------------------------------------------------------------------------
# the selection rule
# --------------------------------------------------------------------------

def test_abandoned_editor_is_selected(qapp):
    w = _editor(qapp, SimpleNamespace(data={}))
    try:
        assert abandoned_idle_timer(w) is w._idle_timer
    finally:
        w._idle_timer.stop()
        _retire(w)


def test_production_shaped_owner_is_not_selected(qapp):
    owner = SimpleNamespace(data={}, capture_silo_state=lambda: None)
    w = _editor(qapp, owner)
    try:
        assert abandoned_idle_timer(w) is None, (
            "a real main window HAS capture_silo_state -- disarming it would "
            "hide a genuine defect behind the isolation rule")
    finally:
        w._idle_timer.stop()
        _retire(w)


def test_a_disarmed_editor_is_not_selected_again(qapp):
    w = _editor(qapp, SimpleNamespace(data={}))
    try:
        w._idle_timer.stop()
        assert abandoned_idle_timer(w) is None
    finally:
        _retire(w)


@pytest.mark.parametrize("factory", [QWidget, QObject])
def test_unrelated_objects_are_never_selected(qapp, factory):
    obj = factory()
    timer = QTimer(obj)
    timer.setInterval(_LONG_MS)
    timer.start()
    try:
        assert abandoned_idle_timer(obj) is None
        assert timer.isActive(), "an unrelated object's timer must be untouched"
    finally:
        timer.stop()
        obj.deleteLater()
        QApplication.sendPostedEvents(obj, QEvent.Type.DeferredDelete)


def test_a_deleted_editor_is_skipped_without_raising(qapp):
    w = _editor(qapp, SimpleNamespace(data={}))
    w._idle_timer.stop()
    _retire(w)
    assert sip.isdeleted(w)
    assert abandoned_idle_timer(w) is None


# --------------------------------------------------------------------------
# the net itself, at real teardown
# --------------------------------------------------------------------------

_LEFT_BEHIND = {}


def test_zz_1_abandon_one_editor_and_keep_one_production_shaped(qapp):
    """Walk away from both, exactly as the eleven offending files do."""
    abandoned = _editor(qapp, SimpleNamespace(data={}))
    owned = _editor(qapp, SimpleNamespace(data={},
                                          capture_silo_state=lambda: None))
    # The real arming is a 2 s single shot; stretch only the deadline so the
    # assertion in the next test measures the safety net and not a natural
    # expiry that happened to land between the two tests.
    for widget in (abandoned, owned):
        widget._idle_timer.setInterval(_LONG_MS)
        widget._idle_timer.start()
    _LEFT_BEHIND["abandoned"] = abandoned
    _LEFT_BEHIND["owned"] = owned
    assert abandoned._idle_timer.isActive()
    assert owned._idle_timer.isActive()


def test_zz_2_only_the_abandoned_timer_was_disarmed(qapp):
    """The autouse fixture ran between these two tests. It must be surgical."""
    abandoned = _LEFT_BEHIND.pop("abandoned")
    owned = _LEFT_BEHIND.pop("owned")
    try:
        assert not abandoned._idle_timer.isActive(), (
            "the abandoned editor's idle timer survived teardown -- its "
            "timeout would qFatal() the interpreter in a later test")
        assert owned._idle_timer.isActive(), (
            "a production-shaped owner was disarmed by the isolation rule")
        assert not sip.isdeleted(abandoned), (
            "the net must stop the timer, not destroy the widget")
    finally:
        owned._idle_timer.stop()
        _retire(abandoned)
        _retire(owned)


def test_the_net_never_drains_deferred_delete_process_wide():
    """Pin the constraint the fix is not allowed to take: a bare
    ``sendPostedEvents()`` / ``sendPostedEvents(None, ...)`` destroys objects
    other tests still own."""
    import os
    here = os.path.dirname(os.path.abspath(__file__))
    for name in ("conftest.py", "_timer_isolation.py"):
        with open(os.path.join(here, name), encoding="utf-8") as fh:
            body = fh.read()
        assert "sendPostedEvents" not in body, (
            f"{name} must not deliver posted events for anything it does not "
            "own")
        assert "deleteLater" not in body
