"""T-1242 spec 18-20/38: the AI-limit hover card stays open to be read.

The native QToolTip could not be entered by the pointer, so moving from the
12px gauge towards the panel fired ``Leave`` and hid it instantly.  These
tests pin the replacement interaction: a real widget, a grace interval, and
no focus theft.
"""

import time

import pytest
from PyQt6.QtCore import QEvent, QPoint, QPointF, Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QApplication, QWidget

from fastprompter.ui.limit_hover_card import HIDE_GRACE_MS, LimitHoverCard


def native_tooltip_visible(widget) -> bool:
    """Ask Qt to paint the native tooltip for this widget; report if it did.

    The real delivery path: Qt sends a ``QHelpEvent(ToolTip)`` to the widget
    under the cursor, and ``QWidget::event()`` paints the popup.  A widget
    that CONSUMES the event never gets one, so this is the observable proof
    that a second presentation cannot appear.
    """
    from PyQt6.QtGui import QHelpEvent
    from PyQt6.QtWidgets import QToolTip

    QToolTip.hideText()
    QApplication.processEvents()
    pos = widget.mapToGlobal(widget.rect().topLeft())
    QApplication.sendEvent(
        widget, QHelpEvent(QEvent.Type.ToolTip, QPoint(pos), QPoint(pos)))
    return QToolTip.isVisible()


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

class TestTransactionalOpen:
    """T-1481: one bounded open transaction, no silent native fallback."""

    def _gauge(self, qapp):
        return TestGaugeIntegration()._gauge(qapp)

    def test_duplicate_enter_and_tooltip_rebuild_once(self, qapp):
        win, gauge = self._gauge(qapp)
        try:
            calls = []
            original = gauge._build_tooltip

            def counted(*args, **kwargs):
                calls.append(1)
                return original(*args, **kwargs)

            gauge._build_tooltip = counted
            QApplication.sendEvent(gauge, QEvent(QEvent.Type.Enter))
            QApplication.sendEvent(gauge, QEvent(QEvent.Type.ToolTip))
            assert len(calls) == 1, "duplicate Enter/ToolTip rebuilt the card"
        finally:
            gauge.hide_hover_card(immediate=True)
            win.deleteLater()

    def test_tooltip_failure_is_diagnosed_without_native_fallback(
            self, qapp, monkeypatch):
        win, gauge = self._gauge(qapp)
        try:
            def boom(**kwargs):
                raise RuntimeError("tooltip boom")

            monkeypatch.setattr(gauge, "_build_tooltip", boom)
            QApplication.sendEvent(gauge, QEvent(QEvent.Type.Enter))
            assert gauge._last_hover_error.startswith("build_tooltip")
            assert gauge._hover_open_failed is True
            assert not gauge._hover_card.isVisible()
            # No native fallback.  The description stays on the widget for
            # assistive technology, but Qt never paints a popup beside the
            # card -- the tooltip EVENT is what is consumed.
            assert gauge.toolTip() != ""
            assert not native_tooltip_visible(gauge)
        finally:
            gauge.hide_hover_card(immediate=True)
            win.deleteLater()

    def test_schedule_failure_is_diagnosed(self, qapp, monkeypatch):
        win, gauge = self._gauge(qapp)
        try:
            def boom(*args, **kwargs):
                raise RuntimeError("schedule boom")

            monkeypatch.setattr(gauge._service, "schedule_auto", boom)
            QApplication.sendEvent(gauge, QEvent(QEvent.Type.Enter))
            assert gauge._last_hover_error.startswith("schedule_auto")
            assert gauge._hover_open_failed is True
            assert not gauge._hover_card.isVisible()
        finally:
            gauge.hide_hover_card(immediate=True)
            win.deleteLater()

class TestFocusLockSafety:
    class _Main:
        def __init__(self):
            self.count = 0

        def _increment_focus_lock(self):
            self.count += 1

        def _decrement_focus_lock(self):
            self.count = max(0, self.count - 1)

    def test_failed_show_releases_focus_lock(self, anchor, monkeypatch):
        main = self._Main()
        anchor.main_win = main
        card = LimitHoverCard(anchor)
        try:
            def boom():
                raise RuntimeError("show boom")

            monkeypatch.setattr(card, "show", boom)
            with pytest.raises(RuntimeError):
                card.show_card("x")
            assert main.count == 0
            assert card._focus_lock_taken is False
        finally:
            card.deleteLater()
            QApplication.processEvents()

    def test_hide_releases_one_focus_lock_once(self, anchor):
        main = self._Main()
        anchor.main_win = main
        card = LimitHoverCard(anchor)
        try:
            card.show_card("x")
            assert main.count == 1
            card.hide_now()
            card.hide_now()
            assert main.count == 0
        finally:
            card.deleteLater()
            QApplication.processEvents()

class TestGoldenPixelBorder:
    def test_all_edges_are_golden_and_continuous(self, card):
        card.show_card("x")
        QApplication.processEvents()
        image = card.grab().toImage()
        golden = QColor("#D9B340")
        assert image.pixelColor(0, 0) == golden
        assert image.pixelColor(image.width() - 1, 0) == golden
        assert image.pixelColor(0, image.height() - 1) == golden
        assert image.pixelColor(image.width() - 1,
                                image.height() - 1) == golden
        for x in range(image.width()):
            assert image.pixelColor(x, 0) == golden
            assert image.pixelColor(x, image.height() - 1) == golden
        for y in range(image.height()):
            assert image.pixelColor(0, y) == golden
            assert image.pixelColor(image.width() - 1, y) == golden

    def test_two_pixel_thickness(self, card):
        card.show_card("x")
        QApplication.processEvents()
        image = card.grab().toImage()
        golden = QColor("#D9B340")
        assert image.pixelColor(1, 1) == golden
        assert image.pixelColor(2, 2) != golden

    def test_hide_removes_the_application_filter(self, card):
        card.show_card("x")
        assert card._app_filter_installed is True
        card.hide_now()
        assert card._app_filter_installed is False


