import sys, os, json, ctypes, time, re, math, shutil
import ctypes.wintypes
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                             QHBoxLayout, QTextEdit, QPushButton, QInputDialog,
                             QMessageBox, QLabel, QSystemTrayIcon,
                             QMenu, QSizePolicy, QSpinBox, QComboBox,
                             QCheckBox, QTabBar, QFrame, QLineEdit, QFileDialog,
                             QDialog, QFormLayout, QGridLayout, QSplitter)
from PyQt6.QtCore import Qt, QEvent, QTimer, QMimeData, QAbstractNativeEventFilter, QPoint
from PyQt6.QtGui import (QCursor, QFont, QIcon, QPixmap, QColor,
                         QShortcut, QKeySequence, QTextOption, QDrag, QTextCursor,
                         QTextCharFormat, QTextDocument)
from PyQt6.QtNetwork import QLocalSocket, QLocalServer
import sqlite3

user32 = ctypes.windll.user32
user32.RegisterHotKey.argtypes = [ctypes.wintypes.HWND, ctypes.c_int, ctypes.wintypes.UINT, ctypes.wintypes.UINT]
user32.RegisterHotKey.restype = ctypes.wintypes.BOOL
user32.UnregisterHotKey.argtypes = [ctypes.wintypes.HWND, ctypes.c_int]
user32.UnregisterHotKey.restype = ctypes.wintypes.BOOL

BASE_DIR    = os.path.dirname(os.path.abspath(__file__))
DATA_DIR    = os.path.join(BASE_DIR, "FastPrompter_Data")
os.makedirs(DATA_DIR, exist_ok=True)
DB_FILE     = os.path.join(DATA_DIR, "local_data_v15.db")
SERVER_NAME = "FastPrompter_Server_V15"

THEMES = {
    "Original Gold": {
        "stylesheet": """
QWidget { background-color: #1a1a1a; color: #c4ba9f; font-family: Verdana; font-size: 11px; }
QMainWindow { background-color: #1a1a1a; border: 1px solid #4a4a4a; }
QTextEdit { background-color: #0f0f0f; color: #dcd3b6; border: 1px inset #050505; padding: 2px; }
QPushButton { background-color: #2b2b2b; color: #bfa65e; border: 1px outset #4a4a4a; padding: 2px 4px; }
QPushButton:pressed, QPushButton:checked { background-color: #1c1c1c; border: 1px inset #050505; color: #d6be76; }
QTabBar::tab { background: #2b2b2b; border: 1px outset #4a4a4a; padding: 3px 8px; color: #7a7566; }
QTabBar::tab:selected { background: #1c1c1c; border: 1px inset #050505; font-weight: bold; color: #d6be76; }
QTabBar::scroller { width: 0px; }
QMenu { background-color: #1c1c1c; border: 1px outset #4a4a4a; font-family: Verdana; }
QMenu::item:selected { background-color: #bfa65e; color: #000000; }
QSpinBox, QComboBox, QLineEdit { background-color: #0f0f0f; color: #c4ba9f; border: 1px inset #050505; padding: 2px; }
QCheckBox { color: #c4ba9f; }
QCheckBox::indicator { width: 12px; height: 12px; background: #0f0f0f; border: 1px inset #050505; }
QCheckBox::indicator:checked { background: #bfa65e; }
QToolTip { color: #ffffff; background-color: #2b2b2b; border: 1px solid #bfa65e; padding: 2px; }
QSplitter::handle { background-color: #2b2b2b; }
#SearchFrame { background-color: #1c1c1c; border: 1px solid #4a4a4a; border-radius: 2px; }
""",
        "preset_colors": ["#1e1e1e","#24221c","#1c2420","#241f1c","#1c1c24", "#22241c","#1c2224","#241c22","#24241c","#1a1a1a"],
        "active_temp_color": "#3a3a2a",
        "inactive_temp_color": "#1c1c1c",
        "tray_color": "#8b4513",
        "btn_new": "background-color: #4a3b1f; color: #ffeb99; font-weight: bold; padding: 4px; border: 1px outset #5a4b2f;",
        "btn_save": "background-color: #1b2c3b; color: #8acee6; font-weight: bold; padding: 4px; border: 1px outset #2c4257;",
        "lbl_help": "font-size: 12px; color: #8acee6;",
        "lbl_title": "font-weight: bold; color: #bfa65e;",
        "mini_settings": "QFrame { background-color: #2b2b2b; border: 1px solid #4a4a4a; padding: 2px; }"
    },
    "Vintage Dark": {
        "stylesheet": """
QWidget { background-color: #000000; color: #c0c0c0; font-family: Verdana; font-size: 11px; }
QMainWindow { background-color: #000000; border: 2px solid #808080; }
QTextEdit { background-color: #141414; color: #c0c0c0; border: 2px inset #202020; padding: 4px; }
QPushButton { background-color: #1e1e1e; color: #c0c0c0; border: 2px outset #808080; padding: 3px 6px; }
QPushButton:pressed, QPushButton:checked { background-color: #141414; border: 2px inset #202020; color: #5a7a96; }
QTabBar::tab { background: #1e1e1e; border: 2px outset #808080; padding: 4px 10px; color: #969696; }
QTabBar::tab:selected { background: #141414; border: 2px inset #202020; font-weight: bold; color: #5a7a96; }
QTabBar::scroller { width: 0px; }
QMenu { background-color: #1e1e1e; border: 2px outset #808080; font-family: Verdana; }
QMenu::item:selected { background-color: #5a7a96; color: #000000; }
QSpinBox, QComboBox, QLineEdit { background-color: #141414; color: #c0c0c0; border: 2px inset #202020; padding: 2px; }
QCheckBox { color: #c0c0c0; }
QCheckBox::indicator { width: 12px; height: 12px; background: #141414; border: 2px inset #202020; }
QCheckBox::indicator:checked { background: #5a7a96; }
QToolTip { color: #c0c0c0; background-color: #1e1e1e; border: 1px solid #808080; padding: 4px; }
QSplitter::handle { background-color: #1e1e1e; }
#SearchFrame { background-color: #141414; border: 1px solid #808080; border-radius: 2px; }
""",
        "preset_colors": ["#1e1e1e"] * 10,
        "active_temp_color": "#364757",
        "inactive_temp_color": "#141414",
        "tray_color": "#8b4513",
        "btn_new": "background-color: #1e1e1e; color: #5a7a96; font-weight: bold; font-size: 12px; padding: 6px; border: 2px outset #808080;",
        "btn_save": "background-color: #1e1e1e; color: #c0c0c0; font-weight: bold; font-size: 12px; padding: 6px; border: 2px outset #808080;",
        "lbl_help": "font-size: 14px; color: #5a7a96;",
        "lbl_title": "font-weight: bold; color: #c0c0c0;",
        "mini_settings": "QFrame { background-color: #141414; border: 1px solid #808080; padding: 2px; }"
    },
    "Vintage Classic": {
        "stylesheet": """
QWidget { background-color: #c0c0c0; color: #000000; font-family: "MS Sans Serif"; font-size: 11px; }
QMainWindow { background-color: #c0c0c0; border: 2px solid #808080; }
QTextEdit { background-color: #ffffff; color: #000000; border: 2px inset #808080; padding: 4px; }
QPushButton { background-color: #c0c0c0; color: #000000; border: 2px outset #ffffff; padding: 3px 6px; }
QPushButton:pressed, QPushButton:checked { background-color: #e6e6e6; border: 2px inset #808080; color: #5e7a7a; }
QTabBar::tab { background: #c0c0c0; border: 2px outset #ffffff; padding: 4px 10px; color: #202020; }
QTabBar::tab:selected { background: #e6e6e6; border: 2px inset #808080; font-weight: bold; color: #5e7a7a; }
QTabBar::scroller { width: 0px; }
QMenu { background-color: #c0c0c0; border: 2px outset #ffffff; }
QMenu::item:selected { background-color: #5e7a7a; color: #ffffff; }
QSpinBox, QComboBox, QLineEdit { background-color: #ffffff; color: #000000; border: 2px inset #808080; padding: 2px; }
QCheckBox { color: #000000; }
QCheckBox::indicator { width: 12px; height: 12px; background: #ffffff; border: 2px inset #808080; }
QCheckBox::indicator:checked { background: #5e7a7a; }
QToolTip { color: #000000; background-color: #ffffff; border: 1px solid #000000; padding: 4px; }
QSplitter::handle { background-color: #c0c0c0; }
#SearchFrame { background-color: #c0c0c0; border: 1px solid #808080; border-radius: 2px; }
""",
        "preset_colors": ["#d4d0c8", "#c0c0c0", "#a0a0a0", "#c0c0c0"],
        "active_temp_color": "#5e7a7a",
        "inactive_temp_color": "#e6e6e6",
        "tray_color": "#8b4513",
        "btn_new": "background-color: #c0c0c0; color: #5e7a7a; font-weight: bold; font-size: 12px; padding: 6px; border: 2px outset #ffffff;",
        "btn_save": "background-color: #c0c0c0; color: #000000; font-weight: bold; font-size: 12px; padding: 6px; border: 2px outset #ffffff;",
        "lbl_help": "QLabel { color: #808080; }",
        "lbl_title": "font-weight: bold; color: #000000;",
        "mini_settings": "QFrame { background-color: #c0c0c0; border: 2px solid #ffffff; border-bottom-color: #808080; border-right-color: #808080; } QLabel { color: #000000; } QCheckBox { color: #000000; } QComboBox, QSpinBox { background-color: #ffffff; color: #000000; border: 2px solid #808080; border-bottom-color: #ffffff; border-right-color: #ffffff; } QPushButton { background-color: #c0c0c0; color: #000000; border: 2px solid #ffffff; border-bottom-color: #808080; border-right-color: #808080; }"
    }
}

def extract_bg(style):
    m = re.search(r"background-color:\s*(#[0-9a-fA-F]+)", style)
    return m.group(1) if m else None

def extract_color(style):
    m = re.search(r"color:\s*(#[0-9a-fA-F]+)", style)
    return m.group(1) if m else None

def create_tray_icon(color="#8b4513"):
    pix = QPixmap(16,16); pix.fill(QColor(color)); return QIcon(pix)

def parse_hotkey(hotkey_str):
    parts = hotkey_str.upper().split('+')
    modifiers, vk = 0, 0
    for part in parts:
        part = part.strip()
        if part == 'CTRL': modifiers |= 0x0002
        elif part == 'ALT': modifiers |= 0x0001
        elif part == 'SHIFT': modifiers |= 0x0004
        elif part == 'WIN': modifiers |= 0x0008
        elif len(part) == 1 and 'A' <= part <= 'Z': vk = ord(part)
        elif len(part) == 1 and '0' <= part <= '9': vk = ord(part)
        elif part.startswith('F') and part[1:].isdigit(): vk = 0x6F + int(part[1:])
        elif part.startswith('NUMPAD') and part[6:].isdigit() and 0 <= int(part[6:]) <= 9: vk = 0x60 + int(part[6:])
        elif part == 'SPACE': vk = 0x20
    return modifiers, vk

def try_connect_to_server(retries=3, delay=0.05):
    for _ in range(retries):
        sock = QLocalSocket()
        sock.connectToServer(SERVER_NAME)
        if sock.waitForConnected(100): return sock
        time.sleep(delay)
    return None

class VaultTextEdit(QTextEdit):
    def __init__(self, main_win):
        super().__init__()
        self.main_win = main_win
        self.document().setUndoRedoEnabled(True)

    def insertFromMimeData(self, source):
        if self.main_win.btn_format.text() == "Plain":
            if source.hasText(): self.insertPlainText(source.text())
        else:
            super().insertFromMimeData(source)

    def wheelEvent(self, event):
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            delta = event.angleDelta().y()
            if delta:
                self.main_win.adjust_font_size(1 if delta > 0 else -1)
                event.accept()
                return
        super().wheelEvent(event)

    def keyPressEvent(self, event):
        mods = event.modifiers()
        
        if mods == Qt.KeyboardModifier.ControlModifier:
            if event.key() == Qt.Key.Key_Z:
                self.undo()
                event.accept()
                return
            if event.key() == Qt.Key.Key_Y:
                self.redo()
                event.accept()
                return

        if mods & Qt.KeyboardModifier.ControlModifier and event.key() in (Qt.Key.Key_Home, Qt.Key.Key_End):
            cursor = self.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.Start if event.key() == Qt.Key.Key_Home else QTextCursor.MoveOperation.End)
            self.setTextCursor(cursor)
            self.ensureCursorVisible()
            event.accept()
            return

        if mods & Qt.KeyboardModifier.ControlModifier and event.key() in (Qt.Key.Key_Plus, Qt.Key.Key_Equal, Qt.Key.Key_Minus, Qt.Key.Key_Underscore):
            self.main_win.adjust_ui_scale(0.05 if event.key() in (Qt.Key.Key_Plus, Qt.Key.Key_Equal) else -0.05)
            event.accept()
            return

        if event.key() == Qt.Key.Key_Home:
            cursor = self.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.Start)
            self.setTextCursor(cursor)
            self.ensureCursorVisible()
            event.accept()
            return

        if event.key() == Qt.Key.Key_End:
            cursor = self.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.End)
            self.setTextCursor(cursor)
            self.ensureCursorVisible()
            event.accept()
            return

        if event.key() == Qt.Key.Key_C and mods == Qt.KeyboardModifier.ControlModifier:
            cursor = self.textCursor()
            if not cursor.hasSelection():
                cursor.select(QTextCursor.SelectionType.Document)
                self.setTextCursor(cursor)
            super().keyPressEvent(event)
            if self.main_win.cb_ctrl_c.isChecked():
                QTimer.singleShot(10, self.main_win.hide_and_save)
            return
        super().keyPressEvent(event)

