"""Tests for the header gauge's own geometry — the pixels the user sees.

Two defects live here and both were invisible to every data-level test:

* width was reserved per account as the WIDEST cluster on screen, so one
  Antigravity account reporting four windows made every two-window account
  reserve four slots; the unpainted ones showed up as a dead strip between the
  gauge and the reset countdown;
* the width reservation and the fit check disagreed about the last cluster's
  trailing gap, so the gauge could conclude nothing fitted inside its own width
  and paint an overflow marker instead of the quota bars.

The assertions are on geometry, not on a screenshot: the cluster row must end
exactly where the widget does, and identical accounts must occupy identical
space.
"""

from __future__ import annotations

import os
import time

import pytest

# Before ANY PyQt6 import, as every Qt-touching test here does: a module that
# lets Qt bind the native Windows platform plugin first makes the next real
# QApplication in the same process abort the interpreter (0xC0000409).
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from fastprompter.core.usage_limits.model import (  # noqa: E402
    FIVE_HOUR,
    OK,
    WEEKLY,
    UsageSnapshot,
    UsageWindow,
    qualified_key,
)
from fastprompter.core.usage_limits.model import AccountRef as AR  # noqa: E402

pytest.importorskip("PyQt6.QtWidgets")

from PyQt6.QtWidgets import QApplication, QWidget  # noqa: E402

from fastprompter.ui.limit_gauges import (  # noqa: E402
    LimitGauges,
    _cluster_windows,
)


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


class _State:
    def __init__(self, accounts, snapshots):
        self.accounts = list(accounts)
        self.snapshots = dict(snapshots)
        self.status = "IDLE"


class _Service:
    def __init__(self, state):
        self._state = state
        self.auto_calls = []

    @property
    def state_copy(self):
        return self._state

    def add_callback(self, cb):
        pass

    def schedule_auto(self, *a):
        self.auto_calls.append(a)

    def refresh(self):
        pass


class _Win(QWidget):
    def __init__(self, **data):
        super().__init__()
        self.data = {"limit_gauges": "True", "limit_gauges_style": "bars",
                     "limit_gauges_show_labels": "False",
                     "limit_gauges_fill": "remaining", **data}
        self._theme_cache = {"raw_colors": {}}


def _account(provider, sid):
    return AR(provider_id=provider, stable_id=sid, display_name=sid,
              source_kind="test")


def test_hover_displays_card_on_enter_without_wakeup_delay(qapp):
    """T-1242: hover opens the application-owned card, not a native tooltip."""
    from PyQt6.QtCore import QEvent
    win = _Win()
    service = _Service(_State([], {}))
    gauge = LimitGauges(win, service)
    try:
        qapp.sendEvent(gauge, QEvent(QEvent.Type.Enter))
        card = gauge._hover_card
        assert card is not None
        assert card.isVisible()
        assert card._label.text() == gauge._build_tooltip()
        # The native tooltip must never compete with the card.
        assert gauge.toolTip() == ""
        assert service.auto_calls
    finally:
        gauge.hide_hover_card(immediate=True)
        win.deleteLater()


def _snapshot(account, windows):
    return UsageSnapshot(account=account, status=OK, fetched_at=time.time(),
                         windows=windows)


def _codex(account, five=0.0, weekly=0.0):
    now = time.time()
    return _snapshot(account, [
        UsageWindow("five_hour", 300, True, 100 - five, five, now + 5 * 3600),
        UsageWindow("weekly", 10080, True, 100 - weekly, weekly,
                    now + 4 * 86400)])


def _antigravity(account):
    """Four windows across two independent pools — the widest real cluster."""
    now = time.time()
    return _snapshot(account, [
        UsageWindow(qualified_key("five_hour", "g"), 300, True, 90, 10,
                    now + 1800, group="g"),
        UsageWindow(qualified_key("weekly", "g"), 10080, True, 32, 68,
                    now + 5 * 86400, group="g"),
        UsageWindow(qualified_key("five_hour", "t"), 300, True, 100, 0, None,
                    group="t"),
        UsageWindow(qualified_key("weekly", "t"), 10080, True, 100, 0,
                    now + 29 * 3600, group="t")])


def _build(qapp, accounts, snapshots, **data):
    win = _Win(**data)
    gauges = LimitGauges(win, _Service(_State(accounts, snapshots)))
    gauges._on_data()
    return gauges


def _ink_end(gauges, accounts, snapshots):
    """Where the last mark's right edge lands — mirrors paintEvent's advance.

    paintEvent advances ``GAP_ACC - GAP_PAIR`` after each cluster, on top of the
    ``GAP_PAIR`` the last bar already added, so the cursor ends one whole
    ``GAP_ACC`` past the ink. Subtracting it gives the exclusive right edge.
    """
    x = gauges.PAD + gauges._status_width(accounts, gauges._service.state_copy)
    show_labels, _per, n_fit = gauges._fit_layout(
        max(0, gauges.width() - x - gauges.PAD), accounts)
    drawn = accounts[:n_fit]
    for account in drawn:
        if show_labels:
            x += gauges._account_label_width(account)
        for _bar in _cluster_windows(snapshots.get(account.key)):
            x += gauges._unit_width() + gauges.GAP_PAIR
        x += gauges.GAP_ACC - gauges.GAP_PAIR
    return x - gauges.GAP_ACC if drawn else x


