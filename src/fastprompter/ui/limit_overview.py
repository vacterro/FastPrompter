"""Full-size horizontal quota bars — one row per window, grouped by account.

The header gauge is 3 px wide on purpose: it answers "am I close to a limit"
at a glance and nothing more. This widget is the opposite end of that trade —
it lives in the AI Limit Settings window, where there is room to state every
fact the providers actually reported: which vendor, which window, how much is
spent, how much is left, when it resets, and which file proved it.

Two fill directions, user's choice (``limit_gauges_fill``):

* ``remaining`` — the bar holds what is LEFT and drains to the left as quota
  is spent. A fuel gauge: empty bar = no fuel.
* ``used`` — the bar grows to the right with what is SPENT. A progress bar:
  full bar = nothing left.

Both render the same number. The fill COLOUR always follows the REMAINING
percentage (the thresholds the header gauge uses), so a nearly-exhausted
window is red in either direction.

Everything is painted directly: one widget, 2 px Win95 bevels, no stylesheet
to fight, no antialiasing, no animation (UI.md).
"""

from __future__ import annotations

from PyQt6.QtCore import QRect, Qt
from PyQt6.QtGui import QColor, QCursor, QFont, QFontMetrics, QPainter, QPen
from PyQt6.QtWidgets import QMessageBox, QPushButton, QSizePolicy, QWidget

from fastprompter.core.usage_limits.model import (
    OK,
    STALE,
    UsageWindow,
    resolved_windows,
)
from fastprompter.ui.limit_account_selector import (
    account_display_name,
    hidden_account_keys,
    ordered_accounts,
)
from fastprompter.ui.limit_colors import limit_palette
from fastprompter.ui.limit_gauges import _win_label
from fastprompter.utils.fonts import no_aa

_PROVIDER_LABEL = {"codex": "Codex", "claude": "Claude",
                   "antigravity": "Antigravity", "zcode": "ZCode"}