class TestTooltipOwnership:
    """T-1482: one hovered surface, one tooltip owner, one presentation."""

    def _gauge(self, qapp):
        return TestGaugeIntegration()._gauge(qapp)

    @staticmethod
    def _visible_cards():
        return LimitHoverCard.visible_cards()

    def test_the_gauge_hover_shows_exactly_one_card(self, qapp):
        win, gauge = self._gauge(qapp)
        try:
            QApplication.sendEvent(gauge, QEvent(QEvent.Type.Enter))
            assert gauge._hover_card.isVisible()
            assert len(self._visible_cards()) == 1
        finally:
            gauge.hide_hover_card(immediate=True)
            win.deleteLater()

    def test_no_native_tooltip_appears_beside_the_gauge_card(self, qapp):
        win, gauge = self._gauge(qapp)
        try:
            QApplication.sendEvent(gauge, QEvent(QEvent.Type.Enter))
            assert gauge._hover_card.isVisible()
            assert not native_tooltip_visible(gauge)
        finally:
            gauge.hide_hover_card(immediate=True)
            win.deleteLater()

    def test_a_delayed_tooltip_event_paints_no_native_popup(self, qapp):
        """The event Qt delivers after the hover delay must stay consumed."""
        win, gauge = self._gauge(qapp)
        try:
            QApplication.sendEvent(gauge, QEvent(QEvent.Type.Enter))
            QApplication.sendEvent(gauge, QEvent(QEvent.Type.ToolTip))
            assert gauge._hover_card.isVisible()
            assert len(self._visible_cards()) == 1
            assert not native_tooltip_visible(gauge)
        finally:
            gauge.hide_hover_card(immediate=True)
            win.deleteLater()

    def test_a_provider_refresh_creates_no_second_popup(self, qapp):
        win, gauge = self._gauge(qapp)
        try:
            QApplication.sendEvent(gauge, QEvent(QEvent.Type.Enter))
            gauge._on_data()
            gauge.refresh_hover_card()
            assert len(self._visible_cards()) == 1
            assert gauge._hover_card.isVisible()
        finally:
            gauge.hide_hover_card(immediate=True)
            win.deleteLater()

    def test_the_gauge_description_stays_readable_by_assistive_technology(
            self, qapp):
        """The card owns the VISUAL, never the description.

        Pre-fix the gauge cleared its tooltip text to keep the native popup
        away -- which also erased the accessible description.  The repair
        keeps the text and consumes the tooltip EVENT instead, so the
        description must survive the card open AND a data refresh.
        """
        win, gauge = self._gauge(qapp)
        try:
            assert gauge.toolTip() != ""
            assert gauge.accessibleDescription() != ""
            QApplication.sendEvent(gauge, QEvent(QEvent.Type.Enter))
            assert gauge._hover_card.isVisible()
            assert gauge.toolTip() != "", \
                "the card took the hover and took the description with it"
            assert gauge.accessibleDescription() != ""
            gauge._on_data()
            assert gauge.toolTip() != "", \
                "a data refresh wiped the accessible description"
            assert gauge.accessibleDescription() != ""
            assert not native_tooltip_visible(gauge)
        finally:
            gauge.hide_hover_card(immediate=True)
            win.deleteLater()

    def test_an_unrelated_button_tooltip_still_works(self, qapp):
        """Native tooltips elsewhere in the app are NOT disabled."""
        from PyQt6.QtWidgets import QPushButton

        button = QPushButton("plain")
        button.setToolTip("native button hint")
        button.show()
        try:
            assert native_tooltip_visible(button)
        finally:
            button.hide()
            button.deleteLater()

    def test_opening_a_second_card_retires_the_first(self, qapp, anchor):
        from PyQt6.QtWidgets import QWidget

        other = QWidget()
        other.resize(100, 20)
        other.show()
        first = LimitHoverCard(anchor)
        second = LimitHoverCard(other)
        try:
            first.show_card("a")
            assert first.isVisible()
            second.show_card("b")
            assert second.isVisible()
            assert not first.isVisible(), \
                "two cards open at once is the double-presentation defect"
        finally:
            first.hide_now()
            second.hide_now()
            other.deleteLater()

    def test_retiring_a_card_releases_its_focus_lock(self, qapp, anchor):
        from PyQt6.QtWidgets import QWidget

        main = TestFocusLockSafety._Main()
        anchor.main_win = main
        other = QWidget()
        other.resize(100, 20)
        other.show()
        first = LimitHoverCard(anchor)
        second = LimitHoverCard(other)
        try:
            first.show_card("a")
            assert main.count == 1
            second.show_card("b")
            assert main.count == 0, "a retired card leaked its focus lock"
        finally:
            first.hide_now()
            second.hide_now()
            other.deleteLater()

    def test_the_hover_sound_fires_once_per_session(self, qapp, anchor,
                                                    monkeypatch):
        import fastprompter.ui.appearance_sounds as sounds

        calls = []
        monkeypatch.setattr(sounds, "emit_hover_card_show",
                            lambda *a, **kw: calls.append(1))
        card = LimitHoverCard(anchor)
        try:
            card.show_card("x")
            card.set_html("y")            # per-second content refresh
            card.show_card("z")           # re-show of an open card
            assert len(calls) == 1, "the hover sound repeated inside one session"
        finally:
            card.hide_now()
            card.deleteLater()
            QApplication.processEvents()