class TestNoTrailingGap:
    def test_a_mixed_roster_leaves_no_dead_strip(self, qapp):
        """The live machine: 4 two-window accounts plus one four-window one."""
        accounts = [_account("claude", "cl"), _account("codex", "c1"),
                    _account("codex", "c2"), _account("codex", "c3"),
                    _account("antigravity", "ag")]
        snapshots = {a.key: _codex(a) for a in accounts[:4]}
        snapshots[accounts[4].key] = _antigravity(accounts[4])
        gauges = _build(qapp, accounts, snapshots)
        slack = gauges.width() - _ink_end(gauges, accounts, snapshots) - gauges.PAD
        assert 0 <= slack <= 1, (
            f"{slack}px of reserved-but-unpainted width; the header shows it "
            "as a gap before the reset countdown")

    def test_uniform_accounts_leave_no_dead_strip(self, qapp):
        accounts = [_account("codex", "c1"), _account("codex", "c2")]
        snapshots = {a.key: _codex(a) for a in accounts}
        gauges = _build(qapp, accounts, snapshots)
        slack = gauges.width() - _ink_end(gauges, accounts, snapshots) - gauges.PAD
        assert 0 <= slack <= 1, f"{slack}px trailing air"

    def test_a_single_account_leaves_no_dead_strip(self, qapp):
        account = _account("antigravity", "ag")
        snapshots = {account.key: _antigravity(account)}
        gauges = _build(qapp, [account], snapshots)
        slack = gauges.width() - _ink_end(gauges, [account], snapshots) - gauges.PAD
        assert 0 <= slack <= 1, f"{slack}px trailing air"

    def test_width_only_covers_the_marks_each_account_draws(self, qapp):
        """A two-window account must not reserve a four-window footprint."""
        two = _account("codex", "c1")
        four = _account("antigravity", "ag")
        snapshots = {two.key: _codex(two), four.key: _antigravity(four)}
        gauges = _build(qapp, [two, four], snapshots)
        assert gauges._bars_for(two) == 2
        assert gauges._bars_for(four) == 4
        assert gauges._cluster_width(False, two) < \
            gauges._cluster_width(False, four)


class TestClustersAlwaysFitTheirOwnWidget:
    """The widget sizes itself; it must never then decide it is too small."""

    @pytest.mark.parametrize("roster", [
        ("codex",),
        ("codex", "codex"),
        ("antigravity",),
        ("claude", "codex", "codex", "codex", "antigravity"),
    ])
    def test_no_overflow_marker_at_the_widgets_own_width(self, qapp, roster):
        accounts = [_account(provider, f"a{i}")
                    for i, provider in enumerate(roster)]
        snapshots = {}
        for account in accounts:
            snapshots[account.key] = (_antigravity(account)
                                      if account.provider_id == "antigravity"
                                      else _codex(account))
        gauges = _build(qapp, accounts, snapshots)
        content = max(0, gauges.width() - gauges.PAD * 2
                      - gauges._status_width(accounts))
        _labels, _per, n_fit = gauges._fit_layout(content, accounts)
        assert n_fit == len(accounts), (
            "the gauge sized itself too small for its own clusters and would "
            "paint an overflow marker instead of the bars")

    def test_a_genuinely_narrow_budget_still_overflows(self, qapp):
        """The overflow path must keep working when space is really short."""
        accounts = [_account("codex", f"c{i}") for i in range(6)]
        snapshots = {a.key: _codex(a) for a in accounts}
        gauges = _build(qapp, accounts, snapshots)
        _labels, _per, n_fit = gauges._fit_layout(20, accounts)
        assert 0 <= n_fit < len(accounts)


class TestIdenticalAccountsRenderIdentically:
    def test_two_exhausted_codex_accounts_get_the_same_footprint(self, qapp):
        """Both empty: same bar count, same width, same gated verdict."""
        c1, c2 = _account("codex", "c1"), _account("codex", "c2")
        snapshots = {c1.key: _codex(c1, five=0.0, weekly=0.0),
                     c2.key: _codex(c2, five=0.0, weekly=0.0)}
        gauges = _build(qapp, [c1, c2], snapshots)
        assert gauges._bars_for(c1) == gauges._bars_for(c2)
        assert gauges._cluster_width(False, c1) == \
            gauges._cluster_width(False, c2)
        first = _cluster_windows(snapshots[c1.key])
        second = _cluster_windows(snapshots[c2.key])
        assert [w.remaining_percent for w in first] == \
            [w.remaining_percent for w in second]
        assert [w.gated_by for w in first] == [w.gated_by for w in second]

    def test_an_int_zero_and_a_float_zero_are_the_same_reading(self, qapp):
        """The Codex parser yields int 0; Claude yields 0.0. Same pixels."""
        c1, c2 = _account("codex", "c1"), _account("codex", "c2")
        now = time.time()
        snapshots = {
            c1.key: _snapshot(c1, [
                UsageWindow("five_hour", 300, True, 100, 0, now + 3600),
                UsageWindow("weekly", 10080, True, 100, 0, now + 86400)]),
            c2.key: _snapshot(c2, [
                UsageWindow("five_hour", 300, True, 100.0, 0.0, now + 3600),
                UsageWindow("weekly", 10080, True, 100.0, 0.0, now + 86400)]),
        }
        gauges = _build(qapp, [c1, c2], snapshots)
        assert [gauges._fill_fraction(w.remaining_percent)
                for w in _cluster_windows(snapshots[c1.key])] == \
            [gauges._fill_fraction(w.remaining_percent)
             for w in _cluster_windows(snapshots[c2.key])]


