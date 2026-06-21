from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QPushButton
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QCursor
from PyQt6 import sip
from fastprompter.theme.themes import THEMES
from fastprompter.core.config import extract_bg, extract_color
from pynput import keyboard

class QuickListWidget(QWidget):
    def __init__(self, main_win):
        super().__init__(None)
        self.main_win = main_win
        self.kb_listener = None
        
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
        
        theme_name = self.main_win.data.get("theme", "Original Gold")
        theme = THEMES.get(theme_name, THEMES["Original Gold"])
        
        bg = extract_bg(theme.get('mini_settings', '')) or '#2b2b2b'
        fg = extract_color(theme.get('lbl_title', '')) or '#bfa65e'
        border = extract_color(theme.get('btn_save', '')) or '#4a4a4a'
        hover = extract_color(theme.get('lbl_help', '')) or '#1c1c1c'
        active_bg = extract_bg(theme.get('btn_new', '')) or '#4a3b1f'
        
        self.setStyleSheet(f"background-color: {hover}; border: 1px solid {border}; border-radius: 4px;")
        
        for cat in self.cats:
            btn = QPushButton(cat[:10])
            btn.setFixedSize(52, 20)
            btn_bg = active_bg if cat == self.current_cat else bg
            btn.setStyleSheet(f"QPushButton {{ background-color: {btn_bg}; color: {fg}; border: 1px solid {border}; border-radius: 2px; font-size: 10px; font-weight: bold; }} QPushButton:hover {{ border: 1px solid {fg}; }}")
            btn.clicked.connect(lambda checked, c=cat: self.switch_cat(c))
            self.cat_layout.addWidget(btn)
            
        snippets = [s for s in self.main_win.data["categories"].get(self.current_cat, []) if s is not None][:10]
        for i, snip in enumerate(snippets):
            btn = QPushButton(snip.get("name", "")[:20])
            btn.setFixedSize(160, 26)
            btn.setStyleSheet(f"QPushButton {{ background-color: {bg}; color: {fg}; border: 1px solid {border}; border-radius: 2px; font-size: 11px; font-weight: bold; text-align: left; padding-left: 6px; }} QPushButton:hover {{ background-color: {hover}; border: 1px solid {fg}; }}")
            btn.clicked.connect(lambda checked, c=self.current_cat, idx=i: self.on_click(c, idx))
            self.snip_layout.addWidget(btn)
            
        self.setStyleSheet(self.main_win.styleSheet())
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
        QTimer.singleShot(50, lambda: not sip.isdeleted(self.main_win) and self.main_win.fire_global_snippet_from_cat(cat, idx))

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape: self.close()
        else: super().keyPressEvent(event)
             
    def focusOutEvent(self, event):
        self.close()

    def showEvent(self, event):
        super().showEvent(event)
        if self.kb_listener is None:
            self.kb_listener = keyboard.Listener(on_press=self.on_global_key_press)
            self.kb_listener.start()
            
    def hideEvent(self, event):
        super().hideEvent(event)
        if self.kb_listener is not None:
            self.kb_listener.stop()
            self.kb_listener = None
            
    def closeEvent(self, event):
        super().closeEvent(event)
        if self.kb_listener is not None:
            self.kb_listener.stop()
            self.kb_listener = None

    def on_global_key_press(self, key):
        if key == keyboard.Key.esc:
            from PyQt6.QtCore import QMetaObject, Qt
            QMetaObject.invokeMethod(self, "close", Qt.ConnectionType.QueuedConnection)