class LimitOverview(QWidget):
    """Every discovered account's quota windows as full-width bars."""

    PAD = 4
    HEADER_H = 18
    POOL_H = 14
    ROW_H = 20
    BAR_H = 12
    GROUP_GAP = 5
    LABEL_W = 62
    VALUE_W = 190

    def __init__(self, main_win, service, parent=None):
        super().__init__(parent)
        self.main_win = main_win
        self._service = service
        self.setSizePolicy(QSizePolicy.Policy.Expanding,
                           QSizePolicy.Policy.Fixed)
        self.setMinimumWidth(360)
        self._rows: list[tuple] = []
        self._buttons: list[tuple[QPushButton, int]] = []
        self.refresh()

    # -- data ------------------------------------------------------------
    def _accounts(self):
        hidden = hidden_account_keys(self.main_win.data)
        shown = [a for a in self._service.state_copy.accounts
                 if a.key not in hidden]
        return ordered_accounts(shown, self.main_win.data)

    def refresh(self):
        """Rebuild the row model and resize to fit it exactly.

        Height is recomputed here and only here, so the panel never reflows
        while it is being read: a sweep that adds a window grows the widget
        once, at the moment the data arrives.
        """
        for btn, _ in self._buttons:
            btn.hide()
            btn.deleteLater()
        self._buttons = []

        snap = self._service.state_copy
        rows: list[tuple] = []
        for account in self._accounts():
            shot = snap.snapshots.get(account.key)
            rows.append(("account", account, shot))
            if shot is None:
                rows.append(("note", "not probed yet", None))
                continue
            if shot.status not in (OK, STALE):
                rows.append(("note",
                             f"{shot.status.lower()} — "
                             f"{shot.error_summary or 'no data'}", None))
                continue
            windows = [w for w in resolved_windows(shot.windows)
                       if isinstance(w, UsageWindow)]
            live = [w for w in windows if w.available]
            if not live:
                rows.append(("note", "no readable quota window", None))
            else:
                # A pool heading is drawn once per independent quota group, so two
                # "7 days" rows from different pools cannot be mistaken for one
                # limit reported twice.
                pool = None
                for window in live:
                    if window.group_label and window.group_label != pool:
                        pool = window.group_label
                        rows.append(("pool", pool, shot))
                    rows.append(("window", window, shot))
            if getattr(shot, "banked_resets", None):
                b_count = shot.banked_resets
                res_suffix = "s" if b_count != 1 else ""
                rows.append(("banked_resets",
                             f"★ {b_count} usage limit reset{res_suffix} available (/usage to redeem)",
                             shot))
        if not rows:
            rows.append(("note", "No AI accounts detected", None))
        self._rows = rows
        self.setFixedHeight(self._content_height())

        # Create interactive buttons for any banked_resets rows
        y = self.PAD
        for index, (kind, _payload, shot) in enumerate(self._rows):
            if kind == "account":
                if index:
                    y += self.GROUP_GAP
                y += self.HEADER_H
            elif kind == "pool":
                y += self.POOL_H
            elif kind == "banked_resets":
                btn = QPushButton("Activate reset", self)
                btn.setCursor(Qt.CursorShape.PointingHandCursor)
                btn.setToolTip("Consume 1 banked reset credit to refill quota immediately")
                btn.setStyleSheet(
                    "QPushButton { font-size: 10px; font-weight: bold; padding: 1px 6px; }"
                )
                btn.clicked.connect(lambda checked=False, s=shot: self._prompt_activate_reset(s))
                self._buttons.append((btn, y))
                y += self.ROW_H
            else:
                y += self.ROW_H
        self._layout_buttons()
        self.update()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._layout_buttons()

    def _layout_buttons(self):
        w = self.width()
        for btn, y in self._buttons:
            btn_w = 96
            btn_h = 20
            btn_x = max(self.PAD + self.LABEL_W, w - self.PAD - btn_w - 4)
            btn_y = y + (self.ROW_H - btn_h) // 2
            btn.setGeometry(btn_x, btn_y, btn_w, btn_h)
            btn.show()

    def _prompt_activate_reset(self, shot):
        if shot is None or not getattr(shot, "account", None):
            return
        account = shot.account
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
                    "Quota is refreshing...",
                )
                self.refresh()
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

    def _content_height(self) -> int:
        height = self.PAD * 2
        for index, (kind, _payload, _shot) in enumerate(self._rows):
            if kind == "account":
                height += self.HEADER_H + (self.GROUP_GAP if index else 0)
            elif kind == "pool":
                height += self.POOL_H
            elif kind == "banked_resets":
                height += self.ROW_H
            else:
                height += self.ROW_H
        return max(self.PAD * 2 + self.ROW_H, height)

    # -- painting --------------------------------------------------------
    def _palette(self):
        """Every colour these bars paint — user-settable (see limit_colors)."""
        return limit_palette(self.main_win)

    def _fill_color(self, remaining, pal, stale=False):
        if stale:
            return pal["stale"]
        if not isinstance(remaining, (int, float)):
            return pal["dim"]
        if remaining < 20:
            return pal["bad"]
        if remaining < 50:
            return pal["warn"]
        return pal["good"]

    def _fill_mode(self) -> str:
        """``remaining`` = drains like fuel, ``used`` = grows like progress."""
        value = str(self.main_win.data.get("limit_gauges_fill", "remaining"))
        return value if value in ("remaining", "used") else "remaining"

    def _font(self, size: int, bold: bool = False) -> QFont:
        font = no_aa(QFont(self.font()))
        font.setPointSize(size)
        font.setBold(bold)
        return font

    def paintEvent(self, _event):
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
            pal = self._palette()
            painter.fillRect(self.rect(), pal["bg"])
            y = self.PAD
            width = self.width()
            for index, (kind, payload, shot) in enumerate(self._rows):
                if kind == "account":
                    if index:
                        y += self.GROUP_GAP
                    self._paint_header(painter, pal, y, width, payload, shot)
                    y += self.HEADER_H
                elif kind == "pool":
                    self._paint_pool(painter, pal, y, width, payload)
                    y += self.POOL_H
                elif kind == "note":
                    self._paint_note(painter, pal, y, width, payload)
                    y += self.ROW_H
                elif kind == "banked_resets":
                    self._paint_banked(painter, pal, y, width, payload)
                    y += self.ROW_H
                else:
                    self._paint_window(painter, pal, y, width, payload, shot)
                    y += self.ROW_H
        finally:
            painter.end()

    def _paint_pool(self, painter, pal, y, width, label):
        """One independent quota pool's name, above the windows it governs."""
        painter.setFont(self._font(10))
        painter.setPen(QPen(pal["pool"], 1))
        painter.drawText(
            QRect(self.PAD, y, width - self.PAD * 2, self.POOL_H),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            str(label))

    def _paint_header(self, painter, pal, y, width, account, shot):
        painter.setFont(self._font(11, bold=True))
        vendor = _PROVIDER_LABEL.get(account.provider_id,
                                     account.provider_id.title())
        name = account_display_name(account, self.main_win.data)
        title = name if name.lower().startswith(vendor.lower()) \
            else f"{vendor} · {name}"
        plan = getattr(shot, "plan_type", None) if shot is not None else None
        if plan:
            title = f"{title} ({plan})"
        banked = getattr(shot, "banked_resets", None) if shot is not None else None
        if banked:
            res_suffix = "s" if banked != 1 else ""
            title = f"{title} [{banked} banked reset{res_suffix}]"
        painter.setPen(QPen(pal["good"], 1))
        painter.drawText(
            QRect(self.PAD, y, width - self.PAD * 2, self.HEADER_H),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, title)
        if shot is not None and shot.status == STALE:
            painter.setFont(self._font(10))
            painter.setPen(QPen(pal["stale"], 1))
            painter.drawText(
                QRect(self.PAD, y, width - self.PAD * 2, self.HEADER_H),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                "stale")
        # a 1px rule under the account name groups its windows visually
        painter.setPen(QPen(pal["light"], 1))
        bottom = y + self.HEADER_H - 1
        painter.drawLine(self.PAD, bottom, width - self.PAD, bottom)

    def _paint_note(self, painter, pal, y, width, text):
        painter.setFont(self._font(10))
        painter.setPen(QPen(pal["dim"], 1))
        painter.drawText(
            QRect(self.PAD + self.LABEL_W, y, width - self.PAD * 2 - self.LABEL_W,
                  self.ROW_H),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, str(text))

    def _paint_banked(self, painter, pal, y, width, text):
        painter.setFont(self._font(10))
        painter.setPen(QPen(QColor("#4FB6A8"), 1))
        # Leave 104px room on the right for the "Activate reset" button
        usable_w = max(0, width - self.PAD * 2 - self.LABEL_W - 104)
        painter.drawText(
            QRect(self.PAD + self.LABEL_W, y, usable_w, self.ROW_H),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, str(text))

    def _paint_window(self, painter, pal, y, width, window, shot):
        stale = shot is not None and shot.status == STALE
        remaining = window.remaining_percent
        used = window.used_percent
        if not isinstance(used, (int, float)):
            used = (100.0 - float(remaining)
                    if isinstance(remaining, (int, float)) else 0.0)
        used = max(0.0, min(100.0, float(used)))
        drains = self._fill_mode() == "remaining"
        # The inked share: what is LEFT in fuel mode, what is SPENT otherwise.
        inked = (100.0 - used) if drains else used

        painter.setFont(self._font(11))
        painter.setPen(QPen(pal["text"], 1))
        painter.drawText(
            QRect(self.PAD, y, self.LABEL_W - 4, self.ROW_H),
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
            _win_label(window))
        metrics = QFontMetrics(self._font(10))
        value = self._value_text(window, remaining)
        value_w = min(self.VALUE_W, metrics.horizontalAdvance(value) + 8)
        bar_x = self.PAD + self.LABEL_W
        bar_w = max(40, width - bar_x - value_w - self.PAD)
        bar_y = y + (self.ROW_H - self.BAR_H) // 2

        # sunken track: dark top/left, light bottom/right (Win95 inset)
        painter.setPen(QPen(pal["dark"], 1))
        painter.drawLine(bar_x, bar_y, bar_x + bar_w - 1, bar_y)
        painter.drawLine(bar_x, bar_y, bar_x, bar_y + self.BAR_H - 1)
        painter.setPen(QPen(pal["light"], 1))
        painter.drawLine(bar_x, bar_y + self.BAR_H - 1,
                         bar_x + bar_w - 1, bar_y + self.BAR_H - 1)
        painter.drawLine(bar_x + bar_w - 1, bar_y,
                         bar_x + bar_w - 1, bar_y + self.BAR_H - 1)
        inner = QRect(bar_x + 1, bar_y + 1, bar_w - 2, self.BAR_H - 2)
        painter.fillRect(inner, pal["track"])

        fill_w = int(round(inner.width() * inked / 100.0))
        if fill_w > 0:
            painter.fillRect(
                QRect(inner.x(), inner.y(), fill_w, inner.height()),
                self._fill_color(remaining, pal, stale=stale))
        # 25/50/75% ticks: a bar without a scale cannot be read as a number
        painter.setPen(QPen(pal["dark"], 1))
        for fraction in (0.25, 0.5, 0.75):
            tick_x = inner.x() + int(round(inner.width() * fraction))
            painter.drawLine(tick_x, inner.y(), tick_x, inner.y() + 1)
            painter.drawLine(tick_x, inner.bottom() - 1, tick_x, inner.bottom())

        painter.setFont(self._font(10))
        painter.setPen(QPen(pal["stale"] if stale else pal["text"], 1))
        painter.drawText(
            QRect(bar_x + bar_w + 4, y, value_w - 4, self.ROW_H),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, value)

    def _value_text(self, window, remaining) -> str:
        """The number beside the bar, worded to match the fill direction.

        Fuel mode inks what is LEFT, so it reads ``24% left``; progress mode
        inks what is SPENT, so the same window reads ``76% used``. A bar and a
        caption that disagree about which end they describe is the one thing
        this panel must never do.
        """
        drains = self._fill_mode() == "remaining"
        if window.gated_by:
            spent = "0% left" if drains else "100% used"
            return f"{spent} · blocked by {_win_label(window.gated_by)}"
        if not isinstance(remaining, (int, float)):
            value = "--"
        elif drains:
            value = f"{int(round(remaining))}% left"
        else:
            value = f"{int(round(100.0 - float(remaining)))}% used"
        reset = _reset_text(window.resets_at_epoch)
        return f"{value} · {reset}" if reset else value

    # -- tooltip ---------------------------------------------------------
    def event(self, event):
        if event.type() == event.Type.ToolTip:
            self.setToolTip(self._build_tooltip())
        return super().event(event)

    def _build_tooltip(self) -> str:
        lines = []
        for kind, payload, shot in self._rows:
            if kind == "account":
                lines.append(account_display_name(payload, self.main_win.data))
            elif kind == "pool":
                lines.append(f"  {payload}")
            elif kind == "window":
                source = payload.source or "unknown source"
                lines.append(f"  {_win_label(payload)}: {source}")
            else:
                lines.append(f"  {payload}")
        return "\n".join(lines) or "No AI accounts detected"


def _reset_text(epoch) -> str:
    if not isinstance(epoch, (int, float)) or epoch <= 0:
        return ""
    import datetime
    try:
        target = datetime.datetime.fromtimestamp(epoch)
    except (OverflowError, OSError, ValueError):
        return ""
    delta = (target - datetime.datetime.now()).total_seconds()
    if delta <= 0:
        return "resets now"
    if delta < 3600:
        return f"resets in {int(delta // 60)}m"
    if delta < 86400:
        return f"resets in {int(delta // 3600)}h {int((delta % 3600) // 60)}m"
    return f"resets {target.strftime('%a %H:%M')}"