class TestStackedStyle:
    """The third header style: horizontal bars stacked in one column.

    Its whole promise is that a column is ONE bar wide however many windows an
    account reports (2 + 2 + 1 windows pack as three narrow columns), and that a
    lone window keeps the shared bottom row instead of floating in the middle.
    """

    def test_one_column_costs_the_same_width_whatever_the_window_count(
            self, qapp):
        two = _account("codex", "c1")
        four = _account("antigravity", "ag")
        snapshots = {two.key: _codex(two), four.key: _antigravity(four)}
        gauges = _build(qapp, [two, four], snapshots,
                        limit_gauges_style="stack")
        assert gauges._marks_width(two) == gauges._marks_width(four) \
            == gauges.STACK_BAR_W
        assert gauges._cluster_width(False, two) == \
            gauges._cluster_width(False, four)

    def test_stacking_is_narrower_than_bars_for_a_wide_account(self, qapp):
        four = _account("antigravity", "ag")
        snapshots = {four.key: _antigravity(four)}
        bars = _build(qapp, [four], snapshots, limit_gauges_style="bars")
        stack = _build(qapp, [four], snapshots, limit_gauges_style="stack")
        assert stack._bars_for(four) == 4
        assert stack._marks_width(four) < bars._marks_width(four) * 4

    @pytest.mark.parametrize("height", [10, 12, 16, 22, 30])
    def test_rows_always_fit_the_mark_area(self, qapp, height):
        account = _account("antigravity", "ag")
        snapshots = {account.key: _antigravity(account)}
        gauges = _build(qapp, [account], snapshots,
                        limit_gauges_style="stack")
        area = height - 6
        row_h, gap = gauges._stack_metrics(area)
        assert row_h >= 1
        used = gauges.MAX_BARS * row_h + (gauges.MAX_BARS - 1) * gap
        assert used <= area, (
            f"a {gauges.MAX_BARS}-row column needs {used}px of {area}px")

    def test_the_widget_still_sizes_itself_to_its_own_clusters(self, qapp):
        accounts = [_account("claude", "cl"), _account("codex", "c1"),
                    _account("antigravity", "ag")]
        snapshots = {a.key: _codex(a) for a in accounts[:2]}
        snapshots[accounts[2].key] = _antigravity(accounts[2])
        gauges = _build(qapp, accounts, snapshots,
                        limit_gauges_style="stack")
        content = max(0, gauges.width() - gauges.PAD * 2
                      - gauges._status_width(accounts))
        _labels, _per, n_fit = gauges._fit_layout(content, accounts)
        assert n_fit == len(accounts)

    def test_a_single_window_sits_on_the_bottom_row(self, qapp):
        """Not centred: the one bar is the foot of the L."""
        from PyQt6.QtGui import QImage

        account = _account("codex", "free")
        now = time.time()
        snapshots = {account.key: _snapshot(account, [
            UsageWindow("monthly", 43200, True, 100, 0, now + 20 * 86400)])}
        gauges = _build(qapp, [account], snapshots,
                        limit_gauges_style="stack")
        height = 22
        gauges.resize(gauges.width(), height)
        image = QImage(gauges.width(), height, QImage.Format.Format_ARGB32)
        image.fill(0)
        gauges.render(image)

        area_top, area_h = 2, height - 6
        row_h, gap = gauges._stack_metrics(area_h)
        bg = gauges._palette()["bg"].rgb()

        def inked(top, bottom):
            return any(image.pixel(x, y) != bg
                       for y in range(top, bottom)
                       for x in range(gauges.width()))

        bottom_top = area_top + area_h - row_h
        assert inked(bottom_top, area_top + area_h), \
            "the single quota bar must be drawn on the bottom row"
        second_row_bottom = bottom_top - gap
        second_row_top = max(area_top, second_row_bottom - row_h)
        assert not inked(area_top, second_row_top + 1), \
            "nothing may be drawn above the bar: it is bottom-anchored, not centred"

    def test_paintEvent_renders_every_window_of_every_roster(self, qapp):
        """The stack draw loop must not crash on any legal window count
        (including accounts that pad to MIN_BARS or report a single one)."""
        rosters = [
            [_account("claude", "cl"), _account("codex", "c1")],
            [_account("antigravity", "ag")],
            [_account("codex", "free")],
        ]
        for accounts in rosters:
            snapshots = {}
            for account in accounts:
                if account.provider_id == "antigravity":
                    snapshots[account.key] = _antigravity(account)
                elif account.stable_id == "free":
                    now = time.time()
                    snapshots[account.key] = _snapshot(account, [
                        UsageWindow("monthly", 43200, True, 62, 38,
                                    now + 20 * 86400)])
                else:
                    snapshots[account.key] = _codex(account)
            gauges = _build(qapp, accounts, snapshots,
                            limit_gauges_style="stack")
            for height in (10, 14, 22, 30):
                gauges.resize(gauges.width(), height)
                from PyQt6.QtGui import QImage
                image = QImage(gauges.width(), height,
                               QImage.Format.Format_ARGB32)
                image.fill(0)
                gauges.render(image)   # exercises paintEvent end to end

    def test_ink_advance_matches_paintEvent_in_stack_mode(self, qapp):
        """The widget must size itself to exactly what stack mode paints:
        label + ONE column of bars + trailing GAP_ACC per account."""
        accounts = [_account("claude", "cl"), _account("codex", "c1"),
                    _account("antigravity", "ag")]
        snapshots = {a.key: _codex(a) for a in accounts[:2]}
        snapshots[accounts[2].key] = _antigravity(accounts[2])
        gauges = _build(qapp, accounts, snapshots,
                        limit_gauges_style="stack",
                        limit_gauges_show_labels="True")
        x = gauges.PAD + gauges._status_width(accounts)
        for account in accounts:
            label_w = gauges._account_label_width(account)
            x += label_w + gauges._marks_width(account) + gauges.GAP_ACC
        # the final cluster's GAP_ACC separates it from a NEXT cluster; there
        # is none, so neither the widget nor the painter reserves it
        x -= gauges.GAP_ACC
        slack = gauges.width() - x - gauges.PAD
        assert 0 <= slack <= 1, f"{slack}px reserved but not painted"


