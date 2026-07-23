from PyQt6 import sip
from PyQt6.QtCore import QMetaObject, Qt, QTimer
from PyQt6.QtGui import QCursor
from PyQt6.QtWidgets import QHBoxLayout, QPushButton, QVBoxLayout, QWidget

from fastprompter.core.config import extract_bg, extract_color
from fastprompter.theme.themes import THEMES


class QuickListWidget(QWidget):
    def __init__(self, main_win):
        super().__init__(None)
        self.main_win = main_win

        self.setWindowFlags(Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(4, 4, 4, 4)
        self.layout.setSpacing(4)

        self.cat_layout = QHBoxLayout()
        self.cat_layout.setSpacing(2)
        self.layout.addLayout(self.cat_layout)

        self.snip_layout = QVBoxLayout()
        self.snip_layout.setSpacing(2)
        self.layout.addLayout(self.snip_layout)

        self.cats = self.main_win.data['cats_order'][:3]
        self.current_cat = self.main_win.get_current_category()
        if self.current_cat not in self.cats and self.cats:
            self.current_cat = self.cats[0]

        self.init_ui()

    def init_ui(self):
        while self.cat_layout.count():
            w = self.cat_layout.takeAt(0).widget()
            if w: w.deleteLater()
        while self.snip_layout.count():
            w = self.snip_layout.takeAt(0).widget()
            if w: w.deleteLater()

        if not self.cats: return

        theme_name = self.main_win.data.get("theme", "Default")
        theme = THEMES.get(theme_name, THEMES["Default"])

        bg = extract_bg(theme.get('mini_settings', '')) or '#2b2b2b'
        fg = extract_color(theme.get('lbl_title', '')) or '#bfa65e'
        border = extract_color(theme.get('btn_save', '')) or '#4a4a4a'
        active_bg = extract_bg(theme.get('btn_new', '')) or '#4a3b1f'
        raw = theme.get("raw_colors", {})
        # Hover must stay dark with light text — never a light bg under
        # light text (was unreadable)
        hover_bg = raw.get("btn_pressed", "#141414")
        hover_fg = raw.get("accent", fg)

        self.setStyleSheet(f"background-color: {bg}; border: 1px solid {border}; border-radius: 4px;")

        # Combined scale with readable floors (fonts >= 8px equivalents)
        scale = float(self.main_win.data.get("ui_scale", "0.5"))
        cat_font = max(11, int(14 * scale))
        snip_font = max(12, int(15 * scale))

        for cat in self.cats:
            btn = QPushButton(cat[:10])
            btn.setFixedSize(max(52, int(52 * scale)), max(18, int(20 * scale)))
            btn_bg = active_bg if cat == self.current_cat else bg
            btn.setStyleSheet(f"QPushButton {{ background-color: {btn_bg}; color: {fg}; border: 1px solid {border}; border-radius: 2px; font-size: {cat_font}px; font-weight: bold; }} QPushButton:hover {{ background-color: {hover_bg}; color: {hover_fg}; border: 1px solid {fg}; }}")
            btn.clicked.connect(lambda checked, c=cat: self.switch_cat(c))
            self.cat_layout.addWidget(btn)

        snippets = [(i, s) for i, s in enumerate(self.main_win.data["categories"].get(self.current_cat, [])) if s is not None][:10]
        for idx, snip in snippets:
            i = idx
            btn = QPushButton(snip.get("name", "")[:20])
            btn.setFixedSize(max(120, int(160 * scale)), max(20, int(24 * scale)))
            btn.setStyleSheet(f"QPushButton {{ background-color: {bg}; color: {fg}; border: 1px solid {border}; border-radius: 2px; font-size: {snip_font}px; font-weight: bold; text-align: left; padding-left: 6px; }} QPushButton:hover {{ background-color: {hover_bg}; color: {hover_fg}; border: 1px solid {fg}; }}")
            btn.clicked.connect(lambda checked, c=self.current_cat, idx=i: self.on_click(c, idx))
            self.snip_layout.addWidget(btn)
        QTimer.singleShot(10, lambda: not sip.isdeleted(self) and self.adjustSize())
        QTimer.singleShot(15, lambda: not sip.isdeleted(self) and self.center_on_cursor())

    def center_on_cursor(self):
        cursor_pos = QCursor.pos()
        self.move(cursor_pos.x() - self.width() // 2, cursor_pos.y() - self.height() // 2)

    def switch_cat(self, cat):
        self.current_cat = cat
        self.init_ui()

    def on_click(self, cat, idx):
        self.close()
        main_win = self.main_win
        QTimer.singleShot(50, lambda: not sip.isdeleted(main_win) and main_win.fire_global_snippet_from_cat(cat, idx))

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape: self.close()
        else: super().keyPressEvent(event)

    def focusOutEvent(self, event):
        self.close()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.close()
            event.accept()
        else:
            super().keyPressEvent(event)
