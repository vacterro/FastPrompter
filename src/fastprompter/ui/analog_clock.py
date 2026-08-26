"""Mini analog clock for the header — real time, hour + minute hands.

Painted flat (no antialiasing) to match the Win95-style theme. The parent
window's 1-second date timer calls sync(); the widget only repaints when
the displayed minute actually changes.
"""

import datetime
import math

from PyQt6.QtCore import QPoint, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPen, QFont, QPolygon
from PyQt6.QtWidgets import QSizePolicy, QWidget

from fastprompter.theme.themes import theme_raw_colors

# Used only when the theme cache isn't reachable yet.
_FALLBACK = {"bg_text": "#1e1e1e", "border_light": "#5a4a2a", "accent": "#D9B340"}


def _theme_palette(main_win):
    """Face/rim/hands from the ACTIVE theme — these were hardcoded to one
    dark-golden palette and ignored the theme entirely."""
    raw = theme_raw_colors(main_win, _FALLBACK)
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
    PAD = 2

    def __init__(self, main_win):
        parent = main_win if isinstance(main_win, QWidget) else None
        super().__init__(parent)
        self.main_win = main_win
        # Fixed WIDTH, stretching height. At a fixed 18x18 the widget was
        # shorter than the labels beside it, so four rows of the header bar's
        # own (lighter) tint stayed visible above and below - a box drawn
        # around the clock. Filling the widget could never hide that, because
        # the box is outside the widget. Covering the full row height does.
        # A couple of pixels wider than the dial. The layout leaves a 1px gap
        # on each side where the bar's lighter tint shows through; with the
        # dial filling the widget edge to edge those gaps sat right against
        # the circle and read as a frame around it. The padding puts the
        # widget's own background between the two, so they become ordinary
        # toolbar spacing instead of an outline.
        self.setFixedWidth(self.SIZE + 2 * self.PAD)
        self.setSizePolicy(QSizePolicy.Policy.Fixed,
                           QSizePolicy.Policy.Expanding)
        self.setMinimumHeight(self.SIZE)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._shown_minute = -1
        # Painting its own background (below) rather than inheriting one:
        # a transparent child kept whatever was behind it when it was built,
        # so it showed the Default theme's toolbar tint on every theme.
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            event.accept()
            if hasattr(self.main_win, "open_timer_dialog"):
                self.main_win.open_timer_dialog(initial_tab=1)
        else:
            super().mousePressEvent(event)

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


