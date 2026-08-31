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
        h_lock = self.data.get("lock_window_hotkey", "Alt+E")
        h_aot = self.data.get("always_on_top_hotkey", "Alt+S")
        h_sidebar = self.data.get("toggle_sidebar_hotkey", "Alt+D")
        h_clickout = self.data.get("hide_on_clickout_hotkey", "Alt+A")
        h_files = self.data.get("toggle_files_hotkey", "Alt+F")

        lang = self._current_lang
        if hasattr(self, "cb_top") and not _is_deleted(self.cb_top):
            self.cb_top.setToolTip(f"{tr('Always on Top', lang)} ({h_aot})")
        if hasattr(self, "cb_lock_window") and not _is_deleted(self.cb_lock_window):
            self.cb_lock_window.setToolTip(f"{tr('Lock Window', lang)} ({h_lock})")

        lang = self._current_lang
        shortcuts_info = (
            f"{tr('--- GLOBAL HOTKEYS (work anywhere) ---', lang)}\n"
            f"{tr('Toggle App Visibility', lang)}: {h_global}\n"
            f"{tr('Pie Menu', lang)}: {h_pie}\n"
            f"{tr('Stop the Watcher', lang)}: "
            f"{self.data.get('watcher_panic_hotkey', 'Ctrl+Alt+Shift+P')}\n\n"
            f"{tr('--- APP HOTKEYS (only when window active) ---', lang)}\n"
            f"{tr('Lock Window', lang)}: {h_lock}\n"
            f"{tr('Always On Top', lang)}: {h_aot}\n"
            f"{tr('Toggle Sidebar', lang)}: {h_sidebar}\n"
            f"{tr('Toggle Hide-on-Clickout', lang)}: {h_clickout}\n"
            f"{tr('Toggle Files (asset drawer)', lang)}: {h_files}\n"
            f"Ctrl+Q : {tr('Cycle Snap Corners (move across screens)', lang)}\n"
            f"Ctrl+N : {tr('New Empty Snippet', lang)}\n"
            f"Ctrl+S : {tr('Save Snippet', lang)}\n"
            f"Ctrl+Z : {tr('Undo Text Change', lang)}\n"
            f"Ctrl+D : {tr('Toggle Focus Mode', lang)}\n"
            f"Ctrl+F : {tr('Find Text', lang)}\n"
            f"Ctrl+H : {tr('Replace Text', lang)}\n"
            f"Ctrl+Shift+S : {tr('Export/Save Silo to File', lang)}\n"
            f"Esc : {tr('Hide Window & Auto-save', lang)}\n"
            f"F1 - F10 : {tr('Switch to Project 1-10 (set fkey_action=snippets for Snippet 1-10)', lang)}\n"
            f"Ctrl+Alt+Shift+Q : {tr('Quit Application Completely', lang)}"
        )
        if hasattr(self, "btn_hotkeys") and not _is_deleted(self.btn_hotkeys):
            self.btn_hotkeys.setToolTip(shortcuts_info)

    def unregister_all_hotkeys(self):
        """Unregister all Win32 global hotkeys.

        Reports the truth about the operation: False when any id could not
        be unregistered (or was never registered). Every failure is logged —
        a silent best-effort call let a shutdown believe the keys were
        released when they were still live (P1-8).

        Only OS-CONFIRMED releases are dropped from ``registered_hotkeys``;
        an id the OS refused to release (or that was never registered) is
        RETAINED so the local tracking model keeps parity with the real OS
        state. Clearing it would let a later re-registration believe the key
        is free and create an untracked live binding."""
        hwnd = ctypes.wintypes.HWND(int(self.winId()))
        failed = []
        retained = []
        for hk_id in list(self.registered_hotkeys):
            if ctypes.windll.user32.UnregisterHotKey(hwnd, hk_id):
                continue  # OS confirmed release: drop from tracking
            failed.append(hk_id)
            retained.append(hk_id)  # OS still owns it: keep tracked
        if failed:
            from fastprompter.core.logging import logger
            logger.error("hotkey unregister FAILED for ids %s", failed)
        self.registered_hotkeys = retained
        return not failed

    def register_all_hotkeys(self):
        """Register all global hotkeys from config.

        Only toggle_visibility and pie_menu are global. All other hotkeys
        are handled as QShortcut (local to app window) to avoid conflicts.

        Returns False when any registration was attempted but rejected — a
        conflict with another app, an invalid combo. A failed registration
        is REPORTED, never silently skipped (P1-8)."""
        self.unregister_all_hotkeys()
        ok = True
        # Global hotkeys only
        ok = self._register_single(self.data.get("global_hotkey", "Alt+X"), 1) and ok
        ok = self._register_single(self.data.get("global_hotkey_alt", "F15"), 101) and ok
        ok = self._register_single(self.data.get("pie_menu_hotkey", "Shift+Alt+X"), 2) and ok
        ok = self._register_single(self.data.get("pie_menu_hotkey_alt", ""), 102) and ok
        # The watcher types into another application, so its stop key is
        # global: it has to work from whatever window the user is in when
        # they decide it is going wrong, not only from FastPrompter.
        # id 300, well clear of the 1-5/10-24 scheme and its +100 alternates.
        # Ids 3 and 103 are lock, and a test pins them as NOT globally
        # handled - taking one would have re-created the bug where a
        # window-local key fired system-wide.
        ok = self._register_single(
            self.data.get("watcher_panic_hotkey", "Ctrl+Alt+Shift+P"),
            300) and ok
        self._apply_tooltips()
        return ok

    def _register_single(self, hotkey_str, hk_id):
        """Register a single hotkey if the string is non-empty.

        Returns True when the id is now registered (or nothing was asked:
        empty string), False when the OS rejected the registration."""
        if not hotkey_str:
            return True
        try:
            modifiers, vk = parse_hotkey(hotkey_str)
        except Exception:
            # P2: one deterministic, observable error for a malformed config
            # string — identical in observability to an OS rejection, so a
            # weak agent/test cannot mistake an invalid spec for an
            # unattempted optional binding.
            from fastprompter.core.logging import logger
            logger.error("hotkey spec invalid for %r (id %s): parse failed",
                         hotkey_str, hk_id)
            return False
        if vk:
            hwnd = ctypes.wintypes.HWND(int(self.winId()))
            if ctypes.windll.user32.RegisterHotKey(hwnd, hk_id, modifiers, vk):
                self.registered_hotkeys.append(hk_id)
                return True
            from fastprompter.core.logging import logger
            logger.error("hotkey registration FAILED for %r (id %s)",
                         hotkey_str, hk_id)
            return False
        return False
