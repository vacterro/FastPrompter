"""T-1494: Smart Links -- the acceptance regression suite.

The scenarios of the mission, exercised against the REAL surfaces (Source
editor, Live Preview highlighter, Reading renderer) rather than against a
description of them.  The tokenizer-level rules live in
``test_link_tokens.py``; here a surface has to AGREE with them.

The red-before/green-after control is
``test_control_bare_url_at_position_zero_is_a_link``: before the shared
tokenizer existed, a bare URL at the very start of a line was not a link in
any surface.  It is the smallest statement of the newly identified
behaviour, so it comes first.
"""

from __future__ import annotations

import html
import inspect
import re

import pytest
from PyQt6.QtCore import QEvent, QPoint, QPointF, Qt
from PyQt6.QtGui import QDesktopServices, QMouseEvent
from PyQt6.QtWidgets import QApplication, QMenu

from fastprompter.core import rich_preview
from fastprompter.ui import editor as editor_module
from fastprompter.ui.editor import VaultTextEdit
from fastprompter.ui.rich_preview_view import RichPreviewView

# ---------------------------------------------------------------------------
# harness
# ---------------------------------------------------------------------------


class _FakeMain:
    """The little the editor actually asks the window for."""

    def __init__(self, mode="Live Preview", data=None):
        class _Combo:
            def __init__(self, value):
                self._value = value

            def currentData(self):
                return self._value

            def currentText(self):
                return self._value

        self.preview_combo = _Combo(mode)
        self.settings = None
        self.data = {"show_line_numbers": "False", "code_auto_gutter": "False",
                     "line_marks": "False"}
        if data:
            self.data.update(data)
        self.highlighter = None
        self._LARGE_DOC_THRESHOLD = 500_000
        self._current_lang = "EN"

    def play_tick_sound(self):
        pass


@pytest.fixture
def app():
    instance = QApplication.instance()
    if instance is None:
        instance = QApplication([])
    return instance


@pytest.fixture
def opened(monkeypatch):
    """Every URL the central router handed to the operating system."""
    calls = []

    def _open(url):
        calls.append(url)
        return True

    monkeypatch.setattr(QDesktopServices, "openUrl", _open)
    return calls


def _editor(mode="Live Preview", data=None, text="", width=700, height=400):
    """A laid-out editor -- geometry tests need a real viewport."""
    editor = VaultTextEdit(_FakeMain(mode, data))
    editor.resize(width, height)
    editor.show()
    QApplication.processEvents()
    editor.setPlainText(text)
    QApplication.processEvents()
    return editor


def _click(widget, pos, button=Qt.MouseButton.LeftButton,
           modifiers=Qt.KeyboardModifier.NoModifier, drag_to=None):
    start = QPointF(pos)
    widget.mousePressEvent(QMouseEvent(
        QMouseEvent.Type.MouseButtonPress, start, start, button, button, modifiers))
    end = QPointF(drag_to) if drag_to is not None else start
    if drag_to is not None:
        widget.mouseMoveEvent(QMouseEvent(
            QMouseEvent.Type.MouseMove, end, end, button, button, modifiers))
    widget.mouseReleaseEvent(QMouseEvent(
        QMouseEvent.Type.MouseButtonRelease, end, end, button, button, modifiers))


def _blocks(editor):
    """The document's blocks, in order."""
    block = editor.document().begin()
    out = []
    while block.isValid():
        out.append(block)
        block = block.next()
    return out


def _token(editor, index=0, block=None):
    """The n-th recognised link token of a block."""
    block = block if block is not None else editor.document().firstBlock()
    tokens = [t for t in editor._link_tokens(block) if t.kind != "image"]
    return tokens[index], block


def _rects(editor, token, block):
    rects = editor._link_glyph_rects(block, token.span)
    assert rects, "the token must have a viewport rect"
    return rects


