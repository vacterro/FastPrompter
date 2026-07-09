"""Tests for fastprompter.core.config — extract_bg, extract_color."""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

from fastprompter.core.config import extract_bg, extract_color


class TestExtractBg:
    def test_extract_bg_simple(self):
        """Extract background-color from a simple stylesheet string."""
        style = "background-color: #1a1a1a; color: white;"
        assert extract_bg(style) == "#1a1a1a"

    def test_extract_bg_no_match(self):
        """Return None when no background-color is present."""
        assert extract_bg("color: red; font-weight: bold;") is None

    def test_extract_bg_empty_string(self):
        """Return None for empty string."""
        assert extract_bg("") is None

    def test_extract_bg_multiline(self):
        """Extract from multi-line stylesheet."""
        style = """
        QWidget {
            background-color: #2b2b2b;
            color: #c0c0c0;
        }
        """
        assert extract_bg(style) == "#2b2b2b"

    def test_extract_bg_short_hex(self):
        """Handle short 3-digit hex colors."""
        style = "background-color: #fff;"
        assert extract_bg(style) == "#fff"

    def test_extract_bg_uppercase(self):
        """Handle uppercase hex values."""
        style = "background-color: #ABCDEF;"
        assert extract_bg(style) == "#ABCDEF"

    def test_extract_bg_rgba_no_match(self):
        """rgba() values should not match the hex pattern."""
        style = "background-color: rgba(0,0,0,0.5);"
        assert extract_bg(style) is None


class TestExtractColor:
    def test_extract_color_simple(self):
        """Extract color from a simple stylesheet string."""
        style = "color: #c0c0c0; font-size: 11px;"
        assert extract_color(style) == "#c0c0c0"

    def test_extract_color_no_match(self):
        """Return None when no color is present."""
        assert extract_color("background-color: #000; font-weight: bold;") is None

    def test_extract_color_empty_string(self):
        """Return None for empty string."""
        assert extract_color("") is None

    def test_extract_color_multiline(self):
        """Extract from multi-line stylesheet with separate color property."""
        style = """
        QPushButton {
            background-color: #333;
            color: #bfa65e;
        }
        """
        assert extract_color(style) == "#bfa65e"

    def test_extract_color_after_background(self):
        """Extract color when background-color appears first on same line."""
        style = "background-color: #000; color: #fff;"
        assert extract_color(style) == "#fff"

    def test_extract_color_before_background(self):
        """Extract color when color appears before background-color."""
        style = "color: #d0d0d0; background-color: #2b2b2b;"
        assert extract_color(style) == "#d0d0d0"

    def test_extract_color_named_no_match(self):
        """Named colors (e.g. 'white') should not match the hex pattern."""
        style = "color: white;"
        assert extract_color(style) is None
