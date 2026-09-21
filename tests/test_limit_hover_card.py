"""T-1242 spec 18-20/38: the AI-limit hover card stays open to be read.

The native QToolTip could not be entered by the pointer, so moving from the
12px gauge towards the panel fired ``Leave`` and hid it instantly.  These
tests pin the replacement interaction: a real widget, a grace interval, and
no focus theft.
"""

import time

import pytest
from PyQt6.QtCore import QEvent, QPoint, QPointF, Qt
from PyQt6.QtWidgets import QApplication, QWidget

from fastprompter.ui.limit_hover_card import HIDE_GRACE_MS, LimitHoverCard


@pytest.fixture
def anchor(qapp):
    host = QWidget()
    host.resize(400, 60)
    gauge = QWidget(host)
    gauge.setGeometry(10, 10, 60, 12)     # deliberately tiny, like the real one
    host.show()
    QApplication.processEvents()
    yield gauge
    host.hide()
    host.deleteLater()
    QApplication.processEvents()


@pytest.fixture
def card(anchor):
    widget = LimitHoverCard(anchor)
    yield widget
    widget.hide_now()
    widget.deleteLater()
    QApplication.processEvents()


def _pump(ms):
    end = time.monotonic() + ms / 1000.0
    while time.monotonic() < end:
        QApplication.processEvents()
        time.sleep(0.005)


class TestVisibility:
    def test_showing_the_card_makes_it_visible(self, card):
        card.show_card("<b>usage</b>")
        assert card.isVisible()

    def test_the_card_renders_the_html_it_was_given(self, card):
        card.show_card("<b>Freebuff</b> 30 FB")
        assert "Freebuff" in card._label.text()

    def test_leaving_the_gauge_does_not_hide_the_card_immediately(self, card):
        """The defect: travelling towards the panel used to close it."""
        card.show_card("x")
        card.schedule_hide()
        assert card.isVisible(), "the grace interval must not have expired yet"

    def test_entering_the_card_before_the_grace_expires_cancels_the_hide(
            self, card):
        card.show_card("x")
        card.schedule_hide()
        card.cancel_hide()
        _pump(HIDE_GRACE_MS + 120)
        assert card.isVisible()

    def test_staying_on_the_card_keeps_it_open_for_seconds(self, card,
                                                           monkeypatch):
        card.show_card("x")
        monkeypatch.setattr(card, "_pointer_inside", lambda: True)
        card.schedule_hide()
        _pump(2000)
        assert card.isVisible(), "a card the pointer is on must stay readable"

    def test_leaving_both_surfaces_closes_it_after_the_grace(self, card,
                                                             monkeypatch):
        card.show_card("x")
        monkeypatch.setattr(card, "_pointer_inside", lambda: False)
        card.schedule_hide()
        _pump(HIDE_GRACE_MS + 250)
        assert not card.isVisible()

    def test_an_enter_event_cancels_a_pending_hide(self, card):
        card.show_card("x")
        card.schedule_hide()
        QApplication.sendEvent(card, QEvent(QEvent.Type.Enter))
        assert card._hide_timer.isActive() is False

    def test_a_leave_event_schedules_the_hide(self, card):
        card.show_card("x")
        QApplication.sendEvent(card, QEvent(QEvent.Type.Leave))
        assert card._hide_timer.isActive() is True

    def test_hide_now_is_immediate(self, card):
        card.show_card("x")
        card.hide_now()
        assert not card.isVisible()

    def test_scheduling_a_hide_on_a_closed_card_is_a_no_op(self, card):
        card.schedule_hide()
        assert card._hide_timer.isActive() is False


class TestNoFlicker:
    def test_repeated_shows_reuse_one_card(self, card):
        card.show_card("a")
        first = id(card)
        for text in ("b", "c", "d"):
            card.show_card(text)
        assert id(card) == first
        assert card.isVisible()

    def test_a_rapid_re_enter_cancels_the_pending_hide(self, card):
        card.show_card("a")
        for _ in range(5):
            card.schedule_hide()
            card.show_card("a")
        assert card.isVisible()
        assert card._hide_timer.isActive() is False


class TestLiveContent:
    def test_the_content_can_be_replaced_while_open(self, card):
        card.show_card("<b>old</b>")
        card.set_html("<b>new</b>")
        assert "new" in card._label.text()
        assert card.isVisible()

    def test_replacing_content_does_not_close_the_card(self, card):
        card.show_card("<b>old</b>")
        card.set_html("<b>" + "wide " * 200 + "</b>")
        assert card.isVisible()

    def test_the_card_width_is_bounded(self, card):
        card.show_card("<b>" + ("model-name-that-is-long " * 200) + "</b>")
        assert card.width() <= 680


