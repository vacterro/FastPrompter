import sys, os, json, ctypes, time, re, math, shutil, copy
import ctypes.wintypes
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                             QHBoxLayout, QTextEdit, QPushButton, QInputDialog,
                             QMessageBox, QLabel, QSystemTrayIcon,
                             QMenu, QSizePolicy, QSpinBox, QComboBox,
                             QCheckBox, QTabBar, QFrame, QLineEdit, QFileDialog,
                             QDialog, QFormLayout, QGridLayout, QSplitter)
from PyQt6.QtCore import Qt, QEvent, QTimer, QMimeData, QAbstractNativeEventFilter, QPoint, QUrl, QRect
from PyQt6.QtGui import (QCursor, QFont, QIcon, QPixmap, QColor,
                         QShortcut, QKeySequence, QTextOption, QDrag, QTextCursor,
                         QTextCharFormat, QTextDocument, QFontDatabase)
from PyQt6.QtNetwork import QLocalSocket, QLocalServer
from PyQt6.QtMultimedia import QSoundEffect
import sqlite3
from PyQt6 import sip

user32 = ctypes.windll.user32
user32.RegisterHotKey.argtypes = [ctypes.wintypes.HWND, ctypes.c_int, ctypes.wintypes.UINT, ctypes.wintypes.UINT]
user32.RegisterHotKey.restype = ctypes.wintypes.BOOL
user32.UnregisterHotKey.argtypes = [ctypes.wintypes.HWND, ctypes.c_int]
user32.UnregisterHotKey.restype = ctypes.wintypes.BOOL

from fastprompter.core.state import FastPrompterState

SERVER_NAME = "FastPrompter_Server_V15"

from fastprompter.theme.themes import THEMES
from fastprompter.ui.markdown_highlighter import MarkdownHighlighter

from fastprompter.core.config import extract_bg, extract_color, create_tray_icon
from fastprompter.ui.editor import VaultTextEdit
from fastprompter.ui.snippet_panel import DraggableButton, SnippetWidget, DropVerticalWidget, DraggableSiloButton, SiloDropWidget
from fastprompter.ui.settings import HotkeyWidget, HotkeySettingsDialog, ColorConfigDialog
from fastprompter.ui.pie_menu import QuickListWidget

from fastprompter.core.hotkeys import parse_hotkey

def try_connect_to_server(retries=3, delay=0.05):
    import tempfile
    token_file = os.path.join(tempfile.gettempdir(), "fastprompter_ipc.token")
    token = ""
    if os.path.exists(token_file):
        try:
            with open(token_file, "r") as f:
                token = f.read().strip()
        except Exception:
            pass

    for _ in range(retries):
        sock = QLocalSocket()
        sock.connectToServer(SERVER_NAME)
        if sock.waitForConnected(100):
            # Pass token as property to be picked up by main_entry
            if token:
                sock.setProperty("ipc_token", token)
            return sock
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
                    if msg.wParam in (1, 101): self.window.toggle_visibility(); return True, 0
                    elif msg.wParam in (2, 102): self.window.show_quick_list(); return True, 0
                    elif msg.wParam in (3, 103): self.window.toggle_lock(); return True, 0
                    elif msg.wParam in (4, 104): self.window.toggle_always_on_top(); return True, 0
                    elif msg.wParam in (5, 105): self.window.toggle_visibility(force_sidebar=True); return True, 0
                    elif (10 <= msg.wParam <= 14) or (110 <= msg.wParam <= 114): self.window.fire_global_snippet((msg.wParam % 100) - 10); return True, 0
                    elif (20 <= msg.wParam <= 24) or (120 <= msg.wParam <= 124): self.window.fire_global_silo((msg.wParam % 100) - 20); return True, 0
                elif msg.message == 0x0112: # WM_SYSCOMMAND
                    if (msg.wParam & 0xFFF0) == 0xF100: # SC_KEYMENU
                        return True, 0
        except Exception: pass
        return False, 0

class EdgeResizer(QWidget):
    def __init__(self, target, edge):
        super().__init__(target)
        self.target = target
        self.edge = edge
        self.pressed = False
        self.mouse_start = None
        self.target_rect = None
        
        if edge in ('left', 'right'): self.setCursor(Qt.CursorShape.SizeHorCursor)
        elif edge in ('top', 'bottom'): self.setCursor(Qt.CursorShape.SizeVerCursor)
        elif edge in ('topleft', 'bottomright'): self.setCursor(Qt.CursorShape.SizeFDiagCursor)
        elif edge in ('topright', 'bottomleft'): self.setCursor(Qt.CursorShape.SizeBDiagCursor)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.pressed = True
            self.mouse_start = event.globalPosition().toPoint()
            self.target_rect = self.target.geometry()

    def mouseReleaseEvent(self, event):
        self.pressed = False

    def mouseMoveEvent(self, event):
        if self.pressed:
            delta = event.globalPosition().toPoint() - self.mouse_start
            from PyQt6.QtCore import QRect
            rect = QRect(self.target_rect)
            if 'left' in self.edge:
                new_w = max(self.target.minimumWidth(), rect.width() - delta.x())
                if new_w > self.target.minimumWidth(): rect.setLeft(rect.left() + delta.x())
            if 'right' in self.edge: rect.setWidth(max(self.target.minimumWidth(), rect.width() + delta.x()))
            if 'top' in self.edge:
                new_h = max(self.target.minimumHeight(), rect.height() - delta.y())
                if new_h > self.target.minimumHeight(): rect.setTop(rect.top() + delta.y())
            if 'bottom' in self.edge: rect.setHeight(max(self.target.minimumHeight(), rect.height() + delta.y()))
            self.target.setGeometry(rect)

