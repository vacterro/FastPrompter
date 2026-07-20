"""FancyZones — interactive window snapping with switchable zone layouts.

Ctrl+Q opens a full-screen picker over the monitor the cursor is on. Every
zone is numbered: click it, or press its digit, and the window snaps there.
Tab / arrow keys cycle layouts, Esc cancels. The chosen layout is
remembered, so the next Ctrl+Q comes up on the one you actually use.

Zones are stored as FRACTIONS of the screen's available area (0..1), not
pixels, so a layout behaves the same on a 1080p laptop panel and a 4K
monitor, and automatically avoids the taskbar.

Users can define their own grid via Settings (rows x columns) — that shows
up as the "Custom" layout at the end of the list.
"""

from __future__ import annotations

from PyQt6.QtCore import QRect, Qt
from PyQt6.QtGui import QColor, QCursor, QFont, QPainter, QPen
from PyQt6.QtWidgets import QApplication, QWidget

# (name, [(x, y, w, h), ...]) with every value a fraction of the available
# screen area. Ordered roughly by how often people reach for them.
BUILTIN_LAYOUTS: list[tuple[str, list[tuple[float, float, float, float]]]] = [
    ("Halves", [
        (0.0, 0.0, 0.5, 1.0),
        (0.5, 0.0, 0.5, 1.0),
    ]),
    ("Thirds", [
        (0.0, 0.0, 1 / 3, 1.0),
        (1 / 3, 0.0, 1 / 3, 1.0),
        (2 / 3, 0.0, 1 / 3, 1.0),
    ]),
    ("Priority", [  # wide middle, narrow sides — the classic writing setup
        (0.0, 0.0, 0.25, 1.0),
        (0.25, 0.0, 0.50, 1.0),
        (0.75, 0.0, 0.25, 1.0),
    ]),
    ("Quarters", [
        (0.0, 0.0, 0.5, 0.5),
        (0.5, 0.0, 0.5, 0.5),
        (0.0, 0.5, 0.5, 0.5),
        (0.5, 0.5, 0.5, 0.5),
    ]),
    ("Focus", [  # one centred window, the rest of the screen left alone
        (0.15, 0.10, 0.70, 0.80),
    ]),
    ("Sidebar", [  # tall narrow strip + the remainder
        (0.0, 0.0, 0.28, 1.0),
        (0.28, 0.0, 0.72, 1.0),
    ]),
]

_MAX_CUSTOM = 6  # rows/cols cap — beyond this the digit keys run out anyway


def custom_layout(rows: int, cols: int):
    """An evenly divided rows x cols grid, left-to-right then top-to-bottom."""
    rows = max(1, min(_MAX_CUSTOM, int(rows)))
    cols = max(1, min(_MAX_CUSTOM, int(cols)))
    w, h = 1.0 / cols, 1.0 / rows
    return [(c * w, r * h, w, h) for r in range(rows) for c in range(cols)]


def layouts_for(data) -> list[tuple[str, list]]:
    """Built-ins plus the user's own grid, read from settings."""
    out = list(BUILTIN_LAYOUTS)
    try:
        rows = int(data.get("fancyzones_rows", 2))
        cols = int(data.get("fancyzones_cols", 3))
    except (TypeError, ValueError):
        rows, cols = 2, 3
    out.append((f"Custom {rows}x{cols}", custom_layout(rows, cols)))
    return out