class TestVendorTint:
    """A live fill leans towards its vendor's hue, muted."""

    def _pal(self, gauges):
        return gauges._palette()

    def test_two_vendors_at_the_same_quota_differ(self, qapp):
        claude, codex = _account("claude", "cl"), _account("codex", "c1")
        snapshots = {claude.key: _codex(claude), codex.key: _codex(codex)}
        gauges = _build(qapp, [claude, codex], snapshots)
        pal = self._pal(gauges)
        assert gauges._bar_color(80, pal, claude).name() != \
            gauges._bar_color(80, pal, codex).name()

    def test_the_tint_stays_closer_to_the_quota_colour_than_to_the_vendor(
            self, qapp):
        """Muted on purpose: the quota level must still read first."""
        from PyQt6.QtGui import QColor

        from fastprompter.ui.limit_colors import reset_color

        claude = _account("claude", "cl")
        gauges = _build(qapp, [claude], {claude.key: _codex(claude)})
        pal = self._pal(gauges)
        base = pal["good"]
        vendor = QColor(reset_color(gauges.main_win, "claude"))
        tinted = gauges._bar_color(80, pal, claude)

        def dist(a, b):
            return ((a.red() - b.red()) ** 2 + (a.green() - b.green()) ** 2
                    + (a.blue() - b.blue()) ** 2) ** 0.5

        assert tinted.name() != base.name()
        assert dist(tinted, base) < dist(tinted, vendor)

    def test_tint_off_paints_the_plain_quota_colour(self, qapp):
        claude = _account("claude", "cl")
        gauges = _build(qapp, [claude], {claude.key: _codex(claude)},
                        limit_gauges_vendor_tint="False")
        pal = self._pal(gauges)
        assert gauges._bar_color(80, pal, claude).name() == pal["good"].name()
        assert gauges._bar_color(10, pal, claude).name() == pal["bad"].name()

    def test_quota_thresholds_survive_the_tint(self, qapp):
        """Critical still reads red-ward, healthy still gold-ward."""
        claude = _account("claude", "cl")
        gauges = _build(qapp, [claude], {claude.key: _codex(claude)})
        pal = self._pal(gauges)
        healthy = gauges._bar_color(80, pal, claude)
        critical = gauges._bar_color(10, pal, claude)
        assert healthy.name() != critical.name()
        assert gauges._bar_color(None, pal, claude).name() == pal["dim"].name()


class TestLimitGaugeRichTooltip:
    def test_tooltip_renders_rich_html_with_bars_and_colors(self, qapp):
        """The gauge tooltip renders visual progress bars and color-coded percentages."""
        c1 = _account("claude", "c1")
        now = time.time()
        snapshots = {
            c1.key: _snapshot(c1, [
                UsageWindow("five_hour", 300, True, 20, 80, now + 3600),
                UsageWindow("weekly", 10080, True, 85, 15, now + 86400),
            ])
        }
        gauges = _build(qapp, [c1], snapshots)
        tt = gauges._build_tooltip()

        assert tt.startswith("<html>")
        assert "AI Usage Limits" in tt
        # Visual progress bars: solid blocks for both filled and track
        assert "█" in tt
        assert "░" not in tt
        # Color coding
        assert "color:" in tt
        # Windows & percentages
        assert "80%" in tt
        assert "15%" in tt
        import re
        assert not re.search(r">(?:80|15)%\s+\d+m</td>", tt)
        assert "80% ·" not in tt
        assert "15% ·" not in tt
        assert "resets in " in tt
        assert "5h:" in tt
        assert "weekly:" in tt

        # Multi-account realistic tooltip
        c2 = AR("antigravity", "main", "Antigravity", "test")
        c3 = AR("claude", "work", "Claude", "test")
        multi_snaps = {
            c2.key: _snapshot(c2, [
                UsageWindow("five_hour", 300, True, 100, 0, None, gated_by="weekly", group_label="Claude and GPT models"),
                UsageWindow("weekly", 10080, True, 100, 0, now + 22 * 3600, group_label="Claude and GPT models"),
                UsageWindow("five_hour", 300, True, 14, 86, now + 4 * 3600, group_label="Gemini Models"),
                UsageWindow("weekly", 10080, True, 52, 48, now + 40 * 3600, group_label="Gemini Models"),
            ]),
            c3.key: _snapshot(c3, [
                UsageWindow("five_hour", 300, True, 100, 0, now + 3540),
                UsageWindow("weekly", 10080, True, 77, 23, now + 50 * 3600),
            ]),
            c1.key: _snapshot(c1, [
                UsageWindow("five_hour", 300, True, 100, 0, None, gated_by="weekly"),
                UsageWindow("weekly", 10080, True, 100, 0, now + 86400),
            ]),
        }
        multi_gauges = _build(qapp, [c2, c3, c1], multi_snaps)
        multi_tt = multi_gauges._build_tooltip()

        assert "Antigravity" in multi_tt
        assert "Claude" in multi_tt
        # Single unified table across all accounts guarantees perfect column alignment
        assert multi_tt.count("<table") == 1
        assert multi_tt.count("</table>") == 1

    def test_tooltip_hover_rebuilds_elapsed_reset_without_sync_probe(
            self, qapp):
        from PyQt6.QtCore import QEvent, QPoint
        from PyQt6.QtGui import QHelpEvent

        account = _account("codex", "hover")
        now = time.time()
        live = _snapshot(account, [
            UsageWindow("five_hour", 300, True, 100, 0, now + 120),
        ])
        gauges = _build(qapp, [account], {account.key: live})
        assert "0% ·" not in gauges._build_tooltip()
        assert "resets in 2m" in gauges._build_tooltip()

        elapsed = UsageSnapshot(
            account=account, status=OK, fetched_at=now,
            windows=[UsageWindow(
                "five_hour", 300, True, 100, 0, now - 1)])
        gauges._service._state.snapshots[account.key] = elapsed
        event = QHelpEvent(
            QEvent.Type.ToolTip, QPoint(1, 1), gauges.mapToGlobal(QPoint(1, 1)))

        QApplication.sendEvent(gauges, event)

        rendered = gauges._hover_card._label.text()
        assert "Reset time passed" in rendered
        assert "100%" not in rendered
        assert "0% ·" not in rendered
        assert "0m" not in rendered
        assert gauges._service.auto_calls == [(180,)]
        gauges.hide_hover_card(immediate=True)

    def test_tooltip_never_calls_a_future_reset_zero_minutes(self, qapp):
        account = _account("codex", "under-minute")
        now = time.time()
        snapshots = {account.key: UsageSnapshot(
            account=account, status=OK, fetched_at=now - 125,
            windows=[UsageWindow(
                "five_hour", 300, True, 100, 0, now + 30)])}
        tt = _build(qapp, [account], snapshots)._build_tooltip()

        assert "0% ·" not in tt
        assert "resets in &lt;1m" in tt
        assert "resets in 0m" not in tt
        assert "updated 2m ago" in tt


