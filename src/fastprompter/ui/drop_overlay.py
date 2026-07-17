"""Drop overlay — Telegram-style choice zones while dragging files.

Shown over the editor during a file drag. Text-based files offer two
zones: top = insert as text, bottom = store in the silo's file container.
Non-text files show a single Files zone. The zone under the cursor
highlights; the editor's drop handler asks zone_at() to route the drop.

Solid Win95-dark panels, 2px bevels, no transparency effects.
"""

from PyQt6.QtCore import QRect, Qt
from PyQt6.QtGui import QColor, QFont, QPainter, QPen
from PyQt6.QtWidgets import QWidget

_BG = QColor("#1A0F05")
_PANEL = QColor("#2A1C0A")
_PANEL_HOT = QColor("#362812")
_BORDER = QColor("#4A3820")
_BORDER_HOT = QColor("#C0A060")
_TEXT = QColor("#D4B87A")
_TEXT_DIM = QColor("#7A6838")


class DropOverlay(QWidget):
    def __init__(self, editor):
        super().__init__(editor.viewport())
        self.editor = editor
        self._two_zones = True
        self._hot = "text"
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.hide()

    def begin(self, two_zones):
        self._two_zones = two_zones
        self._hot = "text" if two_zones else "files"
        self.setGeometry(self.editor.viewport().rect())
        self.raise_()
        self.show()

    def track(self, pos):
        """Editor dragMove feeds cursor position; highlight follows."""
        if not self._two_zones:
            return
        zone = "text" if pos.y() < self.height() // 2 else "files"
        if zone != self._hot:
            self._hot = zone
            self.update()

    def zone_at(self, pos):
        if not self._two_zones:
            return "files"
        return "text" if pos.y() < self.height() // 2 else "files"

    def end(self):
        self.hide()

    def _panel(self, p, rect, title, sub, hot):
        p.fillRect(rect, _PANEL_HOT if hot else _PANEL)
        border = _BORDER_HOT if hot else _BORDER
        p.setPen(QPen(border, 2))
        p.drawRect(rect.adjusted(1, 1, -2, -2))
        f = QFont(self.font())
        f.setPointSizeF(max(11.0, f.pointSizeF() * 1.6))
        f.setBold(True)
        p.setFont(f)
        p.setPen(_TEXT if hot else _TEXT_DIM)
        title_rect = QRect(rect.x(), rect.y(), rect.width(),
                           rect.height() // 2 + 10)
        p.drawText(title_rect, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom, title)
        f2 = QFont(self.font())
        f2.setPointSizeF(max(9.0, f2.pointSizeF() * 1.1))
        p.setFont(f2)
        sub_rect = QRect(rect.x(), rect.y() + rect.height() // 2 + 14,
                         rect.width(), rect.height() // 2 - 14)
        p.drawText(sub_rect, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, sub)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        p.fillRect(self.rect(), _BG)
        m = 8
        if self._two_zones:
            half = (self.height() - 3 * m) // 2
            top = QRect(m, m, self.width() - 2 * m, half)
            bot = QRect(m, half + 2 * m, self.width() - 2 * m, half)
            self._panel(p, top, "Drop as Text",
                        "insert the file's content into this silo",
                        self._hot == "text")
            self._panel(p, bot, "Drop to Files \U0001F4C1",
                        "store in the silo's file container",
                        self._hot == "files")
        else:
            full = QRect(m, m, self.width() - 2 * m, self.height() - 2 * m)
            self._panel(p, full, "Drop to Files \U0001F4C1",
                        "stored in the silo's file container", True)
        p.end()
