"""Tests for fastprompter.ui.markdown_highlighter — MarkdownHighlighter."""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

from unittest.mock import MagicMock

# ---------------------------------------------------------------------------
# PyQt6 stubs
# ---------------------------------------------------------------------------


class _MockQTextCharFormat:
    """Stand-in for QTextCharFormat — tracks formatting properties."""

    def __init__(self, source=None):
        # QTextCharFormat(other) copy-constructs; mirror that so highlighter
        # code that clones a base format (e.g. links) works under the mock.
        if source is not None:
            self._properties = dict(getattr(source, "_properties", {}))
            self._font_family = getattr(source, "_font_family", None)
            self._foreground = getattr(source, "_foreground", None)
            self._background = getattr(source, "_background", None)
            self._font_underline = getattr(source, "_font_underline", False)
            self._font_weight = getattr(source, "_font_weight", None)
            self._font_italic = getattr(source, "_font_italic", False)
            self._anchor = getattr(source, "_anchor", False)
            self._anchor_href = getattr(source, "_anchor_href", None)
            return
        self._properties = {}
        self._font_family = None
        self._foreground = None
        self._background = None
        self._font_underline = False
        self._font_weight = None
        self._font_italic = False
        self._anchor = False
        self._anchor_href = None

    def setFontWeight(self, w):
        self._font_weight = w

    def setFontStyleStrategy(self, strategy):
        self._properties["style_strategy"] = strategy

    def setFontItalic(self, v):
        self._font_italic = v

    def setFontStrikeOut(self, v):
        self._font_strikeout = v

    def setFontFixedPitch(self, v):
        self._font_fixed_pitch = v

    def setProperty(self, key, value):
        self._properties[key] = value

    def setForeground(self, color):
        self._foreground = color

    def setBackground(self, color):
        self._background = color

    def setFontFamily(self, family):
        self._font_family = family

    def setFontUnderline(self, v):
        self._font_underline = v

    def setAnchor(self, v):
        self._anchor = v

    def isAnchor(self):
        return self._anchor

    def setAnchorHref(self, href):
        self._anchor_href = href


class _MockQColor:
    """Stand-in for QColor — stores hex/name.

    Accepts one arg (hex string ``QColor(\"#fff\")``) or four
    (``QColor(r, g, b, a)``) positional patterns used in the highlighter.
    """

    def __init__(self, *args):
        # Preserve single-arg hex strings, store tuple repr for multi-arg
        self._name = args[0] if len(args) == 1 else str(args) if args else ""

    def __repr__(self):
        return f"_MockQColor({self._name!r})"


class _MockQFont:
    """Stand-in for QFont — holds Weight and StyleStrategy namespaces."""

    class Weight:
        Bold = 75

    class StyleStrategy:
        NoAntialias = 0x0100
        NoSubpixelAntialias = 0x0200


class _MockQTextFormat:
    """Stand-in for QTextFormat — provides Property namespace."""

    class Property:
        FontPointSize = 40


class _MockSip:
    """Stand-in for sip — provides isdeleted()."""

    @staticmethod
    def isdeleted(obj):
        return False


class _MockQSyntaxHighlighter:
    """Stand-in for QSyntaxHighlighter — tracks setFormat calls on highlight."""

    def __init__(self, parent=None):
        self._parent = parent
        self._format_calls = []  # (start, length, fmt)

    def setFormat(self, start, length, fmt):
        self._format_calls.append((start, length, fmt))

    def rehighlight(self):
        """Clear format calls to simulate rehighlight."""
        self._format_calls.clear()

    # block-state API used for fenced-code tracking
    def previousBlockState(self):
        return getattr(self, "_prev_state", -1)

    def currentBlockState(self):
        return getattr(self, "_cur_state", -1)

    def setCurrentBlockState(self, state):
        self._cur_state = state


class _MockTextDocument:
    """Stand-in for QTextDocument."""

    def __init__(self, parent=None):
        self._parent = parent


