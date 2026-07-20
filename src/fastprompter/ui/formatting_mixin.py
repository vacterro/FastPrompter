"""Formatting mixin for FastPrompter — markdown rendering, text cleaning, and format clearing.

Extracted from main.py Phase 1 of the modularization plan.
Provides FormattingMixin class for use as a mixin with FastPrompter QMainWindow.
"""

import html
import re

import markdown
from PyQt6.QtGui import QFont, QTextCharFormat, QTextCursor

# Pre-compiled regex patterns for markdown processing
_RE_DASH_LINE = re.compile(r"^\s*-{3,}\s*$")
_RE_HEADER_DASH = re.compile(r"^\s*-{3,}\s*$")
_RE_LIST_ITEM = re.compile(r"^\s*(?:[-*•+]\s|\d+\.\s)")
_RE_LIST_SUB = re.compile(r"^\s*[-*•+](?:\s+|$)|^\s*\d+\.\s+")
_RE_BOLD = re.compile(r"\*\*(.*?)\*\*")
_RE_ITALIC = re.compile(r"\*(?!\*)(.*?)\*")
_RE_INLINE_CODE = re.compile(r"`([^`]+)`")
_RE_LINK = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
_RE_BULLET = re.compile(r"^\s*•")
# Fenced/inline code spans, split out so simple_markdown_to_html can skip
# escaping them (markdown escapes code content itself — see its docstring)
_RE_CODE_SPAN = re.compile(r"(```[\s\S]*?```|`[^`\n]*`)")