class TestTooltipNameClearsTheBars:
    """A long account name must not sit on top of the quota rows.

    The name used to be a ``<div>`` whose bottom margin Qt's rich-text engine
    partially ignored, leaving it ~1px above the bars — it read as lying
    "under" them. The name is now the table's first row, so the cell padding
    is honoured. Laid out through the same QTextDocument the tooltip label
    uses, the name block must clear the first quota row by real pixels.
    """

    def test_long_name_clears_the_first_bar_row(self, qapp):
        from PyQt6.QtGui import QTextDocument

        long_name = ("CodexUltraLongAccountNameEnterpriseTeam"
                     "Production2026Workspace")
        account = _account("codex", "long")
        account = AR(provider_id="codex", stable_id="long",
                     display_name=long_name, source_kind="test")
        snapshots = {account.key: _codex(account, five=58.0, weekly=88.0)}
        gauges = _build(qapp, [account], snapshots,
                        limit_gauges_show_labels="True")

        for width in (None, 180):
            doc = QTextDocument()
            doc.setHtml(gauges._build_tooltip())
            layout = doc.documentLayout()
            if width:
                doc.setTextWidth(width)
            else:
                doc.adjustSize()
            name_bottom = first_row_top = None
            block = doc.begin()
            while block.isValid():
                rect = layout.blockBoundingRect(block)
                text = block.text()
                if name_bottom is None and long_name[:24] in text:
                    name_bottom = rect.top() + rect.height()
                elif name_bottom is not None and "5h" in text:
                    first_row_top = rect.top()
                    break
                block = block.next()
            assert name_bottom is not None and first_row_top is not None
            assert first_row_top - name_bottom >= 3, (
                f"long name bottom {name_bottom:.0f} vs first bar row top "
                f"{first_row_top:.0f}: the name crowds/overlaps the bars "
                f"(width={width})")


class TestCodexBankedResetsTooltip:
    def test_tooltip_shows_banked_resets_badge_and_footnote(self, qapp):
        account = _account("codex", "c_banked")
        snap = UsageSnapshot(
            account=account, status=OK, fetched_at=time.time(),
            windows=[UsageWindow("five_hour", 300, True, 50, 50, None)],
            banked_resets=1,
        )
        gauges = _build(qapp, [account], {account.key: snap})
        tt = gauges._build_tooltip()
        assert "[1 banked reset]" in tt
        assert "★ 1 usage limit reset available" in tt
        assert "run <code>/usage</code> in CLI to redeem" in tt

    def test_tooltip_shows_plural_banked_resets(self, qapp):
        account = _account("codex", "c_banked_multi")
        snap = UsageSnapshot(
            account=account, status=OK, fetched_at=time.time(),
            windows=[UsageWindow("five_hour", 300, True, 50, 50, None)],
            banked_resets=3,
        )
        gauges = _build(qapp, [account], {account.key: snap})
        tt = gauges._build_tooltip()
        assert "[3 banked resets]" in tt
        assert "★ 3 usage limit resets available" in tt

    def test_context_menu_has_activate_reset_action(self, qapp, monkeypatch):
        from PyQt6.QtCore import QPoint
        from PyQt6.QtGui import QContextMenuEvent
        account = _account("codex", "c_banked")
        snap = UsageSnapshot(
            account=account, status=OK, fetched_at=time.time(),
            windows=[UsageWindow("five_hour", 300, True, 50, 50, None)],
            banked_resets=1,
        )
        gauges = _build(qapp, [account], {account.key: snap})

        actions_seen = []
        from PyQt6.QtWidgets import QMenu
        monkeypatch.setattr(QMenu, "exec", lambda self, pos: [actions_seen.append(a.text()) for a in self.actions()])

        ev = QContextMenuEvent(QContextMenuEvent.Reason.Mouse, QPoint(5, 5))
        gauges.contextMenuEvent(ev)
        assert any("Activate c_banked Reset" in text for text in actions_seen)
        assert any("Refresh Limits Now" in text for text in actions_seen)

    def test_tooltip_titles_colored_with_vendor_colors(self, qapp):
        acc_claude = _account("claude", "Claude Pro")
        acc_codex = _account("codex", "Codex Plus")
        snap_claude = UsageSnapshot(account=acc_claude, status=OK, fetched_at=time.time(), windows=[])
        snap_codex = UsageSnapshot(account=acc_codex, status=OK, fetched_at=time.time(), windows=[])

        gauges = _build(qapp, [acc_claude, acc_codex], {
            acc_claude.key: snap_claude,
            acc_codex.key: snap_codex,
        })
        gauges.main_win.data["limit_colors"] = {"reset_claude": "#112233"}
        tt = gauges._build_tooltip()
        assert "<b style='color:#112233;'>Claude Pro</b>" in tt
        assert "<b style='color:#6AA9FF;'>Codex Plus</b>" in tt


