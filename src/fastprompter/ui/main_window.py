import sys, os, json, ctypes, time, re, math, shutil
import ctypes.wintypes
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                             QHBoxLayout, QTextEdit, QPushButton, QInputDialog,
                             QMessageBox, QLabel, QSystemTrayIcon,
                             QMenu, QSizePolicy, QSpinBox, QComboBox,
                             QCheckBox, QTabBar, QFrame, QLineEdit, QFileDialog,
                             QDialog, QFormLayout, QGridLayout, QSplitter, QDockWidget)
from PyQt6.QtCore import Qt, QEvent, QTimer, QMimeData, QAbstractNativeEventFilter, QPoint
from PyQt6.QtGui import (QCursor, QFont, QIcon, QPixmap, QColor,
                         QShortcut, QKeySequence, QTextOption, QDrag, QTextCursor,
                         QTextCharFormat, QTextDocument, QFontDatabase, QGuiApplication)
from PyQt6.QtNetwork import QLocalSocket, QLocalServer
import sqlite3
from PyQt6 import sip

from .spotlight_palette import SpotlightPalette

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

from fastprompter.theme.themes import THEMES

from fastprompter.core.config import extract_bg, extract_color, create_tray_icon
from fastprompter.ui.editor import VaultTextEdit
from fastprompter.ui.snippet_panel import DraggableButton, SnippetWidget, DropVerticalWidget, DraggableSiloButton, SiloDropWidget
from fastprompter.core.hotkeys import HotkeyManager
from fastprompter.ui.settings import HotkeyWidget, HotkeySettingsDialog
from fastprompter.ui.pie_menu import QuickListWidget

from fastprompter.core.hotkeys import parse_hotkey

