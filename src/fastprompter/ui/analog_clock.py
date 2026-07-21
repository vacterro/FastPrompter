"""Mini analog clock for the header — real time, hour + minute hands.

Painted flat (no antialiasing) to match the Win95-style theme. The parent
window's 1-second date timer calls sync(); the widget only repaints when
the displayed minute actually changes.
"""

import datetime
import math

from PyQt6.QtCore import QPoint, Qt
from PyQt6.QtGui import QColor, QPainter, QPen
from PyQt6.QtWidgets import QSizePolicy, QWidget


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
        # What the widgets NEXT TO the clock actually paint. The header bar
        # itself is tinted lighter, but the labels sitting on it render
        # bg_main - so filling with the bar's tint left the clock as a pale
        # square among dark neighbours, which is the reported artefact.
        "face": QColor(raw.get("bg_main", _FALLBACK["bg_text"])),
        "rim": QColor(raw.get("border_light", _FALLBACK["border_light"])),
        "hands": QColor(raw.get("accent", _FALLBACK["accent"])),
    }


class MiniAnalogClock(QWidget):
    SIZE = 18

    def __init__(self, main_win):
        super().__init__(main_win)
        self.main_win = main_win
        # Fixed WIDTH, stretching height. At a fixed 18x18 the widget was
        # shorter than the labels beside it, so four rows of the header bar's
        # own (lighter) tint stayed visible above and below - a box drawn
        # around the clock. Filling the widget could never hide that, because
        # the box is outside the widget. Covering the full row height does.
        self.setFixedWidth(self.SIZE)
        self.setSizePolicy(QSizePolicy.Policy.Fixed,
                           QSizePolicy.Policy.Expanding)
        self.setMinimumHeight(self.SIZE)
        self._shown_minute = -1
        # Painting its own background (below) rather than inheriting one:
        # a transparent child kept whatever was behind it when it was built,
        # so it showed the Default theme's toolbar tint on every theme.
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)

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
            # the dial keeps its size while the widget may be taller
            r = min(self.SIZE, self.height()) // 2 - 1

            colors = _theme_palette(self.main_win)
            face, rim, hands = colors["face"], colors["rim"], colors["hands"]
            # Fill the whole widget with the toolbar's colour first: that is
            # what removes the square, since the rectangle now matches what
            # surrounds it on every theme instead of on one.
            p.fillRect(self.rect(), face)
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