def _hover_and_copy(editor, token, block):
    """Hover the token, then press the Copy control it revealed."""
    editor._update_inline_hover(_rects(editor, token, block)[0].center())
    button = editor._hover_inline_copy_rect
    assert button is not None, "hovering a link must reveal the Copy control"
    _click(editor, button.center())
    return button


# ---------------------------------------------------------------------------
# the control: a bare URL is a link, at position 0 and everywhere else
# ---------------------------------------------------------------------------


def test_control_bare_url_at_position_zero_is_a_link(app):
    """RED before the shared tokenizer, GREEN after it."""
    editor = _editor("Source View", text="https://example.com/a?b=1&c=2")
    token, _block = _token(editor)
    assert token.destination == "https://example.com/a?b=1&c=2"
    assert token.span == (0, len(token.destination))
    assert token.action == "web"


def test_control_two_consecutive_url_lines(app):
    editor = _editor("Source View",
                     text="https://one.example.com\nhttps://two.example.com")
    blocks = _blocks(editor)
    first = editor._link_tokens(blocks[0])
    second = editor._link_tokens(blocks[1])
    assert [t.destination for t in first] == ["https://one.example.com"]
    assert [t.destination for t in second] == ["https://two.example.com"]


def test_control_several_links_in_one_paragraph(app):
    editor = _editor("Source View",
                     text="a https://one.example.com b https://two.example.com c")
    tokens = editor._link_tokens(editor.document().firstBlock())
    assert [t.destination for t in tokens] == [
        "https://one.example.com", "https://two.example.com"]


def test_control_markdown_link_with_label(app):
    editor = _editor("Source View", text="[My Project](https://example.com?a=1&b=2)")
    token, _block = _token(editor)
    assert token.kind == "markdown"
    assert token.label == "My Project"
    assert token.destination == "https://example.com?a=1&b=2"


def test_control_local_screenshot_file_url(app):
    editor = _editor("Source View", text="[Screenshot](file:///M:/shots/a.png)")
    token, _block = _token(editor)
    assert token.action == "local_file"
    assert token.destination == "file:///M:/shots/a.png"


def test_control_query_parameters_keep_their_ampersand(app):
    editor = _editor("Source View", text="https://example.com?a=1&b=2")
    token, _block = _token(editor)
    assert token.destination == "https://example.com?a=1&b=2"
    assert "&amp;" not in token.destination


def test_control_url_with_balanced_parentheses(app):
    editor = _editor("Source View", text="https://example.com/a_(b) end")
    token, _block = _token(editor)
    assert token.destination == "https://example.com/a_(b)"


def test_control_terminal_punctuation_is_not_part_of_the_url(app):
    editor = _editor("Source View", text="see https://example.com/path.")
    token, _block = _token(editor)
    assert token.destination == "https://example.com/path"


def test_control_code_fence_url_stays_plain(app):
    editor = _editor("Source View", text="```\nhttps://example.com\n```")
    blocks = _blocks(editor)
    assert editor._link_tokens(blocks[1]) == []


def test_control_inline_code_url_stays_plain(app):
    editor = _editor("Source View", text="`https://example.com`")
    assert editor._link_tokens(editor.document().firstBlock()) == []


def test_control_links_in_a_list_item_and_a_quote(app):
    editor = _editor("Source View",
                     text="- https://example.com/list\n> https://example.com/quote")
    blocks = _blocks(editor)
    assert editor._link_tokens(blocks[0])[0].destination == \
        "https://example.com/list"
    assert editor._link_tokens(blocks[1])[0].destination == \
        "https://example.com/quote"


def test_control_a_bbcode_link_is_recognised(app):
    editor = _editor("Source View",
                     text="[url=https://example.com/bb]click[/url]")
    token, _block = _token(editor)
    assert token.kind == "bbcode"
    assert token.destination == "https://example.com/bb"


# ---------------------------------------------------------------------------
# hover Copy
# ---------------------------------------------------------------------------


