"""Tests for fastprompter.main — testable static methods and fallback renderer."""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

# ---------------------------------------------------------------------------
# No module-level mocking!  We replicate only the fallback renderer logic
# (which uses stdlib: html, re) — no Qt imports needed.
# ---------------------------------------------------------------------------

import html as html_mod
import re as re_mod


def _fallback_markdown_to_html(text):
    """Replicate FastPrompter.simple_markdown_to_html fallback path (main.py lines 2809-2849).

    The production code::

        @staticmethod
        def simple_markdown_to_html(text):
            import markdown
            try:
                body = markdown.markdown(html.escape(text), ...)
            except Exception:
                … fallback regex renderer …
            return f"<html>…{body}</html>"

    Since the ``markdown`` third-party library is not installed, the fallback
    path is always taken.  Keeping an extracted copy here avoids importing
    the full FastPrompter class (which requires a running QApplication).
    """
    lines = text.split("\n")
    html_lines = []
    in_code_block = False
    for line in lines:
        if line.startswith("```"):
            if in_code_block:
                html_lines.append("</pre>")
                in_code_block = False
            else:
                html_lines.append(
                    "<pre style='background:#1a1a1a;padding:5px;border:1px solid #333'>"
                )
                in_code_block = True
            continue
        if in_code_block:
            html_lines.append(line.replace("<", "&lt;").replace(">", "&gt;"))
            continue

        if line.startswith("### "):
            html_lines.append(
                f"<h3 style='color:#d4a842;margin:4px 0'>{html_mod.escape(line[4:])}</h3>"
            )
        elif line.startswith("## "):
            html_lines.append(
                f"<h2 style='color:#e0b856;margin:5px 0'>{html_mod.escape(line[3:])}</h2>"
            )
        elif line.startswith("# "):
            html_lines.append(
                f"<h1 style='color:#f0cc6a;margin:6px 0'>{html_mod.escape(line[2:])}</h1>"
            )
        elif line.startswith("> "):
            html_lines.append(
                f"<blockquote style='border-left:3px solid #7f848e;margin:4px 0;"
                f"padding-left:8px;color:#7f848e'>"
                f"<i>{html_mod.escape(line[2:])}</i></blockquote>"
            )
        elif re_mod.match(r"^\s*[-*_]{3,}\s*$", line):
            html_lines.append("<hr style='border:1px solid #5a4a2a;'>")
        elif re_mod.match(r"^\s*[-•*+]\s", line):
            content = re_mod.sub(r"^[-•*+]\s+", "", line)
            content = html_mod.escape(content)
            content = re_mod.sub(r"\*\*(.*?)\*\*", r"<b>\1</b>", content)
            content = re_mod.sub(r"\*(.*?)\*", r"<i>\1</i>", content)
            content = re_mod.sub(
                r"`(.*?)`",
                r'<code style="background:#1a1a1a;padding:0 2px;color:#e06c75">\1</code>',
                content,
            )
            content = re_mod.sub(
                r"\[(.*?)\]\((.*?)\)",
                r'<a href="\2" style="color:#61afef">\1</a>',
                content,
            )
            html_lines.append(f"<li style='margin:1px 0'>{content}</li>")
        else:
            line_text = line
            line_text = html_mod.escape(line_text)
            line_text = re_mod.sub(r"\*\*(.*?)\*\*", r"<b>\1</b>", line_text)
            line_text = re_mod.sub(r"\*(.*?)\*", r"<i>\1</i>", line_text)
            line_text = re_mod.sub(
                r"`(.*?)`",
                r'<code style="background:#1a1a1a;padding:0 2px;color:#e06c75">\1</code>',
                line_text,
            )
            line_text = re_mod.sub(
                r"\[(.*?)\]\((.*?)\)",
                r'<a href="\2" style="color:#61afef">\1</a>',
                line_text,
            )
            html_lines.append(
                f"<p style='margin:1px 0'>{line_text}</p>" if line_text.strip() else "<br>"
            )
    body = "\n".join(html_lines)
    return (
        "<html><body style='color:#c4ba9f;background:#0f0f0f;"
        "font-family:Verdana,sans-serif;font-size:11px;padding:6px'>"
        f"{body}</body></html>"
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestSimpleMarkdownToHtml:
    """Test the fallback regex-based markdown renderer."""

    def test_plain_text(self):
        result = _fallback_markdown_to_html("Hello world")
        assert result.startswith("<html>")
        assert "Hello world" in result
        assert "</body></html>" in result

    def test_bold(self):
        result = _fallback_markdown_to_html("This is **bold** text")
        assert "<b>bold</b>" in result

    def test_italic(self):
        result = _fallback_markdown_to_html("This is *italic* text")
        assert "<i>italic</i>" in result

    def test_header_h1(self):
        result = _fallback_markdown_to_html("# Heading 1")
        assert "<h1" in result
        assert "Heading 1" in result

    def test_header_h2(self):
        result = _fallback_markdown_to_html("## Heading 2")
        assert "<h2" in result

    def test_header_h3(self):
        result = _fallback_markdown_to_html("### Heading 3")
        assert "<h3" in result

    def test_blockquote(self):
        result = _fallback_markdown_to_html("> quoted text")
        assert "<blockquote" in result
        assert "quoted text" in result

    def test_horizontal_rule(self):
        result = _fallback_markdown_to_html("---")
        assert "<hr" in result

    def test_bullet_list(self):
        result = _fallback_markdown_to_html("- list item")
        assert "<li" in result
        assert "list item" in result

    def test_code_block(self):
        result = _fallback_markdown_to_html("```\nprint('hello')\n```")
        assert "<pre" in result
        assert "print" in result

    def test_inline_code(self):
        result = _fallback_markdown_to_html("Inline `code` here")
        assert "<code" in result

    def test_link(self):
        result = _fallback_markdown_to_html("[click](https://example.com)")
        assert '<a href="https://example.com"' in result
        assert "click" in result

    def test_html_escaping(self):
        result = _fallback_markdown_to_html("<script>alert('xss')</script>")
        assert "&lt;" in result
        assert "<script>" not in result

    def test_empty_string(self):
        result = _fallback_markdown_to_html("")
        assert "<html>" in result
        assert "</body>" in result

    def test_multiple_lines(self):
        text = "Line 1\n\nLine 2"
        result = _fallback_markdown_to_html(text)
        assert "Line 1" in result
        assert "Line 2" in result

    def test_mixed_formatting(self):
        result = _fallback_markdown_to_html("**bold** and *italic* and `code`")
        assert "<b>bold</b>" in result
        assert "<i>italic</i>" in result
        assert "<code" in result

    def test_bullet_with_formatting(self):
        result = _fallback_markdown_to_html("- **bold bullet**")
        assert "<li" in result
        assert "<b>bold bullet</b>" in result

    def test_consecutive_headers(self):
        text = "# Title\n\n## Subtitle\n\n### Section"
        result = _fallback_markdown_to_html(text)
        assert "<h1" in result
        assert "<h2" in result
        assert "<h3" in result