class TestAllAccountsFilteredPlaceholder:
    """hide 5h/0% removed every account: no hole in the header.

    When every account is filtered out the gauge collapses to its actual
    painted ink: a dim neutral filtered indicator owns only its glyph width
    (plus padding), never a reserved empty cluster footprint. The tooltip says
    "filtered" rather than "no accounts selected".
    """

    def _filtered_gauge(self, qapp, **data):
        accounts = [_account("codex", "c1"), _account("claude", "cl")]
        # both exhausted (0% left everywhere) -> hidden by the hide-0% filter
        snapshots = {a.key: _codex(a) for a in accounts}
        return _build(qapp, accounts, snapshots,
                      limit_gauges_hide_zero_usage="True", **data)

    def test_filtered_width_is_ink_plus_padding(self, qapp):
        gauges = self._filtered_gauge(qapp)
        assert gauges._visible_accounts() == []
        assert gauges._has_any_accounts() is True
        assert gauges.width() == gauges.PAD * 2 + gauges._status_width([]) + gauges.fontMetrics().horizontalAdvance("0")
        assert gauges.width() <= gauges.PAD * 2 + gauges._status_width([]) + 14

    def test_filter_toggle_resizes_immediately(self, qapp):
        gauges = self._filtered_gauge(qapp)
        compact = gauges.width()
        gauges.main_win.data["limit_gauges_hide_zero_usage"] = "False"

        gauges._on_data()

        assert gauges.width() > compact
        gauges.main_win.data["limit_gauges_hide_zero_usage"] = "True"
        gauges._on_data()
        assert gauges.width() == compact

    def test_tooltip_says_filtered_not_no_accounts(self, qapp):
        gauges = self._filtered_gauge(qapp)
        tt = gauges._build_tooltip()
        assert "hide 5h/0% filter" in tt
        assert "no accounts selected" not in tt

    def test_empty_service_still_reads_no_accounts_selected(self, qapp):
        """A genuinely empty roster keeps the original 'no accounts' text."""
        win = _Win()
        gauges = LimitGauges(win, _Service(_State([], {})))
        gauges._on_data()
        assert gauges._has_any_accounts() is False
        assert "no accounts selected" in gauges._build_tooltip()

    def test_paints_dim_marks_without_crashing(self, qapp):
        from PyQt6.QtGui import QImage
        gauges = self._filtered_gauge(qapp, limit_gauges_style="bars")
        gauges.resize(gauges.width(), 22)
        image = QImage(gauges.width(), 22, QImage.Format.Format_ARGB32)
        image.fill(0)
        gauges.render(image)
        pal = gauges._palette()
        bg = pal["bg"].rgb()
        inked = any(image.pixel(x, y) != bg
                    for y in range(gauges.height())
                    for x in range(gauges.width()))
        assert inked, "the filtered gauge must paint dim ink, not a blank hole"

    def test_placeholder_renders_in_stack_and_dots_styles(self, qapp):
        from PyQt6.QtGui import QImage
        for style in ("stack", "dots"):
            gauges = self._filtered_gauge(qapp, limit_gauges_style=style)
            gauges.resize(gauges.width(), 22)
            image = QImage(gauges.width(), 22, QImage.Format.Format_ARGB32)
            image.fill(0)
            gauges.render(image)   # must not crash on any style


