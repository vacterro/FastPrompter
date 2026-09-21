"""No provider text may inflate the AI-limit hover card (user-reported).

A Codex probe failure arrives as vendor text of unbounded length::

    rateLimits error: {'code': -32603, 'message': 'failed to fetch codex
    rate limits: GET https://chatgpt.com/backend-api/...'}

Rendered raw, that one line stretched the panel past the screen edge and
clipped the whole reset column behind a horizontal scrollbar.  Every string
that reaches the card is bounded, and the card sizes itself so a scrollbar
never hides a column.
"""

import time

import pytest
from PyQt6.QtCore import QEvent
from PyQt6.QtWidgets import QApplication

from fastprompter.core.usage_limits.model import UsageSnapshot, UsageWindow
from fastprompter.ui.limit_gauges import LimitGauges
from fastprompter.ui.limit_hover_card import MAX_HEIGHT, MAX_WIDTH

LONG_ERROR = (
    "rateLimits error: {'code': -32603, 'message': 'failed to fetch codex "
    "rate limits: GET https://chatgpt.com/backend-api/conversation/"
    "rate_limits returned 500 after 3 retries with a very long trailing "
    "diagnostic payload that never ends'}"
)


def _gauge(qapp, snapshot=None, account=None):
    from tests.test_usage_limits_gauge_layout import (
        _account,
        _Service,
        _State,
        _Win,
    )

    account = account or _account("codex", "bounds")
    win = _Win()
    win.data["limit_accounts"] = [account.key]
    snapshots = {account.key: snapshot} if snapshot is not None else {}
    gauge = LimitGauges(win, _Service(_State([account], snapshots)))
    return win, gauge, account


def _unavailable(account, summary):
    return UsageSnapshot(
        account=account, status="UNAVAILABLE", fetched_at=time.time(),
        windows=[UsageWindow.unavailable("five_hour")],
        error_code="http_error", error_summary=summary)


class TestElision:
    def test_a_long_provider_error_is_bounded(self, qapp):
        from tests.test_usage_limits_gauge_layout import _account

        account = _account("codex", "bounds")
        win, gauge, _a = _gauge(qapp, _unavailable(account, LONG_ERROR),
                                account)
        try:
            rendered = gauge._build_tooltip()
            assert "rateLimits error" in rendered
            assert "…" in rendered
            assert "never ends" not in rendered
        finally:
            win.deleteLater()

    def test_a_short_error_is_left_alone(self, qapp):
        from tests.test_usage_limits_gauge_layout import _account

        account = _account("codex", "bounds")
        win, gauge, _a = _gauge(qapp, _unavailable(account, "not signed in"),
                                account)
        try:
            rendered = gauge._build_tooltip()
            assert "not signed in" in rendered
            assert "…" not in rendered
        finally:
            win.deleteLater()

    @pytest.mark.parametrize("limit_attr,length", [
        ("ERROR_CHARS", 72), ("NAME_CHARS", 26),
        ("LABEL_CHARS", 30), ("LIST_CHARS", 96),
    ])
    def test_every_bound_is_declared(self, limit_attr, length):
        assert getattr(LimitGauges, limit_attr) == length

    def test_elide_keeps_short_text_identical(self):
        assert LimitGauges._elide("abc", 10) == "abc"

    def test_elide_marks_what_it_cut(self):
        result = LimitGauges._elide("x" * 200, 20)
        assert len(result) == 20
        assert result.endswith("…")

    def test_elide_survives_none(self):
        assert LimitGauges._elide(None, 10) == ""


class TestCardGeometry:
    def test_the_card_never_exceeds_its_bounds_on_huge_content(self, qapp):
        from PyQt6.QtWidgets import QWidget

        from fastprompter.ui.limit_hover_card import LimitHoverCard

        host = QWidget()
        host.resize(400, 60)
        anchor = QWidget(host)
        anchor.setGeometry(10, 10, 60, 12)
        host.show()
        QApplication.processEvents()
        card = LimitHoverCard(anchor)
        try:
            card.show_card("<br>".join(
                "<b>" + "wide-column-content " * 40 + "</b>"
                for _ in range(120)))
            assert card.width() <= MAX_WIDTH
            assert card.height() <= MAX_HEIGHT
        finally:
            card.hide_now()
            card.deleteLater()
            host.hide()
            host.deleteLater()
            QApplication.processEvents()

    def test_a_scrollbar_never_steals_the_last_column(self, qapp):
        """The card reserves the scrollbar it is about to show."""
        from PyQt6.QtWidgets import QWidget

        from fastprompter.ui.limit_hover_card import LimitHoverCard

        host = QWidget()
        host.resize(400, 60)
        anchor = QWidget(host)
        anchor.setGeometry(10, 10, 60, 12)
        host.show()
        QApplication.processEvents()
        card = LimitHoverCard(anchor)
        try:
            # Tall enough to force the vertical scrollbar, narrow enough that
            # the content itself still fits horizontally.
            card.show_card("<br>".join(f"row {i}" for i in range(400)))
            QApplication.processEvents()
            bar = card._scroll.verticalScrollBar()
            assert card.height() == MAX_HEIGHT
            viewport = card._scroll.viewport().width()
            assert viewport >= card._label.sizeHint().width(), (
                "the label must not be clipped by the scrollbar")
            assert bar.sizeHint().width() > 0
        finally:
            card.hide_now()
            card.deleteLater()
            host.hide()
            host.deleteLater()
            QApplication.processEvents()


class TestRenderedWidth:
    def test_a_pathological_snapshot_still_fits_the_card(self, qapp):
        from tests.test_usage_limits_gauge_layout import _account

        account = _account("codex", "bounds")
        win, gauge, _a = _gauge(qapp, _unavailable(account, LONG_ERROR * 4),
                                account)
        try:
            QApplication.sendEvent(gauge, QEvent(QEvent.Type.Enter))
            card = gauge._hover_card
            assert card.width() <= MAX_WIDTH
        finally:
            gauge.hide_hover_card(immediate=True)
            win.deleteLater()