# Patch modules before importing MarkdownHighlighter
pyqt6_mock = MagicMock()
pyqt6_mock.sip = _MockSip
sys.modules["PyQt6"] = pyqt6_mock
sys.modules["PyQt6.QtGui"] = MagicMock()
sys.modules["PyQt6.QtGui"].QColor = _MockQColor
sys.modules["PyQt6.QtGui"].QFont = _MockQFont
sys.modules["PyQt6.QtGui"].QSyntaxHighlighter = _MockQSyntaxHighlighter
sys.modules["PyQt6.QtGui"].QTextCharFormat = _MockQTextCharFormat
sys.modules["PyQt6.QtGui"].QTextDocument = _MockTextDocument
sys.modules["PyQt6.QtGui"].QTextFormat = _MockQTextFormat

from fastprompter.ui.markdown_highlighter import MarkdownHighlighter

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def make_highlighter(base_size=11):
    """Create a MarkdownHighlighter with stubbed parent."""
    return MarkdownHighlighter(base_font_size=base_size)


# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------


class TestInit:
    def test_default_base_size(self):
        h = make_highlighter()
        assert h.base_font_size == 11

    def test_custom_base_size(self):
        h = make_highlighter(base_size=14)
        assert h.base_font_size == 14

    def test_skip_highlighting_defaults_false(self):
        h = make_highlighter()
        assert h._skip_highlighting is False

    def test_theme_defaults_none(self):
        h = make_highlighter()
        assert h.theme is None

    def test_rules_populated_after_init(self):
        h = make_highlighter()
        assert len(h._highlighting_rules) == 16, (
            f"Expected 16 rules (underline, strike, bold, italic x2, h1-h3, code, quote, link, "
            f"hr, cb_unchecked, cb_checked, bullet list, numbered list), got {len(h._highlighting_rules)}"
        )

    def test_each_rule_is_pattern_format_tuple(self):
        h = make_highlighter()
        for rule in h._highlighting_rules:
            assert isinstance(rule, tuple)
            assert len(rule) == 2
            assert hasattr(rule[0], "search")  # compiled regex
            assert hasattr(rule[1], "setFontWeight") or hasattr(
                rule[1], "_font_weight"
            )  # format-like


# ---------------------------------------------------------------------------
# update_base_size
# ---------------------------------------------------------------------------


class TestUpdateBaseSize:
    def test_updates_base_size(self):
        h = make_highlighter(11)
        h.update_base_size(16)
        assert h.base_font_size == 16

    def test_rebuilds_rules(self):
        h = make_highlighter(11)
        h.update_base_size(16)
        assert len(h._highlighting_rules) > 0
        # Header rule (H1) — index 5 after bold/underline/strike/italic x2
        h1_rule = h._highlighting_rules[5]
        fmt = h1_rule[1]
        assert fmt._properties.get(_MockQTextFormat.Property.FontPointSize) == 16 * 1.5

    def test_rehighlight_clears_format_calls(self):
        h = make_highlighter()
        h._format_calls.append((0, 5, _MockQTextCharFormat()))
        h.update_base_size(12)
        assert len(h._format_calls) == 0  # rehighlight clears


# ---------------------------------------------------------------------------
# update_theme
# ---------------------------------------------------------------------------


class TestUpdateTheme:
    def test_sets_theme(self):
        h = make_highlighter()
        theme = {"name": "Dark"}
        h.update_theme(theme)
        assert h.theme == theme

    def test_rebuilds_rules(self):
        h = make_highlighter()
        before = len(h._highlighting_rules)
        h.update_theme({})
        assert len(h._highlighting_rules) == before


# ---------------------------------------------------------------------------
# set_skip_large
# ---------------------------------------------------------------------------


class TestSetSkipLarge:
    def test_skip_true(self):
        h = make_highlighter()
        h.set_skip_large(True)
        assert h._skip_highlighting is True

    def test_skip_false(self):
        h = make_highlighter()
        h.set_skip_large(False)
        assert h._skip_highlighting is False


# ---------------------------------------------------------------------------
# highlightBlock — regex matching
# ---------------------------------------------------------------------------