def try_connect_to_server(retries=3, delay=0.05):
    for _ in range(retries):
        sock = QLocalSocket()
        sock.connectToServer(SERVER_NAME)
        if sock.waitForConnected(100): return sock
        time.sleep(delay)
    return None

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
                    elif msg.wParam == 5: self.window.show_spotlight(); return True, 0
                    elif 10 <= msg.wParam <= 19: self.window.fire_global_snippet(msg.wParam - 10); return True, 0
        except Exception: pass
        return False, 0


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
        for hk_id in self.registered_hotkeys: ctypes.windll.user32.UnregisterHotKey(None, hk_id)
        self.registered_hotkeys.clear()

    def register_all_hotkeys(self):
        self.unregister_all_hotkeys()
        self._register_single(self.data.get("global_hotkey", "Alt+X"), 1)
        self._register_single(self.data.get("pie_menu_hotkey", "Shift+Alt+X"), 2)
        self._register_single(self.data.get("lock_window_hotkey", "Ctrl+Shift+L"), 3)
        self._register_single(self.data.get("always_on_top_hotkey", "Ctrl+Shift+E"), 4)
        self._register_single(self.data.get("spotlight_hotkey", "Ctrl+Alt+Space"), 5)
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
        if self.isHidden() or self.isMinimized() or not self.isVisible() or not self.isActiveWindow():
            self.show_window()
        else:
            self.hide_and_save()

    def show_spotlight(self):
        screen = QGuiApplication.screenAt(QCursor.pos())
        if not screen:
            screen = QApplication.primaryScreen()
        geometry = screen.availableGeometry()
        
        # Center on the active screen
        x = geometry.x() + (geometry.width() - self.spotlight.width()) // 2
        y = geometry.y() + (geometry.height() - self.spotlight.height()) // 2
        
        self.spotlight.move(x, y)
        self.spotlight.show()
        self.spotlight.raise_()
        self.spotlight.activateWindow()
        self.spotlight.search_input.setFocus()

    def init_db(self):
        try:
            self.conn = sqlite3.connect(DB_FILE, check_same_thread=True)
            self.conn.execute('PRAGMA journal_mode=WAL;')
            cur = self.conn.cursor()
            try:
                with sqlite3.connect(DB_FILE + ".bak") as dest:
                    self.conn.backup(dest)
            except Exception: pass
            
            cur.execute("CREATE TABLE IF NOT EXISTS presets (category TEXT, slot INTEGER, name TEXT, content TEXT, PRIMARY KEY (category, slot))")
            cur.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)")
            cur.execute("CREATE TABLE IF NOT EXISTS temp_presets (slot INTEGER PRIMARY KEY, content TEXT)")
            self.conn.commit()

            self.data = {
                "categories": {"Code": [None]*100, "Text": [None]*100, "Misc": [None]*100}, "cats_order": ["Code", "Text", "Misc"],
                "last_text": "", "last_tab_idx": 0, "last_geometry": "", "temp_presets": [""]*10, "active_temp_slot": 0,
                "font_size": 11, "preview_mode": "None", "paste_mode": "Plain", "tray_visible": "True", "global_hotkey": "Alt+X",
                "pie_menu_hotkey": "Shift+Alt+X", "lock_window_hotkey": "Ctrl+Shift+L", "always_on_top_hotkey": "Ctrl+Shift+E",
                "close_on_focus_loss": "True", "ctrl_c_closes": "True", "theme": "Default", "ui_scale": "1.0", "window_locked": "False",
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
        except Exception: pass

    def save_data_to_db(self, force=False):
        if not getattr(self, "conn", None): return
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
                    ('always_on_top_hotkey', self.data.get("always_on_top_hotkey", "Ctrl+Shift+E")), ('theme', self.data.get("theme", "Default")),
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
            try:
                dest_conn = sqlite3.connect(DB_FILE + ".bak")
                with dest_conn:
                    self.conn.backup(dest_conn)
                dest_conn.close()
            except Exception: pass
        except sqlite3.Error: pass

    def init_ui(self):
        flags = Qt.WindowType.Window if self.data.get("normal_window", "False") == "True" else Qt.WindowType.Widget
        if self.data.get("normal_window", "False") != "True": flags |= Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool
        if self.data.get("always_on_top", "True") == "True": flags |= Qt.WindowType.WindowStaysOnTopHint
        self.setWindowFlags(flags)
        self.setWindowTitle("FastPrompter")
        self.setMinimumSize(480, 320)
        
        self.auto_save_timer = QTimer(self)
        self.auto_save_timer.timeout.connect(self.save_data_to_db)
        self.auto_save_timer.start(5000)
        self.setMouseTracking(True)
        self._initializing_ui, self._suspend_temp_sync = True, True

        self.spotlight = SpotlightPalette(self.data)

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
            "<b>FastPrompter Tips & Hotkeys:</b><br>"
            "• <i>Global Hotkey</i>: Show/Hide UI from anywhere.<br>"
            "• <b>Ctrl+D</b>: Zen/Focus Mode.<br>"
            "• <b>Ctrl+F</b>: Find.<br>"
            "• <b>Ctrl+H</b>: Replace.<br>"
            "• <b>Ctrl+S</b>: Save Snippet.<br>"
            "• <b>Ctrl+N</b>: New Snippet (Empty Editor).<br>"
            "• <b>Ctrl+Q</b>: Cycle Snap Corner (All Monitors).<br>"
            "• <b>Ctrl+Shift+L</b>: Lock Window Mode.<br>"
            "• <b>Ctrl+Shift+E</b>: Always on Top Toggle.<br>"
            "• <b>Ctrl+Shift+S</b>: Export Silo to file.<br>"
            "• <b>Shift+Alt+X</b>: Pie Menu/Quick List.<br>"
            "• <b>F1..F10</b>: Paste Snippet.<br>"
            "• <b>Ctrl+Alt+Shift+Q</b>: Quit Application."
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
        self.cb_theme.addItems(["Default", "Default", "Vintage Dark", "Vintage Classic"])
        saved_theme = self.data.get("theme", "Default")
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
        
        self.preset_frame = QWidget()
        preset_layout = QHBoxLayout(self.preset_frame)
        preset_layout.setContentsMargins(0, 0, 0, 0)
        preset_layout.addWidget(QLabel("Layout:"))
        self.btn_preset1 = QPushButton("Default")
        self.btn_preset1.clicked.connect(lambda: self.load_preset(1))
        self.btn_preset2 = QPushButton("Vertical")
        self.btn_preset2.clicked.connect(lambda: self.load_preset(2))
        self.btn_preset3 = QPushButton("Minimal")
        self.btn_preset3.clicked.connect(lambda: self.load_preset(3))
        self.btn_reset_dock = QPushButton("Reset")
        self.btn_reset_dock.clicked.connect(self.apply_sidebar_position)
        preset_layout.addWidget(self.btn_preset1)
        preset_layout.addWidget(self.btn_preset2)
        preset_layout.addWidget(self.btn_preset3)
        preset_layout.addWidget(self.btn_reset_dock)
        mini_layout.addWidget(self.preset_frame, 3, 0, 1, 6)
        
        self.on_hide_extra_toggled(self.cb_hide_extra.isChecked())
        
        self.main_layout.addWidget(self.mini_settings_frame)

        self.inner_main = QMainWindow()
        self.inner_main.setWindowFlags(Qt.WindowType.Widget)
        self.inner_main.setDockNestingEnabled(True)
        self.inner_main.setDockOptions(QMainWindow.DockOption.AllowNestedDocks | QMainWindow.DockOption.AllowTabbedDocks)

        self.snippets_dock = QDockWidget("Snippets", self.inner_main)
        self.snippets_dock.setObjectName("SnippetsDock")
        self.snippets_dock.setAllowedAreas(Qt.DockWidgetArea.AllDockWidgetAreas)
        
        self.silos_dock = QDockWidget("Silos", self.inner_main)
        self.silos_dock.setObjectName("SilosDock")
        self.silos_dock.setAllowedAreas(Qt.DockWidgetArea.AllDockWidgetAreas)

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

        self.snippets_dock.setWidget(self.snippets_section)

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
        self.silos_dock.setWidget(self.silos_section)

        self.center_panel = QWidget()
        self.center_layout = QVBoxLayout(self.center_panel)
        self.center_layout.setContentsMargins(0,0,0,0)
        self.center_layout.setSpacing(2)

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
        
        self.inner_main.setCentralWidget(self.center_panel)
        self.main_layout.addWidget(self.inner_main, 1)
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
        if not (0 <= idx1 < len(temps) and 0 <= idx2 < len(temps)): return
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
        flags = Qt.WindowType.Window if self.cb_normal_window.isChecked() else Qt.WindowType.Widget
        if not self.cb_normal_window.isChecked(): flags |= Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool
        if self.cb_top.isChecked(): flags |= Qt.WindowType.WindowStaysOnTopHint
        self.setWindowFlags(flags)
        if self.isVisible():
            self.show()
            self.register_all_hotkeys()
        self.register_all_hotkeys()
        self.mark_dirty()

    def on_hide_extra_toggled(self, checked):
        self.data["hide_extra"] = "True" if checked else "False"
        self.mark_dirty()
        
        self.font_panel.setVisible(not checked)
        self.preview_panel.setVisible(not checked)
        self.theme_panel.setVisible(not checked)
        self.cb_lock_cursor.setVisible(not checked)
        self.cb_hide_shortkeys.setVisible(not checked)
        self.cb_sidebar.setVisible(not checked)

    def load_preset(self, preset_id):
        self.snippets_dock.setFloating(False)
        self.silos_dock.setFloating(False)
        self.snippets_dock.show()
        self.silos_dock.show()
        if preset_id == 1:
            # Default: Side by side on left or right depending on cb_sidebar
            area = Qt.DockWidgetArea.RightDockWidgetArea if self.cb_sidebar.isChecked() else Qt.DockWidgetArea.LeftDockWidgetArea
            self.inner_main.addDockWidget(area, self.snippets_dock)
            self.inner_main.addDockWidget(area, self.silos_dock)
        elif preset_id == 2:
            # Vertical: Snippets on Left, Silos on Right
            self.inner_main.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.snippets_dock)
            self.inner_main.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.silos_dock)
        elif preset_id == 3:
            # Minimal: Editor only
            self.snippets_dock.hide()
            self.silos_dock.hide()

    def apply_sidebar_position(self):
        # Called when toggling sidebar right checkbox or resetting
        area = Qt.DockWidgetArea.RightDockWidgetArea if self.cb_sidebar.isChecked() else Qt.DockWidgetArea.LeftDockWidgetArea
        if not self.snippets_dock.isFloating() and not self.snippets_dock.isHidden():
            self.inner_main.addDockWidget(area, self.snippets_dock)
        if not self.silos_dock.isFloating() and not self.silos_dock.isHidden():
            self.inner_main.addDockWidget(area, self.silos_dock)

    def on_hide_shortkeys_toggled(self, checked):
        self.data["hide_shortkeys"] = "True" if checked else "False"
        self.mark_dirty()
        self.refresh_snippets_panel()

    def on_lock_cursor_toggled(self, checked):
        self.data["lock_to_cursor"] = "True" if checked else "False"
        self.mark_dirty()
        if checked:
            self.place_window()
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
        path, _ = QFileDialog.getOpenFileName(self, "Restore Backup", "", "SQLite DB (*.db *.bak);;All Files (*)")
        if not path: return
        self.ignore_focus_loss = True
        try:
            reply = QMessageBox.question(self, "Confirm", "App will restart. Proceed?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if reply == QMessageBox.StandardButton.Yes:
                if getattr(self, "conn", None):
                    self.conn.close()
                    self.conn = None
                time.sleep(0.1)
                import shutil
                shutil.copy2(path, DB_FILE)
                for ext in ["-wal", "-shm"]:
                    if os.path.exists(DB_FILE + ext):
                        try: os.remove(DB_FILE + ext)
                        except: pass
                self.quit_app()
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to restore backup:\n{e}")
            self.init_db()
        finally:
            self.ignore_focus_loss = False

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
        clean_format.setFontWeight(QFont.Weight.Normal)
        clean_format.setFontItalic(False)
        clean_format.setFontUnderline(False)
        clean_format.setFontStrikeOut(False)
        
        self.text_area.blockSignals(True)
        try:
            if cursor.hasSelection():
                raw_text = cursor.selectedText().replace('\u2029', '\n')
                cursor.insertText(raw_text, clean_format)
            else:
                raw_text = self.text_area.toPlainText()
                self.text_area.setPlainText(raw_text)
                cursor = self.text_area.textCursor()
                cursor.select(QTextCursor.SelectionType.Document)
                cursor.setCharFormat(clean_format)
                cursor.clearSelection()
                self.text_area.setTextCursor(cursor)
        finally:
            self.text_area.blockSignals(False)
            
        cursor.endEditBlock()
        
        self.apply_font()
        self.mark_dirty()
        self.cache_current_text()

    def load_snippet_for_edit(self, cat, global_idx):
        if self.editing_snippet:
            self.save_snippet()
            
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
        theme_name = self.data.get("theme", "Default")
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

    def _update_last_geometry(self):
        if getattr(self, 'is_locked', False): return
        if not self.isVisible() or self.isMinimized(): return

        geo = self.geometry()
        x, y, w, h = geo.x(), geo.y(), geo.width(), geo.height()
        
        if hasattr(self, "cb_lock_cursor") and self.cb_lock_cursor.isChecked():
            old_geo = self.data.get("last_geometry", "")
            if old_geo:
                try:
                    ox, oy, _, _ = map(int, old_geo.split(','))
                    x, y = ox, oy
                except Exception:
                    pass
                    
        self.data["last_geometry"] = f"{x},{y},{w},{h}"
        self.mark_dirty()

    def moveEvent(self, event):
        if getattr(self, 'is_locked', False) and getattr(self, '_locked_geometry', None):
            if self.geometry() != self._locked_geometry:
                self.setGeometry(self._locked_geometry)
                return
        self._update_last_geometry()
        super().moveEvent(event)

    def resizeEvent(self, event):
        if getattr(self, 'is_locked', False) and getattr(self, '_locked_geometry', None):
            if self.geometry() != self._locked_geometry:
                self.setGeometry(self._locked_geometry)
                return
        self._update_last_geometry()
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
        geo_str = self.data.get("last_geometry", "")
        
        # 1. First, restore or calculate the size
        if geo_str:
            try:
                _, _, saved_w, saved_h = map(int, geo_str.split(','))
                w, h = max(saved_w, self.minimumWidth()), max(saved_h, self.minimumHeight())
                self.resize(w, h)
            except Exception:
                self.adjustSize()
                w, h = self.width(), self.height()
        else:
            self.adjustSize()
            w, h = self.width(), self.height()

        # 2. Then, determine and set the position
        if self.cb_lock_cursor.isChecked():
            cp = QCursor.pos()
            screen = QApplication.screenAt(cp)
            screen_geom = screen.availableGeometry() if screen else QApplication.primaryScreen().availableGeometry()
            
            x = cp.x() - w // 2
            y = cp.y() - h // 2
            
            x = max(screen_geom.left(), min(x, screen_geom.right() - w))
            y = max(screen_geom.top(), min(y, screen_geom.bottom() - h))
            
            self.move(x, y)
        else:
            if geo_str:
                try:
                    x, y, _, _ = map(int, geo_str.split(','))
                    valid_screen = False
                    for screen in QApplication.screens():
                        if screen.availableGeometry().contains(x, y):
                            valid_screen = True; break
                    if not valid_screen:
                        cp = QCursor.pos()
                        x, y = cp.x() - w//2, cp.y() - h//2
                    self.move(x, y)
                except Exception:
                    cp = QCursor.pos()
                    self.move(cp.x() - w//2, cp.y() - h//2)
            else:
                cp = QCursor.pos()
                self.move(cp.x() - w//2, cp.y() - h//2)

    def show_window(self):
        if self.isMinimized():
            self.showNormal()
        self.show()
        self.place_window()
        self.raise_()
        self.activateWindow()
        self.text_area.setFocus()

    def cancel_editing(self):
        self.editing_snippet = None
        self.btn_save.setText("Save")
        theme_name = self.data.get("theme", "Default")
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
        theme_name = self.data.get("theme", "Default")
        if theme_name not in THEMES: theme_name = "Default"
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
        cat = self.get_current_category()
        
        if self.editing_snippet:
            edit_cat, idx = self.editing_snippet
            if edit_cat in self.data["categories"]:
                slots = self.data["categories"][edit_cat]
                if text:
                    old_name = slots[idx]["name"] if slots[idx] else ""
                    slots[idx] = {"name": old_name, "text": text}
                    self.mark_dirty()
                    self.refresh_snippets_panel()
            self.cancel_editing()
            return

        if not text or not cat: return
        slots = self.data["categories"][cat]


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
        
        theme_name = self.data.get("theme", "Default")
        if theme_name not in THEMES: theme_name = "Default"
        preset_colors = THEMES[theme_name]["preset_colors"]
        font_family = self.data.get("font_family", "Verdana")
        hide_keys = self.data.get("hide_shortkeys", "False") == "True"
        
        try: scale = float(self.data.get("ui_scale", "1.0"))
        except Exception: scale = 1.0

        for i, w in enumerate(self.snippet_buttons):
            if i < len(page_items):
                global_idx, item = page_items[i]
                d_idx = i + 1
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
        self.silo_page = idx // 10
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
        
        theme_name = self.data.get("theme", "Default")
        if theme_name not in THEMES: theme_name = "Default"
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
        QTimer.singleShot(150, lambda: not sip.isdeleted(self) and self.simulate_ctrl_v())

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
        QShortcut(QKeySequence("Ctrl+N"), self).activated.connect(self.select_empty_silo)
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
            global_idx, item = page_items[i]
            self.auto_paste(item["text"])

    def fire_global_snippet_from_cat(self, cat, idx):
        if not cat: return
        active_snippets = [s for s in self.data["categories"].get(cat, []) if s is not None]
        if 0 <= idx < len(active_snippets): self.auto_paste(active_snippets[idx]["text"])

    def cycle_snap_corner(self):
        from PyQt6.QtGui import QGuiApplication
        self.resize(960, 540)
        screen = QGuiApplication.screenAt(QCursor.pos())
        if not screen: screen = QApplication.primaryScreen()
        sw, sh = screen.availableGeometry().width(), screen.availableGeometry().height()
        sx, sy = screen.availableGeometry().x(), screen.availableGeometry().y()
        if self._snap_first_press:
            self.snap_index = 0
            self._snap_first_press = False
        corners = [(sw - 960, sh - 540), (0, sh - 540), (0, 0), (sw - 960, 0)]
        x, y = corners[self.snap_index % 4]
        self.move(sx + x, sy + y)
        self.snap_index = (self.snap_index + 1) % 4

    def cache_current_text(self):
        if getattr(self, "_suspend_cache", False): return
        self.mark_dirty()
        current_text = self.text_area.toPlainText()
        if not self.editing_snippet:
            self.data["temp_presets"][self.active_temp_slot] = current_text
            page_start = self.silo_page * 10
            if page_start <= self.active_temp_slot < page_start + 10:
                view_idx = self.active_temp_slot - page_start
                if view_idx < len(self.silo_buttons):
                    btn = self.silo_buttons[view_idx]
                    t = current_text.replace('\n',' ').strip()
                    display_idx = self.active_temp_slot + 1
                    label = f"{display_idx}: {t[:22]}\u2026" if len(t)>22 else (f"{display_idx}: {t}" if t else str(display_idx))
                    btn.setText(label)
        else:
            cat, idx = self.editing_snippet
            if cat in self.data["categories"] and self.data["categories"][cat][idx]:
                self.data["categories"][cat][idx]["text"] = current_text
                if cat == self.get_current_category():
                    self.refresh_snippets_panel()
    
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
            QTimer.singleShot(0, lambda: not sip.isdeleted(self) and self.showNormal())
            QTimer.singleShot(0, lambda: not sip.isdeleted(self) and self.raise_())
            QTimer.singleShot(0, lambda: not sip.isdeleted(self) and self.activateWindow())
        if event.type() == QEvent.Type.ActivationChange and not self.isActiveWindow() and not self.ignore_focus_loss:
            if self.cb_focus.isChecked() and not self.isMinimized() and not self.cb_normal_window.isChecked():
                self.hide_and_save()
        super().changeEvent(event)

    def open_hotkey_settings(self):
        dlg = HotkeySettingsDialog(self)
        dlg.exec()

    def show_quick_list(self):
        if hasattr(self, 'quick_list') and self.quick_list is not None:
            import sip
            if not sip.isdeleted(self.quick_list):
                try: self.quick_list.close()
                except Exception: pass
            self.quick_list = None
            
        self.quick_list = QuickListWidget(self)
        self.quick_list.show()
        self.quick_list.activateWindow()
        self.quick_list.setFocus()

    def fire_global_snippet(self, idx):
        cat = self.get_current_category()
        self.fire_global_snippet_from_cat(cat, idx)

    def init_tray(self):
        theme_name = self.data.get("theme", "Default")
        if theme_name not in THEMES: theme_name = "Default"
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

def main_entry():
    import sys
    from PyQt6.QtGui import QFontDatabase
    app = QApplication(sys.argv)
    app.setWindowIcon(create_tray_icon("#8b4513"))
    font_id = QFontDatabase.addApplicationFont(r"V:\___VAC\__K\__CUSTOMIZATION\_FONT\Verdana_m1.ttf")
    if font_id >= 0:
        family = QFontDatabase.applicationFontFamilies(font_id)[0]
        font = QFont(family, 11)
    else:
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

if __name__ == "__main__":
    main_entry()