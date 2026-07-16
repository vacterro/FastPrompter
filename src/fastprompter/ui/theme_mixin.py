"""Theme mixin for FastPrompter — theme switching, font management, and preview modes.

Extracted from main.py Phase 3 of the modularization plan.
Provides ThemeMixin class for use as a mixin with FastPrompter QMainWindow.
"""

import ast
import json
import os

from PyQt6 import sip
from PyQt6.QtCore import QTimer
from PyQt6.QtGui import QFont, QFontDatabase, QIcon
from PyQt6.QtWidgets import QApplication, QFileDialog, QMessageBox

from fastprompter.core.config import create_tray_icon, extract_bg
from fastprompter.core.logging import logger
from fastprompter.theme.themes import THEMES, generate_custom_theme
from fastprompter.utils.paths import get_resource_path

_is_deleted = sip.isdeleted


class ThemeMixin:
    """Mixin providing theme switching, font management, and preview modes.

    Type hints assume these attributes are provided by the FastPrompter
    QMainWindow instance at runtime:
        self.data, self._theme_cache, self._theme_cache_name,
        self.text_area, self.preview_area, self.highlighter,
        self.font_combo, self.preview_combo,
        self.btn_new, self.btn_save, self.btn_help, self.mini_settings_frame,
        self.tray_icon
    """

    def _get_custom_colors(self):
        """Parse custom_colors from data, handling string-serialized dicts. Cached via _custom_colors_cache."""
        raw = self.data.get("custom_colors", {})
        cache_key = str(raw)
        if cache_key != getattr(self, "_custom_colors_cache_key", None):
            if isinstance(raw, str):
                try:
                    parsed = ast.literal_eval(raw)
                except Exception:
                    parsed = {}
            else:
                parsed = raw
            self._custom_colors_cache = parsed if isinstance(parsed, dict) else {}
            self._custom_colors_cache_key = cache_key
        return self._custom_colors_cache

    def _refresh_theme_cache(self) -> None:
        """Cache the active theme dict for fast lookups."""
        name = self.data.get("theme", "Default")
        if name != self._theme_cache_name:
            self._theme_cache_name = name
            self._theme_cache = THEMES.get(name, THEMES["Default"])

    def _theme_val(self, key: str, fallback: str = "") -> str:
        """Fast single-value lookup from cached theme dict."""
        return self._theme_cache.get(key, fallback)

    def change_font_family(self, font_name):
        """Change the application font family."""
        if getattr(self, "_initializing_ui", False):
            return
        self.data["font_family"] = font_name
        self.apply_font()
        self.mark_dirty()

    def change_font_size(self, size):
        """Change the application font size."""
        if getattr(self, "_initializing_ui", False):
            return
        self.data["font_size"] = size
        self.apply_font()
        self.mark_dirty()

    def change_theme(self, theme_name):
        """Switch to a different theme."""
        self.add_data_undo_state("Change theme")
        self.data["theme"] = theme_name
        self.mark_dirty()
        self._refresh_theme_cache()
        self.apply_theme()

    def apply_theme(self):
        """Apply the active theme stylesheet to all themed widgets."""
        self._refresh_theme_cache()
        theme_name = self.data.get("theme", "Default")
        if theme_name == "Custom":
            c = self._get_custom_colors()
            if "bg_main" not in c:
                theme_name = "Default"
                theme = THEMES["Default"]
            else:
                theme = generate_custom_theme(c)
            # Update cache so _theme_val() and other consumers get the correct
            # custom theme instead of the Default fallback from _refresh_theme_cache().
            self._theme_cache = theme
        else:
            if theme_name not in THEMES:
                theme_name = "Default"
            self._refresh_theme_cache()
            theme = self._theme_cache

        QApplication.instance().setStyleSheet(theme["stylesheet"])
        self.btn_new.setStyleSheet(theme["btn_new"])
        self.btn_save.setStyleSheet(theme["btn_save"])
        self.btn_help.setStyleSheet(theme["lbl_help"])
        self.mini_settings_frame.setStyleSheet(theme["mini_settings"])

        snip_label = getattr(self, "snip_label", None)
        if snip_label is not None and not _is_deleted(snip_label):
            snip_label.setStyleSheet(theme["lbl_title"])
        if hasattr(self, "silo_label") and not _is_deleted(self.silo_label):
            self.silo_label.setStyleSheet(theme["lbl_title"])
        if hasattr(self, "archive_section") and not _is_deleted(self.archive_section):
            bg = extract_bg(theme.get("mini_settings", "")) or "#1a1a1a"
            self.archive_section.setStyleSheet(f"#ArchiveSection {{ background-color: {bg}; }}")

        if hasattr(self, "tray_icon") and not _is_deleted(self.tray_icon):
            icon_path = get_resource_path("_res", "fastprompter_logo2.png")
            if os.path.exists(icon_path):
                icon = QIcon(icon_path)
            else:
                icon = create_tray_icon(theme["tray_color"])
            self.tray_icon.setIcon(icon)
            self.setWindowIcon(icon)

        try:
            highlighter = getattr(self, "highlighter", None)
            if highlighter is not None and not _is_deleted(highlighter):
                highlighter.update_theme(theme)
        except RuntimeError:
            pass

        self._begin_batch_update()
        try:
            self.refresh_snippets_panel()
            self.refresh_temp_presets()
        finally:
            self._end_batch_update()

    def apply_font(self):
        """Apply the configured font to the UI."""
        if getattr(self, "_initializing_ui", False):
            return
        try:
            base_size = self._font_size
        except Exception:
            base_size = 11
        font_name = self._font_family
        try:
            scale = self._ui_scale
        except Exception:
            scale = 1.0
        font_size = max(8, int(round(base_size * scale)))
        font_key: tuple = (font_name, font_size)
        if font_key != getattr(self, "_font_cache_key", None):
            self._font_cache_key = font_key
            self._cached_main_font = QFont(font_name, font_size)
            self._cached_main_font.setStyleStrategy(
                QFont.StyleStrategy.NoAntialias | QFont.StyleStrategy.NoSubpixelAntialias
            )
        font = self._cached_main_font
        QApplication.setFont(font)

        try:
            self.text_area.setFont(font)
            self.text_area.document().setDefaultFont(font)
            self.highlighter.update_base_size(font_size)
        except Exception:
            logger.debug("apply_font: failed to set font on text_area")
        try:
            self.preview_area.setFont(font)
        except Exception:
            logger.debug("apply_font: failed to set font on preview_area")
        self._begin_batch_update()
        try:
            self.refresh_snippets_panel()
        finally:
            self._end_batch_update()

    def load_custom_font(self):
        """Load a custom TTF/OTF font file and add it to the font combobox."""
        # json is already imported at module level
        self.ignore_focus_loss = True
        try:
            path, _ = QFileDialog.getOpenFileName(
                self, "Load Font File", "", "Font Files (*.ttf *.otf *.TTF *.OTF);;All Files (*.*)"
            )
        finally:
            self.ignore_focus_loss = False
        self.activateWindow()
        if not path:
            return

        font_id = QFontDatabase.addApplicationFont(path)
        if font_id < 0:
            QMessageBox.warning(self, "Load Font", f"Failed to load font: {path}")
            return

        families = QFontDatabase.applicationFontFamilies(font_id)
        if not families:
            QMessageBox.warning(self, "Load Font", "Font loaded but no font families found.")
            return

        loaded = self.data.get("custom_font_ids", [])
        if isinstance(loaded, str):
            try:
                loaded = json.loads(loaded)
            except Exception:
                loaded = []
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
                self,
                "Clear Custom Fonts",
                "Remove all custom fonts from the font selector?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
        finally:
            self.ignore_focus_loss = False
        self.activateWindow()
        if reply != QMessageBox.StandardButton.Yes:
            return

        default_fonts = [
            "Verdana",
            "Tahoma",
            "Consolas",
            "Calibri",
            "Times New Roman",
            "Arial",
            "Segoe UI",
            "Courier New",
        ]
        self.font_combo.blockSignals(True)
        self.font_combo.clear()
        self.font_combo.addItems(default_fonts)
        self.font_combo.blockSignals(False)

        if self._font_family not in default_fonts:
            self.font_combo.setCurrentText("Verdana")
            self.change_font_family("Verdana")
        else:
            self.font_combo.setCurrentText(self._font_family)

        self.data["custom_font_ids"] = []
        self.mark_dirty()

    def change_preview_mode(self, index):
        """Switch between Source View, Live Preview, and Reading modes."""
        mode = self.preview_combo.currentText()

        if self._preview_connected and hasattr(self, "_preview_timer"):
            try:
                self.text_area.textChanged.disconnect(self._preview_timer.start)
            except Exception:
                logger.debug(
                    "change_preview_mode: textChanged disconnect failed (may not have been connected)"
                )
            try:
                self._preview_timer.stop()
                self._preview_timer.timeout.disconnect(self.update_preview)
            except Exception:
                logger.debug(
                    "change_preview_mode: timeout disconnect failed (may not have been connected)"
                )
            self._preview_connected = False

        if mode == "Source View":
            self.text_area.setVisible(True)
            self.text_area.setReadOnly(False)
            self.preview_area.setVisible(False)
            self.highlighter.setDocument(None)

        elif mode == "Live Preview":
            self.text_area.setVisible(True)
            self.text_area.setReadOnly(False)
            self.preview_area.setVisible(False)
            large = self.text_area.document().blockCount() > 500
            self.highlighter.set_skip_large(large)
            self.highlighter.setDocument(self.text_area.document())
            if not large:
                self.highlighter.rehighlight()

        elif mode == "Reading":
            self.text_area.setVisible(False)
            self.preview_area.setVisible(True)
            if not self._preview_connected:
                if not hasattr(self, "_preview_timer"):
                    self._preview_timer = QTimer(self)
                    self._preview_timer.setSingleShot(True)
                    self._preview_timer.setInterval(500)
                    self._preview_timer.timeout.connect(self.update_preview)
                self.text_area.textChanged.connect(self._preview_timer.start)
                self._preview_connected = True
            self.update_preview()

        self.mark_dirty()

    def update_preview(self):
        """Update the preview area when in Reading mode."""
        text = self.text_area.toPlainText()
        mode = self.preview_combo.currentText()

        if mode == "Reading":
            self.preview_area.setHtml(self.simple_markdown_to_html(text))


