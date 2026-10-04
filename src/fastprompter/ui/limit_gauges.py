"""Provider-neutral LimitGauges header widget.

Consumes normalized :mod:`fastprompter.core.usage_limits.model` snapshots
only — never provider payloads. Renders one 2–3 px bar-pair (5h | weekly) per
account, filled bottom-up by REMAINING percentage. Unavailable renders a dim
outline, stale renders dashed/amber, live renders gold/olive/red by threshold.

Three styles, cycled with Ctrl+Click (``limit_gauges_style``):

* ``bars``  — one thin vertical bar per window, side by side;
* ``dots``  — the same windows as pie-filled dots;
* ``stack`` — one HORIZONTAL bar per window, stacked bottom-up in a single
  column (max ``MAX_BARS`` tall), so an account costs one bar of width whatever
  its window count: 2 + 2 + 1 windows pack as three narrow columns. A lone
  window keeps the shared bottom row instead of being centred.

A live fill also picks up a muted share of its vendor's colour — the same hue
the reset countdown uses — unless ``limit_gauges_vendor_tint`` is off.

The widget is deliberately hard to miss when enabled: it always paints a
beveled box and the quota clusters. Healthy account counts are not repeated;
only ``!`` (unavailable/error) or ``~`` (stale) consumes status space.

Overflow policy: data supports any account count; the header renders as many
complete account clusters as fit the width budget, then shows an overflow
marker. Every account stays inspectable in the tooltip.
"""

from __future__ import annotations

import html
import math
import time

from PyQt6.QtCore import QEvent, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QCursor, QPainter, QPen
from PyQt6.QtWidgets import QSizePolicy, QWidget


def sip_deleted(widget) -> bool:
    """True when Qt has already destroyed the C++ side of ``widget``."""
    try:
        import sip
    except ImportError:
        try:
            from PyQt6 import sip
        except ImportError:
            return False
    try:
        return bool(sip.isdeleted(widget))
    except (TypeError, RuntimeError):
        return False

from fastprompter.core.translations import tr
from fastprompter.core.usage_limits.freebuff_format import (
    format_amount,
    format_price,
    price_buckets,
    spendable_total,
)
from fastprompter.core.usage_limits.model import (
    EXPECTED_QUIET_CODES,
    FIVE_HOUR,
    MONTHLY,
    OK,
    STALE,
    WEEKLY,
    UsageWindow,
    account_has_usage,
    account_usable_now,
    base_key,
    display_windows,
    format_offer_expiry,
    manual_reset_count,
    reserve_advice,
    reset_offer_rows,
    resolved_windows,
)
from fastprompter.core.usage_limits.service import UsageLimitService
from fastprompter.ui.limit_account_selector import (
    account_display_name,
    hidden_account_keys,
    ordered_accounts,
    short_account_label,
)
from fastprompter.ui.limit_colors import limit_palette, reset_color
from fastprompter.ui.qt_lifetime import weak_qt_callback

_KNOWN_WINDOW_MIN = {FIVE_HOUR: 300, WEEKLY: 10080, MONTHLY: 43200}

# Where a non-activatable manual reset offer sends the user (T-1360): the
# vendor's own usage surface, never an invented deep link. Codex is absent
# because its redemption IS proven and gets a real Activate button.
_RESET_OPEN_URLS = {
    "claude": "https://claude.ai/settings/usage",
    "zcode": "https://zcode.z.ai",
}

# Bars per account cluster — see LimitGauges.MIN_BARS/MAX_BARS.
_MIN_BARS = 2
# An Antigravity account alone reports three live windows across two pools
# (Gemini weekly + Gemini 5h + Claude/GPT weekly), and a Codex Plus account
# two. Four keeps the widest real cluster complete instead of silently
# dropping a limit the user is actually spending.
_MAX_BARS = 4

# The three header styles, in Ctrl+Click cycle order.
_STYLES = ("bars", "dots", "stack")