def test_hover_copy_on_a_bare_url_copies_the_exact_destination(app):
    editor = _editor("Live Preview", text="https://example.com?a=1&b=2")
    token, block = _token(editor)
    _hover_and_copy(editor, token, block)
    assert QApplication.clipboard().text() == "https://example.com?a=1&b=2"


def test_hover_copy_on_a_markdown_link_copies_the_destination(app):
    editor = _editor("Live Preview", text="[My Project](https://example.com?a=1&b=2)")
    token, block = _token(editor)
    _hover_and_copy(editor, token, block)
    assert QApplication.clipboard().text() == "https://example.com?a=1&b=2"


def test_hover_copy_on_a_www_host_copies_the_destination(app):
    editor = _editor("Live Preview", text="www.example.com/page")
    token, block = _token(editor)
    assert token.normalized == "https://www.example.com/page"
    _hover_and_copy(editor, token, block)
    assert QApplication.clipboard().text() == "www.example.com/page"


def test_hover_copy_on_a_mailto_copies_the_address(app):
    editor = _editor("Live Preview", text="write to mailto:mail@example.com now")
    token, block = _token(editor)
    assert token.action == "email"
    _hover_and_copy(editor, token, block)
    assert QApplication.clipboard().text() == "mailto:mail@example.com"


def test_hover_copy_keeps_the_fragment(app):
    editor = _editor("Live Preview", text="https://example.com/p#section-2")
    token, block = _token(editor)
    _hover_and_copy(editor, token, block)
    assert QApplication.clipboard().text() == "https://example.com/p#section-2"


def test_copy_never_opens_the_link(app, opened):
    editor = _editor("Live Preview", text="https://example.com/path")
    token, block = _token(editor)
    _hover_and_copy(editor, token, block)
    assert opened == [], "the Copy control must never launch a URL"


def test_copy_does_not_touch_the_document_or_the_undo_stack(app):
    editor = _editor("Live Preview", text="https://example.com/path")
    token, block = _token(editor)
    before_text = editor.toPlainText()
    before_undo = editor.document().availableUndoSteps()
    _hover_and_copy(editor, token, block)
    assert editor.toPlainText() == before_text
    assert editor.document().availableUndoSteps() == before_undo


def test_copy_markdown_link_action_writes_the_markdown_form(app):
    editor = _editor("Source View", text="[My Project](https://example.com?a=1&b=2)")
    token, _block = _token(editor)
    editor.copy_markdown_link_at(token)
    assert QApplication.clipboard().text() == \
        "[My Project](https://example.com?a=1&b=2)"


def test_copy_link_text_action_writes_the_visible_text(app):
    editor = _editor("Source View", text="[My Project](https://example.com?a=1&b=2)")
    token, _block = _token(editor)
    editor.copy_link_text_at(token)
    assert QApplication.clipboard().text() == "My Project"


def test_the_hover_copy_control_is_cleared_when_the_pointer_leaves(app):
    editor = _editor("Live Preview", text="https://example.com/path")
    token, block = _token(editor)
    _hover_and_copy(editor, token, block)
    assert editor._hover_inline_copy_rect is not None
    editor.leaveEvent(QEvent(QEvent.Type.Leave))
    assert editor._hover_inline_copy_rect is None


def test_the_hover_copy_switch_switches_the_control_off(app):
    editor = _editor("Live Preview",
                     data={"smart_links_copy_hover": "False"},
                     text="https://example.com/path")
    token, block = _token(editor)
    editor._update_inline_hover(_rects(editor, token, block)[0].center())
    assert editor._hover_inline_copy_rect is None


def test_the_master_switch_switches_the_whole_feature_off(app, opened):
    editor = _editor("Source View",
                     data={"smart_links_enabled": "False",
                           "source_link_click": "Single-click"},
                     text="https://example.com/path")
    token, block = _token(editor)
    editor._update_inline_hover(_rects(editor, token, block)[0].center())
    assert editor._hover_inline_copy_rect is None
    _click(editor, _rects(editor, token, block)[0].center())
    assert opened == []