class TestHighlightBlock:
    def test_bold(self):
        """**bold** should apply bold format."""
        h = make_highlighter()
        h.highlightBlock("text **bold** here")
        found = any(start == 5 and length == 8 for start, length, fmt in h._format_calls)
        assert found, f"Expected bold format at (5,8), got calls: {h._format_calls}"

    def test_italic_star(self):
        """*italic* should apply italic format."""
        h = make_highlighter()
        h.highlightBlock("text *italic* here")
        found = any(start == 5 and length == 8 for start, length, fmt in h._format_calls)
        assert found, f"Expected italic format at (5,8), got calls: {h._format_calls}"

    def test_italic_underscore(self):
        """_italic_ should apply italic format."""
        h = make_highlighter()
        h.highlightBlock("text _italic_ here")
        found = any(start == 5 and length == 8 for start, length, fmt in h._format_calls)
        assert found, f"Expected italic format at (5,8), got calls: {h._format_calls}"

    def test_header_h1(self):
        h = make_highlighter()
        h.highlightBlock("# Heading 1")
        found = any(start == 0 and length == 11 for start, length, fmt in h._format_calls)
        assert found, f"Expected H1 format at (0,11), got calls: {h._format_calls}"

    def test_header_h2(self):
        h = make_highlighter()
        h.highlightBlock("## Heading 2")
        found = any(start == 0 and length == 12 for start, length, fmt in h._format_calls)
        assert found, f"Expected H2 format at (0,12), got calls: {h._format_calls}"

    def test_header_h3(self):
        h = make_highlighter()
        h.highlightBlock("### Heading 3")
        found = any(start == 0 and length == 13 for start, length, fmt in h._format_calls)
        assert found, f"Expected H3 format at (0,13), got calls: {h._format_calls}"

    def test_inline_code(self):
        h = make_highlighter()
        h.highlightBlock("text `code` here")
        found = any(start == 5 and length == 6 for start, length, fmt in h._format_calls)
        assert found, f"Expected code format at (5,6), got calls: {h._format_calls}"

    def test_blockquote(self):
        h = make_highlighter()
        h.highlightBlock("> quoted text")
        found = any(start == 0 and length == 13 for start, length, fmt in h._format_calls)
        assert found, f"Expected quote format at (0,13), got calls: {h._format_calls}"

    def test_link(self):
        h = make_highlighter()
        h.highlightBlock("click [link](url) here")
        found = any(start == 6 and length == 11 for start, length, fmt in h._format_calls)
        assert found, f"Expected link format at (6,11), got calls: {h._format_calls}"

    def test_horizontal_rule(self):
        h = make_highlighter()
        h.highlightBlock("---")
        found = any(start == 0 and length == 3 for start, length, fmt in h._format_calls)
        assert found, f"Expected HR format at (0,3), got calls: {h._format_calls}"

    def test_checkbox_unchecked(self):
        h = make_highlighter()
        h.highlightBlock("[ ] task")
        found = any(start == 0 and length == 4 for start, length, fmt in h._format_calls)
        assert found, f"Expected unchecked checkbox format at (0,4), got calls: {h._format_calls}"

    def test_checkbox_checked(self):
        h = make_highlighter()
        h.highlightBlock("[x] done")
        found = any(start == 0 and length == 4 for start, length, fmt in h._format_calls)
        assert found, f"Expected checked checkbox format at (0,4), got calls: {h._format_calls}"

    def test_bullet_list(self):
        h = make_highlighter()
        h.highlightBlock("- item")
        found = any(start == 0 and length == 2 for start, length, fmt in h._format_calls)
        assert found, f"Expected bullet list format at (0,2), got calls: {h._format_calls}"

    def test_numbered_list(self):
        h = make_highlighter()
        h.highlightBlock("1. item")
        found = any(start == 0 and length == 3 for start, length, fmt in h._format_calls)
        assert found, f"Expected numbered list format at (0,3), got calls: {h._format_calls}"

    def test_no_matches_for_plain_text(self):
        h = make_highlighter()
        h.highlightBlock("just plain text")
        assert len(h._format_calls) == 0, (
            f"Expected no format calls for plain text, got {len(h._format_calls)}"
        )

    def test_empty_string(self):
        h = make_highlighter()
        h.highlightBlock("")
        assert len(h._format_calls) == 0

    def test_skip_highlighting_skips(self):
        h = make_highlighter()
        h.set_skip_large(True)
        h.highlightBlock("**bold**")
        assert len(h._format_calls) == 0, "Should not highlight when skip is True"

    def test_multiple_matches_same_line(self):
        h = make_highlighter()
        h.highlightBlock("**bold** and *italic*")
        calls = h._format_calls
        fmt_types = {(c[0], c[1]) for c in calls}
        assert (0, 8) in fmt_types, f"Expected bold at (0,8), got {fmt_types}"