class DraggableButton(QPushButton):
    def __init__(self, main_win, parent=None):
        super().__init__("", parent)
        self.cat, self.global_idx, self.full_text = "", -1, ""
        self.main_win, self.drag_start, self._dragging = main_win, None, False
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self.show_menu)

    def update_data(self, text_label, cat, global_idx, full_text, color, font_family):
        self.setText(text_label)
        self.cat, self.global_idx, self.full_text = cat, global_idx, full_text
        self.setStyleSheet(f"background-color:{color}; font-size:10px; padding:0 4px; font-family:'{font_family}'; text-align:left;")
        self.show()

    def show_menu(self, pos):
        menu = QMenu(self)
        menu.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        menu.setFont(QApplication.font())
        menu.addAction("Copy", lambda: self.main_win.copy_snippet_to_clipboard(self.full_text))
        menu.addAction("Rename", lambda: self.main_win.rename_snippet(self.cat, self.global_idx))
        self.main_win.ignore_focus_loss = True
        try:
            menu.exec(self.mapToGlobal(pos))
        finally:
            self.main_win.ignore_focus_loss = False
        self.main_win.activateWindow()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.RightButton and e.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.main_win.prompt_delete_snippet(self.cat, self.global_idx)
            e.accept()
            return
        if e.button() == Qt.MouseButton.LeftButton:
            self.drag_start, self._dragging = e.pos(), False
            e.accept()
            return
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if getattr(self.main_win, 'is_locked', False) or not (e.buttons() & Qt.MouseButton.LeftButton) or not self.drag_start: return
        if (e.pos() - self.drag_start).manhattanLength() < QApplication.startDragDistance(): return
        self._dragging = True
        drag, mime = QDrag(self), QMimeData()
        mime.setText(f"{self.cat}:{self.global_idx}")
        drag.setMimeData(mime)
        drag.exec(Qt.DropAction.MoveAction)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton and not self._dragging:
            self.main_win.load_snippet_for_edit(self.cat, self.global_idx)
            e.accept()
            return
        super().mouseReleaseEvent(e)

class SnippetWidget(QWidget):
    def __init__(self, main_win, parent=None):
        super().__init__(parent)
        self.main_win = main_win
        self.layout = QHBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(1)

        self.main_btn = DraggableButton(main_win, self)
        self.main_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        
        self.btn_top = QPushButton("▲")
        self.btn_ins = QPushButton("▶")
        self.btn_bot = QPushButton("▼")
        
        self.layout.addWidget(self.main_btn)
        for btn in (self.btn_top, self.btn_ins, self.btn_bot):
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(self.on_action_clicked)
            self.layout.addWidget(btn)

    def update_data(self, text_label, cat, global_idx, full_text, color, font_family, scale):
        self.main_btn.update_data(text_label, cat, global_idx, full_text, color, font_family)
        
        theme_name = self.main_win.data.get("theme", "Original Gold")
        theme = THEMES.get(theme_name, THEMES["Original Gold"])
        bg = extract_bg(theme.get('mini_settings', '')) or '#2b2b2b'
        fg = extract_color(theme.get('lbl_title', '')) or '#bfa65e'
        border = extract_color(theme.get('btn_save', '')) or '#4a4a4a'
        
        btn_size = max(14, int(round(22 * scale)))
        self.main_btn.setFixedHeight(btn_size)
        
        btn_style = f"background-color:{bg}; color:{fg}; border: 1px solid {border}; font-size:{max(8, int(round(9*scale)))}px; font-weight:bold; padding:0;"
        
        for btn in (self.btn_top, self.btn_ins, self.btn_bot):
            btn.setStyleSheet(btn_style)
            btn.setFixedSize(max(14, int(round(18 * scale))), btn_size)
        
        self.show()

    def on_action_clicked(self):
        sender = self.sender()
        if sender == self.btn_top: self.main_win.insert_snippet_text(self.main_btn.full_text, "top")
        elif sender == self.btn_ins: self.main_win.insert_snippet_text(self.main_btn.full_text, "ins")
        elif sender == self.btn_bot: self.main_win.insert_snippet_text(self.main_btn.full_text, "bot")

class DropVerticalWidget(QWidget):
    def __init__(self, main_win):
        super().__init__()
        self.setAcceptDrops(True)
        self.main_win = main_win
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(2)
        self.layout.setAlignment(Qt.AlignmentFlag.AlignTop)

    def dragEnterEvent(self, e):
        cat = self.main_win.get_current_category()
        if e.mimeData().hasText() and e.mimeData().text().startswith(cat + ":"): e.acceptProposedAction()

    def dropEvent(self, e):
        cat = self.main_win.get_current_category()
        pos, source_data = e.position().toPoint(), e.mimeData().text().split(':')
        if len(source_data) != 2 or source_data[0] != cat: e.ignore(); return
        source_idx, page = int(source_data[1]), self.main_win.current_pages.get(cat, 0)
        
        target_view_idx = -1
        for i in range(self.layout.count()):
            item = self.layout.itemAt(i).widget()
            if item and item.isVisible() and item.geometry().contains(pos): target_view_idx = i; break
        
        if target_view_idx == -1:
            visible_count = sum(1 for i in range(self.layout.count()) if self.layout.itemAt(i).widget().isVisible())
            target_view_idx = 0 if pos.y() < self.height() // 2 else visible_count - 1
            
        target_global_idx = page * 10 + max(0, min(9, target_view_idx))
        self.main_win.move_preset_to_index(cat, source_idx, target_global_idx)
        e.acceptProposedAction()

class DraggableSiloButton(QPushButton):
    def __init__(self, main_win, parent=None):
        super().__init__("", parent)
        self.global_idx, self.main_win, self.drag_start, self._dragging = -1, main_win, None, False
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self.show_menu)

    def update_data(self, text_label, global_idx, bg_color):
        self.setText(text_label)
        self.global_idx = global_idx
        self.setStyleSheet(f"font-size:10px; padding:0 4px; font-family:Verdana; text-align:left; background-color:{bg_color};")
        self.show()

    def show_menu(self, pos):
        self.main_win.show_temp_menu(self.global_idx, self.mapToGlobal(pos))

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.drag_start, self._dragging = e.pos(), False
            e.accept()
            return
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if getattr(self.main_win, 'is_locked', False) or not (e.buttons() & Qt.MouseButton.LeftButton) or not self.drag_start: return
        if (e.pos() - self.drag_start).manhattanLength() < QApplication.startDragDistance(): return
        self._dragging = True
        drag, mime = QDrag(self), QMimeData()
        mime.setText(f"silo:{self.global_idx}")
        drag.setMimeData(mime)
        drag.exec(Qt.DropAction.MoveAction)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton and not self._dragging:
            self.main_win._switch_to_slot(self.global_idx)
            e.accept()
            return
        super().mouseReleaseEvent(e)

class SiloDropWidget(QWidget):
    def __init__(self, main_win):
        super().__init__()
        self.setAcceptDrops(True)
        self.main_win = main_win
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(2)
        self.layout.setAlignment(Qt.AlignmentFlag.AlignTop)

    def dragEnterEvent(self, e):
        if e.mimeData().hasText() and e.mimeData().text().startswith("silo:"): e.acceptProposedAction()

    def dropEvent(self, e):
        mime = e.mimeData()
        if not mime.hasText(): return
        data, pos = mime.text().split(':'), e.position().toPoint()
        if len(data) != 2 or data[0] != "silo": return
        
        start_idx, target_view_idx = self.main_win.silo_page * 10, -1
        for i in range(self.layout.count()):
            btn = self.layout.itemAt(i).widget()
            if btn and btn.isVisible() and btn.geometry().contains(pos): target_view_idx = i; break
        
        if target_view_idx == -1:
            visible_count = sum(1 for i in range(self.layout.count()) if self.layout.itemAt(i).widget().isVisible())
            target_view_idx = 0 if pos.y() < self.height() // 2 else visible_count - 1

        target_global_idx = start_idx + target_view_idx
        if int(data[1]) != target_global_idx: self.main_win.swap_temp_slots(int(data[1]), target_global_idx)
        e.acceptProposedAction()

class HotkeyFilter(QAbstractNativeEventFilter):
    def __init__(self, window):
        super().__init__()
        self.window = window

    def nativeEventFilter(self, eventType, message):
        try:
            if eventType in (b"windows_generic_MSG", b"windows_dispatcher_MSG"):
                msg = ctypes.wintypes.MSG.from_address(message.__int__())
                if msg.message == 0x0312:
                    if msg.wParam == 1: self.window.toggle_visibility(); return True, 0
                    elif msg.wParam == 2: self.window.show_quick_list(); return True, 0
                    elif msg.wParam == 3: self.window.toggle_lock(); return True, 0
                    elif msg.wParam == 4: self.window.toggle_always_on_top(); return True, 0
                    elif 10 <= msg.wParam <= 19: self.window.fire_global_snippet(msg.wParam - 10); return True, 0
        except Exception: pass
        return False, 0

class HotkeyWidget(QWidget):
    def __init__(self, default_text=""):
        super().__init__()
        self.layout = QHBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.lbl_key = QLabel(default_text)
        self.lbl_key.setStyleSheet("font-weight: bold;")
        self.btn_bind = QPushButton("Bind")
        self.btn_bind.setFixedWidth(50)
        self.btn_bind.clicked.connect(self.start_listening)
        self.layout.addWidget(self.lbl_key)
        self.layout.addWidget(self.btn_bind)
        self.is_listening = False
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        
    def start_listening(self):
        self.is_listening = True
        self.btn_bind.setText("...")
        self.setFocus()
        
    def keyPressEvent(self, event):
        if not self.is_listening:
            super().keyPressEvent(event); return
        key = event.key()
        if key in (Qt.Key.Key_Control, Qt.Key.Key_Shift, Qt.Key.Key_Alt, Qt.Key.Key_Meta): return
        if key == Qt.Key.Key_Escape:
            self.btn_bind.setText("Bind"); self.is_listening = False; self.clearFocus(); return
            
        modifiers, parts = event.modifiers(), []
        if modifiers & Qt.KeyboardModifier.ControlModifier: parts.append("Ctrl")
        if modifiers & Qt.KeyboardModifier.AltModifier: parts.append("Alt")
        if modifiers & Qt.KeyboardModifier.ShiftModifier: parts.append("Shift")
        if modifiers & Qt.KeyboardModifier.MetaModifier: parts.append("Win")
        
        key_str = QKeySequence(key).toString()
        if event.modifiers() & Qt.KeyboardModifier.KeypadModifier and Qt.Key.Key_0 <= key <= Qt.Key.Key_9: key_str = f"Numpad{chr(key)}"
        if key_str:
            parts.append(key_str)
            self.setText("+".join(parts))
        self.is_listening = False
        self.btn_bind.setText("Bind")
        self.clearFocus()

    def setText(self, text):
        self.lbl_key.setText(text)
        
    def text(self):
        return self.lbl_key.text()

