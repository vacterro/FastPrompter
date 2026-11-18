"""T-1445: ordinary hover must show the FULL detail table, as it did before T-1441.

T-1441 replaced the hover view with a compact per-provider summary and kept
the dense table behind a second pointer move (enter the card).  That trade was
wrong in use: the operator reported that the limits "show almost no
information" on hover -- four provider rows of percentages and a footnote --
so the information the card exists for was no longer where the gesture puts
the pointer.  The compact view is gone; `_show_hover_card` renders
``_build_tooltip`` directly again, and ``LimitHoverCard`` has no
compact/expand state left.

What these tests pin, so this cannot silently regress a second time:

* hover opens the detail table itself -- every account row is on screen
  immediately, with no second gesture;
* the detail view still carries what the compact summary dropped (per-window
  breakdown, per-account identity, pool labels), i.e. the revert restored
  information and did not merely relabel a summary;
* the card's size contract is unchanged: it still fits its content inside
  the documented caps instead of running off the screen;
* refresh keeps the open card current without moving it.

The reported-window size note: the detail table at twelve accounts is the
size the operator asked for.  It is bounded by ``MAX_WIDTH``/``MAX_HEIGHT``
in the card (and scrolls inside those caps), not by dropping rows.
"""

from __future__ import annotations

import os
import re
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from fastprompter.core.usage_limits.model import (  # noqa: E402
    OK,
    UsageSnapshot,
    UsageWindow,
)

pytest.importorskip("PyQt6.QtWidgets")

from PyQt6.QtCore import QEvent  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from tests.test_usage_limits_gauge_layout import (  # noqa: E402
    _account,
    _antigravity,
    _build,
    _codex,
    _snapshot,
)
from tests.test_usage_limits_gauge_layout import (
    qapp as qapp,  # noqa: F401
)

#: The window the operator reported the defect at.
REPORTED_WINDOW = (1033, 679)


def _text(html_text: str) -> str:
    return re.sub(r"<[^>]+>", " ", html_text)


def _roster(count, provider="claude"):
    accounts = [_account(provider, f"a{i}") for i in range(count)]
    return accounts, {a.key: _codex(a, five=60, weekly=80) for a in accounts}


def _retire(gauge):
    """Tear a gauge and its hover card down completely.

    A `LimitHoverCard` is a `Qt.Tool`, so Qt makes it TOP-LEVEL and it is never
    destroyed with the widget it annotates. `deleteLater()` on the window alone
    is therefore not enough: the cards left alive by this module crashed a
    later `QToolTip` paint with 0xc0000374, reproducibly, as soon as this file
    and `test_usage_limits_gauge_layout` ran in the same process. The card is
    hidden, unlinked from its anchor and deleted here, and the deferred deletes
    are drained because a test that never spins the event loop would leave both
    objects alive.
    """
    from PyQt6.QtCore import QCoreApplication

    card = getattr(gauge, "_hover_card", None)
    if card is not None:
        try:
            card.hide_now()
            card._anchor = None
            card.deleteLater()
        except RuntimeError:
            pass
        gauge._hover_card = None
    gauge.main_win.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)


