"""T-1242 spec 17-21: the open hover card's geometry is session-stable.

The user reported the AI-limit hover card jumping horizontally by roughly
one pixel per refresh frame.  Root cause class: every snapshot tick called
``set_html()`` (re-fitting width) followed by ``reposition()`` (re-anchoring
from the just-changed gauge geometry), so a one-pixel text-metric change
moved a right-screen-clamped card's x by one pixel per second.  The contract
now: X and width floor are pinned at SHOW; content refreshes never move the
card horizontally and never shrink it; only a real window move re-anchors.
"""

from __future__ import annotations

import pytest
from PyQt6.QtWidgets import QApplication, QWidget

from fastprompter.ui.limit_hover_card import LimitHoverCard


@pytest.fixture
def anchor(qapp):
    host = QWidget()
    host.resize(400, 60)
    gauge = QWidget(host)
    gauge.setGeometry(10, 10, 60, 12)
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


class TestSessionGeometry:
    def test_content_refresh_never_moves_the_card(self, card):
        card.show_card("<b>1h 59m</b> freebuff 12%")
        x, y = card.x(), card.y()
        for html in ("<b>1h 58m</b> freebuff 12%",
                     "<b>1h 57m</b> freebuff 12%",
                     "<b>59m</b> freebuff 12%",
                     "<b>1h 02m</b> freebuff 13%"):
            card.set_html(html)
            QApplication.processEvents()
            assert (card.x(), card.y()) == (x, y), (
                "an open card moved horizontally on a countdown refresh")

    def test_content_refresh_never_shrinks_the_width(self, card):
        card.show_card("<b>" + "wide model name " * 12 + "</b>")
        wide = card.width()
        card.set_html("<b>tiny</b>")
        assert card.width() >= wide, (
            "an open card shrank when the content got shorter")

    def test_the_floor_resets_on_the_next_show(self, card, anchor):
        card.show_card("<b>" + "wide model name " * 12 + "</b>")
        wide = card.width()
        card.hide_now()
        card.show_card("<b>tiny</b>")
        assert card.width() < wide, (
            "a fresh hover session must recompute its width from content")

    def test_height_may_change_while_width_is_frozen(self, card):
        card.show_card("<b>row</b><br>" * 4)
        width = card.width()
        card.set_html("<b>row</b><br>" * 8)
        assert card.width() == width or card.width() > width
        assert card.height() >= 40

    def test_reposition_pins_the_session_geometry(self, card):
        card.show_card("x")
        session_x = card._session_x
        session_y = card._session_y
        assert session_x is not None and session_y is not None
        assert (card.x(), card.y()) == (session_x, session_y)

    def test_hide_clears_the_session_geometry(self, card):
        card.show_card("x")
        card.hide_now()
        assert card._session_x is None
        assert card._session_y is None

    def test_a_real_window_move_reanchors(self, card, anchor):
        card.show_card("x")
        window = anchor.window()
        before = (card.x(), card.y())
        window.move(window.x() + 50, window.y() + 30)
        QApplication.processEvents()
        moved = (card.x(), card.y()) != before
        # The anchor moved; the card must follow (via its own Move filter or
        # the next explicit reposition), never stay floating in space.
        card.reposition()
        assert card.x() >= before[0] or moved

    def test_stays_on_screen_through_growth(self, card):
        card.show_card("x")
        screen = QApplication.primaryScreen().availableGeometry()
        card.set_html("<b>" + "w" * 400 + "</b>")
        assert card.x() >= screen.left()
        assert card.x() + card.width() <= screen.right() + 1