class FastPrompter(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setMouseTracking(True)
        # QApplication.instance().installEventFilter(self)
        self.ignore_focus_loss, self.registered_hotkeys, self._db_dirty = False, [], False
        
        self.editing_snippet = None
        self.auto_save_timer = QTimer(self)
        self.auto_save_timer.timeout.connect(self.save_data_to_db)
        self.auto_save_timer.start(5000)
        
        self.snap_index, self._snap_first_press, self._preview_connected = 0, True, False
        self.current_pages, self.silo_page, self.ui_scale = {}, 0, 1.0
        self.arc_silo_page, self.arc_page = 0, 0
        self.is_locked, self._suspend_cache, self._locked_geometry = False, False, None
        self._initializing_ui, self._suspend_temp_sync = True, True

        self.silo_last_edited = {}  # {slot_index: timestamp} for color-last-edited system
        self._visible_silos = 10  # dynamically adjusted

        self.setup_single_instance_server()
        self.state = FastPrompterState()
        self.data = self.state.data
        self.conn = self.state.conn
        try: self.active_temp_slot = int(self.data.get("active_temp_slot", 0))
        except Exception: self.active_temp_slot = 0
        try:
            raw_silo_edited = self.data.get("silo_last_edited", {})
            self.silo_last_edited = {int(k): int(v) for k, v in raw_silo_edited.items()}
        except Exception:
            self.silo_last_edited = {}
        
        self.init_ui()
        self.init_tray()
        self.setup_global_shortcuts()
        # Delay global hotkey binding until after UI initialization to prevent race conditions causing silent crashes (Debater Constraint)
        QTimer.singleShot(100, self.register_all_hotkeys)
        
        self._switch_to_slot(self.active_temp_slot, initial=True)
        self._initializing_ui, self._suspend_temp_sync = False, False
        self.apply_font()
        self.apply_theme()
        
        self.topmost_timer = QTimer(self)
        self.topmost_timer.timeout.connect(self.enforce_topmost)
        if self.data.get("always_on_top", "True") == "True":
            self.topmost_timer.start(5000)
        
        self.place_window()

    def _get_custom_colors(self):
        """Parse custom_colors from data, handling string-serialized dicts."""
        custom = self.data.get("custom_colors", {})
        if isinstance(custom, str):
            try: custom = ast.literal_eval(custom)
            except Exception: custom = {}
        return custom if isinstance(custom, dict) else {}

    def mark_dirty(self):
        self.state.mark_dirty()

    def play_sound(self, name):
        if name == "type":
            if self.data.get("sound_typewriter", "False") != "True": return
        else:
            if self.data.get("sound_ui", "False") != "True": return
            
        if not hasattr(self, '_sound_players'):
            self._sound_players = {}
            
        if name not in self._sound_players:
            self._sound_players[name] = QSoundEffect(self)
            
        try:
            vol = int(self.data.get("sound_volume", "5")) / 10.0
            player = self._sound_players[name]
            player.setVolume(vol)
            
            import os
            base_dir = os.path.dirname(os.path.abspath(__file__))
            
            mapping = {
                "new": "newbutton1.wav",
                "save": "tickbox3.wav",
                "silo": "button1.wav",
                "snippet": "button2.wav",
                "tick": "tickbox1.wav",
                "delete": "delete1.wav",
                "clear": "delete1.wav",
                "type": "tickbox1.wav",
                "click": "button1.wav"
            }
            
            file_name = mapping.get(name, f"{name}.wav")
            path = os.path.join(base_dir, "sound", file_name)
            
            if os.path.exists(path):
                # Ensure QUrl has the correct format
                player.setSource(QUrl.fromLocalFile(path))
                player.play()
        except: pass

    def play_click_sound(self): self.play_sound("click")
    def play_tick_sound(self): self.play_sound("tick")

    def enforce_topmost(self):
        if self.data.get("always_on_top", "True") == "True" and not self.isHidden():
            try:
                import ctypes
                HWND_TOPMOST = -1
                SWP_NOSIZE = 1
                SWP_NOMOVE = 2
                ctypes.windll.user32.SetWindowPos(int(self.winId()), HWND_TOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE)
            except Exception:
                pass

    def _deferred_silo_refresh(self):
        """Called once after the window layout is computed to set correct silo count."""
        if hasattr(self, 'silos_widget') and self.silos_widget.height() > 0:
            self._update_visible_silo_count()
            self.refresh_temp_presets()
        else:
            # Layout not ready yet, try again
            QTimer.singleShot(50, self._deferred_silo_refresh)

    def _update_visible_silo_count(self):
        if hasattr(self, 'silos_widget') and self.silos_widget.height() > 0:
            btn_height = max(14, int(round(24 * float(self.data.get("ui_scale", "1.0")))))
            spacing = 2
            self._visible_silos = max(1, (self.silos_widget.height() + spacing) // (btn_height + spacing))
        else:
            self._visible_silos = 10

    def _apply_tooltips(self):
        h_global = self.data.get("global_hotkey", "Alt+X")
        h_pie = self.data.get("pie_menu_hotkey", "Shift+Alt+X")
        h_lock = self.data.get("lock_window_hotkey", "Ctrl+Shift+L")
        h_aot = self.data.get("always_on_top_hotkey", "Ctrl+Shift+E")
        
        if hasattr(self, 'cb_top'): self.cb_top.setToolTip(f"Always on top ({h_aot})")
        if hasattr(self, 'cb_lock_window'): self.cb_lock_window.setToolTip(f"Lock Window ({h_lock})")
        
        shortcuts_info = (
            f"--- GLOBAL HOTKEYS ---\n"
            f"Toggle App Visibility: {h_global}\n"
            f"Pie Menu: {h_pie}\n"
            f"Lock Window: {h_lock}\n"
            f"Always On Top: {h_aot}\n\n"
            f"--- APP HOTKEYS ---\n"
            f"Ctrl+Q : Cycle Snap Corners (move across screens)\n"
            f"Ctrl+N : New Empty Snippet\n"
            f"Ctrl+S : Save Snippet\n"
            f"Ctrl+Z : Undo Text Change\n"
            f"Ctrl+D : Toggle Focus Mode\n"
            f"Ctrl+F : Find Text\n"
            f"Ctrl+H : Replace Text\n"
            f"Ctrl+Shift+S : Export/Save Silo to File\n"
            f"Esc : Hide Window & Auto-save\n"
            f"F1 - F10 : Execute Snippet 1-10\n"
            f"Ctrl+Alt+Shift+Q : Quit Application Completely"
        )
        if hasattr(self, 'btn_hotkeys'): self.btn_hotkeys.setToolTip(shortcuts_info)

    def unregister_all_hotkeys(self):
        hwnd = ctypes.wintypes.HWND(int(self.winId()))
        for hk_id in self.registered_hotkeys: ctypes.windll.user32.UnregisterHotKey(hwnd, hk_id)
        self.registered_hotkeys.clear()

    def register_all_hotkeys(self):
        self.unregister_all_hotkeys()
        self._register_single(self.data.get("global_hotkey", "Alt+X"), 1)
        self._register_single(self.data.get("global_hotkey_alt", "F15"), 101)
        self._register_single(self.data.get("pie_menu_hotkey", "Shift+Alt+X"), 2)
        self._register_single(self.data.get("pie_menu_hotkey_alt", ""), 102)
        self._register_single(self.data.get("lock_window_hotkey", "Ctrl+Shift+L"), 3)
        self._register_single(self.data.get("lock_window_hotkey_alt", ""), 103)
        self._register_single(self.data.get("always_on_top_hotkey", "Ctrl+Shift+E"), 4)
        self._register_single(self.data.get("always_on_top_hotkey_alt", ""), 104)
        self._register_single(self.data.get("toggle_sidebar_hotkey", "Alt+D"), 5)
        self._register_single(self.data.get("toggle_sidebar_hotkey_alt", ""), 105)
            
        for i in range(5):
            self._register_single(self.data.get(f"snippet_{i}_hotkey", f"Ctrl+Shift+Numpad{i+1}"), 10 + i)
            self._register_single(self.data.get(f"snippet_{i}_hotkey_alt", ""), 110 + i)
            self._register_single(self.data.get(f"silo_{i}_hotkey", f"Alt+Shift+Numpad{i+1}"), 20 + i)
            self._register_single(self.data.get(f"silo_{i}_hotkey_alt", ""), 120 + i)
        self._apply_tooltips()
            
    def _register_single(self, hotkey_str, hk_id):
        if not hotkey_str: return
        try:
            modifiers, vk = parse_hotkey(hotkey_str)
        except Exception:
            return
        if vk:
            hwnd = ctypes.wintypes.HWND(int(self.winId()))
            if ctypes.windll.user32.RegisterHotKey(hwnd, hk_id, modifiers, vk): self.registered_hotkeys.append(hk_id)

    def setup_single_instance_server(self):
        import uuid
        import tempfile
        self.ipc_token = str(uuid.uuid4())
        token_file = os.path.join(tempfile.gettempdir(), "fastprompter_ipc.token")
        try:
            with open(token_file, "w") as f:
                f.write(self.ipc_token)
        except Exception as e:
            print("Could not write IPC token", e)

        self.server = QLocalServer()
        self.server.removeServer(SERVER_NAME)
        # print('About to listen!')  # debug
        if not self.server.listen(SERVER_NAME):
            # print('Listen failed:', self.server.serverError())  # debug
            sys.exit(0)
        # print('Listen succeeded!')  # debug
        self.server.newConnection.connect(self.handle_command)

    def handle_command(self):
        sock = self.server.nextPendingConnection()
        if sock.bytesAvailable() > 0 or sock.waitForReadyRead(500):
            data = sock.readAll().data()
            try:
                data_str = data.decode('utf-8')
                if data_str.startswith("TOKEN:"):
                    parts = data_str.split("|", 1)
                    if len(parts) == 2:
                        recv_token = parts[0][6:]
                        cmd = parts[1]
                        if recv_token == getattr(self, "ipc_token", "") and cmd.strip() == "SHOW":
                            self.show_window()
                elif data_str.strip() == "SHOW":
                    self.show_window()
            except Exception:
                pass
        sock.disconnectFromServer()

    def toggle_visibility(self, force_sidebar=False):
        if self.isHidden() or self.isMinimized() or not self.isVisible() or not self.isActiveWindow():
            if force_sidebar and not self.snippets_section.isVisible():
                self.toggle_sidebar_visibility()
            self.show_window()
        else:
            if force_sidebar:
                self.toggle_sidebar_visibility()
            else:
                self.hide_and_save()

    # init_db removed, moved to FastPrompterState

    def get_current_context_key(self):
        if getattr(self, 'editing_snippet', None):
            cat, idx = self.editing_snippet
            return f"snippet:{cat}:{idx}"
        else:
            return f"silo:{self.active_temp_slot}"

    def save_data_to_db(self, force=False):
        current_text = self.text_area.toPlainText() if hasattr(self, "text_area") else self.data.get("last_text", "")
        self._last_saved_text = current_text
        
        if not getattr(self, "_suspend_cache", False) and not getattr(self, "_initializing_ui", False) and not getattr(self, "_suspend_temp_sync", False) and not self.editing_snippet:
            if 0 <= self.active_temp_slot < len(self.data["temp_presets"]): 
                self.data["temp_presets"][self.active_temp_slot] = current_text

        self.data["window_locked"] = "True" if getattr(self, "is_locked", False) else "False"

        ui_settings = {
            'last_tab_idx': str(self.data['last_tab_idx']),
            'active_temp_slot': str(self.active_temp_slot),
            'last_geometry': self.data.get("last_geometry", ""),
            'font_size': str(self.font_spin.value()) if hasattr(self, "font_spin") else str(self.data.get('font_size', 11)),
            'preview_mode': self.preview_combo.currentText() if hasattr(self, "preview_combo") else self.data.get('preview_mode', 'None'),
            'paste_mode': self.btn_format.text() if hasattr(self, "btn_format") else self.data.get('paste_mode', 'Plain'),
            'tray_visible': str(self.cb_tray.isChecked()) if hasattr(self, "cb_tray") else self.data.get('tray_visible', 'True'),
            'close_on_focus_loss': str(self.cb_focus.isChecked()) if hasattr(self, "cb_focus") else self.data.get('close_on_focus_loss', 'True'),
            'ctrl_c_closes': str(self.cb_ctrl_c.isChecked()) if hasattr(self, "cb_ctrl_c") else self.data.get('ctrl_c_closes', 'True'),
            'silo_last_edited': getattr(self, 'silo_last_edited', {})
        }
        
        self.state.save_data_to_db(current_text, ui_settings, force=force)

    def apply_button_size(self, widget, base_w, base_h=None):
        scale = float(self.data.get("button_scale", "1.0"))
        widget._base_size = (base_w, base_h)
        min_sz = max(18, int(base_w * scale))
        if base_h is None:
            if getattr(widget, 'is_squishable', False):
                widget.setMaximumHeight(int(base_w * scale))
                widget.setMinimumHeight(1)
            else:
                widget.setFixedHeight(min_sz)
        else:
            sz = max(18, int(base_h * scale))
            widget.setFixedSize(min_sz, sz)

    def refresh_button_scale(self):
        scale = float(self.data.get("button_scale", "1.0"))
        for widget in self.findChildren(QPushButton):
            if hasattr(widget, '_base_size'):
                base_w, base_h = widget._base_size
                try:
                    min_sz = max(18, int(base_w * scale))
                    if base_h is None:
                        if getattr(widget, 'is_squishable', False):
                            widget.setMaximumHeight(int(base_w * scale))
                            widget.setMinimumHeight(1)
                        else:
                            widget.setFixedHeight(min_sz)
                    else:
                        sz = max(18, int(base_h * scale))
                        widget.setFixedSize(min_sz, sz)
                except Exception:
                    pass

    def cycle_button_scale(self):
        scales = [0.5, 0.75, 1.0, 1.25, 1.5]
        current = float(self.data.get("button_scale", "1.0"))
        # Find closest match
        try:
            idx = min(range(len(scales)), key=lambda i: abs(scales[i] - current))
            next_idx = (idx + 1) % len(scales)
        except ValueError:
            next_idx = 2  # default to 100%
        new_scale = scales[next_idx]
        self.data["button_scale"] = str(new_scale)
        self.save_data_to_db()
        if hasattr(self, 'btn_button_scale'):
            self.btn_button_scale.setText(f"Scale: {int(new_scale * 100)}%")
        self.refresh_button_scale()
        self.apply_font()

    def init_tray(self):
        theme_name = self.data.get("theme", "Default")
        theme = THEMES.get(theme_name, THEMES["Default"])
        tray_color = theme.get("tray_color", "#8b4513")
        icon = create_tray_icon(tray_color)
        
        self.tray_icon = QSystemTrayIcon(icon, self)
        tray_menu = QMenu(self)
        
        show_action = tray_menu.addAction("Show/Hide")
        show_action.triggered.connect(self.toggle_visibility)
        tray_menu.addSeparator()
        quit_action = tray_menu.addAction("Quit")
        quit_action.triggered.connect(self.quit_app)
        
        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.activated.connect(self.on_tray_activated)
        self.tray_icon.setVisible(self.data.get("tray_visible", "True") == "True")
        
        # Set window icon too
        icon_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "_res", "fastprompter_logo2.png")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))
        else:
            self.setWindowIcon(icon)

    def on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.toggle_visibility()

    def init_ui(self):
        flags = Qt.WindowType.Window
        if self.data.get("normal_window", "False") != "True":
            flags |= Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool
        if self.data.get("always_on_top", "True") == "True": flags |= Qt.WindowType.WindowStaysOnTopHint
        self.setWindowFlags(flags)
        self.setWindowTitle("FastPrompter")
        self.setMinimumSize(480, 320)
        
        self.setMouseTracking(True)
        self._initializing_ui, self._suspend_temp_sync = True, True
        
        self._resizers = {
            'left': EdgeResizer(self, 'left'),
            'right': EdgeResizer(self, 'right'),
            'top': EdgeResizer(self, 'top'),
            'bottom': EdgeResizer(self, 'bottom'),
            'topleft': EdgeResizer(self, 'topleft'),
            'topright': EdgeResizer(self, 'topright'),
            'bottomleft': EdgeResizer(self, 'bottomleft'),
            'bottomright': EdgeResizer(self, 'bottomright')
        }

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
        self.apply_button_size(self.btn_sidebar_toggle, 24, 24)
        self.btn_sidebar_toggle.setToolTip("Toggle Sidebar (Alt+D)\nShow or hide the right/left sidebar containing snippets and silos.")
        self.btn_sidebar_toggle.clicked.connect(self.toggle_sidebar_visibility)
        self.header_layout.addWidget(self.btn_sidebar_toggle)

        self.tab_bar = QTabBar()
        self.tab_bar.setExpanding(False)
        self.tab_bar.setUsesScrollButtons(False)
        for cat in self.data['cats_order']: self.tab_bar.addTab(cat)
        self.tab_bar.currentChanged.connect(self.on_tab_changed)

        self.btn_add_tab = QPushButton("Tab +")
        self.apply_button_size(self.btn_add_tab, 24)
        self.btn_add_tab.setToolTip("Add Tab\nCreate a new custom category tab for snippets.")
        self.btn_add_tab.clicked.connect(self.add_category)

        self.btn_del_tab = QPushButton("Tab -")
        self.apply_button_size(self.btn_del_tab, 24)
        self.btn_del_tab.setToolTip("Delete Tab\nRemove the currently active category tab.")
        self.btn_del_tab.clicked.connect(self.del_category)

        self.btn_new = QPushButton("NEW")
        self.btn_new.setToolTip("NEW (Ctrl+N)")
        self.apply_button_size(self.btn_new, 24)
        self.btn_new.setMinimumWidth(80)
        self.btn_new.clicked.connect(self.select_empty_silo)

        self.btn_save = QPushButton("Save")
        self.btn_save.setToolTip("Save (Ctrl+S)")
        self.apply_button_size(self.btn_save, 24)
        self.btn_save.clicked.connect(self.save_snippet)

        self.btn_home = QPushButton("Home")
        self.btn_home.setToolTip("Home (Home)")
        self.apply_button_size(self.btn_home, 24)
        self.btn_home.clicked.connect(self.move_cursor_home)

        self.btn_end = QPushButton("End")
        self.btn_end.setToolTip("Jump to End\nMove cursor to the bottom of the document.")
        self.apply_button_size(self.btn_end, 24)
        self.btn_end.clicked.connect(self.move_cursor_end)

        self.btn_add_line = QPushButton("Line")
        self.btn_add_line.setToolTip("Insert Line\nInsert a horizontal markdown line (---).")
        self.apply_button_size(self.btn_add_line, 24)
        self.btn_add_line.clicked.connect(self.insert_add_line)

        self.btn_bullet_toggle = QPushButton("-→•")
        self.apply_button_size(self.btn_bullet_toggle, 24)
        
        def _bullet_mousePress(event):
            if event.modifiers() & Qt.KeyboardModifier.ControlModifier and event.button() == Qt.MouseButton.LeftButton:
                curr = self.data.get("auto_bullet", "False") == "True"
                self.data["auto_bullet"] = "False" if curr else "True"
                self.mark_dirty()
                self.play_click_sound()
                state_str = "ON" if not curr else "OFF"
                self.btn_bullet_toggle.setToolTip(f"Auto-Bullet: {state_str}")
                event.accept()
            else:
                QPushButton.mousePressEvent(self.btn_bullet_toggle, event)
                
        self.btn_bullet_toggle.mousePressEvent = _bullet_mousePress
        self.btn_bullet_toggle.setToolTip("Auto-Bullet: " + ("ON" if self.data.get("auto_bullet", "False") == "True" else "OFF"))
        
        self.btn_bullet_toggle.clicked.connect(self.toggle_bullet_conversion)

        self.btn_bold = QPushButton("B")
        self.btn_bold.setToolTip("Bold (Ctrl+B)\nMake selected text bold.")
        self.apply_button_size(self.btn_bold, 24, 24)
        self.btn_bold.setStyleSheet("font-weight: bold;")
        self.btn_bold.clicked.connect(lambda: self.apply_format('bold'))

        self.btn_italic = QPushButton("I")
        self.btn_italic.setToolTip("Italic (Ctrl+I)\nMake selected text italic.")
        self.apply_button_size(self.btn_italic, 24, 24)
        self.btn_italic.setStyleSheet("font-style: italic;")
        self.btn_italic.clicked.connect(lambda: self.apply_format('italic'))

        self.btn_under = QPushButton("U")
        self.btn_under.setToolTip("Underline (Ctrl+U)\nMake selected text underlined.")
        self.apply_button_size(self.btn_under, 24, 24)
        self.btn_under.setStyleSheet("text-decoration: underline;")
        self.btn_under.clicked.connect(lambda: self.apply_format('underline'))

        self.btn_strike = QPushButton("S")
        self.btn_strike.setToolTip("Strikethrough (Ctrl+T)\nCross out selected text.")
        self.apply_button_size(self.btn_strike, 24, 24)
        self.btn_strike.setStyleSheet("text-decoration: line-through;")
        self.btn_strike.clicked.connect(lambda: self.apply_format('strike'))

        self.btn_clear_fmt = QPushButton("Clear Fmt")
        self.btn_clear_fmt.setToolTip("Clear Format\nRemove all explicit font styling from text.")
        self.apply_button_size(self.btn_clear_fmt, 24)
        self.btn_clear_fmt.clicked.connect(self.clear_formatting)

        self.btn_clean_space = QPushButton("Clean \\n")
        self.apply_button_size(self.btn_clean_space, 24)
        self.btn_clean_space.setToolTip("Clean excessive empty lines (keeps lines near '---')")
        self.btn_clean_space.clicked.connect(self.clean_excessive_newlines)

        self.btn_settings_toggle = QPushButton("⚙")
        self.apply_button_size(self.btn_settings_toggle, 24, 24)
        self.btn_settings_toggle.setToolTip("Settings\nConfigure hotkeys, theme, fonts, and UI scaling.")
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

        self.btn_copy = QPushButton("Copy")
        self.btn_copy.setToolTip("Copy all text (Ctrl+C)\nRight-click: Copy + Close FastPrompter")
        self.apply_button_size(self.btn_copy, 24)
        self.btn_copy.clicked.connect(self.copy_context_to_clipboard)
        self.btn_copy.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.btn_copy.customContextMenuRequested.connect(self.copy_context_and_close)

        self.btn_clear = QPushButton("Clear")
        self.btn_clear.setToolTip("Clear (Ctrl+Shift+C)")
        self.apply_button_size(self.btn_clear, 24)
        self.btn_clear.clicked.connect(self.clear_text)

        self.btn_format = QPushButton("Plain")
        self.btn_format.setToolTip("View Mode Toggle\nSwitch between Plain Text (editing) and Formatted Preview (Markdown rendering).")
        self.btn_format.setCheckable(True)
        saved_mode = self.data.get("paste_mode", "Plain")
        self.btn_format.setChecked(saved_mode == "Plain")
        self.btn_format.setText(saved_mode)
        self.apply_button_size(self.btn_format, 24)
        self.btn_format.toggled.connect(self.toggle_paste_mode)

        # Navigation
        self.header_layout.addWidget(self.tab_bar)
        self.header_layout.addWidget(self.btn_add_tab)
        self.header_layout.addWidget(self.btn_del_tab)
        self.header_layout.addWidget(self.btn_new)
        self.header_layout.addWidget(self.btn_save)

        # Formatting and editing
        self.header_layout.addStretch(1)
        self.header_layout.addWidget(self.btn_bold)
        self.header_layout.addWidget(self.btn_italic)
        self.header_layout.addWidget(self.btn_under)
        self.header_layout.addWidget(self.btn_strike)
        self.header_layout.addWidget(self.btn_clear_fmt)
        self.header_layout.addWidget(self.btn_add_line)
        self.header_layout.addWidget(self.btn_bullet_toggle)
        self.header_layout.addWidget(self.btn_clean_space)
        self.header_layout.addWidget(self.btn_copy)
        self.header_layout.addWidget(self.btn_clear)
        self.header_layout.addWidget(self.btn_format)

        # Cursor nav and settings
        self.header_layout.addStretch(1)
        self.header_layout.addWidget(self.btn_home)
        self.header_layout.addWidget(self.btn_end)
        self.header_layout.addWidget(self.btn_settings_toggle)
        self.header_layout.addWidget(self.btn_help)
        self.main_layout.addWidget(self.header_widget)

        self.mini_settings_frame = QFrame(self)
        self.mini_settings_frame.setVisible(False)

        self.font_combo = QComboBox()
        self.font_combo.addItems(["Verdana", "Tahoma", "Consolas", "Calibri", "Times New Roman", "Arial", "Segoe UI", "Courier New"])
        saved_font = self.data.get("font_family", "Verdana")
        idx = self.font_combo.findText(saved_font)
        if idx >= 0: self.font_combo.setCurrentIndex(idx)
        self.font_combo.currentTextChanged.connect(self.change_font_family)
        
        self.font_spin = QSpinBox()
        self.font_spin.setRange(6, 48)
        self.font_spin.setValue(int(self.data.get("font_size", "11")))
        self.font_spin.valueChanged.connect(self.change_font_size)
        
        self.preview_combo = QComboBox()
        self.preview_combo.addItems(["Source View", "Live Preview", "Reading"])
        self.preview_combo.setToolTip(
            "Source View: Plain text editor\n"
            "Live Preview: Editor with live markdown highlights (default)\n"
            "Reading: Read-only rendered markdown view"
        )
        # Map old saved values to new
        _view_map = {"None": "Source View", "Raw": "Source View", "Markdown": "Reading"}
        saved_preview = self.data.get("preview_mode", "Live Preview")
        saved_preview = _view_map.get(saved_preview, saved_preview)  # migrate old values
        idx = self.preview_combo.findText(saved_preview)
        if idx < 0: idx = 1  # default to Live Preview
        self.preview_combo.setCurrentIndex(idx)
        self.preview_combo.currentIndexChanged.connect(self.change_preview_mode)
        
        self.cb_theme = QComboBox()
        self.cb_theme.addItems(["Default", "Golden Vintage", "Golden Default", "Vintage Dark", "Vintage Classic", "Dark 2 (OLED)", "Custom"])
        saved_theme = self.data.get("theme", "Default")
        idx = self.cb_theme.findText(saved_theme)
        if idx >= 0: self.cb_theme.setCurrentIndex(idx)
        self.cb_theme.currentTextChanged.connect(self.change_theme)
        
        self.preset_combo = QComboBox()
        self.preset_combo.addItems([f"Preset {i}" for i in range(1, 6)])
        self.preset_combo.setCurrentIndex(self.state.profile_id - 1)
        self.preset_combo.currentIndexChanged.connect(self.change_profile)

        def make_action_checkbox(text, callback):
            cb = QCheckBox(text)
            def on_toggled(checked):
                if checked:
                    self.play_tick_sound()
                    callback()
                    cb.setChecked(False)
            cb.toggled.connect(on_toggled)
            return cb

        self.btn_hotkeys = make_action_checkbox("Keys", self.open_hotkey_settings)
        self.btn_hotkeys.setToolTip("Configure Global Hotkeys (Settings Cog)")
        self.btn_colors = make_action_checkbox("RGB", self.open_color_settings)
        self.btn_colors.setToolTip("Custom Theme Colors (Color Palette)")
        self.btn_backup = make_action_checkbox("BkUp", self.backup_db)
        self.btn_restore = make_action_checkbox("Rstr", self.restore_db)
        
        current_b_scale = int(float(self.data.get("button_scale", "1.0")) * 100)
        self.btn_button_scale = make_action_checkbox(f"Btn Scale: {current_b_scale}%", self.cycle_button_scale)

        # Load custom font button
        self.btn_load_font = QPushButton("+ Font")
        self.btn_load_font.setFixedWidth(52)
        self.btn_load_font.setToolTip("Load a custom .ttf/.otf font file")
        self.btn_load_font.clicked.connect(self.load_custom_font)
        
        self.btn_clear_fonts = QPushButton("× Fonts")
        self.btn_clear_fonts.setFixedWidth(54)
        self.btn_clear_fonts.setToolTip("Clear all custom fonts from combo (reset to defaults)")
        self.btn_clear_fonts.clicked.connect(self.clear_custom_fonts)
        
        # Volume control
        self.spin_volume = QSpinBox()
        self.spin_volume.setRange(1, 10)
        self.spin_volume.setValue(int(self.data.get("sound_volume", "5")))
        self.spin_volume.setFixedWidth(42)
        self.spin_volume.setToolTip("Click sound volume (1-10)")
        self.spin_volume.valueChanged.connect(lambda v: (self.data.update({"sound_volume": str(v)}), self.mark_dirty()))
        
        # Switch to QHBoxLayout for mini_layout
        new_mini_layout = QHBoxLayout()
        new_mini_layout.setContentsMargins(0,0,0,0)
        new_mini_layout.addWidget(QLabel("Preset:"))
        new_mini_layout.addWidget(self.preset_combo)
        new_mini_layout.addWidget(QLabel("Font:"))
        new_mini_layout.addWidget(self.font_combo)
        new_mini_layout.addWidget(self.font_spin)
        new_mini_layout.addWidget(self.btn_load_font)
        new_mini_layout.addWidget(self.btn_clear_fonts)
        new_mini_layout.addWidget(QLabel("Theme:"))
        new_mini_layout.addWidget(self.cb_theme)
        new_mini_layout.addWidget(self.btn_colors)
        new_mini_layout.addWidget(QLabel("View:"))
        new_mini_layout.addWidget(self.preview_combo)
        new_mini_layout.addWidget(QLabel("Btn:"))
        new_mini_layout.addWidget(self.btn_button_scale)
        new_mini_layout.addWidget(QLabel("Vol:"))
        new_mini_layout.addWidget(self.spin_volume)
        new_mini_layout.addWidget(self.btn_hotkeys)
        new_mini_layout.addWidget(self.btn_backup)
        new_mini_layout.addWidget(self.btn_restore)
        
        def create_footer_cb(text, tooltip, checked, callback):
            cb = QCheckBox(text)
            cb.setToolTip(tooltip)
            cb.setChecked(checked)
            if callback:
                cb.toggled.connect(lambda _: self.play_tick_sound())
                cb.toggled.connect(callback)
            cb.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            return cb

        footer_layout = QHBoxLayout()
        footer_layout.setContentsMargins(2, 0, 2, 0)
        footer_layout.setSpacing(4)
        
        self.cb_tray = create_footer_cb("[TRAY]", "Tray Icon", self.data.get("tray_visible", "True") == "True", self.on_tray_toggled)
        footer_layout.addWidget(self.cb_tray)
        self.cb_focus = create_footer_cb("[FOCS]", "Close when clicked outside", self.data.get("close_on_focus_loss", "True") == "True", self.mark_dirty)
        footer_layout.addWidget(self.cb_focus)
        self.cb_ctrl_c = create_footer_cb("[C+CC]", "Ctrl+C Closes UI", self.data.get("ctrl_c_closes", "True") == "True", self.mark_dirty)
        footer_layout.addWidget(self.cb_ctrl_c)
        self.cb_top = create_footer_cb("[AOT]", "Always on top", self.data.get("always_on_top", "True") == "True", self.toggle_aot)
        footer_layout.addWidget(self.cb_top)
        self.cb_lock_window = create_footer_cb("[LCK]", "Lock Window", self.data.get("window_locked", "False") == "True", self.set_lock_state)
        footer_layout.addWidget(self.cb_lock_window)
        self.cb_normal_window = create_footer_cb("[NORM]", "Act like normal window", self.data.get("normal_window", "False") == "True", self.apply_window_flags)
        footer_layout.addWidget(self.cb_normal_window)
        self.cb_lock_cursor = create_footer_cb("[CURS]", "Lock to Cursor", self.data.get("lock_to_cursor", "False") == "True", self.on_lock_cursor_toggled)
        footer_layout.addWidget(self.cb_lock_cursor)
        self.cb_hide_shortkeys = create_footer_cb("[SHORT]", "Hide shortkeys", self.data.get("hide_shortkeys", "False") == "True", self.on_hide_shortkeys_toggled)
        footer_layout.addWidget(self.cb_hide_shortkeys)
        self.cb_sidebar = create_footer_cb("[RSID]", "Sidebar on Right", self.data.get("sidebar_right", "False") == "True", self.toggle_sidebar_position)
        footer_layout.addWidget(self.cb_sidebar)
        self.cb_silo_home = create_footer_cb("[HOME]", "Silos open at start", self.data.get("silo_home", "False") == "True", self.on_silo_home_toggled)
        footer_layout.addWidget(self.cb_silo_home)
        self.cb_wrap = create_footer_cb("[WRP]", "Word Wrap", self.data.get("word_wrap", "True") == "True", self.on_wrap_toggled)
        footer_layout.addWidget(self.cb_wrap)
        self.cb_line_numbers = create_footer_cb("[L#]", "Show Line Numbers", self.data.get("show_line_numbers", "False") == "True", self.on_line_numbers_toggled)
        footer_layout.addWidget(self.cb_line_numbers)
        self.cb_sound = create_footer_cb("[SND]", "Interface Sounds", self.data.get("sound_ui", "False") == "True", self.on_sound_toggled)
        footer_layout.addWidget(self.cb_sound)
        self.cb_typewriter = create_footer_cb("[TYP]", "Typing Effect", self.data.get("sound_typewriter", "False") == "True", self.on_typewriter_toggled)
        footer_layout.addWidget(self.cb_typewriter)
        footer_layout.addStretch(1)

        v_layout = QVBoxLayout(self.mini_settings_frame)
        v_layout.setContentsMargins(0,0,0,0)
        v_layout.setSpacing(4)
        v_layout.addLayout(new_mini_layout)
        v_layout.addLayout(footer_layout)

        self.mini_settings_frame.setVisible(self.data.get("hide_extra", "False") != "True")
        
        self.main_layout.addWidget(self.mini_settings_frame)
        # self.main_layout.addWidget(self.left_panel)
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setChildrenCollapsible(True)
        self.main_layout.addWidget(self.splitter)
        self.splitter.setOpaqueResize(True)
        self.splitter.setHandleWidth(1)

        self.left_panel = QWidget()
        self.left_panel_layout = QVBoxLayout(self.left_panel)
        self.left_panel_layout.setContentsMargins(0, 0, 0, 0)
        self.left_panel_layout.setSpacing(0)

        self.snippets_section = QWidget()
        self.snippets_section_layout = QVBoxLayout(self.snippets_section)
        self.snippets_section_layout.setContentsMargins(0,0,0,0)
        self.snippets_section_layout.setSpacing(1)

        snip_header = QHBoxLayout()
        snip_header.setContentsMargins(0,0,0,0)
        self.snip_label = QLabel("Snippets")
        snip_header.addWidget(self.snip_label)
        snip_header.addStretch()
        
        self.btn_toggle_search = QPushButton("⌕")
        self.apply_button_size(self.btn_toggle_search, 20, 20)
        self.btn_toggle_search.setCheckable(True)
        snip_header.addWidget(self.btn_toggle_search)



        self.btn_arc_snip = QPushButton("📥")
        self.apply_button_size(self.btn_arc_snip, 20, 20)
        self.btn_arc_snip.setToolTip("Archive Active Snippet or Silo")
        self.btn_arc_snip.clicked.connect(self.archive_active_item)
        snip_header.addWidget(self.btn_arc_snip)

        self.btn_toggle_archive = QPushButton("📦")
        self.apply_button_size(self.btn_toggle_archive, 20, 20)
        self.btn_toggle_archive.setToolTip("Toggle Archives")
        self.btn_toggle_archive.setCheckable(True)
        snip_header.addWidget(self.btn_toggle_archive)

        self.btn_add_snip = QPushButton("+")
        self.apply_button_size(self.btn_add_snip, 20, 20)
        self.btn_add_snip.clicked.connect(self.save_snippet)
        snip_header.addWidget(self.btn_add_snip)
        
        self.btn_del_snip = QPushButton("-")
        self.apply_button_size(self.btn_del_snip, 20, 20)
        self.btn_del_snip.clicked.connect(self.del_last_snippet)
        snip_header.addWidget(self.btn_del_snip)
        
        self.snippets_section_layout.addLayout(snip_header)

        self.search_bar = QLineEdit()
        self.search_bar.setToolTip("Search snippets")
        self.search_bar.setPlaceholderText("Search...")
        self.search_bar.setFixedHeight(20)
        
        saved_search_visible = self.data.get("search_visible", "False") == "True"
        self.btn_toggle_search.setChecked(saved_search_visible)
        self.search_bar.setVisible(saved_search_visible)
        self.btn_toggle_search.toggled.connect(self.on_search_toggle)
        
        self._search_debounce_timer = QTimer(self)
        self._search_debounce_timer.setSingleShot(True)
        self._search_debounce_timer.setInterval(150)
        self._search_debounce_timer.timeout.connect(self.refresh_snippets_panel)
        self.search_bar.textChanged.connect(self._search_debounce_timer.start)
        self.snippets_section_layout.addWidget(self.search_bar)

        self.btn_page_up = QPushButton("▲")
        self.btn_page_up.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.btn_page_up.setMinimumWidth(10)
        self.apply_button_size(self.btn_page_up, 16)
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
        self.btn_page_down.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.btn_page_down.setMinimumWidth(10)
        self.apply_button_size(self.btn_page_down, 16)
        self.btn_page_down.clicked.connect(lambda: self.change_page(1))
        self.snippets_section_layout.addWidget(self.btn_page_down)
        self.left_panel_layout.addWidget(self.snippets_section, 0)

        self.archive_section = QWidget()
        self.archive_section.setObjectName("ArchiveSection")
        self.archive_section_layout = QVBoxLayout(self.archive_section)
        self.archive_section_layout.setContentsMargins(0,0,0,0)
        self.archive_section_layout.setSpacing(1)

        arc_header = QHBoxLayout()
        arc_header.setContentsMargins(0,0,0,0)
        self.arc_label = QLabel("Archive")
        arc_header.addWidget(self.arc_label)
        arc_header.addStretch()
        self.archive_section_layout.addLayout(arc_header)

        self.btn_arc_page_up = QPushButton("▲")
        self.apply_button_size(self.btn_arc_page_up, 16)
        self.btn_arc_page_up.clicked.connect(lambda: self.change_arc_page(-1))
        self.archive_section_layout.addWidget(self.btn_arc_page_up)

        self.archive_widget = SiloDropWidget(self, is_archive=True)
        self.archive_buttons = []
        for _ in range(50):
            btn = DraggableSiloButton(self, is_archive=True)
            btn.is_squishable = True
            self.apply_button_size(btn, 24)
            btn.hide()
            self.archive_widget.layout.addWidget(btn)
            self.archive_buttons.append(btn)
        self.archive_section_layout.addWidget(self.archive_widget)

        self.btn_arc_page_down = QPushButton("▼")
        self.apply_button_size(self.btn_arc_page_down, 16)
        self.btn_arc_page_down.clicked.connect(lambda: self.change_arc_page(1))
        self.archive_section_layout.addWidget(self.btn_arc_page_down)
        
        saved_arc_visible = self.data.get("archive_visible", "False") == "True"
        self.btn_toggle_archive.setChecked(saved_arc_visible)
        self.archive_section.setVisible(saved_arc_visible)
        self.btn_toggle_archive.toggled.connect(self.on_archive_toggle)

        self.silos_section = QWidget()
        self.silos_section_layout = QVBoxLayout(self.silos_section)
        self.silos_section_layout.setContentsMargins(0,0,0,0)
        self.silos_section_layout.setSpacing(1)

        self.btn_silo_up = QPushButton("▲")
        self.btn_silo_up.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.btn_silo_up.setMinimumWidth(10)
        self.apply_button_size(self.btn_silo_up, 16)
        self.btn_silo_up.clicked.connect(lambda: self.change_silo_page(-1))
        self.silos_section_layout.addWidget(self.btn_silo_up)

        self.silos_widget = SiloDropWidget(self)
        self.silo_buttons = []
        # Create enough silo buttons - _update_visible_silo_count will adjust
        for _ in range(50):
            btn = DraggableSiloButton(self)
            btn.is_squishable = True
            self.apply_button_size(btn, 24)
            btn.hide()
            self.silos_widget.layout.addWidget(btn)
            self.silo_buttons.append(btn)
        self.silos_section_layout.addWidget(self.silos_widget)

        self.btn_silo_down = QPushButton("▼")
        self.btn_silo_down.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.btn_silo_down.setMinimumWidth(10)
        self.apply_button_size(self.btn_silo_down, 16)
        self.btn_silo_down.clicked.connect(lambda: self.change_silo_page(1))
        self.silos_section_layout.addWidget(self.btn_silo_down)
        self.left_panel_layout.addWidget(self.silos_section, 1)

        self.archive_section.setParent(self.left_panel)
        self.archive_section.raise_()

        self.silos_section.setVisible(False)
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
        self.apply_button_size(self.btn_find_prev, 24, 24)
        search_layout.addWidget(self.btn_find_prev)
        
        self.btn_find_next = QPushButton("►")
        self.btn_find_next.clicked.connect(self.find_next)
        self.apply_button_size(self.btn_find_next, 24, 24)
        search_layout.addWidget(self.btn_find_next)
        
        self.replace_input = QLineEdit()
        self.replace_input.setPlaceholderText("Replace with...")
        search_layout.addWidget(self.replace_input)
        
        self.btn_replace = QPushButton("Replace")
        self.btn_replace.clicked.connect(self.replace_text)
        self.apply_button_size(self.btn_replace, 24)
        search_layout.addWidget(self.btn_replace)
        
        self.btn_replace_all = QPushButton("Replace All")
        self.btn_replace_all.clicked.connect(self.replace_all)
        self.apply_button_size(self.btn_replace_all, 24)
        search_layout.addWidget(self.btn_replace_all)
        
        self.btn_close_search = QPushButton("✕")
        self.apply_button_size(self.btn_close_search, 24, 24)
        self.btn_close_search.clicked.connect(self.close_search)
        search_layout.addWidget(self.btn_close_search)
        
        self.center_layout.addWidget(self.search_frame)

        self.text_area = VaultTextEdit(self)

        self.text_area.installEventFilter(self)
        self.setMouseTracking(True) # Required for catching mouse hover for resizing cursor
        # self.highlighter = MarkdownHighlighter(self.text_area.document(), base_font_size=11)
        self.apply_wrap_mode()
        self.text_area.setPlaceholderText("Vault ready. Execute.")
        self.text_area.setWordWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere) # Socratic: Smart visual wrap without corrupting text
        self.text_area.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        # Use a debounce timer to avoid text input stutter from cache sync
        self._cache_timer = QTimer(self)
        self._cache_timer.setSingleShot(True)
        self._cache_timer.setInterval(800)  # 800ms debounce - optimized for large files
        self._cache_timer.timeout.connect(self.cache_current_text)
        self.text_area.textChanged.connect(self._cache_timer.start)

        try: font_size = int(self.data.get("font_size", 11))
        except Exception: font_size = 11
        font = QFont(self.data.get("font_family", "Verdana"), font_size)
        font.setStyleStrategy(QFont.StyleStrategy.NoAntialias | QFont.StyleStrategy.NoSubpixelAntialias)
        self.text_area.setFont(font)
        
        self.silo_docs = []
        for i, text in enumerate(self.data.get("temp_presets", [])):
            doc = QTextDocument()
            doc.setDefaultFont(font)
            self._set_plain_text_clean(doc, text)
            self.silo_docs.append(doc)
            
        self.archive_docs = []
        for text in self.data.get("archive_temp_presets", []):
            doc = QTextDocument()
            doc.setDefaultFont(font)
            self._set_plain_text_clean(doc, text)
            self.archive_docs.append(doc)
            
        self.snippet_docs = {}

        self.center_layout.addWidget(self.text_area, 1)

        self.preview_area = QTextEdit(readOnly=True)
        self.preview_area.setVisible(False)
        self.preview_area.setFont(font)
        # No fixed height — in Reading mode it should fill the whole center
        self.center_layout.addWidget(self.preview_area, 1)
        

        self.main_layout.addWidget(self.splitter, 1)

        # Use custom EdgeResizer instead of QSizeGrip
        
        # Edge resizers

        self.apply_sidebar_position()

        safe_idx = max(0, min(self.data.get("last_tab_idx", 0), self.tab_bar.count()-1))
        if self.tab_bar.count() > 0: self.tab_bar.setCurrentIndex(safe_idx)

        self._trim_archive()
        self.refresh_snippets_panel()
        self.refresh_temp_presets()
        QTimer.singleShot(0, self._deferred_silo_refresh)
        self.change_preview_mode(self.preview_combo.currentIndex())
        self.on_tray_toggled(self.cb_tray.isChecked())
        self.set_lock_state(self.cb_lock_window.isChecked())
        self.apply_scaled_ui()
        self.apply_font()
        
        self.splitter.splitterMoved.connect(self.on_splitter_moved)
        
        self._silo_resize_debounce_timer = QTimer(self)
        self._silo_resize_debounce_timer.setSingleShot(True)
        self._silo_resize_debounce_timer.setInterval(100)
        self._silo_resize_debounce_timer.timeout.connect(self.refresh_temp_presets)
        
        self.silos_widget.installEventFilter(self)
        self.left_panel.installEventFilter(self)

    def change_profile(self, idx):
        self.commit_current_text()
        self.save_data_to_db(force=True)
        self.data_undo_stack = []
        self.data_redo_stack = []
        self.state.switch_profile(idx + 1)
        self.data = self.state.data
        
        # Rebuild document caches for the new profile
        from PyQt6.QtGui import QTextDocument, QFont
        font = self.text_area.font()
        self.silo_docs = []
        for text in self.data.get("temp_presets", []):
            doc = QTextDocument()
            doc.setDefaultFont(font)
            self._set_plain_text_clean(doc, text)
            self.silo_docs.append(doc)
        self.archive_docs = []
        for text in self.data.get("archive_temp_presets", []):
            doc = QTextDocument()
            doc.setDefaultFont(font)
            self._set_plain_text_clean(doc, text)
            self.archive_docs.append(doc)
        self.snippet_docs.clear()
        
        # Apply ui changes
        self.apply_theme()
        
        # Re-populate UI
        self.silo_page = 0
        self.arc_silo_page = 0
        self.btn_toggle_archive.setChecked(False)
        self.refresh_temp_presets()
        self.build_categories()
        
        # Switch to first silo
        self.active_temp_slot = max(0, min(int(self.data.get("active_temp_slot", 0)), len(self.data["temp_presets"]) - 1))
        self._switch_to_slot(self.active_temp_slot, initial=True)
        
        # Switch to Text category
        text_idx = 0
        for i, c in enumerate(self.data["cats_order"]):
            if c == "Text":
                text_idx = i
                break
        self.tab_bar.setCurrentIndex(text_idx)
        self.on_tab_changed(text_idx)

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

    def toggle_header_line(self):
        """Ctrl+E: Toggle current line as header by adding/removing `# ` prefix in plain text."""
        cursor = self.text_area.textCursor()
        cursor.beginEditBlock()
        
        # Save original position relative to block
        pos_in_block = cursor.positionInBlock()
        
        # Select the current block (line)
        block = cursor.block()
        line_text = block.text()
        
        cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
        cursor.movePosition(QTextCursor.MoveOperation.EndOfBlock, QTextCursor.MoveMode.KeepAnchor)
        
        if line_text.startswith("# "):
            # Remove header prefix
            new_text = line_text[2:]
            offset = -2
        else:
            # Add header prefix
            new_text = "# " + line_text
            offset = 2
            
        cursor.insertText(new_text)
        cursor.endEditBlock()
        
        # Restore cursor position, adjusting for added/removed prefix
        new_pos_in_block = max(0, pos_in_block + offset)
        new_cursor = self.text_area.textCursor()
        new_cursor.setPosition(block.position() + new_pos_in_block)
        self.text_area.setTextCursor(new_cursor)
        
        self.text_area.setFocus()
        self.mark_dirty()

    def apply_bold_smart(self):
        """Ctrl+B: Bold selected text. If nothing selected, bold/unbold entire current line."""
        cursor = self.text_area.textCursor()
        if not cursor.hasSelection():
            # Select whole current line
            cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
            cursor.movePosition(QTextCursor.MoveOperation.EndOfBlock, QTextCursor.MoveMode.KeepAnchor)
            self.text_area.setTextCursor(cursor)
        self.apply_format('bold')

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
        self.play_click_sound()
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

    def swap_temp_slots(self, idx1, idx2, is_archive=False):
        if idx1 == idx2: return
        if not getattr(self, 'editing_snippet', None):
            target = self.data["archive_temp_presets" if getattr(self, 'active_is_archive', False) else "temp_presets"]
            slot = getattr(self, 'active_temp_slot', 0)
            if 0 <= slot < len(target):
                target[slot] = self.text_area.toPlainText()
        self.add_data_undo_state("Swap temp slots")
        temps = self.data["archive_temp_presets"] if is_archive else self.data["temp_presets"]
        docs = self.archive_docs if is_archive else self.silo_docs
        if not (0 <= idx1 < len(temps) and 0 <= idx2 < len(temps)): return
        
        from PyQt6.QtGui import QTextDocument
        while len(docs) <= max(idx1, idx2):
            d = QTextDocument()
            d.setDefaultFont(self.text_area.font())
            if len(docs) < len(temps): d.setPlainText(temps[len(docs)])
            docs.append(d)
            
        self._suspend_cache = True
        temps[idx1], temps[idx2] = temps[idx2], temps[idx1]
        docs[idx1], docs[idx2] = docs[idx2], docs[idx1]
        
        if getattr(self, "active_is_archive", False) == is_archive:
            if getattr(self, "active_temp_slot", -1) == idx1:
                self.active_temp_slot = idx2
            elif getattr(self, "active_temp_slot", -1) == idx2:
                self.active_temp_slot = idx1
        self._suspend_cache = False
        self.mark_dirty()
        self.refresh_temp_presets()
        if is_archive: self.refresh_archive_panel()

    def toggle_mini_settings(self):
        is_hidden = self.mini_settings_frame.isVisible()
        self.mini_settings_frame.setVisible(not is_hidden)
        self.data["hide_extra"] = "True" if is_hidden else "False"
        self.mark_dirty()

    def on_tray_toggled(self, checked):
        if hasattr(self, 'tray_icon'): self.tray_icon.setVisible(checked)
        self.data["tray_visible"] = str(checked)
        self.mark_dirty()

    def apply_window_flags(self, _=None):
        self.data["always_on_top"] = "True" if self.cb_top.isChecked() else "False"
        self.data["normal_window"] = "True" if self.cb_normal_window.isChecked() else "False"
        flags = Qt.WindowType.Window
        if not self.cb_normal_window.isChecked():
            flags |= Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool
        # AOT is handled via SetWindowPos now to avoid flickering
        self.unregister_all_hotkeys()
        was_visible = self.isVisible()
        self.setWindowFlags(flags)
        if was_visible:
            self.show()
        self.register_all_hotkeys()
        self.mark_dirty()

    def toggle_aot(self, checked):
        self.data["always_on_top"] = "True" if checked else "False"
        self.mark_dirty()
        try:
            import ctypes
            hwnd = int(self.winId())
            HWND_TOPMOST = -1
            HWND_NOTOPMOST = -2
            SWP_NOMOVE = 0x0002
            SWP_NOSIZE = 0x0001
            ctypes.windll.user32.SetWindowPos(hwnd, HWND_TOPMOST if checked else HWND_NOTOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE)
        except Exception:
            pass
        # Only poll when AOT is on
        if hasattr(self, 'topmost_timer'):
            if checked:
                self.topmost_timer.start(5000)
            else:
                self.topmost_timer.stop()

    def on_hide_shortkeys_toggled(self, checked):
        self.data["hide_shortkeys"] = "True" if checked else "False"
        self.mark_dirty()
        self.refresh_snippets_panel()

    def move_preset_to_index(self, category, from_idx, to_idx):
        if from_idx == to_idx: return
        self.add_data_undo_state("Move preset")
        slots = self.data["categories"][category]
        item = slots.pop(from_idx)
        slots.insert(to_idx, item)
        self.mark_dirty()
        self.refresh_snippets_panel()

    def move_preset_cross_category(self, from_cat, from_idx, to_cat, to_idx):
        self.add_data_undo_state("Move preset cross category")
        
        if from_cat == "silo":
            if not (0 <= from_idx < len(self.data["temp_presets"])): return
            text = self.data["temp_presets"].pop(from_idx)
            if from_idx < len(self.silo_docs): self.silo_docs.pop(from_idx)
            item = {"name": text[:20], "text": text}
            if not getattr(self, 'active_is_archive', False):
                if from_idx < self.active_temp_slot:
                    self.active_temp_slot -= 1
                elif from_idx == self.active_temp_slot:
                    self.active_temp_slot = max(0, self.active_temp_slot - 1) if self.data["temp_presets"] else 0
        elif from_cat == "arcsilo":
            if not (0 <= from_idx < len(self.data.get("archive_temp_presets", []))): return
            text = self.data["archive_temp_presets"].pop(from_idx)
            if from_idx < len(self.archive_docs): self.archive_docs.pop(from_idx)
            item = {"name": text[:20], "text": text}
            if getattr(self, 'active_is_archive', False):
                if from_idx < self.active_temp_slot:
                    self.active_temp_slot -= 1
                elif from_idx == self.active_temp_slot:
                    self.active_temp_slot = max(0, self.active_temp_slot - 1) if self.data["archive_temp_presets"] else 0
        else:
            item = self.data["categories"][from_cat].pop(from_idx)
            self.data["categories"][from_cat].append(None)
            
        if to_cat == "silo":
            self.data["temp_presets"].insert(to_idx, item["text"] if item else "")
            doc = QTextDocument()
            doc.setDefaultFont(self.text_area.font())
            doc.setPlainText(item["text"] if item else "")
            self.silo_docs.insert(to_idx, doc)
        elif to_cat == "arcsilo":
            if "archive_temp_presets" not in self.data: self.data["archive_temp_presets"] = []
            self.data["archive_temp_presets"].insert(to_idx, item["text"] if item else "")
            doc = QTextDocument()
            doc.setDefaultFont(self.text_area.font())
            doc.setPlainText(item["text"] if item else "")
            self.archive_docs.insert(to_idx, doc)
        else:
            slots = self.data["categories"][to_cat]
            slots.insert(to_idx, item)
            # Only pop if the last item is None (empty). Otherwise, let the array grow so we don't lose data!
            if slots[-1] is None:
                slots.pop()
        
        self._trim_archive()
        self.mark_dirty()
        self.refresh_snippets_panel()
        self.refresh_temp_presets()
        self.refresh_archive_panel()

    def swap_cross_temp_slots(self, source_idx, target_idx, source_is_archive, target_is_archive):
        if not getattr(self, 'editing_snippet', None):
            target = self.data["archive_temp_presets" if getattr(self, 'active_is_archive', False) else "temp_presets"]
            slot = getattr(self, 'active_temp_slot', 0)
            if 0 <= slot < len(target):
                target[slot] = self.text_area.toPlainText()
        self.add_data_undo_state("Swap cross temp slots")
        source_arr = self.data["archive_temp_presets"] if source_is_archive else self.data["temp_presets"]
        target_arr = self.data["archive_temp_presets"] if target_is_archive else self.data["temp_presets"]
        source_docs = self.archive_docs if source_is_archive else self.silo_docs
        target_docs = self.archive_docs if target_is_archive else self.silo_docs
        
        # We need to make sure arrays are long enough
        while len(source_arr) <= source_idx: source_arr.append("")
        while len(target_arr) <= target_idx: target_arr.append("")
        
        from PyQt6.QtGui import QTextDocument
        while len(source_docs) <= source_idx: 
            d = QTextDocument()
            d.setDefaultFont(self.text_area.font())
            source_docs.append(d)
        while len(target_docs) <= target_idx:
            d = QTextDocument()
            d.setDefaultFont(self.text_area.font())
            target_docs.append(d)
            
        source_arr[source_idx], target_arr[target_idx] = target_arr[target_idx], source_arr[source_idx]
        source_docs[source_idx], target_docs[target_idx] = target_docs[target_idx], source_docs[source_idx]
        
        self._trim_archive()
        self.mark_dirty()
        self.refresh_temp_presets()
        self.refresh_archive_panel()

    def on_lock_cursor_toggled(self, checked):
        self.data["lock_to_cursor"] = "True" if checked else "False"
        self.mark_dirty()
        self.refresh_snippets_panel()

    def on_silo_home_toggled(self, checked):
        self.data["silo_home"] = "True" if checked else "False"
        self.mark_dirty()

    def on_wrap_toggled(self, checked):
        self.data["word_wrap"] = "True" if checked else "False"
        self.apply_wrap_mode()
        self.mark_dirty()

    def on_sound_toggled(self, checked):
        self.data["sound_ui"] = "True" if checked else "False"
        self.mark_dirty()

    def on_typewriter_toggled(self, checked):
        self.data["sound_typewriter"] = "True" if checked else "False"
        self.mark_dirty()

    def on_line_numbers_toggled(self, checked):
        self.data["show_line_numbers"] = "True" if checked else "False"
        self.text_area.update_line_number_area_width()
        self.text_area.line_number_area.update()
        self.mark_dirty()

    def apply_wrap_mode(self):
        wrap = self.data.get("word_wrap", "True") == "True"
        self.text_area.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth if wrap else QTextEdit.LineWrapMode.NoWrap)

    def open_hotkey_settings(self):
        from fastprompter.ui.settings import HotkeySettingsDialog
        dlg = HotkeySettingsDialog(self)
        self.ignore_focus_loss = True
        try:
            dlg.exec()
        finally:
            self.ignore_focus_loss = False

    def _snapshot_current(self):
        return {
            "categories": copy.deepcopy(self.data["categories"]),
            "temp_presets": copy.deepcopy(self.data["temp_presets"]),
            "archive_temp_presets": copy.deepcopy(self.data["archive_temp_presets"]),
            "active_temp_slot": self.active_temp_slot,
            "active_is_archive": getattr(self, 'active_is_archive', False),
            "editing_snippet": getattr(self, 'editing_snippet', None)
        }

    def undo_action(self):
        if self.text_area.hasFocus() and self.text_area.document().isUndoAvailable():
            self.text_area.undo()
            return
        if hasattr(self, 'data_undo_stack') and self.data_undo_stack:
            if not hasattr(self, 'data_redo_stack'):
                self.data_redo_stack = []
            redo_state = self._snapshot_current()
            self.data_redo_stack.append(redo_state)
            if len(self.data_redo_stack) > 50:
                self.data_redo_stack.pop(0)
            state = self.data_undo_stack.pop()
            self._apply_data_state(state)
            self.play_sound("tick")
            return
        if self.text_area.document().isUndoAvailable():
            self.text_area.undo()

    def redo_action(self):
        if self.text_area.hasFocus() and self.text_area.document().isRedoAvailable():
            self.text_area.redo()
            return
        if hasattr(self, 'data_redo_stack') and self.data_redo_stack:
            if not hasattr(self, 'data_undo_stack'):
                self.data_undo_stack = []
            undo_state = self._snapshot_current()
            self.data_undo_stack.append(undo_state)
            state = self.data_redo_stack.pop()
            self._apply_data_state(state)
            self.play_sound("tick")
            return
        if self.text_area.document().isRedoAvailable():
            self.text_area.redo()

    def _apply_data_state(self, state):
        self.data["categories"] = state["categories"]
        self.data["temp_presets"] = state["temp_presets"]
        self.data["archive_temp_presets"] = state["archive_temp_presets"]
        from PyQt6.QtGui import QTextDocument
        font = self.text_area.font()
        while len(self.silo_docs) < len(self.data["temp_presets"]):
            d = QTextDocument()
            d.setDefaultFont(font)
            self.silo_docs.append(d)
        while len(self.silo_docs) > len(self.data["temp_presets"]):
            self.silo_docs.pop()
        for i, txt in enumerate(self.data["temp_presets"]):
            if self.silo_docs[i].toPlainText() != txt:
                self._set_plain_text_clean(self.silo_docs[i], txt)
        while len(self.archive_docs) < len(self.data["archive_temp_presets"]):
            d = QTextDocument()
            d.setDefaultFont(font)
            self.archive_docs.append(d)
        while len(self.archive_docs) > len(self.data["archive_temp_presets"]):
            self.archive_docs.pop()
        for i, txt in enumerate(self.data["archive_temp_presets"]):
            if self.archive_docs[i].toPlainText() != txt:
                self._set_plain_text_clean(self.archive_docs[i], txt)
        active_is_archive = state.get("active_is_archive", False)
        active_slot = state.get("active_temp_slot", 0)
        editing = state.get("editing_snippet", None)
        self.mark_dirty()
        self.build_categories()
        if editing:
            self._suspend_cache = True
            self.text_area.blockSignals(True)
            snippet_key = f"{editing[0]}_{editing[1]}"
            cat_data = self.data["categories"].get(editing[0])
            slot = cat_data[editing[1]] if cat_data and editing[1] < len(cat_data) else None
            if slot and snippet_key in self.snippet_docs:
                doc = self.snippet_docs[snippet_key]
                if doc.toPlainText() != slot.get("text", ""):
                    self._set_plain_text_clean(doc, slot["text"])
                self.text_area.set_active_document(doc)
            else:
                doc = QTextDocument()
                doc.setDefaultFont(self.text_area.font())
                if slot:
                    doc.setPlainText(slot.get("text", ""))
                self.text_area.set_active_document(doc)
            self.text_area.blockSignals(False)
            self.editing_snippet = editing
            self.btn_save.setText("Save Snippet")
            theme_name = self.data.get("theme", "Default")
            if theme_name in THEMES:
                self.btn_save.setStyleSheet(THEMES[theme_name].get("btn_save_snippet", ""))
            self._suspend_cache = False
        else:
            self._suspend_cache = True
            self.cancel_editing()
            self.active_is_archive = active_is_archive
            if active_is_archive:
                if active_slot < len(self.data["archive_temp_presets"]):
                    self._switch_to_slot(active_slot, initial=True, is_archive=True)
            else:
                if active_slot < len(self.data["temp_presets"]):
                    self._switch_to_slot(active_slot, initial=True)
            self._suspend_cache = False
        self.refresh_temp_presets()
        self.refresh_archive_panel()

    def add_data_undo_state(self, action_name=""):
        if not hasattr(self, 'data_undo_stack'):
            self.data_undo_stack = []
        if not hasattr(self, 'data_redo_stack'):
            self.data_redo_stack = []
        state = self._snapshot_current()
        self.data_undo_stack.append(state)
        if len(self.data_undo_stack) > 50:
            self.data_undo_stack.pop(0)
        self.data_redo_stack.clear()

    def build_categories(self):
        """Rebuild the tab bar from cats_order."""
        self.tab_bar.blockSignals(True)
        self.tab_bar.clear()
        for cat in self.data['cats_order']:
            self.tab_bar.addTab(cat)
        self.tab_bar.blockSignals(False)
        if self.tab_bar.count() > 0:
            self.tab_bar.setCurrentIndex(0)
        self.refresh_snippets_panel()

    def commit_current_text(self):
        """Commit the current text to the active slot."""
        if getattr(self, "_initializing_ui", False):
            return
        current_text = self.text_area.toPlainText()
        if not self.editing_snippet:
            if 0 <= self.active_temp_slot < len(self.data["temp_presets"]):
                self.data["temp_presets"][self.active_temp_slot] = current_text
        else:
            cat, idx = self.editing_snippet
            if cat in self.data["categories"] and self.data["categories"][cat][idx]:
                self.data["categories"][cat][idx]["text"] = current_text


    def open_color_settings(self):
        from fastprompter.ui.settings import ColorConfigDialog
        dlg = ColorConfigDialog(self)
        self.ignore_focus_loss = True
        try:
            dlg.exec()
        finally:
            self.ignore_focus_loss = False

    def backup_db(self):
        from fastprompter.ui.backup_dialog import BackupDialog
        dlg = BackupDialog(self)
        dlg.exec()

    def restore_db(self):
        path, _ = QFileDialog.getOpenFileName(self, "Restore Backup", "", "SQLite DB (*.db *.bak);;All Files (*)")
        if not path: return
        self.ignore_focus_loss = True
        try:
            reply = QMessageBox.question(self, "Confirm", "App will restart. Proceed?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if reply == QMessageBox.StandardButton.Yes:
                db_path = self.state.db_path
                if self.state.conn:
                    self.state.conn.close()
                    self.state.conn = None
                self.conn = None
                time.sleep(0.1)
                shutil.copy2(path, db_path)
                for ext in ["-wal", "-shm"]:
                    if os.path.exists(db_path + ext):
                        try: os.remove(db_path + ext)
                        except: pass
                self.quit_app()
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to restore backup:\n{e}")
            self.state.init_db()
            self.conn = self.state.conn
        finally:
            self.ignore_focus_loss = False

    def on_search_toggle(self, checked):
        self.search_bar.setVisible(checked)
        self.data["search_visible"] = str(checked)
        self.mark_dirty()
        if checked:
            self.search_bar.setFocus()
        else:
            self.search_bar.clear()

    def _position_archive_overlay(self):
        if not hasattr(self, 'archive_section') or not hasattr(self, 'left_panel'):
            return
        self.archive_section.setFixedWidth(self.left_panel.width())
        self.archive_section.adjustSize()
        ah = self.archive_section.sizeHint().height()
        lh = self.left_panel.height()
        self.archive_section.move(0, max(0, lh - ah))
        self.archive_section.raise_()

    def on_archive_toggle(self, checked):
        self.data["archive_visible"] = "True" if checked else "False"
        self.archive_section.setVisible(checked)
        if checked:
            self._position_archive_overlay()
        
        if self.btn_toggle_archive.isChecked() != checked:
            self.btn_toggle_archive.blockSignals(True)
            self.btn_toggle_archive.setChecked(checked)
            self.btn_toggle_archive.blockSignals(False)

        self.mark_dirty()
        self.text_area.setFocus()

    def clean_excessive_newlines(self):
        self.play_sound("clear")
        try:
            text = self.text_area.toPlainText()
            if not text: return
            import re
            lines = text.split('\n')
            is_empty = [bool(not line.strip()) for line in lines]
            is_dash = [bool(re.match(r'^\s*-{3,}\s*$', line)) for line in lines]
            
            out = []
            i = 0
            while i < len(lines):
                if not is_empty[i]:
                    out.append(lines[i])
                    i += 1
                else:
                    j = i
                    while j < len(lines) and is_empty[j]:
                        j += 1
                    prev_is_dash = (i > 0 and is_dash[i-1])
                    next_is_dash = (j < len(lines) and is_dash[j])
                    
                    if prev_is_dash or next_is_dash:
                        out.extend(lines[i:j])
                    else:
                        num_to_keep = min(1, j - i)
                        out.extend(lines[i:i+num_to_keep])
                    i = j
                    
            cleaned_text = '\n'.join(out)
            if cleaned_text != text:
                cursor = self.text_area.textCursor()
                cursor.beginEditBlock()
                cursor.select(QTextCursor.SelectionType.Document)
                cursor.insertText(cleaned_text)
                cursor.endEditBlock()
        except Exception as e:
            pass  # Never crash on newline cleanup

    def clear_formatting(self):
        self.play_sound("clear")
        cursor = self.text_area.textCursor()
        cursor.beginEditBlock()
        
        clean_format = QTextCharFormat()
        try: base_size = int(self.data.get("font_size", 11))
        except Exception: base_size = 11
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
                self._set_plain_text_clean(self.text_area, raw_text)
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

    def load_custom_font(self):
        """Load a custom TTF/OTF font file and add it to the font combobox."""
        self.ignore_focus_loss = True
        try:
            path, _ = QFileDialog.getOpenFileName(
                self, "Load Font File", "", 
                "Font Files (*.ttf *.otf *.TTF *.OTF);;All Files (*.*)"
            )
        finally:
            self.ignore_focus_loss = False
        self.activateWindow()
        if not path: return
        
        font_id = QFontDatabase.addApplicationFont(path)
        if font_id < 0:
            QMessageBox.warning(self, "Load Font", f"Failed to load font: {path}")
            return
        
        families = QFontDatabase.applicationFontFamilies(font_id)
        if not families:
            QMessageBox.warning(self, "Load Font", "Font loaded but no font families found.")
            return
        
        # Track loaded custom font IDs for cleanup
        loaded = self.data.get("custom_font_ids", [])
        if isinstance(loaded, str):
            import json
            try: loaded = json.loads(loaded)
            except: loaded = []
        loaded.append(font_id)
        self.data["custom_font_ids"] = loaded
        
        for family in families:
            if self.font_combo.findText(family) < 0:
                self.font_combo.addItem(family)
        
        self.font_combo.setCurrentText(families[0])
        QMessageBox.information(self, "Font Loaded", f"Loaded: {families[0]}")

    def clear_custom_fonts(self):
        """Remove all custom fonts from the combobox, reset to built-in list."""
        self.ignore_focus_loss = True
        try:
            reply = QMessageBox.question(
                self, "Clear Custom Fonts", 
                "Remove all custom fonts from the font selector?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
        finally:
            self.ignore_focus_loss = False
        self.activateWindow()
        if reply != QMessageBox.StandardButton.Yes: return
        
        default_fonts = ["Verdana", "Tahoma", "Consolas", "Calibri", "Times New Roman", "Arial", "Segoe UI", "Courier New"]
        self.font_combo.blockSignals(True)
        self.font_combo.clear()
        self.font_combo.addItems(default_fonts)
        self.font_combo.blockSignals(False)
        
        # Reset font to Verdana if current was custom
        if self.data.get("font_family", "Verdana") not in default_fonts:
            self.font_combo.setCurrentText("Verdana")
            self.change_font_family("Verdana")
        else:
            idx = self.font_combo.findText(self.data.get("font_family", "Verdana"))
            if idx >= 0: self.font_combo.setCurrentIndex(idx)
        
        self.data["custom_font_ids"] = []
        self.mark_dirty()

    def load_snippet_for_edit(self, cat, global_idx, cursor_pos="end"):
        self._cache_timer.stop()  # prevent stale timer from writing to wrong slot
        if self.editing_snippet:
            self.save_snippet(silent=True)
        else:
            # Save current silo before loading snippet (sandbox)
            if 0 <= self.active_temp_slot < len(self.data["temp_presets"]):
                self.data["temp_presets"][self.active_temp_slot] = self.text_area.toPlainText()
        self.play_sound("snippet")

            
        slot_data = self.data["categories"].get(cat, [None] * 100)[global_idx] if cat in self.data["categories"] else None
        if not slot_data: return
        self.mark_dirty()
        self.ignore_focus_loss, self._suspend_cache = True, True
        try:
            self.text_area.blockSignals(True)
            snippet_key = f"{cat}_{global_idx}"
            if snippet_key not in self.snippet_docs:
                from PyQt6.QtGui import QTextDocument
                doc = QTextDocument()
                doc.setDefaultFont(self.text_area.font())
                self.snippet_docs[snippet_key] = doc
            
            doc = self.snippet_docs[snippet_key]
            if doc.toPlainText() != slot_data["text"]:
                self._set_plain_text_clean(doc, slot_data["text"])
            
            self.text_area.set_active_document(doc)
            
            if cursor_pos == "start":
                self.text_area.moveCursor(QTextCursor.MoveOperation.Start)
            else:
                self.text_area.moveCursor(QTextCursor.MoveOperation.End)

        finally:
            self.text_area.blockSignals(False)
            self._suspend_cache, self.ignore_focus_loss = False, False
        self.editing_snippet = (cat, global_idx)
        self.btn_save.setText("Update")
        theme_name = self.data.get("theme", "Default")
        
        edit_color = "#363b40"
        if theme_name == "Custom":
            custom_colors = self._get_custom_colors()
            if "edit_bg" in custom_colors:
                edit_color = custom_colors["edit_bg"]
        
        if theme_name in THEMES:
            base_style = THEMES[theme_name]["btn_save"]
            self.btn_save.setStyleSheet(base_style.replace("background-color:", f"background-color: {edit_color} !important; /*") + f" */ background-color: {edit_color}; color: #ffffff;")
        self.refresh_snippets_panel()
        self.refresh_temp_presets()
        self.update_preview()
        self.text_area.setFocus()
        self.text_area.ensureCursorVisible()
        self.activateWindow()

    def prompt_delete_snippet(self, cat, global_idx):
        self.play_sound("delete")
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
            self.add_data_undo_state("Rename snippet")
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
        
        btn_height = max(14, int(round(24 * scale)))
        spacing = 2
        if hasattr(self, 'archive_widget'):
            self.archive_widget.setFixedHeight(10 * btn_height + 9 * spacing)
        if hasattr(self, 'snippets_widget'):
            self.snippets_widget.setFixedHeight(10 * btn_height + 9 * spacing)

        base_heights = {
            "btn_clear": 24, "btn_format": 24, "btn_clear_fmt": 24, "btn_clean_space": 24, "btn_add_line": 24,
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
                
                try:
                    font = w.font()
                    font.setPointSizeF(max(7.0, 9.0 * scale))
                    w.setFont(font)
                except Exception: pass
        
        if hasattr(self, 'btn_sidebar_toggle'):
            self.btn_sidebar_toggle.setFixedWidth(max(14, int(round(24 * scale))))
        for btn_name in ('btn_bold', 'btn_italic', 'btn_under', 'btn_strike', 'btn_find_prev', 'btn_find_next', 'btn_close_search'):
            w = getattr(self, btn_name, None)
            if w is not None:
                try: w.setFixedWidth(max(14, int(round(24 * scale))))
                except Exception: pass
                
                try:
                    font = w.font()
                    font.setPointSizeF(max(7.0, 9.0 * scale))
                    w.setFont(font)
                except Exception: pass
            
        try: self.left_panel.setMinimumWidth(max(80, int(round(130 * scale))))
        except Exception: pass
        
        self.refresh_button_scale()
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
            # Convert bullets back to dashes, skip divider lines
            new_lines = []
            for line in lines:
                if re.match(r'^\s*-{3,}\s*$', line):  # Protect --- dividers
                    new_lines.append(line)
                else:
                    new_lines.append(re.sub(r'^(\s*)•\s*', r'\1- ', line))
        else: 
            # Convert dashes to bullets, skip divider lines (---)
            new_lines = []
            for line in lines:
                if re.match(r'^\s*-{3,}\s*$', line):  # Protect --- dividers from conversion
                    new_lines.append(line)
                else:
                    new_lines.append(re.sub(r'^(\s*)-\s+', r'\1• ', line))
            
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
        fgeo = self.frameGeometry()
        x, y, w, h = fgeo.x(), fgeo.y(), geo.width(), geo.height()
        
        if hasattr(self, "cb_lock_cursor") and self.cb_lock_cursor.isChecked():
            old_geo = self.data.get("last_geometry", "")
            if old_geo:
                try:
                    ox, oy, _, _ = map(int, old_geo.split(','))
                    x, y = ox, oy
                except Exception:
                    pass

                    
        new_geo = f"{x},{y},{w},{h}"
        if self.data.get("last_geometry", "") != new_geo:
            self.data["last_geometry"] = new_geo
            self.mark_dirty()

    def moveEvent(self, event):
        if getattr(self, 'is_locked', False) and getattr(self, '_locked_geometry', None):
            if self.geometry() != self._locked_geometry:
                self.setGeometry(self._locked_geometry)
                return
        self._update_last_geometry()
        super().moveEvent(event)

    def closeEvent(self, event):
        self.save_data_to_db(force=True)
        super().closeEvent(event)

    def resizeEvent(self, event):
        if getattr(self, 'is_locked', False) and getattr(self, '_locked_geometry', None):
            if self.geometry() != self._locked_geometry:
                self.setGeometry(self._locked_geometry)
                return
        self._update_last_geometry()
        
        if hasattr(self, 'cb_tray'):
            use_short = self.width() < 650
            self.cb_tray.setText("[TRAY]" if use_short else "Tray Icon")
            self.cb_focus.setText("[FOCS]" if use_short else "Click Out")
            self.cb_ctrl_c.setText("[C+CC]" if use_short else "Ctrl+C Hide")
            self.cb_top.setText("[AOT]" if use_short else "Always Top")
            self.cb_lock_window.setText("[LCK]" if use_short else "Lock Win")
            self.cb_normal_window.setText("[NORM]" if use_short else "Normal Win")
            self.cb_lock_cursor.setText("[CURS]" if use_short else "Lock Cursor")
            self.cb_hide_shortkeys.setText("[SHORT]" if use_short else "Hide Keys")
            self.cb_sidebar.setText("[RSID]" if use_short else "Right Bar")
            self.cb_silo_home.setText("[HOME]" if use_short else "Home Silo")
            self.cb_wrap.setText("[WRP]" if use_short else "Word Wrap")
            self.cb_line_numbers.setText("[L#]" if use_short else "Line Nums")
            self.cb_sound.setText("[SND]" if use_short else "Interface Sounds")
            self.cb_typewriter.setText("[TYP]" if use_short else "Typing Effect")

        # Update edge resizers
        if hasattr(self, '_resizers'):
            t = 6
            w, h = self.width(), self.height()
            self._resizers['left'].setGeometry(0, t, t, h - 2*t)
            self._resizers['right'].setGeometry(w - t, t, t, h - 2*t)
            self._resizers['top'].setGeometry(t, 0, w - 2*t, t)
            self._resizers['bottom'].setGeometry(t, h - t, w - 2*t, t)
            self._resizers['topleft'].setGeometry(0, 0, t, t)
            self._resizers['topright'].setGeometry(w - t, 0, t, t)
            self._resizers['bottomleft'].setGeometry(0, h - t, t, t)
            self._resizers['bottomright'].setGeometry(w - t, h - t, t, t)
            for r in self._resizers.values():
                r.raise_()

        super().resizeEvent(event)

    # def nativeEvent(self, eventType, message):
    #     return super().nativeEvent(eventType, message)

    def mousePressEvent(self, event):
        from PyQt6 import sip
        if sip.isdeleted(self): return
        if getattr(self, "is_locked", False):
            event.ignore(); return
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        from PyQt6 import sip
        if sip.isdeleted(self): return
        if getattr(self, "is_locked", False): return
        
        if event.buttons() == Qt.MouseButton.LeftButton:
            if hasattr(self, '_drag_pos'):
                self.move(event.globalPosition().toPoint() - self._drag_pos)
                event.accept()

    def mouseReleaseEvent(self, event):
        from PyQt6 import sip
        if sip.isdeleted(self): return
        if hasattr(self, '_drag_pos'):
            del self._drag_pos
            event.accept()

    def changeEvent(self, event):
        if event.type() in (QEvent.Type.ActivationChange, QEvent.Type.WindowDeactivate):
            if not self.isActiveWindow():
                if getattr(self, "cb_focus", None) and self.cb_focus.isChecked():
                    if not getattr(self, "ignore_focus_loss", False) and not getattr(self, "is_locked", False):
                        self.hide_and_save()
        super().changeEvent(event)

    def eventFilter(self, obj, event):
        from PyQt6 import sip
        if sip.isdeleted(self) or (obj and sip.isdeleted(obj)): return False
        
        
        if obj == getattr(self, 'silos_widget', None) and event.type() == QEvent.Type.Resize:
            self._update_visible_silo_count()
            if hasattr(self, '_silo_resize_debounce_timer'):
                self._silo_resize_debounce_timer.start()
            return False
        
        if obj == getattr(self, 'left_panel', None) and event.type() == QEvent.Type.Resize:
            self._position_archive_overlay()
            return False
        
        
        if event.type() == QEvent.Type.MouseButtonPress and getattr(event, 'button', lambda: 0)() == Qt.MouseButton.RightButton:
            if not getattr(self, "is_locked", False):
                self._text_drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
                return False
        elif event.type() == QEvent.Type.MouseMove and getattr(event, 'buttons', lambda: 0)() & Qt.MouseButton.RightButton:
            if not getattr(self, "is_locked", False) and hasattr(self, '_text_drag_pos'):
                self.move(event.globalPosition().toPoint() - self._text_drag_pos)
                return True
        elif event.type() == QEvent.Type.MouseButtonRelease and getattr(event, 'button', lambda: 0)() == Qt.MouseButton.RightButton:
            if hasattr(self, '_text_drag_pos'):
                delattr(self, '_text_drag_pos')
                return False
        return super().eventFilter(obj, event)


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
        else:
            self.adjustSize()

        QApplication.processEvents()
        fw = self.frameGeometry().width()
        fh = self.frameGeometry().height()

        # 2. Then, determine and set the position
        if self.cb_lock_cursor.isChecked():
            cp = QCursor.pos()
            screen = QApplication.screenAt(cp)
            screen_geom = screen.availableGeometry() if screen else QApplication.primaryScreen().availableGeometry()
            
            x = cp.x() - fw // 2
            y = cp.y() - fh // 2
            
            x = max(screen_geom.left(), min(x, screen_geom.right() - fw))
            y = max(screen_geom.top(), min(y, screen_geom.bottom() - fh))
            
            self.move(x, y)
        else:
            if geo_str:
                try:
                    saved_x, saved_y, _, _ = map(int, geo_str.split(','))
                    valid_screen = False
                    from PyQt6.QtCore import QRect
                    window_rect = QRect(saved_x, saved_y, fw, fh)
                    for screen in QApplication.screens():
                        if screen.availableGeometry().intersects(window_rect):
                            valid_screen = True; break
                    if not valid_screen:
                        cp = QCursor.pos()
                        saved_x, saved_y = cp.x() - fw//2, cp.y() - fh//2
                    self.move(saved_x, saved_y)
                except Exception:
                    cp = QCursor.pos()
                    self.move(cp.x() - fw//2, cp.y() - fh//2)
            else:
                cp = QCursor.pos()
                self.move(cp.x() - fw//2, cp.y() - fh//2)

    def show_window(self, by_hotkey=False):
        if by_hotkey and hasattr(self, 'cb_lock_cursor') and self.cb_lock_cursor.isChecked():
            self.place_window()
        if self.isMinimized():
            self.showNormal()
        self.show()
        if hasattr(self, "topmost_timer") and self.data.get("always_on_top", "True") == "True":
            self.topmost_timer.start(5000)
        self.raise_()
        self.activateWindow()
        self.text_area.setFocus()

    def cancel_editing(self):
        self.editing_snippet = None
        self.btn_save.setText("Save")
        theme_name = self.data.get("theme", "Default")
        if theme_name in THEMES: self.btn_save.setStyleSheet(THEMES[theme_name]["btn_save"])
        self.refresh_snippets_panel()
        self.refresh_temp_presets()

    def clear_text(self):
        self.play_sound("clear")
        cursor = self.text_area.textCursor()
        cursor.beginEditBlock()
        cursor.select(QTextCursor.SelectionType.Document)
        cursor.removeSelectedText()
        cursor.endEditBlock()
        self.cancel_editing()
        self.text_area.setFocus()

    def copy_context_to_clipboard(self):
        """Copy entire text area content to clipboard."""
        text = self.text_area.toPlainText()
        QApplication.clipboard().setText(text)

    def copy_context_and_close(self, pos=None):
        """Copy entire text area content to clipboard and hide FastPrompter."""
        self.copy_context_to_clipboard()
        self.hide_and_save()


            

    def add_category(self):
        self.play_sound("new")
        if len(self.data['cats_order']) >= 100: return
        self.ignore_focus_loss = True
        try:
            name, ok = QInputDialog.getText(self, "New Tab", "Enter tab name:")
        finally:
            self.ignore_focus_loss = False
        self.activateWindow()
        if ok and name and name.strip() not in self.data['cats_order']:
            self.add_data_undo_state("Add category")
            name = name.strip()
            self.data['cats_order'].append(name)
            self.data['categories'][name] = [None]*100
            self.tab_bar.addTab(name)
            self.tab_bar.setCurrentIndex(self.tab_bar.count()-1)
            self.mark_dirty()

    def del_category(self):
        self.play_sound("delete")
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
            self.add_data_undo_state("Delete category")
            self.data['cats_order'].pop(idx)
            del self.data['categories'][cat]
            if cat in self.current_pages: del self.current_pages[cat]
            self.tab_bar.removeTab(idx)
            self.mark_dirty()

    def on_tab_changed(self, index):
        if index < 0: return
        self.data["last_tab_idx"] = index
        self.commit_current_text()
        self.cancel_editing()
        self.refresh_snippets_panel()
        self.mark_dirty()
        self.text_area.setFocus()

    def get_current_category(self):
        idx = self.tab_bar.currentIndex()
        if 0 <= idx < len(self.data['cats_order']): return self.data['cats_order'][idx]
        return None

    def change_font_family(self, font_name):
        if getattr(self, '_initializing_ui', False): return
        self.data["font_family"] = font_name
        self.apply_font()
        self.mark_dirty()

    def change_font_size(self, size):
        if getattr(self, '_initializing_ui', False): return
        self.data["font_size"] = size
        self.apply_font()
        self.mark_dirty()

    def change_theme(self, theme_name):
        self.data["theme"] = theme_name
        self.mark_dirty()
        self.apply_theme()

    def apply_theme(self):
        theme_name = self.data.get("theme", "Default")
        if theme_name == "Custom":
            c = self._get_custom_colors()
            from fastprompter.theme.themes import generate_custom_theme
            theme = generate_custom_theme(c)
        else:
            if theme_name not in THEMES: theme_name = "Default"
            theme = THEMES[theme_name]
        
        QApplication.instance().setStyleSheet(theme["stylesheet"])
        self.btn_new.setStyleSheet(theme["btn_new"])
        self.btn_save.setStyleSheet(theme["btn_save"])
        self.btn_help.setStyleSheet(theme["lbl_help"])
        self.mini_settings_frame.setStyleSheet(theme["mini_settings"])
        
        if hasattr(self, 'snip_label'): self.snip_label.setStyleSheet(theme["lbl_title"])
        if hasattr(self, 'silo_label'): self.silo_label.setStyleSheet(theme["lbl_title"])
        if hasattr(self, 'archive_section'):
            bg = extract_bg(theme.get('mini_settings', '')) or '#1a1a1a'
            self.archive_section.setStyleSheet(f"#ArchiveSection {{ background-color: {bg}; }}")
        
        if hasattr(self, 'tray_icon'):
            icon_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "_res", "fastprompter_logo2.png")
            if os.path.exists(icon_path):
                icon = QIcon(icon_path)
            else:
                icon = create_tray_icon(theme["tray_color"])
            self.tray_icon.setIcon(icon)
            self.setWindowIcon(icon)
            
        if hasattr(self, 'highlighter'):
            self.highlighter.update_theme(theme)
            
        self.refresh_snippets_panel()
        self.refresh_temp_presets()

    def apply_font(self):
        if getattr(self, '_initializing_ui', False): return
        try: base_size = int(self.data.get("font_size", 11))
        except Exception: base_size = 11
        font_name = self.data.get("font_family", "Verdana")
        try: scale = float(self.data.get("ui_scale", "1.0"))
        except Exception: scale = 1.0
        font_size = max(8, int(round(base_size * scale)))
        font = QFont(font_name, font_size)
        font.setStyleStrategy(QFont.StyleStrategy.NoAntialias | QFont.StyleStrategy.NoSubpixelAntialias)
        QApplication.setFont(font)
        
        try:
            self.text_area.setFont(font)
            self.text_area.document().setDefaultFont(font)
            self.text_area.setFont(font)
            self.text_area.document().setDefaultFont(font)
            
            if hasattr(self, 'highlighter'):
                self.highlighter.update_base_size(font_size)
        except Exception as e: pass
        try:
            self.preview_area.setFont(font)
        except Exception: pass
        try:
            self.refresh_snippets_panel()
        except Exception: pass

    def change_preview_mode(self, index):
        """
        Obsidian-style view modes:
        - Source View: plain editor only, no preview
        - Live Preview: editor visible; headers/bold auto-highlighted via charformat (no separate panel)
        - Reading: read-only rendered HTML preview, editor hidden
        """
        mode = self.preview_combo.currentText()

        # Disconnect preview update if switching away from a connected mode
        if self._preview_connected:
            try: self.text_area.textChanged.disconnect(self.update_preview)
            except Exception: pass
            self._preview_connected = False

        if mode == "Source View":
            self.text_area.setVisible(True)
            self.text_area.setReadOnly(False)
            self.preview_area.setVisible(False)
            if hasattr(self, 'highlighter'): self.highlighter.setDocument(None)

        elif mode == "Live Preview":
            self.text_area.setVisible(True)
            self.text_area.setReadOnly(False)
            self.preview_area.setVisible(False)
            if hasattr(self, 'highlighter'): self.highlighter.setDocument(self.text_area.document())

        elif mode == "Reading":
            # Full reading pane — editor hidden, preview fills full height
            self.text_area.setVisible(False)
            self.preview_area.setVisible(True)
            if not self._preview_connected:
                self.text_area.textChanged.connect(self.update_preview)
                self._preview_connected = True
            self.update_preview()

        self.mark_dirty()

    def update_preview(self):
        text = self.text_area.toPlainText()
        mode = self.preview_combo.currentText()

        if mode == "Reading":
            self.preview_area.setHtml(self.simple_markdown_to_html(text))


    @staticmethod
    def simple_markdown_to_html(text):
        import markdown
        try:
            # Full markdown renderer using standard Python markdown library if available
            body = markdown.markdown(text, extensions=['fenced_code', 'tables'])
        except Exception:
            # Fallback to simple regex renderer if markdown library not available
            lines = text.split('\n')
            html_lines = []
            in_code_block = False
            for line in lines:
                if line.startswith('```'):
                    if in_code_block:
                        html_lines.append("</pre>")
                        in_code_block = False
                    else:
                        html_lines.append("<pre style='background:#1a1a1a;padding:5px;border:1px solid #333'>")
                        in_code_block = True
                    continue
                if in_code_block:
                    html_lines.append(line.replace('<', '&lt;').replace('>', '&gt;'))
                    continue

                if line.startswith('### '): html_lines.append(f"<h3 style='color:#d4a842;margin:4px 0'>{line[4:]}</h3>")
                elif line.startswith('## '): html_lines.append(f"<h2 style='color:#e0b856;margin:5px 0'>{line[3:]}</h2>")
                elif line.startswith('# '): html_lines.append(f"<h1 style='color:#f0cc6a;margin:6px 0'>{line[2:]}</h1>")
                elif line.startswith('> '): html_lines.append(f"<blockquote style='border-left:3px solid #7f848e;margin:4px 0;padding-left:8px;color:#7f848e'><i>{line[2:]}</i></blockquote>")
                elif re.match(r'^\s*[-*_]{3,}\s*$', line): html_lines.append("<hr style='border:1px solid #5a4a2a;'>")
                elif re.match(r'^\s*[-•*+]\s', line):
                    content = line.lstrip(' -•*+')
                    content = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', content)
                    content = re.sub(r'\*(.*?)\*', r'<i>\1</i>', content)
                    content = re.sub(r'`(.*?)`', r'<code style="background:#1a1a1a;padding:0 2px;color:#e06c75">\1</code>', content)
                    content = re.sub(r'\[(.*?)\]\((.*?)\)', r'<a href="\2" style="color:#61afef">\1</a>', content)
                    html_lines.append(f"<li style='margin:1px 0'>{content}</li>")
                else:
                    l = line
                    l = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', l)
                    l = re.sub(r'\*(.*?)\*', r'<i>\1</i>', l)
                    l = re.sub(r'`(.*?)`', r'<code style="background:#1a1a1a;padding:0 2px;color:#e06c75">\1</code>', l)
                    l = re.sub(r'\[(.*?)\]\((.*?)\)', r'<a href="\2" style="color:#61afef">\1</a>', l)
                    html_lines.append(f"<p style='margin:1px 0'>{l}</p>" if l.strip() else "<br>")
            body = '\n'.join(html_lines)
            
        return f"<html><body style='color:#c4ba9f;background:#0f0f0f;font-family:Verdana,sans-serif;font-size:11px;padding:6px'>{body}</body></html>"

    def toggle_paste_mode(self, checked):
        self.btn_format.setText("Plain" if checked else "Formatted")
        self.mark_dirty()

    def save_snippet(self, silent=False):
        if not silent:
            self.play_sound("snippet")
        text = self.text_area.toPlainText().strip()
        cat = self.get_current_category()
        
        if self.editing_snippet:
            edit_cat, idx = self.editing_snippet
            if edit_cat in self.data["categories"]:
                slots = self.data["categories"][edit_cat]
                if text:
                    old_name = slots[idx]["name"] if slots[idx] else ""
                    import time
                    if silent: self.add_data_undo_state("Auto-save snippet")
                    else: self.add_data_undo_state("Save snippet")
                    import time
                    old_text = slots[idx].get("text", "") if slots[idx] else ""
                    last_edited = slots[idx].get("last_edited", 0) if slots[idx] else 0
                    if text != old_text:
                        last_edited = int(time.time())
                    slots[idx] = {"name": old_name, "text": text, "last_edited": last_edited}
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
            self.add_data_undo_state("Save snippet")
            import time
            slots[slots.index(None)] = {"name": name, "text": text, "last_edited": int(time.time())}
            self.mark_dirty()
            self.refresh_snippets_panel()

    def save_snippet_as_number(self):
        self.play_sound("snippet")
        if self.editing_snippet:
            self.save_snippet(silent=True)
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
            self.add_data_undo_state("Save snippet as number")
            import time
            slots[slot] = {"name": name, "text": text, "last_edited": int(time.time())}
            self.mark_dirty()
            self.refresh_snippets_panel()
            self.cancel_editing()

    def del_last_snippet(self):
        cat = self.get_current_category()
        if getattr(self, 'editing_snippet', None) and cat and self.editing_snippet[0] == cat:
            idx = self.editing_snippet[1]
            slots = self.data["categories"][cat]
            if slots[idx] and slots[idx].get("text", "").strip():
                self.ignore_focus_loss = True
                try:
                    reply = QMessageBox.question(self, "Delete Snippet", "Are you sure you want to delete this snippet?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
                finally:
                    self.ignore_focus_loss = False
                self.activateWindow()
                if reply != QMessageBox.StandardButton.Yes: return
            self.play_sound("delete")
            self.delete_preset_by_index(cat, idx)
            return
            
        current_text = self.text_area.toPlainText().strip()
        if current_text:
            self.ignore_focus_loss = True
            try:
                reply = QMessageBox.question(self, "Delete Silo", "Are you sure you want to delete this silo and its content?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            finally:
                self.ignore_focus_loss = False
            self.activateWindow()
            if reply != QMessageBox.StandardButton.Yes: return
            
            self.play_sound("delete")
            self.del_silo()
            return
            
        # Silo is empty, user wants to delete the empty silo count
        self.del_silo()

    def change_page(self, delta):
        cat = self.get_current_category()
        if not cat: return
        active = sum(1 for s in self.data["categories"][cat] if s is not None)
        max_page = max(0, math.ceil(active / 10.0) - 1)
        new_page = self.current_pages.get(cat, 0) + delta
        if 0 <= new_page <= max_page:
            self.current_pages[cat] = new_page
            self.refresh_snippets_panel()

    def change_arc_page(self, delta):
        total = len(self.data.get("archive_temp_presets", []))
        visible_count = 10
        max_page = max(0, math.ceil(total / max(1, visible_count)) - 1)
        new_page = getattr(self, 'arc_silo_page', 0) + delta
        if 0 <= new_page <= max_page:
            self.arc_silo_page = new_page
            self.data["arc_silo_page"] = new_page
            self.refresh_archive_panel()

    def darken_color(self, hex_color, factor=0.75):
        hex_color = hex_color.lstrip('#')
        if len(hex_color) == 3: hex_color = ''.join(c+c for c in hex_color)
        r, g, b = tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))
        r, g, b = int(r*factor), int(g*factor), int(b*factor)
        return f"#{r:02x}{g:02x}{b:02x}"

    def refresh_snippets_panel(self):
        if self._suspend_cache or self._initializing_ui: return
        cat = self.get_current_category()
        if not cat:
            self.snippets_section.setVisible(False)
            self.refresh_archive_panel()
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
            self.refresh_archive_panel()
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
                disp = item["name"]
                color = preset_colors[global_idx % len(preset_colors)]
                is_editing = self.editing_snippet and self.editing_snippet == (cat, global_idx)
                last_ts = item.get("last_edited", 0)
                if last_ts and not is_editing:
                    diff = time.time() - last_ts
                    custom = self._get_custom_colors()
                    if diff < 60:
                        overlay = QColor(custom.get("overlay_new", "#ff4444"))
                    elif diff < 3600:
                        overlay = QColor(custom.get("overlay_recent", "#ff8800"))
                    elif diff < 86400:
                        overlay = QColor(custom.get("overlay_day", "#ffdd00"))
                    elif diff < 4233600:
                        overlay = QColor(custom.get("overlay_old", "#4488ff"))
                    else:
                        overlay = None
                    if overlay:
                        base = QColor(color)
                        color = self.blend_colors(base, overlay, 0.15)
                        
                w.update_data(f"{key_label}{disp}", cat, global_idx, item["text"], color, font_family, scale)
                w.show()
            else:
                if hasattr(w, 'main_btn'): 
                    w.main_btn.global_idx = -1
                    w.main_btn.setText("")
                    w.main_btn.full_text = ""
                w.hide()
            
        self.btn_page_up.setEnabled(page > 0)
        self.btn_page_down.setEnabled(page < math.ceil(total_active / 10.0) - 1)
        show_pagination = math.ceil(total_active / 10.0) > 1
        self.btn_page_up.setVisible(show_pagination)
        self.btn_page_down.setVisible(show_pagination)
        
        self.snippets_widget.adjustSize()
        self.snippets_section.adjustSize()
        if getattr(self, 'left_widget', None) and self.left_widget.parentWidget(): 
            self.left_widget.parentWidget().updateGeometry()

    def refresh_archive_panel(self):
        self._trim_archive()
        total = len(self.data.get("archive_temp_presets", []))
        if total == 0:
            self.archive_section.setVisible(False)
            return
            
        saved_arc_visible = self.data.get("archive_visible", "False") == "True"
        self.archive_section.setVisible(saved_arc_visible)
        
        visible_count = 10
        max_page = max(0, math.ceil(total / max(1, visible_count)) - 1)
        
        needs_visible = (max_page > 0)
        self.btn_arc_page_up.setVisible(needs_visible)
        self.btn_arc_page_down.setVisible(needs_visible)
        
        self.arc_silo_page = min(getattr(self, 'arc_silo_page', 0), max_page)
        self.btn_arc_page_up.setEnabled(self.arc_silo_page > 0)
        self.btn_arc_page_down.setEnabled(self.arc_silo_page < max_page)
        
        theme_name = self.data.get("theme", "Default")
        if theme_name not in THEMES: theme_name = "Default"
        inactive_color = THEMES[theme_name]["inactive_temp_color"]
        active_color = THEMES[theme_name]["active_temp_color"]
        
        custom_colors = self._get_custom_colors()
        if "edit_bg" in custom_colors:
            active_color = custom_colors["edit_bg"]

        try: scale = float(self.data.get("ui_scale", "1.0"))
        except Exception: scale = 1.0
        font_family = self.data.get("font_family", "Verdana")

        start_idx = self.arc_silo_page * visible_count
        
        for i, btn in enumerate(self.archive_buttons):
            if i < visible_count:
                slot_idx = start_idx + i
                if slot_idx < total:
                    text = self.data["archive_temp_presets"][slot_idx].replace('\n',' ').strip()
                    display_idx = slot_idx + 1
                    label = f"{display_idx}: {text}" if text else str(display_idx)
                    is_active = getattr(self, 'active_is_archive', False) and (slot_idx == self.active_temp_slot) and not getattr(self, 'editing_snippet', None)
                    bg_color = active_color if is_active else inactive_color
                    btn.update_data(label, slot_idx, bg_color, font_family, scale)
                    btn.show()
                else:
                    btn.hide()
            else:
                btn.hide()
                
        self.archive_widget.adjustSize()
        self.archive_section.adjustSize()

    def _trim_archive(self):
        entries = self.data.get("archive_temp_presets", [])
        if not entries:
            return
        new_entries = []
        new_docs = []
        old_to_new = {}
        for i, item in enumerate(entries):
            if item.strip():
                old_to_new[i] = len(new_entries)
                new_entries.append(item)
                if hasattr(self, 'archive_docs') and i < len(self.archive_docs):
                    new_docs.append(self.archive_docs[i])
        if len(new_entries) == len(entries):
            return
        self.data["archive_temp_presets"] = new_entries
        if hasattr(self, 'archive_docs'):
            self.archive_docs = new_docs
        if getattr(self, 'active_is_archive', False):
            old_idx = getattr(self, 'active_temp_slot', -1)
            if old_idx in old_to_new:
                self.active_temp_slot = old_to_new[old_idx]
            elif new_entries:
                self.active_temp_slot = 0
            else:
                self.active_is_archive = False
                self.active_temp_slot = max(0, min(self.active_temp_slot, len(self.data["temp_presets"]) - 1))
        self.mark_dirty()

    # move_preset_to_index is defined earlier in the class (uses pop+insert with undo)

    def delete_preset_by_index(self, cat, global_idx):
        if self.data["categories"][cat][global_idx] is not None:
            self.add_data_undo_state("Delete snippet")
        if getattr(self, 'editing_snippet', None) == (cat, global_idx):
            self.editing_snippet = None
            self.btn_save.setText("Save")
            self._suspend_cache = True
            try:
                self.clear_text()
            finally:
                self._suspend_cache = False
        snippet_key = f"{cat}_{global_idx}"
        if snippet_key in getattr(self, 'snippet_docs', {}):
            del self.snippet_docs[snippet_key]
        self.data["categories"][cat][global_idx] = None
        self.mark_dirty()
        self.refresh_snippets_panel()
        self.refresh_archive_panel()

    def del_silo(self, idx=None):
        self.play_sound("delete")
        if len(self.data["temp_presets"]) > 1:
            if idx is None:
                idx = self.active_temp_slot
                
            if not (0 <= idx < len(self.data["temp_presets"])):
                return
            
            if idx == self.active_temp_slot:
                self.data["temp_presets"][idx] = self.text_area.toPlainText()
            self.add_data_undo_state("Delete silo")
            text = self.data["temp_presets"].pop(idx)
            doc = self.silo_docs.pop(idx) if idx < len(self.silo_docs) else None
            
            if idx < self.active_temp_slot:
                self.active_temp_slot -= 1
            elif self.active_temp_slot >= len(self.data["temp_presets"]):
                self.active_temp_slot = len(self.data["temp_presets"]) - 1
            
            self.silo_page = self.active_temp_slot // max(1, self._visible_silos)
            self._switch_to_slot(self.active_temp_slot, initial=True)
            self.mark_dirty()
            self.cancel_editing()
            self.refresh_temp_presets()

    def select_empty_silo(self):
        if getattr(self, 'editing_snippet', None):
            self.save_snippet(silent=True)
        else:
            self.data["temp_presets"][self.active_temp_slot] = self.text_area.toPlainText()
        self.add_data_undo_state("New silo")
            
        for i, content in enumerate(self.data["temp_presets"]):
            if not content.strip():
                self.silo_page = i // max(1, self._visible_silos)
                self._switch_to_slot(i, initial=True)
                return
        if len(self.data["temp_presets"]) < 100:
            i = len(self.data["temp_presets"])
            self.data["temp_presets"].append("")
            
            from PyQt6.QtGui import QTextDocument
            doc = QTextDocument()
            doc.setDefaultFont(self.text_area.font())
            self.silo_docs.append(doc)
            
            self.silo_page = i // max(1, self._visible_silos)
            self._switch_to_slot(i, initial=True)

    def change_silo_page(self, delta):
        last_used = -1
        total_silos = len(self.data["temp_presets"])
        for i in range(total_silos - 1, -1, -1):
            if self.data["temp_presets"][i].strip():
                last_used = i
                break
        
        # Determine the maximum slot currently visible/accessible
        visible_silos = max(last_used + 1, self.active_temp_slot + 1, self._visible_silos)
        max_page = max(0, math.ceil(visible_silos / max(1, self._visible_silos)) - 1)
        new_page = self.silo_page + delta
        if 0 <= new_page <= max_page:
            self.silo_page = new_page
            self.refresh_temp_presets()

    def _switch_to_slot(self, idx, initial=False, is_archive=False):
        if is_archive:
            self.arc_silo_page = idx // 10
        else:
            self.silo_page = idx // max(1, self._visible_silos)
            
        was_editing_snippet = bool(getattr(self, 'editing_snippet', None))
        was_archive = getattr(self, 'active_is_archive', False)
        
        if not initial:
            self.play_click_sound()
            self._cache_timer.stop()  # prevent stale timer from updating wrong silo's last_edited
            if was_editing_snippet:
                self.save_snippet(silent=True)
            else:
                if was_archive:
                    new_txt = self.text_area.toPlainText()
                    if new_txt.strip() and 0 <= self.active_temp_slot < len(self.data.get("archive_temp_presets", [])):
                        self.data["archive_temp_presets"][self.active_temp_slot] = new_txt
                else:
                    old_slot = self.active_temp_slot
                    new_text = self.text_area.toPlainText()
                    if 0 <= old_slot < len(self.data["temp_presets"]):
                        old_text = self.data["temp_presets"][old_slot]
                        self.data["temp_presets"][old_slot] = new_text
                        if new_text != old_text:
                            self.silo_last_edited[old_slot] = int(time.time())
                
        if not is_archive:
            if "temp_presets" not in self.data or not self.data["temp_presets"]:
                self.data["temp_presets"] = [""]
            if idx >= len(self.data["temp_presets"]):
                idx = max(0, len(self.data["temp_presets"]) - 1)
        else:
            if "archive_temp_presets" not in self.data or not self.data["archive_temp_presets"]:
                self.data["archive_temp_presets"] = [""]
            if idx >= len(self.data["archive_temp_presets"]):
                idx = max(0, len(self.data["archive_temp_presets"]) - 1)
                
        # If we are already on this silo and not editing a snippet, early return
        if not initial and not was_editing_snippet and self.active_temp_slot == idx and getattr(self, 'active_is_archive', False) == is_archive:
            self.text_area.setFocus()
            self.text_area.ensureCursorVisible()
            if is_archive:
                self.refresh_archive_panel()
            else:
                self.refresh_temp_presets()
            return
        
        if not initial:
            self.add_data_undo_state("Switch silo")
        
        self.cancel_editing()
        self.active_temp_slot = idx
        self.active_is_archive = is_archive
        
        self._suspend_cache = True
        try:
            self.text_area.blockSignals(True)
            
            if is_archive:
                # Ensure archive_docs has enough docs
                while len(self.archive_docs) <= idx:
                    from PyQt6.QtGui import QTextDocument
                    d = QTextDocument()
                    d.setDefaultFont(self.text_area.font())
                    self.archive_docs.append(d)
                doc = self.archive_docs[idx]
                archive = self.data.get("archive_temp_presets", [])
                if idx >= len(archive):
                    archive = [""] * (idx + 1)
                    self.data["archive_temp_presets"] = archive
                new_text = archive[idx]
            else:
                if idx >= len(self.silo_docs):
                    from PyQt6.QtGui import QTextDocument
                    while len(self.silo_docs) <= idx:
                        d = QTextDocument()
                        d.setDefaultFont(self.text_area.font())
                        self.silo_docs.append(d)
                doc = self.silo_docs[idx]
                new_text = self.data["temp_presets"][idx]
                
            if doc.toPlainText() != new_text:
                self._set_plain_text_clean(doc, new_text)
                
            self.text_area.set_active_document(doc)
            
            if self.data.get("silo_home", "False") == "True":
                self.text_area.moveCursor(QTextCursor.MoveOperation.Start)
            else:
                self.text_area.moveCursor(QTextCursor.MoveOperation.End)

        finally:
            self.text_area.blockSignals(False)
            self._suspend_cache = False
            
        self.refresh_temp_presets()
        self.refresh_archive_panel()
        self.update_preview()
        self.text_area.setFocus()
        self.text_area.ensureCursorVisible()
        if not initial: self.mark_dirty()

    def _switch_to_arc_slot(self, idx):
        self._switch_to_slot(idx, is_archive=True)


    def refresh_temp_presets(self):
        total = len(self.data["temp_presets"])
        if total == 0:
            self.silos_section.setVisible(False)
            return
        # Skip if silos_widget not ready
        if not hasattr(self, 'silos_widget') or not hasattr(self, 'silo_buttons'):
            return

        self.silos_section.setVisible(True)
        max_page = max(0, math.ceil(total / max(1, self._visible_silos)) - 1)
        
        # Check if up/down button visibility needs to change, causing layout shift
        was_visible = self.btn_silo_up.isVisible()
        needs_visible = (max_page > 0)
        
        if was_visible != needs_visible:
            self.btn_silo_up.setVisible(needs_visible)
            self.btn_silo_down.setVisible(needs_visible)
            from PyQt6.QtCore import QTimer
            QTimer.singleShot(0, self._deferred_silo_refresh)
            return

        if self.silo_page > max_page: self.silo_page = max_page
        
        theme_name = self.data.get("theme", "Default")
        if theme_name not in THEMES: theme_name = "Default"
        active_color = THEMES[theme_name]["active_temp_color"]
        inactive_color = THEMES[theme_name]["inactive_temp_color"]

        try: scale = float(self.data.get("ui_scale", "1.0"))
        except Exception: scale = 1.0
        font_family = self.data.get("font_family", "Verdana")

        start_idx = self.silo_page * self._visible_silos
        for i, btn in enumerate(self.silo_buttons):
            slot_idx = start_idx + i
            if slot_idx < total and i < self._visible_silos:
                text = self.data["temp_presets"][slot_idx].replace('\n',' ').strip()
                display_idx = slot_idx + 1
                label = f"{display_idx}: {text}" if text else str(display_idx)
                is_active = (not getattr(self, 'active_is_archive', False)) and (slot_idx == self.active_temp_slot) and not getattr(self, 'editing_snippet', None)
                bg_color = active_color if is_active else inactive_color
                if text and slot_idx in getattr(self, 'silo_last_edited', {}):
                    last_ts = self.silo_last_edited[slot_idx]
                    diff = time.time() - last_ts
                    custom = self._get_custom_colors()
                    if diff < 60:
                        overlay = QColor(custom.get("overlay_new", "#ff4444"))
                    elif diff < 3600:
                        overlay = QColor(custom.get("overlay_recent", "#ff8800"))
                    elif diff < 86400:
                        overlay = QColor(custom.get("overlay_day", "#ffdd00"))
                    elif diff < 4233600:
                        overlay = QColor(custom.get("overlay_old", "#4488ff"))
                    else:
                        overlay = None
                    if overlay and not is_active:
                        base = QColor(bg_color)
                        bg_color = self.blend_colors(base, overlay, 0.15)
                btn.update_data(label, slot_idx, bg_color, font_family, scale)
            else:
                btn.hide()
            
        self.btn_silo_up.setEnabled(self.silo_page > 0)
        self.btn_silo_down.setEnabled(self.silo_page < max_page)

    @staticmethod
    def blend_colors(c1, c2, ratio):
        return f"#{int(c1.red() * (1 - ratio) + c2.red() * ratio):02x}{int(c1.green() * (1 - ratio) + c2.green() * ratio):02x}{int(c1.blue() * (1 - ratio) + c2.blue() * ratio):02x}"

    def show_temp_menu(self, idx, pos, is_archive=False):
        cur = self.text_area.toPlainText().strip()
        menu = QMenu(self)
        menu.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        menu.setFont(QApplication.font())
        if cur:
            menu.addAction("Save text as Snippet", self.save_snippet)
            menu.addAction("Save as Snippet #...", self.save_snippet_as_number)
        if (is_archive and idx < len(self.data.get("archive_temp_presets", [])) and self.data["archive_temp_presets"][idx]) or (not is_archive and idx < len(self.data["temp_presets"]) and self.data["temp_presets"][idx]):
            menu.addAction(f"Clear Silo {idx+1}", lambda: self.clear_temp(idx, is_archive))

        # Replace Silo submenu — shows all non-empty silos to copy text from
        presets = self.data["archive_temp_presets"] if is_archive else self.data["temp_presets"]
        replace_menu = menu.addMenu(f"Replace Silo {idx+1} from...")
        has_source = False
        for src_i, src_text in enumerate(presets):
            if src_i == idx or not src_text or not src_text.strip(): continue
            has_source = True
            label = src_text.strip().replace('\n', ' ')[:30] + ("…" if len(src_text.strip()) > 30 else "")
            act_label = f"Silo {src_i+1}: {label}"
            def make_replace(target_idx=idx, src_idx=src_i, archive=is_archive):
                def do_replace():
                    src_presets = self.data["archive_temp_presets"] if archive else self.data["temp_presets"]
                    src_presets[target_idx] = src_presets[src_idx]
                    self.mark_dirty()
                    self.refresh_temp_presets()
                    if target_idx == self.active_temp_slot:
                        self._set_plain_text_clean(self.text_area, src_presets[target_idx])
                return do_replace
            replace_menu.addAction(act_label, make_replace())
        if not has_source:
            replace_menu.setEnabled(False)

        self.ignore_focus_loss = True
        try:
            menu.exec(pos)
        finally:
            self.ignore_focus_loss = False
        self.activateWindow()

    def clear_temp(self, idx, is_archive=False):
        self.add_data_undo_state("Clear silo")
        self.play_sound("clear")
        if is_archive:
            self.data["archive_temp_presets"][idx] = ""
            if idx == self.active_temp_slot and getattr(self, 'active_is_archive', False): self.clear_text()
            self._trim_archive()
            self.refresh_archive_panel()
        else:
            self.data["temp_presets"][idx] = ""
            if idx == self.active_temp_slot and not getattr(self, 'active_is_archive', False): self.clear_text()
            self.refresh_temp_presets()
        self.mark_dirty()

    def archive_active_item(self):
        if getattr(self, 'editing_snippet', None):
            self.archive_active_snippet()
        else:
            self.archive_active_silo()

    def archive_active_snippet(self):
        self.add_data_undo_state("Archive snippet")
        cat = self.get_current_category()
        if not cat: return
        
        text = self.text_area.toPlainText().strip()
        if not text: return
        
        # If it's already an active silo/arcsilo, this function shouldn't do anything because
        # it is meant for Snippets. Wait, what if they press archive while on a Silo?
        if getattr(self, "active_is_archive", False):
            return
            
        # First, ensure we save the current editing state to the current category slot if it exists.
        if self.editing_snippet:
            self.save_snippet(silent=True)
            
        slots = self.data["categories"].get(cat, [])
        found_idx = -1
        for i, s in enumerate(slots):
            if s and s["text"] == text:
                found_idx = i
                break
                
        if found_idx == -1: return
        
        # Found it. Move it to archive_temp_presets
        item = slots[found_idx]
        if "archive_temp_presets" not in self.data:
            self.data["archive_temp_presets"] = []
            
        self.data["archive_temp_presets"].insert(0, item["text"])
        from PyQt6.QtGui import QTextDocument
        doc = QTextDocument()
        doc.setDefaultFont(self.text_area.font())
        doc.setPlainText(item["text"])
        self.archive_docs.insert(0, doc)
        
        slots[found_idx] = None
        
        self._trim_archive()
        self.mark_dirty()
        self.refresh_snippets_panel()
        self.refresh_archive_panel()
        self.cancel_editing()

    def convert_to_snippet(self):
        # Converts active silo to a snippet
        text = self.text_area.toPlainText().strip()
        if not text: return
        
        cat = self.get_current_category()
        if not cat: return
        
        slots = self.data["categories"][cat]
        if None not in slots: return
        
        self.add_data_undo_state("Convert silo to snippet")
        empty_idx = slots.index(None)
        
        name = text.replace('\n', ' ')[:22]
        if len(text) > 22: name += "..."
        import time
        slots[empty_idx] = {"name": name, "text": text, "last_edited": int(time.time())}
        
        idx = self.active_temp_slot
        if 0 <= idx < len(self.data["temp_presets"]):
            self.data["temp_presets"][idx] = ""
        self.clear_text()
        
        self.mark_dirty()
        self.refresh_snippets_panel()
        self.refresh_temp_presets()

    def archive_active_silo(self):
        idx = self.active_temp_slot
        
        # Prevent archiving if we are currently viewing an archived silo
        if getattr(self, 'active_is_archive', False): return
        
        text = self.text_area.toPlainText().strip()
        if not text: return
        
        self.data["temp_presets"][idx] = text
        self.add_data_undo_state("Archive silo")
        
        # Move to archive_temp_presets
        if "archive_temp_presets" not in self.data:
            self.data["archive_temp_presets"] = []
            
        self.data["archive_temp_presets"].insert(0, text)
        from PyQt6.QtGui import QTextDocument
        doc = QTextDocument()
        doc.setDefaultFont(self.text_area.font())
        doc.setPlainText(text)
        self.archive_docs.insert(0, doc)
        
        # Clear the silo
        self.data["temp_presets"][idx] = ""
        self._set_plain_text_clean(self.silo_docs[idx], "")
        self.clear_text()
        
        self._trim_archive()
        self.mark_dirty()
        self.refresh_archive_panel()
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

    def insert_divider_line(self):
        self.text_area.insertPlainText("\n---\n")

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
        QShortcut(QKeySequence("Ctrl+N"), self, context=Qt.ShortcutContext.ApplicationShortcut).activated.connect(self.select_empty_silo)
        QShortcut(QKeySequence("Ctrl+W"), self, context=Qt.ShortcutContext.ApplicationShortcut).activated.connect(self.insert_divider_line)
        QShortcut(QKeySequence("Ctrl+Z"), self, context=Qt.ShortcutContext.ApplicationShortcut).activated.connect(self.undo_action)
        QShortcut(QKeySequence("Ctrl+Y"), self, context=Qt.ShortcutContext.ApplicationShortcut).activated.connect(self.redo_action)
        QShortcut(QKeySequence("Ctrl+Shift+Z"), self, context=Qt.ShortcutContext.ApplicationShortcut).activated.connect(self.redo_action)
        for i in range(1, 11): 
            key_num = i % 10
            QShortcut(QKeySequence(f"F{i}"), self).activated.connect(lambda i=i: self.fire_shortcut(i))
            QShortcut(QKeySequence(f"Ctrl+{key_num}"), self).activated.connect(lambda i=i: self._switch_to_slot(i - 1))
            QShortcut(QKeySequence(f"Ctrl+Shift+{key_num}"), self).activated.connect(lambda i=i: self.fire_shortcut(i))
        QShortcut(QKeySequence("Ctrl+Q"), self).activated.connect(self.cycle_snap_corner)
        QShortcut(QKeySequence("Ctrl+Alt+Shift+Q"), self).activated.connect(self.quit_app)
        QShortcut(QKeySequence("Ctrl+E"), self).activated.connect(self.toggle_header_line)
        QShortcut(QKeySequence("Ctrl+B"), self).activated.connect(self.apply_bold_smart)

    def fire_shortcut(self, idx):
        self.play_sound("snippet")
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

    def show_quick_list(self):
        self.play_sound("tick")
        from fastprompter.ui.pie_menu import QuickListWidget
        w = QuickListWidget(self)
        w.show()

    def fire_global_snippet(self, idx):
        self.play_sound("snippet")
        cat = self.get_current_category()
        if not cat: return
        active = [s for s in self.data["categories"].get(cat, []) if s is not None]
        if 0 <= idx < len(active):
            self.auto_paste(active[idx]["text"])

    def fire_global_silo(self, idx):
        self.play_sound("silo")
        if 0 <= idx < len(self.data.get("temp_presets", [])):
            text = self.data["temp_presets"][idx]
            if text.strip():
                self.auto_paste(text)

    def fire_global_snippet_from_cat(self, cat, idx):
        self.play_sound("snippet")
        if not cat: return
        active_snippets = [s for s in self.data["categories"].get(cat, []) if s is not None]
        if 0 <= idx < len(active_snippets): self.auto_paste(active_snippets[idx]["text"])

    def cycle_snap_corner(self):
        screen = QApplication.screenAt(QCursor.pos())
        if screen is None:
            screen = QApplication.primaryScreen()
        if screen is None:
            return

        avail = screen.availableGeometry()
        
        # Clamp dimensions to not overflow
        w = min(960, avail.width())
        h = min(540, avail.height())
        self.resize(w, h)
        
        if getattr(self, '_snap_first_press', True):
            self.snap_index = 0
            self._snap_first_press = False
            
        corner_idx = self.snap_index % 4
        
        sw, sh = avail.width(), avail.height()
        QApplication.processEvents()
        fw = self.frameGeometry().width()
        fh = self.frameGeometry().height()
        corners = [(sw - fw, sh - fh), (0, sh - fh), (0, 0), (sw - fw, 0)]
        x, y = corners[corner_idx]
        self.move(avail.x() + x, avail.y() + y)
        
        self.snap_index = (self.snap_index + 1) % 4

    def cache_current_text(self):
        if hasattr(self, '_last_deleted_preset'):
            self._last_deleted_preset = None
        if hasattr(self, '_last_deleted_silo_data'):
            self._last_deleted_silo_data = None
        if getattr(self, "_suspend_cache", False): return
        if getattr(self, "_initializing_ui", False): return
        if getattr(self, "_cache_in_progress", False): return
        self._cache_in_progress = True
        try:
            current_text = self.text_area.toPlainText()
            if not self.editing_snippet:
                if 0 <= self.active_temp_slot < len(self.data["temp_presets"]):
                    old_text = self.data["temp_presets"][self.active_temp_slot]
                    self.data["temp_presets"][self.active_temp_slot] = current_text
                    if current_text != old_text:
                        self.mark_dirty()
                        self.silo_last_edited[self.active_temp_slot] = int(time.time())
                page_start = self.silo_page * self._visible_silos
                if page_start <= self.active_temp_slot < page_start + self._visible_silos:
                    view_idx = self.active_temp_slot - page_start
                    if view_idx < len(self.silo_buttons):
                        btn = self.silo_buttons[view_idx]
                        t = current_text.replace(chr(10),' ').strip()
                        display_idx = self.active_temp_slot + 1
                        label = f"{display_idx}: {t[:22]}…" if len(t)>22 else (f"{display_idx}: {t}" if t else str(display_idx))
                        btn.setText(label)
            else:
                cat, idx = self.editing_snippet
                if cat in self.data["categories"] and self.data["categories"][cat][idx]:
                    self.data["categories"][cat][idx]["text"] = current_text
                    if cat == self.get_current_category():
                        t = current_text.replace(chr(10), ' ').strip()
                        display_idx = idx + 1
                        label = f"{display_idx}: {t[:22]}…" if len(t) > 22 else (f"{display_idx}: {t}" if t else str(display_idx))
                        layout = getattr(self, 'snippets_widget', None)
                        if layout and hasattr(layout, 'layout'):
                            for i in range(layout.layout.count()):
                                item = layout.layout.itemAt(i)
                                if item and item.widget():
                                    widget = item.widget()
                                    main_btn = getattr(widget, 'main_btn', None)
                                    if main_btn and getattr(main_btn, 'cat', None) == cat and getattr(main_btn, 'global_idx', None) == idx:
                                        main_btn.setText(label)
                                        break
        finally:
            self._cache_in_progress = False
    

    @staticmethod
    def _set_plain_text_clean(target, text):
        doc = target.document() if hasattr(target, 'document') else target
        doc.setUndoRedoEnabled(False)
        doc.setPlainText(text)
        doc.setUndoRedoEnabled(True)

    def hide_and_save(self):
        self.save_data_to_db(force=True)
        if getattr(self, "is_locked", False):
            self.show()
            self.raise_()
            self.activateWindow()
            return
        self.hide()

    def quit_app(self):
        self.save_data_to_db(force=True)
        try:
            if hasattr(self, 'server') and self.server:
                self.server.close()
        except:
            pass
        try:
            if hasattr(self, 'conn') and self.conn:
                self.conn.close()
        except:
            pass
        try:
            if hasattr(self, 'tray_icon'):
                self.tray_icon.hide()
        except:
            pass
        QApplication.quit()



def setup_exception_hook():
    """Ensure unhandled exceptions are visible (written to crash.log and shown as MessageBox)."""
    import traceback
    old_hook = sys.excepthook
    def hook(typ, val, tb):
        error_msg = "".join(traceback.format_exception(typ, val, tb))
        crash_log = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "crash.log")
        try:
            with open(crash_log, "a") as f:
                f.write(error_msg + chr(10))
        except:
            pass
        ctypes.windll.user32.MessageBoxW(0, f"FastPrompter Error:" + chr(10)*2 + f"{error_msg}", "FastPrompter Error", 0x10)
        if old_hook:
            old_hook(typ, val, tb)
    sys.excepthook = hook

def main_entry():
    # Connect to existing instance or start new
    sock = try_connect_to_server()
    if sock:
        token = sock.property("ipc_token") or ""
        cmd = f"TOKEN:{token}|SHOW" if token else "SHOW"
        sock.write(cmd.encode())
        sock.flush()
        sock.disconnectFromServer()
        return
    
    setup_exception_hook()
    
    app = QApplication(sys.argv)
    global_font = QFont("Verdana", 10)
    global_font.setStyleStrategy(QFont.StyleStrategy.NoAntialias | QFont.StyleStrategy.NoSubpixelAntialias)
    app.setFont(global_font)
    app.setQuitOnLastWindowClosed(False)
    
    # Create and show window
    window = FastPrompter()
    window.show()
    
    # Install hotkey filter for global hotkeys
    filter_obj = HotkeyFilter(window)
    app.installNativeEventFilter(filter_obj)
    
    sys.exit(app.exec())

if __name__ == "__main__":
    main_entry()
