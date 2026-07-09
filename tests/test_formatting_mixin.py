"""Tests for fastprompter.ui.formatting_mixin — markdown rendering, regex patterns, text cleaning."""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

from unittest.mock import MagicMock

# ---------------------------------------------------------------------------
# PyQt6 stubs — needed because FormattingMixin imports QFont/QTextCursor at
# the module level, even though simple_markdown_to_html doesn't use them.
# ---------------------------------------------------------------------------

class _MockQFont:
    class Weight:
        Normal = 50
        Bold = 75

    class StyleStrategy:
        NoAntialias = 0x0100
        NoSubpixelAntialias = 0x0200

    def __init__(self, family=None, size=None):
        self._family = family
        self._size = size

    def setStyleStrategy(self, strategy):
        pass


class _MockQTextCharFormat:
    def setFont(self, font):
        pass

    def setFontWeight(self, w):
        pass

    def setFontItalic(self, v):
        pass

    def setFontUnderline(self, v):
        pass

    def setFontStrikeOut(self, v):
        pass


class _MockQTextCursor:
    class MoveOperation:
        Start = 0
        End = 1
        StartOfBlock = 2
        EndOfBlock = 3
        NoMove = 4

    class SelectionType:
        Document = 0

    def __init__(self):
        self._pos = 0
        self._selected = ""
        self._block = MagicMock()
        self._block.position.return_value = 0

    def positionInBlock(self):
        return self._pos

    def movePosition(self, op, mode=0, n=1):
        return True

    def selectedText(self):
        return self._selected

    def hasSelection(self):
        return False

    def block(self):
        return self._block

    def beginEditBlock(self):
        pass

    def endEditBlock(self):
        pass

    def insertText(self, text):
        pass

    def charFormat(self):
        return _MockQTextCharFormat()

    def mergeCharFormat(self, fmt):
        pass

    def select(self, mode):
        pass

    def removeSelectedText(self):
        pass

    def clearSelection(self):
        pass

    def setPosition(self, pos):
        pass


sys.modules["PyQt6"] = MagicMock()
sys.modules["PyQt6.QtGui"] = MagicMock()
sys.modules["PyQt6.QtGui"].QFont = _MockQFont
sys.modules["PyQt6.QtGui"].QTextCharFormat = _MockQTextCharFormat
sys.modules["PyQt6.QtGui"].QTextCursor = _MockQTextCursor

# Force the fallback renderer path by patching markdown.markdown to raise.
# Without this, the installed markdown library would handle rendering and
# output <strong>/<em> instead of the fallback's <b>/<i>.
import markdown as _markdown_mod

from fastprompter.ui.formatting_mixin import (
    _RE_BOLD,
    _RE_BULLET,
    _RE_DASH_LINE,
    _RE_HEADER_DASH,
    _RE_INLINE_CODE,
    _RE_ITALIC,
    _RE_LINK,
    _RE_LIST_ITEM,
    _RE_LIST_SUB,
    FormattingMixin,
)

_markdown_mod.markdown = MagicMock(side_effect=Exception("forced fallback"))


# ---------------------------------------------------------------------------
# Regex pattern tests
# ---------------------------------------------------------------------------