class TestRealTopbarGap:
    """SYNTHETIC component-layout test (audit 5): the dead strip was reserved
    INSIDE the gauge's own fixed width, so with the header's zero spacing the
    reset countdown sat far right of any painted ink. This reproduces the
    topbar ARRANGEMENT with a bare QWidget + zero-spacing QHBoxLayout and
    asserts the neighbour gap is only layout. It does NOT exercise the real
    FastPrompter header, its visibility coordinator or its semantic state —
    that is TestRealFastPrompterHeader's job. Kept because it pins the pure
    layout contract cheaply."""

    def _topbar(self, qapp, hide):
        from PyQt6.QtWidgets import QHBoxLayout, QLabel
        accounts = [_account("codex", "c1"), _account("claude", "cl")]
        snapshots = {a.key: _codex(a) for a in accounts}
        gauges = _build(qapp, accounts, snapshots,
                        limit_gauges_hide_zero_usage="True" if hide else "False")
        bar = QLabel("reset 2h")
        host = QWidget()
        layout = QHBoxLayout(host)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(gauges)
        layout.addWidget(bar)
        host.resize(600, 24)
        host.show()
        qapp.processEvents()
        return gauges, bar, host

    def test_all_filtered_neighbour_gap_is_layout_only(self, qapp):
        gauges, bar, host = self._topbar(qapp, hide=True)
        try:
            gap = bar.geometry().left() - gauges.geometry().right()
            assert -1 <= gap <= 1, f"{gap}px dead strip before the reset label"
            assert gauges.width() <= gauges.PAD * 2 + gauges._status_width([]) + 14
            assert bar.isVisible()
        finally:
            host.deleteLater()

    def test_filter_toggle_expands_and_collapses_without_restart(self, qapp):
        gauges, bar, host = self._topbar(qapp, hide=True)
        try:
            compact = gauges.width()
            gauges.main_win.data["limit_gauges_hide_zero_usage"] = "False"

            gauges._on_data()
            qapp.processEvents()
            wide = gauges.width()
            assert wide > compact
            gap_wide = bar.geometry().left() - gauges.geometry().right()
            assert -1 <= gap_wide <= 1
            gauges.main_win.data["limit_gauges_hide_zero_usage"] = "True"
            gauges._on_data()
            qapp.processEvents()
            expected_compact = (gauges.PAD * 2 + gauges._status_width([])
                                + gauges.fontMetrics().horizontalAdvance("0"))
            assert gauges.width() == expected_compact

        finally:

            host.deleteLater()

    def test_resize_does_not_resurrect_the_dead_gap(self, qapp):
        gauges, bar, host = self._topbar(qapp, hide=True)
        try:
            for width in (600, 420, 300, 600):
                host.resize(width, 24)
                qapp.processEvents()
                gap = bar.geometry().left() - gauges.geometry().right()
                assert -1 <= gap <= 1, f"{gap}px gap resurrected at width {width}"
        finally:
            host.deleteLater()


