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
        self._build_problip_tray_menu(tray_menu, lang)
        self._tray_stop_all_action = tray_menu.addAction(
            tr("Stop All Sound", lang))
        self._tray_stop_all_action._en_text = "Stop All Sound"
        self._tray_stop_all_action.triggered.connect(self._on_tray_stop_all)

        tray_menu.addSeparator()
        self._tray_quit_action = tray_menu.addAction(tr("Quit", lang))
        self._tray_quit_action.triggered.connect(self.quit_app)

        # Refresh check states on every open instead of chasing every code path
        # that can flip a setting (hotkeys, header pin, settings restore).
        tray_menu.aboutToShow.connect(self._sync_tray_menu_checks)

        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.activated.connect(self.on_tray_activated)
        self.restyle_tray_menu()

    # --- Problip / audio submenu (T-1238-C4) --------------------------------

    def _build_problip_tray_menu(self, tray_menu, lang):
        """One Problip submenu delegating to the canonical controller.

        The tray owns no state and duplicates no logic: it reads the
        controller on ``aboutToShow`` and calls the same methods the settings
        page calls.
        """
        submenu = tray_menu.addMenu(tr("Problip", lang))
        submenu._en_text = "Problip"
        self._tray_problip_menu = submenu

        self._tray_problip_status = submenu.addAction("")
        self._tray_problip_status.setEnabled(False)
        submenu.addSeparator()

        def _add(en_text, handler):
            action = submenu.addAction(tr(en_text, lang))
            action._en_text = en_text
            action.triggered.connect(handler)
            return action

        self._tray_problip_start = _add("Start", self._on_tray_problip_start)
        self._tray_problip_stop = _add("Stop", self._on_tray_problip_stop)
        self._tray_problip_test = _add("Test", self._on_tray_problip_test)
        submenu.addSeparator()
        self._tray_problip_settings = _add("Open Problip Settings",
                                           self._on_tray_problip_settings)

    def _problip_controller(self):
        return getattr(self, "problip_controller", None)

    def _on_tray_problip_start(self):
        controller = self._problip_controller()
        if controller is not None:
            controller.start()

    def _on_tray_problip_stop(self):
        controller = self._problip_controller()
        if controller is not None:
            controller.stop()

    def _on_tray_problip_test(self):
        controller = self._problip_controller()
        if controller is not None:
            controller.test()

    def _on_tray_problip_settings(self):
        """Show the window, open Settings, select the Problip page (C4.2)."""
        from fastprompter.main import settings_tab_index

        try:
            self.show_window()
        except Exception:
            pass
        try:
            frame = getattr(self, "mini_settings_frame", None)
            if frame is not None and not frame.isVisible():
                frame.setVisible(True)
            elif hasattr(self, "_ensure_settings_built"):
                self._ensure_settings_built()
            tabs = getattr(self, "settings_tabs", None)
            index = settings_tab_index("Problip")
            if tabs is not None and 0 <= index < tabs.count():
                tabs.setCurrentIndex(index)
        except Exception:
            pass

    def _on_tray_stop_all(self):
        manager = getattr(self, "sound_manager", None)
        if manager is not None:
            manager.stop_all_sound()

    def _sync_problip_tray_menu(self):
        """Refresh the submenu from the controller each time it opens."""
        controller = self._problip_controller()
        status = getattr(self, "_tray_problip_status", None)
        start = getattr(self, "_tray_problip_start", None)
        stop = getattr(self, "_tray_problip_stop", None)
        test = getattr(self, "_tray_problip_test", None)
        menu = getattr(self, "_tray_problip_menu", None)
        if menu is None or _is_deleted(menu):
            return
        lang = getattr(self, "_current_lang", "EN")
        if controller is None:
            menu.setEnabled(False)
            return
        menu.setEnabled(True)
        running = controller.is_running()
        state_text = str(controller.state)
        if status is not None and not _is_deleted(status):
            status.setText(f"{tr('Status', lang)}: {tr(state_text, lang)}")
        for action, enabled in ((start, not running), (stop, running),
                                (test, True)):
            if action is not None and not _is_deleted(action):
                action.setEnabled(enabled)

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
        self._sync_problip_tray_menu()
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
        for attr in ("_tray_aot_action", "_tray_focus_action",
                     "_tray_icon_action", "_tray_stop_all_action",
                     "_tray_problip_menu", "_tray_problip_start",
                     "_tray_problip_stop", "_tray_problip_test",
                     "_tray_problip_settings"):
            action = getattr(self, attr, None)
            if (action is None or _is_deleted(action)
                    or not getattr(action, "_en_text", None)):
                continue
            text = tr(action._en_text, lang)
            # A submenu is a QMenu (setTitle); everything else is a QAction.
            if hasattr(action, "setTitle"):
                action.setTitle(text)
            else:
                action.setText(text)
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