class TestFocus:
    def test_the_card_never_takes_keyboard_focus(self, card):
        card.show_card("x")
        assert card.focusPolicy() == Qt.FocusPolicy.NoFocus
        assert not card.hasFocus()

    def test_escape_closes_it(self, card):
        from PyQt6.QtGui import QKeyEvent

        card.show_card("x")
        QApplication.sendEvent(card, QKeyEvent(
            QEvent.Type.KeyPress, Qt.Key.Key_Escape,
            Qt.KeyboardModifier.NoModifier))
        assert not card.isVisible()

    def test_hiding_the_owner_window_closes_the_card(self, card, anchor):
        card.show_card("x")
        anchor.window().hide()
        QApplication.processEvents()
        assert not card.isVisible()


class TestPlacement:
    def test_it_anchors_below_the_gauge(self, card, anchor):
        card.show_card("x")
        expected_top = anchor.mapToGlobal(QPoint(0, anchor.height() + 2)).y()
        screen = QApplication.screenAt(anchor.mapToGlobal(QPoint(0, 0))) \
            or QApplication.primaryScreen()
        if expected_top + card.height() <= screen.availableGeometry().bottom():
            assert card.y() == expected_top

    def test_it_stays_on_screen(self, card):
        card.show_card("x")
        screen = QApplication.primaryScreen().availableGeometry()
        assert card.x() >= screen.left()
        assert card.x() + card.width() <= screen.right() + 1


class TestGaugeIntegration:
    def _gauge(self, qapp):
        from fastprompter.ui.limit_gauges import LimitGauges
        from tests.test_usage_limits_gauge_layout import _Service, _State, _Win

        win = _Win()
        gauge = LimitGauges(win, _Service(_State([], {})))
        return win, gauge

    def test_entering_the_tiny_gauge_opens_the_card(self, qapp):
        win, gauge = self._gauge(qapp)
        try:
            QApplication.sendEvent(gauge, QEvent(QEvent.Type.Enter))
            assert gauge._hover_card.isVisible()
        finally:
            gauge.hide_hover_card(immediate=True)
            win.deleteLater()

    def test_leaving_the_gauge_only_schedules_the_hide(self, qapp):
        win, gauge = self._gauge(qapp)
        try:
            QApplication.sendEvent(gauge, QEvent(QEvent.Type.Enter))
            QApplication.sendEvent(gauge, QEvent(QEvent.Type.Leave))
            assert gauge._hover_card.isVisible(), \
                "the card must survive the trip from gauge to card"
        finally:
            gauge.hide_hover_card(immediate=True)
            win.deleteLater()

    def test_hover_never_performs_a_synchronous_provider_request(self, qapp):
        win, gauge = self._gauge(qapp)
        try:
            QApplication.sendEvent(gauge, QEvent(QEvent.Type.Enter))
            # schedule_auto is the ONLY refresh route, and it is asynchronous
            # and rate-limited; a blocking probe API is never called.
            assert gauge._service.auto_calls
            assert not hasattr(gauge._service, "probe_calls")
        finally:
            gauge.hide_hover_card(immediate=True)
            win.deleteLater()

    def test_a_fresh_snapshot_updates_an_open_card(self, qapp):
        win, gauge = self._gauge(qapp)
        try:
            QApplication.sendEvent(gauge, QEvent(QEvent.Type.Enter))
            gauge.refresh_hover_card()
            assert gauge._hover_card.isVisible()
            assert gauge._hover_card._label.text() == gauge._build_tooltip()
        finally:
            gauge.hide_hover_card(immediate=True)
            win.deleteLater()

    def test_clicking_the_gauge_closes_the_card(self, qapp):
        from PyQt6.QtGui import QMouseEvent

        win, gauge = self._gauge(qapp)
        try:
            QApplication.sendEvent(gauge, QEvent(QEvent.Type.Enter))
            event = QMouseEvent(
                QEvent.Type.MouseButtonPress, QPointF(1, 1),
                QPointF(gauge.mapToGlobal(QPoint(1, 1))),
                Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
                Qt.KeyboardModifier.NoModifier)
            QApplication.sendEvent(gauge, event)
            assert not gauge._hover_card.isVisible()
        finally:
            gauge.hide_hover_card(immediate=True)
            win.deleteLater()

    def test_rapid_re_entry_never_creates_a_second_card(self, qapp):
        win, gauge = self._gauge(qapp)
        try:
            cards = set()
            for _ in range(6):
                QApplication.sendEvent(gauge, QEvent(QEvent.Type.Enter))
                cards.add(id(gauge._hover_card))
                QApplication.sendEvent(gauge, QEvent(QEvent.Type.Leave))
            assert len(cards) == 1
        finally:
            gauge.hide_hover_card(immediate=True)
            win.deleteLater()
