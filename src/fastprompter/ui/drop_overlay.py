"""Drop overlay — Telegram-style choice zones while dragging files.

Shown over the editor during a file drag. Text-based files offer two
zones: top = insert as text, bottom = store in the silo's file container.
Non-text files show a single Files zone. The zone under the cursor
highlights; the editor's drop handler asks zone_at() to route the drop.

Solid Win95-dark panels, 2px bevels, no transparency effects.
"""

from PyQt6.QtCore import QRect, Qt
from PyQt6.QtGui import QColor, QFont, QPainter, QPen
from fastprompter.core.translations import tr
from PyQt6.QtWidgets import QWidget

from fastprompter.theme.themes import blend_hex

# Used only when the theme cache isn't reachable yet (very early paint).
_FALLBACK = {
    "bg_main": "#1A0F05", "bg_text": "#2A1C0A", "text_main": "#D4B87A",
    "border_light": "#4A3820", "accent": "#C0A060",
}


def _theme_palette(main_win):
    """Overlay colors derived from the ACTIVE theme's raw_colors.

    These were hardcoded to one dark-golden palette, so the drop zones
    looked wrong on every other theme.
    """
    raw = _FALLBACK
    try:
        cached = getattr(main_win, "_theme_cache", None)
        if cached and cached.get("raw_colors"):
            raw = cached["raw_colors"]
    except Exception:
        pass
    bg = raw.get("bg_main", _FALLBACK["bg_main"])
    panel = raw.get("bg_text", _FALLBACK["bg_text"])
    accent = raw.get("accent", _FALLBACK["accent"])
    text = raw.get("text_main", _FALLBACK["text_main"])
    return {
        "bg": QColor(bg),
        "panel": QColor(panel),
        "panel_hot": QColor(blend_hex(panel, accent, 0.22)),
        "border": QColor(raw.get("border_light", _FALLBACK["border_light"])),
        "border_hot": QColor(accent),
        "text": QColor(text),
        "text_dim": QColor(blend_hex(text, panel, 0.45)),
    }


class DropOverlay(QWidget):
    def __init__(self, editor):
        super().__init__(editor.viewport())
        self.editor = editor
        self._two_zones = True
        self._hot = "text"
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.hide()

    @property
    def _lang(self):
        return getattr(getattr(self.editor, 'main_win', None), '_current_lang', 'EN')

    def begin(self, has_text_option):
        self._has_text_option = has_text_option
        self._hot = "text" if has_text_option else "files"
        # resolve once per drag — the theme can't change mid-drop
        self._colors = _theme_palette(getattr(self.editor, "main_win", None))
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
        mw = getattr(self.editor, 'main_win', None)
        if self._has_text_option:
            # 2x2 grid
            col = "left" if pos.x() < w // 2 else "right"
            row = "top" if pos.y() < h // 2 else "bottom"
            if mw:
                if row == "top" and col == "left": return mw.data.get("drop_top_left", "text")
                if row == "top" and col == "right": return mw.data.get("drop_top_right", "editor_link")
                if row == "bottom" and col == "left": return mw.data.get("drop_bot_left", "files")
                return mw.data.get("drop_bot_right", "files_link")
            else:
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
        c = getattr(self, "_colors", None) or _theme_palette(
            getattr(self.editor, "main_win", None))
        p.fillRect(rect, c["panel_hot"] if hot else c["panel"])
        border = c["border_hot"] if hot else c["border"]
        p.setPen(QPen(border, 2))
        p.drawRect(rect.adjusted(1, 1, -2, -2))
        f = QFont(self.font())
        f.setPointSizeF(max(11.0, f.pointSizeF() * 1.6))
        f.setBold(True)
        p.setFont(f)
        p.setPen(c["text"] if hot else c["text_dim"])
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
        try:
            p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
            c = getattr(self, "_colors", None) or _theme_palette(
                getattr(self.editor, "main_win", None))
            p.fillRect(self.rect(), c["bg"])
            m = 8
            if self._has_text_option:
                # 2x2 grid
                hw = (self.width() - 3 * m) // 2
                hh = (self.height() - 3 * m) // 2
                top_left = QRect(m, m, hw, hh)
                top_right = QRect(2 * m + hw, m, hw, hh)
                bot_left = QRect(m, 2 * m + hh, hw, hh)
                bot_right = QRect(2 * m + hw, 2 * m + hh, hw, hh)
                l = self._lang
                
                info = {
                    "text": (tr("📝 Drop as Text", l), tr("insert content into silo", l)),
                    "editor_link": (tr("🔗 Link in Text", l), tr("insert markdown link at cursor", l)),
                    "files": (tr("📥 Copy to Files 📁", l), tr("store in silo's container", l)),
                    "files_link": (tr("🔗 Link in Files 📁", l), tr("add shortcut in container", l))
                }
                mw = getattr(self.editor, 'main_win', None)
                tl_id = mw.data.get("drop_top_left", "text") if mw else "text"
                tr_id = mw.data.get("drop_top_right", "editor_link") if mw else "editor_link"
                bl_id = mw.data.get("drop_bot_left", "files") if mw else "files"
                br_id = mw.data.get("drop_bot_right", "files_link") if mw else "files_link"
                
                self._panel(p, top_left, info.get(tl_id, info["text"])[0], info.get(tl_id, info["text"])[1], self._hot == tl_id)
                self._panel(p, top_right, info.get(tr_id, info["editor_link"])[0], info.get(tr_id, info["editor_link"])[1], self._hot == tr_id)
                self._panel(p, bot_left, info.get(bl_id, info["files"])[0], info.get(bl_id, info["files"])[1], self._hot == bl_id)
                self._panel(p, bot_right, info.get(br_id, info["files_link"])[0], info.get(br_id, info["files_link"])[1], self._hot == br_id)
            else:
                # 3 stacked rows
                rh = (self.height() - 4 * m) // 3
                top = QRect(m, m, self.width() - 2 * m, rh)
                mid = QRect(m, 2 * m + rh, self.width() - 2 * m, rh)
                bot = QRect(m, 3 * m + 2 * rh, self.width() - 2 * m, rh)
                l = self._lang
                self._panel(p, top, "📥 Copy to Files 📁", "store in silo's container", self._hot == "files")
                self._panel(p, mid, "🔗 Link in Files 📁", "add shortcut in container", self._hot == "files_link")
                self._panel(p, bot, "🔗 Link in Text", "insert markdown link at cursor", self._hot == "editor_link")
        finally:
            p.end()

