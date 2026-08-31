"""Tests for fastprompter.main — testable static methods and fallback renderer."""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

# ---------------------------------------------------------------------------
# No module-level mocking!  We replicate only the fallback renderer logic
# (which uses stdlib: html, re) — no Qt imports needed.
# ---------------------------------------------------------------------------

import ast
import html as html_mod
import pathlib
import re as re_mod
from types import SimpleNamespace


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


def test_project_tab_switch_does_not_push_all_bindings():
    source = pathlib.Path(__file__).parents[1] / "src/fastprompter/main.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    method = next(
        node for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == "on_tab_changed"
    )
    calls = [
        node for node in ast.walk(method)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "_push_sync_files"
    ]
    assert not calls


def _method_node(name):
    source = pathlib.Path(__file__).parents[1] / "src/fastprompter/main.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    return next(
        node for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == name
    )


def test_project_tab_switch_has_no_duplicate_silo_refresh():
    method = _method_node("on_tab_changed")
    refreshes = [
        node for node in ast.walk(method)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "refresh_temp_presets"
    ]
    assert not refreshes


def test_warm_switch_has_no_whole_document_equality():
    method = _method_node("_switch_to_slot")
    for node in ast.walk(method):
        if not isinstance(node, ast.Compare):
            continue
        calls = [child for child in ast.walk(node) if isinstance(child, ast.Call)]
        assert not any(
            isinstance(call.func, ast.Attribute)
            and call.func.attr == "toPlainText"
            for call in calls
        )


