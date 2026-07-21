"""Ctrl+Q zone picker — a small map that pops up under the cursor.

It used to cover the whole monitor, which meant a full-screen repaint and a
lot of mouse travel to hit a corner. Now it is a compact map of the screen
that appears where the pointer already is: the zones sit millimetres apart,
so picking one is a flick rather than a journey.

Two pages, Tab switches between them and the last one is remembered:

  Quarters  the classic four-corner snap
  Columns   Left 640 / Mid 800 / Right 640, as fractions so the proportions
            hold on any panel (those pixel figures are for a 1920 screen)

Zones are stored as FRACTIONS of the screen's available area (0..1), not
pixels, so a layout behaves the same on a 1080p laptop panel and a 4K
monitor, and automatically avoids the taskbar.
"""

from __future__ import annotations

from PyQt6.QtCore import QPoint, QRect, QRectF, Qt
from PyQt6.QtGui import QColor, QCursor, QFont, QPainter, QPen
from PyQt6.QtWidgets import QApplication, QWidget

# (name, [(x, y, w, h), ...]) with every value a fraction of the available
# screen area. Exactly two pages: more would make Tab a menu to read rather
# than a switch to flick.
BUILTIN_LAYOUTS: list[tuple[str, list[tuple[float, float, float, float]]]] = [
    ("Quarters", [
        (0.0, 0.0, 0.5, 0.5),
        (0.5, 0.0, 0.5, 0.5),
        (0.0, 0.5, 0.5, 0.5),
        (0.5, 0.5, 0.5, 0.5),
    ]),
    # On a 1920-wide screen: 640 / 800 centred / 640.
    ("Columns", [
        (0.0, 0.0, 1 / 3, 1.0),
        (7 / 24, 0.0, 5 / 12, 1.0),
        (2 / 3, 0.0, 1 / 3, 1.0),
    ]),
]

# Popup size at 1.0 UI scale. Big enough that a quarter is a comfortable
# click target, small enough to stay a HUD rather than a window.
_BASE_W, _BASE_H = 250, 168
_HEADER_H = 20          # room for the page name above the map
_PAD = 6


def layouts_for(_data=None) -> list[tuple[str, list]]:
    """The pages. Takes the settings dict for call-site compatibility."""
    return list(BUILTIN_LAYOUTS)