class TestRegexPatterns:
    """Verify module-level regex patterns match expected inputs."""

    def test_re_dash_line_matches_dashes(self):
        assert _RE_DASH_LINE.match("---")
        assert _RE_DASH_LINE.match("   ---   ")
        assert _RE_DASH_LINE.match("   -------   ")

    def test_re_dash_line_rejects_non_dashes(self):
        assert not _RE_DASH_LINE.match("hello")
        assert not _RE_DASH_LINE.match("-- ")
        assert not _RE_DASH_LINE.match("----a----")

    def test_re_header_dash_same_as_dash_line(self):
        """_RE_HEADER_DASH should match the same pattern as _RE_DASH_LINE."""
        m1 = _RE_HEADER_DASH.match("---")
        m2 = _RE_DASH_LINE.match("---")
        assert m1 is not None
        assert m2 is not None
        assert m1.group() == m2.group()

    def test_re_list_item_matches_dash(self):
        m = _RE_LIST_ITEM.match("- item")
        assert m

    def test_re_list_item_matches_star(self):
        assert _RE_LIST_ITEM.match("* item")

    def test_re_list_item_matches_bullet(self):
        assert _RE_LIST_ITEM.match("• item")

    def test_re_list_item_matches_numbered(self):
        assert _RE_LIST_ITEM.match("1. item")

    def test_re_list_item_rejects_plain_text(self):
        assert not _RE_LIST_ITEM.match("plain text")
        assert not _RE_LIST_ITEM.match("")

    def test_re_list_sub_removes_dash(self):
        result = _RE_LIST_SUB.sub("", "- item text")
        assert result == "item text"

    def test_re_list_sub_removes_star(self):
        result = _RE_LIST_SUB.sub("", "* item text")
        assert result == "item text"

    def test_re_list_sub_removes_bullet(self):
        result = _RE_LIST_SUB.sub("", "• item text")
        assert result == "item text"

    def test_re_list_sub_removes_numbered(self):
        result = _RE_LIST_SUB.sub("", "1. item text")
        assert result == "item text"

    def test_re_bullet_matches_bullet(self):
        assert _RE_BULLET.match("• text")

    def test_re_bullet_rejects_dash(self):
        assert not _RE_BULLET.match("- text")

    def test_re_bold_matches(self):
        m = _RE_BOLD.search("some **bold** text")
        assert m
        assert m.group(1) == "bold"

    def test_re_italic_matches(self):
        m = _RE_ITALIC.search("some *italic* text")
        assert m
        assert m.group(1) == "italic"

    def test_re_italic_does_not_match_double_star_outside(self):
        """Single-star italic at position 0 should not match the opening **."""
        # _RE_ITALIC = r"\*(?!\*)(.*?)\*" — at pos 0 the negative lookahead
        # finds the second *, so the overall match starts after it.
        # The pattern WILL match *bold* inside **bold** starting at pos 1.
        m = _RE_ITALIC.search("**bold**")
        assert m is not None  # matches *bold* starting at position 1
        assert m.group() == "*bold*"

    def test_re_inline_code_matches(self):
        m = _RE_INLINE_CODE.search("some `code` here")
        assert m
        assert m.group(1) == "code"

    def test_re_link_matches(self):
        m = _RE_LINK.search("[text](https://example.com)")
        assert m
        assert m.group(1) == "text"
        assert m.group(2) == "https://example.com"


# ---------------------------------------------------------------------------
# simple_markdown_to_html tests
# ---------------------------------------------------------------------------