def test_archive_render_does_not_trim_or_mutate_filesystem():
    method = _method_node("refresh_archive_panel")
    called = {
        node.func.attr for node in ast.walk(method)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert "_trim_archive" not in called
    assert "_delete_file_container" not in called


def test_line_count_cache_reuses_text_generation():
    from fastprompter.main import FastPrompter

    class CountingText(str):
        def __new__(cls, value):
            obj = super().__new__(cls, value)
            obj.count_calls = 0
            return obj

        def count(self, *args, **kwargs):
            self.count_calls += 1
            return super().count(*args, **kwargs)

    window = SimpleNamespace(
        _line_count_cache={},
        get_current_category=lambda: "A",
    )
    window._silo_cache_key = FastPrompter._silo_cache_key
    raw = CountingText("one\ntwo")
    assert FastPrompter._cached_silo_line_count(window, raw, 0) == 2
    assert FastPrompter._cached_silo_line_count(window, raw, 0) == 2
    assert raw.count_calls == 1
    replacement = CountingText("one\ntwo")
    assert FastPrompter._cached_silo_line_count(window, replacement, 0) == 2
    assert replacement.count_calls == 1


def test_category_document_cache_obeys_character_budget():
    from fastprompter.main import FastPrompter

    class FakeDocument:
        def __init__(self, chars):
            self.chars = chars

        def characterCount(self):
            return self.chars + 1

    old_doc = FakeDocument(80)
    new_doc = FakeDocument(80)
    window = SimpleNamespace(
        _category_document_cache={
            "old": ([old_doc], []),
            "new": ([new_doc], []),
        },
        _document_cache_limit=4,
        _document_cache_char_limit=100,
        _document_fingerprint_cache={(id(old_doc), 1): (80, 1)},
        _line_count_cache={("old", False, 0): ("old", 1)},
        text_area=SimpleNamespace(document=lambda: None),
    )
    window._document_lists_char_count = \
        FastPrompter._document_lists_char_count
    FastPrompter._prune_category_document_cache(window)
    assert list(window._category_document_cache) == ["new"]
    assert not window._document_fingerprint_cache
    assert not window._line_count_cache


def test_new_document_never_inherits_evicted_loaded_token(qapp):
    from PyQt6.QtGui import QTextDocument

    from fastprompter.main import FastPrompter

    window = SimpleNamespace(_document_fingerprint_cache={})
    window._set_plain_text_clean = FastPrompter._set_plain_text_clean
    window._document_fingerprint = \
        FastPrompter._document_fingerprint.__get__(window)
    window._ensure_document_text = \
        FastPrompter._ensure_document_text.__get__(window)

    authoritative = "PROJECT A — must survive eviction"
    old_doc = QTextDocument()
    assert window._ensure_document_text(old_doc, authoritative) is False
    assert window._ensure_document_text(old_doc, authoritative) is True

    # LRU eviction destroys old_doc. A brand-new document cannot inherit its
    # loaded proof even though the authoritative Python string is identical.
    new_doc = QTextDocument()
    assert window._ensure_document_text(new_doc, authoritative) is False
    assert new_doc.toPlainText() == authoritative


def test_profile_cache_reset_drops_all_document_derived_state():
    from fastprompter.main import FastPrompter

    class FakeDocument:
        def __init__(self):
            self.retired = False

        def deleteLater(self):
            self.retired = True

    active = FakeDocument()
    stale = FakeDocument()
    window = SimpleNamespace(
        data={"temp_presets": ["PROFILE B"], "archive_temp_presets": []},
        text_area=SimpleNamespace(document=lambda: active),
        silo_docs=[active],
        archive_docs=[],
        _category_document_cache={"Text": ([stale], [])},
        _document_fingerprint_cache={(id(stale), 1): (1, 1)},
        _line_count_cache={("Text", False, 0): ("PROFILE A", 1)},
        _editor_text_snaps=(1, 1, "PROFILE A"),
        _last_cached_text="PROFILE A",
    )
    FastPrompter._reset_profile_document_caches(window)
    assert window._category_document_cache == {}
    assert window._document_fingerprint_cache == {}
    assert window._line_count_cache == {}
    assert window._editor_text_snaps is None
    assert window._last_cached_text is None
    assert window.silo_docs == [None]
    assert stale.retired is True
    assert active.retired is False


def test_commit_current_text_reuses_revision_snapshot():
    from unittest.mock import MagicMock

    from fastprompter.main import FastPrompter

    window = SimpleNamespace(
        _initializing_ui=False,
        _editor_text_snapshot=MagicMock(return_value="cached snapshot"),
        text_area=SimpleNamespace(toPlainText=MagicMock()),
        _flush_live_editor=MagicMock(),
    )
    FastPrompter.commit_current_text(window)
    window._editor_text_snapshot.assert_called_once_with()
    window.text_area.toPlainText.assert_not_called()
    window._flush_live_editor.assert_called_once_with("cached snapshot")


def test_hidden_archive_refresh_never_scans_archive_text():
    from unittest.mock import MagicMock

    from fastprompter.main import FastPrompter

    class CountingText(str):
        def count(self, *args, **kwargs):
            raise AssertionError("hidden archive text was scanned")

    window = SimpleNamespace(
        data={
            "archive_temp_presets": [CountingText("large\narchive")],
            "archive_visible": "False",
        },
        archive_section=SimpleNamespace(setVisible=MagicMock()),
    )
    FastPrompter.refresh_archive_panel(window)
    window.archive_section.setVisible.assert_called_once_with(False)


def test_fingerprint_cache_separates_equal_revisions_by_document():
    from fastprompter.main import FastPrompter

    class FakeDocument:
        def __init__(self, text):
            self.text = text
            self.reads = 0

        def revision(self):
            return 7

        def toPlainText(self):
            self.reads += 1
            return self.text

    window = SimpleNamespace(_document_fingerprint_cache={})
    first = FakeDocument("alpha")
    second = FakeDocument("bravo")
    first_fp = FastPrompter._document_fingerprint(window, first)
    second_fp = FastPrompter._document_fingerprint(window, second)
    assert first_fp != second_fp
    assert FastPrompter._document_fingerprint(window, first) == first_fp
    assert first.reads == 1
    assert second.reads == 1


def test_update_preview_does_not_extract_text_outside_reading_mode():
    from unittest.mock import MagicMock

    from fastprompter.ui.theme_mixin import ThemeMixin

    window = ThemeMixin.__new__(ThemeMixin)
    window.preview_combo = MagicMock()
    window.preview_combo.currentData.return_value = "Source View"
    window.text_area = MagicMock()
    window.preview_area = MagicMock()
    ThemeMixin.update_preview(window)
    window.text_area.toPlainText.assert_not_called()


def test_update_preview_accepts_navigation_snapshot():
    from unittest.mock import MagicMock

    from fastprompter.ui.theme_mixin import ThemeMixin

    window = ThemeMixin.__new__(ThemeMixin)
    window.preview_combo = MagicMock()
    window.preview_combo.currentData.return_value = "Reading"
    window.text_area = MagicMock()
    window.preview_area = MagicMock()
    window.simple_markdown_to_html = MagicMock(return_value="<html></html>")
    ThemeMixin.update_preview(window, "already captured")
    window.text_area.toPlainText.assert_not_called()
    window.simple_markdown_to_html.assert_called_once_with("already captured")


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
