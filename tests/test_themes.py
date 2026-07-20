"""Tests for fastprompter.theme.themes — generate_custom_theme, THEMES dict."""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

from fastprompter.theme.themes import (
    THEMES,
    generate_custom_theme,
)

# ---------------------------------------------------------------------------
# generate_custom_theme
# ---------------------------------------------------------------------------


class TestGenerateCustomTheme:
    def test_returns_dict_with_required_keys(self):
        """A full theme should have all expected keys."""
        theme = generate_custom_theme({})
        assert "stylesheet" in theme
        assert "preset_colors" in theme
        assert "active_temp_color" in theme
        assert "inactive_temp_color" in theme
        assert "tray_color" in theme
        assert "btn_new" in theme
        assert "btn_save" in theme
        assert "lbl_help" in theme
        assert "lbl_title" in theme
        assert "mini_settings" in theme
        assert "raw_colors" in theme

    def test_default_values_when_empty_dict(self):
        """An empty dict should produce a theme with all default color values."""
        theme = generate_custom_theme({})
        assert theme["raw_colors"]["bg_main"] == "#1a1a1a"
        assert theme["raw_colors"]["text_main"] == "#c0c0c0"
        assert theme["raw_colors"]["accent"] == "#bfa65e"

    def test_override_single_color(self):
        """Overriding a single color should be reflected in the output."""
        theme = generate_custom_theme({"bg_main": "#ff0000"})
        assert theme["raw_colors"]["bg_main"] == "#ff0000"
        # Other defaults should remain
        assert theme["raw_colors"]["text_main"] == "#c0c0c0"

    def test_override_multiple_colors(self):
        """Multiple color overrides should all be applied."""
        theme = generate_custom_theme({"bg_main": "#111", "bg_text": "#222", "accent": "#333"})
        assert theme["raw_colors"]["bg_main"] == "#111"
        assert theme["raw_colors"]["bg_text"] == "#222"
        assert theme["raw_colors"]["accent"] == "#333"

    def test_preset_colors_has_10_entries(self):
        """preset_colors should have exactly 10 entries (one per silo)."""
        theme = generate_custom_theme({})
        assert len(theme["preset_colors"]) == 10

    def test_preset_colors_match_bg(self):
        """preset_colors entries should match the bg_main color."""
        theme = generate_custom_theme({"bg_main": "#abc123"})
        for color in theme["preset_colors"]:
            assert color == "#abc123"

    def test_active_temp_color_matches_btn_bg(self):
        """active_temp_color should match the btn_bg color."""
        theme = generate_custom_theme({"btn_bg": "#445566"})
        assert theme["active_temp_color"] == "#445566"

    def test_inactive_temp_color_matches_bg_main(self):
        """inactive_temp_color should match the bg_main color."""
        theme = generate_custom_theme({"bg_main": "#1b2b3b"})
        assert theme["inactive_temp_color"] == "#1b2b3b"

    def test_tray_color_matches_accent(self):
        """tray_color should match the accent color."""
        theme = generate_custom_theme({"accent": "#aabbcc"})
        assert theme["tray_color"] == "#aabbcc"

    def test_btn_new_contains_bg_color(self):
        """btn_new stylesheet should reference the btn_bg color."""
        theme = generate_custom_theme({"btn_bg": "#334455"})
        assert "#334455" in theme["btn_new"]

    def test_stylesheet_contains_widget_selectors(self):
        """The generated stylesheet should contain common Qt widget selectors."""
        theme = generate_custom_theme({})
        ss = theme["stylesheet"]
        assert "QWidget" in ss
        assert "QPushButton" in ss
        assert "QTextEdit" in ss
        assert "QTabBar" in ss
        assert "QMenu" in ss
        assert "QCheckBox" in ss

    def test_stylesheet_reflects_colors(self):
        """The stylesheet should contain the configured color values."""
        theme = generate_custom_theme({"text_main": "#ffee00", "bg_main": "#001122"})
        ss = theme["stylesheet"]
        assert "#ffee00" in ss
        assert "#001122" in ss

    def test_raw_colors_has_all_expected_keys(self):
        """raw_colors should have all 9 default color keys."""
        theme = generate_custom_theme({})
        expected_keys = {
            "bg_main",
            "bg_text",
            "text_main",
            "border_light",
            "border_dark",
            "btn_bg",
            "btn_text",
            "btn_pressed",
            "accent",
        }
        assert set(theme["raw_colors"].keys()) == expected_keys

    def test_custom_theme_type(self):
        """The result should be coercible to dict (structural check)."""
        theme = generate_custom_theme({"bg_main": "#000"})
        assert isinstance(theme["stylesheet"], str)
        assert isinstance(theme["preset_colors"], list)
        assert isinstance(theme["raw_colors"], dict)


# ---------------------------------------------------------------------------
# THEMES dict
# ---------------------------------------------------------------------------


class TestThemesDict:
    def test_has_all_expected_themes(self):
        """THEMES should contain all 6 built-in themes."""
        expected = {
            "Default",
            "Golden Vintage",
            "Golden Default",
            "Vintage Dark",
            "Vintage Classic",
            "Dark 2 (OLED)",
        }
        assert set(THEMES.keys()) == expected

    def test_each_theme_has_stylesheet(self):
        """Every theme should have a non-empty stylesheet string."""
        for name, theme in THEMES.items():
            assert "stylesheet" in theme, f"Theme '{name}' missing stylesheet"
            assert len(theme["stylesheet"]) > 100, f"Theme '{name}' stylesheet too short"

    def test_each_theme_has_preset_colors(self):
        """Every theme should have preset_colors list."""
        for name, theme in THEMES.items():
            assert "preset_colors" in theme, f"Theme '{name}' missing preset_colors"
            assert isinstance(theme["preset_colors"], list)
            assert len(theme["preset_colors"]) > 0

    def test_each_theme_has_active_temp_color(self):
        """Every theme should have active_temp_color."""
        for name, theme in THEMES.items():
            assert "active_temp_color" in theme
            assert theme["active_temp_color"].startswith("#")

    def test_each_theme_has_tray_color(self):
        """Every theme should have a tray_color."""
        for name, theme in THEMES.items():
            assert "tray_color" in theme
            assert theme["tray_color"].startswith("#")

    def test_each_theme_has_raw_colors(self):
        """Every theme should have raw_colors dict."""
        for name, theme in THEMES.items():
            assert "raw_colors" in theme
            assert "bg_main" in theme["raw_colors"]

    def test_default_theme_accent(self):
        """The Default theme should have the expected accent color."""
        assert THEMES["Default"]["raw_colors"]["accent"] == "#5a7a96"

    def test_vintage_dark_uses_beveled_borders(self):
        """Vintage Dark stylesheet should contain border-top-color patterns."""
        ss = THEMES["Vintage Dark"]["stylesheet"]
        assert "border-top-color" in ss

    def test_vintage_classic_is_light(self):
        """Vintage Classic should have a light background (Windows 95 style)."""
        assert THEMES["Vintage Classic"]["raw_colors"]["bg_main"] == "#c0c0c0"
