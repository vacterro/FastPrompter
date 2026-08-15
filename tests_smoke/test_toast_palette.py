"""Notification toast palette reads the theme's notif_* tokens.

Regression guard for the notification colour customization: the toast must
resolve its palette from the dedicated notification tokens every theme now
carries, and still degrade cleanly against a theme cache that predates them.
"""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from fastprompter.theme.themes import THEMES
from fastprompter.ui.timer_toast import _get_toast_palette


def _win_with(raw_colors):
    cache = {"raw_colors": raw_colors}
    return type("W", (), {"_theme_cache": cache})()


def test_palette_reads_notification_tokens():
    p = _get_toast_palette(_win_with(THEMES["Golden Vintage"]["raw_colors"]))
    assert p["bg"] == "#1a1a1a"
    assert p["header"] == "#2b2b2b"
    assert p["title"] == "#d6be76"
    assert p["text"] == "#c4ba9f"
    assert p["accent"] == "#d6be76"
    assert p["border"] == "#4a4a4a"


def test_palette_falls_back_to_generic_tokens():
    raw = {
        "bg_main": "#111111", "btn_bg": "#222222", "accent": "#333333",
        "text_main": "#444444", "border_light": "#555555", "border_dark": "#060606",
    }
    p = _get_toast_palette(_win_with(raw))
    assert p["bg"] == "#111111"
    assert p["header"] == "#222222"
    assert p["title"] == "#333333"
    assert p["text"] == "#444444"
    assert p["accent"] == "#333333"
    assert p["border"] == "#555555"


def test_palette_reports_no_main_win():
    p = _get_toast_palette(None)
    assert p["bg"] == "#1A0F05"
    assert p["accent"] == "#D9B340"