class BigAnalogClock(QWidget):
    """Interactive large analog clock for rich Interval & Timer configuration."""

    intervalChanged = pyqtSignal(int)  # minutes (e.g. 15, 30, 45, 60, 120, ...)
    timeSelected = pyqtSignal(int, int)  # hour, minute

    def __init__(self, main_win=None, parent=None, size=180):
        super().__init__(parent)
        self.main_win = main_win
        self._size = size
        self.setMinimumSize(size, size)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)

        self._interval_minutes = 60
        self._align_mode = "clock"  # "clock" (at :00, :15, ...) or "elapsed"
        self._next_trigger = None  # datetime or None
        self._show_seconds = True
        self._interactive = True
        self._dragging = False

        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)

    def set_interval(self, minutes: int, align_mode: str = "clock"):
        """Set the interval duration in minutes."""
        try:
            self._interval_minutes = max(1, int(minutes))
        except (TypeError, ValueError):
            self._interval_minutes = 60
        self._align_mode = align_mode
        self.update()

    def set_next_trigger(self, dt: datetime.datetime | None):
        self._next_trigger = dt
        self.update()

    def sync(self):
        self.update()

    def _palette(self):
        raw = theme_raw_colors(self.main_win, _FALLBACK) if self.main_win else _FALLBACK
        return {
            "bg": QColor(raw.get("bg_main", _FALLBACK["bg_text"])),
            "face": QColor(raw.get("bg_text", _FALLBACK["bg_text"])),
            "border_light": QColor(raw.get("border_light", _FALLBACK["border_light"])),
            "border_dark": QColor(raw.get("border_dark", "#2a2215")),
            "accent": QColor(raw.get("accent", _FALLBACK["accent"])),
            "text": QColor(raw.get("text_main", "#e0d0a0")),
            "dim": QColor(raw.get("text_dim", "#8a7d5a")),
            "sector": QColor(217, 179, 64, 45),
            "needle": QColor(224, 85, 85),
        }

    def mousePressEvent(self, event):
        if not self._interactive or event.button() != Qt.MouseButton.LeftButton:
            return super().mousePressEvent(event)
        self._dragging = True
        self._handle_click_pos(event.position())

    def mouseMoveEvent(self, event):
        if self._dragging:
            self._handle_click_pos(event.position())
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = False
        super().mouseReleaseEvent(event)

    def _handle_click_pos(self, pos):
        c = self.rect().center()
        dx = pos.x() - c.x()
        dy = pos.y() - c.y()
        dist = math.hypot(dx, dy)
        r = min(self.width(), self.height()) // 2 - 8
        if dist < 10 or dist > r + 20:
            return

        # Calculate angle from top (12 o'clock) clockwise (0 to 360 deg)
        angle = math.degrees(math.atan2(dx, -dy)) % 360.0
        # Convert angle to minute of the hour (0..59)
        minute = int(round((angle / 360.0) * 60.0)) % 60
        for snap in (0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55, 60):
            if abs((angle / 6.0) - snap) <= 1.2:
                minute = snap % 60
                break

        now = datetime.datetime.now()
        self.timeSelected.emit(now.hour, minute)

        mins = 60 if minute == 0 else minute
        self._interval_minutes = mins
        self.intervalChanged.emit(mins)
        self.update()

    def paintEvent(self, _event):
        from PyQt6.QtCore import QPointF, QRectF
        from PyQt6.QtGui import QBrush, QFont, QPen

        p = QPainter(self)
        try:
            p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            colors = self._palette()
            rect = self.rect()
            p.fillRect(rect, colors["bg"])

            c = rect.center()
            radius = min(rect.width(), rect.height()) // 2 - 6
            if radius <= 10:
                return

            # Draw outer 3D bezel ring
            p.setPen(QPen(colors["border_dark"], 2))
            p.setBrush(QBrush(colors["face"]))
            p.drawEllipse(c, radius, radius)

            p.setPen(QPen(colors["border_light"], 1.5))
            p.drawEllipse(c, radius - 2, radius - 2)

            # Draw interval sector / chime markers
            now = datetime.datetime.now()
            if 0 < self._interval_minutes <= 60:
                step = self._interval_minutes
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QBrush(colors["sector"]))
                span_angle = int(-step * 6 * 16)
                p.drawPie(
                    QRectF(c.x() - radius + 5, c.y() - radius + 5, (radius - 5) * 2, (radius - 5) * 2),
                    90 * 16,
                    span_angle,
                )

            # Draw hour and minute tick marks
            for i in range(60):
                ang = i * 6.0
                rad = math.radians(ang)
                sin_a, cos_a = math.sin(rad), math.cos(rad)
                if i % 5 == 0:
                    p.setPen(QPen(colors["accent"], 2 if i % 15 == 0 else 1.5))
                    inner_r = radius - 9 if i % 15 == 0 else radius - 7
                    p.drawLine(
                        QPointF(c.x() + inner_r * sin_a, c.y() - inner_r * cos_a),
                        QPointF(c.x() + (radius - 3) * sin_a, c.y() - (radius - 3) * cos_a),
                    )
                else:
                    p.setPen(QPen(colors["dim"], 1))
                    p.drawLine(
                        QPointF(c.x() + (radius - 5) * sin_a, c.y() - (radius - 5) * cos_a),
                        QPointF(c.x() + (radius - 3) * sin_a, c.y() - (radius - 3) * cos_a),
                    )

            # Draw numerals 12, 3, 6, 9
            font = QFont(p.font())
            font.setPointSize(max(7, radius // 9))
            font.setBold(True)
            p.setFont(font)
            p.setPen(colors["text"])
            numerals = [(0, "12"), (90, "3"), (180, "6"), (270, "9")]
            for ang, label in numerals:
                rad = math.radians(ang)
                nr = radius - 18
                tx = c.x() + nr * math.sin(rad)
                ty = c.y() - nr * math.cos(rad)
                p.drawText(QRectF(tx - 14, ty - 8, 28, 16), Qt.AlignmentFlag.AlignCenter, label)

            # Draw Interval label in dial center
            sub_font = QFont(font)
            sub_font.setPointSize(max(6, radius // 12))
            sub_font.setBold(False)
            p.setFont(sub_font)
            p.setPen(colors["dim"])

            if self._interval_minutes % 60 == 0:
                hours = self._interval_minutes // 60
                if getattr(self, "_align_mode", "clock") == "clock":
                    interval_str = f"🔔 {hours}h (:00)" if hours > 1 else "🔔 1h (:00)"
                else:
                    interval_str = f"every {hours}h"
            else:
                interval_str = f"every {self._interval_minutes}m"
            p.drawText(QRectF(c.x() - 50, c.y() + 18, 100, 14), Qt.AlignmentFlag.AlignCenter, interval_str)

            # Draw Hands
            # Hour hand
            hour_ang = (now.hour % 12 + now.minute / 60.0 + now.second / 3600.0) * 30.0
            hour_rad = math.radians(hour_ang)
            hour_len = radius * 0.52
            p.setPen(QPen(colors["accent"], 3.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.drawLine(
                QPointF(c.x() - 4 * math.sin(hour_rad), c.y() + 4 * math.cos(hour_rad)),
                QPointF(c.x() + hour_len * math.sin(hour_rad), c.y() - hour_len * math.cos(hour_rad)),
            )

            # Minute hand
            min_ang = (now.minute + now.second / 60.0) * 6.0
            min_rad = math.radians(min_ang)
            min_len = radius * 0.76
            p.setPen(QPen(colors["text"], 2.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.drawLine(
                QPointF(c.x() - 6 * math.sin(min_rad), c.y() + 6 * math.cos(min_rad)),
                QPointF(c.x() + min_len * math.sin(min_rad), c.y() - min_len * math.cos(min_rad)),
            )

            # Second hand
            if self._show_seconds:
                sec_ang = now.second * 6.0
                sec_rad = math.radians(sec_ang)
                sec_len = radius * 0.82
                p.setPen(QPen(colors["needle"], 1.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
                p.drawLine(
                    QPointF(c.x() - 10 * math.sin(sec_rad), c.y() + 10 * math.cos(sec_rad)),
                    QPointF(c.x() + sec_len * math.sin(sec_rad), c.y() - sec_len * math.cos(sec_rad)),
                )

            # Center cap
            p.setPen(QPen(colors["border_dark"], 1))
            p.setBrush(QBrush(colors["accent"]))
            p.drawEllipse(c, 4, 4)

        finally:
            p.end()