class TestRealFastPrompterHeader:
    """T-1220 on the REAL FastPrompter header, not a synthetic stand-in.

    A bare-QWidget reproduction (TestRealTopbarGap) cannot see the topbar
    visibility coordinator, semantic availability or the real header reflow.
    Here a real FastPrompter window runs the real update path —
    ``limit_gauges._on_data()``, ``_update_limit_timer_label()`` and the real
    ``_apply_topbar_visibility()`` — and the geometry must prove itself:
    all-filtered renders the compact dim indicator, the reset countdown sits
    directly beside it with no dead strip, and toggling the filter expands and
    collapses the header immediately, without a resize or restart.

    Fixture pattern mirrors tests/test_usage_limits_hide_zero.py (DB path
    redirected to tmp_path BEFORE construction, hotkeys/single-instance/
    background probing no-ops).
    """

    @pytest.fixture
    def real_win(self, qapp, monkeypatch, tmp_path):
        from _qt_retire import retire

        import fastprompter.core.state as state_mod
        from fastprompter.core.usage_limits.service import UsageLimitService
        from fastprompter.main import FastPrompter

        monkeypatch.setattr(
            state_mod, "get_db_path",
            lambda profile_id=1: str(tmp_path / f"t1220_{profile_id}.db"))
        for name in ("setup_single_instance_server", "register_all_hotkeys",
                     "unregister_all_hotkeys"):
            monkeypatch.setattr(FastPrompter, name, lambda self: None)
        monkeypatch.setattr(UsageLimitService, "schedule_auto",
                            lambda *a, **kw: None)

        win = FastPrompter()
        win.data["limit_gauges"] = "True"
        win.data["limit_gauges_hide_zero_usage"] = "False"
        win.data["limit_gauges_hide_unusable_5h"] = "False"
        win.resize(1400, 800)
        win.show()
        qapp.processEvents()
        yield win

        if hasattr(win, "limit_service") and win.limit_service is not None:
            try:
                win.limit_service.shutdown()
            except Exception:
                pass
        from PyQt6.QtCore import QTimer
        win._wait_for_undo_saves()
        for timer in win.findChildren(QTimer):
            timer.stop()
        win._logical_finalized = True
        win.tray_icon.hide()
        win.close()
        # T-1286: canonical receiver-scoped retirement replaces a
        # process-wide sendPostedEvents(None, DeferredDelete) drain, which
        # destroyed Qt objects other test files still owned.
        retire(win)

    # -- helpers -----------------------------------------------------------
    def _inject(self, win, mode):
        """Two real accounts whose quota bars disappear under one filter,
        while a future reset timestamp survives (the countdown the user is
        waiting for must not vanish with the bars)."""
        now = time.time()
        c1 = AR("codex", "t1220_c1", "Codex C1", "test")
        c2 = AR("claude", "t1220_cl", "Claude CL", "test")
        if mode == "zero":
            # 0% remaining everywhere -> hidden by hide 0%
            windows = [
                UsageWindow(FIVE_HOUR, 300, True, 100.0, 0.0, now + 1800),
                UsageWindow(WEEKLY, 10080, True, 100.0, 0.0,
                            now + 4 * 86400)]
        else:
            # 5h exhausted, weekly full -> hidden by hide unusable 5h
            windows = [
                UsageWindow(FIVE_HOUR, 300, True, 100.0, 0.0, now + 1800),
                UsageWindow(WEEKLY, 10080, True, 0.0, 100.0,
                            now + 4 * 86400)]
        snaps = {a.key: UsageSnapshot(a, OK, list(windows))
                 for a in (c1, c2)}
        with win.limit_service._lock:
            win.limit_service._state.accounts = [c1, c2]
            win.limit_service._state.snapshots = snaps

    def _enable_filter(self, win, mode):
        win.data["limit_gauges_hide_zero_usage"] = (
            "True" if mode == "zero" else "False")
        win.data["limit_gauges_hide_unusable_5h"] = (
            "True" if mode == "unusable" else "False")

    def _settle(self, qapp, win):
        """The real update path: data -> width, reset label, coordinator."""
        win.limit_gauges._on_data()
        win._update_limit_timer_label()
        win._apply_topbar_visibility()
        for _ in range(3):
            qapp.processEvents()

    def _gap(self, win):
        """Exclusive-ish dead strip between the gauge and the reset label.

        QRect.right() is inclusive, so flush neighbours read -1..0.
        """
        return (win.lbl_limit_timer.geometry().left()
                - win.limit_gauges.geometry().right())

    # -- acceptance --------------------------------------------------------
    @pytest.mark.parametrize("mode", ["zero", "unusable"])
    def test_all_filtered_keeps_reset_adjacent_on_the_real_header(
            self, qapp, real_win, mode):
        win = real_win
        self._inject(win, mode)
        win.limit_gauges.sync()
        self._enable_filter(win, mode)
        self._settle(qapp, win)

        assert win.limit_gauges.isVisible()
        assert win.limit_gauges._visible_accounts() == []
        assert win.limit_gauges._has_any_accounts() is True
        compact = win.limit_gauges.width()
        # INDEPENDENT expectation: the ink of the dim "0" measured from the
        # widget's own font, not a product helper — reserving any invisible
        # width here is exactly the dead strip T-1220 exists to kill. All
        # fixture snapshots are OK, so no "!" status marker is expected.
        expected = (win.limit_gauges.PAD * 2
                    + win.limit_gauges.fontMetrics().horizontalAdvance("0"))
        assert compact == expected, (
            "the all-filtered gauge must own only its painted ink width "
            f"({compact}px != {expected}px)")
        gap = self._gap(win)
        assert -1 <= gap <= 1, (
            f"{gap}px dead strip between the compact gauge and the reset "
            "countdown on the real header")
        assert win.lbl_limit_timer.isVisible()

    def test_filter_toggle_moves_the_real_header_immediately(
            self, qapp, real_win):
        win = real_win
        self._inject(win, "zero")
        self._enable_filter(win, "zero")
        win.limit_gauges.sync()
        self._settle(qapp, win)
        compact = win.limit_gauges.width()
        assert win.lbl_limit_timer.isVisible()
        assert -1 <= self._gap(win) <= 1

        # filter OFF: real path expands the gauge and the label closes up
        win.data["limit_gauges_hide_zero_usage"] = "False"
        self._settle(qapp, win)
        wide = win.limit_gauges.width()
        assert wide > compact
        assert -1 <= self._gap(win) <= 1
        assert win.lbl_limit_timer.isVisible()
        assert win.lbl_limit_timer.geometry().left() >= wide - 1

        # filter ON again: exactly compact again, no resize, no restart
        win.data["limit_gauges_hide_zero_usage"] = "True"
        self._settle(qapp, win)
        assert win.limit_gauges.width() == compact
        assert -1 <= self._gap(win) <= 1
        assert win.lbl_limit_timer.isVisible()

    @pytest.mark.parametrize("width", [1400, 1100, 900])
    def test_compact_state_survives_normal_widths(self, qapp, real_win,
                                                  width):
        win = real_win
        self._inject(win, "zero")
        self._enable_filter(win, "zero")
        win.limit_gauges.sync()
        win.resize(width, 800)
        self._settle(qapp, win)

        assert win.limit_gauges._visible_accounts() == []
        assert win.limit_gauges.width() <= (
            win.limit_gauges.PAD * 2
            + win.limit_gauges.STATUS_W + 14)
        assert win.lbl_limit_timer.isVisible()
        assert -1 <= self._gap(win) <= 1, (
            f"dead strip at width {width}")

    def test_resize_path_is_deterministic_at_the_same_width(
            self, qapp, real_win):
        win = real_win
        self._inject(win, "zero")
        self._enable_filter(win, "zero")
        win.limit_gauges.sync()

        def probe():
            self._settle(qapp, win)
            return (win.limit_gauges.width(),
                    win.lbl_limit_timer.geometry().left(),
                    win.lbl_limit_timer.isVisible())

        # sequence A: 1400 -> 900 -> 1100
        win.resize(1400, 800)
        probe()
        win.resize(900, 800)
        probe()
        win.resize(1100, 800)
        a_final = probe()
        # sequence B: 900 -> 1400 -> 1100
        win.resize(900, 800)
        probe()
        win.resize(1400, 800)
        probe()
        win.resize(1100, 800)
        b_final = probe()

        assert a_final[0] == b_final[0], (
            f"gauge width depends on the resize path: A={a_final} B={b_final}")
        assert abs(a_final[1] - b_final[1]) <= 1, (
            f"reset label position depends on the resize path: "
            f"A={a_final} B={b_final}")
        assert a_final[2] and b_final[2]

    def test_genuinely_empty_service_stays_distinct_on_the_real_header(
            self, qapp, real_win):
        win = real_win
        with win.limit_service._lock:
            win.limit_service._state.accounts = []
            win.limit_service._state.snapshots = {}
        win.limit_gauges.sync()
        self._settle(qapp, win)

        assert win.limit_gauges._has_any_accounts() is False
        # A genuinely empty gauge is the bare status-bearing sliver, NOT the
        # all-filtered placeholder width.
        assert win.limit_gauges.width() == win.limit_gauges.PAD * 2 + 14
        assert "no accounts selected" in win.limit_gauges._build_tooltip()
        # No reset known -> no fabricated countdown either.
        assert not win.lbl_limit_timer.isVisible()