class FormattingMixin:
    """Mixin providing markdown rendering, text cleaning, and format clearing.

    Type hints assume these attributes are provided by the FastPrompter
    QMainWindow instance at runtime:
        self.text_area, self.sound_manager, self._font_size,
        self._font_family, self._ui_scale
    """

    # Formatting lives IN the text as markdown markers — it survives
    # save/reload (the DB stores plain text) and copy-paste anywhere.
    _MD_MARKERS = {"bold": "**", "italic": "*", "underline": "__", "strike": "~~"}

    @staticmethod
    def _md_wrapped(sel, marker):
        """Is the selection exactly wrapped in this marker?"""
        m = len(marker)
        if not (sel.startswith(marker) and sel.endswith(marker) and len(sel) > 2 * m):
            return False
        if marker == "*":
            # '**bold**' is not italic-wrapped ('***both***' is)
            if sel.startswith("**") and not sel.startswith("***"):
                return False
            if sel.endswith("**") and not sel.endswith("***"):
                return False
        return True

    def apply_format(self, fmt_type):
        """Toggle markdown markers around the selection (word at cursor if
        nothing is selected). The highlighter renders the marked spans."""
        marker = self._MD_MARKERS.get(fmt_type)
        if marker is None:
            return
        ta = self.text_area
        cursor = ta.textCursor()
        if not cursor.hasSelection():
            cursor.select(QTextCursor.SelectionType.WordUnderCursor)
            if not cursor.hasSelection():
                return
        doc_text = ta.toPlainText()
        start, end = cursor.selectionStart(), cursor.selectionEnd()
        sel = doc_text[start:end]
        # keep markers tight against the text, not surrounding whitespace
        start += len(sel) - len(sel.lstrip())
        end -= len(sel) - len(sel.rstrip())
        if start >= end:
            return
        sel = doc_text[start:end]
        m = len(marker)

        wrapped_inside = self._md_wrapped(sel, marker)
        wrapped_outside = False
        if not wrapped_inside:
            wrapped_outside = (
                doc_text[max(0, start - m):start] == marker
                and doc_text[end:end + m] == marker
            )
            if wrapped_outside and marker == "*":
                if doc_text[max(0, start - 2):start] == "**" and doc_text[max(0, start - 3):start] != "***":
                    wrapped_outside = False
                elif doc_text[end:end + 2] == "**" and doc_text[end:end + 3] != "***":
                    wrapped_outside = False

        cursor.beginEditBlock()
        if wrapped_inside:
            cursor.setPosition(start)
            cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
            cursor.insertText(sel[m:-m])
            new_start, new_end = start, end - 2 * m
        elif wrapped_outside:
            cursor.setPosition(start - m)
            cursor.setPosition(end + m, QTextCursor.MoveMode.KeepAnchor)
            cursor.insertText(sel)
            new_start, new_end = start - m, start - m + len(sel)
        else:
            cursor.setPosition(start)
            cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
            cursor.insertText(f"{marker}{sel}{marker}")
            new_start, new_end = start + m, start + m + len(sel)
        cursor.endEditBlock()

        cursor.setPosition(new_start)
        cursor.setPosition(new_end, QTextCursor.MoveMode.KeepAnchor)
        ta.setTextCursor(cursor)
        ta.setFocus()
        self.mark_dirty()

    def toggle_header_line(self):
        """Ctrl+E: Toggle `# ` header + `**` bold markers (persists across sessions)."""
        cursor = self.text_area.textCursor()
        # balance the endEditBlock() below (was unbalanced — freeze risk)
        cursor.beginEditBlock()

        pos_in_block = cursor.positionInBlock()
        block = cursor.block()

        cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
        cursor.movePosition(QTextCursor.MoveOperation.EndOfBlock, QTextCursor.MoveMode.KeepAnchor)
        sel = cursor.selectedText()

        # Remove old `**` if it happens to be there from the old version
        if sel.startswith("**") and sel.endswith("**") and len(sel) >= 4:
            sel = sel[2:-2]

        has_hdr = sel.startswith("# ")
        if has_hdr:
            new_text = sel[2:]
            offset = -2
        else:
            new_text = f"# {sel}"
            offset = 2

        cursor.insertText(new_text)

        # Apply visual format
        cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
        cursor.movePosition(QTextCursor.MoveOperation.EndOfBlock, QTextCursor.MoveMode.KeepAnchor)
        fmt = cursor.charFormat()
        if has_hdr:
            fmt.setFontWeight(QFont.Weight.Normal)
            fmt.setFontUnderline(False)
        else:
            fmt.setFontWeight(QFont.Weight.Bold)
            fmt.setFontUnderline(True)
        cursor.mergeCharFormat(fmt)

        cursor.endEditBlock()

        new_pos_in_block = max(0, pos_in_block + offset)
        new_cursor = self.text_area.textCursor()
        new_cursor.setPosition(block.position() + new_pos_in_block)
        self.text_area.setTextCursor(new_cursor)

        self.text_area.setFocus()
        self.mark_dirty()

    def apply_bold_smart(self):
        """Ctrl+B: Bold selected text. If nothing selected, bold/unbold entire current line."""
        cursor = self.text_area.textCursor()
        if not cursor.hasSelection():
            # Select whole current line
            cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
            cursor.movePosition(
                QTextCursor.MoveOperation.EndOfBlock, QTextCursor.MoveMode.KeepAnchor
            )
            self.text_area.setTextCursor(cursor)
        self.apply_format("bold")

    def toggle_quote_conversion(self):
        """Wrap/unwrap the selected lines (or the current line) as a '> '
        quote block. A quote of 2+ lines becomes foldable — see editor.py
        _is_quote_start/_fold_range — collapsing down to its first line."""
        cursor = self.text_area.textCursor()
        cursor.beginEditBlock()
        try:
            if cursor.hasSelection():
                text = cursor.selectedText().replace(" ", "\n")
            else:
                cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
                cursor.movePosition(QTextCursor.MoveOperation.EndOfBlock,
                                    QTextCursor.MoveMode.KeepAnchor)
                text = cursor.selectedText()

            lines = text.split("\n") or [""]
            non_empty = [ln for ln in lines if ln.strip()]
            if non_empty and all(ln.lstrip().startswith(">") for ln in non_empty):
                new_lines = [re.sub(r"^(\s*)>\s?", r"\1", ln) for ln in lines]
            else:
                new_lines = [ln if not ln.strip() else f"> {ln.lstrip()}" for ln in lines]
            cursor.insertText("\n".join(new_lines))
        finally:
            cursor.endEditBlock()
        self.text_area.setFocus()
        self.mark_dirty()

    def toggle_bullet_conversion(self):
        """Toggle between bullet (•) and dash (-) list markers on selected text."""
        cursor = self.text_area.textCursor()
        # beginEditBlock MUST balance every endEditBlock below — an unbalanced
        # end corrupts the doc edit-block counter and freezes rendering
        cursor.beginEditBlock()
        if cursor.hasSelection():
            text = cursor.selectedText().replace("\u2029", "\n")
        else:
            text = self.text_area.toPlainText()
            cursor.select(QTextCursor.SelectionType.Document)

        lines = text.splitlines()
        if not lines:
            cursor.endEditBlock()
            return

        if any(_RE_BULLET.match(line) for line in lines):
            # Convert bullets back to dashes, skip divider lines
            new_lines = []
            for line in lines:
                if _RE_DASH_LINE.match(line):  # Protect --- dividers
                    new_lines.append(line)
                else:
                    new_lines.append(re.sub(r"^(\s*)•\s*", r"\1- ", line))
        else:
            # Convert dashes to bullets, skip divider lines (---)
            new_lines = []
            for line in lines:
                if _RE_DASH_LINE.match(line):  # Protect --- dividers from conversion
                    new_lines.append(line)
                else:
                    new_lines.append(re.sub(r"^(\s*)-\s+", r"\1• ", line))

        new_text = "\n".join(new_lines)
        cursor.insertText(new_text)
        cursor.endEditBlock()
        self.text_area.setFocus()
        self.mark_dirty()

    def divider_counts(self):
        """User-configured blank-line counts around a --- divider.
        Single source of truth for every divider entry point (toolbar,
        Ctrl+W, Enter on a bare --- line)."""
        try:
            before = max(0, min(6, int(self.data.get("divider_lines_before", 2))))
        except (TypeError, ValueError):
            before = 2
        try:
            after = max(1, min(6, int(self.data.get("divider_lines_after", 3))))
        except (TypeError, ValueError):
            after = 3
        return before, after

    def insert_add_line(self):
        """Insert a horizontal markdown divider line (---) pushing text down,
        while returning the cursor to the exact original position.
        """
        cursor = self.text_area.textCursor()
        original_pos = cursor.position()
        # beginEditBlock MUST balance endEditBlock — an unbalanced end
        # corrupts the document's edit-block counter and freezes rendering
        cursor.beginEditBlock()
        cursor.insertText("\n\n\n\n\n---\n")
        cursor.endEditBlock()
        cursor.setPosition(original_pos)
        self.text_area.setTextCursor(cursor)
        self.text_area.ensureCursorVisible()
        self.text_area.setFocus()
        self.mark_dirty()

    def insert_old_add_line(self):
        """Insert a horizontal markdown divider line (---) with smart spacing,
        landing on a fresh bullet ready to type. (Old Ctrl+W behavior)
        """
        before, after = self.divider_counts()
        cursor = self.text_area.textCursor()
        cursor.beginEditBlock()
        block = cursor.block()
        if cursor.positionInBlock() > 0 or block.text().strip():
            cursor.movePosition(QTextCursor.MoveOperation.EndOfBlock)
        cursor.insertText("\n" * before + "---" + "\n" * after + "\u2022 ")
        cursor.endEditBlock()
        self.text_area.setTextCursor(cursor)
        self.text_area.ensureCursorVisible()
        self.text_area.setFocus()
        self.mark_dirty()

    def simple_markdown_to_html(self, text):
        """Convert markdown text to styled HTML with fallback renderer."""


        try:
            # html.escape() runs on the prose so raw HTML (e.g. a pasted
            # <script> tag) can't render as live markup — but code spans and
            # fences are skipped: markdown does its own <, >, & escaping for
            # those, and that pass isn't entity-aware, so pre-escaping them
            # here double-escaped the content ("a < b" came out as the
            # literal text "a &amp;lt; b").
            parts = _RE_CODE_SPAN.split(text)
            escaped = "".join(
                part if part.startswith("`") else html.escape(part) for part in parts
            )
            # Full markdown renderer using standard Python markdown library if available
            body = markdown.markdown(escaped, extensions=["fenced_code", "tables"])
        except Exception:
            # Fallback to simple regex renderer if markdown library not available
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
                    html_lines.append(
                        line.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                    )
                    continue

                if line.startswith("### "):
                    html_lines.append(
                        f"<h3 style='color:#d4a842;margin:4px 0'>{html.escape(line[4:])}</h3>"
                    )
                elif line.startswith("## "):
                    html_lines.append(
                        f"<h2 style='color:#e0b856;margin:5px 0'>{html.escape(line[3:])}</h2>"
                    )
                elif line.startswith("# "):
                    html_lines.append(
                        f"<h1 style='color:#f0cc6a;margin:6px 0'>{html.escape(line[2:])}</h1>"
                    )
                elif line.startswith("> "):
                    html_lines.append(
                        f"<blockquote style='border-left:3px solid #7f848e;margin:4px 0;padding-left:8px;color:#7f848e'><i>{html.escape(line[2:])}</i></blockquote>"
                    )
                elif _RE_HEADER_DASH.match(line):
                    html_lines.append("<hr style='border:1px solid #5a4a2a;'>")
                elif _RE_LIST_ITEM.match(line):
                    content = _RE_LIST_SUB.sub("", line)
                    content = html.escape(content)
                    content = _RE_BOLD.sub(r"<b>\1</b>", content)
                    content = _RE_ITALIC.sub(r"<i>\1</i>", content)
                    content = _RE_INLINE_CODE.sub(
                        r'<code style="background:#1a1a1a;padding:0 2px;color:#e06c75">\1</code>',
                        content,
                    )
                    content = _RE_LINK.sub(lambda m: f'<a href="{__import__("html").unescape(m.group(2))}" style="color:#61afef">{m.group(1)}</a>', content)
                    html_lines.append(f"<li style='margin:1px 0'>{content}</li>")
                else:
                    line_text = line
                    line_text = html.escape(line_text)
                    line_text = _RE_BOLD.sub(r"<b>\1</b>", line_text)
                    line_text = _RE_ITALIC.sub(r"<i>\1</i>", line_text)
                    line_text = _RE_INLINE_CODE.sub(
                        r'<code style="background:#1a1a1a;padding:0 2px;color:#e06c75">\1</code>',
                        line_text,
                    )
                    line_text = _RE_LINK.sub(
                        lambda m: f'<a href="{__import__("html").unescape(m.group(2))}" style="color:#61afef">{m.group(1)}</a>',
                        line_text,
                    )
                    html_lines.append(
                        f"<p style='margin:1px 0'>{line_text}</p>" if line_text.strip() else "<br>"
                    )
            body = "\n".join(html_lines)

        return f"<html><body style='color:#c4ba9f;background:#0f0f0f;font-family:Verdana,sans-serif;font-size:11px;padding:6px'>{body}</body></html>"



    def clear_formatting(self):
        """Reset text formatting to base font with plain style."""
        self.sound_manager.play("clear")
        cursor = self.text_area.textCursor()

        clean_format = QTextCharFormat()
        clean_format.setFontStyleStrategy(QFont.StyleStrategy.NoAntialias | QFont.StyleStrategy.NoSubpixelAntialias)
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
        font = QFont(font_name, font_size)
        font.setStyleStrategy(
            QFont.StyleStrategy(
                int(QFont.StyleStrategy.NoAntialias.value)
                | int(QFont.StyleStrategy.NoSubpixelAntialias.value)
            )
        )
        clean_format.setFont(font)
        clean_format.setFontWeight(QFont.Weight.Normal)
        clean_format.setFontItalic(False)
        clean_format.setFontUnderline(False)
        clean_format.setFontStrikeOut(False)

        self.text_area.blockSignals(True)
        cursor.beginEditBlock()  # balance the endEditBlock() in finally
        try:
            if cursor.hasSelection():
                raw_text = cursor.selectedText().replace("\u2029", "\n")
                cursor.insertText(raw_text, clean_format)
            else:
                raw_text = self.text_area.toPlainText()
                self._set_plain_text_clean(self.text_area, raw_text)
                cursor = self.text_area.textCursor()
                cursor.select(QTextCursor.SelectionType.Document)
                cursor.setCharFormat(clean_format)
                cursor.clearSelection()
                self.text_area.setTextCursor(cursor)
        finally:
            cursor.endEditBlock()
            self.text_area.blockSignals(False)

        self.apply_font()
        self.mark_dirty()
        self.cache_current_text()
