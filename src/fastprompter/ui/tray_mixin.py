"""Tray mixin for FastPrompter — system tray icon and context menu.

Extracted from main.py Phase 2a of the modularization plan.
Provides TrayMixin class for use as a mixin with FastPrompter QMainWindow.
"""

import os

from PyQt6 import sip
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QMenu, QSystemTrayIcon

from fastprompter.core.config import create_tray_icon
from fastprompter.core.translations import tr
from fastprompter.utils.paths import get_resource_path

_is_deleted = sip.isdeleted


class TrayMixin:
    """Mixin providing system tray icon and context menu functionality.

    Type hints assume these attributes are provided by the FastPrompter
    QMainWindow instance at runtime:
        self._tray_visible, self.tray_icon, self.data, self._theme_cache
    """

    def init_tray(self):
        """Initialize the system tray icon and context menu."""
        tray_color = self._theme_val("tray_color", "#8b4513")
        icon = create_tray_icon(tray_color)

        self.tray_icon = QSystemTrayIcon(icon, self)
        tray_menu = QMenu(self)
        self._tray_menu = tray_menu

        lang = getattr(self, "_current_lang", "EN")
        self._tray_show_action = tray_menu.addAction(tr("Show/Hide", lang))
        self._tray_show_action.triggered.connect(self.toggle_visibility)
        tray_menu.addSeparator()

        # Checkable toggles. Each one drives the same canonical handler as the
        # footer checkbox it mirrors, so the tray, the header pin and the
        # mini-settings never drift out of sync.
        self._tray_aot_action = self._tray_check_action(
            tray_menu, "📌 Always on Top", self._on_tray_aot
        )
        self._tray_focus_action = self._tray_check_action(
            tray_menu, "👁 Hide on Click-Out", self._on_tray_focus
        )
        self._tray_icon_action = self._tray_check_action(
            tray_menu, "📉 Tray Icon", self._on_tray_icon
        )

        tray_menu.addSeparator()
        self._tray_quit_action = tray_menu.addAction(tr("Quit", lang))
        self._tray_quit_action.triggered.connect(self.quit_app)

        # Refresh check states on every open instead of chasing every code path
        # that can flip a setting (hotkeys, header pin, settings restore).
        tray_menu.aboutToShow.connect(self._sync_tray_menu_checks)

        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.activated.connect(self.on_tray_activated)
        self.restyle_tray_menu()

    def _tray_check_action(self, menu, en_text, handler):
        """A checkable tray action whose label is translated and remembered."""
        action = menu.addAction(tr(en_text, getattr(self, "_current_lang", "EN")))
        action.setCheckable(True)
        action._en_text = en_text
        action.triggered.connect(handler)
        return action

    # --- tray toggle handlers (delegate to the canonical checkbox paths) ---

    def _on_tray_aot(self, checked):
        pin = getattr(self, "_pin_top_toggled", None)
        if callable(pin):
            pin(checked)
        else:
            self.toggle_aot(checked)

    def _on_tray_focus(self, checked):
        cb = getattr(self, "cb_focus", None)
        if cb is not None and not _is_deleted(cb):
            if cb.isChecked() != checked:
                cb.setChecked(checked)  # its toggled handler persists + ticks
        else:
            self.data["close_on_focus_loss"] = "True" if checked else "False"
            self.mark_dirty()

    def _on_tray_icon(self, checked):
        cb = getattr(self, "cb_tray", None)
        if cb is not None and not _is_deleted(cb):
            if cb.isChecked() != checked:
                cb.setChecked(checked)  # its toggled handler calls on_tray_toggled
        else:
            self.on_tray_toggled(checked)

    def _tray_state(self):
        """Current on/off for the three tray toggles, read from live sources."""
        cb_focus = getattr(self, "cb_focus", None)
        return (
            self.data.get("always_on_top", "True") == "True",
            (cb_focus.isChecked()
             if cb_focus is not None and not _is_deleted(cb_focus)
             else self.data.get("close_on_focus_loss", "True") == "True"),
            self.data.get("tray_visible", "True") == "True",
        )

    def _sync_tray_menu_checks(self):
        """Set the checkmarks right each time the menu opens."""
        aot, focus, tray = self._tray_state()
        for action, value in (
            (getattr(self, "_tray_aot_action", None), aot),
            (getattr(self, "_tray_focus_action", None), focus),
            (getattr(self, "_tray_icon_action", None), tray),
        ):
            if action is not None and not _is_deleted(action):
                action.setChecked(value)

    def restyle_tray_menu(self):
        """Skin the tray menu with the active theme's palette.

        The application stylesheet only styles QMenu background + the selected
        item; text padding, the separator and the check indicator would fall
        back to the OS look (a checkmark invisible on dark). This per-menu
        sheet overrides that for the tray menu only.
        """
        menu = getattr(self, "_tray_menu", None)
        if menu is None or _is_deleted(menu):
            return
        raw = (getattr(self, "_theme_cache", None) or {}).get("raw_colors") or {}
        bg = raw.get("btn_bg", "#2b2b2b")
        border_dark = raw.get("border_dark", "#0a0a0a")
        border_light = raw.get("border_light", "#4d4d4d")
        text = raw.get("text_main", "#c0c0c0")
        accent = raw.get("accent", "#5a7a96")
        base = raw.get("bg_main", "#1a1a1a")
        pressed = raw.get("btn_pressed", "#141414")
        menu.setStyleSheet(
            f"QMenu {{ background-color: {bg}; color: {text};"
            f" border: 1px solid {border_dark}; padding: 2px; }}"
            f"QMenu::item {{ color: {text}; background: transparent;"
            f" padding: 3px 22px 3px 22px; }}"
            f"QMenu::item:selected {{ background-color: {accent}; color: {base}; }}"
            f"QMenu::item:pressed {{ background-color: {pressed}; }}"
            f"QMenu::item:disabled {{ color: {border_light}; }}"
            f"QMenu::separator {{ height: 1px; background: {border_dark};"
            f" margin: 2px 4px; }}"
            f"QMenu::indicator {{ width: 13px; height: 13px; }}"
            f"QMenu::indicator:unchecked {{ background: {base};"
            f" border: 1px solid {border_dark}; }}"
            f"QMenu::indicator:checked {{ background: {accent};"
            f" border: 1px solid {border_dark}; }}"
        )

    def retranslate_tray(self):
        """Update tray menu texts for the new language."""
        lang = getattr(self, "_current_lang", "EN")
        if hasattr(self, "_tray_show_action") and not _is_deleted(self._tray_show_action):
            self._tray_show_action.setText(tr("Show/Hide", lang))
        for attr in ("_tray_aot_action", "_tray_focus_action", "_tray_icon_action"):
            action = getattr(self, attr, None)
            if action is not None and not _is_deleted(action):
                action.setText(tr(action._en_text, lang))
        if hasattr(self, "_tray_quit_action") and not _is_deleted(self._tray_quit_action):
            self._tray_quit_action.setText(tr("Quit", lang))
        if hasattr(self, "tray_icon") and not _is_deleted(self.tray_icon):
            self.tray_icon.setVisible(self._tray_visible)

        # Set window icon too
        icon_path = get_resource_path("_res", "fastprompter_logo2.png")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))
        else:
            self.setWindowIcon(QIcon())

    def on_tray_activated(self, reason):
        """Handle double-click on tray icon."""
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            # tray_click_activates: when True, tray click always brings focus
            # regardless of hide-on-clickout mode; when False, behaves like
            # the hotkey (toggle hide/show based on close_on_focus_loss).
            if self.data.get("tray_click_activates", "True") == "True":
                self.show_window()
            else:
                self.toggle_visibility()

    def on_tray_toggled(self, checked):
        """Toggle tray icon visibility."""
        tray_icon = getattr(self, "tray_icon", None)
        if tray_icon is not None:
            tray_icon.setVisible(checked)
        self.data["tray_visible"] = str(checked)
        self.mark_dirty()