class FancyZoneOverlay(QWidget):
    """Compact zone picker, drawn as a map of the screen."""

    def __init__(self, main_win=None):
        super().__init__()
        self.main_win = main_win
        self._zones: list[QRect] = []        # real screen rectangles
        self._cells: list[QRect] = []        # their miniatures, popup-local
        self._layouts: list[tuple[str, list]] = list(BUILTIN_LAYOUTS)
        self._layout_idx = 0
        self._hot = -1
        self._avail = QRect()
        self._focus_locked = False

        self.setWindowFlags(
            Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
        )
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)

    # ---- colors -------------------------------------------------------
    def _accent(self) -> QColor:
        """Follow the active theme, like every other painted widget here."""
        try:
            cache = getattr(self.main_win, "_theme_cache", None)
            if cache and cache.get("raw_colors"):
                return QColor(cache["raw_colors"].get("accent", "#6aa9ff"))
        except Exception:
            pass
        return QColor("#6aa9ff")

    def _colors(self):
        raw = {}
        try:
            cache = getattr(self.main_win, "_theme_cache", None)
            if cache:
                raw = cache.get("raw_colors") or {}
        except Exception:
            raw = {}
        return (QColor(raw.get("bg_main", "#1b1b1b")),
                QColor(raw.get("text_main", "#c0c0c0")),
                self._accent())

    # ---- geometry -----------------------------------------------------
    def _rebuild_zones(self):
        """Real screen rects, and the miniature of each inside the popup."""
        a = self._avail
        self._zones = [
            QRect(a.x() + round(fx * a.width()),
                  a.y() + round(fy * a.height()),
                  max(1, round(fw * a.width())),
                  max(1, round(fh * a.height())))
            for fx, fy, fw, fh in self._layouts[self._layout_idx][1]
        ]

        # The map keeps the screen's aspect ratio, so a quarter looks like a
        # quarter — a stretched map would make the columns page misleading.
        box = QRect(_PAD, _HEADER_H, self.width() - 2 * _PAD,
                    self.height() - _HEADER_H - _PAD)
        if a.isValid() and a.height():
            ratio = a.width() / a.height()
            w = min(box.width(), int(box.height() * ratio))
            h = min(box.height(), int(w / ratio) if ratio else box.height())
            box = QRect(box.x() + (box.width() - w) // 2,
                        box.y() + (box.height() - h) // 2, w, h)
        self._map = box
        self._cells = [
            QRect(box.x() + round(fx * box.width()),
                  box.y() + round(fy * box.height()),
                  max(2, round(fw * box.width())),
                  max(2, round(fh * box.height())))
            for fx, fy, fw, fh in self._layouts[self._layout_idx][1]
        ]

    def open_for(self, main_win):
        """Show the picker under the cursor, on that cursor's monitor."""
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

        try:
            scale = float(data.get("ui_scale", "1.0"))
        except (TypeError, ValueError):
            scale = 1.0
        scale = max(0.75, min(2.0, scale))
        w, h = int(_BASE_W * scale), int(_BASE_H * scale)

        # Under the pointer, nudged so the whole popup stays on screen.
        pos = QCursor.pos()
        sg = screen.geometry()
        x = min(max(sg.left(), pos.x() - w // 2), sg.right() - w + 1)
        y = min(max(sg.top(), pos.y() - h // 2), sg.bottom() - h + 1)
        self.setGeometry(QRect(x, y, w, h))

        self._rebuild_zones()
        self._hot = -1
        self._lock_focus(True)
        self.show()
        self.raise_()
        self.activateWindow()
        self.setFocus()
        self.update()
        return True

    # ---- keeping the main window alive --------------------------------
    def _lock_focus(self, on):
        """Hold off "hide on click-out" while the picker is up.

        Opening the picker takes focus away from the main window, so with
        that setting on the window hid itself the moment Ctrl+Q was pressed
        - and stayed hidden after snapping, which made the whole feature
        look broken. This is the same lock the dialogs use.
        """
        mw = self.main_win
        if mw is None:
            return
        if on and not self._focus_locked:
            if hasattr(mw, "_increment_focus_lock"):
                mw._increment_focus_lock()
                self._focus_locked = True
        elif not on and self._focus_locked:
            self._focus_locked = False
            if hasattr(mw, "_decrement_focus_lock"):
                # deferred: the main window regains focus a beat after the
                # picker goes away, and releasing early re-arms the hide
                from PyQt6.QtCore import QTimer
                QTimer.singleShot(300, mw._decrement_focus_lock)

    def closeEvent(self, event):
        self._lock_focus(False)
        super().closeEvent(event)

    # ---- picking ------------------------------------------------------
    def _zone_at(self, pos) -> int:
        """Index of the zone whose miniature is under a popup-local point."""
        for i, cell in enumerate(self._cells):
            if cell.contains(pos):
                return i
        return -1

    def apply_zone(self, idx: int) -> bool:
        """Snap the window into zone `idx` and remember the page."""
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
        self.close()
        # after the picker is gone, so the window ends up in front
        if not mw.isVisible():
            mw.show()
        mw.raise_()
        mw.activateWindow()
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
        if not self._cells:
            return
        bg, text, accent = self._colors()
        p = QPainter(self)
        try:
            p.setRenderHint(QPainter.RenderHint.Antialiasing, False)

            p.fillRect(self.rect(), bg)
            p.setPen(QPen(accent, 1))
            p.drawRect(self.rect().adjusted(0, 0, -1, -1))

            font = QFont(self.font())
            font.setPointSizeF(max(7.0, font.pointSizeF()))
            font.setBold(True)
            p.setFont(font)
            p.setPen(text)
            name = self._layouts[self._layout_idx][0]
            p.drawText(QRect(_PAD, 2, self.width() - 2 * _PAD, _HEADER_H - 2),
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                       name)
            p.drawText(QRect(_PAD, 2, self.width() - 2 * _PAD, _HEADER_H - 2),
                       Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                       "Tab")

            fill = QColor(accent)
            fill.setAlpha(40)
            hot_fill = QColor(accent)
            hot_fill.setAlpha(120)

            for i, cell in enumerate(self._cells):
                inner = cell.adjusted(1, 1, -1, -1)
                p.fillRect(inner, hot_fill if i == self._hot else fill)
                p.setPen(QPen(accent, 2 if i == self._hot else 1))
                p.drawRect(inner)

                p.setPen(text if i != self._hot else accent.lighter(150))
                p.drawText(QRectF(inner), Qt.AlignmentFlag.AlignCenter,
                           str(i + 1))
        finally:
            p.end()
