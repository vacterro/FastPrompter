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
        from fastprompter.ui.shortcut_display import resolve

        def hk(name):
            return resolve(self, name) or "—"

        h_global = hk("global_hotkey")
        h_pie = hk("pie_menu_hotkey")
        h_lock = hk("lock_window_hotkey")
        h_aot = hk("always_on_top_hotkey")
        h_sidebar = hk("toggle_sidebar_hotkey")
        h_clickout = hk("hide_on_clickout_hotkey")
        h_files = hk("toggle_files_hotkey")

        lang = self._current_lang
        if getattr(self, "cb_top", None) is not None and not _is_deleted(self.cb_top):
            self.cb_top.setToolTip(f"{tr('Always on Top', lang)} ({h_aot})")
        if getattr(self, "cb_lock_window", None) is not None and not _is_deleted(self.cb_lock_window):
            self.cb_lock_window.setToolTip(f"{tr('Lock Window', lang)} ({h_lock})")

        lang = self._current_lang
        # T-1410: every chord below is read from the binding at the moment the
        # sheet is built. They used to be twelve literal strings, which meant a
        # rebound key left this blob advertising the key the user just gave up
        # — the same class of drift as the per-button tooltips. The F1-F10 row
        # is the one exception and stays a range: it names a fixed series, not
        # one command's binding.
        shortcuts_info = (
            f"{tr('--- GLOBAL HOTKEYS (work anywhere) ---', lang)}\n"
            f"{tr('Toggle App Visibility', lang)}: {h_global}\n"
            f"{tr('Pie Menu', lang)}: {h_pie}\n\n"
            f"{tr('--- APP HOTKEYS (only when window active) ---', lang)}\n"
            f"{tr('Lock Window', lang)}: {h_lock}\n"
            f"{tr('Always On Top', lang)}: {h_aot}\n"
            f"{tr('Toggle Sidebar', lang)}: {h_sidebar}\n"
            f"{tr('Toggle Hide-on-Clickout', lang)}: {h_clickout}\n"
            f"{tr('Toggle Files (asset drawer)', lang)}: {h_files}\n"
            f"{hk('hk_snap')} : {tr('Cycle Snap Corners (move across screens)', lang)}\n"
            f"{hk('hk_new_snippet')} : {tr('New Empty Snippet', lang)}\n"
            f"{hk('hk_save_snippet')} : {tr('Save Snippet', lang)}\n"
            f"{hk('hk_undo')} : {tr('Undo Text Change', lang)}\n"
            f"{hk('hk_focus')} : {tr('Toggle Focus Mode', lang)}\n"
            f"{hk('hk_find')} : {tr('Find Text', lang)}\n"
            f"{hk('hk_replace')} : {tr('Replace Text', lang)}\n"
            f"{hk('hk_export_silo')} : {tr('Export/Save Silo to File', lang)}\n"
            f"{hk('escape')} : {tr('Hide Window & Auto-save', lang)}\n"
            f"F1 - F10 : {tr('Switch to Project 1-10 (set fkey_action=snippets for Snippet 1-10)', lang)}\n"
            f"{hk('hk_quit')} : {tr('Quit Application Completely', lang)}"
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
