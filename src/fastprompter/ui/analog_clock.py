"""Mini analog clock for the header — real time, hour + minute hands.

Painted flat (no antialiasing) to match the Win95-style theme. The parent
window's 1-second date timer calls sync(); the widget only repaints when
the displayed minute actually changes.
"""

import datetime
import math

from PyQt6.QtCore import QPoint
from PyQt6.QtGui import QColor, QPainter, QPen
from PyQt6.QtWidgets import QWidget


# Used only when the theme cache isn't reachable yet.
_FALLBACK = {"bg_text": "#1e1e1e", "border_light": "#5a4a2a", "accent": "#D9B340"}


def _theme_palette(main_win):
    """Face/rim/hands from the ACTIVE theme — these were hardcoded to one
    dark-golden palette and ignored the theme entirely."""
    raw = _FALLBACK
    try:
        cached = getattr(main_win, "_theme_cache", None)
        if cached and cached.get("raw_colors"):
            raw = cached["raw_colors"]
    except Exception:
        pass
    return {
        "face": QColor(raw.get("bg_text", _FALLBACK["bg_text"])),
        "rim": QColor(raw.get("border_light", _FALLBACK["border_light"])),
        "hands": QColor(raw.get("accent", _FALLBACK["accent"])),
    }


class MiniAnalogClock(QWidget):
    SIZE = 18

    def __init__(self, main_win):
        super().__init__(main_win)
        self.main_win = main_win
        self.setFixedSize(self.SIZE, self.SIZE)
        self._shown_minute = -1

    def sync(self):
        """Called every second by the window's date timer."""
        visible = (self.main_win.data.get("analog_clock", "False") == "True"
                   and not getattr(self.main_win, "_header_ultra", False))
        if self.isVisible() != visible:
            self.setVisible(visible)
        if not visible:
            return
        now = datetime.datetime.now()
        if now.minute != self._shown_minute:
            self._shown_minute = now.minute
            self.update()

    def paintEvent(self, _event):
        now = datetime.datetime.now()
        p = QPainter(self)
        try:
            p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
            c = self.rect().center()
            r = self.SIZE // 2 - 1

            colors = _theme_palette(self.main_win)
            face, rim, hands = colors["face"], colors["rim"], colors["hands"]
            p.setPen(QPen(rim, 1))
            p.setBrush(face)
            p.drawEllipse(c, r, r)
            # 12/3/6/9 ticks
            p.setPen(QPen(rim, 1))
            for ang in (0, 90, 180, 270):
                rad = math.radians(ang)
                p.drawPoint(c.x() + int((r - 1) * math.sin(rad)),
                            c.y() - int((r - 1) * math.cos(rad)))

            def hand(angle_deg, length, width):
                rad = math.radians(angle_deg)
                end = QPoint(c.x() + int(length * math.sin(rad)),
                             c.y() - int(length * math.cos(rad)))
                p.setPen(QPen(hands, width))
                p.drawLine(c, end)

            hour_ang = (now.hour % 12 + now.minute / 60.0) * 30.0
            min_ang = now.minute * 6.0
            hand(hour_ang, r - 4, 2)
            hand(min_ang, r - 2, 1)
        finally:
            p.end()
