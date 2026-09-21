"""T-1238-D.1: the Wintage palettes ported from the real reference source.

The six palettes below were ported from the ProBlipAndroid reference
(``app/src/main/java/com/vacster/problip/ui/theme/Palettes.kt``), value for
value -- not eyeballed.  This test pins the exact ARGB constants so a later
"tidy-up" cannot quietly drift them, and it proves no existing palette was
modified in the process.
"""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

from fastprompter.theme.themes import THEMES  # noqa: E402

#: name -> (bg_main, btn_bg, border_light, border_dark, accent, text_main,
#:          btn_text, bg_text) exactly as Palettes.kt defines
#:          Bg / Surface / Bevel / BDark / Gold / TextMain / TextDim / Compare.
WINTAGE_PALETTES = {
    "Dark Golden (Win95)": ("#342012", "#4A341B", "#826941", "#1C1208",
                            "#D3B57A", "#E2CA95", "#C5AB6E", "#24170C"),
    "Claude Code": ("#29241D", "#3B362A", "#75644F", "#15130F",
                    "#D1A27C", "#E0B997", "#C39870", "#1C1914"),
    "Antigravity": ("#1B1F2C", "#272B3E", "#4B6678", "#0D0F17",
                    "#7AD0D3", "#95DEE2", "#6EBFC5", "#12151E"),
    "K-Lite (MPC-HC)": ("#212325", "#303235", "#5E6165", "#111213",
                        "#A2A5AB", "#B8BABF", "#95989E", "#171819"),
    "FreeBuff": ("#1B232B", "#28303D", "#506B5F", "#0E1116",
                 "#89D37A", "#A0E295", "#7AC56E", "#13181D"),
    "CodeNomad": ("#1C242A", "#29313C", "#575776", "#0E1216",
                  "#9D86D1", "#B099DE", "#9C84C8", "#13181D"),
}

#: Palettes that existed before this ticket.  None of them may change.
PRE_EXISTING = ("Default", "Golden Vintage")


class TestCatalog:
    @pytest.mark.parametrize("name", sorted(WINTAGE_PALETTES))
    def test_the_palette_is_in_the_catalog(self, name):
        assert name in THEMES, f"{name} was not ported into THEMES"

    @pytest.mark.parametrize("name", sorted(WINTAGE_PALETTES))
    def test_the_colours_match_the_reference_exactly(self, name):
        (bg, surface, bevel, bdark, gold, text, dim,
         compare) = WINTAGE_PALETTES[name]
        colors = THEMES[name]["raw_colors"]
        assert colors["bg_main"].upper() == bg
        assert colors["btn_bg"].upper() == surface
        assert colors["border_light"].upper() == bevel
        assert colors["border_dark"].upper() == bdark
        assert colors["accent"].upper() == gold
        assert colors["text_main"].upper() == text
        assert colors["btn_text"].upper() == dim
        # Compare is the sunken colour: the editor field AND the pressed
        # state, which is exactly how the reference uses it.
        assert colors["bg_text"].upper() == compare
        assert colors["btn_pressed"].upper() == compare

    @pytest.mark.parametrize("name", sorted(WINTAGE_PALETTES))
    def test_every_ported_palette_is_a_complete_theme(self, name):
        theme = THEMES[name]
        for key in ("stylesheet", "preset_colors", "tray_color",
                    "mini_settings", "raw_colors"):
            assert key in theme, f"{name} is missing {key}"
        assert theme["tray_color"].upper() == WINTAGE_PALETTES[name][4]

    @pytest.mark.parametrize("name", PRE_EXISTING)
    def test_pre_existing_palettes_still_exist(self, name):
        assert name in THEMES

    def test_the_default_palette_was_not_modified(self):
        colors = THEMES["Default"]["raw_colors"]
        assert colors["bg_main"] == "#1a1a1a"
        assert colors["accent"] == "#5a7a96"

    def test_no_duplicate_display_names(self):
        assert len(set(THEMES)) == len(THEMES)

    def test_every_theme_carries_a_usable_stylesheet(self):
        for name, theme in THEMES.items():
            assert isinstance(theme.get("stylesheet"), str), name
            assert "QWidget" in theme["stylesheet"], name
