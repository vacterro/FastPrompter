"""Tray mixin for FastPrompter — system tray icon and context menu.

Extracted from main.py Phase 2a of the modularization plan.
Provides TrayMixin class for use as a mixin with FastPrompter QMainWindow.
"""

import os

from PyQt6 import sip
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QMenu, QSystemTrayIcon

from fastprompter.core.translations import tr
from fastprompter.core.config import create_tray_icon
from fastprompter.utils.paths import get_resource_path

_is_deleted = sip.isdeleted


class TrayMixin:
    """Mixin providing system tray icon and context menu functionality.

    Type hints assume these attributes are provided by the FastPrompter
    QMainWindow instance at runtime:
        self._tray_visible, self.tray_icon
    """

    def init_tray(self):
        """Initialize the system tray icon and context menu."""
        tray_color = self._theme_val("tray_color", "#8b4513")
        icon = create_tray_icon(tray_color)

        self.tray_icon = QSystemTrayIcon(icon, self)
        tray_menu = QMenu(self)

        lang = getattr(self, "_current_lang", "EN")
        show_action = tray_menu.addAction(tr("Show/Hide", lang))
        show_action.triggered.connect(self.toggle_visibility)
        tray_menu.addSeparator()
        quit_action = tray_menu.addAction(tr("Quit", lang))
        quit_action.triggered.connect(self.quit_app)

        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.activated.connect(self.on_tray_activated)
        self.tray_icon.setVisible(self._tray_visible)

        # Set window icon too
        icon_path = get_resource_path("_res", "fastprompter_logo2.png")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))
        else:
            self.setWindowIcon(icon)

    def on_tray_activated(self, reason):
        """Handle double-click on tray icon."""
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.toggle_visibility()

    def on_tray_toggled(self, checked):
        """Toggle tray icon visibility."""
        tray_icon = getattr(self, "tray_icon", None)
        if tray_icon is not None:
            tray_icon.setVisible(checked)
        self.data["tray_visible"] = str(checked)
        self.mark_dirty()