from PyQt6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QPushButton

class DropZonesDialog(QDialog):
    def __init__(self, main_win):
        from PyQt6.QtWidgets import QVBoxLayout, QGridLayout, QLabel, QComboBox, QPushButton, QHBoxLayout
        super().__init__(main_win, Qt.WindowType.Dialog)
        self.main_win = main_win
        self.setWindowTitle(tr("Drop Zones Configuration", getattr(main_win, "_current_lang", "EN")))
        self.setFixedSize(300, 200)
        self.setStyleSheet(main_win.styleSheet())
        
        layout = QVBoxLayout(self)
        grid = QGridLayout()
        
        self.combos = {}
        options = [
            ("text", tr("Insert Text", getattr(main_win, "_current_lang", "EN"))),
            ("editor_link", tr("Editor Link", getattr(main_win, "_current_lang", "EN"))),
            ("files", tr("Silo Files", getattr(main_win, "_current_lang", "EN"))),
            ("files_link", tr("Silo Link", getattr(main_win, "_current_lang", "EN")))
        ]
        
        zones = [
            ("drop_top_left", tr("Top Left:", getattr(main_win, "_current_lang", "EN"))),
            ("drop_top_right", tr("Top Right:", getattr(main_win, "_current_lang", "EN"))),
            ("drop_bot_left", tr("Bottom Left:", getattr(main_win, "_current_lang", "EN"))),
            ("drop_bot_right", tr("Bottom Right:", getattr(main_win, "_current_lang", "EN")))
        ]
        
        for i, (key, label) in enumerate(zones):
            lbl = QLabel(label)
            combo = QComboBox()
            for val, text in options:
                combo.addItem(text, val)
            
            # Set current value
            current = self.main_win.data.get(key)
            if current is None:
                if key == "drop_top_left": current = "text"
                elif key == "drop_top_right": current = "editor_link"
                elif key == "drop_bot_left": current = "files"
                elif key == "drop_bot_right": current = "files_link"
            
            idx = combo.findData(current)
            if idx >= 0:
                combo.setCurrentIndex(idx)
                
            self.combos[key] = combo
            grid.addWidget(lbl, i, 0)
            grid.addWidget(combo, i, 1)
            
        layout.addLayout(grid)
        
        btn_layout = QHBoxLayout()
        btn_save = QPushButton(tr("Save", getattr(main_win, "_current_lang", "EN")))
        btn_save.clicked.connect(self.save_and_close)
        btn_cancel = QPushButton(tr("Cancel", getattr(main_win, "_current_lang", "EN")))
        btn_cancel.clicked.connect(self.close)
        btn_layout.addWidget(btn_save)
        btn_layout.addWidget(btn_cancel)
        layout.addLayout(btn_layout)
        
    def save_and_close(self):
        for key, combo in self.combos.items():
            self.main_win.data[key] = combo.currentData()
        self.main_win.mark_dirty()
        self.close()
