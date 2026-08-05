from fastprompter.core.translations import tr

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
from PyQt6.QtWidgets import QApplication, QFileDialog, QMessageBox, QPushButton, QWidget

from fastprompter.core.config import create_tray_icon, extract_bg
from fastprompter.core.logging import logger
from fastprompter.theme.themes import (
    THEMES,
    generate_custom_theme,
    header_view_qss,
    scrollbar_qss,
)
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

        # Suppress the native dotted focus-rect Qt draws on buttons after a
        # click — every theme is a solid chrome-less skin, so that rectangle
        # just looks like a rendering glitch, not a focus indicator.
        no_focus_rect_qss = (
            "\nQPushButton:focus, QToolButton:focus, QCheckBox:focus { outline: none; }\n"
            # Square icon buttons keep the theme's bevel but drop its text
            # padding: a themed 2px border + 3px/6px padding leaves a 4x10
            # content rect inside a 20x20 button, and a 15px emoji is then
            # painted as a narrow vertical slice. This is what "the icons are
            # cropped" was. Property selector, so it beats the plain
            # QPushButton rule in every theme without editing all of them.
            "QPushButton[fp_icon_button=\"true\"] { padding: 0px; }\n"
        )
        raw = theme.get("raw_colors") or {}
        extra_qss = no_focus_rect_qss
        # Thin ghost-until-hovered scrollbars (toggleable). Rebuilt on every
        # apply_theme, so turning it off cleanly restores the OS default.
        if self.data.get("thin_scrollbars", "True") == "True":
            extra_qss += scrollbar_qss(raw)
        # Not behind a setting: an unstyled header is a white bar across a
        # dark dialog, which is a defect rather than a preference.
        extra_qss += header_view_qss(raw)
        QApplication.instance().setStyleSheet(theme["stylesheet"] + extra_qss)

        # Header/toolbar bar gets its own per-theme tint instead of blending
        # flat into the window. NOTE: a plain QWidget needs
        # WA_StyledBackground (set in main.py) or this is a silent no-op.
        header = getattr(self, "header_widget", None)
        if header is not None and not _is_deleted(header):
            from fastprompter.theme.themes import header_tint
            header_bg = header_tint(raw)
            header.setStyleSheet(f"#HeaderBar {{ background-color: {header_bg}; }}")

        # The clock repaints itself only once a minute off its own timer —
        # without this nudge a theme switch left it showing stale colors for
        # up to 59 seconds ("themes don't refresh instantly").
        clock = getattr(self, "analog_clock", None)
        if clock is not None and not _is_deleted(clock):
            clock.update()
        # Re-pack the dense header AFTER the new stylesheet has re-polished
        # fonts — packing with pre-theme metrics truncates button labels
        if hasattr(self, "_apply_header_density"):
            from PyQt6.QtCore import QTimer
            self._header_dense = None  # force a full re-pack
            QTimer.singleShot(0, self._apply_header_density)
        # through scale_button_qss: the fixed px font/padding in these
        # strings is what crushed the labels at small UI scales
        self.btn_new.setStyleSheet(self.scale_button_qss(theme["btn_new"]))
        self.btn_save.setStyleSheet(self.scale_button_qss(theme["btn_save"]))
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

        # Re-apply the font LAST. Setting an application stylesheet makes Qt
        # re-polish every widget, and a widget whose font was set explicitly
        # comes back on the class default - measured: with "Courier New"
        # chosen, the editor and its document both read "Verdana" again the
        # moment a theme was applied, while data and the app font still said
        # Courier New. That is the "theme change loses my font" report.
        try:
            self.apply_font()
        except Exception:
            logger.debug("apply_theme: could not re-apply the font")

        # The padding override is keyed on a dynamic property, which an
        # already-polished widget does not re-evaluate by itself.
        try:
            self.repolish_icon_buttons()
        except Exception:
            logger.debug("apply_theme: icon-button repolish failed", exc_info=True)

        self._begin_batch_update()
        try:
            self.refresh_snippets_panel()
            self.refresh_temp_presets()
        finally:
            self._end_batch_update()

        try:
            self._apply_kanban_theme(theme)
            self._apply_table_theme(theme)
        except Exception:
            logger.debug("apply_theme: visual widget theme pass failed", exc_info=True)

        # LAST. Every theme hands buttons a different content rect, and the
        # panels above rebuild their own buttons with their own fixed sizes,
        # so a fit pass run any earlier is simply overwritten by them.
        try:
            self.enforce_button_fit()
        except Exception:
            logger.debug("apply_theme: button fit pass failed", exc_info=True)

    def repolish_icon_buttons(self):
        """Make the fp_icon_button padding rule land on existing buttons.

        A dynamic property set after a widget was polished does not
        re-evaluate the stylesheet on its own, so without this the padding
        override only applied to buttons created after the theme.
        """
        style = QApplication.style()
        if style is None:
            return
        for btn in self.findChildren(QPushButton):
            if _is_deleted(btn) or not btn.property("fp_icon_button"):
                continue
            style.unpolish(btn)
            style.polish(btn)

    def apply_font(self):
        """Apply the configured font to the UI. Defaults to Verdana."""
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
        # QApplication.setFont alone does not reach a widget whose look is
        # driven by its own stylesheet: those keep resolving their family
        # from the app font as it was when the style last ran. Measured with
        # "Courier New" picked - the toolbar buttons stayed Verdana until a
        # theme change happened to re-polish them. Re-polishing here is what
        # makes the font switch land everywhere at once.
        style = QApplication.style()
        if style is not None:
            for widget in self.findChildren(QWidget):
                if widget.styleSheet():
                    style.unpolish(widget)
                    style.polish(widget)

        try:
            self.text_area.setFont(font)
            self.text_area.document().setDefaultFont(font)
            self.highlighter.update_base_size(font_size)
            # code spans follow the editor font when monospace is off
            if hasattr(self, "_apply_code_font"):
                self._apply_code_font()
            # text alignment follows the saved setting
            if hasattr(self, "_apply_text_alignment"):
                self._apply_text_alignment()
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
            QMessageBox.warning(self, tr("Load Font", getattr(self, "_current_lang", "EN")), tr("Failed to load font: {}", getattr(self, "_current_lang", "EN")).format(path))
            return

        families = QFontDatabase.applicationFontFamilies(font_id)
        if not families:
            QMessageBox.warning(self, tr("Load Font", getattr(self, "_current_lang", "EN")), tr("Font loaded but no font families found.", getattr(self, "_current_lang", "EN")))
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
        QMessageBox.information(self, tr("Font Loaded", getattr(self, "_current_lang", "EN")), tr("Loaded: {}", getattr(self, "_current_lang", "EN")).format(families[0]))

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
        # Read the English mode key from itemData — currentText() is localized
        # and would never match the English "Source View"/"Reading" checks.
        mode = self.preview_combo.currentData() or self.preview_combo.currentText()
        # the Vision button is a second face of this combo, so its tooltip
        # has to follow the mode however the mode was changed
        if hasattr(self, "_refresh_vision_button"):
            self._refresh_vision_button()

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
            # re-arm Hide Markup for this document: conceal has to know the
            # caret's block, and a fresh setDocument() drops the old one
            if hasattr(self, "_apply_conceal_mode"):
                self._apply_conceal_mode()
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
        mode = self.preview_combo.currentData() or self.preview_combo.currentText()

        if mode == "Reading":
            self.preview_area.setHtml(self.simple_markdown_to_html(text))

    # ---- SiloTable / SiloKanban skin ------------------------------------
    #
    # House rules (saipen UI.md), and they are rules, not taste:
    #   * depth is a 2px BEVEL and nothing else — no radius, no shadow, no
    #     gradient, no transition;
    #   * every colour traces back to a token — here the active theme's
    #     raw_colors, so the board follows Vintage Classic and OLED alike
    #     instead of carrying its own hardcoded greys;
    #   * compact by default, and states must be instant.

    def _skin_tokens(self):
        """The theme's palette, with sane fallbacks. One place, both widgets."""
        raw = (self._theme_cache or {}).get("raw_colors") or {}
        return {
            "bg": raw.get("bg_main", "#232018"),
            "sunken": raw.get("bg_text", "#1a1810"),
            "raised": raw.get("btn_bg", "#332e22"),
            "pressed": raw.get("btn_pressed", "#232018"),
            "light": raw.get("border_light", "#5a5040"),
            "dark": raw.get("border_dark", "#100e08"),
            "text": raw.get("text_main", "#d4c89a"),
            "btn_text": raw.get("btn_text", "#c9a84c"),
            "accent": raw.get("accent", "#c9a84c"),
        }

    @staticmethod
    def _bevel(t, raised=True):
        """A 2px Win95 bevel. Raised = lit from the top-left, sunken = inverse."""
        a, b = (t["light"], t["dark"]) if raised else (t["dark"], t["light"])
        return (f"border: 2px solid; border-top-color: {a}; "
                f"border-left-color: {a}; border-right-color: {b}; "
                f"border-bottom-color: {b};")

    def _apply_kanban_theme(self, theme):
        if not hasattr(self, "kanban_widget"):
            return
        from fastprompter.theme.themes import blend_hex
        t = self._skin_tokens()
        # a done card's text steps back rather than disappearing: still
        # readable, visibly finished
        muted = blend_hex(t["text"], t["bg"], 0.45)
        self.kanban_widget.setStyleSheet(
            f"QScrollArea {{ background-color: {t['bg']}; border: none; }}"
            f"QWidget {{ background-color: {t['bg']}; color: {t['text']}; }}"
            # column: a sunken well, so the cards read as sitting IN it
            f"QFrame#kanban_column {{ background-color: {t['sunken']}; "
            f"  {self._bevel(t, raised=False)} margin: 0px; }}"
            f"QLabel#kanban_column_name {{ background: transparent; "
            f"  color: {t['btn_text']}; font-weight: bold; padding: 1px 2px; }}"
            f"QLabel#kanban_column_count {{ background: transparent; "
            f"  color: {muted}; padding: 1px 2px; }}"
            # card: a raised tile
            f"QFrame#kanban_card {{ background-color: {t['raised']}; "
            f"  {self._bevel(t)} }}"
            f"QFrame#kanban_card:hover {{ background-color: {t['pressed']}; }}"
            f"QFrame#kanban_card QLabel {{ background: transparent; "
            f"  color: {t['text']}; }}"
            f"QFrame#kanban_card[done=\"true\"] QLabel {{ color: {muted}; }}"
            f"QFrame#kanban_card QLineEdit {{ background-color: {t['sunken']}; "
            f"  color: {t['text']}; {self._bevel(t, raised=False)} padding: 1px; }}"
            # the add controls are BUTTONS, not decorated labels
            f"QLabel#kanban_add {{ background-color: {t['raised']}; "
            f"  color: {t['btn_text']}; {self._bevel(t)} padding: 1px 6px; }}"
            f"QLabel#kanban_add:hover {{ background-color: {t['pressed']}; }}"
        )

    def _apply_table_theme(self, theme):
        if not hasattr(self, "table_widget"):
            return
        t = self._skin_tokens()
        self.table_widget.setStyleSheet(
            f"QWidget {{ background-color: {t['bg']}; color: {t['text']}; }}"
            # every cell is a sunken field: that is what a text input looks
            # like in this house, and a table is a grid of them
            f"QLineEdit {{ background-color: {t['sunken']}; color: {t['text']}; "
            f"  {self._bevel(t, raised=False)} padding: 1px 3px; }}"
            # focus is instant and unmistakable — no animation budget here
            f"QLineEdit:focus {{ background-color: {t['pressed']}; "
            f"  border-color: {t['accent']}; }}"
            f"QLineEdit[header=\"true\"] {{ background-color: {t['raised']}; "
            f"  color: {t['btn_text']}; font-weight: bold; "
            f"  {self._bevel(t)} }}"
            f"QLabel#table_add {{ background-color: {t['raised']}; "
            f"  color: {t['btn_text']}; {self._bevel(t)} padding: 1px 6px; }}"
            f"QLabel#table_add:hover {{ background-color: {t['pressed']}; }}"
        )