class TestHoverShowsTheDetailTable:
    """The first gesture must deliver the whole table."""

    @pytest.mark.parametrize("count", [1, 4, 8, 12])
    def test_hover_opens_the_detail_view_not_a_summary(self, qapp, count):
        accounts, snapshots = _roster(count)
        gauge = _build(qapp, accounts, snapshots,
                       limit_gauges_show_labels="True")
        try:
            card = gauge.hover_card()
            QApplication.sendEvent(gauge, QEvent(QEvent.Type.Enter))
            assert card.isVisible()
            # Byte-for-byte the detail builder: this is the whole contract of
            # the revert, and it is checked against the builder on the same
            # snapshot so a live countdown cannot make it flaky.
            assert card._label.text() == gauge._build_tooltip(), (
                f"hover at {count} accounts did not open the detail table")
        finally:
            _retire(gauge)

    def test_the_detail_view_enumerates_every_account(self, qapp):
        """One row per account -- the thing the compact summary collapsed."""
        accounts, snapshots = _roster(6)
        gauge = _build(qapp, accounts, snapshots)
        try:
            detail = _text(gauge._build_tooltip())
            for account in accounts:
                assert account.display_name in detail, (
                    f"{account.display_name} is missing from the detail view")
        finally:
            _retire(gauge)

    def test_the_detail_view_is_richer_than_the_old_summary(self, qapp):
        """The revert restored information, not just a different heading.

        The compact summary had exactly one row per provider and no
        per-window reset column.  The restored view must have strictly more
        rows than providers and must render EACH window separately -- the
        window names come from ``_win_label``, which calls Claude's five-hour
        bucket "Session" because that is what /usage calls it.
        """
        accounts, snapshots = _roster(5)
        gauge = _build(qapp, accounts, snapshots)
        try:
            detail = gauge._build_tooltip()
            assert detail.count("<tr>") > 1, (
                "the detail view collapsed to a single row per provider")
            text = _text(detail)
            # Both windows of every account, named as the header names them.
            assert "Session" in text and "weekly" in text, (
                "the restored detail view lost its per-window breakdown")
            assert text.count("weekly") >= len(accounts), (
                "not every account got its own weekly row")
        finally:
            _retire(gauge)

    def test_twelve_accounts_are_all_present_and_the_card_stays_capped(
            self, qapp):
        """No row is dropped to make the card small.

        T-1441 dropped rows to shrink the card.  The card's own contract is to
        CLIP with a scrollbar instead (``MAX_WIDTH``/``MAX_HEIGHT``), so a
        twelve-account table must show every account and still fit on screen.
        """
        accounts, snapshots = _roster(12)
        gauge = _build(qapp, accounts, snapshots,
                       limit_gauges_show_labels="True")
        try:
            from fastprompter.ui.limit_hover_card import (
                MAX_HEIGHT,
                MAX_WIDTH,
            )

            card = gauge.hover_card()
            card.set_html(gauge._build_tooltip())
            assert card.width() <= MAX_WIDTH, (
                f"card is {card.width()}px wide, past the {MAX_WIDTH}px cap")
            assert card.height() <= MAX_HEIGHT, (
                f"card is {card.height()}px tall, past the {MAX_HEIGHT}px cap")
            detail = _text(card._label.text())
            assert detail.count("×12") or all(
                account.display_name in detail for account in accounts), (
                "accounts were dropped from the twelve-account detail view")
            card.hide_now()
        finally:
            _retire(gauge)


class TestHoverKeepsIdentity:
    """Whatever opens on hover must name providers, accounts and states."""

    def test_every_account_is_named_with_its_windows(self, qapp):
        """The detail table identifies ACCOUNTS, not provider rollups.

        Pre-T-1441 behaviour, and the thing the compact summary replaced: a
        per-account header followed by that account's own window rows.  The
        provider name only appears on a shared-pool banner, so asserting on
        provider labels here would be asserting the summary's shape back in.
        """
        claude = _account("claude", "cl")
        codex = _account("codex", "c1")
        ag = _account("antigravity", "ag")
        snapshots = {claude.key: _codex(claude), codex.key: _codex(codex),
                     ag.key: _antigravity(ag)}
        gauge = _build(qapp, [claude, codex, ag], snapshots)
        try:
            detail = _text(gauge._build_tooltip())
            for account in (claude, codex, ag):
                assert account.display_name in detail, (
                    f"{account.display_name} is missing from the detail view")
            assert "Session" in detail or "5h" in detail
            assert "weekly" in detail
        finally:
            _retire(gauge)

    def test_a_passed_reset_is_reported_not_called_unprobed(self, qapp):
        """Stale-and-refilling is not the same state as never probed."""
        account = _account("codex", "elapsed")
        now = time.time()
        elapsed = UsageSnapshot(
            account=account, status=OK, fetched_at=now,
            windows=[UsageWindow("five_hour", 300, True, 100, 0, now - 1)])
        gauge = _build(qapp, [account], {account.key: elapsed})
        try:
            detail = _text(gauge._build_tooltip())
            assert "Reset time passed" in detail
            assert "not probed yet" not in detail
        finally:
            _retire(gauge)

    def test_an_empty_roster_still_explains_itself(self, qapp):
        gauge = _build(qapp, [], {})
        try:
            assert "no accounts selected" in _text(gauge._build_tooltip())
        finally:
            _retire(gauge)

    def test_antigravity_pools_keep_their_names(self, qapp):
        """The revert must not reintroduce generic Pool 1 / Pool 2 labels."""
        ag = _account("antigravity", "ag")
        now = time.time()
        windows = [
            UsageWindow(key="five_hour@pool0", duration_minutes=300,
                        available=True, used_percent=50.0,
                        remaining_percent=50.0, resets_at_epoch=now + 7200,
                        group="pool0", group_label="Pool 1"),
            UsageWindow(key="weekly@pool0", duration_minutes=10080,
                        available=True, used_percent=42.0,
                        remaining_percent=58.0, resets_at_epoch=now + 86400,
                        group="pool0", group_label="Pool 1"),
        ]
        snapshot = UsageSnapshot(account=ag, status=OK, windows=windows,
                                 fetched_at=now)
        gauge = _build(qapp, [ag], {ag.key: snapshot})
        try:
            detail = gauge._build_tooltip()
            assert "Pool 1" not in detail
            assert "Gemini" in detail
        finally:
            _retire(gauge)