# ---------------------------------------------------------------------------
# geometry
# ---------------------------------------------------------------------------


def test_a_wrapped_url_is_hoverable_on_every_row(app):
    editor = _editor("Live Preview", text="https://example.com/" + "a" * 400)
    token, block = _token(editor)
    rects = _rects(editor, token, block)
    assert len(rects) >= 2, "a wrapped URL needs one rect per visual row"
    for rect in rects:
        assert editor._link_token_at(rect.center()) is not None


def test_the_copy_control_stays_inside_the_viewport(app):
    editor = _editor("Live Preview", text="https://example.com/path")
    token, block = _token(editor)
    button = _hover_and_copy(editor, token, block)
    assert editor.viewport().rect().contains(button)


def test_the_hover_copy_survives_a_resize_and_a_theme_change(app):
    """A resize moves the glyphs, a theme change re-lays the document out."""
    from fastprompter.ui.markdown_highlighter import MarkdownHighlighter
    editor = _editor("Live Preview", text="https://example.com/path")
    highlighter = MarkdownHighlighter()
    highlighter.setDocument(editor.document())
    QApplication.processEvents()
    token, block = _token(editor)

    editor.resize(420, 260)
    QApplication.processEvents()
    editor._update_inline_hover(_rects(editor, token, block)[0].center())
    button = editor._hover_inline_copy_rect
    assert button is not None
    assert editor.viewport().rect().contains(button)

    highlighter.update_theme({})
    QApplication.processEvents()
    editor._update_inline_hover(_rects(editor, token, block)[0].center())
    button = editor._hover_inline_copy_rect
    assert button is not None
    assert editor.viewport().rect().contains(button)


def test_no_stale_hover_after_a_document_edit(app):
    editor = _editor("Live Preview", text="https://example.com/path")
    token, block = _token(editor)
    _hover_and_copy(editor, token, block)
    editor.setPlainText("plain text now")
    QApplication.processEvents()
    assert editor._link_tokens(editor.document().firstBlock()) == []
    editor._update_inline_hover(QPoint(5, 5))
    assert editor._hover_inline_copy_rect is None


# ---------------------------------------------------------------------------
# Source view navigation
# ---------------------------------------------------------------------------


def test_single_click_opens_the_link_exactly_once(app, opened):
    editor = _editor("Source View", {"source_link_click": "Single-click"},
                     "https://example.com/path")
    token, block = _token(editor)
    _click(editor, _rects(editor, token, block)[0].center())
    assert len(opened) == 1
    assert opened[0].toString() == "https://example.com/path"


def test_drag_selection_never_opens_a_link(app, opened):
    editor = _editor("Source View", {"source_link_click": "Single-click"},
                     "https://example.com/path and some prose after it")
    token, block = _token(editor)
    start = _rects(editor, token, block)[0].center()
    _click(editor, start, drag_to=start + QPoint(150, 0))
    assert opened == [], "a drag that starts on a link must only select text"
    assert editor.textCursor().hasSelection()


def test_live_preview_a_plain_click_opens_the_link(app, opened):
    """Live Preview opens on a plain click -- the anchor format of the
    highlighter is invisible to the cursor, so the token is the authority."""
    editor = _editor("Live Preview", text="https://example.com/path")
    token, block = _token(editor)
    _click(editor, _rects(editor, token, block)[0].center())
    assert len(opened) == 1
    assert opened[0].toString() == "https://example.com/path"


def test_live_preview_a_drag_never_opens_a_link(app, opened):
    editor = _editor("Live Preview",
                     text="https://example.com/path and some prose after it")
    token, block = _token(editor)
    start = _rects(editor, token, block)[0].center()
    _click(editor, start, drag_to=start + QPoint(150, 0))
    assert opened == []