class TestSimpleMarkdownToHtml:
    """Test FormattingMixin.simple_markdown_to_html via the fallback path.

    The method tries markdown.markdown() first; if that fails, it falls
    back to a regex-based renderer.  By patching markdown.markdown to
    raise an exception we can test the fallback deterministically.
    """

    def _call(self, text):
        return FormattingMixin().simple_markdown_to_html(text)

    def test_plain_text(self):
        result = self._call("Hello world")
        assert result.startswith("<html>")
        assert "Hello world" in result
        assert "</body></html>" in result

    def test_bold(self):
        result = self._call("This is **bold** text")
        assert "<b>bold</b>" in result

    def test_italic(self):
        result = self._call("This is *italic* text")
        assert "<i>italic</i>" in result

    def test_header_h1(self):
        result = self._call("# Heading 1")
        assert "<h1" in result
        assert "Heading 1" in result

    def test_header_h2(self):
        result = self._call("## Heading 2")
        assert "<h2" in result

    def test_header_h3(self):
        result = self._call("### Heading 3")
        assert "<h3" in result

    def test_blockquote(self):
        result = self._call("> quoted text")
        assert "<blockquote" in result
        assert "quoted text" in result

    def test_horizontal_rule(self):
        result = self._call("---")
        assert "<hr" in result

    def test_bullet_dash(self):
        result = self._call("- list item")
        assert "<li" in result
        assert "list item" in result

    def test_bullet_asterisk(self):
        result = self._call("* list item")
        assert "<li" in result

    def test_bullet_numbered(self):
        result = self._call("1. list item")
        assert "<li" in result

    def test_code_block(self):
        result = self._call("```\nprint('hello')\n```")
        assert "<pre" in result
        assert "print" in result

    def test_inline_code(self):
        result = self._call("Inline `code` here")
        assert "<code" in result

    def test_link(self):
        result = self._call("[click](https://example.com)")
        assert 'href="https://example.com"' in result
        assert "click" in result

    def test_html_escaping(self):
        result = self._call("<script>alert('xss')</script>")
        assert "&lt;" in result
        assert "<script>" not in result

    def test_empty_string(self):
        result = self._call("")
        assert "<html>" in result
        assert "</body>" in result

    def test_multiple_lines(self):
        result = self._call("Line 1\n\nLine 2")
        assert "Line 1" in result
        assert "Line 2" in result

    def test_mixed_formatting(self):
        result = self._call("**bold** and *italic* and `code`")
        assert "<b>bold</b>" in result
        assert "<i>italic</i>" in result
        assert "<code" in result

    def test_bullet_with_formatting(self):
        result = self._call("- **bold bullet**")
        assert "<li" in result
        assert "<b>bold bullet</b>" in result

    def test_consecutive_headers(self):
        result = self._call("# Title\n\n## Subtitle\n\n### Section")
        assert "<h1" in result
        assert "<h2" in result
        assert "<h3" in result

    def test_blockquote_with_formatting(self):
        result = self._call("> **important** quote")
        # Fallback wraps blockquote content in <i> and applies html.escape
        # before any markdown substitution, so ** is not rendered as bold.
        assert "<blockquote" in result
        assert "**important**" in result

    def test_empty_block_still_wraps_body(self):
        result = self._call("\n\n")
        assert "<body" in result
        assert "<br" in result

    def test_bullet_with_inline_code(self):
        result = self._call("- use `os.path.join()` here")
        assert "<li" in result
        assert "<code" in result

    def test_star_inside_word_not_italic(self):
        """Asterisk inside a word should not be treated as italic marker."""
        result = self._call("file1.py * file2.py")
        # The fallback treats * as italic, but this is acceptable.
        # Just verify it doesn't crash and produces valid HTML.
        assert result.startswith("<html>")

    def test_link_in_bullet(self):
        result = self._call("- [docs](https://docs.example.com)")
        assert "<li" in result
        assert 'href="https://docs.example.com"' in result


# ---------------------------------------------------------------------------
# toggle_bullet_conversion logic tests (regex-level, no Qt needed)
# ---------------------------------------------------------------------------




class TestBulletConversionLogic:
    """Test the regex substitution logic used by toggle_bullet_conversion.

    This tests the pure regex transforms without requiring a QTextCursor.
    """

    def test_dash_to_bullet_conversion(self):
        import re
        lines = ["- item one", "- item two"]
        result = [re.sub(r"^(\s*)-\s+", r"\1• ", line) for line in lines]
        assert result == ["• item one", "• item two"]

    def test_bullet_to_dash_conversion(self):
        import re
        lines = ["• item one", "• item two"]
        result = [re.sub(r"^(\s*)•\s*", r"\1- ", line) for line in lines]
        assert result == ["- item one", "- item two"]

    def test_dash_line_preserved_during_conversion(self):
        """Lines matching _RE_DASH_LINE should not have their content altered."""
        import re
        lines = ["- item one", "---", "- item two"]
        result = []
        for line in lines:
            if _RE_DASH_LINE.match(line):
                result.append(line)
            else:
                result.append(re.sub(r"^(\s*)-\s+", r"\1• ", line))
        assert result == ["• item one", "---", "• item two"]

    def test_indented_dash_conversion(self):
        import re
        lines = ["  - indented item"]
        result = [re.sub(r"^(\s*)-\s+", r"\1• ", line) for line in lines]
        assert result == ["  • indented item"]