class FancyZoneOverlay(QWidget):
    """Full-screen, interactive zone picker."""

    def __init__(self, main_win=None):
        super().__init__()
        self.main_win = main_win
        self._zones: list[QRect] = []
        self._layouts: list[tuple[str, list]] = list(BUILTIN_LAYOUTS)
        self._layout_idx = 0
        self._hot = -1
        self._avail = QRect()

        self.setWindowFlags(
            Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)

    # ---- colors -------------------------------------------------------
    def _accent(self) -> QColor:
        """Follow the active theme, like every other painted widget here."""
        accent = "#C0A060"
        try:
            cache = getattr(self.main_win, "_theme_cache", None)
            if cache and cache.get("raw_colors"):
                accent = cache["raw_colors"].get("accent", accent)
        except Exception:
            pass
        c = QColor(accent)
        return c if c.isValid() else QColor("#C0A060")

    # ---- geometry -----------------------------------------------------
    def _rebuild_zones(self):
        a = self._avail
        self._zones = [
            QRect(a.x() + round(fx * a.width()),
                  a.y() + round(fy * a.height()),
                  max(1, round(fw * a.width())),
                  max(1, round(fh * a.height())))
            for fx, fy, fw, fh in self._layouts[self._layout_idx][1]
        ]

    def open_for(self, main_win):
        """Show the picker on whichever monitor the cursor is on."""
        self.main_win = main_win
        screen = QApplication.screenAt(QCursor.pos()) or QApplication.primaryScreen()
        if screen is None:
            return False

        data = getattr(main_win, "data", {}) or {}
        self._layouts = layouts_for(data)
        saved = data.get("fancyzones_layout", "")
        self._layout_idx = next(
            (i for i, (name, _) in enumerate(self._layouts) if name == saved), 0)

        self._avail = screen.availableGeometry()
        self._rebuild_zones()
        self._hot = -1
        self.setGeometry(screen.geometry())
        self.show()
        self.raise_()
        self.activateWindow()
        self.setFocus()
        self.update()
        return True

    def _zone_at(self, pos) -> int:
        gp = self.mapToGlobal(pos)
        for i, z in enumerate(self._zones):
            if z.contains(gp):
                return i
        return -1

    def apply_zone(self, idx: int) -> bool:
        """Snap the window into zone `idx` and remember the layout."""
        if not (0 <= idx < len(self._zones)) or self.main_win is None:
            return False
        z = self._zones[idx]
        mw = self.main_win

        # A locked window refuses geometry changes — say so instead of
        # silently doing nothing.
        if getattr(mw, "is_locked", False):
            self.close()
            return False

        try:
            mw.data["fancyzones_layout"] = self._layouts[self._layout_idx][0]
            if hasattr(mw, "mark_dirty"):
                mw.mark_dirty()
        except Exception:
            pass

        if mw.isMinimized():
            mw.showNormal()

        # A zone can be narrower/shorter than the window is allowed to be
        # (minimumSize wins over setGeometry, silently). Grow to the minimum
        # and pull back inside the screen so the window never ends up half
        # off the edge instead of neatly snapped.
        w = max(z.width(), mw.minimumWidth())
        h = max(z.height(), mw.minimumHeight())
        a = self._avail
        x = min(z.x(), a.right() - w + 1) if a.isValid() else z.x()
        y = min(z.y(), a.bottom() - h + 1) if a.isValid() else z.y()
        if a.isValid():
            x, y = max(a.left(), x), max(a.top(), y)

        # setGeometry targets the CLIENT area; on a frameless tool window
        # that is what the user sees, so no frame compensation is needed.
        mw.setGeometry(QRect(x, y, w, h))
        mw.raise_()
        mw.activateWindow()
        self.close()
        return True

    def cycle_layout(self, step: int = 1):
        if not self._layouts:
            return
        self._layout_idx = (self._layout_idx + step) % len(self._layouts)
        self._rebuild_zones()
        self._hot = -1
        self.update()

    # ---- input --------------------------------------------------------
    def mouseMoveEvent(self, event):
        hot = self._zone_at(event.pos())
        if hot != self._hot:
            self._hot = hot
            self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            idx = self._zone_at(event.pos())
            if idx >= 0:
                self.apply_zone(idx)
                return
        self.close()  # click outside any zone dismisses

    def keyPressEvent(self, event):
        key = event.key()
        if key in (Qt.Key.Key_Escape, Qt.Key.Key_Q):
            self.close()
            return
        if Qt.Key.Key_1 <= key <= Qt.Key.Key_9:
            self.apply_zone(key - Qt.Key.Key_1)
            return
        if key in (Qt.Key.Key_Tab, Qt.Key.Key_Right, Qt.Key.Key_Down):
            self.cycle_layout(1)
            return
        if key in (Qt.Key.Key_Backtab, Qt.Key.Key_Left, Qt.Key.Key_Up):
            self.cycle_layout(-1)
            return
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.apply_zone(self._hot if self._hot >= 0 else 0)
            return
        super().keyPressEvent(event)

    def focusOutEvent(self, event):
        self.close()

    # ---- paint --------------------------------------------------------
    def paintEvent(self, _event):
        if not self._zones:
            return
        p = QPainter(self)
        try:
            p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
            accent = self._accent()
            origin = self.geometry().topLeft()

            p.fillRect(self.rect(), QColor(0, 0, 0, 110))  # dim the desktop

            for i, zone in enumerate(self._zones):
                r = zone.translated(-origin.x(), -origin.y()).adjusted(6, 6, -6, -6)
                hot = i == self._hot

                fill = QColor(accent)
                fill.setAlpha(90 if hot else 38)
                p.fillRect(r, fill)

                border = QColor(accent)
                border.setAlpha(255 if hot else 120)
                p.setPen(QPen(border, 3 if hot else 2))
                p.drawRect(r.adjusted(1, 1, -2, -2))

                label = QColor(accent)
                label.setAlpha(255 if hot else 190)
                p.setPen(label)
                f = QFont(self.font())
                f.setPointSize(28 if hot else 22)
                f.setBold(True)
                p.setFont(f)
                p.drawText(r, Qt.AlignmentFlag.AlignCenter, str(i + 1))

            self._paint_hint(p, accent)
        finally:
            p.end()

    def _paint_hint(self, p, accent):
        name = self._layouts[self._layout_idx][0]
        text = f"{name}   —   1-9 snap · Tab layout · Esc cancel"
        f = QFont(self.font())
        f.setPointSize(11)
        f.setBold(True)
        p.setFont(f)
        fm = p.fontMetrics()
        w = fm.horizontalAdvance(text) + 24
        h = fm.height() + 14
        box = QRect((self.width() - w) // 2, self.height() - h - 28, w, h)
        p.fillRect(box, QColor(0, 0, 0, 190))
        border = QColor(accent)
        border.setAlpha(160)
        p.setPen(QPen(border, 2))
        p.drawRect(box.adjusted(1, 1, -2, -2))
        p.setPen(accent)
        p.drawText(box, Qt.AlignmentFlag.AlignCenter, text)
