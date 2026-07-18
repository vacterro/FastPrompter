"""Hotkey mixin for FastPrompter — Win32 global hotkey registration.

Extracted from main.py Phase 2a of the modularization plan.
Provides HotkeyMixin class for use as a mixin with FastPrompter QMainWindow.
"""

import ctypes
import ctypes.wintypes

from PyQt6 import sip

from fastprompter.core.hotkeys import parse_hotkey
from fastprompter.core.translations import tr

_is_deleted = sip.isdeleted


class HotkeyMixin:
    """Mixin providing Win32 global hotkey registration.

    Type hints assume these attributes are provided by the FastPrompter
    QMainWindow instance at runtime:
        self.data, self.registered_hotkeys
    """

    def _apply_tooltips(self):
        """Update tooltip for hotkey-related buttons."""
        h_global = self.data.get("global_hotkey", "Alt+X")
        h_pie = self.data.get("pie_menu_hotkey", "Shift+Alt+X")
        h_lock = self.data.get("lock_window_hotkey", "Alt+S")
        h_aot = self.data.get("always_on_top_hotkey", "Alt+E")
        h_sidebar = self.data.get("toggle_sidebar_hotkey", "Alt+D")
        h_clickout = self.data.get("hide_on_clickout_hotkey", "Alt+A")

        lang = self._current_lang
        if hasattr(self, "cb_top") and not _is_deleted(self.cb_top):
            self.cb_top.setToolTip(f"{tr('Always on Top', lang)} ({h_aot})")
        if hasattr(self, "cb_lock_window") and not _is_deleted(self.cb_lock_window):
            self.cb_lock_window.setToolTip(f"{tr('Lock Window', lang)} ({h_lock})")

        lang = self._current_lang
        shortcuts_info = (
            f"{tr('--- GLOBAL HOTKEYS (work anywhere) ---', lang)}\n"
            f"{tr('Toggle App Visibility', lang)}: {h_global}\n"
            f"{tr('Pie Menu', lang)}: {h_pie}\n\n"
            f"{tr('--- APP HOTKEYS (only when window active) ---', lang)}\n"
            f"{tr('Lock Window', lang)}: {h_lock}\n"
            f"{tr('Always On Top', lang)}: {h_aot}\n"
            f"{tr('Toggle Sidebar', lang)}: {h_sidebar}\n"
            f"{tr('Toggle Hide-on-Clickout', lang)}: {h_clickout}\n"
            f"Ctrl+Q : {tr('Cycle Snap Corners (move across screens)', lang)}\n"
            f"Ctrl+N : {tr('New Empty Snippet', lang)}\n"
            f"Ctrl+S : {tr('Save Snippet', lang)}\n"
            f"Ctrl+Z : {tr('Undo Text Change', lang)}\n"
            f"Ctrl+D : {tr('Toggle Focus Mode', lang)}\n"
            f"Ctrl+F : {tr('Find Text', lang)}\n"
            f"Ctrl+H : {tr('Replace Text', lang)}\n"
            f"Ctrl+Shift+S : {tr('Export/Save Silo to File', lang)}\n"
            f"Esc : {tr('Hide Window & Auto-save', lang)}\n"
            f"F1 - F10 : {tr('Execute Snippet 1-10', lang)}\n"
            f"Ctrl+Alt+Shift+Q : {tr('Quit Application Completely', lang)}"
        )
        if hasattr(self, "btn_hotkeys") and not _is_deleted(self.btn_hotkeys):
            self.btn_hotkeys.setToolTip(shortcuts_info)

    def unregister_all_hotkeys(self):
        """Unregister all Win32 global hotkeys."""
        hwnd = ctypes.wintypes.HWND(int(self.winId()))
        for hk_id in self.registered_hotkeys:
            ctypes.windll.user32.UnregisterHotKey(hwnd, hk_id)
        self.registered_hotkeys.clear()

    def register_all_hotkeys(self):
        """Register all global hotkeys from config.
        
        Only toggle_visibility and pie_menu are global. All other hotkeys
        are handled as QShortcut (local to app window) to avoid conflicts.
        """
        self.unregister_all_hotkeys()
        # Global hotkeys only
        self._register_single(self.data.get("global_hotkey", "Alt+X"), 1)
        self._register_single(self.data.get("global_hotkey_alt", "F15"), 101)
        self._register_single(self.data.get("pie_menu_hotkey", "Shift+Alt+X"), 2)
        self._register_single(self.data.get("pie_menu_hotkey_alt", ""), 102)
        self._apply_tooltips()

    def _register_single(self, hotkey_str, hk_id):
        """Register a single hotkey if the string is non-empty."""
        if not hotkey_str:
            return
        try:
            modifiers, vk = parse_hotkey(hotkey_str)
        # TODO: BUG: Silent blanket exception handler swallows errors

        except Exception:
            return
        if vk:
            hwnd = ctypes.wintypes.HWND(int(self.winId()))
            if ctypes.windll.user32.RegisterHotKey(hwnd, hk_id, modifiers, vk):
                self.registered_hotkeys.append(hk_id)
