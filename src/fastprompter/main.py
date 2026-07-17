import copy
import ctypes
import ctypes.wintypes
import math
import os
import re
import shutil
import sys
import time

from PyQt6 import sip
from PyQt6.QtCore import (
    QEvent,
    Qt,
    QTimer,
)
from PyQt6.QtGui import (
    QColor,
    QCursor,
    QFont,
    QKeySequence,
    QShortcut,
    QTextCharFormat,
    QTextCursor,
    QTextDocument,
    QTextOption,
)
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QTabBar,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

user32 = ctypes.windll.user32
user32.RegisterHotKey.argtypes = [
    ctypes.wintypes.HWND,
    ctypes.c_int,
    ctypes.wintypes.UINT,
    ctypes.wintypes.UINT,
]
user32.RegisterHotKey.restype = ctypes.wintypes.BOOL
user32.UnregisterHotKey.argtypes = [ctypes.wintypes.HWND, ctypes.c_int]
user32.UnregisterHotKey.restype = ctypes.wintypes.BOOL

from fastprompter.core.hotkey_filter import HotkeyFilter
from fastprompter.core.ipc_server import IpcServer, try_connect_to_server
from fastprompter.core.sound_manager import SoundManager
from fastprompter.core.state import FastPrompterState
from fastprompter.theme.themes import THEMES
from fastprompter.ui.editor import VaultTextEdit
from fastprompter.ui.formatting_mixin import FormattingMixin
from fastprompter.ui.help_dialog import HelpDialog
from fastprompter.ui.hotkey_mixin import HotkeyMixin
from fastprompter.ui.markdown_highlighter import MarkdownHighlighter
from fastprompter.ui.pie_menu import QuickListWidget
from fastprompter.ui.resizers import EdgeResizer
from fastprompter.ui.scaling_mixin import ScalingMixin
from fastprompter.ui.search_mixin import SearchMixin
from fastprompter.ui.settings import ColorConfigDialog, HotkeySettingsDialog
from fastprompter.ui.snippet_ops_mixin import SnippetOpsMixin
from fastprompter.ui.snippet_panel import (
    DraggableSiloButton,
    DropVerticalWidget,
    SiloDropWidget,
    SnippetWidget,
    WheelPager,
)
from fastprompter.ui.theme_mixin import ThemeMixin
from fastprompter.ui.tray_mixin import TrayMixin
from fastprompter.ui.window_mixin import WindowMixin
from fastprompter.utils.paths import get_data_dir


