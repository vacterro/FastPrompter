"""T-1449: the Shift reveal must land on the PRESS, not on the release.

The operator's report: with the limit-meter hover card open, holding Shift
reveals the accounts the header filters hide -- but only once Shift comes
back UP.  Pressing it did nothing visible, so the gesture read as broken and
the reveal arrived as the user was already letting go.

The cause is the modifier SOURCE, not the delivery.  The card's event filter
catches KeyPress and KeyRelease of ``Key_Shift`` and asks the gauge to
re-render (``LimitHoverCard.eventFilter`` -> ``refresh_hover_card``), but the
gauge answers the question with ``QApplication.keyboardModifiers()``.  That
call is a mirror of the LAST event Qt processed -- the repository documents
the property itself in ``tests/test_line_drag_autoscroll.py`` and
``tests/test_new_empty_silos.py`` -- and Windows marks a modifier's keydown
with the PRE-press bit and its keyup with the PRE-release one.  So the
ambient answer is one event behind exactly when the event itself is what
changes it: the reveal appeared on the keyup.

These controls own the modifier source instead of inheriting it, so the
gesture is pinned without any ambient dependency.  ``NoModifier`` on the
press and ``ShiftModifier`` on the release is the Windows convention, spelled
out here rather than left implicit.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PyQt6.QtWidgets")

from PyQt6.QtCore import QEvent, Qt  # noqa: E402
from PyQt6.QtGui import QKeyEvent  # noqa: E402
from PyQt6.QtWidgets import QApplication, QWidget  # noqa: E402

from tests.test_t1441_hover_compact import _retire, _text  # noqa: E402
from tests.test_usage_limits_gauge_layout import (  # noqa: E402
    _account,
    _build,
    _codex,
)
from tests.test_usage_limits_gauge_layout import (  # noqa: E402
    qapp as qapp,  # noqa: F401
)

#: The UNPATCHED mirror accessor.  ``_ambient`` replaces the class attribute
#: for the duration of a test, and this module's own teardown sentinel must
#: not read its own patch back.
_REAL_KEYBOARD_MODIFIERS = QApplication.keyboardModifiers


def _ambient(monkeypatch, value):
    """Pin Qt's process-wide modifier mirror to ``value``.

    Production reads it through ``QApplication.keyboardModifiers()``; patching
    the class attribute is how ``tests/test_usage_limits_hide_zero.py``
    already owns this source.
    """
    monkeypatch.setattr(QApplication, "keyboardModifiers", staticmethod(lambda: value))


@pytest.fixture(autouse=True)
def _restore_ambient_modifiers():
    """No test here may leave a modifier latched for the next module.

    A delivered Shift event updates the PROCESS-WIDE mirror Qt keeps, and this
    module delivers two of them per control.  ``tests/test_line_drag_autoscroll.py``
    documents both the leak and the cure.  Its cure is a synthetic MOUSE event,
    which this module cannot use: Shift is only ever delivered here to a
    ``Qt.Tool`` overlay and its anchor, and the latch survived every mouse
    release/move tried.  What clears it is another key event carrying the
    current state, so one plain synthetic letter press -- a key no binding
    here or in the mirror cares about -- puts the mirror back to NoModifier.

    Without this, ``test_t1441_hover_compact`` -- which asserts the card opens
    FILTERED -- inherited a held Shift and failed only when the two files
    shared a process.
    """
    yield

    scratch = QWidget()
    try:
        for _ in range(3):
            QApplication.sendEvent(scratch, QKeyEvent(
                QEvent.Type.KeyPress, Qt.Key.Key_A,
                Qt.KeyboardModifier.NoModifier))
            if _REAL_KEYBOARD_MODIFIERS() == Qt.KeyboardModifier.NoModifier:
                break
    finally:
        scratch.deleteLater()
    assert _REAL_KEYBOARD_MODIFIERS() == Qt.KeyboardModifier.NoModifier, (
        "this module left a modifier latched into the shared QApplication")


def _filtered_gauge(qapp, count=3):
    """Every account is 0%, so the filter hides exactly all of them."""
    accounts = [_account("codex", f"c{i}") for i in range(count)]
    snapshots = {a.key: _codex(a, five=0, weekly=0) for a in accounts}
    gauge = _build(qapp, accounts, snapshots,
                   limit_gauges_hide_unusable_5h="True")
    card = gauge.hover_card()
    QApplication.sendEvent(gauge, QEvent(QEvent.Type.Enter))
    return accounts, gauge, card


def _key(gauge, kind, modifiers):
    """Deliver one key event the way the live app does: to the focused window.

    The card never takes focus (``Qt.Tool``, ``WA_ShowWithoutActivating``), so
    in the real application the press lands on the main window and reaches the
    card only because the card installed itself as an application event
    filter.
    """
    QApplication.sendEvent(
        gauge.window(),
        QKeyEvent(kind, Qt.Key.Key_Shift, modifiers))


def _expanded(card) -> bool:
    return "Shift held" in _text(card._label.text())


class TestTheRevealLandsOnThePress:
    def test_a_shift_press_expands_an_open_card_at_once(self, qapp, monkeypatch):
        """Windows marks the keydown with the PRE-press bit: no Shift there.

        The ambient mirror is pinned to the same stale answer, because that is
        exactly the state the live app is in while the press is being
        delivered.
        """
        accounts, gauge, card = _filtered_gauge(qapp)
        try:
            assert not _expanded(card), "the card opened unfiltered"
            _ambient(monkeypatch, Qt.KeyboardModifier.NoModifier)
            _key(gauge, QEvent.Type.KeyPress, Qt.KeyboardModifier.NoModifier)
            text = _text(card._label.text())
            assert "Shift held" in text, (
                "the Shift PRESS did not reveal the filtered accounts; the "
                "reveal is waiting for the key to come back up again")
            for account in accounts:
                assert account.display_name in text, (
                    f"{account.display_name} stayed hidden under Shift")
        finally:
            card.hide_now()
            _retire(gauge)

    def test_the_ambient_state_cannot_answer_for_the_press(
            self, qapp, monkeypatch):
        """RED CONTROL: the ambient answer alone is one event behind.

        With the ambient mirror still reporting the pre-press state, the
        re-render must not read it.  This is the defect stated directly: the
        gesture is defined by the event, not by the global that lags it.
        """
        _accounts, gauge, card = _filtered_gauge(qapp)
        try:
            _ambient(monkeypatch, Qt.KeyboardModifier.NoModifier)
            assert gauge._shift_held() is False, (
                "the fixture failed to pin the ambient source")
            _key(gauge, QEvent.Type.KeyPress, Qt.KeyboardModifier.NoModifier)
            assert _expanded(card), (
                "the reveal was decided by QApplication.keyboardModifiers() "
                "instead of by the press that changes it")
        finally:
            card.hide_now()
            _retire(gauge)

    def test_a_shift_release_takes_the_reveal_back(self, qapp, monkeypatch):
        """The mirror still says Shift during the keyup; the card must not.

        Windows marks the keyup with the PRE-release bit, so the ambient
        source reports Shift held while the key is already coming up.  The
        sequence is authoritative: after a release, Shift is up.
        """
        accounts, gauge, card = _filtered_gauge(qapp)
        try:
            _ambient(monkeypatch, Qt.KeyboardModifier.NoModifier)
            _key(gauge, QEvent.Type.KeyPress, Qt.KeyboardModifier.NoModifier)
            assert _expanded(card)
            _ambient(monkeypatch, Qt.KeyboardModifier.ShiftModifier)
            _key(gauge, QEvent.Type.KeyRelease, Qt.KeyboardModifier.ShiftModifier)
            text = _text(card._label.text())
            assert "Shift held" not in text, (
                "the reveal outlived the key: a released Shift still showed "
                "the unfiltered roster")
            for account in accounts:
                assert account.display_name not in text
        finally:
            card.hide_now()
            _retire(gauge)

    def test_the_reveal_does_not_outlive_the_key_across_sessions(
            self, qapp, monkeypatch):
        """Closing and re-hovering must ask the ambient source again."""
        _accounts, gauge, card = _filtered_gauge(qapp)
        try:
            _ambient(monkeypatch, Qt.KeyboardModifier.NoModifier)
            _key(gauge, QEvent.Type.KeyPress, Qt.KeyboardModifier.NoModifier)
            assert _expanded(card)
            _key(gauge, QEvent.Type.KeyRelease, Qt.KeyboardModifier.NoModifier)
            card.hide_now()
            QApplication.sendEvent(gauge, QEvent(QEvent.Type.Enter))
            assert not _expanded(card), (
                "a finished Shift gesture latched the card into the "
                "unfiltered view")
        finally:
            card.hide_now()
            _retire(gauge)


class TestTheHoverOpenRouteIsUnchanged:
    def test_shift_held_at_hover_time_still_reveals_everything(
            self, qapp, monkeypatch):
        """No key event is in flight, so the ambient source is current here."""
        accounts, gauge, card = _filtered_gauge(qapp)
        try:
            _ambient(monkeypatch, Qt.KeyboardModifier.ShiftModifier)
            card.hide_now()
            QApplication.sendEvent(gauge, QEvent(QEvent.Type.Enter))
            text = _text(card._label.text())
            assert "Shift held" in text
            for account in accounts:
                assert account.display_name in text
        finally:
            card.hide_now()
            _retire(gauge)

    def test_a_card_whose_anchor_cannot_refresh_still_ignores_the_key(self, qapp):
        """The reset-queue card shares this class and has no reveal to drive."""
        from PyQt6.QtCore import QCoreApplication
        from PyQt6.QtWidgets import QLabel

        from fastprompter.ui.limit_hover_card import LimitHoverCard

        label = QLabel("reset queue")
        card = LimitHoverCard(label)
        try:
            card.show_card("<b>1h 2m</b>")
            before = card._label.text()
            card.eventFilter(card, QKeyEvent(
                QEvent.Type.KeyPress, Qt.Key.Key_Shift,
                Qt.KeyboardModifier.NoModifier))
            assert card._label.text() == before, (
                "a card with no reveal hook re-rendered on a Shift press")
        finally:
            card.hide_now()
            card._anchor = None
            card.deleteLater()
            label.deleteLater()
            QCoreApplication.sendPostedEvents(
                None, QEvent.Type.DeferredDelete.value)
