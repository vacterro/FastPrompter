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

    def begin(self, has_text_option):
        self._has_text_option = has_text_option
        self._hot = "text" if has_text_option else "files"
        self.setGeometry(self.editor.viewport().rect())
        self.raise_()
        self.show()

    def track(self, pos):
        """Editor dragMove feeds cursor position; highlight follows."""
        new_hot = self.zone_at(pos)
        if new_hot != self._hot:
            self._hot = new_hot
            self.update()

    def zone_at(self, pos):
        w, h = self.width(), self.height()
        if self._has_text_option:
            # 2x2 grid
            col = "left" if pos.x() < w // 2 else "right"
            row = "top" if pos.y() < h // 2 else "bottom"
            if row == "top" and col == "left": return "text"
            if row == "top" and col == "right": return "editor_link"
            if row == "bottom" and col == "left": return "files"
            return "files_link"
        else:
            # 3 stacked rows
            if pos.y() < h // 3: return "files"
            if pos.y() < (h * 2) // 3: return "files_link"
            return "editor_link"

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
        if self._has_text_option:
            # 2x2 grid
            hw = (self.width() - 3 * m) // 2
            hh = (self.height() - 3 * m) // 2
            top_left = QRect(m, m, hw, hh)
            top_right = QRect(2 * m + hw, m, hw, hh)
            bot_left = QRect(m, 2 * m + hh, hw, hh)
            bot_right = QRect(2 * m + hw, 2 * m + hh, hw, hh)
            
            self._panel(p, top_left, "📄 Drop as Text", "insert content into silo", self._hot == "text")
            self._panel(p, top_right, "🔗 Link in Text", "insert markdown link at cursor", self._hot == "editor_link")
            self._panel(p, bot_left, "📥 Copy to Files 📁", "store in silo's container", self._hot == "files")
            self._panel(p, bot_right, "🔗 Link in Files 📁", "add shortcut in container", self._hot == "files_link")
        else:
            # 3 stacked rows
            rh = (self.height() - 4 * m) // 3
            top = QRect(m, m, self.width() - 2 * m, rh)
            mid = QRect(m, 2 * m + rh, self.width() - 2 * m, rh)
            bot = QRect(m, 3 * m + 2 * rh, self.width() - 2 * m, rh)
            
            self._panel(p, top, "📥 Copy to Files 📁", "store in silo's container", self._hot == "files")
            self._panel(p, mid, "🔗 Link in Files 📁", "add shortcut in container", self._hot == "files_link")
            self._panel(p, bot, "🔗 Link in Text", "insert markdown link at cursor", self._hot == "editor_link")
        p.end()