def test_live_preview_alt_click_does_not_open_the_link(app, opened):
    """Alt+click is the caret gesture, so it never opens anything."""
    editor = _editor("Live Preview", text="https://example.com/path")
    token, block = _token(editor)
    _click(editor, _rects(editor, token, block)[0].center(),
           modifiers=Qt.KeyboardModifier.AltModifier)
    assert opened == []


def test_ctrl_click_mode_ignores_a_plain_click(app, opened):
    editor = _editor("Source View", {"source_link_click": "Ctrl+Click"},
                     "https://example.com/path")
    token, block = _token(editor)
    _click(editor, _rects(editor, token, block)[0].center())
    assert opened == []
    _click(editor, _rects(editor, token, block)[0].center(),
           modifiers=Qt.KeyboardModifier.ControlModifier)
    assert len(opened) == 1


def test_source_click_preference_is_read_from_the_settings_authority(app):
    editor = _editor("Source View", {"source_link_click": "Ctrl+Click"})
    assert editor._source_link_click_mode() == "Ctrl+Click"
    editor.main_win.data["source_link_click"] = "Single-click"
    assert editor._source_link_click_mode() == "Single-click"


def test_the_settings_builder_writes_the_same_preference_key():
    """The two halves of the preference must not drift apart."""
    from fastprompter.ui import settings_builder

    source = inspect.getsource(settings_builder)
    assert '"source_link_click"' in source
    assert "Single-click" in source and "Ctrl+Click" in source
    for key in ("smart_links_enabled", "smart_links_copy_hover",
                "smart_links_tooltip", "smart_links_feedback"):
        assert f'"{key}"' in source


def test_source_caret_editing_stays_usable(app, opened):
    """Alt+click puts the caret inside a link and opens nothing."""
    editor = _editor("Source View", {"source_link_click": "Single-click"},
                     "https://example.com/path")
    token, block = _token(editor)
    _click(editor, _rects(editor, token, block)[0].center(),
           modifiers=Qt.KeyboardModifier.AltModifier)
    assert opened == []
    cursor = editor.textCursor()
    cursor.setPosition(block.position() + 4)
    editor.setTextCursor(cursor)
    editor.insertPlainText("X")
    assert editor.toPlainText().startswith("httpX")


def test_an_invalid_scheme_is_never_opened(app, opened):
    editor = _editor("Source View", {"source_link_click": "Single-click"},
                     "[click](javascript:alert(1))")
    token, block = _token(editor)
    assert token.is_supported is False
    _click(editor, _rects(editor, token, block)[0].center())
    assert opened == []


def test_a_local_executable_asks_before_the_shell_sees_it(app, opened,
                                                          monkeypatch):
    from PyQt6.QtWidgets import QMessageBox

    monkeypatch.setattr(
        QMessageBox, "warning",
        staticmethod(lambda *a, **k: QMessageBox.StandardButton.No))
    editor = _editor("Source View", {"source_link_click": "Single-click"},
                     "[run](file:///C:/Windows/System32/cmd.exe)")
    token, block = _token(editor)
    _click(editor, _rects(editor, token, block)[0].center())
    assert opened == [], "a local file needs an explicit confirmation"


def test_a_missing_local_file_does_not_reach_the_shell(app, opened, monkeypatch):
    from PyQt6.QtWidgets import QMessageBox

    monkeypatch.setattr(
        QMessageBox, "warning",
        staticmethod(lambda *a, **k: QMessageBox.StandardButton.No))
    editor = _editor("Source View", {"source_link_click": "Single-click"},
                     "[gone](file:///C:/definitely/missing.txt)")
    token, block = _token(editor)
    _click(editor, _rects(editor, token, block)[0].center())
    assert opened == []


# ---------------------------------------------------------------------------
# context menu
# ---------------------------------------------------------------------------


def _menu_labels(editor, token, block):
    menu = QMenu()
    editor._add_link_menu(menu, token, block, "EN")
    return menu, [action.text() for action in menu.actions()]


