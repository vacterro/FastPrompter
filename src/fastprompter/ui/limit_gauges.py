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

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPen
from PyQt6.QtWidgets import QSizePolicy, QWidget

from fastprompter.core.usage_limits.model import (
    EXPECTED_QUIET_CODES,
    FIVE_HOUR,
    MONTHLY,
    OK,
    STALE,
    WEEKLY,
    UsageWindow,
    base_key,
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

_KNOWN_WINDOW_MIN = {FIVE_HOUR: 300, WEEKLY: 10080, MONTHLY: 43200}

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
        self.setToolTip("AI usage: click to open settings")
        self._last_prefer_labels = None
        self._result_ready.connect(self._on_data)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._auto)
        service.add_callback(self._result_ready.emit)

    # -- visibility --------------------------------------------------------
    @property
    def _visible(self):
        if not hasattr(self.main_win, "data"):
            return False
        return self.main_win.data.get("limit_gauges", "False") == "True"

    def sync(self):
        """Called by the 1-second header timer — visibility + timer only."""
        visible = self._visible
        # isVisible() also becomes False when an ancestor is temporarily
        # hidden, so it cannot tell whether this widget itself carries the
        # explicit hidden flag. isHidden() can, and keeps notification-only
        # mode from accidentally leaving the header gauge enabled.
        if self.isHidden() == visible:
            self.setVisible(visible)
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
        if not self._service.state_copy.snapshots:
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

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
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

        snap = self._service.state_copy
        banked_accounts = []
        for a in self._visible_accounts():
            s = snap.snapshots.get(a.key)
            if s and getattr(s, "banked_resets", 0):
                banked_accounts.append((a, s))

        for a, s in banked_accounts:
            cnt = s.banked_resets
            res_word = "reset" if cnt == 1 else "resets"
            act = menu.addAction(f"★ Activate {a.display_name} Reset ({cnt} {res_word})...")
            act.triggered.connect(lambda checked=False, acc=a, shot=s: self._prompt_activate_reset(acc, shot))

        if banked_accounts:
            menu.addSeparator()

        act_refresh = menu.addAction("Refresh Limits Now")
        act_refresh.triggered.connect(self._service.refresh)

        menu.addSeparator()

        if hasattr(self.main_win, "open_limit_settings_dialog"):
            act_settings = menu.addAction("AI Limit Settings...")
            act_settings.triggered.connect(self.main_win.open_limit_settings_dialog)

        menu.exec(event.globalPos())

    def _prompt_activate_reset(self, account, shot):
        from PyQt6.QtGui import QCursor
        from PyQt6.QtWidgets import QMessageBox
        banked = getattr(shot, "banked_resets", 0) or 0
        res_word = "reset" if banked == 1 else "resets"
        ans = QMessageBox.question(
            self,
            "Activate Rate Limit Reset",
            f"Activate rate limit reset for {account.display_name}?\n\n"
            f"Available: {banked} banked {res_word}.\n\n"
            "This will consume 1 reset credit to immediately refill your quota.",
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
                res = {"ok": False, "error": "Service does not support reset consumption"}
            if res.get("ok"):
                QMessageBox.information(
                    self,
                    "Reset Activated",
                    f"Rate limit reset activated successfully for {account.display_name}!\n"
                    f"Outcome: {res.get('outcome', 'success')}\n\n"
                    "Quota has been refreshed.",
                )
            else:
                err = res.get("error") or res.get("outcome") or "Unknown error"
                QMessageBox.warning(
                    self,
                    "Reset Failed",
                    f"Failed to activate reset for {account.display_name}:\n{err}",
                )
        except Exception as exc:
            QMessageBox.warning(
                self,
                "Reset Error",
                f"Exception while activating reset:\n{exc}",
            )
        finally:
            self.unsetCursor()

    # -- data --------------------------------------------------------------
    def _on_data(self):
        self.setToolTip(self._build_tooltip())
        self._update_width()
        self.update()

    def refresh_view(self):
        """Apply account visibility settings immediately, without probing."""
        self._on_data()

    def _visible_accounts(self):
        hidden = hidden_account_keys(self.main_win.data)
        shown = [a for a in self._service.state_copy.accounts
                 if a.key not in hidden]
        return ordered_accounts(shown, self.main_win.data)

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
        drawn = len(_cluster_windows(snap.snapshots.get(account.key)))
        return max(self.MIN_BARS, min(drawn, self.MAX_BARS))

    def _max_bars(self) -> int:
        """Widest cluster across all accounts — the per-account upper bound."""
        snap = self._service.state_copy
        widest = self.MIN_BARS
        for a in self._visible_accounts():
            widest = max(widest, len(_cluster_windows(snap.snapshots.get(a.key))))
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

    def _update_width(self):
        """Size the widget to the ink, so no dead strip trails the gauge.

        The header lays widgets out left to right with no stretch between the
        gauge and the reset countdown, so every pixel reserved here and not
        painted shows up as a gap between them.
        """
        self._last_prefer_labels = self._prefer_account_labels()
        accounts = self._visible_accounts()
        w = (self.PAD * 2 + self._status_width(accounts)
             + self._clusters_width(accounts, self._last_prefer_labels))
        w = min(w, self.MAX_WIDGET_W)
        target = max(self.PAD * 2 + 14, w)
        if self.width() != target:
            self.setFixedWidth(target)
        parent = self.parentWidget()
        if parent is not None:
            layout = parent.layout()
            if layout is not None:
                layout.invalidate()

    # -- tooltip -----------------------------------------------------------
    def _build_tooltip(self) -> str:
        snap = self._service.state_copy
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
                return f"<span style='color:{bad_col};'>— blocked by {_win_label(b.gated_by)}</span>"
            if b.resets_at_epoch:
                import datetime
                try:
                    t = datetime.datetime.fromtimestamp(b.resets_at_epoch)
                    now = datetime.datetime.now().astimezone()
                    delta = t.astimezone() - now
                    if delta.total_seconds() < 0:
                        r_text = "resets now"
                    elif delta.total_seconds() < 3600:
                        r_text = f"resets in {int(delta.total_seconds() // 60)}m"
                    elif delta.total_seconds() < 86400:
                        r_text = f"resets in {int(delta.total_seconds() // 3600)}h"
                    else:
                        r_text = f"resets {t.strftime('%a %H:%M')}"
                    return f"<span style='color:#9e9479;'>— {r_text}</span>"
                except Exception:
                    pass
            return ""

        accounts = self._visible_accounts()
        hidden = [a for a in snap.accounts if a not in accounts]

        parts = [
            "<html><body style='font-family:Verdana, Segoe UI, sans-serif; font-size:11px; color:#c0c0c0;'>",
            "<div style='font-weight:bold; font-size:12px; color:#ffd700; border-bottom:1px solid #5a4f32; padding-bottom:3px; margin-bottom:5px;'>",
            "AI Usage Limits <span style='font-weight:normal; font-size:10px; color:#9a8b5f;'>(remaining)</span>",
            "</div>"
        ]

        if not accounts:
            parts.append("<div style='color:#888888; font-style:italic;'>no accounts selected</div>")
            if hidden:
                parts.append(f"<div style='color:#666666; font-size:10px;'>hidden in settings: {len(hidden)}</div>")
            parts.append("</body></html>")
            return "".join(parts)

        parts.append(
            "<table cellspacing='0' cellpadding='1' "
            "style='margin-left:2px; border-collapse:collapse;'>"
        )

        for a in accounts:
            s = snap.snapshots.get(a.key)
            header = html.escape(account_display_name(a, self.main_win.data))
            if not s:
                parts.append(
                    f"<tr><td colspan='4' style='padding-top:6px; padding-bottom:3px;'>"
                    f"<b>{header}</b>: <span style='color:#888888;'>not probed yet</span></td></tr>"
                )
                continue

            plan = f" <span style='color:#8f856c; font-size:10px;'>({html.escape(s.plan_type)})</span>" if s.plan_type else ""
            stale = f" <span style='color:{stale_col}; font-size:10px;'>[stale]</span>" if s.status == STALE else ""
            banked = ""
            if getattr(s, "banked_resets", None):
                res_word = "reset" if s.banked_resets == 1 else "resets"
                banked = f" <span style='color:#4FB6A8; font-size:10px; font-weight:bold;'>[{s.banked_resets} banked {res_word}]</span>"

            parts.append(
                f"<tr><td colspan='4' style='padding-top:7px; padding-bottom:3px; border-bottom:1px solid #4a3e28;'><b>{header}</b>{plan}{stale}{banked}</td></tr>"
            )

            if s.status in (OK, STALE):
                windows = _cluster_windows(s)
                readable = False
                for b in windows:
                    if b is None or not b.available:
                        continue
                    readable = True
                    pool = html.escape(b.group_label) if b.group_label else ""
                    w_lbl = html.escape(_win_label(b))
                    if pool:
                        clean_pool = pool.replace(" and ", " & ").replace(" models", "").replace(" Models", "")
                        lbl_text = f"{clean_pool} {w_lbl}:"
                    else:
                        lbl_text = f"{w_lbl}:"
                    rem = b.remaining_percent
                    col = _color_for(rem, s.status)
                    bar_html = _render_bar(rem, col)
                    pct_str = f"{int(round(rem))}%" if isinstance(rem, (int, float)) else "--"
                    reset_str = _reset_snippet(b)

                    parts.append(
                        f"<tr>"
                        f"<td style='color:#d8ccaa; padding-left:4px; padding-right:12px; white-space:nowrap;'>{lbl_text}</td>"
                        f"<td width='88' style='padding-right:8px; white-space:nowrap; vertical-align:middle;'>{bar_html}</td>"
                        f"<td width='38' align='right' style='color:{col}; font-weight:bold; padding-right:10px; white-space:nowrap; font-family:Consolas, monospace;'>{pct_str}</td>"
                        f"<td style='white-space:nowrap;'>{reset_str}</td>"
                        f"</tr>"
                    )
                if getattr(s, "banked_resets", None):
                    res_word = "reset" if s.banked_resets == 1 else "resets"
                    parts.append(
                        f"<tr><td colspan='4' style='color:#4FB6A8; padding-left:4px; font-size:10px; padding-top:2px; padding-bottom:3px;'>"
                        f"★ {s.banked_resets} usage limit {res_word} available — run <code>/usage</code> in CLI to redeem</td></tr>"
                    )
                if not readable and not getattr(s, "banked_resets", None):
                    parts.append("<tr><td colspan='4' style='color:#777777; font-style:italic; padding-left:6px;'>no readable quota window</td></tr>")
            else:
                err = html.escape(s.error_summary or 'unavailable')
                parts.append(f"<tr><td colspan='4' style='color:{bad_col}; padding-left:6px;'>{s.status.lower()} — {err}</td></tr>")

        parts.append("</table>")

        if hidden:
            h_names = html.escape(", ".join(account_display_name(a, self.main_win.data) for a in hidden))
            parts.append(f"<div style='margin-top:6px; font-size:10px; color:#666666; border-top:1px dotted #3e382b; padding-top:3px;'>Hidden: {h_names}</div>")

        content_w = max(0, self.width() - self.PAD * 2 - self._status_width(accounts, snap))
        _labels, _per_cluster, count_fit = self._fit_layout(content_w, accounts)
        if count_fit < len(accounts):
            parts.append(f"<div style='font-size:10px; color:#8a8067; margin-top:2px;'>+{len(accounts) - count_fit} more selected accounts than fit in the header</div>")

        parts.append("<div style='font-size:10px; color:#77705d; margin-top:5px; border-top:1px dotted #3e382b; padding-top:2px;'>Click: Settings • Ctrl+Click: Bars / Dots / Stacked</div>")
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
                        p.setPen(QPen(pal["dim"], 1))
                        p.drawText(x, 2, label_width - 1, bar_h,
                                   Qt.AlignmentFlag.AlignVCenter,
                                   account_label)
                        x += label_width
                if self._style() == "stack":
                    self._draw_stack(p, x, 2, bar_h, s, pal, a)
                    x += self._marks_width(a) + self.GAP_ACC
                    continue
                for b in _cluster_windows(s):
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
        finally:
            p.end()

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
        rows = _cluster_windows(snap)[:self.MAX_BARS]
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


def _cluster_windows(snap) -> list:
    """Bars to draw for one account — one per window the provider reported.

    An unprobed account yields ``MIN_BARS`` dim placeholders so its cluster
    keeps the same footprint as its neighbours; a plan reporting a single
    window (Codex Free: 30-day) is not padded up to a fake second bar, it
    simply renders one and the padding keeps the cluster readable.

    Windows are resolved here too: a snapshot that reached the widget without
    passing through the service (a test, a stale cached object) must still
    show a 5h bar as empty while the weekly window is exhausted, and full
    once its own reset time has passed.
    """
    if snap is None:
        return [None] * _MIN_BARS
    windows = [w for w in (getattr(snap, "windows", None) or ())
               if isinstance(w, UsageWindow)]
    if not windows:
        return [None] * _MIN_BARS
    windows = resolved_windows(windows)[:_MAX_BARS]
    while len(windows) < _MIN_BARS:
        windows.append(None)
    return windows


def _win_label(b) -> str:
    """Human window name from the window key or its duration."""
    if isinstance(b, str):
        key = base_key(b)
        mins = _KNOWN_WINDOW_MIN.get(key)
    else:
        mins = b.duration_minutes if isinstance(b.duration_minutes,
                                                (int, float)) else None
        key = base_key(getattr(b, "key", "") or "")
    if key == FIVE_HOUR or mins == 300:
        return "5h"
    if key == WEEKLY or mins == 10080:
        return "weekly"
    if key == MONTHLY or mins == 43200:
        return "monthly"
    if key == "spend_limit":
        return "spend"
    if key == "quota":
        # Antigravity quotes only the remaining delay, never a window length.
        return "quota"
    if mins:
        if mins < 60:
            return f"{int(mins)}m"
        if mins < 1440:
            return f"{int(mins // 60)}h"
        return f"{int(mins // 1440)}d"
    return key or "window"


def _fmt_win(b) -> str:
    if b is None or not b.available:
        return "unavailable"
    rem = b.remaining_percent
    rem_s = "--" if rem is None else f"{int(round(rem))}% left"
    if b.gated_by:
        return f"{rem_s} — blocked by {_win_label(b.gated_by)}"
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