class TestNoCompactMachineryRemains:
    """The removed state must stay removed, not linger as a second code path."""

    def test_the_card_has_no_compact_or_expand_state(self, qapp):
        accounts, snapshots = _roster(3)
        gauge = _build(qapp, accounts, snapshots)
        try:
            card = gauge.hover_card()
            for removed in ("_detail_html", "_expanded"):
                assert not hasattr(card, removed), (
                    f"{removed} is back on the card; there must be one view")
            assert not hasattr(card, "expand") or not callable(
                getattr(card, "expand", None)), (
                "LimitHoverCard.expand is back; hover must not need a "
                "second gesture to show the table")
        finally:
            _retire(gauge)

    def test_the_gauge_no_longer_builds_a_hover_summary(self, qapp):
        accounts, snapshots = _roster(3)
        gauge = _build(qapp, accounts, snapshots)
        try:
            assert not hasattr(gauge, "_build_hover_summary"), (
                "_build_hover_summary survived the revert; a dead compact "
                "renderer is a second contract waiting to be switched on")
        finally:
            _retire(gauge)

    def test_entering_the_card_does_not_change_what_it_says(self, qapp):
        """With one view there is nothing for enter/leave to swap."""
        accounts, snapshots = _roster(4)
        gauge = _build(qapp, accounts, snapshots)
        try:
            card = gauge.hover_card()
            QApplication.sendEvent(gauge, QEvent(QEvent.Type.Enter))
            before = card._label.text()
            QApplication.sendEvent(card, QEvent(QEvent.Type.Enter))
            assert card._label.text() == before, (
                "entering the card re-rendered it; hover already showed the "
                "full table, so there is nothing to promote")
            card.hide_now()
        finally:
            _retire(gauge)


class TestRefreshKeepsTheOpenViewCurrent:
    """A per-second refresh must update the table without moving the card."""

    def test_refresh_still_renders_the_detail_view(self, qapp):
        accounts, snapshots = _roster(4)
        gauge = _build(qapp, accounts, snapshots)
        try:
            card = gauge.hover_card()
            QApplication.sendEvent(gauge, QEvent(QEvent.Type.Enter))
            gauge.refresh_hover_card()
            assert card._label.text() == gauge._build_tooltip(), (
                "the refresh downgraded the open card away from the table")
            card.hide_now()
        finally:
            _retire(gauge)

    def test_refresh_picks_up_new_numbers(self, qapp):
        """The refreshed table must not be a snapshot older than the card."""
        account = _account("codex", "c1")
        now = time.time()
        fresh = _snapshot(account, [
            UsageWindow("five_hour", 300, True, 100, 0, now + 7200),
            UsageWindow("weekly", 10080, True, 100, 0, now + 86400)])
        gauge = _build(qapp, [account], {account.key: fresh})
        try:
            card = gauge.hover_card()
            QApplication.sendEvent(gauge, QEvent(QEvent.Type.Enter))
            stale = card._label.text()
            then = time.time()
            # A reset an HOUR later: the countdown must change, so a stale
            # render is distinguishable without depending on a rounding edge.
            later = _snapshot(account, [
                UsageWindow("five_hour", 300, True, 100, 0, then + 10800),
                UsageWindow("weekly", 10080, True, 100, 0, then + 90000)])
            gauge._service._state.snapshots[account.key] = later
            gauge.refresh_hover_card()
            assert card._label.text() != stale, (
                "the refresh replayed the pre-refresh table")
            card.hide_now()
        finally:
            _retire(gauge)