def test_the_context_menu_offers_the_link_actions(app):
    editor = _editor("Source View", text="[My Project](https://example.com?a=1&b=2)")
    token, block = _token(editor)
    _menu, labels = _menu_labels(editor, token, block)
    assert "Open Link" in labels
    assert "Copy Link" in labels
    assert "Copy Markdown Link" in labels
    assert "Copy Link Text" in labels


def test_the_context_menu_copy_link_copies_the_destination(app):
    editor = _editor("Source View", text="[My Project](https://example.com?a=1&b=2)")
    token, block = _token(editor)
    menu, _labels = _menu_labels(editor, token, block)
    for action in menu.actions():
        if action.text() == "Copy Link":
            action.trigger()
            break
    else:
        pytest.fail("the menu has no Copy Link action")
    assert QApplication.clipboard().text() == "https://example.com?a=1&b=2"


def test_the_context_menu_open_link_uses_the_central_router(app, opened):
    editor = _editor("Source View", text="[My Project](https://example.com?a=1&b=2)")
    token, block = _token(editor)
    menu, _labels = _menu_labels(editor, token, block)
    for action in menu.actions():
        if action.text() == "Open Link":
            action.trigger()
            break
    else:
        pytest.fail("the menu has no Open Link action")
    assert len(opened) == 1
    assert opened[0].toString() == "https://example.com?a=1&b=2"


def test_the_context_menu_offers_the_folder_action_for_a_local_file(app):
    editor = _editor("Source View", text="[shot](file:///M:/shots/a.png)")
    token, block = _token(editor)
    _menu, labels = _menu_labels(editor, token, block)
    assert "Open Containing Folder" in labels


def test_a_local_file_link_gets_one_folder_action_only(app):
    """The link menu and the older anchor menu must not BOTH offer it.

    A local file link can also be an anchor, and the older anchor-based
    "open the folder" action fires for anchors.  Two identical entries in
    one menu is noise; the link menu owns the translated one and the older
    copy stands down.
    """
    editor = _editor("Source View", text="[shot](file:///M:/shots/a.png)")
    token, block = _token(editor)
    menu = QMenu()
    offered = editor._add_link_menu(menu, token, block, "EN")
    # the link menu covered the folder, so the older action must stand down
    assert offered is True
    folder_actions = [a.text() for a in menu.actions()
                      if "folder" in a.text().lower()]
    assert len(folder_actions) == 1


def test_the_context_menu_offers_edit_only_for_a_markdown_link(app):
    editor = _editor("Source View", text="[label](https://example.com)")
    token, block = _token(editor)
    _menu, labels = _menu_labels(editor, token, block)
    assert any(label.startswith("Edit Link") for label in labels)

    editor2 = _editor("Source View", text="https://example.com/plain")
    token2, block2 = _token(editor2)
    _menu2, labels2 = _menu_labels(editor2, token2, block2)
    assert not any(label.startswith("Edit Link") for label in labels2)


# ---------------------------------------------------------------------------
# Live Preview and Reading agree with Source
# ---------------------------------------------------------------------------


def _live_preview_anchors(text):
    """The anchor formats Live Preview actually applies to ``text``.

    The highlighter needs a document with a real layout -- a bare
    ``QTextDocument`` never lays out, so nothing is ever highlighted.
    """
    from fastprompter.ui.markdown_highlighter import MarkdownHighlighter

    editor = _editor("Live Preview", text=text)
    highlighter = MarkdownHighlighter()
    highlighter.setDocument(editor.document())
    QApplication.processEvents()
    formats = editor.document().firstBlock().layout().formats()
    return [(rng.start, rng.length, rng.format.isAnchor(),
             rng.format.anchorHref()) for rng in formats]


def test_live_preview_anchors_the_same_urls_the_source_editor_recognises(app):
    anchors = [f for f in _live_preview_anchors("see https://example.com/a?b=1 now")
               if f[2]]
    assert anchors, "the bare URL must be an anchor in Live Preview"
    assert anchors[0][3] == "https://example.com/a?b=1"