class FastPrompter(
    QMainWindow,
    FormattingMixin,
    HotkeyMixin,
    ScalingMixin,
    SearchMixin,
    SnippetOpsMixin,
    ThemeMixin,
    TrayMixin,
    WindowMixin,
):
    # Live settings accessors used by the UI mixins.
    @property
    def _font_size(self):
        try:
            return int(float(self.data.get("font_size", 11)))
        except Exception:
            return 11

    @property
    def _font_family(self):
        return self.data.get("font_family", "Verdana")

    @property
    def _ui_scale(self):
        try:
            return float(self.data.get("ui_scale", 1.0))
        except Exception:
            return 1.0

    @property
    def _button_scale(self):
        try:
            return float(self.data.get("button_scale", 1.0))
        except Exception:
            return 1.0

    @property
    def _sidebar_right(self):
        return self.data.get("sidebar_right", "False") == "True"

    @property
    def _always_on_top(self):
        return self.data.get("always_on_top", "True") == "True"

    @property
    def _normal_window(self):
        return self.data.get("normal_window", "False") == "True"

    @property
    def _tray_visible(self):
        return self.data.get("tray_visible", "True") == "True"

    def _refresh_settings_cache(self):
        """Settings are read live from self.data via properties; nothing to refresh."""

    def __init__(self):
        super().__init__()
        self.setMouseTracking(True)
        # QApplication.instance().installEventFilter(self)
        self.ignore_focus_loss, self.registered_hotkeys, self._db_dirty = False, [], False

        self.editing_snippet = None
        self.auto_save_timer = QTimer(self)
        self.auto_save_timer.timeout.connect(self._auto_save_tick)
        self.auto_save_timer.start(10000)

        self.snap_index, self._snap_first_press, self._preview_connected = 0, True, False
        self.current_pages, self.silo_page, self.ui_scale = {}, 0, 1.0
        self.arc_silo_page, self.arc_page = 0, 0
        self.is_locked, self._suspend_cache, self._locked_geometry = False, False, None
        self._initializing_ui, self._suspend_temp_sync = True, True

        self.silo_last_edited = {}  # {slot_index: timestamp} for color-last-edited system
        self._visible_silos = 10  # dynamically adjusted
        self._snippet_widget_cache = {}  # {(cat, idx): widget} for O(1) lookup

        self.setup_single_instance_server()
        self.state = FastPrompterState()
        self.data = self.state.data
        self.conn = self.state.conn
        self.sound_manager = SoundManager(self, self.data)
        self._theme_cache, self._theme_cache_name = THEMES["Default"], None
        self._custom_colors_cache, self._custom_colors_cache_key = {}, None
        self._font_cache_key, self._cached_main_font = None, None
        try:
            self.active_temp_slot = int(self.data.get("active_temp_slot", 0))
        except Exception:
            self.active_temp_slot = 0
        # Per-category pins/last-edited stores (aliased per tab like
        # temp_presets_all); migrate the old flat keys into the first tab.
        first_cat = (self.data.get("cats_order") or ["Code"])[0]
        pall = self.data.get("pinned_silos_all")
        if not isinstance(pall, dict):
            pall = {}
        if not pall and isinstance(self.data.get("pinned_silos"), list) and self.data["pinned_silos"]:
            pall[first_cat] = list(self.data["pinned_silos"])
        self.data["pinned_silos_all"] = pall
        eall = self.data.get("silo_last_edited_all")
        if not isinstance(eall, dict):
            eall = {}
        if not eall and self.data.get("silo_last_edited"):
            eall[first_cat] = self.data["silo_last_edited"]
        norm = {}
        for c, d in eall.items():
            try:
                norm[c] = {int(k): int(v) for k, v in d.items()}
            except Exception:
                norm[c] = {}
        self.data["silo_last_edited_all"] = norm
        self.silo_last_edited = norm.setdefault(first_cat, {})
        self.data["pinned_silos"] = pall.setdefault(first_cat, [])
        tall = self.data.get("silo_ticked_all")
        if not isinstance(tall, dict):
            tall = {}
        if not tall and isinstance(self.data.get("silo_ticked"), list) and self.data["silo_ticked"]:
            tall[first_cat] = list(self.data["silo_ticked"])
        self.data["silo_ticked_all"] = tall
        self.data["silo_ticked"] = tall.setdefault(first_cat, [])

        self.init_ui()
        self.init_tray()
        self.setup_global_shortcuts()
        self._apply_tooltips()
        # Delay global hotkey binding until after UI initialization to prevent race conditions causing silent crashes (Debater Constraint)
        QTimer.singleShot(100, lambda: not sip.isdeleted(self) and self.register_all_hotkeys())

        self._switch_to_slot(self.active_temp_slot, initial=True)
        self._initializing_ui, self._suspend_temp_sync = False, False
        self.apply_font()
        self.apply_theme()

        self.topmost_timer = QTimer(self)
        self.topmost_timer.timeout.connect(self.enforce_topmost)
        if self.data.get("always_on_top", "True") == "True":
            self.topmost_timer.start(30000)

        self.date_timer = QTimer(self)
        self.date_timer.timeout.connect(self._update_date_label)
        self.date_timer.start(1000)
        self._update_date_label()

        self.place_window()

    def _update_date_label(self):
        if hasattr(self, "analog_clock"):
            self.analog_clock.sync()
        show_date = self.data.get("show_date_rect", "True") == "True"
        if not show_date:
            self.lbl_date.setVisible(False)
            return
            
        self.lbl_date.setVisible(True)
        import datetime
        now = datetime.datetime.now()
        # Narrow windows (Ctrl+Q quarter snap) degrade gracefully:
        win_w = self.width()
        show_secs = self.data.get("date_seconds", "True") == "True" and win_w >= 1000
        show_word = self.data.get("date_daypart", "True") == "True" and win_w >= 1200
        text_month = self.data.get("date_text_month", "False") == "True"
        m_fmt = "%d %b" if text_month else "%d.%m"
        if show_secs:
            dt_str = now.strftime(f"{m_fmt} - %H:%M:%S")
            ref_str = "00 MMM - 00:00:00" if text_month else "00.00 - 00:00:00"
        else:
            dt_str = now.strftime(f"{m_fmt} - %H:%M")
            ref_str = "00 MMM - 00:00" if text_month else "00.00 - 00:00"
        if show_word:
            dt_str += f" · {self._day_part(now.hour)}"
            ref_str += " · Morning"

        from PyQt6.QtGui import QFontMetrics
        fm = QFontMetrics(self.lbl_date.font())
        needed_width = fm.horizontalAdvance(ref_str) + 8
        if self.lbl_date.minimumWidth() != needed_width:
            self.lbl_date.setMinimumWidth(needed_width)
            self.lbl_date.setMaximumWidth(needed_width + 8)
            from PyQt6.QtCore import Qt
            self.lbl_date.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.lbl_date.setText(dt_str)

    # (button, normal label, dense label) — dense squeezes into a
    # Ctrl+Q quarter-FullHD window without hiding anything
    _DENSE_LABELS = (
        ("btn_new", "NEW", "NEW"),
        ("btn_save", "Save", "Save"),
        ("btn_clear_fmt", "Clear Fmt", "CF"),
        ("btn_add_line", "Line", "Line"),
        ("btn_copy", "Copy", "Copy"),
        ("btn_clear", "Clear", "Clear"),
        ("btn_home", "Home", "⇤"),
        ("btn_end", "End", "⇥"),
    )

    def _apply_header_density(self):
        """Pack the header for small windows (Ctrl+Q quarter-FullHD and
        below): hard-clamp text-button widths to their label, shorten the
        widest labels, and let the date clock degrade (day word first,
        then seconds). Nothing gets hidden — only tightened."""
        w = self.width()
        dense = w < 1280
        flipped = getattr(self, "_header_dense", None) != dense
        if flipped:
            self._header_dense = dense
            self.header_layout.setSpacing(1 if dense else 2)

        def _dense_font(widget):
            # shrink to 10px while dense; remember the original for restore
            if dense:
                if not hasattr(widget, "_pre_dense_font"):
                    widget._pre_dense_font = QFont(widget.font())
                f = QFont(widget.font())
                f.setPixelSize(10)
                widget.setFont(f)
            elif flipped and hasattr(widget, "_pre_dense_font"):
                widget.setFont(widget._pre_dense_font)
                del widget._pre_dense_font

        # widths recompute every pass while dense — the font can change
        # after the flag flips (scale/theme), stale metrics overshoot
        for name, normal, short in self._DENSE_LABELS:
            btn = getattr(self, name, None)
            if btn is None or sip.isdeleted(btn):
                continue
            if flipped:
                btn.setText(short if dense else normal)
            _dense_font(btn)
            if dense:
                btn.setFixedWidth(btn.fontMetrics().horizontalAdvance(btn.text()) + 8)
            elif flipped:
                btn.setMinimumWidth(0)
                btn.setMaximumWidth(16777215)
        for name in ("btn_bullet_toggle", "btn_files"):
            bt = getattr(self, name, None)
            if bt is None or sip.isdeleted(bt):
                continue
            _dense_font(bt)
            if dense:
                bt.setFixedWidth(bt.fontMetrics().horizontalAdvance(bt.text()) + 8)
            elif flipped:
                bt.setMinimumWidth(0)
                bt.setMaximumWidth(16777215)
        for name in ("lbl_date", "lbl_line_count"):
            lbl = getattr(self, name, None)
            if lbl is not None and not sip.isdeleted(lbl):
                _dense_font(lbl)
        if flipped:
            self._update_date_label()
        import os as _os
        if _os.environ.get("FP_DENSITY_DEBUG"):
            print("DENSITY dense=", dense, "flipped=", flipped,
                  "save px=", self.btn_save.font().pixelSize(),
                  "save minW=", self.btn_save.minimumWidth())
        if flipped:
            # format squares squeeze 24 -> 20 in dense
            for name in ("btn_bold", "btn_italic", "btn_under", "btn_strike",
                         "btn_header", "btn_settings_toggle", "btn_help"):
                btn = getattr(self, name, None)
                if btn is None or sip.isdeleted(btn):
                    continue
                if dense:
                    btn.setFixedSize(20, 20)
                else:
                    self.apply_button_size(btn, 24, 24)
            # tabs scroll inside a bounded strip when space is tight
            # (inline QSS re-enables the scroller arrows the theme hides)
            if hasattr(self, "tab_bar"):
                if dense:
                    self.tab_bar.setStyleSheet("QTabBar::scroller { width: 14px; }")
                    self.tab_bar.setMinimumWidth(90)
                    self.tab_bar.setMaximumWidth(150)
                else:
                    self.tab_bar.setStyleSheet("")
                    self.tab_bar.setMinimumWidth(0)
                    self.tab_bar.setMaximumWidth(16777215)
            if hasattr(self, "lbl_date"):
                self.lbl_date.setStyleSheet(
                    "padding: 0 1px;" if dense else "padding: 0 4px;")
        if flipped or getattr(self, "_last_density_width", None) != w:
            self._last_density_width = w
            self._update_date_label()
            self._update_line_count_label()

    @staticmethod
    def _day_part(hour):
        """Word for the time of day shown in the date widget."""
        if 5 <= hour < 12:
            return "Morning"
        if 12 <= hour < 17:
            return "Day"
        if 17 <= hour < 23:
            return "Evening"
        return "Night"

    def toggle_hide_on_clickout(self):
        """Alt+A: flip the Hide on Click-Out behavior from anywhere."""
        if hasattr(self, "cb_focus"):
            self.cb_focus.setChecked(not self.cb_focus.isChecked())
            self.play_tick_sound()

    def _pin_top_toggled(self, checked):
        """Header 📌 mirrors the Always-on-Top setting checkbox."""
        if hasattr(self, "cb_top") and self.cb_top.isChecked() != checked:
            self.cb_top.setChecked(checked)  # cb_top's handler does the work
        else:
            self.toggle_aot(checked)

    def _line_nums_btn_toggled(self, checked):
        """Header # mirrors the Line Numbers setting checkbox."""
        if hasattr(self, "cb_line_numbers") and self.cb_line_numbers.isChecked() != checked:
            self.cb_line_numbers.setChecked(checked)
        else:
            self.on_line_numbers_toggled(checked)

    def _files_root(self):
        custom = (self.data.get("files_root") or "").strip()
        if custom and os.path.isdir(custom):
            return custom
        from fastprompter.utils.paths import get_data_dir
        return os.path.join(get_data_dir(), "files")

    def pick_files_root(self):
        """Settings: let the user choose where silo file containers live."""
        from PyQt6.QtWidgets import QFileDialog
        start = self._files_root()
        path = QFileDialog.getExistingDirectory(self, "Folder for silo files", start)
        if path:
            self.data["files_root"] = path
            self.mark_dirty()
            self._update_files_button()
            self.refresh_temp_presets()

    def reset_files_root(self):
        self.data["files_root"] = ""
        self.mark_dirty()
        self._update_files_button()
        self.refresh_temp_presets()

    def add_files_to_active_silo(self, paths):
        """Drop target helper: put files into the active silo's container
        and show the drawer so the user sees where they landed."""
        is_archive = getattr(self, "active_is_archive", False)
        self.open_file_container(is_archive=is_archive)
        self._file_container.import_paths(paths)

    def _update_files_button(self):
        """Refresh the header 📁 button: live file count + breakdown tooltip."""
        if not hasattr(self, "btn_files"):
            return
        from fastprompter.ui.file_container import folder_summary, silo_file_count
        is_archive = getattr(self, "active_is_archive", False)
        presets = self.data.get("archive_temp_presets" if is_archive else "temp_presets", [])
        idx = self.active_temp_slot
        text = presets[idx] if 0 <= idx < len(presets) else ""
        cat = self.get_current_category()
        n = silo_file_count(self._files_root(), cat, text)
        self.btn_files.setText(f"📁{n}" if n else "📁")
        if getattr(self, "_header_dense", False):
            self.btn_files.setFixedWidth(
                self.btn_files.fontMetrics().horizontalAdvance(self.btn_files.text()) + 8)
        self.btn_files.setToolTip(
            "Files — asset drawer for the active silo (drop in / drag out /\n"
            "preview / export; plain folder in data/files)\n\n"
            + folder_summary(self._files_root(), cat, text)
        )

    def open_file_container(self, global_idx=None, is_archive=False):
        """Open the per-silo file drawer (📁 button / silo hover button)."""
        from fastprompter.ui.file_container import FileContainerPanel
        if global_idx is None:
            global_idx = self.active_temp_slot
            is_archive = getattr(self, "active_is_archive", False)
        presets = self.data.get("archive_temp_presets" if is_archive else "temp_presets", [])
        text = presets[global_idx] if 0 <= global_idx < len(presets) else ""
        if getattr(self, "_file_container", None) is None:
            self._file_container = FileContainerPanel(self)
        self._file_container.open_for(self._files_root(), self.get_current_category(), text)

    def _begin_batch_update(self):
        """Suppress paints + snapshot overlay as backup."""
        self.setUpdatesEnabled(False)
        snap = self.left_panel.grab()
        self._sidebar_snap = QLabel(self.left_panel)
        self._sidebar_snap.setPixmap(snap)
        self._sidebar_snap.setGeometry(self.left_panel.rect())
        self._sidebar_snap.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._sidebar_snap.show()
        self._sidebar_snap.raise_()

    def _end_batch_update(self):
        """Re-enable paints — naturally batched by Qt's backing store."""
        if hasattr(self, "_sidebar_snap") and self._sidebar_snap is not None:
            self._sidebar_snap.hide()
            self._sidebar_snap.deleteLater()
            self._sidebar_snap = None
        self.setUpdatesEnabled(True)

    def mark_dirty(self):
        self.state.mark_dirty()

    def _auto_save_tick(self):
        if not getattr(self.state, "_db_dirty", False):
            return
        self.save_data_to_db()

    def play_sound(self, name):
        self.sound_manager.play(name)

    def play_click_sound(self):
        self.sound_manager.play_click()

    def play_tick_sound(self):
        self.sound_manager.play_tick()

    def _deferred_silo_refresh(self):
        """Called once after the window layout is computed to set correct silo count."""
        if hasattr(self, "silos_widget") and self.silos_widget.height() > 0:
            self._update_visible_silo_count()
            self.refresh_temp_presets()
        else:
            # Layout not ready yet, try again
            QTimer.singleShot(50, lambda: not sip.isdeleted(self) and self._deferred_silo_refresh())

    def _update_visible_silo_count(self):
        if hasattr(self, "silos_widget") and self.silos_widget.height() > 0:
            # Estimate button height from the first visible button, fallback to 24*scale
            estimate = 24
            for btn in getattr(self, "silo_buttons", []):
                if btn.isVisible():
                    bh = btn.height()
                    if bh > 0:
                        estimate = bh
                    break
            spacing = 2
            self._visible_silos = max(
                1, (self.silos_widget.height() + spacing) // (estimate + spacing)
            )
        else:
            self._visible_silos = 10

    def setup_single_instance_server(self):
        self.ipc = IpcServer(self.show_window)
        self.ipc.setup()

    # init_db removed, moved to FastPrompterState

    def get_current_context_key(self):
        if getattr(self, "editing_snippet", None):
            cat, idx = self.editing_snippet
            return f"snippet:{cat}:{idx}"
        else:
            return f"silo:{self.active_temp_slot}"

    def save_data_to_db(self, force=False):
        if hasattr(self, "text_area"):
            cached = getattr(self, "_last_cached_text", None)
            current_text = self.text_area.toPlainText() if cached is None else cached
            self._last_cached_text = None
        else:
            current_text = self.data.get("last_text", "")
        self._last_saved_text = current_text

        if (
            not getattr(self, "_suspend_cache", False)
            and not getattr(self, "_initializing_ui", False)
            and not getattr(self, "_suspend_temp_sync", False)
            and not self.editing_snippet
        ):
            if 0 <= self.active_temp_slot < len(self.data["temp_presets"]):
                self.data["temp_presets"][self.active_temp_slot] = current_text

        self.data["window_locked"] = "True" if getattr(self, "is_locked", False) else "False"

        ui_settings = {
            "last_tab_idx": str(self.data["last_tab_idx"]),
            "active_temp_slot": str(self.active_temp_slot),
            "last_geometry": self.data.get("last_geometry", ""),
            "font_size": str(self.font_spin.value())
            if hasattr(self, "font_spin")
            else str(self.data.get("font_size", 11)),
            "preview_mode": self.preview_combo.currentText()
            if hasattr(self, "preview_combo")
            else self.data.get("preview_mode", "None"),
            "paste_mode": self.data.get("paste_mode", "Plain"),
            "tray_visible": str(self.cb_tray.isChecked())
            if hasattr(self, "cb_tray")
            else self.data.get("tray_visible", "True"),
            "close_on_focus_loss": str(self.cb_focus.isChecked())
            if hasattr(self, "cb_focus")
            else self.data.get("close_on_focus_loss", "True"),
            "ctrl_c_closes": str(self.cb_ctrl_c.isChecked())
            if hasattr(self, "cb_ctrl_c")
            else self.data.get("ctrl_c_closes", "True"),
            "silo_last_edited": getattr(self, "silo_last_edited", {}),
        }

        self.state.save_data_to_db(current_text, ui_settings, force=force)

    def init_ui(self):
        flags = Qt.WindowType.Window
        if self.data.get("normal_window", "False") != "True":
            flags |= Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool
        if self.data.get("always_on_top", "True") == "True":
            flags |= Qt.WindowType.WindowStaysOnTopHint
        self.setWindowFlags(flags)
        self.setWindowTitle("FastPrompter")
        self.setMinimumSize(480, 320)

        self.setMouseTracking(True)
        self._initializing_ui, self._suspend_temp_sync = True, True

        self._resizers = {
            "left": EdgeResizer(self, "left"),
            "right": EdgeResizer(self, "right"),
            "top": EdgeResizer(self, "top"),
            "bottom": EdgeResizer(self, "bottom"),
            "topleft": EdgeResizer(self, "topleft"),
            "topright": EdgeResizer(self, "topright"),
            "bottomleft": EdgeResizer(self, "bottomleft"),
            "bottomright": EdgeResizer(self, "bottomright"),
        }

        central = QWidget()
        self.setCentralWidget(central)
        self.main_layout = QVBoxLayout(central)
        self.main_layout.setContentsMargins(2, 2, 2, 2)
        self.main_layout.setSpacing(2)

        self.header_widget = QWidget()
        self.header_layout = QHBoxLayout(self.header_widget)
        self.header_layout.setContentsMargins(0, 0, 0, 0)
        self.header_layout.setSpacing(2)

        self.btn_sidebar_toggle = QPushButton("☰")
        self.apply_button_size(self.btn_sidebar_toggle, 24, 24)
        self.btn_sidebar_toggle.setToolTip(
            "Toggle Sidebar (Alt+D)\nShow or hide the right/left sidebar containing snippets and silos."
        )
        self.btn_sidebar_toggle.clicked.connect(self.toggle_sidebar_visibility)
        self.header_layout.addWidget(self.btn_sidebar_toggle)

        self.tab_bar = QTabBar()
        self.tab_bar.setExpanding(False)
        # Scroll buttons only appear when tabs truly overflow; without them
        # the tab bar's minimum width is the sum of ALL tabs, which alone
        # breaks packing into a Ctrl+Q quarter-FullHD window.
        self.tab_bar.setUsesScrollButtons(True)
        self.tab_bar.setElideMode(Qt.TextElideMode.ElideRight)
        for cat in self.data["cats_order"]:
            self.tab_bar.addTab(cat)
        self.tab_bar.currentChanged.connect(self.on_tab_changed)

        self.btn_add_tab = QPushButton("+")
        self.apply_button_size(self.btn_add_tab, 24)
        self.btn_add_tab.setToolTip("Add Tab\nCreate a new custom category tab for snippets.")
        self.btn_add_tab.clicked.connect(self.add_category)

        self.btn_del_tab = QPushButton("-")
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
        self.btn_add_line.setToolTip(
            "Insert Line (Ctrl+W)\nInsert a spaced --- divider and start a fresh bullet."
        )
        self.apply_button_size(self.btn_add_line, 24)
        self.btn_add_line.clicked.connect(self.insert_add_line)

        self.btn_bullet_toggle = QPushButton("-→•")
        self.apply_button_size(self.btn_bullet_toggle, 24)
        self.btn_bullet_toggle.setCheckable(True)
        self.btn_bullet_toggle.setChecked(self.data.get("auto_bullet", "False") == "True")

        def _bullet_mousePress(event):
            if event.button() == Qt.MouseButton.RightButton:
                curr = self.data.get("auto_bullet", "False") == "True"
                new_state = not curr
                self.data["auto_bullet"] = "True" if new_state else "False"
                self.btn_bullet_toggle.setChecked(new_state)
                self.mark_dirty()
                self.play_click_sound()
                state_str = "ON" if new_state else "OFF"
                self.btn_bullet_toggle.setToolTip(f"Auto-Bullet (Right-Click): {state_str}\nLeft-Click: Convert selected lines between dashes and bullets.")
                event.accept()
            else:
                QPushButton.mousePressEvent(self.btn_bullet_toggle, event)

        self.btn_bullet_toggle.mousePressEvent = _bullet_mousePress
        
        def _on_bullet_left_click():
            # Left click naturally toggles the checked state, revert it to actual auto_bullet mode.
            self.btn_bullet_toggle.setChecked(self.data.get("auto_bullet", "False") == "True")
            self.toggle_bullet_conversion()

        state_str = "ON" if self.data.get("auto_bullet", "False") == "True" else "OFF"
        self.btn_bullet_toggle.setToolTip(f"Auto-Bullet (Right-Click): {state_str}\nLeft-Click: Convert selected lines between dashes and bullets.")
        self.btn_bullet_toggle.clicked.connect(_on_bullet_left_click)

        self.btn_bold = QPushButton("B")
        self.btn_bold.setToolTip("Bold (Ctrl+B)\nMake selected text bold.")
        self.apply_button_size(self.btn_bold, 24, 24)
        f = QFont(self.btn_bold.font()); f.setBold(True); self.btn_bold.setFont(f)
        self.btn_bold.clicked.connect(lambda: self.apply_format("bold"))

        self.btn_italic = QPushButton("I")
        self.btn_italic.setToolTip("Italic (Ctrl+I)\nMake selected text italic.")
        self.apply_button_size(self.btn_italic, 24, 24)
        f = QFont(self.btn_italic.font()); f.setItalic(True); self.btn_italic.setFont(f)
        self.btn_italic.clicked.connect(lambda: self.apply_format("italic"))

        self.btn_under = QPushButton("U")
        self.btn_under.setToolTip("Underline (Ctrl+U)\nMake selected text underlined.")
        self.apply_button_size(self.btn_under, 24, 24)
        f = QFont(self.btn_under.font()); f.setUnderline(True); self.btn_under.setFont(f)
        self.btn_under.clicked.connect(lambda: self.apply_format("underline"))

        self.btn_strike = QPushButton("S")
        self.btn_strike.setToolTip("Strikethrough (Ctrl+T)\nCross out selected text.")
        self.apply_button_size(self.btn_strike, 24, 24)
        f = QFont(self.btn_strike.font()); f.setStrikeOut(True); self.btn_strike.setFont(f)
        self.btn_strike.clicked.connect(lambda: self.apply_format("strike"))

        self.btn_header = QPushButton("H")
        self.btn_header.setToolTip(
            "Header (Ctrl+E)\nTitle the line: # + bold + underline + timestamp,\n"
            "then land 2 lines below on a fresh bullet."
        )
        self.apply_button_size(self.btn_header, 24, 24)
        f = QFont(self.btn_header.font()); f.setBold(True); f.setUnderline(True); self.btn_header.setFont(f)
        self.btn_header.clicked.connect(self.apply_header_timestamp)

        self.btn_clear_fmt = QPushButton("Clear Fmt")
        self.btn_clear_fmt.setToolTip("Clear Format\nRemove all explicit font styling from text.")
        self.apply_button_size(self.btn_clear_fmt, 24)
        self.btn_clear_fmt.clicked.connect(self.clear_formatting)



        self.btn_settings_toggle = QPushButton("⚙")
        self.apply_button_size(self.btn_settings_toggle, 24, 24)
        self.btn_settings_toggle.setToolTip(
            "Settings\nConfigure hotkeys, theme, fonts, and UI scaling."
        )
        self.btn_settings_toggle.clicked.connect(self.toggle_mini_settings)

        self.btn_help = QPushButton("❓")
        self.btn_help.setToolTip("Help — every hotkey, gesture and feature (click)")
        self.btn_help.setCursor(Qt.CursorShape.PointingHandCursor)
        self.apply_button_size(self.btn_help, 24, 24)
        self.btn_help.clicked.connect(self.open_help_dialog)

        self.btn_copy = QPushButton("Copy")
        self.btn_copy.setToolTip("Copy all text (Ctrl+C)\nRight-click: Copy + Close FastPrompter")
        self.apply_button_size(self.btn_copy, 26)
        self.btn_copy.clicked.connect(self.copy_context_to_clipboard)
        self.btn_copy.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.btn_copy.customContextMenuRequested.connect(self.copy_context_and_close)

        self.btn_clear = QPushButton("Clear")
        self.btn_clear.setToolTip("Clear (Ctrl+Shift+C)")
        self.apply_button_size(self.btn_clear, 26)
        self.btn_clear.clicked.connect(self.clear_text)

        self.btn_files = QPushButton("📁")
        self.btn_files.setToolTip(
            "Files\nAsset drawer for the active silo: drop any files in,\n"
            "drag them out, preview, export. Stored as a plain folder\n"
            "in data/files — readable outside FastPrompter."
        )
        self.apply_button_size(self.btn_files, 24)
        self.btn_files.clicked.connect(lambda: self.open_file_container())



        # Navigation
        self.header_layout.addWidget(self.tab_bar)
        self.header_layout.addWidget(self.btn_add_tab)
        self.header_layout.addWidget(self.btn_del_tab)
        self.header_layout.addWidget(self.btn_new)
        self.header_layout.addWidget(self.btn_save)

        # Cursor nav sits next to New/Save (used together while writing)
        self.header_layout.addWidget(self.btn_home)
        self.header_layout.addWidget(self.btn_end)

        # Formatting and editing
        self.header_layout.addStretch(1)
        self.header_layout.addWidget(self.btn_bold)
        self.header_layout.addWidget(self.btn_italic)
        self.header_layout.addWidget(self.btn_under)
        self.header_layout.addWidget(self.btn_strike)
        self.header_layout.addWidget(self.btn_header)
        self.header_layout.addWidget(self.btn_clear_fmt)
        self.header_layout.addWidget(self.btn_add_line)
        self.header_layout.addWidget(self.btn_bullet_toggle)
        self.header_layout.addWidget(self.btn_copy)
        self.header_layout.addWidget(self.btn_clear)
        self.header_layout.addWidget(self.btn_files)

        # Status cluster (right): clock | pins | line counter | settings
        self.header_layout.addStretch(1)
        from fastprompter.ui.analog_clock import MiniAnalogClock
        self.analog_clock = MiniAnalogClock(self)
        self.analog_clock.setToolTip("Current time (analog)")
        self.header_layout.addWidget(self.analog_clock)

        self.lbl_date = QLabel("")
        self.lbl_date.setToolTip("Current Date and Time")
        self.lbl_date.setStyleSheet("padding: 0 4px;")
        self.header_layout.addWidget(self.lbl_date)

        self.btn_pin_top = QPushButton("📌")
        self.btn_pin_top.setCheckable(True)
        self.btn_pin_top.setChecked(self.data.get("always_on_top", "True") == "True")
        self.btn_pin_top.setToolTip("Always on Top — keep the window above all others")
        self.apply_button_size(self.btn_pin_top, 20, 20)
        self.btn_pin_top.toggled.connect(self._pin_top_toggled)
        self.header_layout.addWidget(self.btn_pin_top)

        self.btn_line_nums = QPushButton("#")
        self.btn_line_nums.setCheckable(True)
        self.btn_line_nums.setChecked(self.data.get("show_line_numbers", "False") == "True")
        self.btn_line_nums.setToolTip(
            "Show / hide the line-number gutter\n(click the gutter to place colored margin marks)")
        self.apply_button_size(self.btn_line_nums, 20, 20)
        self.btn_line_nums.toggled.connect(self._line_nums_btn_toggled)
        self.header_layout.addWidget(self.btn_line_nums)

        self._counter_sep = QFrame()
        self._counter_sep.setFrameShape(QFrame.Shape.VLine)
        self._counter_sep.setFixedHeight(16)
        self.header_layout.addWidget(self._counter_sep)

        self.lbl_line_count = QLabel("")
        self.lbl_line_count.setToolTip("Line count of the open silo/snippet")
        self.lbl_line_count.setStyleSheet("padding: 0 4px; font-weight: bold;")
        self.header_layout.addWidget(self.lbl_line_count)
        self.header_layout.addWidget(self.btn_settings_toggle)
        self.header_layout.addWidget(self.btn_help)
        self.main_layout.addWidget(self.header_widget)

        self.mini_settings_frame = QFrame(self)
        self.mini_settings_frame.setVisible(False)

        self.font_combo = QComboBox()
        self.font_combo.addItems(
            [
                "Verdana",
                "Tahoma",
                "Consolas",
                "Calibri",
                "Times New Roman",
                "Arial",
                "Segoe UI",
                "Courier New",
            ]
        )
        saved_font = self.data.get("font_family", "Verdana")
        idx = self.font_combo.findText(saved_font)
        if idx >= 0:
            self.font_combo.setCurrentIndex(idx)
        self.font_combo.currentTextChanged.connect(self.change_font_family)

        self.font_spin = QSpinBox()
        self.font_spin.setRange(6, 48)
        try:
            self.font_spin.setValue(int(self.data.get("font_size", "11")))
        except Exception:
            self.font_spin.setValue(11)
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
        if idx < 0:
            idx = 1  # default to Live Preview
        self.preview_combo.setCurrentIndex(idx)
        self.preview_combo.currentIndexChanged.connect(self.change_preview_mode)

        self.cb_theme = QComboBox()
        self.cb_theme.addItems(
            [
                "Default",
                "Golden Vintage",
                "Golden Default",
                "Vintage Dark",
                "Vintage Classic",
                "Dark 2 (OLED)",
                "Custom",
            ]
        )
        saved_theme = self.data.get("theme", "Default")
        idx = self.cb_theme.findText(saved_theme)
        if idx >= 0:
            self.cb_theme.setCurrentIndex(idx)
        self.cb_theme.currentTextChanged.connect(self.change_theme)

        # Removed broken preset_combo — it didn't work

        def make_action_checkbox(text, callback):
            cb = QCheckBox(text)

            def on_toggled(checked):
                if checked:
                    self.play_tick_sound()
                    callback()
                    cb.blockSignals(True)
                    cb.setChecked(False)
                    cb.blockSignals(False)

            cb.toggled.connect(on_toggled)
            return cb

        self.btn_hotkeys = make_action_checkbox("Keys", self.open_hotkey_settings)
        self.btn_hotkeys.setToolTip("Configure Global Hotkeys (Settings Cog)")
        self.btn_colors = make_action_checkbox("RGB", self.open_color_settings)
        self.btn_colors.setToolTip("Custom Theme Colors (Color Palette)")
        self.btn_backup = make_action_checkbox("BkUp", self.backup_db)
        self.btn_restore = make_action_checkbox("Rstr", self.restore_db)

        try:
            current_scale_pct = int(float(self.data.get("ui_scale", "1.0")) * 100)
        except Exception:
            current_scale_pct = 100
        self.btn_button_scale = make_action_checkbox(
            f"Scale: {current_scale_pct}%", self.cycle_button_scale
        )
        self.btn_button_scale.setToolTip(
            "Scale the whole program: 50 / 75 / 100 / 125 / 150%\n"
            "(fine-tune with Ctrl+Plus / Ctrl+Minus)"
        )

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
        try:
            self.spin_volume.setValue(int(self.data.get("sound_volume", "5")))
        except Exception:
            self.spin_volume.setValue(5)
        self.spin_volume.setFixedWidth(42)
        self.spin_volume.setToolTip("Click sound volume (1-10)")
        self.spin_volume.valueChanged.connect(
            lambda v: (self.data.update({"sound_volume": str(v)}), self.mark_dirty())
        )

        # --- Settings panel: hidden by default, toggled by the gear button. ---
        # Top row: appearance & actions. Below: toggles grouped by purpose.
        appearance_row = QHBoxLayout()
        appearance_row.setContentsMargins(0, 0, 0, 0)
        appearance_row.setSpacing(4)
        appearance_row.addWidget(QLabel("Font:"))
        appearance_row.addWidget(self.font_combo)
        appearance_row.addWidget(self.font_spin)
        appearance_row.addWidget(self.btn_load_font)
        appearance_row.addWidget(self.btn_clear_fonts)
        appearance_row.addSpacing(8)
        appearance_row.addWidget(QLabel("Theme:"))
        appearance_row.addWidget(self.cb_theme)
        appearance_row.addWidget(self.btn_colors)
        appearance_row.addSpacing(8)
        appearance_row.addWidget(QLabel("View:"))
        appearance_row.addWidget(self.preview_combo)
        appearance_row.addWidget(self.btn_button_scale)
        appearance_row.addStretch(1)
        appearance_row.addWidget(self.btn_hotkeys)
        appearance_row.addWidget(self.btn_backup)
        appearance_row.addWidget(self.btn_restore)

        def create_footer_cb(text, tooltip, checked, callback):
            cb = QCheckBox(text)
            cb.setToolTip(tooltip)
            cb.setChecked(checked)
            if callback:
                cb.toggled.connect(lambda _: self.play_tick_sound())
                cb.toggled.connect(callback)
            return cb

        self.cb_top = create_footer_cb(
            "Always on Top",
            "Keep the window above all others",
            self.data.get("always_on_top", "True") == "True",
            self.toggle_aot,
        )
        self.cb_lock_window = create_footer_cb(
            "Lock Window",
            "Freeze the window's position and size",
            self.data.get("window_locked", "False") == "True",
            self.set_lock_state,
        )
        self.cb_normal_window = create_footer_cb(
            "Normal Window",
            "Use a standard OS window frame and taskbar entry",
            self.data.get("normal_window", "False") == "True",
            self.apply_window_flags,
        )
        self.cb_tray = create_footer_cb(
            "Tray Icon",
            "Keep an icon in the system tray",
            self.data.get("tray_visible", "True") == "True",
            self.on_tray_toggled,
        )
        self.cb_sidebar = create_footer_cb(
            "Sidebar Right",
            "Move the snippet/silo sidebar to the right side",
            self.data.get("sidebar_right", "False") == "True",
            self.toggle_sidebar_position,
        )
        self.cb_focus = create_footer_cb(
            "Hide on Click-Out",
            "Hide the window when you click outside of it",
            self.data.get("close_on_focus_loss", "True") == "True",
            self.mark_dirty,
        )
        self.cb_ctrl_c = create_footer_cb(
            "Ctrl+C Hides",
            "Copying with Ctrl+C also hides the window\n(copy & get back to work in one stroke)",
            self.data.get("ctrl_c_closes", "True") == "True",
            self.mark_dirty,
        )
        self.cb_lock_cursor = create_footer_cb(
            "Open at Cursor",
            "The hotkey opens the window at your mouse cursor",
            self.data.get("lock_to_cursor", "False") == "True",
            self.on_lock_cursor_toggled,
        )
        self.cb_silo_home = create_footer_cb(
            "Silos at Start",
            "Place the cursor at the top of a silo when opening it",
            self.data.get("silo_home", "False") == "True",
            self.on_silo_home_toggled,
        )
        self.cb_portable_backup = create_footer_cb(
            "Auto Backup (.md)",
            "Mirror silos & snippets as Markdown files to Documents\\.fastprompter\\",
            self.data.get("portable_backup_enabled", "True") == "True",
            lambda checked: (
                self.data.update({"portable_backup_enabled": "True" if checked else "False"})
                or self.mark_dirty()
            ),
        )
        self.cb_wrap = create_footer_cb(
            "Word Wrap",
            "Wrap long lines instead of scrolling horizontally",
            self.data.get("word_wrap", "True") == "True",
            self.on_wrap_toggled,
        )
        self.cb_line_numbers = create_footer_cb(
            "Line Numbers",
            "Show a line-number gutter\n(click it to place colored margin marks)",
            self.data.get("show_line_numbers", "False") == "True",
            self.on_line_numbers_toggled,
        )
        # keep the header mirror buttons in sync with the checkboxes
        self.cb_top.toggled.connect(
            lambda c: hasattr(self, "btn_pin_top") and self.btn_pin_top.setChecked(c))
        self.cb_line_numbers.toggled.connect(
            lambda c: hasattr(self, "btn_line_nums") and self.btn_line_nums.setChecked(c))

        self.cb_zebra = create_footer_cb(
            "Zebra Stripes",
            "Lightly shade every other line for readability",
            self.data.get("zebra_lines", "False") == "True",
            lambda checked: (
                self.data.update({"zebra_lines": "True" if checked else "False"})
                or self.text_area.viewport().update()
                or self.mark_dirty()
            ),
        )
        self.cb_hide_shortkeys = create_footer_cb(
            "Hide Key Hints",
            "Hide the F1-F10 shortcut labels on snippet buttons",
            self.data.get("hide_shortkeys", "False") == "True",
            self.on_hide_shortkeys_toggled,
        )
        self.cb_double_line = create_footer_cb(
            "Double-Space Lists",
            "With Auto-Bullet on, Enter after a list item adds a blank\n"
            "line before the next bullet — spaced, easy-to-read lists",
            self.data.get("bullet_double_line", "False") == "True",
            lambda checked: (
                self.data.update({"bullet_double_line": "True" if checked else "False"})
                or self.mark_dirty()
            ),
        )
        self.cb_bold_titles = create_footer_cb(
            "Bold # Titles",
            "Bold the sidebar title of silos and snippets whose\n"
            "content starts with a '#' markdown header",
            self.data.get("bold_hash_titles", "True") == "True",
            lambda checked: (
                self.data.update({"bold_hash_titles": "True" if checked else "False"})
                or self.mark_dirty()
                or self.refresh_temp_presets()
                or self.refresh_snippets_panel()
                or self.refresh_archive_panel()
            ),
        )
        self.cb_silo_pinned_gap = create_footer_cb(
            "Pinned Gap",
            "Show a visual separator between pinned and unpinned silos",
            self.data.get("silo_pinned_gap", "True") == "True",
            lambda checked: (
                self.data.update({"silo_pinned_gap": "True" if checked else "False"})
                or self.mark_dirty()
                or self.refresh_temp_presets()
                or self.refresh_snippets_panel()
            ),
        )
        self.cb_date_rect = create_footer_cb(
            "Show Date Widget",
            "Show a floating date and time rectangle in the top-right\n"
            "corner of the text editor",
            self.data.get("show_date_rect", "True") == "True",
            lambda checked: (
                self.data.update({"show_date_rect": "True" if checked else "False"})
                or self.mark_dirty()
            ),
        )
        self.cb_date_seconds = create_footer_cb(
            "Date Seconds",
            "Show seconds in the date widget (hh:mm:ss instead of hh:mm)",
            self.data.get("date_seconds", "True") == "True",
            lambda checked: (
                self.data.update({"date_seconds": "True" if checked else "False"})
                or self.mark_dirty()
            ),
        )
        self.cb_analog_clock = create_footer_cb(
            "Analog Clock",
            "Show a mini analog clock (hour + minute hands)\nnext to the date widget",
            self.data.get("analog_clock", "False") == "True",
            lambda checked: (
                self.data.update({"analog_clock": "True" if checked else "False"})
                or self.mark_dirty()
                or self._update_date_label()
            ),
        )
        self.cb_date_daypart = create_footer_cb(
            "Day Word",
            "Show the time-of-day word (Morning / Day / Evening / Night)\n"
            "after the clock in the date widget",
            self.data.get("date_daypart", "True") == "True",
            lambda checked: (
                self.data.update({"date_daypart": "True" if checked else "False"})
                or self.mark_dirty()
            ),
        )
        self.cb_date_text_month = create_footer_cb(
            "Text Month",
            "Show month as text instead of numbers (17 Jul instead of 17.07)",
            self.data.get("date_text_month", "False") == "True",
            lambda checked: (
                self.data.update({"date_text_month": "True" if checked else "False"})
                or self.mark_dirty()
            ),
        )
        self.cb_sound = create_footer_cb(
            "UI Sounds",
            "Play click sounds for buttons and actions",
            self.data.get("sound_ui", "False") == "True",
            self.on_sound_toggled,
        )
        self.cb_typewriter = create_footer_cb(
            "Typewriter",
            "Play a typewriter tick for every typed character",
            self.data.get("sound_typewriter", "False") == "True",
            self.on_typewriter_toggled,
        )
        self.cb_trash_vision = create_footer_cb(
            "Trash Vision",
            "Show the Trash category for deleted snippets",
            self.data.get("trash_vision", "False") == "True",
            self.toggle_trash_vision,
        )

        div_row = QHBoxLayout()
        div_row.setContentsMargins(0, 0, 0, 0)
        div_row.setSpacing(4)
        lbl_div = QLabel("Line gaps:")
        lbl_div.setToolTip("Blank lines the Line/Ctrl+W divider puts before and after ---")
        div_row.addWidget(lbl_div)
        self.spin_div_before = QSpinBox()
        self.spin_div_before.setRange(0, 6)
        self.spin_div_before.setToolTip("Lines before ---")
        try:
            self.spin_div_before.setValue(int(self.data.get("divider_lines_before", 2)))
        except (TypeError, ValueError):
            self.spin_div_before.setValue(2)
        self.spin_div_before.valueChanged.connect(
            lambda v: (self.data.update({"divider_lines_before": str(v)}), self.mark_dirty())
        )
        div_row.addWidget(self.spin_div_before)
        self.spin_div_after = QSpinBox()
        self.spin_div_after.setRange(1, 6)
        self.spin_div_after.setToolTip("Lines after --- (before the fresh bullet)")
        try:
            self.spin_div_after.setValue(int(self.data.get("divider_lines_after", 3)))
        except (TypeError, ValueError):
            self.spin_div_after.setValue(3)
        self.spin_div_after.valueChanged.connect(
            lambda v: (self.data.update({"divider_lines_after": str(v)}), self.mark_dirty())
        )
        div_row.addWidget(self.spin_div_after)
        div_row.addStretch(1)

        files_row = QHBoxLayout()
        files_row.setContentsMargins(0, 0, 0, 0)
        files_row.setSpacing(4)
        self.btn_files_root = QPushButton("Files Folder…")
        self.btn_files_root.setToolTip(
            "Choose where silo file containers are stored.\n"
            "Default: data/files next to the app."
        )
        self.btn_files_root.clicked.connect(self.pick_files_root)
        files_row.addWidget(self.btn_files_root)
        btn_files_root_reset = QPushButton("↺")
        btn_files_root_reset.setToolTip("Reset silo files location to the default data/files")
        btn_files_root_reset.setFixedWidth(24)
        btn_files_root_reset.clicked.connect(self.reset_files_root)
        files_row.addWidget(btn_files_root_reset)
        files_row.addStretch(1)

        vol_row = QHBoxLayout()
        vol_row.setContentsMargins(0, 0, 0, 0)
        vol_row.setSpacing(4)
        vol_row.addWidget(QLabel("Volume:"))
        vol_row.addWidget(self.spin_volume)
        vol_row.addStretch(1)

        hdr_row = QHBoxLayout()
        hdr_row.setContentsMargins(0, 0, 0, 0)
        hdr_row.setSpacing(4)
        lbl_hdr = QLabel("Header Fmt:")
        lbl_hdr.setToolTip(
            "Template for the Ctrl+E header.\n"
            "{text} — the line's text\n{time} — timestamp\n"
            "{state} — Morning / Day / Evening / Night\n"
            "Markdown markers (** __ etc.) are yours to add or drop."
        )
        hdr_row.addWidget(lbl_hdr)
        self.le_hdr_fmt = QLineEdit()
        self.le_hdr_fmt.setPlaceholderText("**__{text}__** ({time})")
        self.le_hdr_fmt.setText(self.data.get("ctrl_e_format", "**__{text}__** ({time})"))
        self.le_hdr_fmt.textChanged.connect(
            lambda v: (self.data.update({"ctrl_e_format": v}), self.mark_dirty())
        )
        hdr_row.addWidget(self.le_hdr_fmt)

        def _settings_group(title, items):
            col = QVBoxLayout()
            col.setContentsMargins(0, 0, 0, 0)
            col.setSpacing(1)
            col.setAlignment(Qt.AlignmentFlag.AlignTop)
            header = QLabel(title)
            header.setStyleSheet("font-weight: bold; padding: 0 0 1px 0;")
            col.addWidget(header)
            for item in items:
                if isinstance(item, QHBoxLayout):
                    col.addLayout(item)
                else:
                    col.addWidget(item)
            col.addStretch(1)
            return col

        def _vline():
            line = QFrame()
            line.setFrameShape(QFrame.Shape.VLine)
            line.setFrameShadow(QFrame.Shadow.Sunken)
            return line

        # Equal stretch on every column so the groups spread across the
        # full panel width instead of bunching up on the left.
        groups_row = QHBoxLayout()
        groups_row.setContentsMargins(2, 0, 2, 0)
        groups_row.setSpacing(8)
        groups_row.addLayout(_settings_group("Window", [
            self.cb_top, self.cb_lock_window, self.cb_normal_window,
            self.cb_tray, self.cb_sidebar, self.cb_date_rect, self.cb_date_seconds,
            self.cb_date_daypart, self.cb_date_text_month, self.cb_analog_clock,
            self.cb_trash_vision
        ]), 1)
        groups_row.addWidget(_vline())
        groups_row.addLayout(_settings_group("Editor", [
            self.cb_focus, self.cb_wrap, self.cb_ctrl_c, self.cb_lock_cursor,
            self.cb_line_numbers, self.cb_zebra, self.cb_double_line,
        ]), 1)
        groups_row.addWidget(_vline())
        groups_row.addLayout(_settings_group("Data & Appearance", [
            self.cb_silo_home, self.cb_silo_pinned_gap, self.cb_bold_titles,
            self.cb_hide_shortkeys, self.cb_portable_backup, self.cb_sound,
            self.cb_typewriter, vol_row, div_row, hdr_row, files_row
        ]), 1)

        hline = QFrame()
        hline.setFrameShape(QFrame.Shape.HLine)
        hline.setFrameShadow(QFrame.Shadow.Sunken)

        v_layout = QVBoxLayout(self.mini_settings_frame)
        v_layout.setContentsMargins(4, 2, 4, 3)
        v_layout.setSpacing(3)
        v_layout.addLayout(appearance_row)
        v_layout.addWidget(hline)
        v_layout.addLayout(groups_row)

        # Hidden by default — the gear button reveals it
        self.mini_settings_frame.setVisible(self.data.get("hide_extra", "True") != "True")

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
        self.snippets_section_layout.setContentsMargins(0, 0, 0, 0)
        self.snippets_section_layout.setSpacing(1)

        snip_header = QHBoxLayout()
        snip_header.setContentsMargins(0, 0, 0, 0)
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
        self.archive_section_layout.setContentsMargins(0, 0, 0, 0)
        self.archive_section_layout.setSpacing(1)

        arc_header = QHBoxLayout()
        arc_header.setContentsMargins(0, 0, 0, 0)
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
            btn.setMinimumHeight(14)
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
        self.silos_section_layout.setContentsMargins(0, 0, 0, 0)
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
            btn.setMinimumHeight(14)
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

        self.sections_gap_widget = QFrame(self)
        self.sections_gap_widget.setFixedHeight(8)
        self.sections_gap_widget.setStyleSheet("border-top: 1px solid #5a5a40; border-bottom: 1px solid #1a1a10; margin: 2px 8px; background: transparent;")
        self.sections_gap_widget.hide()
        self.left_panel_layout.addWidget(self.sections_gap_widget)

        self.left_panel_layout.addWidget(self.silos_section, 1)

        # Mouse-wheel paging over the sidebar sections and tabs;
        # Ctrl+wheel walks the silo selection one by one.
        WheelPager(self.silos_section, self.change_silo_page, ctrl_callback=self.navigate_silo)
        WheelPager(self.archive_section, self.change_arc_page, ctrl_callback=self.navigate_silo)
        WheelPager(self.snippets_section, self.change_page)
        WheelPager(self.tab_bar, self._wheel_switch_tab)
        wheel_hint = (
            "\nTip: mouse wheel over the list scrolls pages;"
            "\nCtrl+wheel selects the previous/next silo."
        )
        self.btn_silo_up.setToolTip("Previous silo page" + wheel_hint)
        self.btn_silo_down.setToolTip("Next silo page" + wheel_hint)
        self.btn_page_up.setToolTip("Previous snippet page" + wheel_hint)
        self.btn_page_down.setToolTip("Next snippet page" + wheel_hint)
        self.btn_arc_page_up.setToolTip("Previous archive page" + wheel_hint)
        self.btn_arc_page_down.setToolTip("Next archive page" + wheel_hint)
        self.tab_bar.setToolTip("Projects — mouse wheel switches tabs")

        self.archive_section.setParent(self.left_panel)
        self.archive_section.raise_()

        self.silos_section.setVisible(False)
        self.center_panel = QWidget()
        self.center_layout = QVBoxLayout(self.center_panel)
        self.center_layout.setContentsMargins(0, 0, 0, 0)
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

        self.btn_replace = QPushButton("Rpl")
        self.btn_replace.clicked.connect(self.replace_text)
        self.apply_button_size(self.btn_replace, 24)
        search_layout.addWidget(self.btn_replace)

        self.btn_replace_all = QPushButton("Rpl All")
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
        self.setMouseTracking(True)
        self.highlighter = MarkdownHighlighter(base_font_size=11)
        self.highlighter.setDocument(self.text_area.document())
        self.highlighter.set_skip_large(True)
        self.apply_wrap_mode()
        self.text_area.setPlaceholderText("Think deeply.")
        self.text_area.setWordWrapMode(
            QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere
        )  # Socratic: Smart visual wrap without corrupting text
        self.text_area.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        # Use a debounce timer to avoid text input stutter from cache sync
        self._cache_timer = QTimer(self)
        self._cache_timer.setSingleShot(True)
        self._cache_timer.setInterval(800)
        self._cache_timer.timeout.connect(self._on_cache_timer)
        self.text_area.textChanged.connect(self._on_text_changed)

        self._LARGE_DOC_THRESHOLD = 500000  # chars (raised 100x for large file support)
        self._cache_timer_interval = 800

        try:
            font_size = int(self.data.get("font_size", 11))
        except Exception:
            font_size = 11
        font = QFont(self.data.get("font_family", "Verdana"), font_size)
        font.setStyleStrategy(
            QFont.StyleStrategy.NoAntialias | QFont.StyleStrategy.NoSubpixelAntialias
        )
        self.text_area.setFont(font)

        self.silo_docs = []
        for _, text in enumerate(self.data.get("temp_presets", [])):
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

        safe_idx = max(0, min(self.data.get("last_tab_idx", 0), self.tab_bar.count() - 1))
        if self.tab_bar.count() > 0:
            self.tab_bar.setCurrentIndex(safe_idx)

        self._trim_archive()
        self.refresh_snippets_panel()
        self.refresh_temp_presets()
        QTimer.singleShot(0, lambda: not sip.isdeleted(self) and self._deferred_silo_refresh())
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
        from PyQt6.QtGui import QTextDocument

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
        try:
            slot_val = int(self.data.get("active_temp_slot", 0))
        except Exception:
            slot_val = 0
        self.active_temp_slot = max(0, min(slot_val, len(self.data["temp_presets"]) - 1))
        self._switch_to_slot(self.active_temp_slot, initial=True)

        # Switch to Text category
        text_idx = 0
        for i, c in enumerate(self.data["cats_order"]):
            if c == "Text":
                text_idx = i
                break
        self.tab_bar.setCurrentIndex(text_idx)
        self.on_tab_changed(text_idx)

    def insert_timestamp_at_end(self):
        cursor = self.text_area.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.EndOfBlock)
        ts = __import__('datetime').datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        prefix = " " if cursor.block().text().strip() else ""
        cursor.insertText(f"{prefix}{ts}")
        self.text_area.setTextCursor(cursor)
        self.text_area.ensureCursorVisible()
        self.text_area.setFocus()
        self.mark_dirty()

    def apply_header_timestamp(self):
        """Ctrl+E: Apply user-defined header formatting and timestamp at end of current line."""
        cursor = self.text_area.textCursor()
        cursor.beginEditBlock()

        # Select entire line
        cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
        cursor.movePosition(QTextCursor.MoveOperation.EndOfBlock, QTextCursor.MoveMode.KeepAnchor)
        sel = cursor.selectedText()

        if not sel.strip():
            cursor.endEditBlock()
            return

        template = self.data.get("ctrl_e_format", "**__{text}__** ({time})")
        full_template = template if template.startswith("# ") else f"# {template}"
        
        pattern = re.escape(full_template)
        pattern = pattern.replace(re.escape("{text}"), r"(.*?)")
        pattern = pattern.replace(re.escape("{time}"), r".*?")
        pattern = pattern.replace(re.escape("{state}"), r".*?")
        pattern = f"^{pattern}$"
        
        m = re.match(pattern, sel)
        if m:
            clean_sel = m.group(1)
            plain = QTextCharFormat()
            cursor.insertText(clean_sel, plain)
            cursor.endEditBlock()
            self.mark_dirty()
            return

        import datetime
        now = datetime.datetime.now()
        h = now.hour
        if 5 <= h < 12: daypart = "Morning"
        elif 12 <= h < 17: daypart = "Day"
        elif 17 <= h < 22: daypart = "Evening"
        else: daypart = "Night"
        
        text_month = self.data.get("date_text_month", "False") == "True"
        m_fmt = "%d %b" if text_month else "%d.%m"
        ts = now.strftime(f"{m_fmt} - %H:%M")
        
        # {state} in the template takes over the day word; otherwise the
        # legacy behavior prefixes it inside {time} when Day Word is on
        if "{state}" in template:
            time_str = ts
        else:
            time_str = f"{daypart} {ts}" if self.data.get("date_daypart", "True") == "True" else ts

        # Remove any existing "# " prefix to avoid duplication if running on an existing header
        clean_sel = sel[2:] if sel.startswith("# ") else sel

        formatted_text = (template.replace("{text}", clean_sel)
                          .replace("{time}", time_str)
                          .replace("{state}", daypart))
        if not formatted_text.startswith("# "):
            formatted_text = f"# {formatted_text}"
            
        cursor.insertText(formatted_text)

        # Jump two lines below the header onto a fresh bullet, with PLAIN
        # formatting — the header's bold/underline must not bleed into
        # what gets typed next. Reuses existing blank lines on repeats.
        plain = QTextCharFormat()
        cursor.movePosition(QTextCursor.MoveOperation.EndOfBlock)
        cursor.setCharFormat(plain)
        nxt = cursor.block().next()
        if not nxt.isValid() or nxt.text().strip():
            cursor.insertText("\n\n• ", plain)
        else:
            nxt2 = nxt.next()
            if not nxt2.isValid():
                cursor.setPosition(nxt.position())
                cursor.movePosition(QTextCursor.MoveOperation.EndOfBlock)
                cursor.insertText("\n• ", plain)
            else:
                cursor.setPosition(nxt2.position())
                cursor.movePosition(QTextCursor.MoveOperation.EndOfBlock)
                if not nxt2.text().strip():
                    cursor.insertText("• ", plain)
        cursor.endEditBlock()

        self.text_area.setTextCursor(cursor)
        self.text_area.setCurrentCharFormat(plain)
        self.text_area.ensureCursorVisible()
        self.text_area.setFocus()
        self.mark_dirty()

    def on_splitter_moved(self, pos, index):
        self.mark_dirty()

    def swap_temp_slots(self, idx1, idx2, is_archive=False):
        if idx1 == idx2:
            return
        if not getattr(self, "editing_snippet", None):
            target = self.data[
                "archive_temp_presets"
                if getattr(self, "active_is_archive", False)
                else "temp_presets"
            ]
            slot = getattr(self, "active_temp_slot", 0)
            if 0 <= slot < len(target):
                target[slot] = self.text_area.toPlainText()
        self.add_data_undo_state("Swap temp slots")
        temps = self.data["archive_temp_presets"] if is_archive else self.data["temp_presets"]
        docs = self.archive_docs if is_archive else self.silo_docs
        if not (0 <= idx1 < len(temps) and 0 <= idx2 < len(temps)):
            return

        from PyQt6.QtGui import QTextDocument

        while len(docs) <= max(idx1, idx2):
            d = QTextDocument()
            d.setDefaultFont(self.text_area.font())
            if len(docs) < len(temps):
                d.setPlainText(temps[len(docs)])
            docs.append(d)

        self._suspend_cache = True
        temps[idx1], temps[idx2] = temps[idx2], temps[idx1]
        docs[idx1], docs[idx2] = docs[idx2], docs[idx1]

        if getattr(self, "active_is_archive", False) == is_archive:
            if getattr(self, "active_temp_slot", -1) == idx1:
                self.active_temp_slot = idx2
            elif getattr(self, "active_temp_slot", -1) == idx2:
                self.active_temp_slot = idx1
        if not is_archive:
            self._remap_silo_indices(lambda i: idx2 if i == idx1 else idx1 if i == idx2 else i)
        self._suspend_cache = False
        self.mark_dirty()
        self.refresh_temp_presets()
        if is_archive:
            self.refresh_archive_panel()

    def _rebind_visible_lists(self, temp=None, archive=None):
        """Rebind data['temp_presets']/['archive_temp_presets'] AND the
        per-category backing store together — DB saves and tab switches read
        from temp_presets_all, so a bare rebind orphans the data."""
        cat = self.get_current_category()
        if temp is not None:
            self.data["temp_presets"] = temp
            if cat and "temp_presets_all" in self.data:
                self.data["temp_presets_all"][cat] = temp
        if archive is not None:
            self.data["archive_temp_presets"] = archive
            if cat and "archive_temp_presets_all" in self.data:
                self.data["archive_temp_presets_all"][cat] = archive

    def _remap_silo_indices(self, remap):
        """Apply an index remap to slot-index-keyed silo state (pins, tints).

        Mutates in place: both containers are aliases into per-category
        stores; rebinding them would orphan the data."""
        remapped = {remap(k): v for k, v in self.silo_last_edited.items()}
        self.silo_last_edited.clear()
        self.silo_last_edited.update(remapped)
        pinned = self.data.get("pinned_silos", [])
        if isinstance(pinned, list):
            pinned[:] = [remap(p) for p in pinned]
        ticked = self.data.get("silo_ticked", [])
        if isinstance(ticked, list):
            ticked[:] = [remap(t) for t in ticked]

    def handle_pinned_drop(self, source_idx, boundary_idx=None, swap_idx=None):
        """Handle dragging and dropping silos within or across the pinned section."""
        pinned = self.data.get("pinned_silos", [])
        if not isinstance(pinned, list):
            pinned = []
            
        if swap_idx is not None:
            if source_idx in pinned and swap_idx in pinned:
                i1, i2 = pinned.index(source_idx), pinned.index(swap_idx)
                pinned[i1], pinned[i2] = pinned[i2], pinned[i1]
                self.data["pinned_silos"] = pinned
                self.mark_dirty()
                self.refresh_temp_presets()
                return True
            return False

        if boundary_idx is not None:
            if source_idx in pinned and boundary_idx in pinned:
                pinned.remove(source_idx)
                pinned.insert(pinned.index(boundary_idx), source_idx)
                self.data["pinned_silos"] = pinned
                self.mark_dirty()
                self.refresh_temp_presets()
                return True
            elif source_idx in pinned and boundary_idx not in pinned:
                pinned.remove(source_idx)
                self.data["pinned_silos"] = pinned
                return False
            elif source_idx not in pinned and boundary_idx in pinned:
                pinned.insert(pinned.index(boundary_idx), source_idx)
                self.data["pinned_silos"] = pinned
                self.mark_dirty()
                self.refresh_temp_presets()
                return True
        else:
            if source_idx in pinned:
                pinned.remove(source_idx)
                self.data["pinned_silos"] = pinned
                return False
                
        return False

    def move_temp_to_index(self, from_idx, to_idx, is_archive=False):
        """Move a silo to a new position, shifting the others (drop 'between' silos)."""
        if from_idx == to_idx:
            return
        if not getattr(self, "editing_snippet", None):
            target = self.data[
                "archive_temp_presets"
                if getattr(self, "active_is_archive", False)
                else "temp_presets"
            ]
            slot = getattr(self, "active_temp_slot", 0)
            if 0 <= slot < len(target):
                target[slot] = self.text_area.toPlainText()
        temps = self.data["archive_temp_presets"] if is_archive else self.data["temp_presets"]
        docs = self.archive_docs if is_archive else self.silo_docs
        if not (0 <= from_idx < len(temps)):
            return
        to_idx = max(0, min(len(temps) - 1, to_idx))
        if from_idx == to_idx:
            return
        self.add_data_undo_state("Move silo")

        from PyQt6.QtGui import QTextDocument

        while len(docs) <= max(from_idx, to_idx):
            d = QTextDocument()
            d.setDefaultFont(self.text_area.font())
            if len(docs) < len(temps):
                d.setPlainText(temps[len(docs)])
            docs.append(d)

        self._suspend_cache = True
        temps.insert(to_idx, temps.pop(from_idx))
        docs.insert(to_idx, docs.pop(from_idx))

        def remap(i):
            if i == from_idx:
                return to_idx
            if from_idx < to_idx and from_idx < i <= to_idx:
                return i - 1
            if to_idx < from_idx and to_idx <= i < from_idx:
                return i + 1
            return i

        if getattr(self, "active_is_archive", False) == is_archive:
            self.active_temp_slot = remap(getattr(self, "active_temp_slot", 0))
        if not is_archive:
            self._remap_silo_indices(remap)
        self._suspend_cache = False
        self.mark_dirty()
        self.refresh_temp_presets()
        if is_archive:
            self.refresh_archive_panel()

    def apply_window_flags(self, _=None):
        self.data["always_on_top"] = "True" if self.cb_top.isChecked() else "False"
        self.data["normal_window"] = "True" if self.cb_normal_window.isChecked() else "False"
        flags = Qt.WindowType.Window
        normal = self.cb_normal_window.isChecked()
        if not normal:
            flags |= Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool
        self.unregister_all_hotkeys()
        was_visible = self.isVisible()
        # setWindowFlags recreates the native window; the resulting
        # activation-change would trigger the click-out auto-hide and make
        # the toggle look broken. Suppress it until the dust settles.
        self.ignore_focus_loss = True
        geo = self.geometry()
        # Anti-flashbang: the recreated native window first paints with the
        # default (white) background brush before the stylesheet kicks in.
        # Paint it in the theme's window color instead.
        m_bg = re.search(
            r"QWidget\s*\{[^}]*background-color:\s*(#[0-9a-fA-F]{3,8})",
            QApplication.instance().styleSheet(),
        )
        if m_bg:
            from PyQt6.QtGui import QPalette
            pal = self.palette()
            pal.setColor(QPalette.ColorRole.Window, QColor(m_bg.group(1)))
            self.setPalette(pal)
            self.setAutoFillBackground(True)
        self.setUpdatesEnabled(False)
        self.hide()  # explicit hide forces a clean native-frame rebuild
        self.setWindowFlags(flags)
        self.setGeometry(geo)
        if was_visible:
            self.show()
            self.setUpdatesEnabled(True)
            self.repaint()
            self.raise_()
            self.activateWindow()
        else:
            self.setUpdatesEnabled(True)
            # New native handle: re-assert always-on-top on it
            if self._always_on_top and not normal:
                try:
                    ctypes.windll.user32.SetWindowPos(
                        int(self.winId()), -1, 0, 0, 0, 0, 0x0002 | 0x0001
                    )
                except Exception:
                    pass
        QTimer.singleShot(300, lambda: setattr(self, "ignore_focus_loss", False))
        self.register_all_hotkeys()
        self.mark_dirty()

    def move_preset_to_index(self, category, from_idx, to_idx):
        if from_idx == to_idx:
            return
        self.add_data_undo_state("Move preset")
        slots = self.data["categories"][category]
        item = slots.pop(from_idx)
        slots.insert(to_idx, item)
        self.mark_dirty()
        self.refresh_snippets_panel()

    def move_preset_cross_category(self, from_cat, from_idx, to_cat, to_idx):
        self.add_data_undo_state("Move preset cross category")

        if from_cat == "silo":
            if not (0 <= from_idx < len(self.data["temp_presets"])):
                return
            text = self.data["temp_presets"].pop(from_idx)
            if from_idx < len(self.silo_docs):
                self.silo_docs.pop(from_idx)
            item = {"name": text[:20], "text": text}
            if not getattr(self, "active_is_archive", False):
                if from_idx < self.active_temp_slot:
                    self.active_temp_slot -= 1
                elif from_idx == self.active_temp_slot:
                    self.active_temp_slot = (
                        max(0, self.active_temp_slot - 1) if self.data["temp_presets"] else 0
                    )
        elif from_cat == "arcsilo":
            if not (0 <= from_idx < len(self.data.get("archive_temp_presets", []))):
                return
            text = self.data["archive_temp_presets"].pop(from_idx)
            if from_idx < len(self.archive_docs):
                self.archive_docs.pop(from_idx)
            item = {"name": text[:20], "text": text}
            if getattr(self, "active_is_archive", False):
                if from_idx < self.active_temp_slot:
                    self.active_temp_slot -= 1
                elif from_idx == self.active_temp_slot:
                    self.active_temp_slot = (
                        max(0, self.active_temp_slot - 1)
                        if self.data["archive_temp_presets"]
                        else 0
                    )
        else:
            item = self.data["categories"][from_cat].pop(from_idx)
            slots = self.data["categories"][from_cat]
            if len(slots) < 100:
                slots.append(None)

        if to_cat == "silo":
            self.data["temp_presets"].insert(to_idx, item["text"] if item else "")
            doc = QTextDocument()
            doc.setDefaultFont(self.text_area.font())
            doc.setPlainText(item["text"] if item else "")
            self.silo_docs.insert(to_idx, doc)
        elif to_cat == "arcsilo":
            if "archive_temp_presets" not in self.data:
                self.data["archive_temp_presets"] = []
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
        if not getattr(self, "editing_snippet", None):
            target = self.data[
                "archive_temp_presets"
                if getattr(self, "active_is_archive", False)
                else "temp_presets"
            ]
            slot = getattr(self, "active_temp_slot", 0)
            if 0 <= slot < len(target):
                target[slot] = self.text_area.toPlainText()
        self.add_data_undo_state("Swap cross temp slots")
        source_arr = (
            self.data["archive_temp_presets"] if source_is_archive else self.data["temp_presets"]
        )
        target_arr = (
            self.data["archive_temp_presets"] if target_is_archive else self.data["temp_presets"]
        )
        source_docs = self.archive_docs if source_is_archive else self.silo_docs
        target_docs = self.archive_docs if target_is_archive else self.silo_docs

        # We need to make sure arrays are long enough
        while len(source_arr) <= source_idx:
            source_arr.append("")
        while len(target_arr) <= target_idx:
            target_arr.append("")

        from PyQt6.QtGui import QTextDocument

        while len(source_docs) <= source_idx:
            d = QTextDocument()
            d.setDefaultFont(self.text_area.font())
            source_docs.append(d)
        while len(target_docs) <= target_idx:
            d = QTextDocument()
            d.setDefaultFont(self.text_area.font())
            target_docs.append(d)

        source_arr[source_idx], target_arr[target_idx] = (
            target_arr[target_idx],
            source_arr[source_idx],
        )
        source_docs[source_idx], target_docs[target_idx] = (
            target_docs[target_idx],
            source_docs[source_idx],
        )

        self._trim_archive()
        self.mark_dirty()
        self.refresh_temp_presets()
        self.refresh_archive_panel()

    def on_wrap_toggled(self, checked):
        self.data["word_wrap"] = "True" if checked else "False"
        self.apply_wrap_mode()
        self.mark_dirty()

    def on_line_numbers_toggled(self, checked):
        self.data["show_line_numbers"] = "True" if checked else "False"
        self.text_area.update_line_number_area_width()
        self.text_area.line_number_area.update()
        self.mark_dirty()

    def apply_wrap_mode(self):
        wrap = self.data.get("word_wrap", "True") == "True"
        self.text_area.setLineWrapMode(
            QTextEdit.LineWrapMode.WidgetWidth if wrap else QTextEdit.LineWrapMode.NoWrap
        )

    def open_help_dialog(self):
        """Open the comprehensive help window (hotkeys, gestures, features)."""
        self.play_tick_sound()
        dlg = getattr(self, "_help_dialog", None)
        if dlg is None or sip.isdeleted(dlg):
            dlg = HelpDialog(self)
            self._help_dialog = dlg
        self.ignore_focus_loss = True
        dlg.show()
        dlg.raise_()
        dlg.activateWindow()
        QTimer.singleShot(300, lambda: setattr(self, "ignore_focus_loss", False))

    def open_hotkey_settings(self):
        dlg = HotkeySettingsDialog(self)
        self.ignore_focus_loss = True
        try:
            dlg.exec()
        finally:
            self.ignore_focus_loss = False

    def _snapshot_current(self):
        pinned = self.data.get("pinned_silos", [])
        return {
            "categories": copy.deepcopy(self.data["categories"]),
            "cats_order": list(self.data.get("cats_order", [])),
            "category": self.get_current_category(),
            "temp_presets": copy.deepcopy(self.data["temp_presets"]),
            "archive_temp_presets": copy.deepcopy(self.data["archive_temp_presets"]),
            "active_temp_slot": self.active_temp_slot,
            "active_is_archive": getattr(self, "active_is_archive", False),
            "editing_snippet": getattr(self, "editing_snippet", None),
            "pinned_silos": list(pinned) if isinstance(pinned, list) else [],
            "silo_ticked": list(self.data.get("silo_ticked", [])),
            "silo_last_edited": dict(getattr(self, "silo_last_edited", {})),
        }

    def _snapshot_is_noop(self, state):
        """True when restoring this snapshot would change no user data."""
        return (
            state["temp_presets"] == self.data["temp_presets"]
            and state["archive_temp_presets"] == self.data["archive_temp_presets"]
            and state["categories"] == self.data["categories"]
            and state.get("active_temp_slot") == self.active_temp_slot
            and state.get("active_is_archive", False) == getattr(self, "active_is_archive", False)
            and state.get("pinned_silos", self.data.get("pinned_silos", []))
            == self.data.get("pinned_silos", [])
        )

    def _bump_action_seq(self):
        """Monotonic ordering for text edits vs data actions — wall-clock
        time ties on Windows' timer granularity and breaks Ctrl+Z routing."""
        self._action_seq = getattr(self, "_action_seq", 0) + 1
        return self._action_seq

    def _undo_prefers_data(self):
        """Route Ctrl+Z to the data stack when a silo/snippet action is newer
        than the last text edit, or when text undo has nothing to offer."""
        if not getattr(self, "data_undo_stack", None):
            return False
        if getattr(self, "_last_data_action_time", 0) > getattr(self, "_last_text_edit_time", 0):
            return True
        doc = self.text_area.document()
        return not doc.isUndoAvailable()

    def _smart_undo(self):
        """Ctrl+Z: data undo (silo clear/delete/move) or text undo."""
        if self._undo_prefers_data():
            self.undo_action()
        else:
            self.text_area.undo()

    def undo_action(self):
        if hasattr(self, "data_undo_stack") and self.data_undo_stack:
            if not hasattr(self, "data_redo_stack"):
                self.data_redo_stack = []
            # Skip no-op snapshots, but ONLY within the current tab —
            # a snapshot from another tab is never comparable to the
            # currently visible lists and must be restored, not judged
            cur_cat = self.get_current_category()
            state = self.data_undo_stack.pop()
            while (
                self.data_undo_stack
                and state.get("category") == cur_cat
                and self._snapshot_is_noop(state)
            ):
                state = self.data_undo_stack.pop()
            if state.get("category") == cur_cat and self._snapshot_is_noop(state):
                return
            redo_state = self._snapshot_current()
            self.data_redo_stack.append(redo_state)
            if len(self.data_redo_stack) > 50:
                self.data_redo_stack.pop(0)
            self._apply_data_state(state)
            self.play_sound("tick")
            # Keep data undo "fresh" so repeated Ctrl+Z keeps popping this stack
            self._last_data_action_time = self._bump_action_seq()
            return
        # Text undo is handled natively by QTextEdit via VaultTextEdit.keyPressEvent

    def redo_action(self):
        if hasattr(self, "data_redo_stack") and self.data_redo_stack:
            if not hasattr(self, "data_undo_stack"):
                self.data_undo_stack = []
            undo_state = self._snapshot_current()
            self.data_undo_stack.append(undo_state)
            state = self.data_redo_stack.pop()
            self._apply_data_state(state)
            self.play_sound("tick")
            return
        # Text redo is handled natively by QTextEdit via VaultTextEdit.keyPressEvent

    def _apply_data_state(self, state):
        self.data["categories"] = state["categories"]
        if state.get("cats_order"):
            self.data["cats_order"] = list(state["cats_order"])
        # Rebuild the tab bar FIRST — it resets the current index to 0 and
        # would otherwise clobber the tab jump and orphan the restored lists
        self.build_categories()

        # The action may have happened on another tab — return to it, and
        # rebind the per-category backing store; DB saves read from
        # temp_presets_all, so without this the restored data is lost.
        snap_cat = state.get("category")
        if snap_cat and snap_cat in self.data.get("cats_order", []):
            idx = self.data["cats_order"].index(snap_cat)
            if self.tab_bar.currentIndex() != idx:
                self.tab_bar.blockSignals(True)
                self.tab_bar.setCurrentIndex(idx)
                self.tab_bar.blockSignals(False)
            self.data["last_tab_idx"] = idx

        self.data["temp_presets"] = state["temp_presets"]
        self.data["archive_temp_presets"] = state["archive_temp_presets"]
        if snap_cat and "temp_presets_all" in self.data:
            self.data["temp_presets_all"][snap_cat] = self.data["temp_presets"]
            self.data["archive_temp_presets_all"][snap_cat] = self.data["archive_temp_presets"]
        if snap_cat:
            plist = self.data.setdefault("pinned_silos_all", {}).setdefault(snap_cat, [])
            plist[:] = list(state.get("pinned_silos", []))
            self.data["pinned_silos"] = plist
            tlist = self.data.setdefault("silo_ticked_all", {}).setdefault(snap_cat, [])
            tlist[:] = list(state.get("silo_ticked", []))
            self.data["silo_ticked"] = tlist
            edict = self.data.setdefault("silo_last_edited_all", {}).setdefault(snap_cat, {})
            edict.clear()
            edict.update(state.get("silo_last_edited", {}))
            self.silo_last_edited = edict
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
            elif active_slot < len(self.data["temp_presets"]):
                self._switch_to_slot(active_slot, initial=True)
            self._suspend_cache = False
        self.refresh_temp_presets()
        self.refresh_archive_panel()

    def toggle_trash_vision(self, checked):
        self.data["trash_vision"] = "True" if checked else "False"
        if checked:
            if "Trash" not in self.data["categories"]:
                self.data["categories"]["Trash"] = []
            if "Trash" not in self.data["cats_order"]:
                self.data["cats_order"].append("Trash")
        else:
            if "Trash" in self.data["cats_order"]:
                self.data["cats_order"].remove("Trash")
        self.build_categories()
        self.mark_dirty()

    def add_data_undo_state(self, _action_name=""):
        if not hasattr(self, "data_undo_stack"):
            self.data_undo_stack = []
        if not hasattr(self, "data_redo_stack"):
            self.data_redo_stack = []
        state = self._snapshot_current()
        # Never push a snapshot identical to the top — no-op pileups make
        # the skip logic walk into unrelated (even cross-tab) history
        if self.data_undo_stack and self.data_undo_stack[-1] == state:
            return
        self.data_undo_stack.append(state)
        if len(self.data_undo_stack) > 50:
            self.data_undo_stack.pop(0)
        self.data_redo_stack.clear()
        # Lets Ctrl+Z pick data undo over text undo when this action is newer
        self._last_data_action_time = self._bump_action_seq()

    def build_categories(self):
        """Rebuild the tab bar from cats_order."""
        self.tab_bar.blockSignals(True)
        while self.tab_bar.count() > 0:
            self.tab_bar.removeTab(0)
        for cat in self.data["cats_order"]:
            self.tab_bar.addTab(cat)
        self.tab_bar.blockSignals(False)
        if self.tab_bar.count() > 0:
            self.tab_bar.setCurrentIndex(0)
        self.refresh_snippets_panel()

    def _sync_silo_folder(self, cat, old_text, new_text):
        """Retitled silo/snippet: rename its file folder so assets follow.
        Every path that rewrites a first line must run through here —
        a missed sync silently detaches the silo from its files."""
        from fastprompter.ui.file_container import silo_files_dir, silo_slug
        if silo_slug(old_text) == silo_slug(new_text):
            return
        old_dir = silo_files_dir(self._files_root(), cat, old_text)
        new_dir = silo_files_dir(self._files_root(), cat, new_text)
        try:
            if os.path.isdir(old_dir) and not os.path.exists(new_dir):
                os.makedirs(os.path.dirname(new_dir), exist_ok=True)
                os.rename(old_dir, new_dir)
        except OSError as e:
            from fastprompter.core.logging import logger
            logger.warning(f"Silo folder sync {old_dir} -> {new_dir} failed: {e}")

    def commit_current_text(self):
        """Commit the current text to the active slot."""
        if getattr(self, "_initializing_ui", False):
            return
        current_text = self.text_area.toPlainText()
        cat = self.get_current_category()

        if not self.editing_snippet:
            if 0 <= self.active_temp_slot < len(self.data["temp_presets"]):
                old_text = self.data["temp_presets"][self.active_temp_slot]
                self._sync_silo_folder(cat, old_text, current_text)
                self.data["temp_presets"][self.active_temp_slot] = current_text
        else:
            cat_snip, idx = self.editing_snippet
            if cat_snip in self.data["categories"] and self.data["categories"][cat_snip][idx]:
                old_text = self.data["categories"][cat_snip][idx]["text"]
                self._sync_silo_folder(cat_snip, old_text, current_text)
                self.data["categories"][cat_snip][idx]["text"] = current_text

    def open_color_settings(self):
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
        path, _ = QFileDialog.getOpenFileName(
            self, "Restore Backup", "", "SQLite DB (*.db *.bak);;All Files (*)"
        )
        if not path:
            return
        self.ignore_focus_loss = True
        try:
            reply = QMessageBox.question(
                self,
                "Confirm",
                "App will restart. Proceed?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply == QMessageBox.StandardButton.Yes:
                db_path = self.state.db_path
                if os.path.abspath(path) == os.path.abspath(db_path):
                    QMessageBox.warning(self, "Error", "Source and destination are the same file.")
                    return
                if self.state.conn:
                    self.state.conn.close()
                    self.state.conn = None
                self.conn = None
                time.sleep(0.1)
                shutil.copy2(path, db_path)
                for ext in ["-wal", "-shm"]:
                    if os.path.exists(db_path + ext):
                        try:
                            os.remove(db_path + ext)
                        except Exception:
                            import traceback

                            traceback.print_exc()
                self.quit_app()
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to restore backup:\n{e}")
            self.state.init_db()
            self.conn = self.state.conn
        finally:
            self.ignore_focus_loss = False

    def _position_archive_overlay(self):
        if not hasattr(self, "archive_section") or not hasattr(self, "left_panel"):
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

    def moveEvent(self, event):
        if getattr(self, "is_locked", False) and getattr(self, "_locked_geometry", None):
            if self.geometry() != self._locked_geometry:
                self.setGeometry(self._locked_geometry)
                return
        self._update_last_geometry()
        super().moveEvent(event)

    def closeEvent(self, event):
        self.save_data_to_db(force=True)
        super().closeEvent(event)

    def resizeEvent(self, event):
        if getattr(self, "is_locked", False) and getattr(self, "_locked_geometry", None):
            if self.geometry() != self._locked_geometry:
                self.setGeometry(self._locked_geometry)
                return
        self._update_last_geometry()

        # Update edge resizers
        if hasattr(self, "_resizers"):
            t = 6
            w, h = self.width(), self.height()
            self._resizers["left"].setGeometry(0, t, t, h - 2 * t)
            self._resizers["right"].setGeometry(w - t, t, t, h - 2 * t)
            self._resizers["top"].setGeometry(t, 0, w - 2 * t, t)
            self._resizers["bottom"].setGeometry(t, h - t, w - 2 * t, t)
            self._resizers["topleft"].setGeometry(0, 0, t, t)
            self._resizers["topright"].setGeometry(w - t, 0, t, t)
            self._resizers["bottomleft"].setGeometry(0, h - t, t, t)
            self._resizers["bottomright"].setGeometry(w - t, h - t, t, t)
            for r in self._resizers.values():
                r.raise_()

        self._apply_header_density()
        super().resizeEvent(event)

    # def nativeEvent(self, eventType, message):
    #     return super().nativeEvent(eventType, message)

    def mousePressEvent(self, event):
        if sip.isdeleted(self):
            return
        if getattr(self, "is_locked", False):
            event.ignore()
            return
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if sip.isdeleted(self):
            return
        if getattr(self, "is_locked", False):
            return

        if event.buttons() == Qt.MouseButton.LeftButton:
            if hasattr(self, "_drag_pos"):
                self.move(event.globalPosition().toPoint() - self._drag_pos)
                event.accept()

    def mouseReleaseEvent(self, event):
        if sip.isdeleted(self):
            return
        if hasattr(self, "_drag_pos"):
            del self._drag_pos
            event.accept()

    def changeEvent(self, event):
        if event.type() in (QEvent.Type.ActivationChange, QEvent.Type.WindowDeactivate):
            if not self.isActiveWindow() and not self.isMinimized():
                if getattr(self, "cb_focus", None) and self.cb_focus.isChecked():
                    help_dlg = getattr(self, "_help_dialog", None)
                    help_open = (
                        help_dlg is not None
                        and not sip.isdeleted(help_dlg)
                        and help_dlg.isVisible()
                    )
                    if (
                        not getattr(self, "ignore_focus_loss", False)
                        and not getattr(self, "is_locked", False)
                        and not help_open
                    ):
                        self.hide_and_save()
        super().changeEvent(event)

    def eventFilter(self, obj, event):
        if sip.isdeleted(self) or (obj and sip.isdeleted(obj)):
            return False

        if obj == getattr(self, "silos_widget", None) and event.type() == QEvent.Type.Resize:
            self._update_visible_silo_count()
            if hasattr(self, "_silo_resize_debounce_timer"):
                self._silo_resize_debounce_timer.start()
            return False

        if obj == getattr(self, "left_panel", None) and event.type() == QEvent.Type.Resize:
            self._position_archive_overlay()
            return False

        if (
            event.type() == QEvent.Type.MouseButtonPress
            and getattr(event, "button", lambda: 0)() == Qt.MouseButton.RightButton
        ):
            if not getattr(self, "is_locked", False):
                self._text_drag_pos = (
                    event.globalPosition().toPoint() - self.frameGeometry().topLeft()
                )
                return False
        elif (
            event.type() == QEvent.Type.MouseMove
            and getattr(event, "buttons", lambda: 0)() & Qt.MouseButton.RightButton
        ):
            if not getattr(self, "is_locked", False) and hasattr(self, "_text_drag_pos"):
                self.move(event.globalPosition().toPoint() - self._text_drag_pos)
                return True
        elif (
            event.type() == QEvent.Type.MouseButtonRelease
            and getattr(event, "button", lambda: 0)() == Qt.MouseButton.RightButton
        ):
            if hasattr(self, "_text_drag_pos"):
                delattr(self, "_text_drag_pos")
                return False
        return super().eventFilter(obj, event)

    def add_category(self):
        self.play_sound("new")
        if len(self.data["cats_order"]) >= 5:
            QMessageBox.information(
                self, "Tab Limit", "Maximum of 5 tabs/projects. Remove one first."
            )
            return
        self.ignore_focus_loss = True
        try:
            name, ok = QInputDialog.getText(self, "New Tab", "Enter tab name:")
        finally:
            self.ignore_focus_loss = False
        self.activateWindow()
        if ok and name and name.strip() not in self.data["cats_order"]:
            self.add_data_undo_state("Add category")
            name = name.strip()
            self.data["cats_order"].append(name)
            self.data["categories"][name] = [None] * 100
            self.tab_bar.addTab(name)
            self.tab_bar.setCurrentIndex(self.tab_bar.count() - 1)
            self.mark_dirty()

    def del_category(self):
        self.play_sound("delete")
        if self.tab_bar.count() <= 1:
            return
        idx = self.tab_bar.currentIndex()
        cat = self.data["cats_order"][idx]
        self.ignore_focus_loss = True
        try:
            reply = QMessageBox.question(
                self,
                "Delete Tab",
                f"Nuke '{cat}' and all snippets?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
        finally:
            self.ignore_focus_loss = False
        self.activateWindow()
        if reply == QMessageBox.StandardButton.Yes:
            self.add_data_undo_state("Delete category")
            self.data["cats_order"].pop(idx)
            del self.data["categories"][cat]
            if cat in self.current_pages:
                del self.current_pages[cat]
            self.tab_bar.removeTab(idx)
            self.mark_dirty()

    def _wheel_switch_tab(self, direction):
        """Mouse wheel over the tab bar switches projects."""
        idx = self.tab_bar.currentIndex() + direction
        if 0 <= idx < self.tab_bar.count():
            self.tab_bar.setCurrentIndex(idx)

    def _on_escape(self):
        """Esc closes the search bar first; a second Esc hides the window."""
        if hasattr(self, "search_frame") and self.search_frame.isVisible():
            self.close_search()
            return
        self.hide_and_save()

    def on_tab_changed(self, index):
        if index < 0:
            return
        self.data["last_tab_idx"] = index
        self.commit_current_text()
        self.cancel_editing()

        # Switch Silos to the new Tab's hierarchy
        cats = self.data.get("cats_order", [])
        if index >= len(cats):
            return
        cat = cats[index]
        if "temp_presets_all" in self.data:
            if cat not in self.data["temp_presets_all"]:
                self.data["temp_presets_all"][cat] = [""] * 10
            if cat not in self.data["archive_temp_presets_all"]:
                self.data["archive_temp_presets_all"][cat] = []
            self.data["temp_presets"] = self.data["temp_presets_all"][cat]
            self.data["archive_temp_presets"] = self.data["archive_temp_presets_all"][cat]
            self.data["pinned_silos"] = self.data.setdefault("pinned_silos_all", {}).setdefault(
                cat, []
            )
            self.data["silo_ticked"] = self.data.setdefault("silo_ticked_all", {}).setdefault(
                cat, []
            )
            self.silo_last_edited = self.data.setdefault("silo_last_edited_all", {}).setdefault(
                cat, {}
            )

            # Rebuild document caches for the new silos
            from PyQt6.QtGui import QTextDocument

            font = self.text_area.font()
            self.silo_docs = []
            for text in self.data["temp_presets"]:
                doc = QTextDocument()
                doc.setDefaultFont(font)
                self._set_plain_text_clean(doc, text)
                self.silo_docs.append(doc)
            self.archive_docs = []
            for text in self.data["archive_temp_presets"]:
                doc = QTextDocument()
                doc.setDefaultFont(font)
                self._set_plain_text_clean(doc, text)
                self.archive_docs.append(doc)

            # Keep active slot within bounds and switch to it
            self.active_temp_slot = max(
                0, min(self.active_temp_slot, len(self.data["temp_presets"]) - 1)
            )
            self._switch_to_slot(self.active_temp_slot, initial=True)
            self.refresh_temp_presets()

        self.refresh_snippets_panel()
        self.mark_dirty()
        self.text_area.setFocus()

    def change_page(self, delta):
        cat = self.get_current_category()
        if not cat or cat not in self.data.get("categories", {}):
            return
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
        new_page = getattr(self, "arc_silo_page", 0) + delta
        if 0 <= new_page <= max_page:
            self.arc_silo_page = new_page
            self.data["arc_silo_page"] = new_page
            self.refresh_archive_panel()

    def darken_color(self, hex_color, factor=0.75):
        hex_color = hex_color.lstrip("#")
        if len(hex_color) == 3:
            hex_color = "".join(c + c for c in hex_color)
        r, g, b = tuple(int(hex_color[i : i + 2], 16) for i in (0, 2, 4))
        r, g, b = int(r * factor), int(g * factor), int(b * factor)
        return f"#{r:02x}{g:02x}{b:02x}"

    def _snippet_query(self):
        """Active snippet filter. A hidden search bar NEVER filters —
        stale text in a closed bar used to silently hide snippets."""
        if self.search_bar.isHidden():
            return ""
        return self.search_bar.text().strip().lower()

    def refresh_snippets_panel(self):
        if self._suspend_cache or self._initializing_ui:
            return
        cat = self.get_current_category()
        if not cat:
            self.snippets_section.setVisible(False)
            if hasattr(self, "sections_gap_widget"):
                self.sections_gap_widget.setVisible(False)
            self.refresh_archive_panel()
            return

        query = self._snippet_query()
        active_items = []
        for i, s in enumerate(self.data["categories"][cat]):
            if s is not None:
                if not query or query in s["name"].lower() or query in s["text"].lower():
                    active_items.append((i, s))

        total_active = len(active_items)
        if total_active == 0:
            self.snippets_section.setVisible(False)
            if hasattr(self, "sections_gap_widget"):
                self.sections_gap_widget.setVisible(False)
            self.refresh_archive_panel()
            return

        self.snippets_section.setVisible(True)
        if hasattr(self, "sections_gap_widget"):
            self.sections_gap_widget.setVisible(self.data.get("silo_pinned_gap", "True") == "True")
        page = min(self.current_pages.get(cat, 0), max(0, math.ceil(total_active / 10.0) - 1))
        self.current_pages[cat] = page

        start_idx = page * 10
        page_items = active_items[start_idx : start_idx + 10]

        theme_name = self.data.get("theme", "Default")
        if theme_name not in THEMES:
            theme_name = "Default"
        preset_colors = THEMES[theme_name]["preset_colors"]
        font_family = self.data.get("font_family", "Verdana")
        hide_keys = self.data.get("hide_shortkeys", "False") == "True"

        try:
            scale = float(self.data.get("ui_scale", "1.0"))
        except Exception:
            scale = 1.0

        self._snippet_widget_cache.clear()
        for i, w in enumerate(self.snippet_buttons):
            if i < len(page_items):
                global_idx, item = page_items[i]
                d_idx = i + 1
                key_label = (
                    ""
                    if hide_keys
                    else (
                        f"[{d_idx % 10 if d_idx % 10 != 0 else 0}] "
                        if d_idx <= 10
                        else f"[{d_idx}] "
                    )
                )
                disp = item["name"]
                color = preset_colors[global_idx % len(preset_colors)]
                is_editing = self.editing_snippet and self.editing_snippet == (cat, global_idx)
                last_ts = item.get("last_edited", 0)
                if last_ts and not is_editing:
                    diff = time.time() - last_ts
                    custom = self._get_custom_colors()
                    if diff < 60:
                        overlay = QColor(custom.get("overlay_new", "#7a5555"))
                    elif diff < 3600:
                        overlay = QColor(custom.get("overlay_recent", "#7a6a40"))
                    elif diff < 86400:
                        overlay = QColor(custom.get("overlay_day", "#6a6a30"))
                    elif diff < 4233600:
                        overlay = QColor(custom.get("overlay_old", "#40556a"))
                    else:
                        overlay = None
                    if overlay:
                        base = QColor(color)
                        color = self.blend_colors(base, overlay, 0.15)

                w.update_data(
                    f"{key_label}{disp}", cat, global_idx, item["text"], color, font_family, scale,
                    title_bold=(
                        self.data.get("bold_hash_titles", "True") == "True"
                        and item["text"].lstrip().startswith("#")
                    ),
                )
                self._snippet_widget_cache[(cat, global_idx)] = (
                    w.main_btn if hasattr(w, "main_btn") else w
                )
                w.show()
            else:
                if hasattr(w, "main_btn"):
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
        if getattr(self, "left_widget", None) and self.left_widget.parentWidget():
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

        needs_visible = max_page > 0
        self.btn_arc_page_up.setVisible(needs_visible)
        self.btn_arc_page_down.setVisible(needs_visible)

        self.arc_silo_page = min(getattr(self, "arc_silo_page", 0), max_page)
        self.btn_arc_page_up.setEnabled(self.arc_silo_page > 0)
        self.btn_arc_page_down.setEnabled(self.arc_silo_page < max_page)

        theme_name = self.data.get("theme", "Default")
        if theme_name not in THEMES:
            theme_name = "Default"
        inactive_color = THEMES[theme_name]["inactive_temp_color"]
        active_color = THEMES[theme_name]["active_temp_color"]

        custom_colors = self._get_custom_colors()
        if "edit_bg" in custom_colors:
            active_color = custom_colors["edit_bg"]

        try:
            scale = float(self.data.get("ui_scale", "1.0"))
        except Exception:
            scale = 1.0
        font_family = self.data.get("font_family", "Verdana")

        start_idx = self.arc_silo_page * visible_count

        for i, btn in enumerate(self.archive_buttons):
            slot_idx = start_idx + i
            if i >= visible_count or slot_idx >= total:
                btn.hide()
                continue
            raw = self.data["archive_temp_presets"][slot_idx]
            text = (raw[:100] if len(raw) > 100 else raw).replace("\n", " ").strip()
            display_idx = slot_idx + 1
            line_count = raw.count("\n") + 1 if raw.strip() else 0
            line_str = str(line_count) if line_count > 0 else ""
            
            from fastprompter.ui.file_container import silo_file_count
            fcount = silo_file_count(self._files_root(), self.get_current_category(), raw)
            if fcount > 0:
                line_str = f"📁{fcount} " + line_str
            label = f"{display_idx}: {text}" if text else f"{display_idx}"
            is_active = (
                getattr(self, "active_is_archive", False)
                and (slot_idx == self.active_temp_slot)
                and not getattr(self, "editing_snippet", None)
            )
            bg_color = active_color if is_active else inactive_color
            title_bold = (
                self.data.get("bold_hash_titles", "True") == "True"
                and raw.lstrip().startswith("#")
            )
            btn.update_data(label, slot_idx, bg_color, font_family, scale, line_count_str=line_str, is_pushed=is_active, title_bold=title_bold)
            btn.show()

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
                if hasattr(self, "archive_docs") and i < len(self.archive_docs):
                    new_docs.append(self.archive_docs[i])
        if len(new_entries) == len(entries):
            return
        self._rebind_visible_lists(archive=new_entries)
        if hasattr(self, "archive_docs"):
            self.archive_docs = new_docs
        if getattr(self, "active_is_archive", False):
            old_idx = getattr(self, "active_temp_slot", -1)
            if old_idx in old_to_new:
                self.active_temp_slot = old_to_new[old_idx]
            elif new_entries:
                self.active_temp_slot = 0
            else:
                self.active_is_archive = False
                self.active_temp_slot = max(
                    0, min(self.active_temp_slot, len(self.data["temp_presets"]) - 1)
                )
        self.mark_dirty()

    # move_preset_to_index is defined earlier in the class (uses pop+insert with undo)

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

    def navigate_silo(self, delta):
        """Move silo selection up/down the sidebar (Alt+Up / Alt+Down)."""
        is_arc = getattr(self, "active_is_archive", False)
        presets = self.data["archive_temp_presets" if is_arc else "temp_presets"]
        if not presets:
            return
        if is_arc:
            order = list(range(len(presets)))
        else:
            # Follow the visual order: pinned silos first, then the rest
            pinned = self.data.get("pinned_silos", [])
            if isinstance(pinned, str):
                import ast

                try:
                    pinned = ast.literal_eval(pinned)
                except Exception:
                    pinned = []
            total = len(presets)
            order = [p for p in pinned if p < total] + [
                j for j in range(total) if j not in pinned
            ]
        try:
            pos = order.index(self.active_temp_slot)
        except ValueError:
            pos = 0
        new_pos = max(0, min(len(order) - 1, pos + delta))
        if order[new_pos] != self.active_temp_slot or self.editing_snippet:
            self._switch_to_slot(order[new_pos], is_archive=is_arc)

    def _switch_to_slot(self, idx, initial=False, is_archive=False):
        if is_archive:
            self.arc_silo_page = idx // 10
        else:
            self.silo_page = idx // max(1, self._visible_silos)

        was_editing_snippet = bool(getattr(self, "editing_snippet", None))
        was_archive = getattr(self, "active_is_archive", False)

        if not initial:
            self.play_click_sound()
            self._cache_timer.stop()
            if was_editing_snippet:
                self.save_snippet(silent=True)
            elif was_archive:
                new_txt = self.text_area.toPlainText()
                if new_txt.strip() and 0 <= self.active_temp_slot < len(
                    self.data.get("archive_temp_presets", [])
                ):
                    self._sync_silo_folder(
                        self.get_current_category(),
                        self.data["archive_temp_presets"][self.active_temp_slot],
                        new_txt,
                    )
                    self.data["archive_temp_presets"][self.active_temp_slot] = new_txt
            else:
                old_slot = self.active_temp_slot
                new_text = self.text_area.toPlainText()
                if 0 <= old_slot < len(self.data["temp_presets"]):
                    old_text = self.data["temp_presets"][old_slot]
                    self._sync_silo_folder(self.get_current_category(), old_text, new_text)
                    self.data["temp_presets"][old_slot] = new_text
                    if new_text != old_text:
                        self.silo_last_edited[old_slot] = int(time.time())

        if not is_archive:
            if "temp_presets" not in self.data or not self.data["temp_presets"]:
                self._rebind_visible_lists(temp=[""])
            if idx >= len(self.data["temp_presets"]):
                idx = max(0, len(self.data["temp_presets"]) - 1)
        else:
            if "archive_temp_presets" not in self.data or not self.data["archive_temp_presets"]:
                self._rebind_visible_lists(archive=[""])
            if idx >= len(self.data["archive_temp_presets"]):
                idx = max(0, len(self.data["archive_temp_presets"]) - 1)

        # If we are already on this silo and not editing a snippet, early return
        if (
            not initial
            and not was_editing_snippet
            and self.active_temp_slot == idx
            and getattr(self, "active_is_archive", False) == is_archive
        ):
            self._begin_batch_update()
            try:
                self.text_area.setFocus()
                self.text_area.ensureCursorVisible()
                if is_archive:
                    self.refresh_archive_panel()
                else:
                    self.refresh_temp_presets()
            finally:
                self._end_batch_update()
            return

        if not initial:
            self.add_data_undo_state("Switch silo")

        self._begin_batch_update()
        try:
            self.cancel_editing(silent=True)
            self.active_temp_slot = idx
            self.active_is_archive = is_archive

            self._suspend_cache = True
            try:
                self.text_area.blockSignals(True)

                if is_archive:
                    while len(self.archive_docs) <= idx:
                        from PyQt6.QtGui import QTextDocument

                        d = QTextDocument()
                        d.setDefaultFont(self.text_area.font())
                        self.archive_docs.append(d)
                    doc = self.archive_docs[idx]
                    archive = self.data.get("archive_temp_presets", [])
                    if idx >= len(archive):
                        archive = archive + [""] * (idx + 1 - len(archive))
                        self._rebind_visible_lists(archive=archive)
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
            self._update_line_count_label()
            self._update_files_button()
            self.text_area.setFocus()
            self.text_area.ensureCursorVisible()
            if not initial:
                self.mark_dirty()
        finally:
            self._end_batch_update()

    def _switch_to_arc_slot(self, idx):
        self._switch_to_slot(idx, is_archive=True)

    def refresh_temp_presets(self):
        total = len(self.data["temp_presets"])
        if total == 0:
            self.silos_section.setVisible(False)
            return
        if not hasattr(self, "silos_widget") or not hasattr(self, "silo_buttons"):
            return

        self.silos_section.setVisible(True)

        self._update_visible_silo_count()
        max_page = max(0, math.ceil(total / max(1, self._visible_silos)) - 1)
        self.silo_page = min(self.silo_page, max_page)

        self.btn_silo_up.setVisible(max_page > 0)
        self.btn_silo_down.setVisible(max_page > 0)
        self.btn_silo_up.setEnabled(self.silo_page > 0)
        self.btn_silo_down.setEnabled(self.silo_page < max_page)

        theme_name = self.data.get("theme", "Default")
        if theme_name not in THEMES:
            theme_name = "Default"
        active_color = THEMES[theme_name]["active_temp_color"]
        inactive_color = THEMES[theme_name]["inactive_temp_color"]

        try:
            scale = float(self.data.get("ui_scale", "1.0"))
        except Exception:
            scale = 1.0
        font_family = self.data.get("font_family", "Verdana")

        start_idx = self.silo_page * self._visible_silos
        # Build sorted display order: pinned first in pin order, then unpinned by index
        pinned_list = self.data.get("pinned_silos", [])
        if isinstance(pinned_list, str):
            import ast

            try:
                pinned_list = ast.literal_eval(pinned_list)
            except Exception:
                pinned_list = []
        # Compute display order: pinned first (preserving pin-list order), then unpinned (by natural index)
        unpinned = [j for j in range(total) if j not in pinned_list]
        display_order = [p for p in pinned_list if p < total] + unpinned
        if not hasattr(self, "silo_gap_widget"):
            from PyQt6.QtWidgets import QFrame
            self.silo_gap_widget = QFrame(self)
            self.silo_gap_widget.setFixedHeight(8)
            self.silo_gap_widget.setStyleSheet("border-top: 1px solid #5a5a40; border-bottom: 1px solid #1a1a10; margin: 2px 8px; background: transparent;")
            self.silos_widget.layout.addWidget(self.silo_gap_widget)
            
        self.silos_widget.layout.removeWidget(self.silo_gap_widget)
        self.silo_gap_widget.hide()

        first_unpinned_ui_index = -1
        show_gap = self.data.get("silo_pinned_gap", "True") == "True"

        for i, btn in enumerate(self.silo_buttons):
            disp_pos = start_idx + i
            if disp_pos >= total or i >= self._visible_silos:
                btn.hide()
                continue
            slot_idx = display_order[disp_pos]
            raw = self.data["temp_presets"][slot_idx]
            is_pinned = slot_idx in pinned_list
            
            if not is_pinned and first_unpinned_ui_index == -1 and pinned_list:
                first_unpinned_ui_index = i

            text = (raw[:100] if len(raw) > 100 else raw).replace("\n", " ").strip()
            
            if is_pinned:
                display_idx = pinned_list.index(slot_idx) + 1
            else:
                display_idx = unpinned.index(slot_idx) + 1
                
            line_count = raw.count("\n") + 1 if raw.strip() else 0
            line_str = str(line_count) if line_count > 0 else ""
            
            from fastprompter.ui.file_container import silo_file_count
            fcount = silo_file_count(self._files_root(), self.get_current_category(), raw)
            if fcount > 0:
                line_str = f"📁{fcount} " + line_str
            pin_str = "📌 " if is_pinned else ""
            label = f"{pin_str}{display_idx}: {text}" if text else f"{pin_str}{display_idx}"
            is_active = (
                (not getattr(self, "active_is_archive", False))
                and (slot_idx == self.active_temp_slot)
                and not getattr(self, "editing_snippet", None)
            )
            bg_color = active_color if is_active else inactive_color
            if text and slot_idx in self.silo_last_edited:
                bg_color = self._overlay_silo_bg(bg_color, self.silo_last_edited[slot_idx])
            title_bold = (
                self.data.get("bold_hash_titles", "True") == "True"
                and raw.lstrip().startswith("#")
            )
            btn.update_data(label, slot_idx, bg_color, font_family, scale, line_count_str=line_str, is_pushed=is_active, title_bold=title_bold)

        if show_gap and first_unpinned_ui_index != -1:
            # layout contains the buttons, so insertWidget at first_unpinned_ui_index puts it before that button
            # Note: since we removed it, the buttons are contiguous at indices 0..N
            self.silos_widget.layout.insertWidget(first_unpinned_ui_index, self.silo_gap_widget)
            self.silo_gap_widget.show()

    def _overlay_silo_bg(self, bg_color, last_ts):
        diff = time.time() - last_ts
        custom = self._get_custom_colors()
        if diff < 60:
            overlay = QColor(custom.get("overlay_new", "#6a5555"))
        elif diff < 3600:
            overlay = QColor(custom.get("overlay_recent", "#6a5a40"))
        elif diff < 86400:
            overlay = QColor(custom.get("overlay_day", "#5a5a30"))
        elif diff < 4233600:
            overlay = QColor(custom.get("overlay_old", "#40506a"))
        else:
            overlay = None
        if overlay:
            base = QColor(bg_color)
            return self.blend_colors(base, overlay, 0.25)
        return bg_color

    @staticmethod
    def blend_colors(c1, c2, ratio):
        return f"#{int(c1.red() * (1 - ratio) + c2.red() * ratio):02x}{int(c1.green() * (1 - ratio) + c2.green() * ratio):02x}{int(c1.blue() * (1 - ratio) + c2.blue() * ratio):02x}"

    def show_temp_menu(self, idx, pos, is_archive=False):
        cur = self.text_area.toPlainText().strip()
        menu = QMenu(self)
        menu.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        menu.setFont(QApplication.font())

        has_content = (
            is_archive
            and idx < len(self.data.get("archive_temp_presets", []))
            and self.data["archive_temp_presets"][idx]
        ) or (
            not is_archive
            and idx < len(self.data["temp_presets"])
            and self.data["temp_presets"][idx]
        )

        # -- everyday actions ------------------------------------------------
        if not is_archive:
            pinned_list = self.data.get("pinned_silos", [])
            if isinstance(pinned_list, str):
                import ast
                try:
                    pinned_list = ast.literal_eval(pinned_list)
                except Exception:
                    pinned_list = []
            if idx in pinned_list:
                menu.addAction("📌 Unpin", lambda i=idx: self._toggle_pin_silo(i))
            else:
                menu.addAction("📌 Pin to Top", lambda i=idx: self._toggle_pin_silo(i))
            menu.addAction("📥 Archive", lambda i=idx: self.archive_single_silo(i))
        menu.addAction("📁 Files…", lambda i=idx, a=is_archive: self.open_file_container(i, a))

        # -- save ---------------------------------------------------------------
        if cur:
            menu.addSeparator()
            menu.addAction("💾 Save text as Snippet", self.save_snippet)
            menu.addAction("💾 Save as Snippet #…", self.save_snippet_as_number)

        # -- destructive (grouped at the bottom of the section) ---------------
        if has_content:
            menu.addSeparator()
            menu.addAction("🧹 Clear (files kept in trash)",
                           lambda: self.clear_temp(idx, is_archive))
            menu.addAction("🗑 Move to Trash",
                           lambda i=idx, a=is_archive: self.trash_silo(i, a))
            menu.addAction("🗂 Open Trash Folder", self.open_trash_folder)

        menu.addSeparator()
        # Transfer to Snippet
        presets_list = (
            self.data["archive_temp_presets"] if is_archive else self.data["temp_presets"]
        )
        if idx < len(presets_list) and presets_list[idx] and presets_list[idx].strip():
            menu.addAction(
                "➡ Transfer to Snippet",
                lambda i=idx, a=is_archive: self._transfer_to_snippet(i, a),
            )
            transfer_menu = menu.addMenu("➡ Transfer to Project")
            for cat_name in self.data.get("cats_order", list(self.data["categories"].keys())):
                if cat_name not in self.data["categories"]:
                    continue
                transfer_menu.addAction(
                    cat_name,
                    lambda i=idx, a=is_archive, c=cat_name: self._transfer_to_snippet(i, a, target_cat=c),
                )
            menu.addAction(
                "⬇ Move to Bottom",
                lambda i=idx, a=is_archive: self._move_silo_to_bottom(i, a),
            )

        # Replace Silo submenu — shows all non-empty silos to copy text from
        presets = self.data["archive_temp_presets"] if is_archive else self.data["temp_presets"]
        replace_menu = menu.addMenu("🔁 Replace from…")
        has_source = False
        for src_i, src_text in enumerate(presets):
            if src_i == idx or not src_text or not src_text.strip():
                continue
            has_source = True
            label = src_text.strip().replace("\n", " ")[:30] + (
                "…" if len(src_text.strip()) > 30 else ""
            )
            act_label = f"Silo {src_i + 1}: {label}"

            def make_replace(target_idx=idx, src_idx=src_i, archive=is_archive):
                def do_replace():
                    src_presets = (
                        self.data["archive_temp_presets"] if archive else self.data["temp_presets"]
                    )
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



    def _transfer_to_snippet(self, idx, is_archive, target_cat=None):
        """Transfer silo content to a new snippet in the current (or given) category."""
        presets = self.data["archive_temp_presets"] if is_archive else self.data["temp_presets"]
        if idx >= len(presets) or not presets[idx] or not presets[idx].strip():
            return
        text = presets[idx]
        cat = target_cat if target_cat in self.data["categories"] else self.get_current_category()
        if not cat:
            return
        slots = self.data["categories"][cat]
        if None not in slots:
            return
        self.add_data_undo_state("Transfer to snippet")
        empty_idx = slots.index(None)
        name = text.replace("\n", " ")[:22]
        if len(text) > 22:
            name += "..."
        slots[empty_idx] = {"name": name, "text": text, "last_edited": int(time.time())}
        presets[idx] = ""
        if idx == self.active_temp_slot and not getattr(self, "editing_snippet", None):
            self.clear_text(internal=True)
        self.mark_dirty()
        self.refresh_snippets_panel()
        self.refresh_temp_presets()
        self.play_sound("snippet")

    def _toggle_tick_silo(self, idx):
        """Toggle the ✅ done-mark on a silo (persists per project)."""
        self.add_data_undo_state("Tick silo")
        ticked = self.data.get("silo_ticked", [])
        if not isinstance(ticked, list):
            ticked = []
            self.data["silo_ticked"] = ticked
        if idx in ticked:
            ticked.remove(idx)
        else:
            ticked.append(idx)
        self.play_tick_sound()
        self.mark_dirty()
        self.refresh_temp_presets()

    def _toggle_pin_silo(self, idx):
        """Toggle pin/unpin status for a silo."""
        self.add_data_undo_state("Pin silo")
        pinned = self.data.get("pinned_silos", [])
        if not isinstance(pinned, list):
            pinned = []
            self.data["pinned_silos"] = pinned
        if idx in pinned:
            pinned.remove(idx)
        else:
            pinned.insert(0, idx)
        self.mark_dirty()
        self.refresh_temp_presets()

    def _move_silo_to_bottom(self, idx, is_archive=False):
        """Move a silo to the bottom of the order."""
        presets = self.data["archive_temp_presets"] if is_archive else self.data["temp_presets"]
        docs = self.archive_docs if is_archive else self.silo_docs
        if not (0 <= idx < len(presets)):
            return
        if idx == len(presets) - 1:
            return  # already at bottom
        self.add_data_undo_state("Move silo to bottom")
        text = presets.pop(idx)
        if idx < len(docs):
            doc = docs.pop(idx)
        else:
            doc = None
        presets.append(text)
        if doc is not None:
            docs.append(doc)
        # Adjust active slot if needed
        if not is_archive:
            if idx == getattr(self, "active_temp_slot", 0):
                self.active_temp_slot = len(presets) - 1
            elif idx < getattr(self, "active_temp_slot", 0):
                self.active_temp_slot -= 1
        self.mark_dirty()
        self.refresh_temp_presets()

    def clear_temp(self, idx, is_archive=False):
        # Clicking clear on an already-empty silo removes the slot entirely.
        presets = self.data["archive_temp_presets"] if is_archive else self.data["temp_presets"]
        if (
            0 <= idx < len(presets)
            and not presets[idx].strip()
            and len(presets) > 1
            and getattr(self, "active_is_archive", False) == is_archive
        ):
            self.del_silo(idx)
            return
        self.add_data_undo_state("Clear silo")
        self.play_sound("clear")
        
        if 0 <= idx < len(presets):
            old_text = presets[idx]
            if hasattr(self, "_delete_file_container"):
                self._delete_file_container(self.get_current_category(), old_text)

        if is_archive:
            self.data["archive_temp_presets"][idx] = ""
            if idx == self.active_temp_slot and getattr(self, "active_is_archive", False):
                self.clear_text(internal=True)
            self._trim_archive()
            self.refresh_archive_panel()
        else:
            self.data["temp_presets"][idx] = ""
            if idx == self.active_temp_slot and not getattr(self, "active_is_archive", False):
                self.clear_text(internal=True)
            self.refresh_temp_presets()
        self.mark_dirty()

    def archive_single_silo(self, idx):
        """Archive a specific silo by index (called from hover button)."""
        if getattr(self, "active_is_archive", False):
            return
        if not (0 <= idx < len(self.data.get("temp_presets", []))):
            return
        text = self.data["temp_presets"][idx]
        if not text.strip():
            return
        if idx == self.active_temp_slot:
            text = self.text_area.toPlainText().strip()
            if not text:
                return
            self.data["temp_presets"][idx] = text
        self.add_data_undo_state("Archive silo")
        # Move to archive
        if "archive_temp_presets" not in self.data:
            self.data["archive_temp_presets"] = []
        self.data["archive_temp_presets"].append(self.data["temp_presets"][idx])
        self.data["temp_presets"][idx] = ""
        # Sync docs
        from PyQt6.QtGui import QTextDocument
        font = self.text_area.font()
        arc_doc = QTextDocument()
        arc_doc.setDefaultFont(font)
        arc_doc.setPlainText(text)
        self.archive_docs.append(arc_doc)
        if idx < len(self.silo_docs):
            self.silo_docs[idx].setPlainText("")
        # If archiving active silo, clear text area
        if idx == self.active_temp_slot and not getattr(self, "active_is_archive", False):
            self.clear_text(internal=True)
        self._trim_archive()
        self.mark_dirty()
        self.refresh_temp_presets()
        self.refresh_archive_panel()

    def safe_set_clipboard(self, text):
        if text:
            from PyQt6.QtGui import QGuiApplication

            clip = QGuiApplication.clipboard()
            clip.setText(text)

    def insert_divider_line(self):
        """Ctrl+W: alias for the toolbar's Insert Line command — single
        implementation lives in FormattingMixin.insert_add_line so the two
        entry points can never silently diverge again."""
        self.insert_add_line()

    def auto_paste(self, text):
        if not text.strip():
            return
        self.safe_set_clipboard(text)
        self.hide_and_save()
        QTimer.singleShot(150, lambda: not sip.isdeleted(self) and self.simulate_ctrl_v())

    @staticmethod
    def simulate_ctrl_v():
        class KEYBDINPUT(ctypes.Structure):
            _fields_ = (
                ("wVk", ctypes.c_ushort),
                ("wScan", ctypes.c_ushort),
                ("dwFlags", ctypes.c_ulong),
                ("time", ctypes.c_ulong),
                ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
            )

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

        for vk in (VK_SHIFT, VK_MENU, VK_LWIN, VK_RWIN):
            if ctypes.windll.user32.GetAsyncKeyState(vk) & 0x8000:
                send_key(vk, True)

        send_key(VK_CTRL)
        send_key(VK_V)
        send_key(VK_V, True)
        send_key(VK_CTRL, True)

    def setup_global_shortcuts(self):
        QShortcut(QKeySequence("Ctrl+D"), self).activated.connect(self.toggle_focus_mode)
        QShortcut(QKeySequence("Ctrl+F"), self).activated.connect(self.show_find)
        QShortcut(QKeySequence("Ctrl+H"), self).activated.connect(self.show_replace)
        QShortcut(QKeySequence("Ctrl+Shift+S"), self).activated.connect(self.save_silo_to_file)
        QShortcut(QKeySequence("Esc"), self).activated.connect(self._on_escape)
        QShortcut(QKeySequence("Ctrl+S"), self).activated.connect(self.save_snippet)
        QShortcut(
            QKeySequence("Ctrl+N"), self, context=Qt.ShortcutContext.ApplicationShortcut
        ).activated.connect(self.select_empty_silo)
        QShortcut(
            QKeySequence("Ctrl+W"), self, context=Qt.ShortcutContext.ApplicationShortcut
        ).activated.connect(self.insert_divider_line)
        QShortcut(
            QKeySequence("Alt+W"), self, context=Qt.ShortcutContext.ApplicationShortcut
        ).activated.connect(self.insert_old_add_line)
        QShortcut(QKeySequence("Ctrl+Shift+Z"), self).activated.connect(self.redo_action)
        # Fires when focus is outside the editor (the editor overrides it while
        # focused and routes through VaultTextEdit.keyPressEvent instead)
        QShortcut(QKeySequence("Ctrl+Z"), self).activated.connect(self._smart_undo)
        # Keyboard silo navigation in the sidebar
        QShortcut(
            QKeySequence("Alt+Up"), self, context=Qt.ShortcutContext.ApplicationShortcut
        ).activated.connect(lambda: self.navigate_silo(-1))
        QShortcut(
            QKeySequence("Alt+Down"), self, context=Qt.ShortcutContext.ApplicationShortcut
        ).activated.connect(lambda: self.navigate_silo(1))
        for i in range(1, 11):
            key_num = i % 10
            QShortcut(QKeySequence(f"F{i}"), self).activated.connect(
                lambda i=i: self.fire_shortcut(i)
            )
            QShortcut(QKeySequence(f"Ctrl+{key_num}"), self).activated.connect(
                lambda i=i: self._switch_to_slot(i - 1)
            )
            QShortcut(QKeySequence(f"Ctrl+Shift+{key_num}"), self).activated.connect(
                lambda i=i: self.fire_shortcut(i)
            )
        QShortcut(QKeySequence("Ctrl+Q"), self).activated.connect(self.cycle_snap_corner)
        QShortcut(QKeySequence("Ctrl+Alt+Shift+Q"), self).activated.connect(self.quit_app)
        QShortcut(QKeySequence("Ctrl+E"), self).activated.connect(self.apply_header_timestamp)
        QShortcut(QKeySequence("Ctrl+B"), self).activated.connect(self.apply_bold_smart)
        QShortcut(QKeySequence("Ctrl+I"), self).activated.connect(
            lambda: self.apply_format("italic"))
        QShortcut(QKeySequence("Ctrl+U"), self).activated.connect(
            lambda: self.apply_format("underline"))
        QShortcut(QKeySequence("Ctrl+T"), self).activated.connect(
            lambda: self.apply_format("strike"))

    def fire_shortcut(self, idx):
        self.play_sound("snippet")
        cat = self.get_current_category()
        if not cat:
            return
        query = self._snippet_query()
        active_items = []
        for i, s in enumerate(self.data["categories"][cat]):
            if s is not None:
                if not query or query in s["name"].lower() or query in s["text"].lower():
                    active_items.append((i, s))

        page = self.current_pages.get(cat, 0)
        start_idx = page * 10
        page_items = active_items[start_idx : start_idx + 10]

        i = idx - 1
        if i < len(page_items):
            global_idx, item = page_items[i]
            self.auto_paste(item["text"])

    def show_quick_list(self):
        self.play_sound("tick")
        w = QuickListWidget(self)
        w.show()

    def fire_global_snippet(self, idx):
        self.play_sound("snippet")
        cat = self.get_current_category()
        if not cat:
            return
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
        if not cat:
            return
        active_snippets = [s for s in self.data["categories"].get(cat, []) if s is not None]
        if 0 <= idx < len(active_snippets):
            self.auto_paste(active_snippets[idx]["text"])

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

        if getattr(self, "_snap_first_press", True):
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

    _TS_RE = None  # compiled lazily below

    def _update_line_count_label(self):
        lbl = getattr(self, "lbl_line_count", None)
        if lbl is None or sip.isdeleted(lbl):
            return
        doc = self.text_area.document()
        lines = doc.blockCount() if doc.characterCount() > 1 else 0
        
        from PyQt6.QtGui import QFontMetrics
        fm = QFontMetrics(lbl.font())
        # minimum stays tiny so the header can pack into a quarter-FullHD
        # window; the layout still grants the full sizeHint when there is room
        needed_width = fm.horizontalAdvance("0 L") + 4
        if lbl.minimumWidth() != needed_width:
            lbl.setMinimumWidth(needed_width)
            from PyQt6.QtCore import Qt
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            
        lbl.setText(f"{lines} L" if lines else "")

    def refresh_timestamp_in_block(self, block):
        """Replace a line's (DD.MM - hh:mm) stamp with right now — used by
        the inline refresh glyph painted after stamped lines."""
        import datetime

        from fastprompter.ui.editor import TS_STAMP_LINE_RE
        m = TS_STAMP_LINE_RE.search(block.text())
        if not m:
            return
        
        now = datetime.datetime.now()
        h = now.hour
        if 5 <= h < 12: daypart = "Morning"
        elif 12 <= h < 17: daypart = "Day"
        elif 17 <= h < 22: daypart = "Evening"
        else: daypart = "Night"
        text_month = self.data.get("date_text_month", "False") == "True"
        m_fmt = "%d %b" if text_month else "%d.%m"
        ts = now.strftime(f"{m_fmt} - %H:%M")
        
        now_str = f"{daypart} {ts}" if self.data.get("date_daypart", "True") == "True" else ts
        doc = self.text_area.document()
        cur = self.text_area.textCursor()
        keep = cur.position()
        cur.setPosition(block.position() + m.start())
        cur.setPosition(block.position() + m.end(), QTextCursor.MoveMode.KeepAnchor)
        cur.insertText(now_str)
        cur.setPosition(min(keep, doc.characterCount() - 1))
        self.text_area.setTextCursor(cur)
        self.play_tick_sound()
        self.mark_dirty()

    def _on_text_changed(self):
        self._last_text_edit_time = self._bump_action_seq()
        self._update_line_count_label()
        doc = self.text_area.document()
        count = doc.characterCount()
        if count > 50000:
            interval = 2500
        elif count > 20000:
            interval = 1500
        else:
            interval = 800
        if interval != self._cache_timer_interval:
            self._cache_timer_interval = interval
            self._cache_timer.setInterval(interval)
        self._cache_timer.start()

    def _on_cache_timer(self):
        self.cache_current_text()

    def cache_current_text(self):
        if hasattr(self, "_last_deleted_preset"):
            self._last_deleted_preset = None
        if hasattr(self, "_last_deleted_silo_data"):
            self._last_deleted_silo_data = None
        if getattr(self, "_suspend_cache", False):
            return
        if getattr(self, "_initializing_ui", False):
            return
        if getattr(self, "_cache_in_progress", False):
            return
        self._cache_in_progress = True
        try:
            current_text = self.text_area.toPlainText()
            self._last_cached_text = current_text
            if not self.editing_snippet:
                if 0 <= self.active_temp_slot < len(self.data["temp_presets"]):
                    old_text = self.data["temp_presets"][self.active_temp_slot]
                    self.data["temp_presets"][self.active_temp_slot] = current_text
                    if current_text != old_text:
                        self.mark_dirty()
                        self.silo_last_edited[self.active_temp_slot] = int(time.time())
                        self.refresh_temp_presets()
            else:
                cat, idx = self.editing_snippet
                if cat in self.data["categories"] and self.data["categories"][cat][idx]:
                    self.data["categories"][cat][idx]["text"] = current_text
                    if cat == self.get_current_category():
                        if len(current_text) > 100:
                            t = current_text[:100].replace(chr(10), " ").strip()
                        else:
                            t = current_text.replace(chr(10), " ").strip()
                        display_idx = idx + 1
                        label = (
                            f"{display_idx}: {t[:22]}…"
                            if len(t) > 22
                            else (f"{display_idx}: {t}" if t else str(display_idx))
                        )
                        main_btn = self._snippet_widget_cache.get((cat, idx))
                        if main_btn is None:
                            layout = getattr(self, "snippets_widget", None)
                            if layout and hasattr(layout, "layout"):
                                for i in range(layout.layout.count()):
                                    item = layout.layout.itemAt(i)
                                    if item and item.widget():
                                        widget = item.widget()
                                        main_btn = getattr(widget, "main_btn", None)
                                        if (
                                            main_btn
                                            and getattr(main_btn, "cat", None) == cat
                                            and getattr(main_btn, "global_idx", None) == idx
                                        ):
                                            self._snippet_widget_cache[(cat, idx)] = main_btn
                                            break
                        if main_btn:
                            main_btn.setText(label)
        finally:
            self._cache_in_progress = False

    @staticmethod
    def _set_plain_text_clean(target, text):
        doc = target.document() if hasattr(target, "document") else target
        large = doc.blockCount() > 500 or len(text) > 10000
        if not large:
            doc.setUndoRedoEnabled(False)
        doc.setPlainText(text)
        if not large:
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
            if hasattr(self, "ipc"):
                self.ipc.close()
        except Exception:
            pass
        try:
            if hasattr(self, "conn") and self.conn:
                self.conn.close()
        except Exception:
            pass
        # Null out every reference so the closeEvent save triggered by
        # QApplication.quit() doesn't touch the closed connection.
        self.conn = None
        if hasattr(self, "state"):
            self.state.conn = None
        try:
            if hasattr(self, "tray_icon"):
                self.tray_icon.hide()
        except Exception:
            pass
        QApplication.quit()


def setup_exception_hook():
    """Ensure unhandled exceptions are visible (written to crash.log and shown as MessageBox)."""
    import traceback

    old_hook = sys.excepthook

    def hook(typ, val, tb):
        error_msg = "".join(traceback.format_exception(typ, val, tb))
        crash_log = os.path.join(get_data_dir(), "crash.log")
        try:
            with open(crash_log, "a") as f:
                f.write(error_msg + chr(10))
        except Exception:
            pass
        ctypes.windll.user32.MessageBoxW(
            0, "FastPrompter Error:" + chr(10) * 2 + f"{error_msg}", "FastPrompter Error", 0x10
        )
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
    global_font.setStyleStrategy(
        QFont.StyleStrategy.NoAntialias | QFont.StyleStrategy.NoSubpixelAntialias
    )
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
