"""FancyZones overlay — transparent snap-zone preview for window positioning.

Shown briefly when user presses Ctrl+Q (cycle_snap_corner). Overlays
translucent zone rectangles on the current screen, highlights the target
zone, then auto-fades. Non-intrusive — clicks pass through, timer dismisses.
"""

from __future__ import annotations

from PyQt6.QtCore import QPropertyAnimation, QRect, Qt, QTimer, pyqtProperty
from PyQt6.QtGui import QColor, QCursor, QPainter, QPen
from PyQt6.QtWidgets import QApplication, QWidget


_ZONE_FILL = QColor(192, 160, 96, 50)
_ZONE_ACTIVE = QColor(192, 160, 96, 120)
_ZONE_BORDER = QColor(192, 160, 96, 80)
_TEXT_COLOR = QColor(212, 184, 122, 200)

_LABELS = ["BR", "BL", "TL", "TR"]


class FancyZoneOverlay(QWidget):
    def __init__(self):
        super().__init__()
        self._target_idx = 0
        self._opacity = 180
        self._zones: list[QRect] = []
        self._anim: QPropertyAnimation | None = None
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._fade_out)

        self.setWindowFlags(
            Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setStyleSheet("background: transparent;")

    def opac(self) -> int:
        return self._opacity

    def set_opac(self, val: int):
        self._opacity = val
        self.update()

    opacity = pyqtProperty(int, opac, set_opac)

    def show_zones(self, target_idx: int):
        screen = QApplication.screenAt(QCursor.pos())
        if screen is None:
            screen = QApplication.primaryScreen()
        if screen is None:
            return

        geo = screen.availableGeometry()
        sw, sh = geo.width(), geo.height()

        fw = min(960, sw)
        fh = min(540, sh)

        corners = [
            QRect(geo.right() - fw, geo.bottom() - fh, fw, fh),
            QRect(geo.left(), geo.bottom() - fh, fw, fh),
            QRect(geo.left(), geo.top(), fw, fh),
            QRect(geo.right() - fw, geo.top(), fw, fh),
        ]

        self._zones = corners
        self._target_idx = target_idx
        self.setGeometry(screen.geometry())
        self.raise_()
        self.show()
        self.update()

        self._timer.stop()
        self._timer.start(800)

    def _fade_out(self):
        if self._anim and self._anim.state() == QPropertyAnimation.State.Running:
            return
        self._anim = QPropertyAnimation(self, b"opacity")
        self._anim.setDuration(300)
        self._anim.setStartValue(self._opacity)
        self._anim.setEndValue(0)
        self._anim.finished.connect(self.hide)
        self._anim.start()

    def paintEvent(self, event):
        if not self._zones:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, False)

        for i, zone in enumerate(self._zones):
            active = i == self._target_idx
            fill = _ZONE_ACTIVE if active else _ZONE_FILL
            alpha = fill.alpha() * self._opacity // 255
            c = QColor(fill)
            c.setAlpha(alpha)
            p.fillRect(zone, c)

            border = QColor(_ZONE_BORDER)
            border.setAlpha(border.alpha() * self._opacity // 255)
            p.setPen(QPen(border, 2))
            p.drawRect(zone.adjusted(1, 1, -2, -2))

            if active and self._opacity > 50:
                p.setPen(_TEXT_COLOR)
                font = p.font()
                font.setPointSize(14)
                font.setBold(True)
                p.setFont(font)
                p.drawText(zone, Qt.AlignmentFlag.AlignCenter, _LABELS[i] if i < len(_LABELS) else "")
