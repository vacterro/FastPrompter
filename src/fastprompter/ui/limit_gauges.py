"""Provider-neutral LimitGauges header widget.

Consumes normalized :mod:`fastprompter.core.usage_limits.model` snapshots
only — never provider payloads. Renders one 2–3 px bar-pair (5h | weekly) per
account, filled bottom-up by REMAINING percentage. Unavailable renders a dim
outline, stale renders dashed/amber, live renders gold/olive/red by threshold.

The widget is deliberately hard to miss when enabled: it always paints a
beveled box, a live status text (``3/5`` = accounts OK / total), then the bar
clusters. No zero-width invisible state.

Overflow policy: data supports any account count; the header renders as many
complete account clusters as fit the width budget, then shows an overflow
marker. Every account stays inspectable in the tooltip.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPen
from PyQt6.QtWidgets import QSizePolicy, QWidget

from fastprompter.core.usage_limits.model import FIVE_HOUR, OK, STALE, WEEKLY
from fastprompter.core.usage_limits.service import UsageLimitService
from fastprompter.theme.themes import theme_raw_colors

_FALLBACK = {"bg_main": "#1a1a1a", "border_light": "#5a4a2a", "accent": "#D9B340"}
_FALLBACK_WARN = QColor("#A3822A")
_FALLBACK_BAD = QColor("#C05A3A")
_FALLBACK_DIM = QColor("#6E674E")
_FALLBACK_STALE = QColor("#9C9371")


class LimitGauges(QWidget):
    """Compact usage gauges driven by a UsageLimitService."""

    _result_ready = pyqtSignal(object)

    BAR_W = 3
    GAP_PAIR = 1
    GAP_ACC = 2
    PAD = 2
    MAX_WIDGET_W = 160

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
        self.setToolTip("AI usage: click to refresh")
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
        if self.isVisible() != visible:
            self.setVisible(visible)
        if not visible:
            return
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
        if self._visible:
            self._service.schedule_auto(self._refresh_interval() // 1000)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            event.accept()
            self._service.refresh()
        else:
            super().mousePressEvent(event)

    # -- data --------------------------------------------------------------
    def _on_data(self, *_args):
        self.setToolTip(self._build_tooltip())
        self._update_width()
        self.update()

    def _visible_accounts(self):
        return self._service.state_copy.accounts

    def _update_width(self):
        n = len(self._visible_accounts())
        # 22px for status text + clusters
        w = self.PAD * 2 + 22 + n * (self.BAR_W * 2 + self.GAP_PAIR) \
            + max(0, n - 1) * self.GAP_ACC
        w = min(w, self.MAX_WIDGET_W)
        self.setFixedWidth(max(self.PAD * 2 + 14, w))
        parent = self.parentWidget()
        if parent is not None:
            layout = parent.layout()
            if layout is not None:
                layout.invalidate()

    # -- tooltip -----------------------------------------------------------
    def _build_tooltip(self) -> str:
        snap = self._service.state_copy
        lines = ["AI usage limits (remaining)"]
        accounts = snap.accounts
        if not accounts:
            lines.append("no accounts detected — click to rescan")
            return "\n".join(lines)
        for a in accounts:
            s = snap.snapshots.get(a.key)
            header = a.display_name
            if not s:
                lines.append(f"{header}: not probed yet")
                continue
            if s.status == OK:
                lines.append(f"{header}")
                lines.append(f"  5h: {_fmt_win(s.window(FIVE_HOUR))}")
                lines.append(f"  weekly: {_fmt_win(s.window(WEEKLY))}")
            else:
                lines.append(f"{header}: {s.status.lower()} — "
                             f"{s.error_summary or 'unavailable'}")
        return "\n".join(lines)

    # -- painting ----------------------------------------------------------
    def _palette(self):
        raw = theme_raw_colors(self.main_win, _FALLBACK)
        return {
            "bg": QColor(raw.get("bg_main", _FALLBACK["bg_main"])),
            "edge": QColor(raw.get("border_light", _FALLBACK["border_light"])),
            "good": QColor(raw.get("accent", _FALLBACK["accent"])),
            "warn": _FALLBACK_WARN,
            "bad": _FALLBACK_BAD,
            "dim": _FALLBACK_DIM,
            "stale": _FALLBACK_STALE,
        }

    def paintEvent(self, _event):
        p = QPainter(self)
        try:
            p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
            pal = self._palette()
            w, h = self.width(), self.height()
            p.fillRect(self.rect(), pal["bg"])
            if h < 8:
                return
            # visible bevel so the widget can never be missed
            p.setPen(QPen(pal["edge"], 1))
            p.drawRect(0, 0, w - 1, h - 1)
            bar_h = h - 6
            snap = self._service.state_copy
            accounts = self._visible_accounts()
            ok_c = sum(1 for s in snap.snapshots.values()
                       if getattr(s, "status", None) == "OK")
            err_c = sum(1 for s in snap.snapshots.values()
                        if getattr(s, "status", None)
                        in ("ERROR", "AUTH_REQUIRED"))
            x = self.PAD + 1
            # status text: N/total, ! when errors
            label = f"{ok_c}/{len(accounts)}" if accounts else "—"
            if err_c:
                label += "!"
            p.setPen(QPen(pal["dim"], 1))
            p.drawText(x, 2, 22, bar_h, Qt.AlignmentFlag.AlignVCenter, label)
            x += 22
            if not accounts:
                return
            per_cluster = self.BAR_W * 2 + self.GAP_PAIR + self.GAP_ACC
            avail_w = w - x - self.PAD - 1
            n_fit = max(0, avail_w // per_cluster)
            overflow = len(accounts) > n_fit
            for a in accounts[:n_fit]:
                s = snap.snapshots.get(a.key)
                for key in (FIVE_HOUR, WEEKLY):
                    rem = None
                    mode = "dim"
                    if s is not None:
                        if s.status == STALE:
                            mode = "stale"
                        elif s.status == OK:
                            b = s.window(key)
                            if b is not None and b.available:
                                mode = "live"
                                rem = b.remaining_percent
                    self._draw_bar(p, x, 2, bar_h, rem, pal, mode)
                    x += self.BAR_W + self.GAP_PAIR
                x += self.GAP_ACC - self.GAP_PAIR
            if overflow:
                p.setPen(QPen(pal["dim"], 1))
                p.drawText(x + 1, 2, w - x - 2, bar_h,
                           Qt.AlignmentFlag.AlignVCenter, "+")
        finally:
            p.end()

    def _draw_bar(self, p, x, y, h, rem, pal, mode):
        edge = pal["edge"] if mode == "live" else pal["dim"]
        p.setPen(QPen(edge, 1))
        p.drawRect(x, y, self.BAR_W - 1, h - 1)
        if mode == "live" and isinstance(rem, (int, float)):
            fill = max(0.0, min(1.0, rem / 100.0))
            fill_h = max(1, int(round((h - 2) * fill)))
            color = self._bar_color(rem, pal)
            p.fillRect(x + 1, y + h - 1 - fill_h, self.BAR_W - 2, fill_h, color)
        elif mode == "stale":
            p.setPen(QPen(pal["stale"], 1))
            p.drawLine(x, y + h - 3, x + self.BAR_W - 1, y + 1)

    def _bar_color(self, rem, pal):
        if not isinstance(rem, (int, float)):
            return pal["dim"]
        if rem < 20:
            return pal["bad"]
        if rem < 50:
            return pal["warn"]
        return pal["good"]


def _fmt_win(b) -> str:
    if b is None or not b.available:
        return "unavailable"
    rem = b.remaining_percent
    rem_s = "--" if rem is None else f"{int(round(rem))}% left"
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