class TestShiftStillRevealsEveryAccount:
    """Shift is the "show me everything" modifier and must not have moved.

    The operator reported this alongside the compact-summary complaint: while
    the card was open, holding Shift used to reveal the accounts the header
    filters hide (an exhausted 5h window, 0% usage).  That path lives in
    ``LimitHoverCard.eventFilter`` -> ``refresh_hover_card`` -> the
    ``ignore_filters`` branch of ``_build_tooltip``, and it is pinned here so a
    future "simplification" of the hover code cannot quietly drop it again.
    """

    def _filtered_gauge(self, qapp):
        """Every account is 0% and the filter hides exactly those."""
        accounts = [_account("codex", f"c{i}") for i in range(3)]
        snapshots = {a.key: _codex(a, five=0, weekly=0) for a in accounts}
        return accounts, _build(qapp, accounts, snapshots,
                                limit_gauges_hide_unusable_5h="True")

    def test_without_shift_the_filtered_roster_is_what_shows(self, qapp):
        accounts, gauge = self._filtered_gauge(qapp)
        try:
            assert gauge._visible_accounts() == []
            detail = _text(gauge._build_tooltip(ignore_filters=False))
            assert "Shift held" not in detail
            for account in accounts:
                assert account.display_name not in detail
        finally:
            _retire(gauge)

    def test_shift_held_before_hover_opens_with_every_account(self, qapp):
        """The modifier is read at BUILD time, not only on a later key press."""
        accounts, gauge = self._filtered_gauge(qapp)
        try:
            card = gauge.hover_card()
            original = gauge._shift_held
            gauge._shift_held = lambda: True
            try:
                QApplication.sendEvent(gauge, QEvent(QEvent.Type.Enter))
            finally:
                gauge._shift_held = original
            text = _text(card._label.text())
            assert "Shift held" in text, (
                "the card opened without the all-accounts view even though "
                "Shift was down at hover time")
            for account in accounts:
                assert account.display_name in text, (
                    f"{account.display_name} stayed hidden under Shift")
            card.hide_now()
        finally:
            _retire(gauge)

    def test_pressing_shift_while_the_card_is_open_reveals_everything(
            self, qapp):
        """The live path: Shift reaches the card's own event filter."""
        accounts, gauge = self._filtered_gauge(qapp)
        try:
            card = gauge.hover_card()
            QApplication.sendEvent(gauge, QEvent(QEvent.Type.Enter))
            assert "Shift held" not in card._label.text()

            original = gauge._shift_held
            gauge._shift_held = lambda: True
            try:
                from PyQt6.QtCore import Qt
                from PyQt6.QtGui import QKeyEvent

                card.eventFilter(card, QKeyEvent(
                    QEvent.Type.KeyPress, Qt.Key.Key_Shift,
                    Qt.KeyboardModifier.ShiftModifier))
            finally:
                gauge._shift_held = original

            text = _text(card._label.text())
            assert "Shift held" in text, (
                "pressing Shift with the card open did not switch it to the "
                "all-accounts view")
            for account in accounts:
                assert account.display_name in text
            card.hide_now()
        finally:
            _retire(gauge)

    def test_shift_reaches_the_card_through_the_anchor_window(self, qapp):
        """The realistic route: the key press goes to the focused window.

        The card is a ``Qt.Tool`` that never takes focus, so in the real app
        the press lands on the main window; the card sees it only because it
        installs itself as a QApplication event filter.
        """
        accounts, gauge = self._filtered_gauge(qapp)
        try:
            card = gauge.hover_card()
            QApplication.sendEvent(gauge, QEvent(QEvent.Type.Enter))
            assert getattr(card, "_app_filter_installed", False), (
                "the card is not filtering application events, so a Shift "
                "press in the focused window can never reach it")

            original = gauge._shift_held
            gauge._shift_held = lambda: True
            try:
                from PyQt6.QtCore import Qt
                from PyQt6.QtGui import QKeyEvent

                QApplication.sendEvent(gauge.window(), QKeyEvent(
                    QEvent.Type.KeyPress, Qt.Key.Key_Shift,
                    Qt.KeyboardModifier.ShiftModifier))
            finally:
                gauge._shift_held = original

            text = _text(card._label.text())
            assert "Shift held" in text
            for account in accounts:
                assert account.display_name in text
            card.hide_now()
        finally:
            _retire(gauge)