class LimitGauges(QWidget):
    """Compact usage gauges driven by a UsageLimitService."""

    # UsageLimitService completes on a worker thread.  Emitting this signal
    # is the only allowed bridge back to QWidget state; direct callbacks into
    # Qt can crash the process during refresh or window teardown.
    _result_ready = pyqtSignal()

    BAR_W = 3
    DOT_D = 8
    # "stack" style: every window of one account is a HORIZONTAL bar, stacked
    # bottom-up in one column, so a four-window account costs the same width as
    # a one-window account. A single bar is not centred — it sits on the bottom
    # row, so the baseline is shared across accounts (the "L" foot).
    STACK_BAR_W = 14
    STACK_GAP = 1
    GAP_PAIR = 1
    GAP_ACC = 4
    PAD = 2
    MAX_WIDGET_W = 220
    STATUS_W = 8
    ACCOUNT_LABEL_W = 12
    # A cluster shows one bar per window the provider reported. Most plans
    # report 5h + weekly; a Free Codex plan reports a single 30-day window,
    # so a cluster can legally be 1 bar wide. MIN keeps unknown/unprobed
    # accounts visually consistent with their neighbours.
    MIN_BARS = _MIN_BARS
    MAX_BARS = _MAX_BARS
    # How much of the vendor's own colour a live fill picks up (0..1). Low on
    # purpose: an accent, not a repaint — see _vendor_tinted.
    VENDOR_TINT = 0.34

    def __init__(self, main_win, service: UsageLimitService):
        parent = main_win if isinstance(main_win, QWidget) else None
        super().__init__(parent)
        self.main_win = main_win
        self._service = service
        self.setSizePolicy(QSizePolicy.Policy.Fixed,
                           QSizePolicy.Policy.Expanding)
        self.setMinimumHeight(12)
        self.setFixedWidth(self.PAD * 2 + 14)   # room for status text always
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(tr('AI usage: click to open settings'))
        self._last_prefer_labels = None
        self._initial_auto_scheduled = False
        self._result_ready.connect(self._on_data)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._auto)
        service.add_callback(
            weak_qt_callback(self, lambda w: w._result_ready.emit()))

    # -- visibility --------------------------------------------------------
    @property
    def _visible(self):
        if not hasattr(self.main_win, "data"):
            return False
        return self.main_win.data.get("limit_gauges", "False") == "True"

    def sync(self):
        """Called by the 1-second header timer — visibility + timer only."""
        visible = self._visible
        if self.isHidden() == visible:
            self.setVisible(visible)
        publish = getattr(self.main_win, "_set_topbar_semantic", None)
        if callable(publish):
            publish("limit_gauges", visible, refresh=False)
        active = visible or self._notifications_active()
        if not active:
            if self._timer.isActive():
                self._timer.stop()
            return
        prefer_labels = self._prefer_account_labels()
        if prefer_labels != self._last_prefer_labels:
            self._update_width()
            self.update()
        interval = self._refresh_interval()
        if self._timer.interval() != interval:
            self._timer.setInterval(interval)
        if not self._timer.isActive():
            self._timer.start()
        if not self._initial_auto_scheduled:
            self._initial_auto_scheduled = True
            self._service.schedule_auto(interval // 1000)

    def _refresh_interval(self) -> int:
        raw = self.main_win.data.get("limit_gauges_refresh_sec", "180")
        try:
            secs = max(30, min(3600, int(raw)))
        except (TypeError, ValueError):
            secs = 180
        return secs * 1000

    def _auto(self):
        if self._visible or self._notifications_active():
            self._service.schedule_auto(self._refresh_interval() // 1000)

    def _notifications_active(self) -> bool:
        rules = self.main_win.data.get("limit_notifications", {})
        return (isinstance(rules, dict)
                and any(isinstance(rule, dict)
                        and (rule.get("enabled") in (True, "True")
                             or rule.get("reset_enabled") in (True, "True"))
                        for rule in rules.values()))

    # -- hover card (T-1242 spec 18-20) ------------------------------------

    def hover_card(self):
        """The one application-owned hover panel (created on first hover).

        A native QToolTip cannot be entered by the pointer, so moving from
        this 12px gauge towards the panel fired ``Leave`` and hid it before
        it could be read.  The panel is a real widget now, and it closes on
        a grace timer that either surface can cancel.
        """
        card = getattr(self, "_hover_card", None)
        if card is not None and not sip_deleted(card):
            return card
        from fastprompter.ui.limit_hover_card import LimitHoverCard

        card = LimitHoverCard(self)
        self._hover_card = card
        return card

    def _shift_held(self) -> bool:
        from PyQt6.QtWidgets import QApplication
        return bool(QApplication.keyboardModifiers() & Qt.KeyboardModifier.ShiftModifier)

    def _show_hover_card(self):
        # The panel contains a live reset countdown.  Keeping the HTML
        # produced by the last probe made an old "0m" survive every later
        # hover, even after resolved_windows() knew the reset had passed.
        # Rebuild locally first; schedule_auto is asynchronous and
        # internally rate-limited, so hover never performs a synchronous
        # provider request (spec 21).
        self._service.schedule_auto(self._refresh_interval() // 1000)
        ignore_filters = self._shift_held()
        html_text = self._build_tooltip(ignore_filters=ignore_filters)
        self.setToolTip("")          # the native tooltip must never compete
        try:
            self.hover_card().show_card(html_text)
        except Exception:
            # A hover panel is never worth taking the top bar down for.
            self.setToolTip(html_text)

    def hide_hover_card(self, immediate: bool = False):
        card = getattr(self, "_hover_card", None)
        if card is None or sip_deleted(card):
            return
        if immediate:
            card.hide_now()
        else:
            card.schedule_hide()

    def refresh_hover_card(self):
        """Re-render an OPEN card from the newest snapshot; no-op otherwise.

        T-1242 spec 18/21: a content/countdown refresh must NOT reposition
        the card and must NOT call the ordinary ``reposition()`` -- the
        session geometry was pinned when the card was shown.  Only a real
        window move re-anchors (handled inside the card's own event filter).
        """
        card = getattr(self, "_hover_card", None)
        if card is None or sip_deleted(card) or not card.isVisible():
            return
        ignore_filters = self._shift_held()
        card.set_html(self._build_tooltip(ignore_filters=ignore_filters),
                      ignore_filters=ignore_filters)
        # No reposition(): horizontal geometry is frozen for the session;
        # the card keeps itself on screen only via its own height contract.

    def event(self, event):
        if event.type() in (QEvent.Type.Enter, QEvent.Type.ToolTip):
            self._show_hover_card()
            if event.type() == QEvent.Type.ToolTip:
                event.accept()
                return True
        elif event.type() == QEvent.Type.Leave:
            # Grace interval: travelling towards the card must not close it.
            self.hide_hover_card()
        elif event.type() in (QEvent.Type.Hide, QEvent.Type.Close):
            self.hide_hover_card(immediate=True)
        return super().event(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.hide_hover_card(immediate=True)
            event.accept()
            if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                styles = _STYLES
                new_style = styles[(styles.index(self._style()) + 1)
                                   % len(styles)]
                self.main_win.data["limit_gauges_style"] = new_style
                if hasattr(self.main_win, "mark_dirty"):
                    self.main_win.mark_dirty("settings")
                if hasattr(self.main_win, "play_sound"):
                    try:
                        self.main_win.play_sound(
                            "untick" if new_style == "bars" else "tick")
                    except Exception:
                        pass
                self.refresh_view()
                return
            if hasattr(self.main_win, "open_limit_settings_dialog"):
                self.main_win.open_limit_settings_dialog()
        else:
            super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            event.accept()
            self._service.refresh()

    def contextMenuEvent(self, event):
        from PyQt6.QtWidgets import QMenu
        menu = QMenu(self)

        # Reset actions come from DISCOVERED SNAPSHOTS with current offers,
        # not from _visible_accounts(): an exhausted account hidden by the
        # ordinary filters must still expose its reset (T-1360). Only an
        # explicit settings-hide removes an account's actions.
        for action in self._reset_menu_actions():
            if action.activate:
                from fastprompter.core.usage_limits.model import (
                    banked_reset_count as _count,
                )
                cnt = _count(action.snapshot)
                res_word = tr("reset") if cnt == 1 else tr("resets")
                act = menu.addAction(
                    tr("★ Activate {name} Reset ({cnt} {res_word})...").format(
                        name=action.account.display_name, cnt=cnt,
                        res_word=res_word))
                act.triggered.connect(
                    lambda checked=False, acc=action.account,
                    shot=action.snapshot: self._prompt_activate_reset(acc, shot))
            else:
                act = menu.addAction(
                    tr("★ {name} — {title} · Open {provider} Usage...").format(
                        name=action.account.display_name,
                        title=action.offers[0].title,
                        provider=action.account.provider_id.title()))
                act.triggered.connect(
                    lambda checked=False, url=action.open_url:
                    self._open_reset_page(url))
        if self._reset_menu_actions():
            menu.addSeparator()

        act_refresh = menu.addAction(tr("Refresh Limits Now"))
        act_refresh.triggered.connect(self._service.refresh)

        menu.addSeparator()

        if hasattr(self.main_win, "open_limit_settings_dialog"):
            act_settings = menu.addAction(tr("AI Limit Settings..."))
            act_settings.triggered.connect(self.main_win.open_limit_settings_dialog)

        menu.exec(event.globalPos())

    # Where a non-activatable offer sends the user: the vendor's own usage
    # surface. Codex never uses this (its redemption is proven); Claude's
    # page is its documented usage view; ZCode's is its client home, because
    # no deep link into the app's reset dialog is proven from the client.
    _RESET_OPEN_URLS = _RESET_OPEN_URLS

    def _open_reset_page(self, url: str):
        if not url:
            return
        from PyQt6.QtCore import QUrl
        from PyQt6.QtGui import QDesktopServices
        QDesktopServices.openUrl(QUrl(url))

    def _reset_menu_actions(self):
        """Menu-worthy reset state per account, from snapshots not filters.

        ``activate`` is True only when the provider's offers are directly
        redeemable in FastPrompter (Codex). Otherwise the single action opens
        the vendor's usage page — never a fake Activate button.
        """
        import collections

        rows = self._reset_rows()
        action = collections.namedtuple(
            "ResetMenuAction", "account snapshot offers activate open_url")
        out = []
        for row in rows:
            activate = any(o.redeemable_in_fastprompter for o in row.offers)
            out.append(action(row.account, row.snapshot, row.offers, activate,
                              self._RESET_OPEN_URLS.get(
                                  row.account.provider_id, "")))
        return out

    def _prompt_activate_reset(self, account, shot):
        from PyQt6.QtWidgets import QMessageBox
        banked = getattr(shot, "banked_resets", 0) or 0
        res_word = tr("reset") if banked == 1 else tr("resets")
        ans = QMessageBox.question(
            self,
            tr('Activate Rate Limit Reset'),
            tr("Activate rate limit reset for {name}?").format(
                name=account.display_name) + "\n\n"
            + tr("Available: {banked} banked {res_word}.").format(
                banked=banked, res_word=res_word)
            + "\n\n"
            + tr("This will consume 1 reset credit to immediately refill "
                 "your quota."),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if ans != QMessageBox.StandardButton.Yes:
            return

        self.setCursor(QCursor(Qt.CursorShape.WaitCursor))
        try:
            if hasattr(self._service, "consume_account_reset"):
                res = self._service.consume_account_reset(account.key)
            else:
                res = {"ok": False, "error": tr("Service does not support reset consumption")}
            if res.get("ok"):
                QMessageBox.information(
                    self,
                    tr('Reset Activated'),
                    tr("Rate limit reset activated successfully for {name}!").format(
                        name=account.display_name)
                    + "\n"
                    + tr("Outcome: {outcome}").format(
                        outcome=res.get('outcome', 'success'))
                    + "\n\n"
                    + tr("Quota has been refreshed."),
                )
            else:
                err = res.get("error") or res.get("outcome") or tr("Unknown error")
                QMessageBox.warning(
                    self,
                    tr('Reset Failed'),
                    tr("Failed to activate reset for {name}:").format(
                        name=account.display_name)
                    + "\n" + err,
                )
        except Exception as exc:
            QMessageBox.warning(
                self,
                tr('Reset Error'),
                tr("Exception while activating reset:") + "\n" + str(exc),
            )
        finally:
            self.unsetCursor()

    # -- data --------------------------------------------------------------
    def _on_data(self):
        self.setToolTip("")
        # Width first: refresh_hover_card() anchors the card to this
        # widget's geometry, so it must read the geometry this snapshot
        # produces, not the previous one's.
        self._update_width()
        self.refresh_hover_card()
        self.update()

    def refresh_view(self):
        """Apply account visibility settings immediately, without probing."""
        self._on_data()

    def _hide_unusable(self) -> bool:
        """The "show only accounts usable right now" toggle (5h available)."""
        return str(self.main_win.data.get(
            "limit_gauges_hide_unusable_5h", "False")) == "True"

    def _visible_accounts(self):
        hidden = hidden_account_keys(self.main_win.data)
        hide_zero = str(self.main_win.data.get(
            "limit_gauges_hide_zero_usage", "False")) == "True"
        hide_unusable = self._hide_unusable()
        snap = self._service.state_copy
        shown = []
        for a in snap.accounts:
            if a.key in hidden:
                continue
            shot = snap.snapshots.get(a.key)
            if shot is None or shot.status not in (OK, STALE):
                shown.append(a)
                continue
            if hide_zero and not account_has_usage(shot):
                continue
            if hide_unusable and not account_usable_now(shot):
                continue
            shown.append(a)
        return ordered_accounts(shown, self.main_win.data)

    # -- manual reset offers (T-1360) --------------------------------------
    # Reset offers are exceptional state the user can ACT on: they stay
    # visible even when every usage account is hidden by the ordinary
    # hide-zero / hide-unusable filters (an exhausted account is exactly the
    # one holding a reset). Only the explicit settings-hide excludes an
    # account, and no Shift is required to see them.

    def _reset_rows(self, now: float | None = None):
        """Current offers per account, independent of the bar filters."""
        snap = self._service.state_copy
        hidden = hidden_account_keys(self.main_win.data)
        return reset_offer_rows(snap.snapshots, hidden_keys=hidden, now=now)

    def _reset_badge_text(self) -> str:
        """Compact topbar aggregate, e.g. ``★ 3``; empty when none."""
        snap = self._service.state_copy
        hidden = hidden_account_keys(self.main_win.data)
        count = manual_reset_count(snap.snapshots, hidden_keys=hidden)
        return f"★ {count}" if count else ""

    def _status_marker(self, accounts=None, snap=None) -> str:
        """Only exceptional state earns header space; counts are redundant.

        A provider that is *designed* to stay silent until it has a fact (see
        ``EXPECTED_QUIET_CODES``) is not exceptional: treating Antigravity's
        resting "no refusal recorded" as an error would pin the ``!`` on
        permanently with nothing for the user to fix.
        """
        snap = snap or self._service.state_copy
        accounts = self._visible_accounts() if accounts is None else accounts
        keys = {account.key for account in accounts}
        for key, value in snap.snapshots.items():
            if key not in keys:
                continue
            if getattr(value, "status", None) in (OK, STALE):
                continue
            if getattr(value, "error_code", "") in EXPECTED_QUIET_CODES:
                continue
            return "!"
        return ""

    def _status_width(self, accounts=None, snap=None) -> int:
        return self.STATUS_W if self._status_marker(accounts, snap) else 0

    def _bars_for(self, account) -> int:
        """Marks this ONE account actually draws.

        Width used to be reserved as ``_max_bars()`` per account — the widest
        cluster on screen, applied to every account alike. With one Antigravity
        account reporting four windows and everything else two, that reserved
        twenty slots to paint twelve, and the eight unpainted ones became a
        visible dead strip between the gauge and the reset countdown. Reserving
        what each cluster paints is the only way the two can agree.
        """
        if account is None:
            return self._max_bars()
        snap = self._service.state_copy
        drawn = len(_cluster_windows(snap.snapshots.get(account.key),
                                     self._hide_unusable()))
        return max(self.MIN_BARS, min(drawn, self.MAX_BARS))

    def _max_bars(self) -> int:
        """Widest cluster across all accounts — the per-account upper bound."""
        snap = self._service.state_copy
        widest = self.MIN_BARS
        for a in self._visible_accounts():
            widest = max(widest, len(_cluster_windows(
                snap.snapshots.get(a.key), self._hide_unusable())))
        return min(widest, self.MAX_BARS)

    def _style(self) -> str:
        value = str(self.main_win.data.get("limit_gauges_style", "bars"))
        return value if value in _STYLES else "bars"

    def _vendor_tint(self) -> bool:
        """Tint a live fill towards its vendor's own colour.

        The reset countdown already identifies the vendor by colour; the bars
        pick up the same hue, but only a MUTED share of it, so the quota signal
        (gold healthy / olive low / red critical) still reads first.
        """
        return str(self.main_win.data.get(
            "limit_gauges_vendor_tint", "True")) == "True"

    def _fill_mode(self) -> str:
        """``remaining`` = drains like fuel, ``used`` = grows like progress."""
        value = str(self.main_win.data.get("limit_gauges_fill", "remaining"))
        return value if value in ("remaining", "used") else "remaining"

    def _fill_fraction(self, rem) -> float:
        """How much of the mark is inked, 0..1, per the user's fill mode."""
        if not isinstance(rem, (int, float)):
            return 0.0
        fraction = max(0.0, min(1.0, float(rem) / 100.0))
        return fraction if self._fill_mode() == "remaining" else 1.0 - fraction

    def _unit_width(self) -> int:
        if self._style() == "dots":
            return self.DOT_D
        if self._style() == "stack":
            return self.STACK_BAR_W
        return self.BAR_W

    def _marks_width(self, account=None) -> int:
        """Pixels this account's marks occupy, inner gaps included.

        ``bars``/``dots`` lay the windows out side by side, so the width grows
        with the window count. ``stack`` lays them out on top of each other, so
        one column is one bar wide no matter how many windows an account has —
        the whole point of the style.
        """
        if self._style() == "stack":
            return self.STACK_BAR_W
        bars = self._bars_for(account)
        return bars * (self._unit_width() + self.GAP_PAIR) - self.GAP_PAIR

    def _stack_metrics(self, area_h: int):
        """``(row_h, gap)`` for a stacked column inside ``area_h`` pixels.

        Derived from MAX_BARS, never from the account's own window count, so
        every account's rows land on the same grid and a one-window account
        keeps its single bar on the shared bottom row instead of stretching it.
        Guaranteed to fit: ``MAX_BARS * row_h + (MAX_BARS - 1) * gap <= area_h``.
        """
        rows = max(1, self.MAX_BARS)
        gap = self.STACK_GAP
        row_h = (area_h - (rows - 1) * gap) // rows
        if row_h < 2:            # too short for gaps — spend every pixel on ink
            gap = 0
            row_h = area_h // rows
        return max(1, row_h), gap

    def _account_label_width(self, account=None) -> int:
        if account is None:
            return self.ACCOUNT_LABEL_W
        text = short_account_label(account, self.main_win.data)
        if not text:
            return 0
        return min(52, max(self.ACCOUNT_LABEL_W,
                           self.fontMetrics().horizontalAdvance(text) + 2))

    def _cluster_width(self, with_label=True, account=None) -> int:
        """Pixels one account's cluster occupies, marks it really draws.

        ``account=None`` still budgets the widest cluster, which is what the
        overflow arithmetic needs when it reasons about anonymous slots.
        """
        return ((self._account_label_width(account) if with_label else 0)
                + self._marks_width(account) + self.GAP_ACC)

    def _prefer_account_labels(self) -> bool:
        """Ultra-narrow headers spend pixels on gauges, not account initials."""
        enabled = str(self.main_win.data.get(
            "limit_gauges_show_labels", "False")) == "True"
        return enabled and not bool(
            getattr(self.main_win, "_header_ultra", False))

    def _clusters_width(self, accounts, with_label) -> int:
        """Pixels the whole cluster row occupies, trailing air excluded.

        ONE definition, shared by the width reservation and the fit check. When
        they disagreed by the last cluster's ``GAP_ACC`` the widget reserved 20
        px, the fit check demanded 22, concluded nothing fitted, and painted the
        overflow marker ``+2`` where the bars should have been — the gauge
        stopped showing quota at all.
        """
        widths = [self._cluster_width(with_label, account)
                  for account in accounts]
        if not widths:
            return 0
        # The last cluster's GAP_ACC separates it from a NEXT cluster; there is
        # none, so it is trailing air either way.
        return sum(widths) - self.GAP_ACC

    def _fit_layout(self, available_width: int, accounts_or_count):
        """Return ``(labels, cluster_width, count_fit)`` for current pixels.

        Labels are the first thing shed.  An overflow marker is reserved only
        when even unlabeled clusters cannot all fit, so a marker never replaces
        an account that would fit after dropping ``CL/C1/...``.

        Clusters are measured individually: they are no longer all the same
        width (an account reporting four windows is wider than one reporting
        two), so the count that fits is taken by accumulating real widths rather
        than dividing by an average that matches nobody.
        """
        if isinstance(accounts_or_count, int):
            accounts = [None] * accounts_or_count
        else:
            accounts = list(accounts_or_count)
        account_count = len(accounts)
        plain_widths = [self._cluster_width(False, account)
                        for account in accounts]
        labeled = max((self._cluster_width(True, account)
                       for account in accounts),
                      default=self._cluster_width(True))
        plain = max(plain_widths, default=self._cluster_width(False))
        show_labels = (self._prefer_account_labels()
                       and self._clusters_width(accounts, True) <= available_width)
        per_cluster = labeled if show_labels else plain
        if self._clusters_width(accounts, show_labels) <= available_width:
            return show_labels, per_cluster, account_count
        marker_width = 16  # enough for +1..+99 in the compact header font
        budget = available_width - marker_width
        count_fit = 0
        for index, width in enumerate(plain_widths):
            # Same convention as _clusters_width: the final cluster drawn needs
            # no trailing GAP_ACC, so it is not charged for one.
            need = width - (self.GAP_ACC if index == len(plain_widths) - 1 else 0)
            if budget - need < 0:
                break
            budget -= need
            count_fit += 1
        return False, plain, min(account_count, count_fit)

    def _reset_badge_width(self) -> int:
        """Pixels the ★ aggregate needs; 0 when there is nothing to show."""
        text = self._reset_badge_text()
        if not text:
            return 0
        return self.fontMetrics().horizontalAdvance(text) + self.GAP_ACC

    def _update_width(self):
        """Size the widget to the ink, so no dead strip trails the gauge.

        The header lays widgets out left to right with no stretch between the
        gauge and the reset countdown, so every pixel reserved here and not
        painted shows up as a gap between them.
        """
        self._last_prefer_labels = self._prefer_account_labels()
        accounts = self._visible_accounts()
        if not accounts and self._has_any_accounts():
            # Only the painted neutral indicator owns width when filtered.
            clusters = self._placeholder_width()
        else:
            clusters = self._clusters_width(accounts, self._last_prefer_labels)
        w = (self.PAD * 2 + self._status_width(accounts) + clusters
             + self._reset_badge_width())
        w = min(w, self.MAX_WIDGET_W)
        target = w if not accounts and self._has_any_accounts() else max(self.PAD * 2 + 14, w)
        if self.width() != target:
            self.setFixedWidth(target)
            self.updateGeometry()
            parent = self.parentWidget()
            if parent is not None:
                layout = parent.layout()
                if layout is not None:
                    layout.invalidate()

    def _has_any_accounts(self) -> bool:
        """True when the service knows about accounts at all (filter or not).

        Distinguishes "every account hidden by the 5h/0% filter" from "no
        accounts configured": the first keeps a placeholder, the second is a
        genuinely empty gauge.
        """
        return bool(getattr(self._service.state_copy, "accounts", None))

    def _placeholder_width(self) -> int:
        """Actual ink advance; no invisible account or cluster gutter."""
        return self.fontMetrics().horizontalAdvance("0")

    def _paint_all_filtered(self, p, x, y, h, pal):
        """Accounts exist but every one was hidden (hide 5h/0% / unusable).

        The user asked for no GAP when no quota is usable right now: instead
        of a blank hole between the timers, paint a dim all-empty cluster so
        the gauge reads as present-but-empty. Every mark stays dim.
        """
        snap = self._service.state_copy
        if not getattr(snap, "accounts", None):
            return
        p.setFont(self.font())
        p.setPen(QPen(pal["dim"], 1))
        p.drawText(x, y, self._placeholder_width(), h, Qt.AlignmentFlag.AlignVCenter, "0")

    # -- tooltip -----------------------------------------------------------
    #: Nothing rendered into the hover card may exceed these lengths.  A
    #: provider error is vendor text of unbounded length -- one raw
    #: "rateLimits error: {...GET https://...}" line stretched the panel
    #: past the screen edge and clipped every reset column.
    ERROR_CHARS = 72
    NAME_CHARS = 26
    LABEL_CHARS = 30
    LIST_CHARS = 96

    @staticmethod
    def _elide(text: str, limit: int) -> str:
        """Bound one string; the full value stays in the settings dialog."""
        value = str(text or "")
        if len(value) <= limit:
            return value
        return value[: max(1, limit - 1)].rstrip() + "…"

    def _build_tooltip(self, ignore_filters: bool | None = None) -> str:
        if ignore_filters is None:
            ignore_filters = self._shift_held()
        snap = self._service.state_copy
        tooltip_now = time.time()
        pal = self._palette()
        good_col = pal["good"].name()
        warn_col = pal["warn"].name()
        bad_col = pal["bad"].name()
        stale_col = pal["stale"].name()
        dim_col = pal["dim"].name()
        track_col = "#383122" if pal.get("track", None) is None or pal["track"].name() in ("#1a1810", "#000000", "#1a1a1a") else pal["track"].name()

        def _color_for(rem, status):
            if status == STALE:
                return stale_col
            if not isinstance(rem, (int, float)):
                return dim_col
            if rem < 20:
                return bad_col
            if rem < 50:
                return warn_col
            return good_col

        def _render_bar(rem, color_hex, blocks=10):
            if rem is None or not isinstance(rem, (int, float)):
                return f"<span style='color:{track_col}; font-family:Consolas, monospace; font-size:11px;'>{'█' * blocks}</span>"
            clamped = max(0.0, min(100.0, float(rem)))
            filled = int(round((clamped / 100.0) * blocks))
            empty = blocks - filled
            f_str = "█" * filled
            e_str = "█" * empty
            return (f"<span style='color:{color_hex}; font-family:Consolas, monospace; font-size:11px;'>{f_str}</span>"
                    f"<span style='color:{track_col}; font-family:Consolas, monospace; font-size:11px;'>{e_str}</span>")

        def _reset_snippet(b):
            if b.gated_by:
                return (f"<span style='color:{bad_col};'>" + tr("— blocked by ")
                        + _win_label(b.gated_by) + "</span>")
            if b.resets_at_epoch:
                import datetime
                try:
                    t = datetime.datetime.fromtimestamp(b.resets_at_epoch)
                    remaining = b.resets_at_epoch - tooltip_now
                    if remaining <= 0:
                        r_text = tr("resets now")
                    elif remaining < 60:
                        r_text = tr("resets in &lt;1m")
                    elif remaining < 3600:
                        r_text = tr("resets in {mins}m").format(
                            mins=math.ceil(remaining / 60))
                    elif remaining < 86400:
                        r_text = tr("resets in {hours}h").format(
                            hours=int(remaining // 3600))
                    else:
                        r_text = tr("resets {when}").format(
                            when=t.strftime('%a %H:%M'))
                    return f"<span style='color:#9e9479;'>— {r_text}</span>"
                except Exception:
                    pass
            return ""

        def _snapshot_age(s):
            fetched = getattr(s, "fetched_at", None)
            if not isinstance(fetched, (int, float)) or fetched <= 0:
                return ""
            age = max(0, tooltip_now - fetched)
            if age < 60:
                return tr("updated now")
            if age < 3600:
                return tr("updated {mins}m ago").format(mins=int(age // 60))
            if age < 86400:
                return tr("updated {hours}h ago").format(hours=int(age // 3600))
            return tr("updated {days}d ago").format(days=int(age // 86400))

        def _resets_section() -> str:
            """The manual-reset panel — independent of the bar filters.

            Rendered exactly once per tooltip, with or without Shift: the
            section is exceptional state, not extra detail. Not named "Next
            reset" on purpose: that phrase is the automatic refill timing.
            """
            rows = self._reset_rows(now=tooltip_now)
            if not rows:
                return ""
            chunk = [
                "<div style='font-weight:bold; font-size:12px; color:#ffd700; "
                "border-bottom:1px solid #5a4f32; padding-bottom:2px; "
                "margin-top:6px; margin-bottom:3px;'>"
                + tr("Resets") + "</div>",
            ]
            for row in rows:
                name = html.escape(self._elide(
                    account_display_name(row.account, self.main_win.data),
                    self.NAME_CHARS))
                v_color = reset_color(
                    self.main_win, getattr(row.account, "provider_id", ""))
                name_style = (f" style='color:{v_color};'"
                              if v_color else "")
                for offer in row.offers:
                    title = html.escape(self._elide(
                        offer.title or tr("reset"), self.LABEL_CHARS))
                    chunk.append(
                        f"<div style='padding-top:2px;'>"
                        f"<span style='color:#4FB6A8; font-weight:bold;'>★</span> "
                        f"<b{name_style}>{name}</b> — {title}</div>")
                    expiry = format_offer_expiry(
                        offer.expires_at_epoch, now=tooltip_now)
                    if expiry:
                        chunk.append(
                            f"<div style='color:#77705d; font-size:10px; "
                            f"padding-left:14px;'>{expiry}</div>")
            return "".join(chunk)

        if ignore_filters:
            accounts = ordered_accounts(list(snap.accounts), self.main_win.data)
            hidden = []
        else:
            accounts = self._visible_accounts()
            hidden = [a for a in snap.accounts if a not in accounts]

        shift_tag = (
            " <span style='font-weight:normal; font-size:10px; color:#4FB6A8;'>("
            + tr("all accounts — Shift held") + ")</span>"
            if ignore_filters else
            " <span style='font-weight:normal; font-size:10px; color:#9a8b5f;'>("
            + tr("remaining") + ")</span>")
        parts = [
            "<html><body style='font-family:Verdana, Segoe UI, sans-serif; font-size:11px; color:#c0c0c0;'>",
            "<div style='font-weight:bold; font-size:12px; color:#ffd700; border-bottom:1px solid #5a4f32; padding-bottom:2px; margin-bottom:3px;'>",
            tr("AI Usage Limits") + shift_tag,
            "</div>"
        ]

        if not accounts:
            if self._has_any_accounts():
                filter_active = (self._hide_unusable() or str(self.main_win.data.get(
                    "limit_gauges_hide_zero_usage", "False")) == "True")
                if filter_active:
                    parts.append(
                        "<div style='color:#888888; font-style:italic;'>"
                        + tr("no accounts usable right now (hide 5h/0% filter)")
                        + "</div>")
                else:
                    parts.append(
                        "<div style='color:#888888; font-style:italic;'>"
                        + tr("all accounts hidden in settings") + "</div>")
                manually_hidden = [a for a in snap.accounts
                                   if a.key in hidden_account_keys(self.main_win.data)]
                if manually_hidden:
                    parts.append(
                        "<div style='color:#666666; font-size:10px;'>"
                        + tr("hidden in settings: {n}").format(
                            n=len(manually_hidden)) + "</div>")
            else:
                parts.append(
                    "<div style='color:#888888; font-style:italic;'>"
                    + tr("no accounts selected") + "</div>")
            parts.append(_resets_section())
            parts.append("</body></html>")
            return "".join(parts)

        parts.append(
            "<table cellspacing='0' cellpadding='1' "
            "style='margin-left:2px; border-collapse:collapse;'>"
        )

        # Two slots on ONE Google account read as two rows of quota here, and
        # this hover card is where an operator forms the "how much capacity do
        # I have" impression. The cluster marks stay one-per-slot on purpose:
        # merging them means rewriting the width reservation, which is the one
        # piece of this widget that has already broken quota display once (see
        # _clusters_width). So the accounting is corrected in words instead -- a
        # shared row names the peer it shares with, and the reading is qualified
        # rather than contradicted.
        report = getattr(self._service, "identity_report", None)
        shared = report().get("shared_with", {}) if callable(report) else {}
        peer_names = {
            a.key: html.escape(self._elide(
                account_display_name(a, self.main_win.data), self.NAME_CHARS))
            for a in accounts}

        pools_getter = getattr(self._service, "quota_pools", None)
        quota_pools = pools_getter(accounts) if callable(pools_getter) else []
        pool_by_key = {}
        for p in quota_pools:
            if len(p.member_keys) > 1:
                for k in p.member_keys:
                    pool_by_key[k] = p
        rendered_pools = set()

        for a in accounts:
            if a.key in pool_by_key:
                p = pool_by_key[a.key]
                if p.pool_id not in rendered_pools:
                    rendered_pools.add(p.pool_id)
                    p_name = _PROVIDER_LABEL.get(getattr(a, "provider_id", ""), getattr(a, "provider_id", "").title())
                    parts.append(
                        f"<tr><td colspan='4' style='padding-top:6px; padding-bottom:2px; border-bottom:1px solid #776a3a;'>"
                        f"<b style='color:#e0b43c;'>[{tr('Shared Provider Quota Pool')}: {p_name}]</b> "
                        f"<span style='color:#9a8b5f; font-size:10px;'>({len(p.member_keys)} {tr('linked contexts')})</span></td></tr>"
                    )

            s = snap.snapshots.get(a.key)
            header = html.escape(self._elide(
                account_display_name(a, self.main_win.data), self.NAME_CHARS))
            peer_key = shared.get(a.key, "")
            shared_note = (
                " <span style='color:#9a8b5f; font-size:10px;'>("
                + tr("Same provider account as")
                + " " + peer_names.get(peer_key, html.escape(peer_key))
                + ")</span>") if peer_key else ""
            v_color = reset_color(self.main_win, getattr(a, "provider_id", ""))
            title_style = f" style='color:{v_color};'" if v_color else ""
            if not s:
                parts.append(
                    f"<tr><td colspan='4' style='padding-top:4px; padding-bottom:2px;'>"
                    f"<b{title_style}>{header}</b>{shared_note}: "
                    f"<span style='color:#888888;'>"
                    + tr("not probed yet") + "</span></td></tr>"
                )
                continue

            plan = (f" <span style='color:#8f856c; font-size:10px;'>"
                    f"({html.escape(self._elide(s.plan_type, 18))})</span>"
                    if s.plan_type else "")
            stale = (f" <span style='color:{stale_col}; font-size:10px;'>"
                     + tr("[stale]") + "</span>") if s.status == STALE else ""
            age = _snapshot_age(s)
            freshness = (f" <span style='color:#77705d; font-size:9px;'>"
                         f"[{age}]</span>" if age else "")
            banked = ""
            from fastprompter.core.usage_limits.model import banked_reset_count
            reset_count = banked_reset_count(s, now=tooltip_now)
            if reset_count:
                res_word = tr("reset") if reset_count == 1 else tr("resets")
                banked = (" <span style='color:#4FB6A8; font-size:10px; "
                          "font-weight:bold;'>"
                          + tr("[{n} {res_word}]").format(
                              n=reset_count, res_word=res_word) + "</span>")

            # Freebuff total spendable (daily + wallet) as one amount pill, the
            # vendor's own quick-glance number; the detail rows below explain
            # it. Only an OK/STALE snapshot may show it — an error or auth
            # failure proves nothing, and a stale total wears the stale tint.
            fb_badge = ""
            fb_total = (spendable_total(s) if s.status in (OK, STALE)
                        else None)
            if fb_total is not None:
                pill_fg, pill_bg = (("#1a1810", stale_col) if s.status == STALE
                                    else ("#1a1810", "#e0b43c"))
                fb_badge = (f" <span style='background-color:{pill_bg}; "
                            f"color:{pill_fg}; font-size:10px; "
                            f"font-weight:bold;'>&nbsp;{format_amount(fb_total)}"
                            f"&nbsp;</span>")
            parts.append(
                f"<tr><td colspan='4' style='padding-top:5px; padding-bottom:2px; border-bottom:1px solid #4a3e28;'><b{title_style}>{header}</b>{shared_note}{plan}{fb_badge}{stale}{freshness}{banked}</td></tr>"
            )

            if s.status in (OK, STALE):
                windows = _cluster_windows(s, False if ignore_filters else self._hide_unusable())
                readable = False
                for b in windows:
                    if b is not None and b.reset_pending:
                        parts.append(
                            "<tr><td colspan='4'>"
                            + tr("Reset time passed; refresh to check "
                                 "current limits") + "</td></tr>")
                        readable = True
                    if b is None or not b.available:
                        continue
                    readable = True
                    pool = (html.escape(self._elide(b.group_label,
                                                    self.LABEL_CHARS))
                            if b.group_label else "")
                    w_lbl = html.escape(_win_label(b, a.provider_id))
                    if pool:
                        clean_pool = pool.replace(" and ", " & ").replace(" models", "").replace(" Models", "")
                        lbl_text = f"{clean_pool} {w_lbl}:"
                    else:
                        lbl_text = f"{w_lbl}:"
                    rem = b.remaining_percent
                    col = _color_for(rem, s.status)
                    bar_html = _render_bar(rem, col)
                    unit = getattr(b, "unit", "") or ""
                    rem_amount = getattr(b, "remaining_amount", None)
                    limit_amount = getattr(b, "limit_amount", None)
                    if unit and isinstance(rem_amount, (int, float)) \
                            and isinstance(limit_amount, (int, float)):
                        # AMOUNT window: the vendor's exact numbers, never a
                        # naked percent of an abstract budget.
                        pct_str = (f"{int(round(rem_amount))}/"
                                   f"{int(round(limit_amount))} {unit}")
                    else:
                        pct_str = (f"{int(round(rem))}%"
                                   if isinstance(rem, (int, float)) else "--")
                    reset_str = _reset_snippet(b)

                    parts.append(
                        f"<tr>"
                        f"<td style='color:#d8ccaa; padding-left:2px; padding-right:6px; white-space:nowrap;'>{lbl_text}</td>"
                        f"<td style='padding-right:4px; white-space:nowrap; vertical-align:middle;'>{bar_html}</td>"
                        f"<td style='color:{col}; font-weight:bold; padding-right:6px; white-space:nowrap;'>{pct_str}</td>"
                        f"<td width='99%' style='white-space:nowrap;'>{reset_str}</td>"
                        f"</tr>"
                    )
                if not readable and not banked_reset_count(s, now=tooltip_now):
                    parts.append(
                        "<tr><td colspan='4' style='color:#777777; "
                        "font-style:italic; padding-left:6px;'>"
                        + tr("no readable quota window") + "</td></tr>")
                meta = getattr(s, "provider_metadata", None) or {}
                wallet = meta.get("wallet_balance")
                if isinstance(wallet, (int, float)) and wallet > 0:
                    # Wallet is a BALANCE badge: no meter, no reset — it never
                    # expires, so a progress bar would be a lie.
                    bonus = meta.get("wallet_monthly_bonus")
                    hint = (tr(" (adds {n}/month)").format(n=int(bonus))
                            if isinstance(bonus, (int, float)) and bonus > 0 else "")
                    parts.append(
                        "<tr><td colspan='4' style='color:#d8ccaa; padding-left:4px; font-size:10px; padding-top:2px;'>"
                        + tr("Wallet: <b>{n} FB</b> · never expires{hint}").format(
                            n=int(wallet), hint=hint) + "</td></tr>"
                    )
                prices = meta.get("model_prices") or {}
                if isinstance(prices, dict) and prices:
                    # T-1243: the model catalogue does NOT belong in a hover
                    # panel -- dozens of names made the card enormous and
                    # mostly empty.  One line here; the full Model/FB-hour
                    # table lives in AI Limit Settings.
                    buckets = price_buckets(prices)
                    span = ""
                    if buckets:
                        low = format_price(buckets[0][0])
                        high = format_price(buckets[-1][0])
                        span = f" · {low}-{high} FB/h" if low != high else \
                            f" · {low} FB/h"
                    model_line = tr("{n} model prices{span} — see AI Limit "
                                    "Settings").format(n=len(prices), span=span)
                    parts.append(
                        "<tr><td colspan='4' style='color:#77705d; "
                        "font-size:10px; padding-left:4px;'>"
                        + model_line + "</td></tr>")
                if not readable and not getattr(s, "banked_resets", None):
                    parts.append(
                        "<tr><td colspan='4' style='color:#777777; "
                        "font-style:italic; padding-left:6px;'>"
                        + tr("no readable quota window") + "</td></tr>")
                for advice in reserve_advice(s):
                    parts.append(
                        f"<tr><td colspan='4' style='color:#4FB6A8; font-size:10px; "
                        f"padding-left:6px; padding-bottom:2px;'>→ {html.escape(advice)}</td></tr>")
            else:
                err = html.escape(self._elide(
                    s.error_summary or tr("unavailable"), self.ERROR_CHARS))
                parts.append(
                    f"<tr><td colspan='4' style='color:{bad_col}; "
                    f"padding-left:6px;'>{s.status.lower()} — {err}</td></tr>")

        parts.append("</table>")

        parts.append(_resets_section())

        if hidden:
            h_names = html.escape(self._elide(
                ", ".join(account_display_name(a, self.main_win.data)
                          for a in hidden), self.LIST_CHARS))
            parts.append(
                "<div style='margin-top:6px; font-size:10px; color:#666666; "
                "border-top:1px dotted #3e382b; padding-top:3px;'>"
                + tr("Hidden: {names}").format(names=h_names) + "</div>")

        content_w = max(0, self.width() - self.PAD * 2 - self._status_width(accounts, snap))
        _labels, _per_cluster, count_fit = self._fit_layout(content_w, accounts)
        if count_fit < len(accounts):
            parts.append(
                "<div style='font-size:10px; color:#8a8067; margin-top:2px;'>"
                + tr("+{n} more selected accounts than fit in the header").format(
                    n=len(accounts) - count_fit) + "</div>")

        parts.append(
            "<div style='font-size:10px; color:#77705d; margin-top:5px; "
            "border-top:1px dotted #3e382b; padding-top:2px;'>"
            + tr("Click: Settings • Ctrl+Click: Bars / Dots / Stacked")
            + "</div>")
        parts.append("</body></html>")
        return "".join(parts)

    # -- painting ----------------------------------------------------------
    def _palette(self):
        """Every colour the gauge paints — user-settable (see limit_colors)."""
        return limit_palette(self.main_win)

    def paintEvent(self, _event):
        p = QPainter(self)
        try:
            p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
            pal = self._palette()
            w, h = self.width(), self.height()
            p.fillRect(self.rect(), pal["bg"])
            if h < 8:
                return
            bar_h = h - 6
            snap = self._service.state_copy
            accounts = self._visible_accounts()
            x = self.PAD
            marker = self._status_marker(accounts, snap)
            if marker:
                p.setPen(QPen(pal["dim"], 1))
                p.drawText(x, 2, self.STATUS_W, bar_h,
                           Qt.AlignmentFlag.AlignVCenter, marker)
                x += self.STATUS_W
            if not accounts:
                if self._has_any_accounts():
                    self._paint_all_filtered(p, x, 2, bar_h, pal)
                self._paint_reset_badge(p, pal)
                return
            avail_w = max(0, w - x - self.PAD)
            show_labels, _per_cluster, n_fit = self._fit_layout(
                avail_w, accounts)
            overflow = len(accounts) > n_fit
            for a in accounts[:n_fit]:
                s = snap.snapshots.get(a.key)
                if show_labels:
                    account_label = short_account_label(a, self.main_win.data)
                    label_width = self._account_label_width(a)
                    if label_width:
                        v_col = reset_color(self.main_win, getattr(a, "provider_id", ""))
                        pen_col = QColor(v_col) if v_col else pal["dim"]
                        p.setPen(QPen(pen_col, 1))
                        p.drawText(x, 2, label_width - 1, bar_h,
                                   Qt.AlignmentFlag.AlignVCenter,
                                   account_label)
                        x += label_width
                if self._style() == "stack":
                    self._draw_stack(p, x, 2, bar_h, s, pal, a)
                    x += self._marks_width(a) + self.GAP_ACC
                    continue
                for b in _cluster_windows(s, self._hide_unusable()):
                    rem, mode = _mark_state(s, b)
                    if self._style() == "dots":
                        self._draw_dot(p, x, 2, bar_h, rem, pal, mode, a)
                    else:
                        self._draw_bar(p, x, 2, bar_h, rem, pal, mode, a)
                    x += self._unit_width() + self.GAP_PAIR
                x += self.GAP_ACC - self.GAP_PAIR
            if overflow:
                omitted = len(accounts) - n_fit
                p.setPen(QPen(pal["dim"], 1))
                p.drawText(x + 1, 2, w - x - 2, bar_h,
                           Qt.AlignmentFlag.AlignVCenter, f"+{omitted}")
            self._paint_reset_badge(p, pal)
        finally:
            p.end()

    def _paint_reset_badge(self, p, pal):
        """The ★ N manual-reset aggregate, right of the quota marks.

        Painted in BOTH states — accounts visible or all filtered — because
        reset offers are independent of the usage filters (T-1360)."""
        text = self._reset_badge_text()
        if not text:
            return
        width = self.fontMetrics().horizontalAdvance(text)
        x = max(self.PAD, self.width() - self.PAD - width)
        p.setFont(self.font())
        p.setPen(QPen(QColor("#4FB6A8"), 1))
        p.drawText(x, 2, width, self.height() - 4,
                   Qt.AlignmentFlag.AlignVCenter, text)

    def _draw_bar(self, p, x, y, h, rem, pal, mode, account=None):
        edge = pal["edge"] if mode == "live" else pal["dim"]
        p.setPen(QPen(edge, 1))
        p.drawRect(x, y, self.BAR_W - 1, h - 1)
        # The colour always follows what is LEFT, whichever end is inked: a
        # nearly-empty quota has to read as red in both fill modes.
        if mode in ("live", "stale") and isinstance(rem, (int, float)):
            fill_h = int(round((h - 2) * self._fill_fraction(rem)))
            if fill_h > 0:
                color = (pal["stale"] if mode == "stale"
                         else self._bar_color(rem, pal, account))
                p.fillRect(x + 1, y + h - 1 - fill_h,
                           self.BAR_W - 2, fill_h, color)
        if mode == "stale":
            p.setPen(QPen(pal["stale"], 1))
            p.drawLine(x, y + h - 3, x + self.BAR_W - 1, y + 1)

    def _draw_stack(self, p, x, y, h, snap, pal, account=None):
        """One account as a column of horizontal bars, filled left to right.

        Bottom-anchored on the shared MAX_BARS grid: with a single window the
        bar sits on the bottom row rather than floating in the middle, so a
        1-bar account and a 4-bar account share a baseline and the row reads as
        the foot of an L. Row 0 (the provider's first window, normally 5h) is
        the bottom one and later windows stack upwards.
        """
        row_h, gap = self._stack_metrics(h)
        w = self.STACK_BAR_W
        rows = _cluster_windows(snap, self._hide_unusable())[:self.MAX_BARS]
        if any(b is not None for b in rows):
            # The MIN_BARS padding exists to keep side-by-side clusters the same
            # WIDTH; a stacked column is one bar wide either way, so a
            # single-window account draws exactly one bar on the bottom row.
            rows = [b for b in rows if b is not None]
        for i, b in enumerate(rows):
            rem, mode = _mark_state(snap, b)
            row_y = y + h - (i + 1) * row_h - i * gap
            if row_y < y:
                break
            self._draw_hbar(p, x, row_y, w, row_h, rem, pal, mode, account)

    def _draw_hbar(self, p, x, y, w, h, rem, pal, mode, account=None):
        edge = pal["edge"] if mode == "live" else pal["dim"]
        p.setPen(QPen(edge, 1))
        p.drawRect(x, y, w - 1, h - 1)
        if mode not in ("live", "stale") or not isinstance(rem, (int, float)):
            return
        color = (pal["stale"] if mode == "stale"
                 else self._bar_color(rem, pal, account))
        fraction = self._fill_fraction(rem)
        if h >= 3:
            fill_w = int(round((w - 2) * fraction))
            if fill_w > 0:
                p.fillRect(x + 1, y + 1, fill_w, h - 2, color)
        else:
            # Too thin for an inset: ink the row itself, outline and all.
            fill_w = int(round(w * fraction))
            if fill_w > 0:
                p.fillRect(x, y, fill_w, h, color)

    def _draw_dot(self, p, x, y, h, rem, pal, mode, account=None):
        d = min(self.DOT_D, max(4, h))
        cy = y + max(0, (h - d) // 2)
        edge = pal["edge"] if mode == "live" else pal["dim"]
        p.setPen(QPen(edge, 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(x, cy, d - 1, d - 1)
        if isinstance(rem, (int, float)) and mode in ("live", "stale"):
            fill = self._fill_fraction(rem)
            color = pal["stale"] if mode == "stale" \
                else self._bar_color(rem, pal, account)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(color)
            p.drawPie(x + 1, cy + 1, d - 3, d - 3,
                      90 * 16, int(round(fill * 360 * 16)))
            p.setBrush(Qt.BrushStyle.NoBrush)

    def _bar_color(self, rem, pal, account=None):
        if not isinstance(rem, (int, float)):
            return pal["dim"]
        if rem < 20:
            base = pal["bad"]
        elif rem < 50:
            base = pal["warn"]
        else:
            base = pal["good"]
        return self._vendor_tinted(base, account)

    def _vendor_tinted(self, color, account):
        """``color`` nudged towards the account's vendor hue, or unchanged.

        A MUTED share only (``VENDOR_TINT``): the quota level must still be the
        first thing the bar says, so Claude's terracotta and Codex's blue are an
        accent on top of gold/olive/red, never a replacement for them.
        """
        provider = getattr(account, "provider_id", "") or ""
        if not provider or not self._vendor_tint():
            return color
        vendor_hex = reset_color(self.main_win, provider)
        if not vendor_hex:
            return color
        vendor = QColor(vendor_hex)
        if not vendor.isValid():
            return color
        share = self.VENDOR_TINT
        return QColor(
            int(round(color.red() * (1 - share) + vendor.red() * share)),
            int(round(color.green() * (1 - share) + vendor.green() * share)),
            int(round(color.blue() * (1 - share) + vendor.blue() * share)))


def _mark_state(snap, window):
    """``(remaining_percent, mode)`` for ONE mark.

    One definition for every style: the vertical bars, the dots and the stacked
    rows all have to agree on when a window is live, stale or a dim placeholder.
    """
    if snap is None or window is None:
        return None, "dim"
    if snap.status == STALE:
        return (window.remaining_percent if window.available else None), "stale"
    if snap.status == OK and window.available:
        return window.remaining_percent, "live"
    return None, "dim"


def _cluster_windows(snap, filter_dead_pools: bool = False) -> list:
    """Bars to draw for one account — one per window the provider reported.

    An unprobed account yields ``MIN_BARS`` dim placeholders so its cluster
    keeps the same footprint as its neighbours; a plan reporting a single
    window (Codex Free: 30-day) is not padded up to a fake second bar, it
    simply renders one and the padding keeps the cluster readable.

    Windows are resolved here too: a snapshot that reached the widget without
    passing through the service (a test, a stale cached object) must still
    show a 5h bar as empty while the weekly window is exhausted, and full
    once its own reset time has passed.

    ``filter_dead_pools`` drops the windows of quota pools in which EVERY
    window is spent ("hide 0/0" — the Antigravity pool rule), so a dead
    Gemini pool's two 0% bars disappear while a live Claude/GPT pool keeps
    its own.
    """
    if snap is None:
        return [None] * _MIN_BARS
    windows = [w for w in (getattr(snap, "windows", None) or ())
               if isinstance(w, UsageWindow)]
    if not windows:
        return [None] * _MIN_BARS
    if filter_dead_pools:
        windows = display_windows(windows)   # resolves internally
    else:
        windows = resolved_windows(windows)
    windows = windows[:_MAX_BARS]
    while len(windows) < _MIN_BARS:
        windows.append(None)
    return windows


def _win_label(b, provider_id: str = "") -> str:
    """Human window name from the window key or its duration."""
    if isinstance(b, str):
        key = base_key(b)
        mins = _KNOWN_WINDOW_MIN.get(key)
    else:
        mins = b.duration_minutes if isinstance(b.duration_minutes,
                                                (int, float)) else None
        key = base_key(getattr(b, "key", "") or "")
    if key == FIVE_HOUR or mins == 300:
        # Claude's own /usage answer calls this bucket "Current session".
        # Its reset timestamp is authoritative and may be beyond five hours.
        return tr("Session") if provider_id == "claude" else "5h"
    if key == WEEKLY or mins == 10080:
        return tr("weekly")
    if key == MONTHLY or mins == 43200:
        return tr("monthly")
    if key == "spend_limit":
        return tr("spend")
    if key == "quota":
        # Antigravity quotes only the remaining delay, never a window length.
        return tr("quota")
    if key == "daily_amount":
        # Freebuff Freebucks: an amount pool with a daily refill, not an
        # hours-long percent window — the label must not read "5h" or "1d".
        return tr("daily FB")
    if mins:
        if mins < 60:
            return f"{int(mins)}m"
        if mins < 1440:
            return f"{int(mins // 60)}h"
        return f"{int(mins // 1440)}d"
    # A vendor key is an identifier, not a human name. This used to fall
    # through to `key or "window"`, so a provider that shipped a window this
    # table did not know -- and reported no duration for it -- had its raw key,
    # values like "five_hour", painted straight into the overview's label
    # column. Unknown is a word the translator can supply; an identifier is not.
    return tr("window")


def _fmt_win(b) -> str:
    if b is None or not b.available:
        return "unavailable"
    rem = b.remaining_percent
    rem_s = "--" if rem is None else f"{int(round(rem))}% left"
    if b.gated_by:
        return f"{rem_s}" + tr(" — blocked by ") + _win_label(b.gated_by)
    if b.resets_at_epoch:
        import datetime
        try:
            t = datetime.datetime.fromtimestamp(b.resets_at_epoch)
            now = datetime.datetime.now().astimezone()
            delta = t.astimezone() - now
            if delta.total_seconds() < 0:
                reset = "resets now"
            elif delta.total_seconds() < 3600:
                reset = f"resets in {int(delta.total_seconds() // 60)}m"
            elif delta.total_seconds() < 86400:
                reset = f"resets in {int(delta.total_seconds() // 3600)}h"
            else:
                reset = f"resets {t.strftime('%a %H:%M')}"
        except Exception:
            reset = ""
        return f"{rem_s} — {reset}" if reset else rem_s
    return rem_s
