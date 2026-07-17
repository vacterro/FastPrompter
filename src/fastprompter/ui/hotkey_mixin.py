"""Hotkey mixin for FastPrompter — Win32 global hotkey registration.

Extracted from main.py Phase 2a of the modularization plan.
Provides HotkeyMixin class for use as a mixin with FastPrompter QMainWindow.
"""

import ctypes
import ctypes.wintypes

from PyQt6 import sip

from fastprompter.core.hotkeys import parse_hotkey

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

        if hasattr(self, "cb_top") and not _is_deleted(self.cb_top):
            self.cb_top.setToolTip(f"Always on top ({h_aot})")
        if hasattr(self, "cb_lock_window") and not _is_deleted(self.cb_lock_window):
            self.cb_lock_window.setToolTip(f"Lock Window ({h_lock})")

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
        if hasattr(self, "btn_hotkeys") and not _is_deleted(self.btn_hotkeys):
            self.btn_hotkeys.setToolTip(shortcuts_info)

    def unregister_all_hotkeys(self):
        """Unregister all Win32 global hotkeys."""
        hwnd = ctypes.wintypes.HWND(int(self.winId()))
        for hk_id in self.registered_hotkeys:
            ctypes.windll.user32.UnregisterHotKey(hwnd, hk_id)
        self.registered_hotkeys.clear()

    def register_all_hotkeys(self):
        """Register all global hotkeys from config."""
        self.unregister_all_hotkeys()
        self._register_single(self.data.get("global_hotkey", "Alt+X"), 1)
        self._register_single(self.data.get("global_hotkey_alt", "F15"), 101)
        self._register_single(self.data.get("pie_menu_hotkey", "Shift+Alt+X"), 2)
        self._register_single(self.data.get("pie_menu_hotkey_alt", ""), 102)

        self._register_single(self.data.get("lock_window_hotkey", "Alt+S"), 3)
        self._register_single(self.data.get("lock_window_hotkey_alt", ""), 103)
        self._register_single(self.data.get("always_on_top_hotkey", "Alt+E"), 4)
        self._register_single(self.data.get("always_on_top_hotkey_alt", ""), 104)
        self._register_single(self.data.get("toggle_sidebar_hotkey", "Alt+D"), 5)
        self._register_single(self.data.get("toggle_sidebar_hotkey_alt", ""), 105)
        self._register_single(self.data.get("hide_on_clickout_hotkey", "Alt+A"), 6)
        self._register_single(self.data.get("hide_on_clickout_hotkey_alt", ""), 106)

        for i in range(5):
            self._register_single(
                self.data.get(f"snippet_{i}_hotkey", f"Ctrl+Shift+Numpad{i + 1}"), 10 + i
            )
            self._register_single(self.data.get(f"snippet_{i}_hotkey_alt", ""), 110 + i)
            self._register_single(
                self.data.get(f"silo_{i}_hotkey", f"Alt+Shift+Numpad{i + 1}"), 20 + i
            )
            self._register_single(self.data.get(f"silo_{i}_hotkey_alt", ""), 120 + i)
        self._apply_tooltips()

    def _register_single(self, hotkey_str, hk_id):
        """Register a single hotkey if the string is non-empty."""
        if not hotkey_str:
            return
        try:
            modifiers, vk = parse_hotkey(hotkey_str)
        except Exception:
            return
        if vk:
            hwnd = ctypes.wintypes.HWND(int(self.winId()))
            if ctypes.windll.user32.RegisterHotKey(hwnd, hk_id, modifiers, vk):
                self.registered_hotkeys.append(hk_id)
