import copy
import ctypes
import ctypes.wintypes
import math
import os
import datetime
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
    QGridLayout,
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
from fastprompter.core.translations import tr, set_language, get_language, available_languages
from fastprompter.core.i18n import NATIVE_NAMES as _LANG_NATIVE_NAMES
from fastprompter.utils.textfit import clip_safe_width


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
        self._focus_lock_count = 0

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
        import threading
        self._undo_save_lock = threading.Lock()
        self._load_undo_state()
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
        # Per-slot unique file-folder names {slot: name} per category
        fdall = self.data.get("silo_folders_all")
        if not isinstance(fdall, dict):
            fdall = {}
        if not fdall and isinstance(self.data.get("silo_folders"), dict) and self.data["silo_folders"]:
            fdall[first_cat] = self.data["silo_folders"]
        self.data["silo_folders_all"] = fdall
        self.data["silo_folders"] = fdall.setdefault(first_cat, {})
        # Silo hierarchy: {parent: [children]} per category; JSON round-trips
        # dict keys as strings — normalize everything back to int.
        call = self.data.get("silo_children_all")
        if not isinstance(call, dict):
            call = {}
        if not call and isinstance(self.data.get("silo_children"), dict) and self.data["silo_children"]:
            call[first_cat] = self.data["silo_children"]
        norm_call = {}
        for c, cmap in call.items():
            try:
                norm_call[c] = {int(k): [int(x) for x in v] for k, v in cmap.items()}
            except Exception:
                norm_call[c] = {}
        self.data["silo_children_all"] = norm_call
        self.data["silo_children"] = norm_call.setdefault(first_cat, {})
        coll_all = self.data.get("silo_collapsed_all")
        if not isinstance(coll_all, dict):
            coll_all = {}
        if not coll_all and isinstance(self.data.get("silo_collapsed"), list) and self.data["silo_collapsed"]:
            coll_all[first_cat] = [int(x) for x in self.data["silo_collapsed"]]
        self.data["silo_collapsed_all"] = coll_all
        self.data["silo_collapsed"] = coll_all.setdefault(first_cat, [])
        # Per-slot project folder/executable links per category. This alias
        # was missing at boot (only wired in on_tab_changed), so on any
        # session where the user never switched tabs, saved paths lived in
        # the flat key only; the moment a tab switch DID happen it got
        # clobbered by the still-empty _all store -> "unreliable" paths.
        ppall = self.data.get("silo_project_paths_all")
        if not isinstance(ppall, dict):
            ppall = {}
        if not ppall and isinstance(self.data.get("silo_project_paths"), dict) and self.data["silo_project_paths"]:
            ppall[first_cat] = self.data["silo_project_paths"]
        self.data["silo_project_paths_all"] = ppall
        self.data["silo_project_paths"] = ppall.setdefault(first_cat, {})
        apall = self.data.get("archive_project_paths_all")
        if not isinstance(apall, dict):
            apall = {}
        if not apall and isinstance(self.data.get("archive_project_paths"), dict) and self.data["archive_project_paths"]:
            apall[first_cat] = self.data["archive_project_paths"]
        self.data["archive_project_paths_all"] = apall
        self.data["archive_project_paths"] = apall.setdefault(first_cat, {})

        self._current_lang = get_language(self.data)
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

    def _clock_time_fmt(self, show_secs=False):
        """strftime format for hh:mm[:ss], honoring the 12h/AM-PM setting."""
        ampm = self.data.get("date_ampm", "False") == "True"
        if ampm:
            return "%I:%M:%S %p" if show_secs else "%I:%M %p"
        return "%H:%M:%S" if show_secs else "%H:%M"

    def _update_date_label(self):
        if hasattr(self, "analog_clock"):
            self.analog_clock.sync()
        show_date = self.data.get("show_date_rect", "True") == "True"
        if not show_date:
            self.lbl_date.setVisible(False)
            return

        self.lbl_date.setVisible(True)
        now = datetime.datetime.now()
        # The full clock (seconds + day word) must fit even at the Ctrl+Q
        # quarter-FullHD snap — dense mode wins the pixels from buttons and
        # paddings, never by silently dropping what the user enabled.
        show_secs = self.data.get("date_seconds", "True") == "True"
        show_word = self.data.get("date_daypart", "True") == "True"
        text_month = self.data.get("date_text_month", "False") == "True"
        ampm = self.data.get("date_ampm", "False") == "True"
        if getattr(self, "_header_ultra", False):
            # portrait sliver: the clock keeps only DD.MM - hh:mm
            show_secs = show_word = text_month = False
        m_fmt = "%d %b" if text_month else "%d.%m"
        t_fmt = self._clock_time_fmt(show_secs)
        dt_str = now.strftime(f"{m_fmt} - {t_fmt}")
        ampm_ref = " PM" if ampm else ""
        if show_secs:
            ref_str = ("00 MMM - 00:00:00" if text_month else "00.00 - 00:00:00") + ampm_ref
        else:
            ref_str = ("00 MMM - 00:00" if text_month else "00.00 - 00:00") + ampm_ref
        if show_word:
            use_emoji = self.data.get("date_emoji", "False") == "True"
            if use_emoji:
                emoji = {"Morning": "🌅", "Day": "☀️", "Evening": "🌇", "Night": "🌙"}.get(self._day_part(now.hour), "")
                dt_str += f" {emoji}"
                ref_str += " ☀️"
            else:
                dt_str += f" · {tr(self._day_part(now.hour), self._current_lang)}"
                ref_str += " · Morning"

        from PyQt6.QtGui import QFontMetrics
        f = QFont(self.lbl_date.font())
        f.setPixelSize(11)  # the app stylesheet renders 11px regardless of QFont
        fm = QFontMetrics(f)
        pad = 0 if getattr(self, "_header_dense", False) else 8
        needed_width = fm.horizontalAdvance(ref_str) + pad
        if self.lbl_date.minimumWidth() != needed_width:
            self.lbl_date.setMinimumWidth(needed_width)
            self.lbl_date.setMaximumWidth(needed_width + pad)
            from PyQt6.QtCore import Qt
            self.lbl_date.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.lbl_date.setText(dt_str)

    # (button, normal label, dense label) — dense squeezes into a
    # Ctrl+Q quarter-FullHD window without hiding anything
    _DENSE_LABELS = (
        ("btn_new", "NEW", "NEW"),
        ("btn_save", "Save", "Save"),
        ("btn_clear_fmt", "Clear Fmt", "CF"),
        ("btn_add_line", "Line", "─"),
        ("btn_copy", "Copy", "⧉"),
        ("btn_clear", "Clear", "✕"),
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

        # Ultra tier (portrait / 9:16 slivers): only the essentials survive —
        # tabs, NEW/Save, a short DD.MM - hh:mm clock, line counter, ⚙.
        # Formatting stays reachable via hotkeys and the context menu.
        # Dense hides only the two rarest text buttons (Clear Fmt, Line) —
        # both reachable via the editor's right-click menu and Ctrl+W. The
        # bullet-toggle (-→•) stays visible; it only drops in ultra.
        if flipped:
            for name in ("btn_clear_fmt", "btn_add_line", "btn_home", "btn_end",
                         "btn_under", "btn_strike", "btn_copy"):
                wdg = getattr(self, name, None)
                if wdg is not None and not sip.isdeleted(wdg):
                    wdg.setVisible(not dense)

        ultra = w < 700
        if getattr(self, "_header_ultra", None) != ultra:
            self._header_ultra = ultra
            # bullet-toggle survives dense but hides in the portrait sliver
            for name in ("btn_bold", "btn_italic", "btn_under", "btn_strike",
                         "btn_header", "btn_copy", "btn_clear", "btn_bullet_toggle",
                         "btn_home", "btn_end", "btn_pin_top", "btn_line_nums",
                         "btn_help", "btn_trash", "btn_toggle_search",
                         "btn_arc_snip", "btn_toggle_archive", "btn_project_folder",
                         "btn_project_run", "btn_files"):
                wdg = getattr(self, name, None)
                if wdg is not None and not sip.isdeleted(wdg):
                    wdg.setVisible(not ultra)
            if hasattr(self, "_counter_sep"):
                self._counter_sep.setVisible(not ultra)
            self._update_date_label()

        # widths recompute every pass while dense — the font can change
        # after the flag flips (scale/theme), stale metrics overshoot
        for name, normal, short in self._DENSE_LABELS:
            btn = getattr(self, name, None)
            if btn is None or sip.isdeleted(btn):
                continue
            if flipped:
                btn.setText(short if dense else normal)
            if dense:
                btn.setFixedWidth(clip_safe_width(btn.text(), btn.font()))
            elif flipped:
                btn.setMinimumWidth(0)
                btn.setMaximumWidth(16777215)
        for name in ("btn_bullet_toggle",):
            bt = getattr(self, name, None)
            if bt is None or sip.isdeleted(bt):
                continue
            if dense:
                bt.setFixedWidth(clip_safe_width(bt.text(), bt.font()))
            elif flipped:
                bt.setMinimumWidth(0)
                bt.setMaximumWidth(16777215)
        if flipped:
            self._update_date_label()
        import os as _os
        if _os.environ.get("FP_DENSITY_DEBUG"):
            from fastprompter.core.logging import logger
            logger.debug(f"DENSITY dense={dense} flipped={flipped} save px={self.btn_save.font().pixelSize()} save minW={self.btn_save.minimumWidth()}")
        if flipped:
            # format squares squeeze 24 -> 20 in dense
            for name in ("btn_bold", "btn_italic", "btn_under", "btn_strike",
                         "btn_header", "btn_settings_toggle", "btn_settings_toggle_right", "btn_help",
                         "btn_pin_top", "btn_line_nums",
                         "btn_add_tab", "btn_del_tab", "btn_sidebar_toggle"):
                btn = getattr(self, name, None)
                if btn is None or sip.isdeleted(btn):
                    continue
                if dense:
                    btn.setFixedSize(18, 18)
                else:
                    self.apply_button_size(btn, 24, 24)
            # tabs scroll inside a bounded strip when space is tight
            # (inline QSS re-enables the scroller arrows the theme hides)
            if hasattr(self, "cat_combo"):
                if dense:
                    self.cat_combo.setStyleSheet("")
                    self.cat_combo.setMinimumWidth(0)
                    self.cat_combo.setMaximumWidth(100)
                else:
                    self.cat_combo.setStyleSheet("")
                    self.cat_combo.setMinimumWidth(0)
                    self.cat_combo.setMaximumWidth(16777215)
            if hasattr(self, "lbl_date"):
                self.lbl_date.setStyleSheet(
                    "padding: 0 1px;" if dense else "padding: 0 4px;")
            if hasattr(self, "lbl_line_count"):
                self.lbl_line_count.setStyleSheet(
                    "padding: 0 1px; font-weight: bold;" if dense
                    else "padding: 0 4px; font-weight: bold;")
            if hasattr(self, "_counter_sep"):
                # a couple spare px for the date widget's text-month growth
                self._counter_sep.setFixedSize(1 if dense else 3, 16)
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

    def _increment_focus_lock(self):
        """Counted ignore_focus_loss: overlapping dialogs each take a lock;
        the flag drops only when the LAST 300ms release fires (no race)."""
        self._focus_lock_count = getattr(self, "_focus_lock_count", 0) + 1
        self.ignore_focus_loss = True

    def _decrement_focus_lock(self):
        self._focus_lock_count = max(0, getattr(self, "_focus_lock_count", 0) - 1)
        if self._focus_lock_count == 0:
            self.ignore_focus_loss = False

    def _pin_top_toggled(self, checked):
        """Header 📌 mirrors the Always-on-Top setting checkbox."""
        if hasattr(self, "cb_top") and self.cb_top.isChecked() != checked:
            self.cb_top.setChecked(checked)  # cb_top's handler does the work
        else:
            self.toggle_aot(checked)

    def _toolbar_tokens(self):
        """Movable header items, one entry per token/attr. _counter_sep and
        the two spacers are represented by sentinel tokens."""
        from fastprompter.ui.toolbar_reorder import DEFAULT_TOOLBAR_ORDER
        return DEFAULT_TOOLBAR_ORDER

    def _toolbar_order_list(self):
        """Saved order, validated + self-healed against the default so a
        stale/partial value can never drop or duplicate a button."""
        default = self._toolbar_tokens()
        raw = (self.data.get("toolbar_order") or "").strip()
        # Migrate old btn_launcher by removing it
        if "btn_launcher" in raw:
            raw = raw.replace("btn_launcher", "")
        saved = [t for t in raw.split(",") if t]
        valid, seen = [], set()
        # keep saved tokens that are still real; drop unknowns/dupes
        for t in saved:
            if t == "<stretch>":
                valid.append(t)
            elif (t == "<sep>" or getattr(self, t, None) is not None) and t not in seen:
                valid.append(t)
                seen.add(t)
        # append any default tokens missing from the saved order
        stretch_needed = default.count("<stretch>") - valid.count("<stretch>")
        for t in default:
            if t == "<stretch>":
                if stretch_needed > 0:
                    valid.append(t)
                    stretch_needed -= 1
            elif t not in seen:
                valid.append(t)
                seen.add(t)
        return valid

    def _toolbar_widget_for(self, token):
        if token == "<sep>":
            return getattr(self, "_counter_sep", None)
        return getattr(self, token, None)

    def toolbar_token_of(self, widget):
        """Reverse map a widget back to its token (drag source id)."""
        for t in self._toolbar_tokens():
            if t not in ("<stretch>",) and self._toolbar_widget_for(t) is widget:
                return t
        return None

    def _toolbar_gap(self, i):
        """Reusable expanding gap widget for the i-th <stretch>. Real widget
        (not a bare spacer) so it's a visible, droppable zone in customize
        mode — the user can see exactly where the flexible fill lives."""
        gaps = getattr(self, "_toolbar_gaps", None)
        if gaps is None:
            gaps = self._toolbar_gaps = []
        while len(gaps) <= i:
            g = QWidget(self.header_widget)
            g.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            g.setMinimumWidth(6)
            g._is_toolbar_gap = True
            gaps.append(g)
        return gaps[i]

    def _style_toolbar_gaps(self, on):
        for g in getattr(self, "_toolbar_gaps", []):
            if on:
                g.setStyleSheet(
                    "border: 1px dashed #C0A060; border-radius: 0; margin: 3px 2px;")
                g.setToolTip(tr("Flexible gap — drop buttons on either side to "
                                "change which zone they sit in", getattr(self, "_current_lang", "EN")))
            else:
                g.setStyleSheet("")
                g.setToolTip("")

    def apply_toolbar_order(self, save=False):
        """Rebuild the header layout from the saved token order. Index 0
        (sidebar toggle) is the fixed anchor and is never moved."""
        lay = self.header_layout
        while lay.count() > 1:  # detach everything after the sidebar anchor
            item = lay.takeAt(1)
            w = item.widget()
            if w is not None:
                w.setParent(self.header_widget)
        order = self._toolbar_order_list()
        stretch_i = 0
        for tok in order:
            if tok == "<stretch>":
                lay.addWidget(self._toolbar_gap(stretch_i))
                stretch_i += 1
                continue
            w = self._toolbar_widget_for(tok)
            if w is not None:
                lay.addWidget(w)
        # reset button is a fixed trailing control, never part of the order
        if hasattr(self, "btn_toolbar_reset"):
            lay.addWidget(self.btn_toolbar_reset)
        self._style_toolbar_gaps(self.data.get("customize_toolbar", "False") == "True")
        if save:
            self.data["toolbar_order"] = ",".join(order)
            self.mark_dirty()
        # widths/visibility depend on width tier — re-pack after reorder
        # (skipped during initial header build, before the editor exists)
        if hasattr(self, "text_area"):
            self._header_dense = None
            self._apply_header_density()

    def _toolbar_seq_token(self, w):
        """Token for any header widget: button id, '<sep>', or '<stretch>'."""
        if getattr(w, "_is_toolbar_gap", False):
            return "<stretch>"
        if w is getattr(self, "_counter_sep", None):
            return "<sep>"
        return self.toolbar_token_of(w)

    def reorder_toolbar_token(self, token, drop_x):
        """Rebuild the whole order from the current left-to-right layout with
        `token` reinserted at drop_x. Because gaps are real widgets now, the
        visual sequence IS the order — unambiguous even with two stretches."""
        seq = []
        for i in range(1, self.header_layout.count()):
            w = self.header_layout.itemAt(i).widget()
            if w is None:
                continue
            t = self._toolbar_seq_token(w)
            if t is None:
                continue
            cx = w.x() + w.width() / 2
            if self.toolbar_token_of(w) == token:  # the dragged widget — skip
                continue
            seq.append((t, cx))
        insert_at = len(seq)
        for idx, (_t, cx) in enumerate(seq):
            if drop_x < cx:
                insert_at = idx
                break
        tokens = [t for t, _ in seq]
        tokens.insert(insert_at, token)
        self.data["toolbar_order"] = ",".join(tokens)
        self.apply_toolbar_order()
        self.mark_dirty()

    def on_customize_toolbar_toggled(self, checked):
        self.data["customize_toolbar"] = "True" if checked else "False"
        self.mark_dirty()
        self.refresh_toolbar_customize_state()

    def refresh_toolbar_customize_state(self):
        """Install/refresh drag filters + cursors for the customize toggle,
        and show/hide the in-header Reset button + visible gaps."""
        on = self.data.get("customize_toolbar", "False") == "True"
        flt = getattr(self, "_toolbar_reorder_filter", None)
        for tok in self._toolbar_tokens():
            if tok in ("<stretch>", "<sep>"):
                continue
            w = self._toolbar_widget_for(tok)
            if w is None:
                continue
            if flt is not None:
                w.removeEventFilter(flt)
                if on:
                    w.installEventFilter(flt)
            w.setCursor(Qt.CursorShape.SizeAllCursor if on else Qt.CursorShape.ArrowCursor)
        self._style_toolbar_gaps(on)
        if hasattr(self, "btn_toolbar_reset"):
            self.btn_toolbar_reset.setVisible(on)

    def reset_toolbar_order(self):
        self.data["toolbar_order"] = ""
        self.apply_toolbar_order(save=True)

    def set_line_numbers(self, enabled):
        """Single source of truth for the line-number gutter. Applies the
        render, then force-syncs BOTH the header # button and the settings
        checkbox (signals blocked) so they can never drift out of step —
        that drift used to make the first # click a silent no-op."""
        self.on_line_numbers_toggled(enabled)
        for w in (getattr(self, "btn_line_nums", None), getattr(self, "cb_line_numbers", None)):
            if w is not None and not sip.isdeleted(w) and w.isChecked() != enabled:
                w.blockSignals(True)
                w.setChecked(enabled)
                w.blockSignals(False)

    def _line_nums_btn_toggled(self, checked):
        """Header # button: fast toggle for the line-number gutter."""
        self.set_line_numbers(checked)

    def _files_root(self):
        custom = (self.data.get("files_root") or "").strip()
        if custom and os.path.isdir(custom):
            return custom
        from fastprompter.utils.paths import get_data_dir
        return os.path.join(get_data_dir(), "files")

    def _silo_folder_name(self, slot_idx, is_archive=False):
        """Stable, UNIQUE folder name for a silo's files. Keyed by slot (not
        title) so two silos that share a title — or two empty ones — never
        collide into the same folder (which made files 'jump' to a neighbor).
        Names stay readable (title slug), disambiguated with -2/-3 on clash,
        and are remembered per slot so a retitle doesn't strand the files.
        Archive silos keep the plain title scheme (static, low-risk)."""
        from fastprompter.ui.file_container import silo_slug
        presets = self.data.get("archive_temp_presets" if is_archive else "temp_presets", [])
        text = presets[slot_idx] if 0 <= slot_idx < len(presets) else ""
        base = silo_slug(text)
        cat = self.get_current_category()
        if is_archive:
            fmap = self.data.setdefault("archive_silo_folders", {})
        else:
            fmap = self.data.setdefault("silo_folders", {})
        key = str(slot_idx)
        if key in fmap and fmap[key]:
            # keep the assigned name, but follow a genuine retitle when the
            # new title's slug is free (readability) — otherwise stay put
            cur = fmap[key]
            cur_base = cur.rsplit("-", 1)[0] if cur[-1:].isdigit() and "-" in cur else cur
            if base != cur_base:
                taken = {v for k, v in fmap.items() if k != key}
                if base not in taken and not self._folder_on_disk(cat, base):
                    self._rename_silo_folder(cat, cur, base)
                    fmap[key] = base
            return fmap[key]
        # first assignment: adopt an existing on-disk folder if it's unclaimed,
        # else pick a unique name
        taken = set(fmap.values())
        if base not in taken and self._folder_on_disk(cat, base):
            fmap[key] = base
            self.mark_dirty()
            return base
        name, n = base, 2
        while name in taken:
            name = f"{base}-{n}"
            n += 1
        fmap[key] = name
        self.mark_dirty()
        return name

    def _folder_on_disk(self, cat, name):
        from fastprompter.ui.file_container import silo_slug
        return os.path.isdir(os.path.join(self._files_root(), silo_slug(cat), name))

    def _rename_silo_folder(self, cat, old_name, new_name):
        from fastprompter.ui.file_container import silo_slug
        base = os.path.join(self._files_root(), silo_slug(cat))
        old_dir, new_dir = os.path.join(base, old_name), os.path.join(base, new_name)
        try:
            if os.path.isdir(old_dir) and not os.path.exists(new_dir):
                os.rename(old_dir, new_dir)
        except OSError as e:
            from fastprompter.core.logging import logger
            logger.warning(f"Silo folder rename {old_dir} -> {new_dir} failed: {e}")

    def _silo_folder_dir(self, slot_idx, is_archive=False):
        """Absolute path to a silo's files folder (unique per slot)."""
        from fastprompter.ui.file_container import silo_slug
        return os.path.join(self._files_root(), silo_slug(self.get_current_category()),
                            self._silo_folder_name(slot_idx, is_archive))

    def _restore_trashed_folders(self, cat):
        """Undo helper: for every silo folder the restored map expects, if it's
        missing on disk but was moved to _trash by a delete/clear, move it back.
        Files are never lost — worst case they stay in _trash for manual rescue."""
        from fastprompter.ui.file_container import silo_slug
        log = self.data.get("folder_trash_log", [])
        if not log:
            return
        cat_dir = os.path.join(self._files_root(), silo_slug(cat))
        fmap = self.data.get("silo_folders", {})
        if not isinstance(fmap, dict):
            return
        wanted = {os.path.abspath(os.path.join(cat_dir, name)) for name in fmap.values()}
        remaining = []
        for original, trashed in log:
            if original in wanted and not os.path.exists(original) and os.path.isdir(trashed):
                try:
                    os.makedirs(os.path.dirname(original), exist_ok=True)
                    os.rename(trashed, original)
                    continue  # restored — drop from the log
                except OSError as e:
                    from fastprompter.core.logging import logger
                    logger.warning(f"Could not restore folder {trashed} -> {original}: {e}")
            remaining.append((original, trashed))
        self.data["folder_trash_log"] = remaining
        self.mark_dirty()

    def _silo_file_count(self, slot_idx, is_archive=False):
        try:
            return len(os.listdir(self._silo_folder_dir(slot_idx, is_archive)))
        except OSError:
            return 0

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

    def add_links_to_active_silo(self, paths):
        """Drop target helper: put file links into the active silo's container
        and show the drawer so the user sees where they landed."""
        is_archive = getattr(self, "active_is_archive", False)
        self.open_file_container(is_archive=is_archive)
        self._file_container.import_links(paths)

    def _update_project_buttons(self):
        paths = self.data.get("silo_project_paths", {}).get(str(self.active_temp_slot), {})
        
        has_folder = bool(paths.get("folder"))
        has_exe = bool(paths.get("executable"))
        
        if hasattr(self, "btn_project_folder"):
            self.btn_project_folder.setVisible(has_folder)
        if hasattr(self, "btn_project_run"):
            self.btn_project_run.setVisible(has_exe)

    def _update_files_button(self):
        """Refresh the header 📁 button: live file count + breakdown tooltip."""
        if not hasattr(self, "btn_files"):
            return
        is_archive = getattr(self, "active_is_archive", False)
        idx = self.active_temp_slot
        from fastprompter.ui.file_container import folder_summary
        folder = self._silo_folder_dir(idx, is_archive)
        n = self._silo_file_count(idx, is_archive)
        self.btn_files.setText(f"📁{n}" if n else "📁")
        if getattr(self, "_header_dense", False):
            self.btn_files.setFixedWidth(
                self.btn_files.fontMetrics().horizontalAdvance(self.btn_files.text()) + 8)
        lang = getattr(self, '_current_lang', 'EN')
        self.btn_files.setToolTip(
            tr("Files—asset drawer for the active silo (drop in / drag out /\npreview / export; plain folder in data/files)\n\n", lang)
            + folder_summary(folder, lang=lang)
        )

    def _launch_silo_executable(self):
        import os
        from fastprompter.core.logging import logger
        paths = self.data.get("silo_project_paths", {}).get(str(self.active_temp_slot), {})
        exe = paths.get("executable")
        if not exe or not os.path.exists(exe):
            logger.info("No executable configured or file does not exist.")
            return

        try:
            # Setting working directory to the directory of the executable
            exe_dir = os.path.dirname(exe)
            os.startfile(exe, cwd=exe_dir)
        except OSError as e:
            logger.error(f"Failed to launch executable: {e}")

    def _open_silo_project_folder(self):
        import os
        from fastprompter.core.logging import logger
        paths = self.data.get("silo_project_paths", {}).get(str(self.active_temp_slot), {})
        folder = paths.get("folder")
        if not folder or not os.path.isdir(folder):
            logger.info("No project folder configured or directory does not exist.")
            return
                
        try:
            os.startfile(folder)
        except OSError as e:
            logger.error(f"Failed to open project folder: {e}")

    def open_silo_settings(self, global_idx=None):
        if global_idx is None:
            global_idx = self.active_temp_slot
        from fastprompter.ui.silo_settings_dialog import SiloSettingsDialog
        dlg = SiloSettingsDialog(self, global_idx)
        if dlg.exec():
            # Trigger refresh to show/hide the buttons
            if global_idx == self.active_temp_slot:
                self._update_project_buttons()

    def open_file_container(self, global_idx=None, is_archive=False):
        from fastprompter.ui.file_container import FileContainerPanel, silo_slug
        if global_idx is None:
            global_idx = self.active_temp_slot
            is_archive = getattr(self, "active_is_archive", False)
        presets = self.data.get("archive_temp_presets" if is_archive else "temp_presets", [])
        text = presets[global_idx] if 0 <= global_idx < len(presets) else ""
        if getattr(self, "_file_container", None) is None:
            self._file_container = FileContainerPanel(self)
        self._file_container.open_for(
            self._silo_folder_dir(global_idx, is_archive), title=silo_slug(text))

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
            estimate = int(24 * getattr(self, "_ui_scale", 1.0))
            for btn in getattr(self, "silo_buttons", []):
                bh = btn.height() if btn.isVisible() else btn.sizeHint().height()
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
            "preview_mode": (self.preview_combo.currentData() or self.preview_combo.currentText())
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
        self.btn_sidebar_toggle.setToolTip(tr(
            "Toggle Sidebar (Alt+D)\nShow or hide the right/left sidebar containing snippets and silos.",
            getattr(self, "_current_lang", "EN")))
        self.btn_sidebar_toggle.clicked.connect(self.toggle_sidebar_visibility)
        self.header_layout.addWidget(self.btn_sidebar_toggle)

        self.cat_combo = QComboBox()

        # Scroll buttons only appear when tabs truly overflow; without them
        # the tab bar's minimum width is the sum of ALL tabs, which alone
        # breaks packing into a Ctrl+Q quarter-FullHD window.


        for cat in self.data["cats_order"]:
            self.cat_combo.addItem(cat)
        self.cat_combo.currentIndexChanged.connect(self.on_tab_changed)





        self.btn_new = QPushButton(tr("NEW", getattr(self, "_current_lang", "EN")))
        self.btn_new.setToolTip(tr("NEW ({})", self._current_lang).format(self.data.get('hk_new_snippet', 'Ctrl+N')))
        self.apply_button_size(self.btn_new, 24)
        self.btn_new.setMinimumWidth(80)
        self.btn_new.clicked.connect(self.select_empty_silo)

        self.btn_save = QPushButton(tr("Save", getattr(self, "_current_lang", "EN")))
        self.btn_save.setToolTip(tr("Save ({})", self._current_lang).format(self.data.get('hk_save_snippet', 'Ctrl+S')))
        self.apply_button_size(self.btn_save, 24)
        self.btn_save.clicked.connect(self.save_snippet)

        self.btn_home = QPushButton(tr("Home", getattr(self, "_current_lang", "EN")))
        self.btn_home.setToolTip(tr("Home (Home)", getattr(self, "_current_lang", "EN")))
        self.apply_button_size(self.btn_home, 24)
        self.btn_home.clicked.connect(self.move_cursor_home)

        self.btn_end = QPushButton(tr("End", getattr(self, "_current_lang", "EN")))
        self.btn_end.setToolTip(tr("Jump to End\nMove cursor to the bottom of the document.", getattr(self, "_current_lang", "EN")))
        self.apply_button_size(self.btn_end, 24)
        self.btn_end.clicked.connect(self.move_cursor_end)

        self.btn_add_line = QPushButton(tr("Line", getattr(self, "_current_lang", "EN")))
        self.btn_add_line.setToolTip(tr(
            "Insert Line (Ctrl+W)\nInsert a spaced --- divider and start a fresh bullet.",
            getattr(self, "_current_lang", "EN")))
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

        self.btn_bold = QPushButton(tr("B", getattr(self, "_current_lang", "EN")))
        self.btn_bold.setToolTip(tr("Bold ({})\nMake selected text bold.", self._current_lang).format(self.data.get('hk_bold', 'Ctrl+B')))
        self.apply_button_size(self.btn_bold, 24, 24)
        f = QFont(self.btn_bold.font()); f.setBold(True); self.btn_bold.setFont(f)
        self.btn_bold.clicked.connect(lambda: self.apply_format("bold"))

        self.btn_italic = QPushButton(tr("I", getattr(self, "_current_lang", "EN")))
        self.btn_italic.setToolTip(tr("Italic ({})\nMake selected text italic.", self._current_lang).format(self.data.get('hk_italic', 'Ctrl+I')))
        self.apply_button_size(self.btn_italic, 24, 24)
        f = QFont(self.btn_italic.font()); f.setItalic(True); self.btn_italic.setFont(f)
        self.btn_italic.clicked.connect(lambda: self.apply_format("italic"))

        self.btn_under = QPushButton(tr("U", getattr(self, "_current_lang", "EN")))
        self.btn_under.setToolTip(tr("Underline ({})\nMake selected text underlined.", self._current_lang).format(self.data.get('hk_underline', 'Ctrl+U')))
        self.apply_button_size(self.btn_under, 24, 24)
        f = QFont(self.btn_under.font()); f.setUnderline(True); self.btn_under.setFont(f)
        self.btn_under.clicked.connect(lambda: self.apply_format("underline"))

        self.btn_strike = QPushButton(tr("S", getattr(self, "_current_lang", "EN")))
        self.btn_strike.setToolTip(tr("Strikethrough (Ctrl+T)\nCross out selected text.", getattr(self, "_current_lang", "EN")))
        self.apply_button_size(self.btn_strike, 24, 24)
        f = QFont(self.btn_strike.font()); f.setStrikeOut(True); self.btn_strike.setFont(f)
        self.btn_strike.clicked.connect(lambda: self.apply_format("strike"))

        self.btn_header = QPushButton(tr("H", getattr(self, "_current_lang", "EN")))
        self.btn_header.setToolTip(tr(
            "Header (Ctrl+E)\nTitle the line: # + bold + underline + timestamp,\n"
            "then land 2 lines below on a fresh bullet.", getattr(self, "_current_lang", "EN")))
        self.apply_button_size(self.btn_header, 24, 24)
        f = QFont(self.btn_header.font()); f.setBold(True); f.setUnderline(True); self.btn_header.setFont(f)
        self.btn_header.clicked.connect(self.apply_header_timestamp)

        self.btn_clear_fmt = QPushButton(tr("Clear Fmt", getattr(self, "_current_lang", "EN")))
        self.btn_clear_fmt.setToolTip(tr("Clear Format\nRemove all explicit font styling from text.", getattr(self, "_current_lang", "EN")))
        self.apply_button_size(self.btn_clear_fmt, 24)
        self.btn_clear_fmt.clicked.connect(self.clear_formatting)



        self.btn_settings_toggle = QPushButton("⚙")
        self.apply_button_size(self.btn_settings_toggle, 24, 24)
        self.btn_settings_toggle.setToolTip(tr(
            "Settings\nConfigure hotkeys, theme, fonts, and UI scaling.", getattr(self, "_current_lang", "EN")))
        self.btn_settings_toggle.clicked.connect(self.toggle_mini_settings)

        self.btn_settings_toggle_right = QPushButton("⚙")
        self.apply_button_size(self.btn_settings_toggle_right, 24, 24)
        self.btn_settings_toggle_right.setToolTip(self.btn_settings_toggle.toolTip())
        self.btn_settings_toggle_right.clicked.connect(self.toggle_mini_settings)

        self.btn_help = QPushButton("❓")
        self.btn_help.setToolTip(tr("Help — every hotkey, gesture and feature (click)", getattr(self, "_current_lang", "EN")))
        self.btn_help.setCursor(Qt.CursorShape.PointingHandCursor)
        self.apply_button_size(self.btn_help, 24, 24)
        self.btn_help.clicked.connect(self.open_help_dialog)

        self.btn_copy = QPushButton(tr("Copy", getattr(self, "_current_lang", "EN")))
        self.btn_copy.setToolTip(tr("Copy all text (Ctrl+C)\nRight-click: Copy + Close FastPrompter", getattr(self, "_current_lang", "EN")))
        self.apply_button_size(self.btn_copy, 26)
        self.btn_copy.clicked.connect(self.copy_context_to_clipboard)
        self.btn_copy.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.btn_copy.customContextMenuRequested.connect(self.copy_context_and_close)

        self.btn_clear = QPushButton(tr("Clear", getattr(self, "_current_lang", "EN")))
        self.btn_clear.setToolTip(tr("Clear (Ctrl+Shift+C)", getattr(self, "_current_lang", "EN")))
        self.apply_button_size(self.btn_clear, 26)
        self.btn_clear.clicked.connect(self.clear_text)

        self.btn_files = QPushButton("📁")
        self.btn_files.setToolTip(tr(
            "Files\nAsset drawer for the active silo: drop any files in,\n"
            "drag them out, preview, export. Stored as a plain folder\n"
            "in data/files — readable outside FastPrompter.", getattr(self, "_current_lang", "EN")))
        self.apply_button_size(self.btn_files, 24)
        self.btn_files.clicked.connect(lambda: self.open_file_container())

        self.btn_project_run = QPushButton("▶️")
        self.btn_project_run.setToolTip(tr("Run Executable", getattr(self, "_current_lang", "EN")))
        self.apply_button_size(self.btn_project_run, 20)
        self.btn_project_run.clicked.connect(self._launch_silo_executable)
        self.btn_project_run.hide()

        self.btn_project_folder = QPushButton("📂")
        self.btn_project_folder.setToolTip(tr("Open Project Folder", getattr(self, "_current_lang", "EN")))
        self.apply_button_size(self.btn_project_folder, 20)
        self.btn_project_folder.clicked.connect(self._open_silo_project_folder)
        self.btn_project_folder.hide()

        self.btn_trash = QPushButton("🗑️")
        self.apply_button_size(self.btn_trash, 20, 20)
        self.btn_trash.setToolTip(tr("Open Trash", getattr(self, "_current_lang", "EN")))
        self.btn_trash.clicked.connect(self.open_trash)

        self.btn_toggle_search = QPushButton("⌕")
        self.apply_button_size(self.btn_toggle_search, 20, 20)
        self.btn_toggle_search.setCheckable(True)

        self.btn_arc_snip = QPushButton("📥")
        self.apply_button_size(self.btn_arc_snip, 20, 20)
        self.btn_arc_snip.setToolTip(tr("Archive Active Snippet or Silo", getattr(self, "_current_lang", "EN")))
        self.btn_arc_snip.clicked.connect(self.archive_active_item)

        self.btn_toggle_archive = QPushButton("📦")
        self.apply_button_size(self.btn_toggle_archive, 20, 20)
        self.btn_toggle_archive.setToolTip(tr("Toggle Archives", getattr(self, "_current_lang", "EN")))
        self.btn_toggle_archive.setCheckable(True)
        # Navigation
        self.header_layout.addWidget(self.cat_combo)


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
        # btn_files lives in the sidebar next to the archive buttons

        # Status cluster (right): clock | pins | line counter | settings
        self.header_layout.addStretch(1)
        from fastprompter.ui.analog_clock import MiniAnalogClock
        self.analog_clock = MiniAnalogClock(self)
        self.analog_clock.setToolTip(tr("Current time (analog)", getattr(self, "_current_lang", "EN")))
        self.header_layout.addWidget(self.analog_clock)

        self.lbl_date = QLabel("")
        self.lbl_date.setToolTip(tr("Current Date and Time", getattr(self, "_current_lang", "EN")))
        self.lbl_date.setStyleSheet("padding: 0 4px;")
        self.header_layout.addWidget(self.lbl_date)

        self.btn_pin_top = QPushButton("📌")
        self.btn_pin_top.setCheckable(True)
        self.btn_pin_top.setChecked(self.data.get("always_on_top", "True") == "True")
        self.btn_pin_top.setToolTip(tr("Always on Top — keep the window above all others", getattr(self, "_current_lang", "EN")))
        self.apply_button_size(self.btn_pin_top, 20, 20)
        self.btn_pin_top.toggled.connect(self._pin_top_toggled)
        self.header_layout.addWidget(self.btn_pin_top)

        self.btn_line_nums = QPushButton("#")
        self.btn_line_nums.setCheckable(True)
        self.btn_line_nums.setChecked(self.data.get("show_line_numbers", "False") == "True")
        self.btn_line_nums.setToolTip(tr(
            "Show / hide the line-number gutter\n(click the gutter to place colored margin marks)", getattr(self, "_current_lang", "EN")))
        self.apply_button_size(self.btn_line_nums, 20, 20)
        self.btn_line_nums.toggled.connect(self._line_nums_btn_toggled)
        self.header_layout.addWidget(self.btn_line_nums)

        # Kept as a tiny invisible spacer so the toolbar-order "<sep>" token
        # still resolves; the visible divider line was removed per request.
        self._counter_sep = QFrame()
        self._counter_sep.setFrameShape(QFrame.Shape.NoFrame)
        self._counter_sep.setFixedSize(3, 16)
        self.header_layout.addWidget(self._counter_sep)

        self.lbl_line_count = QLabel("")
        self.lbl_line_count.setToolTip(tr("Line count of the open silo/snippet", getattr(self, "_current_lang", "EN")))
        self.lbl_line_count.setStyleSheet("padding: 0 4px; font-weight: bold;")
        self.header_layout.addWidget(self.lbl_line_count)
        self.header_layout.addWidget(self.btn_settings_toggle)
        self.header_layout.addWidget(self.btn_help)

        # Reset-layout button — a fixed trailing control, shown only while
        # Customize Toolbar is on (re-added by apply_toolbar_order each rebuild)
        self.btn_toolbar_reset = QPushButton("↺")
        self.btn_toolbar_reset.setToolTip(tr("Reset the toolbar to its default order", getattr(self, "_current_lang", "EN")))
        self.apply_button_size(self.btn_toolbar_reset, 20, 20)
        self.btn_toolbar_reset.clicked.connect(self.reset_toolbar_order)
        self.btn_toolbar_reset.setVisible(False)
        self.header_layout.addWidget(self.btn_toolbar_reset)
        self.main_layout.addWidget(self.header_widget)

        # Apply any saved custom toolbar order, then arm drag-reorder
        from fastprompter.ui.toolbar_reorder import install_toolbar_reorder
        self.apply_toolbar_order()
        install_toolbar_reorder(self)

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
        # The English mode name is stored as itemData and is the SINGLE source
        # of truth: the display text is translated per-language, but every
        # lookup (change_preview_mode, saved-value match) reads itemData so a
        # translated combo never breaks the mode logic or gets stuck in a
        # foreign language.
        for _mode in ("Source View", "Live Preview", "Reading"):
            self.preview_combo.addItem(_mode, _mode)
        self._retranslate_preview_combo(getattr(self, "_current_lang", "EN"))
        self.preview_combo.setToolTip(tr(
            "Source View: Plain text editor\n"
            "Live Preview: Editor with live markdown highlights (default)\n"
            "Reading: Read-only rendered markdown view", getattr(self, "_current_lang", "EN")))
        # Map old saved values to new
        _view_map = {"None": "Source View", "Raw": "Source View", "Markdown": "Reading"}
        saved_preview = self.data.get("preview_mode", "Live Preview")
        saved_preview = _view_map.get(saved_preview, saved_preview)  # migrate old values
        idx = self.preview_combo.findData(saved_preview)
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
            cb._en_text = text
            return cb

        self.btn_hotkeys = make_action_checkbox("Keys", self.open_hotkey_settings)
        self.btn_hotkeys.setToolTip(tr("Configure Global Hotkeys (Settings Cog)", getattr(self, "_current_lang", "EN")))
        self.btn_colors = make_action_checkbox("RGB", self.open_color_settings)
        self.btn_colors.setToolTip(tr("Custom Theme Colors (Color Palette)", getattr(self, "_current_lang", "EN")))
        self.btn_backup = make_action_checkbox("BkUp", self.backup_db)
        self.btn_restore = make_action_checkbox("Rstr", self.restore_db)

        try:
            current_scale_pct = int(float(self.data.get("ui_scale", "1.0")) * 100)
        except Exception:
            current_scale_pct = 100
        self.btn_button_scale = make_action_checkbox(
            f"Scale: {current_scale_pct}%", self.cycle_button_scale
        )
        self.btn_button_scale.setToolTip(tr(
            "Scale the whole program: 50 / 75 / 100 / 125 / 150%\n"
            "(fine-tune with Ctrl+Plus / Ctrl+Minus)", getattr(self, "_current_lang", "EN"))
        )

        # Load custom font button
        self.btn_load_font = QPushButton(tr("+ Font", getattr(self, "_current_lang", "EN")))
        self.btn_load_font.setFixedWidth(52)
        self.btn_load_font.setToolTip(tr("Load a custom .ttf/.otf font file", getattr(self, "_current_lang", "EN")))
        self.btn_load_font.clicked.connect(self.load_custom_font)

        self.btn_clear_fonts = QPushButton(tr("× Fonts", getattr(self, "_current_lang", "EN")))
        self.btn_clear_fonts.setFixedWidth(54)
        self.btn_clear_fonts.setToolTip(tr("Clear all custom fonts from combo (reset to defaults)", getattr(self, "_current_lang", "EN")))
        self.btn_clear_fonts.clicked.connect(self.clear_custom_fonts)

        # Volume control
        self.spin_volume = QSpinBox()
        self.spin_volume.setRange(1, 10)
        try:
            self.spin_volume.setValue(int(self.data.get("sound_volume", "5")))
        except Exception:
            self.spin_volume.setValue(5)
        self.spin_volume.setFixedWidth(42)
        self.spin_volume.setToolTip(tr("Click sound volume (1-10)", getattr(self, "_current_lang", "EN")))
        self.spin_volume.valueChanged.connect(
            lambda v: (self.data.update({"sound_volume": str(v)}), self.mark_dirty())
        )

        # --- Settings panel: hidden by default, toggled by the gear button. ---
        # Top row: appearance & actions. Below: toggles grouped by purpose.
        appearance_row = QHBoxLayout()
        appearance_row.setContentsMargins(0, 0, 0, 0)
        appearance_row.setSpacing(4)
        appearance_row.addWidget(QLabel(tr("Font:", getattr(self, "_current_lang", "EN"))))
        appearance_row.addWidget(self.font_combo)
        appearance_row.addWidget(self.font_spin)
        appearance_row.addWidget(self.btn_load_font)
        appearance_row.addWidget(self.btn_clear_fonts)
        appearance_row.addSpacing(8)
        appearance_row.addWidget(QLabel(tr("Theme:", getattr(self, "_current_lang", "EN"))))
        appearance_row.addWidget(self.cb_theme)
        appearance_row.addWidget(self.btn_colors)
        
        self.btn_drop_zones = make_action_checkbox("Drop Zones", self.open_drop_zones_settings)
        self.btn_drop_zones.setToolTip(tr("Customize Drop Zones", getattr(self, "_current_lang", "EN")))
        appearance_row.addWidget(self.btn_drop_zones)
        appearance_row.addSpacing(8)
        appearance_row.addWidget(QLabel(tr("View:", getattr(self, "_current_lang", "EN"))))
        appearance_row.addWidget(self.preview_combo)
        appearance_row.addWidget(self.btn_button_scale)
        appearance_row.addSpacing(8)
        appearance_row.addWidget(QLabel(tr("Language:", getattr(self, "_current_lang", "EN"))))
        self.cb_language = QComboBox()
        # Every language the i18n pack can serve, shown by its native name +
        # a drawn flag icon, keyed on the code (stored as itemData so the
        # display text is free to be localized without breaking the lookup).
        from fastprompter.ui.flags import flag_icon
        from PyQt6.QtCore import QSize
        self.cb_language.setIconSize(QSize(18, 12))
        for code in available_languages():
            native = _LANG_NATIVE_NAMES.get(code, code)
            label = native if code in ("EN",) else f"{native} ({code})"
            ic = flag_icon(code)
            if ic is not None:
                self.cb_language.addItem(ic, label, code)
            else:
                self.cb_language.addItem(label, code)
        saved_lang = self.data.get("language", "EN")
        saved_idx = self.cb_language.findData(saved_lang)
        if saved_idx >= 0:
            self.cb_language.setCurrentIndex(saved_idx)
        self.cb_language.currentIndexChanged.connect(
            lambda i: self._on_language_changed(self.cb_language.itemData(i) or "EN")
        )
        appearance_row.addWidget(self.cb_language)
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
            cb._en_text = text
            cb._en_tooltip = tooltip
            return cb

        self.cb_top = create_footer_cb(
            "📌 Always on Top",
            "Keep the window above all others",
            self.data.get("always_on_top", "True") == "True",
            self.toggle_aot,
        )
        self.cb_lock_window = create_footer_cb(
            "🔒 Lock Window",
            "Freeze the window's position and size",
            self.data.get("window_locked", "False") == "True",
            self.set_lock_state,
        )
        self.cb_normal_window = create_footer_cb(
            "🪟 Normal Window",
            "Use a standard OS window frame and taskbar entry",
            self.data.get("normal_window", "False") == "True",
            self.apply_window_flags,
        )
        self.cb_tray = create_footer_cb(
            "📉 Tray Icon",
            "Keep an icon in the system tray",
            self.data.get("tray_visible", "True") == "True",
            self.on_tray_toggled,
        )
        self.cb_sidebar = create_footer_cb(
            "▶ Sidebar Right",
            "Move the snippet/silo sidebar to the right side",
            self.data.get("sidebar_right", "False") == "True",
            self.toggle_sidebar_position,
        )
        self.cb_focus = create_footer_cb(
            "👁 Hide on Click-Out",
            "Hide the window when you click outside of it\nGlobal toggle: Alt+A",
            self.data.get("close_on_focus_loss", "True") == "True",
            self.mark_dirty,
        )
        self.cb_snippet_arrows = create_footer_cb(
            "↕ Snippet Arrows",
            "Show the ▲ ▶ ▼ paste buttons on snippet rows\n"
            "(insert at top / at cursor / at bottom)",
            self.data.get("snippet_arrows", "False") == "True",
            lambda checked: (
                self.data.update({"snippet_arrows": "True" if checked else "False"})
                or self.mark_dirty()
                or self.refresh_snippets_panel()
            ),
        )
        self.cb_silo_ticks = create_footer_cb(
            "✅ Silo Ticks",
            "Show the ✅ done-mark button when hovering a silo.\n"
            "Off by default — Ctrl+Shift+click a silo toggles its tick either way.",
            self.data.get("silo_ticks_enabled", "False") == "True",
            lambda checked: (
                self.data.update({"silo_ticks_enabled": "True" if checked else "False"})
                or self.mark_dirty()
                or self.refresh_temp_presets()
            ),
        )
        self.cb_ctrl_c = create_footer_cb(
            "📋 Ctrl+C Hides",
            "Copying with Ctrl+C also hides the window\n(copy & get back to work in one stroke)",
            self.data.get("ctrl_c_closes", "True") == "True",
            self.mark_dirty,
        )
        self.cb_lock_cursor = create_footer_cb(
            "🖱 Open at Cursor",
            "The hotkey opens the window at your mouse cursor",
            self.data.get("lock_to_cursor", "False") == "True",
            self.on_lock_cursor_toggled,
        )
        self.cb_customize_toolbar = create_footer_cb(
            "🧩 Customize Toolbar",
            "Drag the top-bar buttons to reorder them. Dashed boxes are\n"
            "flexible gaps — drop a button on either side to move it between\n"
            "the left / centre / right zones. Use the ↺ button (or right-click\n"
            "this text) to reset to the default order.",
            self.data.get("customize_toolbar", "False") == "True",
            self.on_customize_toolbar_toggled,
        )
        self.cb_customize_toolbar.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.cb_customize_toolbar.customContextMenuRequested.connect(
            lambda _p: self.reset_toolbar_order())
        self.cb_silo_home = create_footer_cb(
            "🏠 Silos at Start",
            "Place the cursor at the top of a silo when opening it",
            self.data.get("silo_home", "False") == "True",
            self.on_silo_home_toggled,
        )
        self.cb_portable_backup = create_footer_cb(
            "💾 Auto Backup (.md)",
            "Mirror silos & snippets as Markdown files to Documents\\.fastprompter\\",
            self.data.get("portable_backup_enabled", "True") == "True",
            lambda checked: (
                self.data.update({"portable_backup_enabled": "True" if checked else "False"})
                or self.mark_dirty()
            ),
        )
        self.cb_wrap = create_footer_cb(
            "↩ Word Wrap",
            "Wrap long lines instead of scrolling horizontally",
            self.data.get("word_wrap", "True") == "True",
            self.on_wrap_toggled,
        )
        self.cb_line_numbers = create_footer_cb(
            "🔢 Line Numbers",
            "Show a line-number gutter\n(click it to place colored margin marks)",
            self.data.get("show_line_numbers", "False") == "True",
            self.set_line_numbers,  # routes through the single source of truth
        )
        self.cb_code_gutter = create_footer_cb(
            "🔢 Auto # on Code",
            "Auto-show line numbers inside ``` code blocks even when the gutter\n"
            "is off. Off by default so the Line Numbers toggle stays a clean on/off.",
            self.data.get("code_auto_gutter", "False") == "True",
            lambda checked: (
                self.data.update({"code_auto_gutter": "True" if checked else "False"})
                or self.mark_dirty()
                or self.text_area.update_line_number_area_width()
                or self.text_area.line_number_area.update()
            ),
        )
        # keep the header pin button in sync with the always-on-top checkbox
        self.cb_top.toggled.connect(
            lambda c: hasattr(self, "btn_pin_top") and self.btn_pin_top.setChecked(c))

        self.cb_line_marks = create_footer_cb(
            "🔴 Line Marks",
            "Enable click-to-mark in line numbers (Red dot, Yellow Rhombus, Blue square)",
            self.data.get("line_marks", "False") == "True",
            lambda checked: self.data.update({"line_marks": "True" if checked else "False"})
                            or self.mark_dirty()
                            or (self.text_area.line_number_area.update() if hasattr(self, "text_area") and hasattr(self.text_area, "line_number_area") else None)
        )

        self.cb_zebra = create_footer_cb(
            "🦓 Zebra Stripes",
            "Lightly shade every other line for readability",
            self.data.get("zebra_lines", "False") == "True",
            lambda checked: (
                self.data.update({"zebra_lines": "True" if checked else "False"})
                or self.text_area.viewport().update()
                or self.mark_dirty()
            ),
        )
        self.cb_hide_shortkeys = create_footer_cb(
            "⌨ Hide Key Hints",
            "Hide the F1-F10 shortcut labels on snippet buttons",
            self.data.get("hide_shortkeys", "False") == "True",
            self.on_hide_shortkeys_toggled,
        )
        self.cb_double_line = create_footer_cb(
            "⇕ Double-Space Lists",
            "With Auto-Bullet on, Enter after a list item adds a blank\n"
            "line before the next bullet — spaced, easy-to-read lists",
            self.data.get("bullet_double_line", "False") == "True",
            lambda checked: (
                self.data.update({"bullet_double_line": "True" if checked else "False"})
                or self.mark_dirty()
            ),
        )
        self.cb_bold_titles = create_footer_cb(
            "𝗕 Bold # Titles",
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
            "➖ Pinned Gap",
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
            "📅 Show Date Widget",
            "Show a floating date and time rectangle in the top-right\n"
            "corner of the text editor",
            self.data.get("show_date_rect", "True") == "True",
            lambda checked: (
                self.data.update({"show_date_rect": "True" if checked else "False"})
                or self.mark_dirty()
            ),
        )
        self.cb_date_seconds = create_footer_cb(
            "⏱ Date Seconds",
            "Show seconds in the date widget (hh:mm:ss instead of hh:mm)",
            self.data.get("date_seconds", "True") == "True",
            lambda checked: (
                self.data.update({"date_seconds": "True" if checked else "False"})
                or self.mark_dirty()
            ),
        )
        self.cb_analog_clock = create_footer_cb(
            "🕒 Analog Clock",
            "Show a mini analog clock (hour + minute hands)\nnext to the date widget",
            self.data.get("analog_clock", "False") == "True",
            lambda checked: (
                self.data.update({"analog_clock": "True" if checked else "False"})
                or self.mark_dirty()
                or self._update_date_label()
            ),
        )
        self.cb_date_daypart = create_footer_cb(
            "🌞 Day Word",
            "Show the time-of-day word (Morning / Day / Evening / Night)\n"
            "after the clock in the date widget",
            self.data.get("date_daypart", "True") == "True",
            lambda checked: (
                self.data.update({"date_daypart": "True" if checked else "False"})
                or self.mark_dirty()
                or self._update_date_label()
            ),
        )
        self.cb_date_emoji = create_footer_cb(
            "🎭 Emoji Day State",
            "Show an emoji (🌅/☀️/🌇/🌙) instead of the time-of-day word",
            self.data.get("date_emoji", "False") == "True",
            lambda checked: (
                self.data.update({"date_emoji": "True" if checked else "False"})
                or self.mark_dirty()
                or self._update_date_label()
            ),
        )
        self.cb_date_text_month = create_footer_cb(
            "🔤 Text Month",
            "Show month as text instead of numbers (17 Jul instead of 17.07)",
            self.data.get("date_text_month", "False") == "True",
            lambda checked: (
                self.data.update({"date_text_month": "True" if checked else "False"})
                or self.mark_dirty()
                or self._update_date_label()
            ),
        )
        self.cb_date_ampm = create_footer_cb(
            "🕐 12-Hour Clock",
            "Show time as 09:05 PM instead of 21:05 — applies to the date\n"
            "widget, Ctrl+E headers and the end-of-line timestamp",
            self.data.get("date_ampm", "False") == "True",
            lambda checked: (
                self.data.update({"date_ampm": "True" if checked else "False"})
                or self.mark_dirty()
                or self._update_date_label()
            ),
        )
        self.cb_sound = create_footer_cb(
            "🔊 UI Sounds",
            "Play click sounds for buttons and actions.\n"
            "You can place your own .wav files in the 'sound' folder to override:\n"
            "• newbutton1.wav (New button)\n"
            "• savebutton1.wav (Save button)\n"
            "• button1.wav (Click/Silo)\n"
            "• button2.wav (Snippet)\n"
            "• tickbox1.wav (Checkbox)\n"
            "• delete1.wav (Delete)\n"
            "• clear1.wav (Clear)",
            self.data.get("sound_ui", "False") == "True",
            self.on_sound_toggled,
        )
        self.cb_typewriter = create_footer_cb(
            "⌨ Typewriter",
            "Play a typewriter tick for every typed character.\n"
            "Place 'type1.wav' in the 'sound' folder to use your own typing sound.",
            self.data.get("sound_typewriter", "False") == "True",
            self.on_typewriter_toggled,
        )
        self.cb_trash_vision = create_footer_cb(
            "🗑 Trash Vision",
            "Show the Trash category for deleted snippets",
            self.data.get("trash_vision", "False") == "True",
            self.toggle_trash_vision,
        )
        self.cb_silo_color_box = create_footer_cb(
            "🎨 Silo Color Box",
            "Show the little clickable color box on '#' silos\n"
            "(click to cycle colors, right-click for the full picker)",
            self.data.get("silo_color_box", "True") == "True",
            lambda checked: (
                self.data.update({"silo_color_box": "True" if checked else "False"})
                or self.mark_dirty()
                or self.refresh_temp_presets()
            ),
        )

        div_row = QHBoxLayout()
        div_row.setContentsMargins(0, 0, 0, 0)
        div_row.setSpacing(4)
        lbl_div = QLabel(tr("Line gaps:", getattr(self, "_current_lang", "EN")))
        lbl_div.setToolTip(tr("Blank lines the Line/Ctrl+W divider puts before and after ---", getattr(self, "_current_lang", "EN")))
        div_row.addWidget(lbl_div)
        self.spin_div_before = QSpinBox()
        self.spin_div_before.setRange(0, 6)
        self.spin_div_before.setToolTip(tr("Lines before ---", getattr(self, "_current_lang", "EN")))
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
        self.spin_div_after.setToolTip(tr("Lines after --- (before the fresh bullet)", getattr(self, "_current_lang", "EN")))
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
        self.btn_files_root = QPushButton(tr("Files Folder…", getattr(self, "_current_lang", "EN")))
        self.btn_files_root.setToolTip(tr(
            "Choose where silo file containers are stored.\n"
            "Default: data/files next to the app.",
            getattr(self, "_current_lang", "EN")))
        self.btn_files_root.clicked.connect(self.pick_files_root)
        files_row.addWidget(self.btn_files_root)
        btn_files_root_reset = QPushButton("↺")
        btn_files_root_reset.setToolTip(tr("Reset silo files location to the default data/files", getattr(self, "_current_lang", "EN")))
        btn_files_root_reset.setFixedWidth(24)
        btn_files_root_reset.clicked.connect(self.reset_files_root)
        files_row.addWidget(btn_files_root_reset)
        files_row.addStretch(1)

        vol_row = QHBoxLayout()
        vol_row.setContentsMargins(0, 0, 0, 0)
        vol_row.setSpacing(4)
        vol_row.addWidget(QLabel(tr("Volume:", getattr(self, "_current_lang", "EN"))))
        vol_row.addWidget(self.spin_volume)
        vol_row.addStretch(1)

        hdr_row = QHBoxLayout()
        hdr_row.setContentsMargins(0, 0, 0, 0)
        hdr_row.setSpacing(4)
        lbl_hdr = QLabel(tr("Header Fmt:", getattr(self, "_current_lang", "EN")))
        lbl_hdr.setToolTip(tr(
            "Template for the Ctrl+E header.\n"
            "{text} — the line's text\n{time} — timestamp\n"
            "{state} — Morning / Day / Evening / Night\n"
            "Markdown markers (** __ etc.) are yours to add or drop.",
            getattr(self, "_current_lang", "EN")))
        hdr_row.addWidget(lbl_hdr)
        self.le_hdr_fmt = QLineEdit()
        self.le_hdr_fmt.setPlaceholderText("{text} ({time})")
        self.le_hdr_fmt.setText(self.data.get("ctrl_e_format", "{text} ({time})"))
        self.le_hdr_fmt.textChanged.connect(
            lambda v: (self.data.update({"ctrl_e_format": v}), self.mark_dirty())
        )
        hdr_row.addWidget(self.le_hdr_fmt)
        btn_hdr_edit = QPushButton(tr("Edit…", getattr(self, "_current_lang", "EN")))
        btn_hdr_edit.setToolTip(tr("Open the header format editor (placeholders, presets, live preview)", getattr(self, "_current_lang", "EN")))
        btn_hdr_edit.setFixedWidth(44)
        btn_hdr_edit.clicked.connect(self.open_header_format_editor)
        hdr_row.addWidget(btn_hdr_edit)


        def _settings_group(title, items):
            col = QVBoxLayout()
            col.setContentsMargins(0, 0, 0, 0)
            col.setSpacing(1)
            col.setAlignment(Qt.AlignmentFlag.AlignTop)
            header = QLabel(tr(title, self._current_lang))
            header.setStyleSheet("font-weight: bold; padding: 0 0 1px 0;")
            col.addWidget(header)

            grid = QGridLayout()
            grid.setContentsMargins(0, 0, 0, 0)
            grid.setSpacing(2)
            grid.setHorizontalSpacing(10)

            r, c = 0, 0
            for item in items:
                if isinstance(item, QHBoxLayout):
                    if c != 0:
                        r += 1
                        c = 0
                    grid.addLayout(item, r, 0, 1, 2)
                    r += 1
                else:
                    grid.addWidget(item, r, c)
                    c += 1
                    if c > 1:
                        c = 0
                        r += 1

            col.addLayout(grid)
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
            self.cb_date_daypart, self.cb_date_emoji, self.cb_date_text_month, self.cb_date_ampm,
            self.cb_analog_clock, self.cb_trash_vision, self.cb_silo_color_box, self.cb_customize_toolbar
        ]), 1)
        groups_row.addWidget(_vline())
        groups_row.addLayout(_settings_group("Editor", [
            self.cb_focus, self.cb_wrap, self.cb_ctrl_c, self.cb_lock_cursor,
            self.cb_line_numbers, self.cb_code_gutter, self.cb_line_marks, self.cb_zebra, self.cb_double_line, self.cb_bold_titles,
            div_row, hdr_row
        ]), 1)
        groups_row.addWidget(_vline())
        gap_row = QHBoxLayout()
        gap_row.setContentsMargins(0, 0, 0, 0)
        gap_row.setSpacing(4)
        lbl_gap = QLabel(tr("UI Gaps:", getattr(self, "_current_lang", "EN")))
        lbl_gap.setStyleSheet("color: #808080;")
        gap_row.addWidget(lbl_gap)
        self.spin_silo_gap = QSpinBox()
        self.spin_silo_gap.setRange(0, 50)
        self.spin_silo_gap.setToolTip(tr("Silo Gap Height", getattr(self, "_current_lang", "EN")))
        try:
            self.spin_silo_gap.setValue(int(self.data.get("silo_gap_height", 8)))
        except:
            self.spin_silo_gap.setValue(8)
        def _update_gap(v):
            self.data.update({"silo_gap_height": str(v)})
            if hasattr(self, "silo_gap_widget"): self.silo_gap_widget.setFixedHeight(v)
            if hasattr(self, "sections_gap_widget"): self.sections_gap_widget.setFixedHeight(v)
            self.mark_dirty()
        self.spin_silo_gap.valueChanged.connect(_update_gap)
        gap_row.addWidget(self.spin_silo_gap)

        self.spin_drag_width = QSpinBox()
        self.spin_drag_width.setRange(1, 50)
        self.spin_drag_width.setToolTip(tr("Splitter Handle Width", getattr(self, "_current_lang", "EN")))
        try:
            self.spin_drag_width.setValue(int(self.data.get("splitter_width", 1)))
        except:
            self.spin_drag_width.setValue(1)
        def _update_drag(v):
            self.data.update({"splitter_width": str(v)})
            if hasattr(self, "splitter"): self.splitter.setHandleWidth(v)
            self.mark_dirty()
        self.spin_drag_width.valueChanged.connect(_update_drag)
        gap_row.addWidget(self.spin_drag_width)
        gap_row.addStretch(1)

        groups_row.addLayout(_settings_group("Data & Appearance", [
            self.cb_silo_home, self.cb_silo_pinned_gap, self.cb_silo_ticks,
            self.cb_snippet_arrows, self.cb_hide_shortkeys,
            self.cb_portable_backup, self.cb_sound, self.cb_typewriter,
            vol_row, files_row, gap_row
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
        try:
            self.splitter.setHandleWidth(int(self.data.get("splitter_width", 1)))
        except:
            self.splitter.setHandleWidth(1)

        self.left_panel = QWidget()
        self.left_panel_layout = QVBoxLayout(self.left_panel)
        self.left_panel_layout.setContentsMargins(0, 0, 0, 0)
        self.left_panel_layout.setSpacing(0)

        self.snippets_section = QWidget()
        self.snippets_section_layout = QVBoxLayout(self.snippets_section)
        self.snippets_section_layout.setContentsMargins(0, 0, 0, 0)
        self.snippets_section_layout.setSpacing(1)


        self.search_bar = QLineEdit()
        self.search_bar.setToolTip(tr("Search snippets", getattr(self, "_current_lang", "EN")))
        self.search_bar.setPlaceholderText(tr("Search...", getattr(self, "_current_lang", "EN")))
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
        self.arc_label = QLabel(tr("Archive", getattr(self, "_current_lang", "EN")))
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
        self.sections_gap_widget.setStyleSheet("margin: 2px 8px; background: transparent;")
        self.sections_gap_widget.hide()
        self.left_panel_layout.addWidget(self.sections_gap_widget)

        self.left_panel_layout.addWidget(self.silos_section, 1)

        # Mouse-wheel paging over the sidebar sections and tabs;
        # Ctrl+wheel walks the silo selection one by one.
        WheelPager(self.silos_section, self.change_silo_page, ctrl_callback=self.navigate_silo)
        WheelPager(self.archive_section, self.change_arc_page, ctrl_callback=self.navigate_silo)
        WheelPager(self.snippets_section, self.change_page)
        WheelPager(self.cat_combo, self._wheel_switch_tab)
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
        self.cat_combo.setToolTip(tr("Projects — mouse wheel switches tabs", getattr(self, "_current_lang", "EN")))

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
        self.search_input.setPlaceholderText(tr("Find...", getattr(self, "_current_lang", "EN")))
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
        self.replace_input.setPlaceholderText(tr("Replace with...", getattr(self, "_current_lang", "EN")))
        search_layout.addWidget(self.replace_input)

        self.btn_replace = QPushButton(tr("Rpl", getattr(self, "_current_lang", "EN")))
        self.btn_replace.clicked.connect(self.replace_text)
        self.apply_button_size(self.btn_replace, 24)
        search_layout.addWidget(self.btn_replace)

        self.btn_replace_all = QPushButton(tr("Rpl All", getattr(self, "_current_lang", "EN")))
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
        self._current_lang = get_language(self.data)
        self.apply_wrap_mode()
        self.text_area.setPlaceholderText(tr("Think deeply.", getattr(self, "_current_lang", "EN")))
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

        safe_idx = max(0, min(self.data.get("last_tab_idx", 0), self.cat_combo.count() - 1))
        if self.cat_combo.count() > 0:
            self.cat_combo.setCurrentIndex(safe_idx)

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
        cat = self.data["cats_order"][0] if self.data.get("cats_order") else "Text"
        self.silo_last_edited = self.data.setdefault("silo_last_edited_all", {}).setdefault(cat, {})

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
        self.text_area.document().clearUndoRedoStacks()

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
            if c in ("Text", self.data["cats_order"][0] if self.data.get("cats_order") else "Text"):
                text_idx = i
                break
        self.cat_combo.setCurrentIndex(text_idx)
        self.on_tab_changed(text_idx)

    def insert_timestamp_at_end(self):
        cursor = self.text_area.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.EndOfBlock)
        ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        prefix = " " if cursor.block().text().strip() else ""
        cursor.insertText(f"{prefix}{ts}")
        self.text_area.setTextCursor(cursor)
        self.text_area.ensureCursorVisible()
        self.text_area.setFocus()
        self.mark_dirty()

    def open_header_format_editor(self):
        """Open the comprehensive Ctrl+E header template editor."""
        from fastprompter.ui.header_format_dialog import HeaderFormatDialog
        prev = getattr(self, "ignore_focus_loss", False)
        self.ignore_focus_loss = True
        try:
            HeaderFormatDialog(self).exec()
        finally:
            self.ignore_focus_loss = prev

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

        template = self.data.get("ctrl_e_format", "{text} ({time})")
        
        try:
            from fastprompter.ui.header_format_dialog import LEGACY_TEMPLATE_MIGRATION
            if template in LEGACY_TEMPLATE_MIGRATION:
                template = LEGACY_TEMPLATE_MIGRATION[template]
                self.data["ctrl_e_format"] = template
                self.mark_dirty()
        except ImportError:
            pass
            
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

        now = datetime.datetime.now()
        h = now.hour
        if 5 <= h < 12: daypart = "Morning"
        elif 12 <= h < 17: daypart = "Day"
        elif 17 <= h < 22: daypart = "Evening"
        else: daypart = "Night"

        text_month = self.data.get("date_text_month", "False") == "True"
        m_fmt = "%d %b" if text_month else "%d.%m"
        ts = now.strftime(f"{m_fmt} - {self._clock_time_fmt()}")

        # {state} in the template takes over the day word; otherwise the
        # legacy behavior prefixes it inside {time} when Day Word is on
        if "{state}" in template:
            time_str = ts
        else:
            time_str = f"{daypart} {ts}" if self.data.get("date_daypart", "True") == "True" else ts

        # Strip any existing header hashes or list bullets so they don't get trapped
        clean_sel = re.sub(r'^(?:#+\s*|[-*•●+]\s+)+', '', sel).strip()
        if not clean_sel:
            clean_sel = sel.strip()

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

    def _retranslate_preview_combo(self, lang):
        """Set each View-combo item's display text from its English itemData.

        itemData stays English (the lookup key); only the visible label is
        localized. Translating from the base — not the current display text —
        is what lets the combo recover when you switch away from a language
        whose script it can't reverse-map (e.g. Arabic -> grandpa/RU)."""
        combo = getattr(self, "preview_combo", None)
        if combo is None or sip.isdeleted(combo):
            return
        combo.blockSignals(True)
        for i in range(combo.count()):
            base = combo.itemData(i) or combo.itemText(i)
            combo.setItemText(i, tr(base, lang))
        combo.blockSignals(False)

    def _on_language_changed(self, lang):
        """Handle language combo change: persist and refresh UI text."""
        if lang == self._current_lang:
            return
        self._current_lang = lang
        self.data["language"] = lang
        self.mark_dirty()
        self._apply_settings_language()

    def _apply_settings_language(self):
        """Re-apply translations to all settings widgets."""
        lang = self._current_lang
        # Translate _settings_group headers — find the header QLabels in mini_settings_frame
        for child in self.mini_settings_frame.findChildren(QLabel):
            en = getattr(child, "_en_text", None) or child.text()
            # Only translate known labels (those that are group headers or static labels)
            translated = tr(en, lang)
            if translated != en:
                child.setText(translated)

        # Translate all checkboxes in the settings panel
        for cb_name in ("cb_top", "cb_lock_window", "cb_normal_window", "cb_tray",
                        "cb_sidebar", "cb_focus", "cb_snippet_arrows", "cb_silo_ticks",
                        "cb_ctrl_c", "cb_lock_cursor", "cb_silo_home", "cb_portable_backup",
                        "cb_wrap", "cb_line_numbers", "cb_line_marks", "cb_zebra", "cb_hide_shortkeys",
                        "cb_double_line", "cb_bold_titles", "cb_silo_pinned_gap",
                        "cb_date_rect", "cb_date_seconds", "cb_analog_clock",
                        "cb_date_daypart", "cb_date_emoji", "cb_date_text_month", "cb_date_ampm", "cb_sound",
                        "cb_typewriter", "cb_trash_vision", "cb_silo_color_box"):
            cb = getattr(self, cb_name, None)
            if cb is not None and not sip.isdeleted(cb):
                en_text = getattr(cb, "_en_text", None)
                if en_text:
                    cb.setText(tr(en_text, lang))
                en_tip = getattr(cb, "_en_tooltip", None)
                if en_tip:
                    cb.setToolTip(tr(en_tip, lang))

        # Translate action checkboxes
        for ac_name in ("btn_hotkeys", "btn_colors", "btn_backup", "btn_restore"):
            ac = getattr(self, ac_name, None)
            if ac is not None and not sip.isdeleted(ac):
                en_text = getattr(ac, "_en_text", None)
                if en_text:
                    ac.setText(tr(en_text, lang))

        # Translate button_scale text (has dynamic percentage)
        if hasattr(self, "btn_button_scale") and not sip.isdeleted(self.btn_button_scale):
            try:
                pct = int(float(self.data.get("ui_scale", "1.0")) * 100)
            except Exception:
                pct = 100
            self.btn_button_scale.setText(f"{tr('Scale', lang)}: {pct}%")

        # Translate static labels
        static_labels = [
            "Font:", "Theme:", "View:",
            "Language:", "Volume:", "Line gaps:",
            "Header Fmt:",
            "Window", "Editor",
            "Data && Appearance", "Data & Appearance"
        ]
        from fastprompter.core.translations import _DATA
        rev_data = {v: k for k, v in _DATA.items()}
        for child in self.mini_settings_frame.findChildren(QLabel):
            txt = child.text()
            en_txt = rev_data.get(txt, txt)
            if en_txt in static_labels:
                child.setText(tr(en_txt, lang))

        # Translate spinbox tooltips
        if hasattr(self, "spin_div_before") and not sip.isdeleted(self.spin_div_before):
            self.spin_div_before.setToolTip(tr("Lines before ---", lang))
        if hasattr(self, "spin_div_after") and not sip.isdeleted(self.spin_div_after):
            self.spin_div_after.setToolTip(tr("Lines after --- (before the fresh bullet)", lang))
        if hasattr(self, "spin_volume") and not sip.isdeleted(self.spin_volume):
            self.spin_volume.setToolTip(tr("Click sound volume (1-10)", lang))

        # Translate files_row buttons
        if hasattr(self, "btn_files_root") and not sip.isdeleted(self.btn_files_root):
            self.btn_files_root.setText(tr("Files Folder...", lang))
            self.btn_files_root.setToolTip(
                tr("Choose where silo file containers are stored.\nDefault: data/files next to the app.", lang))

        # Translate preview combo items from their English base (itemData),
        # never from the current — possibly already-translated — display text.
        if hasattr(self, "preview_combo") and not sip.isdeleted(self.preview_combo):
            self._retranslate_preview_combo(lang)
            self.preview_combo.setToolTip(
                tr("Source View: Plain text editor\nLive Preview: Editor with live markdown highlights (default)\nReading: Read-only rendered markdown view", lang))

        # Translate _day_part used in _update_date_label
        self._update_date_label()

        # Translate sidebar tooltips
        for attr_name, en_val, tip_attr in (
            ("btn_trash", "Open Trash", "toolTip"),
            ("btn_arc_snip", "Archive Active Snippet or Silo", "toolTip"),
            ("btn_toggle_archive", "Toggle Archives", "toolTip"),
            ("search_bar", "Search snippets", "toolTip"),
            ("search_bar", "Search...", "placeholderText"),
        ):
            wdg = getattr(self, attr_name, None)
            if wdg is not None and not sip.isdeleted(wdg):
                if tip_attr == "toolTip":
                    wdg.setToolTip(tr(en_val, lang))
                elif tip_attr == "placeholderText":
                    wdg.setPlaceholderText(tr(en_val, lang))

        # Re-apply hotkey tooltips (cheat sheet on Keys button)
        if hasattr(self, '_apply_tooltips'):
            self._apply_tooltips()

    def on_splitter_moved(self, pos, index):
        is_right = getattr(self, "_sidebar_right", False)
        self.data["splitter_sizes_right" if is_right else "splitter_sizes_left"] = self.splitter.sizes()
        self.mark_dirty()

    def open_drop_zones_settings(self):
        from fastprompter.ui.drop_overlay import DropZonesDialog
        dlg = DropZonesDialog(self)
        dlg.exec()
        if hasattr(self, "btn_drop_zones"):
            self.btn_drop_zones.setChecked(False)

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
        cmap = self.data.get("silo_children", {})
        if isinstance(cmap, dict):
            new_map = {remap(int(p)): [remap(int(k)) for k in kids]
                       for p, kids in cmap.items()}
            cmap.clear()
            cmap.update(new_map)
        collapsed = self.data.get("silo_collapsed", [])
        if isinstance(collapsed, list):
            collapsed[:] = [remap(c) for c in collapsed]
        # folder names are keyed by slot -> remap so a moved silo keeps its files
        fmap = self.data.get("silo_folders", {})
        if isinstance(fmap, dict):
            new_fmap = {}
            for k, v in fmap.items():
                try:
                    new_fmap[str(remap(int(k)))] = v
                except (ValueError, TypeError):
                    new_fmap[k] = v
            fmap.clear()
            fmap.update(new_fmap)
        pmap = self.data.get("silo_project_paths", {})
        if isinstance(pmap, dict):
            new_pmap = {}
            for k, v in pmap.items():
                try:
                    new_pmap[str(remap(int(k)))] = v
                except (ValueError, TypeError):
                    new_pmap[k] = v
            pmap.clear()
            pmap.update(new_pmap)

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
        # Skip HWND recreation if flags haven't actually changed
        current = self.windowFlags()
        # Strip WindowStaysOnTopHint from comparison — AOT handled separately via SetWindowPos
        current_stripped = current & ~Qt.WindowType.WindowStaysOnTopHint
        if current_stripped == flags:
            # Only AOT state may differ — handle via SetWindowPos
            if self._always_on_top:
                try:
                    ctypes.windll.user32.SetWindowPos(
                        int(self.winId()), -1, 0, 0, 0, 0, 0x0002 | 0x0001
                    )
                except Exception:
                    pass
            return
        self.unregister_all_hotkeys()
        was_visible = self.isVisible()
        # setWindowFlags recreates the native window; the resulting
        # activation-change would trigger the click-out auto-hide and make
        # the toggle look broken. Suppress it until the dust settles.
        self._increment_focus_lock()
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
        QTimer.singleShot(300, self._decrement_focus_lock)
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
        self._increment_focus_lock()
        dlg.show()
        dlg.raise_()
        dlg.activateWindow()
        QTimer.singleShot(300, self._decrement_focus_lock)

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
            "silo_children": copy.deepcopy(self.data.get("silo_children", {})),
            "silo_collapsed": list(self.data.get("silo_collapsed", [])),
            "silo_folders": dict(self.data.get("silo_folders", {})),
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
            
            MAX_CHARS = 20_000_000
            while len(self.data_redo_stack) > 50:
                self.data_redo_stack.pop(0)
                
            def _get_size(st):
                # snapshots store temp_presets/archive as flat LISTS — handle
                # both shapes so this can never crash the redo push (see the
                # matching guard in add_data_undo_state)
                size = 0
                for key in ("temp_presets", "archive_temp_presets"):
                    d = st.get(key)
                    if isinstance(d, dict):
                        for cats in d.values():
                            if isinstance(cats, (list, tuple)):
                                size += sum(len(t) for t in cats if isinstance(t, str))
                    elif isinstance(d, (list, tuple)):
                        size += sum(len(t) for t in d if isinstance(t, str))
                return size

            while len(self.data_redo_stack) > 1 and sum(_get_size(s) for s in self.data_redo_stack) > MAX_CHARS:
                self.data_redo_stack.pop(0)
            self._apply_data_state(state)
            self.play_sound("tick")
            # Keep data undo "fresh" so repeated Ctrl+Z keeps popping this stack
            self._last_data_action_time = self._bump_action_seq()
            self._save_undo_state()
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
            self._save_undo_state()
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
            if self.cat_combo.currentIndex() != idx:
                self.cat_combo.blockSignals(True)
                self.cat_combo.setCurrentIndex(idx)
                self.cat_combo.blockSignals(False)
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
            cmap = self.data.setdefault("silo_children_all", {}).setdefault(snap_cat, {})
            cmap.clear()
            cmap.update(copy.deepcopy(state.get("silo_children", {})))
            self.data["silo_children"] = cmap
            clist = self.data.setdefault("silo_collapsed_all", {}).setdefault(snap_cat, [])
            clist[:] = list(state.get("silo_collapsed", []))
            self.data["silo_collapsed"] = clist
            fdict = self.data.setdefault("silo_folders_all", {}).setdefault(snap_cat, {})
            fdict.clear()
            fdict.update(dict(state.get("silo_folders", {})))
            self.data["silo_folders"] = fdict
            # a restored silo must get its files back too — pull the folder
            # out of _trash if the delete/clear moved it there
            self._restore_trashed_folders(snap_cat)
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
            self.btn_save.setText(tr("Save Snippet", getattr(self, "_current_lang", "EN")))
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

    def _save_undo_state(self):
        import json
        import os
        import threading
        u_copy = list(getattr(self, "data_undo_stack", []))
        r_copy = list(getattr(self, "data_redo_stack", []))
        def save(undo_data, redo_data):
            try:
                # Cap the persisted snapshots to prevent bloat (H-302)
                undo_data = undo_data[-10:]
                redo_data = redo_data[-10:]
                
                db_path = getattr(self.state, "db_path", "")
                if not db_path:
                    return
                undo_path = os.path.splitext(db_path)[0] + "_undo.json"
                tmp_path = undo_path + ".tmp"
                
                # Serialize the save and make it atomic (H-301)
                with getattr(self, "_undo_save_lock", threading.Lock()):
                    with open(tmp_path, "w", encoding="utf-8") as f:
                        json.dump({
                            "undo": undo_data,
                            "redo": redo_data
                        }, f)
                    os.replace(tmp_path, undo_path)
            except Exception as e:
                from fastprompter.core.logging import logger
                logger.error(f"Failed to save undo state: {e}")
        threading.Thread(target=save, args=(u_copy, r_copy), daemon=True).start()

    def _load_undo_state(self):
        import json
        import os
        try:
            db_path = getattr(self.state, "db_path", "")
            if not db_path:
                return
            undo_path = os.path.splitext(db_path)[0] + "_undo.json"
            if os.path.exists(undo_path):
                with open(undo_path, encoding="utf-8") as f:
                    data = json.load(f)
                    self.data_undo_stack = data.get("undo", [])
                    self.data_redo_stack = data.get("redo", [])
        except Exception as e:
            from fastprompter.core.logging import logger
            logger.error(f"Failed to load undo state: {e}")
            self.data_undo_stack = []
            self.data_redo_stack = []

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
        
        # Enforce caps (50 items max, ~20MB max)
        MAX_CHARS = 20_000_000
        while len(self.data_undo_stack) > 50:
            self.data_undo_stack.pop(0)
            
        def _get_size(st):
            # Snapshots store temp_presets/archive as flat LISTS of silo text
            # (not per-category dicts) — handle both shapes defensively so a
            # structure change can never crash the undo push again.
            size = 0
            for key in ("temp_presets", "archive_temp_presets"):
                d = st.get(key)
                if isinstance(d, dict):
                    for cats in d.values():
                        if isinstance(cats, (list, tuple)):
                            size += sum(len(t) for t in cats if isinstance(t, str))
                elif isinstance(d, (list, tuple)):
                    size += sum(len(t) for t in d if isinstance(t, str))
            return size

        while len(self.data_undo_stack) > 1 and sum(_get_size(s) for s in self.data_undo_stack) > MAX_CHARS:
            self.data_undo_stack.pop(0)
        self.data_redo_stack.clear()
        # Lets Ctrl+Z pick data undo over text undo when this action is newer
        self._last_data_action_time = self._bump_action_seq()
        self._save_undo_state()

    def build_categories(self):
        """Rebuild the tab bar from cats_order."""
        self.cat_combo.blockSignals(True)
        while self.cat_combo.count() > 0:
            self.cat_combo.removeItem(0)
        for cat in self.data["cats_order"]:
            self.cat_combo.addItem(cat)
        self.cat_combo.blockSignals(False)
        if self.cat_combo.count() > 0:
            self.cat_combo.setCurrentIndex(0)
        self.refresh_snippets_panel()

    def _sync_silo_folder(self, cat, old_text, new_text):
        """Deprecated: folder identity is now the per-slot silo_folders map
        (see _silo_folder_name), which follows retitles itself. This
        title-based rename would fight the map, so it is a no-op."""
        return
        from fastprompter.ui.file_container import silo_files_dir, silo_slug  # noqa
        if silo_slug(old_text) == silo_slug(new_text):
            return
        old_dir = silo_files_dir(self._files_root(), cat, old_text)
        new_dir = silo_files_dir(self._files_root(), cat, new_text)
        try:
            if os.path.isdir(old_dir):
                if os.path.exists(new_dir) and os.path.isdir(new_dir) and not os.listdir(new_dir):
                    os.rmdir(new_dir)
                if not os.path.exists(new_dir):
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
                tr("Confirm", self._current_lang),
                tr("App will restart. Proceed?", self._current_lang),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply == QMessageBox.StandardButton.Yes:
                db_path = self.state.db_path
                if os.path.abspath(path) == os.path.abspath(db_path):
                    QMessageBox.warning(self, tr("Error", self._current_lang), tr("Source and destination are the same file.", self._current_lang))
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
            QMessageBox.critical(self, tr("Error", self._current_lang), tr("Failed to restore backup:\n{}", self._current_lang).format(e))
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
                self, tr("Tab Limit", self._current_lang), tr("Maximum of 5 tabs/projects. Remove one first.", self._current_lang)
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
            self.cat_combo.addItem(name)
            self.cat_combo.setCurrentIndex(self.cat_combo.count() - 1)
            self.mark_dirty()

    def del_category(self):
        self.play_sound("delete")
        if self.cat_combo.count() <= 1:
            return
        idx = self.cat_combo.currentIndex()
        cat = self.data["cats_order"][idx]
        self.ignore_focus_loss = True
        try:
            reply = QMessageBox.question(
                self,
                tr("Delete Tab", self._current_lang),
                tr("Nuke '{}' and all snippets?", self._current_lang).format(cat),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
        finally:
            self.ignore_focus_loss = False
        self.activateWindow()
        if reply == QMessageBox.StandardButton.Yes:
            self.add_data_undo_state("Delete category")
            
            # 1. Trash all physical file containers for this category
            from fastprompter.ui.file_container import silo_slug
            trash_targets = []
            fmap = self.data.get("silo_folders_all", {}).get(cat, {})
            trash_targets.extend(fmap.values())
            amap = self.data.get("archive_silo_folders_all", {}).get(cat, {})
            trash_targets.extend(amap.values())
            
            # Archive silos without explicit folder mappings use their title slug
            for text in self.data.get("archive_temp_presets_all", {}).get(cat, []):
                trash_targets.append(silo_slug(text))
                
            for folder_name in set(trash_targets):
                if folder_name:
                    d = os.path.join(self._files_root(), folder_name)
                    if os.path.exists(d):
                        self._delete_file_container(d)
                        
            # 2. Cleanup all category state from DB
            self.data["cats_order"].pop(idx)
            self.data.get("categories", {}).pop(cat, None)
            
            _all_keys = [
                "temp_presets_all", "archive_temp_presets_all", "pinned_silos_all",
                "silo_ticked_all", "silo_children_all", "silo_collapsed_all",
                "silo_colors_all", "silo_folders_all", "archive_silo_folders_all",
                "silo_last_edited_all", "silo_project_paths_all", "archive_project_paths_all"
            ]
            for key in _all_keys:
                self.data.get(key, {}).pop(cat, None)

            if cat in self.current_pages:
                del self.current_pages[cat]
            self.cat_combo.removeItem(idx)
            self.mark_dirty()

    def _wheel_switch_tab(self, direction):
        """Mouse wheel over the tab bar switches projects."""
        idx = self.cat_combo.currentIndex() + direction
        if 0 <= idx < self.cat_combo.count():
            self.cat_combo.setCurrentIndex(idx)

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
            self.data["silo_children"] = self.data.setdefault("silo_children_all", {}).setdefault(
                cat, {}
            )
            self.data["silo_collapsed"] = self.data.setdefault("silo_collapsed_all", {}).setdefault(
                cat, []
            )
            self.data["silo_folders"] = self.data.setdefault("silo_folders_all", {}).setdefault(
                cat, {}
            )
            self.data["archive_silo_folders"] = self.data.setdefault("archive_silo_folders_all", {}).setdefault(
                cat, {}
            )
            self.data["silo_project_paths"] = self.data.setdefault("silo_project_paths_all", {}).setdefault(
                cat, {}
            )
            self.data["archive_project_paths"] = self.data.setdefault("archive_project_paths_all", {}).setdefault(
                cat, {}
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

    def _match_snippet_query(self, query, s):
        if not query:
            return True
        text = (s.get("name", "") + " " + s.get("text", "")).lower()
        for term in query.split():
            if term not in text:
                return False
        return True

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
                if self._match_snippet_query(query, s):
                    active_items.append((i, s))

        total_active = len(active_items)
        if total_active == 0:
            self.snippets_widget.setVisible(False)
            self.btn_page_up.setVisible(False)
            self.btn_page_down.setVisible(False)
            if hasattr(self, "sections_gap_widget"):
                self.sections_gap_widget.setVisible(False)
            self.refresh_archive_panel()
            return

        self.snippets_section.setVisible(True)
        self.snippets_widget.setVisible(True)
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
                # tolerate old/foreign entries (e.g. a pre-fix Trash-category
                # item saved with "title" instead of "name") instead of crashing
                disp = item.get("name") or item.get("title") or "Untitled"
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

            fcount = self._silo_file_count(slot_idx, is_archive=True)
            if fcount > 0:
                line_str = f"📁{fcount} " + line_str if line_str else f"📁{fcount}"
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
            self._update_project_buttons()
            # seed the live folder-sync baseline for the new silo
            from fastprompter.ui.file_container import silo_slug as _sl2
            cur_text = self.text_area.toPlainText()
            self._active_silo_slug = _sl2(
                cur_text[:cur_text.index("\n")] if "\n" in cur_text else cur_text)
            self.text_area.setFocus()
            self.text_area.ensureCursorVisible()
            if not initial:
                self.mark_dirty()
        finally:
            self._end_batch_update()

    def _switch_to_arc_slot(self, idx):
        self._switch_to_slot(idx, is_archive=True)

    def open_trash(self):
        if "Trash" not in self.data["categories"]:
            self.data["categories"]["Trash"] = []
        if "Trash" not in self.data["cats_order"]:
            self.data["cats_order"].append("Trash")
            self.cat_combo.addItem("Trash")
        idx = self.data["cats_order"].index("Trash")
        if self.cat_combo.currentIndex() == idx:
            # We are already in Trash; toggle back
            prev_idx = getattr(self, "_pre_trash_cat_idx", 0)
            if prev_idx == idx or prev_idx >= self.cat_combo.count():
                prev_idx = 0
            self.cat_combo.setCurrentIndex(prev_idx)
        else:
            self._pre_trash_cat_idx = self.cat_combo.currentIndex()
            self.cat_combo.setCurrentIndex(idx)

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
        # Compute display order: pinned first (pin order), then unpinned by
        # index; children follow their parent (hidden while collapsed)
        children_map = self._children_map()
        all_kids = {k for kids in children_map.values() for k in kids}
        collapsed = set(self.data.get("silo_collapsed", []))
        unpinned = [j for j in range(total) if j not in pinned_list and j not in all_kids]
        top_order = [p for p in pinned_list if p < total and p not in all_kids] + unpinned
        display_order = []
        child_of = {}
        for t in top_order:
            display_order.append(t)
            if t not in collapsed:
                for k in children_map.get(t, []):
                    if 0 <= k < total:
                        display_order.append(k)
                        child_of[k] = t
        # pagination follows what's actually displayed (collapse shrinks it)
        max_page = max(0, math.ceil(len(display_order) / max(1, self._visible_silos)) - 1)
        self.silo_page = min(self.silo_page, max_page)
        self.btn_page_up.setEnabled(self.silo_page > 0)
        self.btn_page_down.setEnabled(self.silo_page < max_page)
        start_idx = self.silo_page * self._visible_silos
        if not hasattr(self, "silo_gap_widget"):
            from PyQt6.QtWidgets import QFrame
            self.silo_gap_widget = QFrame(self)
            self.silo_gap_widget.setFixedHeight(8)
            self.silo_gap_widget.setStyleSheet("margin: 2px 8px; background: transparent;")
            self.silos_widget.layout.addWidget(self.silo_gap_widget)

        self.silos_widget.layout.removeWidget(self.silo_gap_widget)
        self.silo_gap_widget.hide()

        first_unpinned_ui_index = -1
        show_gap = self.data.get("silo_pinned_gap", "True") == "True"

        for i, btn in enumerate(self.silo_buttons):
            disp_pos = start_idx + i
            if disp_pos >= len(display_order) or i >= self._visible_silos:
                btn.hide()
                continue
            slot_idx = display_order[disp_pos]
            raw = self.data["temp_presets"][slot_idx]
            is_pinned = slot_idx in pinned_list
            is_child = slot_idx in child_of
            kids = children_map.get(slot_idx, [])

            if not is_pinned and not is_child and first_unpinned_ui_index == -1 and pinned_list:
                first_unpinned_ui_index = i

            text = (raw[:100] if len(raw) > 100 else raw).replace("\n", " ").strip()
            if text.startswith("#"):
                text = text[1:].lstrip()

            if is_child:
                parent_idx = child_of[slot_idx]
                p_disp = pinned_list.index(parent_idx) + 1 if parent_idx in pinned_list else unpinned.index(parent_idx) + 1 if parent_idx in unpinned else 0
                c_rank = children_map.get(parent_idx, []).index(slot_idx) + 1
                display_idx = f"{p_disp}.{c_rank}"
            elif is_pinned:
                display_idx = pinned_list.index(slot_idx) + 1
            else:
                display_idx = unpinned.index(slot_idx) + 1

            line_count = raw.count("\n") + 1 if raw.strip() else 0
            line_str = str(line_count) if line_count > 0 else ""

            # the rightmost 📁N button carries the file count — the text
            # counter stays lines-only (no duplicated 📁)
            fcount = self._silo_file_count(slot_idx)
            # No "📌 " text prefix — the pin button itself is the indicator
            # and its click unpins (see DraggableSiloButton.update_data)
            if is_child:
                label = f"↳ {display_idx}: {text}" if text else f"↳ {display_idx}"
            else:
                label = f"{display_idx}: {text}" if text else f"{display_idx}"
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
            has_hash = (
                raw.lstrip().startswith("#")
                and self.data.get("silo_color_box", "True") == "True"
            )
            silo_colors = self.data.get("silo_colors", {})
            if not isinstance(silo_colors, dict):
                silo_colors = {}
            color_hex = silo_colors.get(str(slot_idx), "") if has_hash else ""
            btn.update_data(label, slot_idx, bg_color, font_family, scale, line_count_str=line_str, is_pushed=is_active, title_bold=title_bold, is_child=is_child, fcount=fcount, has_children=len(kids)>0, is_collapsed=slot_idx in collapsed, has_hash=has_hash, color_hex=color_hex, is_pinned=is_pinned)

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
                menu.addAction(tr("📌 Unpin", getattr(self, "_current_lang", "EN")), lambda i=idx: self._toggle_pin_silo(i))
            else:
                menu.addAction(tr("📌 Pin to Top", getattr(self, "_current_lang", "EN")), lambda i=idx: self._toggle_pin_silo(i))
            menu.addAction(tr("📥 Archive", getattr(self, "_current_lang", "EN")), lambda i=idx: self.archive_single_silo(i))
            kids = self._children_map().get(idx, [])
            if kids:
                collapsed_now = idx in self.data.get("silo_collapsed", [])
                menu.addAction(
                    "▾ Expand Children" if collapsed_now else f"▸ Collapse Children ({len(kids)})",
                    lambda i=idx: self.toggle_silo_collapse(i))
            if self.silo_parent_of(idx) is not None:
                menu.addAction(tr("⬆ Un-nest from Parent", getattr(self, "_current_lang", "EN")),
                               lambda i=idx: (self.unnest_silo(i), self.refresh_temp_presets()))
        menu.addAction(tr("📁 Files…", getattr(self, "_current_lang", "EN")), lambda i=idx, a=is_archive: self.open_file_container(i, a))
        menu.addAction(tr("⚙ Configure Project Paths...", getattr(self, "_current_lang", "EN")), lambda i=idx: self.open_silo_settings(i))

        # -- save ---------------------------------------------------------------
        if cur:
            menu.addSeparator()
            menu.addAction(tr("💾 Save text as Snippet", getattr(self, "_current_lang", "EN")), self.save_snippet)
            menu.addAction(tr("💾 Save as Snippet #…", getattr(self, "_current_lang", "EN")), self.save_snippet_as_number)

        # -- destructive (middle-click already trashes a silo directly) -------
        if has_content:
            menu.addSeparator()
            menu.addAction(tr("🗑 Delete to Trash", getattr(self, "_current_lang", "EN")), lambda: self.trash_silo(idx, is_archive))
            menu.addAction(tr("♻ Manage Trash", getattr(self, "_current_lang", "EN")), self.open_trash_folder)

        menu.addSeparator()
        # Transfer to Snippet
        presets_list = (
            self.data["archive_temp_presets"] if is_archive else self.data["temp_presets"]
        )
        if idx < len(presets_list) and presets_list[idx] and presets_list[idx].strip():
            menu.addAction(
                tr("➡ Transfer to Snippet", getattr(self, "_current_lang", "EN")),
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
                tr("⬆ Move to Top", getattr(self, "_current_lang", "EN")),
                lambda i=idx, a=is_archive: self._move_silo_to_top(i, a),
            )
            menu.addAction(
                tr("⬇ Move to Bottom", getattr(self, "_current_lang", "EN")),
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

    def _children_map(self):
        cmap = self.data.get("silo_children")
        return cmap if isinstance(cmap, dict) else {}

    def silo_parent_of(self, idx):
        for p, kids in self._children_map().items():
            if idx in kids:
                return p
        return None

    def make_silo_child(self, child_idx, parent_idx):
        """Nest child under parent (1 level). The child's own children are
        promoted; its files merge into the parent's container on confirm."""
        if child_idx == parent_idx:
            return
        cmap = self.data.setdefault("silo_children", {})
        if self.silo_parent_of(parent_idx) is not None:
            return  # target is itself a child — no grandchildren
        if child_idx in cmap.get(parent_idx, []):
            return
        self.add_data_undo_state("Nest silo")
        cmap.pop(child_idx, None)  # flatten: promoted grandchildren
        for kids in cmap.values():
            if child_idx in kids:
                kids.remove(child_idx)
        cmap.setdefault(parent_idx, []).append(child_idx)
        pinned = self.data.get("pinned_silos", [])
        if isinstance(pinned, list) and child_idx in pinned:
            pinned.remove(child_idx)  # children live under their parent, not in the pin bar
        self._merge_child_files(child_idx, parent_idx)
        self.mark_dirty()
        self.refresh_temp_presets()

    def unnest_silo(self, idx):
        """Promote a child back to top level (dragging it out does this)."""
        changed = False
        for kids in self._children_map().values():
            if idx in kids:
                kids.remove(idx)
                changed = True
        if changed:
            self.mark_dirty()
        return changed

    def toggle_silo_collapse(self, idx):
        collapsed = self.data.setdefault("silo_collapsed", [])
        if idx in collapsed:
            collapsed.remove(idx)
        else:
            collapsed.append(idx)
        self.mark_dirty()
        self.refresh_temp_presets()

    def _merge_child_files(self, child_idx, parent_idx):
        """A nested silo's files can merge into the parent's folder —
        asked once, moved with collision-safe names, never overwritten."""
        import shutil

        from fastprompter.ui.file_container import _unique_dest
        presets = self.data.get("temp_presets", [])
        if not (0 <= child_idx < len(presets) and 0 <= parent_idx < len(presets)):
            return
        src = self._silo_folder_dir(child_idx)
        dst = self._silo_folder_dir(parent_idx)
        try:
            names = os.listdir(src)
        except OSError:
            return
        if not names or os.path.abspath(src) == os.path.abspath(dst):
            return
        box = QMessageBox(self)
        box.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        box.setWindowTitle(tr("Merge files", self._current_lang))
        box.setText(
            tr("The nested silo owns {} file(s).\nMerge them into the parent silo's Files?\n(collisions get ' (2)' names — nothing is overwritten)", self._current_lang).format(len(names)))
        box.setStandardButtons(
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        box.setDefaultButton(QMessageBox.StandardButton.Yes)
        prev = getattr(self, "ignore_focus_loss", False)
        self.ignore_focus_loss = True
        try:
            ans = box.exec()
        finally:
            self.ignore_focus_loss = prev
        if ans != QMessageBox.StandardButton.Yes:
            return
        os.makedirs(dst, exist_ok=True)
        for n in names:
            try:
                shutil.move(os.path.join(src, n), _unique_dest(dst, n))
            except OSError as e:
                from fastprompter.core.logging import logger
                logger.warning(f"Child file merge failed for {n}: {e}")
        try:
            os.rmdir(src)
        except OSError:
            pass

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
        """Move a silo to the bottom — via move_temp_to_index so pins,
        ticks and children indices are remapped with it."""
        presets = self.data["archive_temp_presets"] if is_archive else self.data["temp_presets"]
        if 0 <= idx < len(presets) - 1:
            self.move_temp_to_index(idx, len(presets) - 1, is_archive=is_archive)

    def _move_silo_to_top(self, idx, is_archive=False):
        """Move a silo to the top of the order (same remap guarantees)."""
        presets = self.data["archive_temp_presets"] if is_archive else self.data["temp_presets"]
        if 0 < idx < len(presets):
            self.move_temp_to_index(idx, 0, is_archive=is_archive)

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
            self._trash_silo_content(presets[idx])
            if hasattr(self, "_delete_file_container"):
                folder = self._silo_folder_dir(idx, is_archive=is_archive)
                self._delete_file_container(self.get_current_category(), folder)
                if not is_archive:
                    self.data.get("silo_folders", {}).pop(str(idx), None)
                    self.data.get("silo_project_paths", {}).pop(str(idx), None)
                else:
                    self.data.get("archive_silo_folders", {}).pop(str(idx), None)
                    self.data.get("archive_project_paths", {}).pop(str(idx), None)

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
        new_idx = len(self.data["archive_temp_presets"])
        self.data["archive_temp_presets"].append(self.data["temp_presets"][idx])
        self.data["temp_presets"][idx] = ""
        
        old_k = str(idx)
        new_k = str(new_idx)
        if old_k in self.data.get("silo_folders", {}):
            self.data.setdefault("archive_silo_folders", {})[new_k] = self.data["silo_folders"].pop(old_k)
        if old_k in self.data.get("silo_project_paths", {}):
            self.data.setdefault("archive_project_paths", {})[new_k] = self.data["silo_project_paths"].pop(old_k)
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
        for shortcut in getattr(self, "_app_shortcuts", []):
            shortcut.deleteLater()
        self._app_shortcuts = []

        def add_shortcut(key_name, default_seq, slot, context=Qt.ShortcutContext.WindowShortcut):
            seq_str = self.data.get(key_name, default_seq)
            if not seq_str: return
            shortcut = QShortcut(QKeySequence(seq_str), self, context=context)
            shortcut.activated.connect(slot)
            self._app_shortcuts.append(shortcut)

        add_shortcut("hk_focus", "Ctrl+D", self.toggle_focus_mode)
        add_shortcut("hk_find", "Ctrl+F", self.show_find)
        add_shortcut("hk_replace", "Ctrl+H", self.show_replace)
        add_shortcut("hk_export_silo", "Ctrl+Shift+S", self.save_silo_to_file)
        
        # Previously global hotkeys, now local to app window
        add_shortcut("lock_window_hotkey", "Alt+S", self.toggle_lock)
        add_shortcut("always_on_top_hotkey", "Alt+E", self.toggle_always_on_top)
        add_shortcut("toggle_sidebar_hotkey", "Alt+D", lambda: self.toggle_visibility(force_sidebar=True))
        add_shortcut("hide_on_clickout_hotkey", "Alt+A", self.toggle_hide_on_clickout)

        shortcut = QShortcut(QKeySequence("Esc"), self)
        shortcut.activated.connect(self._on_escape)
        self._app_shortcuts.append(shortcut)

        add_shortcut("hk_save_snippet", "Ctrl+S", self.save_snippet)
        add_shortcut("hk_new_snippet", "Ctrl+N", self.select_empty_silo, Qt.ShortcutContext.ApplicationShortcut)
        add_shortcut("hk_divider", "Ctrl+W", self.insert_divider_line, Qt.ShortcutContext.ApplicationShortcut)
        add_shortcut("hk_snap", "Ctrl+Q", self.cycle_snap_corner)
        add_shortcut("hk_quit", "Ctrl+Alt+Shift+Q", self.quit_app)
        add_shortcut("hk_header", "Ctrl+E", self.apply_header_timestamp)
        add_shortcut("hk_bold", "Ctrl+B", self.apply_bold_smart)
        add_shortcut("hk_undo", "Ctrl+Z", self._smart_undo)

        def add_fixed(seq_str, slot, context=Qt.ShortcutContext.WindowShortcut):
            shortcut = QShortcut(QKeySequence(seq_str), self, context=context)
            shortcut.activated.connect(slot)
            self._app_shortcuts.append(shortcut)

        add_fixed("Ctrl+Shift+Z", self.redo_action)
        add_fixed("Alt+W", self.insert_old_add_line, Qt.ShortcutContext.ApplicationShortcut)
        add_fixed("Alt+Up", lambda: self.navigate_silo(-1), Qt.ShortcutContext.ApplicationShortcut)
        add_fixed("Alt+Down", lambda: self.navigate_silo(1), Qt.ShortcutContext.ApplicationShortcut)
        add_fixed("Ctrl+I", lambda: self.apply_format("italic"))
        add_fixed("Ctrl+U", lambda: self.apply_format("underline"))
        add_fixed("Ctrl+T", lambda: self.apply_format("strike"))

        for i in range(1, 11):
            key_num = i % 10
            add_fixed(f"F{i}", lambda i=i: self.fire_shortcut(i))
            add_fixed(f"Ctrl+{key_num}", lambda i=i: self._switch_to_slot(i - 1))
            add_fixed(f"Ctrl+Shift+{key_num}", lambda i=i: self.fire_shortcut(i))
        
        # Previously global snippet/silo hotkeys, now local to app window
        for i in range(5):
            seq_str = self.data.get(f"snippet_{i}_hotkey", f"Ctrl+Shift+Numpad{i + 1}")
            if seq_str:
                add_fixed(seq_str, lambda i=i: self.fire_global_snippet(i))
            seq_str = self.data.get(f"silo_{i}_hotkey", f"Alt+Shift+Numpad{i + 1}")
            if seq_str:
                add_fixed(seq_str, lambda i=i: self.fire_global_silo(i))

    def fire_shortcut(self, idx):
        self.play_sound("snippet")
        cat = self.get_current_category()
        if not cat:
            return
        query = self._snippet_query()
        active_items = []
        for i, s in enumerate(self.data["categories"][cat]):
            if s is not None:
                if self._match_snippet_query(query, s):
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
        ts = now.strftime(f"{m_fmt} - {self._clock_time_fmt()}")

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

    def _live_folder_sync(self):
        """Deprecated: the per-slot silo_folders map (see _silo_folder_name)
        owns folder identity and follows retitles on its own. This live
        title-rename would fight the map, so it is a no-op."""
        return
        from fastprompter.ui.file_container import silo_slug  # noqa
        doc = self.text_area.document()
        first = doc.firstBlock().text() if doc.blockCount() > 0 else ""
        new_slug = silo_slug(first)
        old_slug = getattr(self, "_active_silo_slug", None)
        if old_slug is None or new_slug == old_slug:
            self._active_silo_slug = new_slug
            return
        cat = self.get_current_category()
        from fastprompter.ui.file_container import silo_slug as _sl
        root = self._files_root()
        old_dir = os.path.join(root, _sl(cat), old_slug)
        new_dir = os.path.join(root, _sl(cat), new_slug)
        try:
            if os.path.isdir(old_dir):
                if os.path.exists(new_dir) and os.path.isdir(new_dir) and not os.listdir(new_dir):
                    os.rmdir(new_dir)
                if not os.path.exists(new_dir):
                    os.makedirs(os.path.dirname(new_dir), exist_ok=True)
                    os.rename(old_dir, new_dir)
        except OSError as e:
            from fastprompter.core.logging import logger
            logger.warning(f"Live folder sync {old_dir} -> {new_dir} failed: {e}")
        self._active_silo_slug = new_slug

    def _on_text_changed(self):
        self._last_text_edit_time = self._bump_action_seq()
        self._update_line_count_label()
        self._live_folder_sync()
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