def test_live_preview_does_not_anchor_an_invalid_scheme(app):
    anchors = [f for f in _live_preview_anchors("see javascript:alert(1) now")
               if f[2]]
    assert not anchors, "an unsupported scheme must never become a click target"


def test_reading_mode_renders_a_bare_url_as_a_link(app):
    doc = rich_preview.render("see https://example.com/page now")
    match = re.search(r'<a href="([^"]+)">', doc.plain_body)
    assert match, doc.plain_body
    assert html.unescape(match.group(1)) == "https://example.com/page"


def test_reading_mode_keeps_the_query_string_intact(app):
    doc = rich_preview.render("see https://example.com?a=1&b=2 now")
    match = re.search(r'<a href="([^"]+)">', doc.plain_body)
    assert match, doc.plain_body
    # the HTML escapes the ampersand ONCE -- the reader sees the real URL
    assert match.group(1) == "https://example.com?a=1&amp;b=2"
    assert html.unescape(match.group(1)) == "https://example.com?a=1&b=2"


def test_reading_mode_copy_control_copies_the_href(app):
    view = RichPreviewView()
    view.resize(500, 300)
    view.show()
    QApplication.processEvents()
    view.set_rendered_document(
        rich_preview.render("see https://example.com?a=1&b=2 now"))
    QApplication.processEvents()
    blocks = [w for w in view._blocks if w.__class__.__name__ == "_HtmlBlock"]
    assert blocks, "the document must produce an HTML block"
    block = blocks[0]
    href = ""
    position = None
    for y in range(0, block.viewport().height(), 3):
        for x in range(0, block.viewport().width(), 3):
            found = block.anchorAt(QPoint(x, y))
            if found:
                href = found
                position = QPoint(x, y)
                break
        if href:
            break
    assert href == "https://example.com?a=1&b=2"
    block._update_copy_control(position)
    assert block._copy_button.isVisible()
    block._copy_hovered_link()
    assert QApplication.clipboard().text() == "https://example.com?a=1&b=2"
    view.deleteLater()
    QApplication.processEvents()


def test_reading_mode_honours_the_smart_links_switch(app):
    view = RichPreviewView()
    view.smart_links_enabled = False
    view.resize(500, 300)
    view.show()
    QApplication.processEvents()
    view.set_rendered_document(
        rich_preview.render("see https://example.com/page now"))
    QApplication.processEvents()
    block = [w for w in view._blocks if w.__class__.__name__ == "_HtmlBlock"][0]
    block._update_copy_control(QPoint(2, 2))
    assert not block._copy_button.isVisible()
    view.deleteLater()
    QApplication.processEvents()


# ---------------------------------------------------------------------------
# performance
# ---------------------------------------------------------------------------


def test_token_detection_is_cached_per_block(app, monkeypatch):
    editor = _editor("Source View",
                     text="\n".join(f"line {i}" for i in range(500)))
    block = editor.document().findBlockByNumber(10)
    calls = []
    original = editor_module.tokenize_block

    def counting(text, **kwargs):
        calls.append(text)
        return original(text, **kwargs)

    monkeypatch.setattr(editor_module, "tokenize_block", counting)
    editor._link_tokens(block)
    first = len(calls)
    editor._link_tokens(block)
    assert len(calls) == first, "a cached block must not be tokenized again"


def test_an_edit_drops_the_token_cache(app):
    editor = _editor("Source View", text="https://example.com/path")
    block = editor.document().firstBlock()
    editor._link_tokens(block)
    assert editor._link_token_cache
    editor.setPlainText("https://example.com/other")
    assert editor._link_token_cache == {}


def test_a_large_document_stays_usable(app):
    editor = _editor("Source View",
                     text="\n".join(f"https://example.com/{i}" for i in range(2000)))
    block = editor.document().findBlockByNumber(1500)
    tokens = editor._link_tokens(block)
    assert len(tokens) == 1
    assert tokens[0].destination == "https://example.com/1500"