class HotkeySettingsDialog(QDialog):
    def __init__(self, main_win):
        super().__init__(main_win)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.main_win = main_win
        self.main_win.unregister_all_hotkeys()
        self.setWindowTitle("Configure Global Hotkeys")
        self.setMinimumWidth(400)
        
        layout, form_layout = QVBoxLayout(self), QFormLayout()
        
        self.le_global = HotkeyWidget(self.main_win.data.get("global_hotkey", "Alt+X"))
        form_layout.addRow("Toggle UI (Global):", self.le_global)
        self.le_pie = HotkeyWidget(self.main_win.data.get("pie_menu_hotkey", "Shift+Alt+X"))
        form_layout.addRow("Summon Quick List:", self.le_pie)
        self.le_lock = HotkeyWidget(self.main_win.data.get("lock_window_hotkey", "Ctrl+Shift+L"))
        form_layout.addRow("Toggle Lock Window:", self.le_lock)
        self.le_top = HotkeyWidget(self.main_win.data.get("always_on_top_hotkey", "Ctrl+Shift+E"))
        form_layout.addRow("Toggle Always on Top:", self.le_top)
        
        self.snippet_inputs = []
        for i in range(10):
            le = HotkeyWidget(self.main_win.data.get(f"snippet_{i}_hotkey", f"Ctrl+Shift+Numpad{i+1 if i < 9 else 0}"))
            self.snippet_inputs.append(le)
            form_layout.addRow(f"Paste Snippet {i+1}:", le)
            
        layout.addLayout(form_layout)
        
        btn_layout, btn_reset, btn_save = QHBoxLayout(), QPushButton("Reset Defaults"), QPushButton("Save Hotkeys")
        btn_reset.clicked.connect(self.reset_defaults)
        btn_save.clicked.connect(self.save_hotkeys)
        btn_layout.addWidget(btn_reset); btn_layout.addStretch(); btn_layout.addWidget(btn_save)
        layout.addLayout(btn_layout)
        
    def reset_defaults(self):
        self.le_global.setText("Alt+X")
        self.le_pie.setText("Shift+Alt+X")
        self.le_lock.setText("Ctrl+Shift+L")
        self.le_top.setText("Ctrl+Shift+E")
        for i, le in enumerate(self.snippet_inputs): le.setText(f"Ctrl+Shift+Numpad{i+1 if i < 9 else 0}")
         
    def save_hotkeys(self):
        self.main_win.data["global_hotkey"] = self.le_global.text()
        self.main_win.data["pie_menu_hotkey"] = self.le_pie.text()
        self.main_win.data["lock_window_hotkey"] = self.le_lock.text()
        self.main_win.data["always_on_top_hotkey"] = self.le_top.text()
        for i, le in enumerate(self.snippet_inputs): self.main_win.data[f"snippet_{i}_hotkey"] = le.text()
        self.main_win.mark_dirty()
        self.main_win.save_data_to_db(force=True)
        self.accept()
        
    def accept(self):
        self.main_win.register_all_hotkeys(); super().accept()
        
    def reject(self):
        self.main_win.register_all_hotkeys(); super().reject()

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
            btn.setStyleSheet(f"QPushButton {{ background-color: {btn_bg}; color: {fg}; border: 1px solid {border}; border-radius: 2px; font-size: 10px; font-weight: bold; font-family: Verdana; }} QPushButton:hover {{ border: 1px solid {fg}; }}")
            btn.clicked.connect(lambda checked, c=cat: self.switch_cat(c))
            self.cat_layout.addWidget(btn)
            
        snippets = [s for s in self.main_win.data["categories"].get(self.current_cat, []) if s is not None][:10]
        for i, snip in enumerate(snippets):
            btn = QPushButton(snip.get("name", "")[:20])
            btn.setFixedSize(160, 26)
            btn.setStyleSheet(f"QPushButton {{ background-color: {bg}; color: {fg}; border: 1px solid {border}; border-radius: 2px; font-size: 11px; font-weight: bold; font-family: Verdana; text-align: left; padding-left: 6px; }} QPushButton:hover {{ background-color: {hover}; border: 1px solid {fg}; }}")
            btn.clicked.connect(lambda checked, c=self.current_cat, idx=i: self.on_click(c, idx))
            self.snip_layout.addWidget(btn)
            
        QTimer.singleShot(10, self.adjustSize)
        QTimer.singleShot(15, self.center_on_cursor)

    def center_on_cursor(self):
        cursor_pos = QCursor.pos()
        self.move(cursor_pos.x() - self.width() // 2, cursor_pos.y() - self.height() // 2)

    def switch_cat(self, cat):
        self.current_cat = cat
        self.init_ui()

    def on_click(self, cat, idx):
        self.close()
        QTimer.singleShot(50, lambda: self.main_win.fire_global_snippet_from_cat(cat, idx))

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape: self.close()
        else: super().keyPressEvent(event)
             
    def focusOutEvent(self, event):
        self.close()

class FastPrompter(QMainWindow):
    def __init__(self):
        super().__init__()
        self.ignore_focus_loss, self.registered_hotkeys, self._db_dirty = False, [], False
        self.save_timer = QTimer(self)
        self.save_timer.setSingleShot(True)
        self.save_timer.timeout.connect(self.save_data_to_db)
        
        self.editing_snippet = None
        self.auto_save_timer = QTimer(self)
        self.auto_save_timer.timeout.connect(self.save_data_to_db)
        self.auto_save_timer.start(5000)
        
        self.snap_index, self._snap_first_press, self._preview_connected = 0, True, False
        self.current_pages, self.silo_page, self.ui_scale = {}, 0, 1.0
        self.is_locked, self._suspend_cache, self._locked_geometry = False, False, None
        self._initializing_ui, self._suspend_temp_sync = True, True

        self.setup_single_instance_server()
        self.init_db()
        self.init_ui()
        self.init_tray()
        self.setup_global_shortcuts()
        self.register_all_hotkeys()
        
        self._switch_to_slot(self.active_temp_slot, initial=True)
        self._initializing_ui, self._suspend_temp_sync = False, False
        self.apply_theme()

    def mark_dirty(self):
        self._db_dirty = True

    def unregister_all_hotkeys(self):
        hwnd = self.winId().__int__()
        for hk_id in self.registered_hotkeys: ctypes.windll.user32.UnregisterHotKey(hwnd, hk_id)
        self.registered_hotkeys.clear()

    def register_all_hotkeys(self):
        self.unregister_all_hotkeys()
        self._register_single(self.data.get("global_hotkey", "Alt+X"), 1)
        self._register_single(self.data.get("pie_menu_hotkey", "Shift+Alt+X"), 2)
        self._register_single(self.data.get("lock_window_hotkey", "Ctrl+Shift+L"), 3)
        self._register_single(self.data.get("always_on_top_hotkey", "Ctrl+Shift+E"), 4)
        for i in range(10): self._register_single(self.data.get(f"snippet_{i}_hotkey", f"Ctrl+Shift+Numpad{i+1 if i < 9 else 0}"), 10 + i)
            
    def _register_single(self, hotkey_str, hk_id):
        if not hotkey_str: return
        try:
            modifiers, vk = parse_hotkey(hotkey_str)
        except Exception:
            return
        if vk:
            hwnd = None
            if ctypes.windll.user32.RegisterHotKey(hwnd, hk_id, modifiers, vk): self.registered_hotkeys.append(hk_id)

    def setup_single_instance_server(self):
        self.server = QLocalServer()
        self.server.removeServer(SERVER_NAME)
        if not self.server.listen(SERVER_NAME):
            time.sleep(0.05)
            self.server.removeServer(SERVER_NAME)
            self.server.listen(SERVER_NAME)
        self.server.newConnection.connect(self.handle_command)

    def handle_command(self):
        sock = self.server.nextPendingConnection()
        if sock.waitForReadyRead(500):
            if b"SHOW" in sock.readAll().data(): self.show_window()
        sock.disconnectFromServer()

    def toggle_visibility(self):
        if self.isHidden() or self.isMinimized() or not self.isVisible(): self.show_window()
        else: self.hide_and_save()

    def init_db(self):
        self.conn = sqlite3.connect(DB_FILE, check_same_thread=False)
        try:
            with sqlite3.connect(DB_FILE + ".bak") as dest:
                self.conn.backup(dest)
        except Exception: pass
            
        try:
            self.conn.execute("PRAGMA journal_mode=WAL")
            self.conn.execute("PRAGMA synchronous=NORMAL")
            self.conn.execute("PRAGMA temp_store=MEMORY")
        except Exception: pass
            
        cur = self.conn.cursor()
        cur.execute("CREATE TABLE IF NOT EXISTS presets (category TEXT, slot INTEGER, name TEXT, content TEXT, PRIMARY KEY (category, slot))")
        cur.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)")
        cur.execute("CREATE TABLE IF NOT EXISTS temp_presets (slot INTEGER PRIMARY KEY, content TEXT)")
        self.conn.commit()

        self.data = {
            "categories": {"Code": [None]*100, "Text": [None]*100, "Misc": [None]*100}, "cats_order": ["Code", "Text", "Misc"],
            "last_text": "", "last_tab_idx": 0, "last_geometry": "", "temp_presets": [""]*10, "active_temp_slot": 0,
            "font_size": 11, "preview_mode": "None", "paste_mode": "Plain", "tray_visible": "True", "global_hotkey": "Alt+X",
            "pie_menu_hotkey": "Shift+Alt+X", "lock_window_hotkey": "Ctrl+Shift+L", "always_on_top_hotkey": "Ctrl+Shift+E",
            "close_on_focus_loss": "True", "ctrl_c_closes": "True", "theme": "Original Gold", "ui_scale": "1.0", "window_locked": "False",
            "sidebar_right": "False"
        }
        
        for row in cur.execute('SELECT key, value FROM settings'):
            if row[0] in ('last_tab_idx', 'active_temp_slot', 'font_size'): self.data[row[0]] = int(row[1])
            elif row[0] == 'cats_order':
                try: self.data['cats_order'] = json.loads(row[1])
                except json.JSONDecodeError: self.data['cats_order'] = ["Code", "Text", "Misc"]
            elif row[0] in ('ui_scale', 'window_locked', 'sidebar_right'): self.data[row[0]] = row[1]
            elif row[0] == 'hide_font': continue 
            else: self.data[row[0]] = row[1]
                
        for cat in self.data['cats_order']:
             if cat not in self.data['categories']: self.data['categories'][cat] = [None]*100
                
        for row in cur.execute('SELECT category, slot, name, content FROM presets'):
            cat, slot, name, content = row
            if cat in self.data["categories"] and 0 <= slot < 100: self.data["categories"][cat][slot] = {"name": name, "text": content}
                
        temps, max_slot = [""]*10, 9
        for row in cur.execute('SELECT slot, content FROM temp_presets ORDER BY slot ASC'):
            slot, content = row
            if slot > max_slot: temps.extend([""] * (slot - max_slot)); max_slot = slot
            if 0 <= slot < 100: temps[slot] = content
        self.data["temp_presets"], self.active_temp_slot = temps[:100], self.data.get("active_temp_slot", 0)
        self._db_dirty = False

    def save_data_to_db(self, force=False):
        if not self._db_dirty and not force: return
        self.save_timer.stop()

        current_text = self.text_area.toPlainText() if hasattr(self, "text_area") else self.data.get("last_text", "")
        if not getattr(self, "_initializing_ui", False) and not getattr(self, "_suspend_temp_sync", False) and not self.editing_snippet:
            if 0 <= self.active_temp_slot < len(self.data["temp_presets"]): self.data["temp_presets"][self.active_temp_slot] = current_text

        self.data["window_locked"] = "True" if getattr(self, "is_locked", False) else "False"

        try:
            with self.conn:
                cur = self.conn.cursor()
                settings_to_save = [
                    ('last_text', current_text), ('last_tab_idx', str(self.data['last_tab_idx'])),
                    ('active_temp_slot', str(self.active_temp_slot)), ('last_geometry', self.data.get("last_geometry", "")),
                    ('cats_order', json.dumps(self.data['cats_order'])), ('font_size', str(self.font_spin.value())),
                    ('preview_mode', self.preview_combo.currentText()), ('paste_mode', self.btn_format.text()),
                    ('tray_visible', str(self.cb_tray.isChecked())), ('close_on_focus_loss', str(self.cb_focus.isChecked())),
                    ('ctrl_c_closes', str(self.cb_ctrl_c.isChecked())), ('global_hotkey', self.data.get("global_hotkey", "Alt+X")),
                    ('pie_menu_hotkey', self.data.get("pie_menu_hotkey", "Shift+Alt+X")), ('lock_window_hotkey', self.data.get("lock_window_hotkey", "Ctrl+Shift+L")),
                    ('always_on_top_hotkey', self.data.get("always_on_top_hotkey", "Ctrl+Shift+E")), ('theme', self.data.get("theme", "Original Gold")),
                    ('always_on_top', self.data.get("always_on_top", "True")), ('normal_window', self.data.get("normal_window", "False")),
                    ('lock_to_cursor', self.data.get("lock_to_cursor", "False")), ('hide_shortkeys', self.data.get("hide_shortkeys", "False")), 
                    ('ui_scale', self.data.get("ui_scale", "1.0")), ('window_locked', self.data.get("window_locked", "False")), 
                    ('sidebar_right', self.data.get("sidebar_right", "False"))
                ]
                cur.executemany('INSERT OR REPLACE INTO settings (key, value) VALUES (?,?)', settings_to_save)

                cur.execute('DELETE FROM presets')
                presets_to_save = [(cat, i, item["name"], item["text"]) for cat, slots in self.data["categories"].items() for i, item in enumerate(slots) if item]
                cur.executemany('INSERT INTO presets (category, slot, name, content) VALUES (?,?,?,?)', presets_to_save)

                cur.execute('DELETE FROM temp_presets')
                cur.executemany('INSERT INTO temp_presets (slot, content) VALUES (?,?)', [(i, content) for i, content in enumerate(self.data["temp_presets"])])
            self._db_dirty = False
        except sqlite3.Error: pass

    def init_ui(self):
        flags = Qt.WindowType.Widget
        if self.data.get("normal_window", "False") != "True": flags |= Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool
        if self.data.get("always_on_top", "True") == "True": flags |= Qt.WindowType.WindowStaysOnTopHint
        self.setWindowFlags(flags)
        self.setWindowTitle("FastPrompter")
        self.setMinimumSize(480, 320)
        self.setMouseTracking(True)
        self._initializing_ui, self._suspend_temp_sync = True, True

        central = QWidget()
        self.setCentralWidget(central)
        self.main_layout = QVBoxLayout(central)
        self.main_layout.setContentsMargins(2,2,2,2)
        self.main_layout.setSpacing(2)

        self.header_widget = QWidget()
        self.header_layout = QHBoxLayout(self.header_widget)
        self.header_layout.setContentsMargins(0, 0, 0, 0)
        self.header_layout.setSpacing(2)

        self.btn_sidebar_toggle = QPushButton("☰")
        self.btn_sidebar_toggle.setFixedSize(24, 24)
        self.btn_sidebar_toggle.clicked.connect(self.toggle_sidebar_visibility)
        self.header_layout.addWidget(self.btn_sidebar_toggle)

        # ---------------- HEADER WIDGETS CREATION ----------------
        self.tab_bar = QTabBar()
        self.tab_bar.setExpanding(False)
        self.tab_bar.setUsesScrollButtons(False)
        for cat in self.data['cats_order']: self.tab_bar.addTab(cat)
        self.tab_bar.currentChanged.connect(self.on_tab_changed)

        self.btn_add_tab = QPushButton("+")
        self.btn_add_tab.setFixedSize(24, 24)
        self.btn_add_tab.clicked.connect(self.add_category)

        self.btn_del_tab = QPushButton("-")
        self.btn_del_tab.setFixedSize(24, 24)
        self.btn_del_tab.clicked.connect(self.del_category)

        self.btn_new = QPushButton("NEW")
        self.btn_new.setFixedHeight(24)
        self.btn_new.setMinimumWidth(80)
        self.btn_new.clicked.connect(self.select_empty_silo)

        self.btn_save = QPushButton("Save")
        self.btn_save.setFixedHeight(24)
        self.btn_save.clicked.connect(self.save_snippet)

        self.btn_home = QPushButton("Home")
        self.btn_home.setFixedHeight(24)
        self.btn_home.clicked.connect(self.move_cursor_home)

        self.btn_end = QPushButton("End")
        self.btn_end.setFixedHeight(24)
        self.btn_end.clicked.connect(self.move_cursor_end)

        self.btn_add_line = QPushButton("Line")
        self.btn_add_line.setFixedHeight(24)
        self.btn_add_line.clicked.connect(self.insert_add_line)

        self.btn_bullet_toggle = QPushButton("-→•")
        self.btn_bullet_toggle.setFixedHeight(24)
        self.btn_bullet_toggle.clicked.connect(self.toggle_bullet_conversion)

        self.btn_bold = QPushButton("B")
        self.btn_bold.setFixedSize(24, 24)
        self.btn_bold.setStyleSheet("font-weight: bold;")
        self.btn_bold.clicked.connect(lambda: self.apply_format('bold'))

        self.btn_italic = QPushButton("I")
        self.btn_italic.setFixedSize(24, 24)
        self.btn_italic.setStyleSheet("font-style: italic;")
        self.btn_italic.clicked.connect(lambda: self.apply_format('italic'))

        self.btn_under = QPushButton("U")
        self.btn_under.setFixedSize(24, 24)
        self.btn_under.setStyleSheet("text-decoration: underline;")
        self.btn_under.clicked.connect(lambda: self.apply_format('underline'))

        self.btn_strike = QPushButton("S")
        self.btn_strike.setFixedSize(24, 24)
        self.btn_strike.setStyleSheet("text-decoration: line-through;")
        self.btn_strike.clicked.connect(lambda: self.apply_format('strike'))

        self.btn_clear_fmt = QPushButton("Clear Fmt")
        self.btn_clear_fmt.setFixedHeight(24)
        self.btn_clear_fmt.clicked.connect(self.clear_formatting)

        self.btn_settings_toggle = QPushButton("⚙")
        self.btn_settings_toggle.setFixedSize(24, 24)
        self.btn_settings_toggle.clicked.connect(self.toggle_mini_settings)

        self.btn_help = QLabel(" ❓")
        self.btn_help.setToolTip(
            "<b>FastPrompter Tips:</b><br>"
            "• <i>Global Hotkey</i>: Show/Hide UI from anywhere.<br>"
            "• <b>Ctrl+D</b>: Zen/Focus Mode.<br>"
            "• <b>Ctrl+F</b>: Find.<br>"
            "• <b>Ctrl+H</b>: Replace.<br>"
            "• <b>Ctrl+S</b>: Save Snippet.<br>"
            "• <b>Ctrl+Shift+S</b>: Export Silo to file.<br>"
            "• <b>F1..F10</b>: Paste Snippet."
        )

        self.btn_clear = QPushButton("Clear")
        self.btn_clear.setFixedHeight(24)
        self.btn_clear.clicked.connect(self.clear_text)

        self.btn_format = QPushButton("Plain")
        self.btn_format.setCheckable(True)
        saved_mode = self.data.get("paste_mode", "Plain")
        self.btn_format.setChecked(saved_mode == "Plain")
        self.btn_format.setText(saved_mode)
        self.btn_format.setFixedHeight(24)
        self.btn_format.toggled.connect(self.toggle_paste_mode)

        # ---------------- HEADER WIDGETS ASSEMBLY ----------------
        self.header_layout.addWidget(self.tab_bar)
        self.header_layout.addWidget(self.btn_add_tab)
        self.header_layout.addWidget(self.btn_del_tab)
        self.header_layout.addWidget(self.btn_new)
        self.header_layout.addWidget(self.btn_save)

        self.header_layout.addStretch(1)

        self.header_layout.addWidget(self.btn_home)
        self.header_layout.addWidget(self.btn_end)

        self.header_layout.addStretch(1)

        self.header_layout.addWidget(self.btn_add_line)
        self.header_layout.addWidget(self.btn_bullet_toggle)
        
        self.header_layout.addWidget(self.btn_bold)
        self.header_layout.addWidget(self.btn_italic)
        self.header_layout.addWidget(self.btn_under)
        self.header_layout.addWidget(self.btn_strike)

        self.header_layout.addWidget(self.btn_clear_fmt)
        self.header_layout.addWidget(self.btn_settings_toggle)
        self.header_layout.addWidget(self.btn_help)
        self.header_layout.addWidget(self.btn_clear)
        self.header_layout.addWidget(self.btn_format)

        self.main_layout.addWidget(self.header_widget)

        self.mini_settings_frame = QFrame()
        self.mini_settings_frame.setVisible(False)
        mini_layout = QGridLayout(self.mini_settings_frame)
        mini_layout.setContentsMargins(2, 2, 2, 2)
        mini_layout.setSpacing(6)

        self.cb_tray = QCheckBox("Tray Icon")
        self.cb_tray.setChecked(self.data.get("tray_visible", "True") == "True")
        self.cb_tray.toggled.connect(self.on_tray_toggled)
        mini_layout.addWidget(self.cb_tray, 0, 0)

        self.cb_focus = QCheckBox("Close when clicked outside")
        self.cb_focus.setChecked(self.data.get("close_on_focus_loss", "True") == "True")
        self.cb_focus.toggled.connect(self.mark_dirty)
        mini_layout.addWidget(self.cb_focus, 0, 1)

        self.cb_ctrl_c = QCheckBox("Ctrl+C Closes UI")
        self.cb_ctrl_c.setChecked(self.data.get("ctrl_c_closes", "True") == "True")
        self.cb_ctrl_c.toggled.connect(self.mark_dirty)
        mini_layout.addWidget(self.cb_ctrl_c, 0, 2)

        self.cb_top = QCheckBox("Always on top")
        self.cb_top.setChecked(self.data.get("always_on_top", "True") == "True")
        self.cb_top.toggled.connect(self.apply_window_flags)
        mini_layout.addWidget(self.cb_top, 0, 3)

        self.cb_lock_window = QCheckBox("Lock Window")
        self.cb_lock_window.setChecked(self.data.get("window_locked", "False") == "True")
        self.cb_lock_window.toggled.connect(self.set_lock_state)
        mini_layout.addWidget(self.cb_lock_window, 0, 4)

        self.cb_normal_window = QCheckBox("Act like normal window")
        self.cb_normal_window.setChecked(self.data.get("normal_window", "False") == "True")
        self.cb_normal_window.toggled.connect(self.apply_window_flags)
        mini_layout.addWidget(self.cb_normal_window, 1, 5)

        self.cb_lock_cursor = QCheckBox("Lock to Cursor")
        self.cb_lock_cursor.setChecked(self.data.get("lock_to_cursor", "False") == "True")
        self.cb_lock_cursor.toggled.connect(self.on_lock_cursor_toggled)
        mini_layout.addWidget(self.cb_lock_cursor, 1, 0)

        self.cb_hide_shortkeys = QCheckBox("Hide shortkeys")
        self.cb_hide_shortkeys.setChecked(self.data.get("hide_shortkeys", "False") == "True")
        self.cb_hide_shortkeys.toggled.connect(self.on_hide_shortkeys_toggled)
        mini_layout.addWidget(self.cb_hide_shortkeys, 1, 1)
        
        self.cb_sidebar = QCheckBox("Sidebar on Right")
        self.cb_sidebar.setChecked(self.data.get("sidebar_right", "False") == "True")
        self.cb_sidebar.toggled.connect(self.toggle_sidebar_position)
        mini_layout.addWidget(self.cb_sidebar, 1, 2)
        
        self.cb_hide_extra = QCheckBox("Hide Extra Layout")
        self.cb_hide_extra.setChecked(self.data.get("hide_extra", "False") == "True")
        self.cb_hide_extra.toggled.connect(self.on_hide_extra_toggled)
        mini_layout.addWidget(self.cb_hide_extra, 2, 5)

        self.font_panel = QWidget()
        font_layout = QHBoxLayout(self.font_panel)
        font_layout.setContentsMargins(0, 0, 0, 0)
        font_layout.addWidget(QLabel("Font:"))
        self.font_combo = QComboBox()
        self.font_combo.addItems(["Verdana", "Tahoma", "Consolas", "Calibri", "Times New Roman", "Arial", "Segoe UI", "Courier New"])
        saved_font = self.data.get("font_family", "Verdana")
        idx = self.font_combo.findText(saved_font)
        if idx >= 0: self.font_combo.setCurrentIndex(idx)
        self.font_combo.currentTextChanged.connect(self.change_font_family)
        font_layout.addWidget(self.font_combo)
        self.font_spin = QSpinBox()
        self.font_spin.setRange(6, 48)
        self.font_spin.setValue(int(self.data.get("font_size", "10")))
        self.font_spin.valueChanged.connect(self.change_font_size)
        font_layout.addWidget(self.font_spin)
        mini_layout.addWidget(self.font_panel, 1, 3, 1, 2)

        self.preview_panel = QWidget()
        preview_layout = QHBoxLayout(self.preview_panel)
        preview_layout.setContentsMargins(0, 0, 0, 0)
        preview_layout.addWidget(QLabel("View:"))
        self.preview_combo = QComboBox()
        self.preview_combo.addItems(["None", "Raw", "Markdown"])
        saved_preview = self.data.get("preview_mode", "None")
        idx = self.preview_combo.findText(saved_preview)
        if idx >= 0: self.preview_combo.setCurrentIndex(idx)
        self.preview_combo.currentIndexChanged.connect(self.change_preview_mode)
        preview_layout.addWidget(self.preview_combo)
        mini_layout.addWidget(self.preview_panel, 2, 0)

        self.theme_panel = QWidget()
        theme_layout = QHBoxLayout(self.theme_panel)
        theme_layout.setContentsMargins(0, 0, 0, 0)
        theme_layout.addWidget(QLabel("Theme:"))
        self.cb_theme = QComboBox()
        self.cb_theme.addItems(["Original Gold", "Vintage Dark", "Vintage Classic"])
        saved_theme = self.data.get("theme", "Original Gold")
        idx = self.cb_theme.findText(saved_theme)
        if idx >= 0: self.cb_theme.setCurrentIndex(idx)
        self.cb_theme.currentTextChanged.connect(self.change_theme)
        theme_layout.addWidget(self.cb_theme)
        mini_layout.addWidget(self.theme_panel, 2, 1)

        self.btn_hotkeys = QPushButton("Hotkeys...")
        self.btn_hotkeys.setFixedHeight(20)
        self.btn_hotkeys.clicked.connect(self.open_hotkey_settings)
        mini_layout.addWidget(self.btn_hotkeys, 2, 2)

        self.btn_backup = QPushButton("Backup DB")
        self.btn_backup.setFixedHeight(20)
        self.btn_backup.clicked.connect(self.backup_db)
        mini_layout.addWidget(self.btn_backup, 2, 3)

        self.btn_restore = QPushButton("Restore DB")
        self.btn_restore.setFixedHeight(20)
        self.btn_restore.clicked.connect(self.restore_db)
        mini_layout.addWidget(self.btn_restore, 2, 4)
        
        # Apply initial hide_extra state
        self.on_hide_extra_toggled(self.cb_hide_extra.isChecked())
        
        self.main_layout.addWidget(self.mini_settings_frame)

        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setChildrenCollapsible(True)
        self.splitter.setOpaqueResize(True)

        self.left_panel = QWidget()
        self.left_layout = QVBoxLayout(self.left_panel)
        self.left_layout.setContentsMargins(0,0,0,0)
        self.left_layout.setSpacing(2)

        # Snippets Section
        self.snippets_section = QWidget()
        self.snippets_section_layout = QVBoxLayout(self.snippets_section)
        self.snippets_section_layout.setContentsMargins(0,0,0,0)
        self.snippets_section_layout.setSpacing(1)

        snip_header = QHBoxLayout()
        snip_header.setContentsMargins(0,0,0,0)
        self.snip_label = QLabel("Snippets")
        snip_header.addWidget(self.snip_label)
        snip_header.addStretch()
        
        self.btn_add_snip = QPushButton("+")
        self.btn_add_snip.setFixedSize(20, 18)
        self.btn_add_snip.clicked.connect(self.save_snippet)
        snip_header.addWidget(self.btn_add_snip)
        self.btn_del_snip = QPushButton("-")
        self.btn_del_snip.setFixedSize(20, 18)
        self.btn_del_snip.clicked.connect(self.del_last_snippet)
        snip_header.addWidget(self.btn_del_snip)
        self.snippets_section_layout.addLayout(snip_header)

        self.search_bar = QLineEdit()
        self.search_bar.setPlaceholderText("Search...")
        self.search_bar.setFixedHeight(18)
        self.search_bar.textChanged.connect(self.refresh_snippets_panel)
        self.snippets_section_layout.addWidget(self.search_bar)

        self.btn_page_up = QPushButton("▲")
        self.btn_page_up.setFixedHeight(14)
        self.btn_page_up.clicked.connect(lambda: self.change_page(-1))
        self.snippets_section_layout.addWidget(self.btn_page_up)

        self.snippets_widget = DropVerticalWidget(self)
        self.snippet_buttons = []
        for _ in range(10):
            w = SnippetWidget(self)
            w.hide()
            self.snippets_widget.layout.addWidget(w)
            self.snippet_buttons.append(w)
        self.snippets_section_layout.addWidget(self.snippets_widget)

        self.btn_page_down = QPushButton("▼")
        self.btn_page_down.setFixedHeight(14)
        self.btn_page_down.clicked.connect(lambda: self.change_page(1))
        self.snippets_section_layout.addWidget(self.btn_page_down)
        self.left_layout.addWidget(self.snippets_section)

        # Silos Section
        self.silos_section = QWidget()
        self.silos_section_layout = QVBoxLayout(self.silos_section)
        self.silos_section_layout.setContentsMargins(0,0,0,0)
        self.silos_section_layout.setSpacing(1)

        silo_header = QHBoxLayout()
        silo_header.setContentsMargins(0,0,0,0)
        self.silo_label = QLabel("Silos")
        silo_header.addWidget(self.silo_label)
        silo_header.addStretch()
        self.btn_add_silo = QPushButton("+")
        self.btn_add_silo.setFixedSize(20, 18)
        self.btn_add_silo.clicked.connect(self.add_silo)
        silo_header.addWidget(self.btn_add_silo)
        self.btn_del_silo = QPushButton("-")
        self.btn_del_silo.setFixedSize(20, 18)
        self.btn_del_silo.clicked.connect(self.del_silo)
        silo_header.addWidget(self.btn_del_silo)
        self.silos_section_layout.addLayout(silo_header)

        self.btn_silo_up = QPushButton("▲")
        self.btn_silo_up.setFixedHeight(14)
        self.btn_silo_up.clicked.connect(lambda: self.change_silo_page(-1))
        self.silos_section_layout.addWidget(self.btn_silo_up)

        self.silos_widget = SiloDropWidget(self)
        self.silo_buttons = []
        for _ in range(10):
            btn = DraggableSiloButton(self)
            btn.setFixedHeight(22)
            btn.hide()
            self.silos_widget.layout.addWidget(btn)
            self.silo_buttons.append(btn)
        self.silos_section_layout.addWidget(self.silos_widget)

        self.btn_silo_down = QPushButton("▼")
        self.btn_silo_down.setFixedHeight(14)
        self.btn_silo_down.clicked.connect(lambda: self.change_silo_page(1))
        self.silos_section_layout.addWidget(self.btn_silo_down)
        self.left_layout.addWidget(self.silos_section)

        self.center_panel = QWidget()
        self.center_layout = QVBoxLayout(self.center_panel)
        self.center_layout.setContentsMargins(0,0,0,0)
        self.center_layout.setSpacing(2)

        # ---------------- SEARCH & REPLACE FRAME ----------------
        self.search_frame = QFrame()
        self.search_frame.setObjectName("SearchFrame")
        self.search_frame.setVisible(False)
        search_layout = QHBoxLayout(self.search_frame)
        search_layout.setContentsMargins(4, 2, 4, 2)
        search_layout.setSpacing(6)
        
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Find...")
        self.search_input.returnPressed.connect(self.find_next)
        search_layout.addWidget(self.search_input)
        
        self.btn_find_prev = QPushButton("◄")
        self.btn_find_prev.clicked.connect(self.find_prev)
        self.btn_find_prev.setFixedSize(24, 24)
        search_layout.addWidget(self.btn_find_prev)
        
        self.btn_find_next = QPushButton("►")
        self.btn_find_next.clicked.connect(self.find_next)
        self.btn_find_next.setFixedSize(24, 24)
        search_layout.addWidget(self.btn_find_next)
        
        self.replace_input = QLineEdit()
        self.replace_input.setPlaceholderText("Replace with...")
        search_layout.addWidget(self.replace_input)
        
        self.btn_replace = QPushButton("Replace")
        self.btn_replace.clicked.connect(self.replace_text)
        self.btn_replace.setFixedHeight(24)
        search_layout.addWidget(self.btn_replace)
        
        self.btn_replace_all = QPushButton("Replace All")
        self.btn_replace_all.clicked.connect(self.replace_all)
        self.btn_replace_all.setFixedHeight(24)
        search_layout.addWidget(self.btn_replace_all)
        
        self.btn_close_search = QPushButton("✕")
        self.btn_close_search.setFixedSize(24, 24)
        self.btn_close_search.clicked.connect(self.close_search)
        search_layout.addWidget(self.btn_close_search)
        
        self.center_layout.addWidget(self.search_frame)
        # --------------------------------------------------------

        self.text_area = VaultTextEdit(self)
        self.text_area.setPlaceholderText("Vault ready. Execute.")
        self.text_area.setWordWrapMode(QTextOption.WrapMode.WrapAnywhere)
        self.text_area.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.text_area.textChanged.connect(self.cache_current_text)

        font_size = self.data.get("font_size", 11)
        font = QFont(self.data.get("font_family", "Verdana"), font_size)
        font.setStyleStrategy(QFont.StyleStrategy.NoAntialias | QFont.StyleStrategy.NoSubpixelAntialias)
        self.text_area.setFont(font)

        self.center_layout.addWidget(self.text_area, 1)

        self.preview_area = QTextEdit(readOnly=True)
        self.preview_area.setVisible(False)
        self.preview_area.setFixedHeight(80)
        self.preview_area.setFont(font)
        self.center_layout.addWidget(self.preview_area)
        
        self.main_layout.addWidget(self.splitter, 1)
        self.apply_sidebar_position()

        safe_idx = max(0, min(self.data.get("last_tab_idx", 0), self.tab_bar.count()-1))
        if self.tab_bar.count() > 0: self.tab_bar.setCurrentIndex(safe_idx)

        self.refresh_snippets_panel()
        self.refresh_temp_presets()
        self.change_preview_mode(self.preview_combo.currentIndex())
        self.on_tray_toggled(self.cb_tray.isChecked())
        self.set_lock_state(self.cb_lock_window.isChecked())
        self.apply_scaled_ui()
        self.apply_font()
        
        self.splitter.splitterMoved.connect(self.on_splitter_moved)

    # ---------------- FIND & REPLACE LOGIC ----------------
    def show_find(self):
        self.search_frame.show()
        self.replace_input.hide()
        self.btn_replace.hide()
        self.btn_replace_all.hide()
        self.search_input.setFocus()
        self.search_input.selectAll()

    def show_replace(self):
        self.search_frame.show()
        self.replace_input.show()
        self.btn_replace.show()
        self.btn_replace_all.show()
        self.search_input.setFocus()
        self.search_input.selectAll()

    def close_search(self):
        self.search_frame.hide()
        self.text_area.setFocus()

    def find_next(self):
        self.find_text(backward=False)

    def find_prev(self):
        self.find_text(backward=True)

    def find_text(self, backward=False):
        text = self.search_input.text()
        if not text: return
        options = QTextDocument.FindFlag(0)
        if backward: options |= QTextDocument.FindFlag.FindBackward
        found = self.text_area.find(text, options)
        if not found:
            cursor = self.text_area.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.End if backward else QTextCursor.MoveOperation.Start)
            self.text_area.setTextCursor(cursor)
            self.text_area.find(text, options)

    def replace_text(self):
        cursor = self.text_area.textCursor()
        if cursor.hasSelection() and cursor.selectedText() == self.search_input.text():
            cursor.insertText(self.replace_input.text())
        self.find_next()

    def replace_all(self):
        search_str = self.search_input.text()
        if not search_str: return
        replace_str = self.replace_input.text()
        cursor = self.text_area.textCursor()
        cursor.beginEditBlock()
        cursor.movePosition(QTextCursor.MoveOperation.Start)
        self.text_area.setTextCursor(cursor)
        count = 0
        while self.text_area.find(search_str):
            self.text_area.textCursor().insertText(replace_str)
            count += 1
        cursor.endEditBlock()
        QMessageBox.information(self, "Replace All", f"Replaced {count} occurrences.")
    # --------------------------------------------------------

    # ---------------- TEXT FORMATTING LOGIC -----------------
    def apply_format(self, fmt_type):
        cursor = self.text_area.textCursor()
        fmt = cursor.charFormat()
        
        if fmt_type == 'bold':
            fmt.setFontWeight(QFont.Weight.Bold if fmt.fontWeight() != QFont.Weight.Bold else QFont.Weight.Normal)
        elif fmt_type == 'italic':
            fmt.setFontItalic(not fmt.fontItalic())
        elif fmt_type == 'underline':
            fmt.setFontUnderline(not fmt.fontUnderline())
        elif fmt_type == 'strike':
            fmt.setFontStrikeOut(not fmt.fontStrikeOut())
            
        cursor.mergeCharFormat(fmt)
        self.text_area.setTextCursor(cursor)
        self.text_area.setFocus()
        self.mark_dirty()
    # --------------------------------------------------------

    def save_silo_to_file(self):
        text = self.text_area.toPlainText()
        if not text: return
        self.ignore_focus_loss = True
        try:
            path, _ = QFileDialog.getSaveFileName(self, "Save Silo", "", "Text Files (*.txt);;Markdown Files (*.md);;All Files (*.*)")
        finally:
            self.ignore_focus_loss = False
        self.activateWindow()
        if path:
            try:
                with open(path, 'w', encoding='utf-8') as f:
                    f.write(text)
                QMessageBox.information(self, "Saved", f"Silo successfully saved to:\n{path}")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to save file:\n{e}")

    def on_splitter_moved(self, pos, index):
        self.mark_dirty()

    def toggle_sidebar_visibility(self):
        sizes = self.splitter.sizes()
        is_right = self.data.get("sidebar_right", "False") == "True"
        idx = 1 if is_right else 0
        
        if sizes[idx] == 0:
            sizes[idx] = 130
            sizes[1-idx] = self.width() - 130
        else:
            sizes[1-idx] += sizes[idx]
            sizes[idx] = 0
            
        self.splitter.setSizes(sizes)
        self.mark_dirty()

    def toggle_focus_mode(self):
        self.focus_mode = not getattr(self, "focus_mode", False)
        
        if self.focus_mode:
            self._pre_focus_header = self.header_widget.isVisible()
            self._pre_focus_mini = self.mini_settings_frame.isVisible()
            self._pre_focus_sizes = self.splitter.sizes()
            self._pre_focus_search = self.search_frame.isVisible()
            
            self.header_widget.hide()
            self.mini_settings_frame.hide()
            self.search_frame.hide()
            
            is_right = self.data.get("sidebar_right", "False") == "True"
            idx = 1 if is_right else 0
            sizes = self.splitter.sizes()
            sizes[1-idx] += sizes[idx]
            sizes[idx] = 0
            self.splitter.setSizes(sizes)
        else:
            self.header_widget.setVisible(self._pre_focus_header)
            self.mini_settings_frame.setVisible(self._pre_focus_mini)
            self.search_frame.setVisible(self._pre_focus_search)
            self.splitter.setSizes(self._pre_focus_sizes)

    def insert_snippet_text(self, text, position):
        if not text: return
        self.mark_dirty()
        cursor = self.text_area.textCursor()
        cursor.beginEditBlock()
        
        if position == "top":
            cursor.movePosition(QTextCursor.MoveOperation.Start)
            if self.text_area.toPlainText():
                cursor.insertText(text + "\n")
            else:
                cursor.insertText(text)
        elif position == "bot":
            cursor.movePosition(QTextCursor.MoveOperation.End)
            if self.text_area.toPlainText() and not self.text_area.toPlainText().endswith('\n'):
                cursor.insertText("\n")
            cursor.insertText(text)
        elif position == "ins":
            cursor.insertText(text)
            
        cursor.endEditBlock()
        self.text_area.setTextCursor(cursor)
        self.text_area.ensureCursorVisible()
        self.text_area.setFocus()

    def toggle_sidebar_position(self, checked):
        self.data["sidebar_right"] = "True" if checked else "False"
        self.apply_sidebar_position()
        self.mark_dirty()

    def apply_sidebar_position(self):
        is_right = self.data.get("sidebar_right", "False") == "True"
        if is_right:
            self.splitter.insertWidget(0, self.center_panel)
            self.splitter.insertWidget(1, self.left_panel)
            self.splitter.setCollapsible(0, False)
            self.splitter.setCollapsible(1, True)
        else:
            self.splitter.insertWidget(0, self.left_panel)
            self.splitter.insertWidget(1, self.center_panel)
            self.splitter.setCollapsible(0, True)
            self.splitter.setCollapsible(1, False)

        sizes = self.splitter.sizes()
        if sum(sizes) == 0:
            if is_right:
                self.splitter.setSizes([self.width()-130, 130])
            else:
                self.splitter.setSizes([130, self.width()-130])

    def swap_temp_slots(self, idx1, idx2):
        if idx1 == idx2: return
        temps = self.data["temp_presets"]
        temps[idx1], temps[idx2] = temps[idx2], temps[idx1]
        self.mark_dirty()
        self.refresh_temp_presets()

    def toggle_mini_settings(self):
        self.mini_settings_frame.setVisible(not self.mini_settings_frame.isVisible())

    def on_tray_toggled(self, checked):
        if hasattr(self, 'tray_icon'): self.tray_icon.setVisible(checked)
        self.data["tray_visible"] = str(checked)
        self.mark_dirty()

    def apply_window_flags(self, _=None):
        self.data["always_on_top"] = "True" if self.cb_top.isChecked() else "False"
        self.data["normal_window"] = "True" if self.cb_normal_window.isChecked() else "False"
        flags = Qt.WindowType.Widget
        if not self.cb_normal_window.isChecked(): flags |= Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool
        if self.cb_top.isChecked(): flags |= Qt.WindowType.WindowStaysOnTopHint
        self.setWindowFlags(flags)
        if self.isVisible(): self.show()
        self.register_all_hotkeys()
        self.mark_dirty()

    def on_hide_extra_toggled(self, checked):
        self.data["hide_extra"] = "True" if checked else "False"
        self.mark_dirty()
        
        # Hide extra layout elements
        self.font_panel.setVisible(not checked)
        self.preview_panel.setVisible(not checked)
        self.theme_panel.setVisible(not checked)
        self.cb_lock_cursor.setVisible(not checked)
        self.cb_hide_shortkeys.setVisible(not checked)
        self.cb_sidebar.setVisible(not checked)

    def on_hide_shortkeys_toggled(self, checked):
        self.data["hide_shortkeys"] = "True" if checked else "False"
        self.mark_dirty()
        self.refresh_snippets_panel()

    def on_lock_cursor_toggled(self, checked):
        self.data["lock_to_cursor"] = "True" if checked else "False"
        self.mark_dirty()
        self.refresh_snippets_panel()

    def backup_db(self):
        self.save_data_to_db(force=True)
        path, _ = QFileDialog.getSaveFileName(self, "Backup Database", "", "SQLite DB (*.db)")
        if path:
            try:
                with sqlite3.connect(path) as dest:
                    self.conn.backup(dest)
                QMessageBox.information(self, "Success", "Backup saved successfully!")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to save backup:\n{e}")

    def restore_db(self):
        path, _ = QFileDialog.getOpenFileName(self, "Restore Database", "", "SQLite DB (*.db)")
        if path:
            self.ignore_focus_loss = True
            try:
                reply = QMessageBox.question(self, "Confirm Restore", "Restoring will overwrite current data. The app will close and must be restarted manually. Continue?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            finally:
                self.ignore_focus_loss = False
                
            if reply == QMessageBox.StandardButton.Yes:
                try:
                    # Validate DB file
                    with sqlite3.connect(path) as test_conn:
                        test_conn.execute("SELECT 1 FROM sqlite_master LIMIT 1")
                except Exception:
                    QMessageBox.critical(self, "Error", "Selected file is not a valid SQLite database.")
                    return
                try:
                    self.auto_save_timer.stop()
                    self.conn.close()
                    time.sleep(0.1)
                    shutil.copy2(path, DB_FILE)
                    for ext in ["-wal", "-shm"]:
                        if os.path.exists(DB_FILE + ext):
                            os.remove(DB_FILE + ext)
                    QApplication.quit()
                except Exception as e:
                    QMessageBox.critical(self, "Error", f"Failed to restore backup:\n{e}")
                    self.init_db()

    def clear_formatting(self):
        cursor = self.text_area.textCursor()
        cursor.beginEditBlock()
        
        clean_format = QTextCharFormat()
        base_size = self.data.get("font_size", 11)
        font_name = self.data.get("font_family", "Verdana")
        try: scale = float(self.data.get("ui_scale", "1.0"))
        except Exception: scale = 1.0
        font_size = max(8, int(round(base_size * scale)))
        
        font = QFont(font_name, font_size)
        font.setStyleStrategy(QFont.StyleStrategy(int(QFont.StyleStrategy.NoAntialias.value) | int(QFont.StyleStrategy.NoSubpixelAntialias.value)))
        clean_format.setFont(font)
        
        if cursor.hasSelection():
            raw_text = cursor.selectedText().replace('\u2029', '\n')
            cursor.insertText(raw_text, clean_format)
        else:
            raw_text = self.text_area.toPlainText()
            cursor.select(QTextCursor.SelectionType.Document)
            cursor.insertText(raw_text, clean_format)
            
        cursor.endEditBlock()
        self.apply_font()
        self.mark_dirty()

    def load_snippet_for_edit(self, cat, global_idx):
        slot_data = self.data["categories"].get(cat, [None] * 100)[global_idx] if cat in self.data["categories"] else None
        if not slot_data: return
        self.mark_dirty()
        self.ignore_focus_loss, self._suspend_cache = True, True
        try:
            self.text_area.blockSignals(True)
            self.text_area.setPlainText(slot_data["text"])
            self.text_area.moveCursor(QTextCursor.MoveOperation.End)
        finally:
            self.text_area.blockSignals(False)
            self._suspend_cache, self.ignore_focus_loss = False, False
        self.editing_snippet = (cat, global_idx)
        self.btn_save.setText("Update")
        theme_name = self.data.get("theme", "Original Gold")
        if theme_name in THEMES:
            base_style = THEMES[theme_name]["btn_save"]
            self.btn_save.setStyleSheet(base_style.replace("background-color:", "background-color: #d35400 !important; /*") + " */ background-color: #d35400; color: #ffffff;")
        self.text_area.setFocus()
        self.text_area.ensureCursorVisible()
        self.activateWindow()

    def prompt_delete_snippet(self, cat, global_idx):
        self.ignore_focus_loss = True
        try:
            reply = QMessageBox.question(self, "Delete Snippet", "Delete this snippet?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        finally:
            self.ignore_focus_loss = False
        self.activateWindow()
        if reply == QMessageBox.StandardButton.Yes: self.delete_preset_by_index(cat, global_idx)

    def rename_snippet(self, cat, global_idx):
        slots = self.data["categories"][cat]
        if slots[global_idx] is None: return
        old_name = slots[global_idx]["name"]
        self.ignore_focus_loss = True
        try:
            new_name, ok = QInputDialog.getText(self, "Rename Snippet", "New name:", text=old_name)
        finally:
            self.ignore_focus_loss = False
        self.activateWindow()
        if ok and new_name and new_name.strip():
            slots[global_idx]["name"] = new_name.strip()
            self.mark_dirty()
            self.refresh_snippets_panel()

    def copy_snippet_to_clipboard(self, text):
        self.safe_set_clipboard(text)

    def adjust_font_size(self, step):
        base = int(self.font_spin.value())
        new_size = max(self.font_spin.minimum(), min(self.font_spin.maximum(), base + step))
        if new_size != base: self.font_spin.setValue(new_size)

    def adjust_ui_scale(self, delta):
        try: current = float(self.data.get("ui_scale", "1.0"))
        except Exception: current = 1.0
        current = max(0.75, min(1.75, round(current + delta, 2)))
        self.data["ui_scale"] = f"{current:.2f}"
        self.apply_font()
        self.apply_scaled_ui()
        self.mark_dirty()

    def apply_scaled_ui(self):
        try: scale = float(self.data.get("ui_scale", "1.0"))
        except Exception: scale = 1.0
        base_heights = {
            "btn_clear": 24, "btn_format": 24, "btn_clear_fmt": 24, "btn_add_line": 24,
            "btn_bullet_toggle": 24, "btn_save": 24, "btn_home": 24, "btn_end": 24,
            "btn_new": 24, "btn_add_tab": 24, "btn_del_tab": 24, "btn_settings_toggle": 24,
            "btn_page_up": 14, "btn_page_down": 14, "btn_silo_up": 14, "btn_silo_down": 14,
            "btn_add_snip": 18, "btn_del_snip": 18, "btn_hotkeys": 20, "btn_backup": 20, "btn_restore": 20,
            "btn_sidebar_toggle": 24, "btn_bold": 24, "btn_italic": 24, "btn_under": 24, "btn_strike": 24,
            "btn_find_prev": 24, "btn_find_next": 24, "btn_close_search": 24, "btn_replace": 24, "btn_replace_all": 24
        }
        for name, base in base_heights.items():
            w = getattr(self, name, None)
            if w is not None:
                try: w.setFixedHeight(max(14, int(round(base * scale))))
                except Exception: pass
        
        if hasattr(self, 'btn_sidebar_toggle'):
            self.btn_sidebar_toggle.setFixedWidth(max(14, int(round(24 * scale))))
        for btn_name in ('btn_bold', 'btn_italic', 'btn_under', 'btn_strike', 'btn_find_prev', 'btn_find_next', 'btn_close_search'):
            w = getattr(self, btn_name, None)
            if w is not None:
                try: w.setFixedWidth(max(14, int(round(24 * scale))))
                except Exception: pass
            
        try: self.left_panel.setMinimumWidth(max(80, int(round(130 * scale))))
        except Exception: pass
        self.updateGeometry()

    def move_cursor_home(self):
        cursor = self.text_area.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.Start)
        self.text_area.setTextCursor(cursor)
        self.text_area.ensureCursorVisible()
        self.text_area.setFocus()

    def move_cursor_end(self):
        cursor = self.text_area.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self.text_area.setTextCursor(cursor)
        self.text_area.ensureCursorVisible()
        self.text_area.setFocus()

    def insert_add_line(self):
        cursor = self.text_area.textCursor()
        cursor.beginEditBlock()
        cursor.insertText("\n\n\n---\n\n\n")
        cursor.endEditBlock()
        self.text_area.setTextCursor(cursor)
        self.text_area.ensureCursorVisible()
        self.text_area.setFocus()
        self.mark_dirty()

    def toggle_bullet_conversion(self):
        cursor = self.text_area.textCursor()
        cursor.beginEditBlock()
        if cursor.hasSelection(): 
            text = cursor.selectedText().replace('\u2029', '\n')
        else: 
            text = self.text_area.toPlainText()
            cursor.select(QTextCursor.SelectionType.Document)
            
        lines = text.splitlines()
        if not lines: 
            cursor.endEditBlock()
            return
            
        if any(re.match(r'^\s*•\s*', line) for line in lines): 
            new_lines = [re.sub(r'^(\s*)•\s*', r'\1- ', line) for line in lines]
        else: 
            new_lines = [re.sub(r'^(\s*)-\s*', r'\1• ', line) for line in lines]
            
        new_text = "\n".join(new_lines)
        cursor.insertText(new_text)
        cursor.endEditBlock()
        self.text_area.setFocus()
        self.mark_dirty()

    def set_lock_state(self, checked):
        self.is_locked = bool(checked)
        self.data["window_locked"] = "True" if checked else "False"
        self._locked_geometry = self.geometry()
        if checked:
            self.setMinimumSize(self.size())
            self.setMaximumSize(self.size())
        else:
            self.setMinimumSize(480, 320)
            self.setMaximumSize(16777215, 16777215)
        self.mark_dirty()

    def toggle_lock(self):
        self.cb_lock_window.setChecked(not self.cb_lock_window.isChecked())

    def toggle_always_on_top(self):
        self.cb_top.setChecked(not self.cb_top.isChecked())

    def moveEvent(self, event):
        if getattr(self, "_is_restoring_geometry", False): return
        if getattr(self, "is_locked", False) and self._locked_geometry is not None and self.geometry() != self._locked_geometry:
            self._is_restoring_geometry = True
            self.setGeometry(self._locked_geometry)
            self._is_restoring_geometry = False
            return
        if self.isVisible(): self.data["last_geometry"] = f"{self.x()},{self.y()},{self.width()},{self.height()}"
        super().moveEvent(event)

    def resizeEvent(self, event):
        if getattr(self, "_is_restoring_geometry", False): return
        if getattr(self, "is_locked", False) and self._locked_geometry is not None and self.geometry() != self._locked_geometry:
            self._is_restoring_geometry = True
            self.setGeometry(self._locked_geometry)
            self._is_restoring_geometry = False
            return
        if self.isVisible(): self.data["last_geometry"] = f"{self.x()},{self.y()},{self.width()},{self.height()}"
        super().resizeEvent(event)

    def mousePressEvent(self, event):
        if getattr(self, "is_locked", False):
            event.ignore(); return
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if getattr(self, "is_locked", False): return
        if event.buttons() == Qt.MouseButton.LeftButton and hasattr(self, '_drag_pos'):
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()

    def place_window(self):
        self.adjustSize()
        if self.cb_lock_cursor.isChecked():
            cp = QCursor.pos()
            self.move(cp.x() - self.width()//2, cp.y() - self.height()//2)
        else:
            geo_str = self.data.get("last_geometry", "")
            if geo_str:
                try:
                    x, y, w, h = map(int, geo_str.split(','))
                    w, h = max(w, self.minimumWidth()), max(h, self.minimumHeight())
                    valid_screen = False
                    for screen in QApplication.screens():
                        if screen.availableGeometry().contains(x, y):
                            valid_screen = True; break
                    if not valid_screen:
                        cp = QCursor.pos()
                        x, y = cp.x() - w//2, cp.y() - h//2
                    self.setGeometry(x, y, w, h)
                except Exception:
                    cp = QCursor.pos()
                    self.move(cp.x() - self.width()//2, cp.y() - self.height()//2)
            else:
                cp = QCursor.pos()
                self.move(cp.x() - self.width()//2, cp.y() - self.height()//2)

    def show_window(self):
        self.place_window()
        self.show()
        self.activateWindow()
        self.raise_()
        self.text_area.setFocus()

    def cancel_editing(self):
        self.editing_snippet = None
        self.btn_save.setText("Save")
        theme_name = self.data.get("theme", "Original Gold")
        if theme_name in THEMES: self.btn_save.setStyleSheet(THEMES[theme_name]["btn_save"])

    def clear_text(self):
        cursor = self.text_area.textCursor()
        cursor.beginEditBlock()
        cursor.select(QTextCursor.SelectionType.Document)
        cursor.removeSelectedText()
        cursor.endEditBlock()
        self.cancel_editing()
        self.text_area.setFocus()

    def add_category(self):
        if len(self.data['cats_order']) >= 100: return
        self.ignore_focus_loss = True
        try:
            name, ok = QInputDialog.getText(self, "New Tab", "Enter tab name:")
        finally:
            self.ignore_focus_loss = False
        self.activateWindow()
        if ok and name and name.strip() not in self.data['cats_order']:
            name = name.strip()
            self.data['cats_order'].append(name)
            self.data['categories'][name] = [None]*100
            self.tab_bar.addTab(name)
            self.tab_bar.setCurrentIndex(self.tab_bar.count()-1)
            self.mark_dirty()

    def del_category(self):
        if self.tab_bar.count() <= 1: return
        idx = self.tab_bar.currentIndex()
        cat = self.data['cats_order'][idx]
        self.ignore_focus_loss = True
        try:
            reply = QMessageBox.question(self, "Delete Tab", f"Nuke '{cat}' and all snippets?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        finally:
            self.ignore_focus_loss = False
        self.activateWindow()
        if reply == QMessageBox.StandardButton.Yes:
            self.data['cats_order'].pop(idx)
            del self.data['categories'][cat]
            if cat in self.current_pages: del self.current_pages[cat]
            self.tab_bar.removeTab(idx)
            self.mark_dirty()

    def on_tab_changed(self, index):
        if index < 0: return
        self.data["last_tab_idx"] = index
        self.mark_dirty()
        self.cancel_editing()
        self.refresh_snippets_panel()
        self.text_area.setFocus()

    def get_current_category(self):
        idx = self.tab_bar.currentIndex()
        if 0 <= idx < len(self.data['cats_order']): return self.data['cats_order'][idx]
        return None

    def change_font_family(self, font_name):
        self.data["font_family"] = font_name
        self.apply_font()

    def change_font_size(self, size):
        self.data["font_size"] = size
        self.apply_font()
        self.mark_dirty()

    def change_theme(self, theme_name):
        self.data["theme"] = theme_name
        self.mark_dirty()
        self.apply_theme()

    def apply_theme(self):
        theme_name = self.data.get("theme", "Original Gold")
        if theme_name not in THEMES: theme_name = "Original Gold"
        theme = THEMES[theme_name]
        
        QApplication.instance().setStyleSheet(theme["stylesheet"])
        self.btn_new.setStyleSheet(theme["btn_new"])
        self.btn_save.setStyleSheet(theme["btn_save"])
        self.btn_help.setStyleSheet(theme["lbl_help"])
        self.mini_settings_frame.setStyleSheet(theme["mini_settings"])
        
        if hasattr(self, 'snip_label'): self.snip_label.setStyleSheet(theme["lbl_title"])
        if hasattr(self, 'silo_label'): self.silo_label.setStyleSheet(theme["lbl_title"])
        
        if hasattr(self, 'tray_icon'):
            icon = create_tray_icon(theme["tray_color"])
            self.tray_icon.setIcon(icon)
            self.setWindowIcon(icon)
            
        self.refresh_snippets_panel()
        self.refresh_temp_presets()

    def apply_font(self):
        base_size = self.data.get("font_size", 11)
        font_name = self.data.get("font_family", "Verdana")
        try: scale = float(self.data.get("ui_scale", "1.0"))
        except Exception: scale = 1.0
        font_size = max(8, int(round(base_size * scale)))
        font = QFont(font_name, font_size)
        font.setStyleStrategy(QFont.StyleStrategy(int(QFont.StyleStrategy.NoAntialias.value) | int(QFont.StyleStrategy.NoSubpixelAntialias.value)))
        
        self.text_area.setFont(font)
        self.text_area.document().setDefaultFont(font)
        self.preview_area.setFont(font)
        try: QApplication.instance().setFont(font)
        except Exception: pass
        self.refresh_snippets_panel()

    def change_preview_mode(self, index):
        mode = self.preview_combo.currentText()
        if mode == "None":
            self.preview_area.setVisible(False)
            if self._preview_connected:
                self.text_area.textChanged.disconnect(self.update_preview)
                self._preview_connected = False
        else:
            self.preview_area.setVisible(True)
            if not self._preview_connected:
                 self.text_area.textChanged.connect(self.update_preview)
                 self._preview_connected = True
            self.update_preview()
        self.mark_dirty()

    def update_preview(self):
        text = self.text_area.toPlainText()
        mode = self.preview_combo.currentText()
        if mode == "Raw": self.preview_area.setPlainText(text)
        elif mode == "Markdown": self.preview_area.setHtml(self.simple_markdown_to_html(text))

    @staticmethod
    def simple_markdown_to_html(text):
        text = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', text)
        text = re.sub(r'\*(.*?)\*', r'<i>\1</i>', text)
        text = re.sub(r'`(.*?)`', r'<code>\1</code>', text)
        text = re.sub(r'\[(.*?)\]\((.*?)\)', r'<a href="\2">\1</a>', text)
        text = text.replace('\n', '<br>')
        return f"<html><body style='color:#c4ba9f; background:#0f0f0f'>{text}</body></html>"

    def toggle_paste_mode(self, checked):
        self.btn_format.setText("Plain" if checked else "Formatted")
        self.mark_dirty()

    def save_snippet(self):
        text = self.text_area.toPlainText().strip()
        if not text: return
        cat = self.get_current_category()
        if not cat: return
        slots = self.data["categories"][cat]
        
        if self.editing_snippet and self.editing_snippet[0] == cat:
            idx = self.editing_snippet[1]
            old_name = slots[idx]["name"] if slots[idx] else ""
            slots[idx] = {"name": old_name, "text": text}
            self.mark_dirty()
            self.refresh_snippets_panel()
            self.cancel_editing()
            return

        if None not in slots: return
        auto_name = (text.replace('\n',' ')[:22] + "...") if len(text) > 22 else text.replace('\n',' ')
        self.ignore_focus_loss = True
        try:
            name, ok = QInputDialog.getText(self, f"Save Preset", "Name:", text=auto_name)
        finally:
            self.ignore_focus_loss = False
        self.activateWindow()
        if ok and name:
            slots[slots.index(None)] = {"name": name, "text": text}
            self.mark_dirty()
            self.refresh_snippets_panel()

    def save_snippet_as_number(self):
        text = self.text_area.toPlainText().strip()
        if not text: return
        cat = self.get_current_category()
        if not cat: return
        max_slots = len(self.data["categories"][cat])
        
        self.ignore_focus_loss = True
        try:
            num, ok = QInputDialog.getInt(self, "Snippet Number", f"Enter snippet number (1-{max_slots}):", 1, 1, max_slots)
        finally:
            self.ignore_focus_loss = False
        self.activateWindow()
        
        if not ok: return
        slot = num - 1
        slots = self.data["categories"][cat]
        
        if slots[slot] is not None:
            self.ignore_focus_loss = True
            try:
                reply = QMessageBox.question(self, "Overwrite Snippet", f"Snippet #{num} already exists. Overwrite?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            finally:
                self.ignore_focus_loss = False
            self.activateWindow()
            if reply != QMessageBox.StandardButton.Yes: return
                
        auto_name = (text.replace('\n',' ')[:22] + "...") if len(text) > 22 else text.replace('\n',' ')
        self.ignore_focus_loss = True
        try:
            name, ok = QInputDialog.getText(self, "Save Snippet", "Name:", text=auto_name)
        finally:
            self.ignore_focus_loss = False
        self.activateWindow()
        
        if ok and name:
            slots[slot] = {"name": name, "text": text}
            self.mark_dirty()
            self.refresh_snippets_panel()
            self.cancel_editing()

    def del_last_snippet(self):
        cat = self.get_current_category()
        if not cat: return
        slots = self.data["categories"][cat]
        for i in range(99, -1, -1):
            if slots[i] is not None:
                slots[i] = None; break
        self.mark_dirty()
        self.refresh_snippets_panel()

    def change_page(self, delta):
        cat = self.get_current_category()
        if not cat: return
        active = sum(1 for s in self.data["categories"][cat] if s is not None)
        max_page = max(0, math.ceil(active / 10.0) - 1)
        new_page = self.current_pages.get(cat, 0) + delta
        if 0 <= new_page <= max_page:
            self.current_pages[cat] = new_page
            self.refresh_snippets_panel()

    def refresh_snippets_panel(self):
        cat = self.get_current_category()
        if not cat:
            self.snippets_section.setVisible(False)
            return
            
        query = self.search_bar.text().strip().lower()
        active_items = []
        for i, s in enumerate(self.data["categories"][cat]):
            if s is not None:
                if not query or query in s["name"].lower() or query in s["text"].lower():
                    active_items.append((i, s))
                    
        total_active = len(active_items)
        if total_active == 0:
            self.snippets_section.setVisible(False)
            return
            
        self.snippets_section.setVisible(True)
        page = min(self.current_pages.get(cat, 0), max(0, math.ceil(total_active / 10.0) - 1))
        self.current_pages[cat] = page
        
        start_idx = page * 10
        page_items = active_items[start_idx:start_idx+10]
        
        theme_name = self.data.get("theme", "Original Gold")
        if theme_name not in THEMES: theme_name = "Original Gold"
        preset_colors = THEMES[theme_name]["preset_colors"]
        font_family = self.data.get("font_family", "Verdana")
        hide_keys = self.data.get("hide_shortkeys", "False") == "True"
        
        try: scale = float(self.data.get("ui_scale", "1.0"))
        except Exception: scale = 1.0

        for i, w in enumerate(self.snippet_buttons):
            if i < len(page_items):
                view_idx = len(page_items) - 1 - i
                global_idx, item = page_items[view_idx]
                d_idx = start_idx + view_idx + 1
                key_label = "" if hide_keys else (f"[{d_idx%10 if d_idx%10 != 0 else 0}] " if d_idx <= 10 else f"[{d_idx}] ")
                disp = item["name"][:22] + "\u2026" if len(item["name"])>22 else item["name"]
                color = preset_colors[global_idx % len(preset_colors)]
                w.update_data(f"{key_label}{disp}", cat, global_idx, item["text"], color, font_family, scale)
            else:
                w.hide()
            
        self.btn_page_up.setVisible(page > 0)
        self.btn_page_down.setVisible(page < math.ceil(total_active / 10.0) - 1)

    def move_preset_to_index(self, cat, src_idx, tgt_idx):
        if src_idx == tgt_idx: return
        slots = self.data["categories"][cat]
        slots[src_idx], slots[tgt_idx] = slots[tgt_idx], slots[src_idx]
        self.mark_dirty()
        self.refresh_snippets_panel()

    def delete_preset_by_index(self, cat, global_idx):
        self.data["categories"][cat][global_idx] = None
        self.mark_dirty()
        self.refresh_snippets_panel()

    def add_silo(self):
        if len(self.data["temp_presets"]) < 100:
            self.data["temp_presets"].append("")
            self.mark_dirty()
            self.refresh_temp_presets()
            self.cancel_editing()

    def del_silo(self):
        if len(self.data["temp_presets"]) > 1:
            self.data["temp_presets"].pop()
            if self.active_temp_slot >= len(self.data["temp_presets"]):
                self.active_temp_slot = len(self.data["temp_presets"]) - 1
            self.mark_dirty()
            self.refresh_temp_presets()
            self.cancel_editing()

    def select_empty_silo(self):
        self.data["temp_presets"][self.active_temp_slot] = self.text_area.toPlainText()
        for i, content in enumerate(self.data["temp_presets"]):
            if not content.strip():
                self.silo_page = i // 10
                self._switch_to_slot(i, initial=True)
                return
        if len(self.data["temp_presets"]) < 100:
            i = len(self.data["temp_presets"])
            self.data["temp_presets"].append("")
            self.silo_page = i // 10
            self._switch_to_slot(i, initial=True)

    def change_silo_page(self, delta):
        max_page = max(0, math.ceil(len(self.data["temp_presets"]) / 10.0) - 1)
        new_page = self.silo_page + delta
        if 0 <= new_page <= max_page:
            self.silo_page = new_page
            self.refresh_temp_presets()

    def _switch_to_slot(self, idx, initial=False):
        if not initial:
            if self.editing_snippet:
                self.save_snippet()
            else:
                self.data["temp_presets"][self.active_temp_slot] = self.text_area.toPlainText()
            
        self.cancel_editing()
        self.active_temp_slot = idx
        new_text = self.data["temp_presets"][idx]
        self._suspend_cache = True
        
        try:
            self.text_area.blockSignals(True)
            if initial: self.text_area.setPlainText(new_text)
            else:
                cursor = self.text_area.textCursor()
                cursor.beginEditBlock()
                cursor.select(QTextCursor.SelectionType.Document)
                cursor.insertText(new_text)
                cursor.endEditBlock()
            self.text_area.moveCursor(QTextCursor.MoveOperation.End)
        finally:
            self.text_area.blockSignals(False)
            self._suspend_cache = False
            
        self.refresh_temp_presets()
        self.text_area.setFocus()
        self.text_area.ensureCursorVisible()
        if not initial: self.mark_dirty()

    def refresh_temp_presets(self):
        total = len(self.data["temp_presets"])
        if total == 0:
            self.silos_section.setVisible(False)
            return
            
        self.silos_section.setVisible(True)
        max_page = max(0, math.ceil(total / 10.0) - 1)
        if self.silo_page > max_page: self.silo_page = max_page
        
        theme_name = self.data.get("theme", "Original Gold")
        if theme_name not in THEMES: theme_name = "Original Gold"
        active_color = THEMES[theme_name]["active_temp_color"]
        inactive_color = THEMES[theme_name]["inactive_temp_color"]

        start_idx = self.silo_page * 10
        for i, btn in enumerate(self.silo_buttons):
            slot_idx = start_idx + i
            if slot_idx < total:
                text = self.data["temp_presets"][slot_idx].replace('\n',' ').strip()
                display_idx = slot_idx + 1
                label = f"{display_idx}: {text[:22]}\u2026" if len(text)>22 else (f"{display_idx}: {text}" if text else str(display_idx))
                bg_color = active_color if slot_idx == self.active_temp_slot else inactive_color
                btn.update_data(label, slot_idx, bg_color)
            else:
                btn.hide()
            
        self.btn_silo_up.setVisible(self.silo_page > 0)
        self.btn_silo_down.setVisible(self.silo_page < max_page)

    def show_temp_menu(self, idx, pos):
        cur = self.text_area.toPlainText().strip()
        menu = QMenu(self)
        menu.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        menu.setFont(QApplication.font())
        if cur:
            menu.addAction("Save text as Snippet", self.save_snippet)
            menu.addAction("Save as Snippet #...", self.save_snippet_as_number)
        if self.data["temp_presets"][idx]:
            menu.addAction(f"Clear Silo {idx+1}", lambda: self.clear_temp(idx))
            
        self.ignore_focus_loss = True
        try:
            menu.exec(pos)
        finally:
            self.ignore_focus_loss = False
        self.activateWindow()

    def clear_temp(self, idx):
        self.data["temp_presets"][idx] = ""
        if idx == self.active_temp_slot: self.clear_text()
        self.mark_dirty()
        self.refresh_temp_presets()

    def safe_set_clipboard(self, text):
        if text:
            from PyQt6.QtGui import QGuiApplication
            clip = QGuiApplication.clipboard()
            if self.btn_format.text() != "Plain":
                mime = QMimeData()
                mime.setText(text)
                mime.setHtml(self.simple_markdown_to_html(text))
                clip.setMimeData(mime)
            else:
                 clip.setText(text)

    def auto_paste(self, text):
        if not text.strip(): return
        self.safe_set_clipboard(text)
        self.hide_and_save()
        QTimer.singleShot(150, self.simulate_ctrl_v)

    @staticmethod
    def simulate_ctrl_v():
        class KEYBDINPUT(ctypes.Structure):
            _fields_ = (("wVk", ctypes.c_ushort),
                        ("wScan", ctypes.c_ushort),
                        ("dwFlags", ctypes.c_ulong),
                        ("time", ctypes.c_ulong),
                        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)))
        class INPUT_union(ctypes.Union):
            _fields_ = (("ki", KEYBDINPUT), ("mi", ctypes.c_ulong * 6), ("hi", ctypes.c_ulong * 6))
        class INPUT(ctypes.Structure):
            _fields_ = (("type", ctypes.c_ulong), ("union", INPUT_union))
            
        def send_key(vk, up=False):
            i = INPUT(type=1)
            i.union.ki.wVk = vk
            i.union.ki.dwFlags = 2 if up else 0
            ctypes.windll.user32.SendInput(1, ctypes.byref(i), ctypes.sizeof(i))

        VK_SHIFT, VK_MENU, VK_LWIN, VK_RWIN = 0x10, 0x12, 0x5B, 0x5C
        VK_CTRL, VK_V = 0x11, 0x56

        # Release modifiers logically to prevent Ctrl+Shift+V etc
        for vk in (VK_SHIFT, VK_MENU, VK_LWIN, VK_RWIN): send_key(vk, True)
        
        send_key(VK_CTRL)
        send_key(VK_V)
        send_key(VK_V, True)
        send_key(VK_CTRL, True)

    def setup_global_shortcuts(self):
        QShortcut(QKeySequence("Ctrl+D"), self).activated.connect(self.toggle_focus_mode)
        QShortcut(QKeySequence("Ctrl+F"), self).activated.connect(self.show_find)
        QShortcut(QKeySequence("Ctrl+H"), self).activated.connect(self.show_replace)
        QShortcut(QKeySequence("Ctrl+Shift+S"), self).activated.connect(self.save_silo_to_file)
        QShortcut(QKeySequence("Esc"), self).activated.connect(self.hide_and_save)
        QShortcut(QKeySequence("Ctrl+S"), self).activated.connect(self.save_snippet)
        for i in range(1, 11): QShortcut(QKeySequence(f"F{i}"), self).activated.connect(lambda i=i: self.fire_shortcut(i))
        QShortcut(QKeySequence("Ctrl+Q"), self).activated.connect(self.cycle_snap_corner)
        QShortcut(QKeySequence("Ctrl+Alt+Shift+Q"), self).activated.connect(self.quit_app)

    def fire_shortcut(self, idx):
        cat = self.get_current_category()
        if not cat: return
        query = self.search_bar.text().strip().lower()
        active_items = []
        for i, s in enumerate(self.data["categories"][cat]):
            if s is not None:
                if not query or query in s["name"].lower() or query in s["text"].lower():
                    active_items.append((i, s))
        
        page = self.current_pages.get(cat, 0)
        start_idx = page * 10
        page_items = active_items[start_idx:start_idx+10]
        
        i = idx - 1
        if i < len(page_items):
            view_idx = len(page_items) - 1 - i
            global_idx, item = page_items[view_idx]
            self.auto_paste(item["text"])

    def fire_global_snippet_from_cat(self, cat, idx):
        if not cat: return
        active_snippets = [s for s in self.data["categories"].get(cat, []) if s is not None]
        if 0 <= idx < len(active_snippets): self.auto_paste(active_snippets[idx]["text"])

    def cycle_snap_corner(self):
        self.resize(960, 540)
        screen = QApplication.primaryScreen().availableGeometry()
        sw, sh = screen.width(), screen.height()
        if self._snap_first_press:
            self.snap_index = 0
            self._snap_first_press = False
        corners = [(sw - 960, sh - 540), (0, sh - 540), (0, 0), (sw - 960, 0)]
        x, y = corners[self.snap_index % 4]
        self.move(screen.x() + x, screen.y() + y)
        self.snap_index = (self.snap_index + 1) % 4

    def cache_current_text(self):
        if getattr(self, "_suspend_cache", False): return
        self.mark_dirty()
        if not self.editing_snippet:
            self.data["temp_presets"][self.active_temp_slot] = self.text_area.toPlainText()
            page_start = self.silo_page * 10
            if page_start <= self.active_temp_slot < page_start + 10:
                view_idx = self.active_temp_slot - page_start
                if view_idx < len(self.silo_buttons):
                    btn = self.silo_buttons[view_idx]
                    text = self.data["temp_presets"][self.active_temp_slot].replace('\n',' ').strip()
                    display_idx = self.active_temp_slot + 1
                    label = f"{display_idx}: {text[:22]}\u2026" if len(text)>22 else (f"{display_idx}: {text}" if text else str(display_idx))
                    btn.setText(label)
    
    def hide_and_save(self): 
        self.save_data_to_db()
        if getattr(self, "is_locked", False):
            self.show()
            self.raise_()
            self.activateWindow()
            return
        self.hide()

    def changeEvent(self, event):
        if event.type() == QEvent.Type.WindowStateChange and self.isMinimized() and getattr(self, "is_locked", False):
            QTimer.singleShot(0, self.showNormal)
            QTimer.singleShot(0, self.raise_)
            QTimer.singleShot(0, self.activateWindow)
        if event.type() == QEvent.Type.ActivationChange and not self.isActiveWindow() and not self.ignore_focus_loss:
            if self.cb_focus.isChecked() and not self.isMinimized() and not self.cb_normal_window.isChecked():
                self.hide_and_save()
        super().changeEvent(event)

    def open_hotkey_settings(self):
        dlg = HotkeySettingsDialog(self)
        dlg.exec()

    def show_quick_list(self):
        if hasattr(self, 'quick_list') and self.quick_list is not None:
            try:
                self.quick_list.close()
            except Exception:
                pass
        self.quick_list = QuickListWidget(self)
        self.quick_list.show()
        self.quick_list.activateWindow()
        self.quick_list.setFocus()

    def fire_global_snippet(self, idx):
        cat = self.get_current_category()
        self.fire_global_snippet_from_cat(cat, idx)

    def init_tray(self):
        theme_name = self.data.get("theme", "Original Gold")
        if theme_name not in THEMES: theme_name = "Original Gold"
        color = THEMES[theme_name]["tray_color"]
        self.tray_icon = QSystemTrayIcon(self)
        self.tray_icon.setIcon(create_tray_icon(color))
        menu = QMenu()
        menu.setFont(QApplication.font())
        menu.addAction("Open FastPrompter", self.show_window)
        menu.addAction("Settings", self.open_settings)
        menu.addSeparator()
        menu.addAction("Exit", self.quit_app)
        self.tray_icon.setContextMenu(menu)
        self.tray_icon.activated.connect(self.on_tray_click)
        self.tray_icon.setVisible(self.cb_tray.isChecked())

    def on_tray_click(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.Trigger: self.show_window()

    def open_settings(self):
        self.show_window()
        if not self.mini_settings_frame.isVisible(): self.toggle_mini_settings()

    def quit_app(self):
        if getattr(self, "is_locked", False):
            self.show()
            self.raise_()
            self.activateWindow()
            return
        self.save_data_to_db(force=True)
        if hasattr(self, 'tray_icon'): self.tray_icon.hide()
        QApplication.quit()

    def closeEvent(self, event):
        if getattr(self, "is_locked", False):
            event.ignore()
            self.show()
            self.raise_()
            self.activateWindow()
            return
        self.quit_app()
        event.accept()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    font = QFont("Verdana", 11)
    font.setStyleStrategy(QFont.StyleStrategy.NoAntialias | QFont.StyleStrategy.NoSubpixelAntialias)
    app.setFont(font)

    sock = try_connect_to_server(3, 0.05)
    if sock is not None:
        sock.write(b"SHOW")
        sock.waitForBytesWritten(500)
        sock.disconnectFromServer()
        sys.exit(0)

    QApplication.setQuitOnLastWindowClosed(False)
    window = FastPrompter()
    hk_filter = HotkeyFilter(window)
    app.installNativeEventFilter(hk_filter)
    sys.exit(app.exec())