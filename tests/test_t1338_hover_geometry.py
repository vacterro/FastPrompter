"""T-1338: inline hover Copy geometry finalization.

Continuation of T-1337. The hover-only Copy control exists and binds the
right target; this ticket proves the GEOMETRY is correct:

  * Copy never covers trailing/intervening prose where a free slot exists;
  * every returned Copy rect stays inside the viewport (2 <= left,
    right <= width-2), even when the target hugs the right edge;
  * wrapped targets keep Copy on the target's own visual row;
  * two tokens on one line stay independent;
  * scroll/resize/font changes never leave stale Copy geometry;
  * Live Preview with highlighter=None paints no pill over raw markup.

One shared visual-line-aware placement helper (_inline_copy_rect) serves
both links and images, so the two cannot diverge again.
"""

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

from PyQt6.QtGui import QColor, QImage, QTextCursor  # noqa: E402
from PyQt6.QtWidgets import QApplication, QComboBox  # noqa: E402

from fastprompter.ui.editor import MD_IMAGE_RE, MD_LINK_RE, VaultTextEdit  # noqa: E402
from fastprompter.ui.markdown_highlighter import MarkdownHighlighter  # noqa: E402

_APP = QApplication.instance() or QApplication([])


def _flush():
    for _ in range(8):
        _APP.processEvents()


class _Owner:
    highlighter = None
    _LARGE_DOC_THRESHOLD = 500_000
    _LARGE_DOC_BLOCK_THRESHOLD = 2000
    cb_ctrl_c = None

    def __init__(self, tmp_path):
        self.data = {"sound_ui": "False", "sound_typewriter": "False",
                     "auto_bullet": "False", "bullet_double_line": "False",
                     "ctrl_c_closes": "False", "image_paste_style": "pill",
                     "hover_line": "False"}
        self._current_lang = "EN"
        self._tmp = tmp_path
        self.preview_combo = QComboBox()
        self.preview_combo.addItem("Live Preview", "Live Preview")
        self.preview_combo.addItem("Source View", "Source View")

    def _silo_folder_dir(self, *_a):
        return str(self._tmp)

    def play_tick_sound(self):
        pass

    def themed_cursor(self, shape):
        from PyQt6.QtGui import QCursor
        return QCursor(shape)


def _png(tmp_path, name="shot.png"):
    img = QImage(24, 12, QImage.Format.Format_RGB32)
    img.fill(QColor("red"))
    p = tmp_path / name
    assert img.save(str(p))
    return str(p)


def _editor_live(tmp_path, text, width=900, height=600):
    owner = _Owner(tmp_path)
    owner.preview_combo.setCurrentIndex(0)  # Live Preview
    ed = VaultTextEdit(owner)
    ed.resize(width, height)
    ed.setPlainText(text)
    hl = MarkdownHighlighter(ed.document())
    hl.set_degraded(False)
    owner.highlighter = hl
    hl.rehighlight()
    ed.show()
    _flush()
    return ed, owner, hl


def _prose_rect(ed, block, needle):
    """Viewport rect covering the substring ``needle`` on ``block``."""
    text = block.text()
    i = text.index(needle)
    start = QTextCursor(block)
    start.setPosition(block.position() + i)
    end = QTextCursor(block)
    end.setPosition(block.position() + i + len(needle))
    r0, r1 = ed.cursorRect(start), ed.cursorRect(end)
    from PyQt6.QtCore import QRect
    if r1.top() != r0.top():
        return QRect(r0.left(), r0.top(),
                     max(4, ed.viewport().width() - r0.left()), r0.height())
    return QRect(r0.left(), r0.top(), max(4, r1.left() - r0.left()), r0.height())


def _assert_in_viewport(ed, rect):
    vp_w = ed.viewport().width()
    assert rect.left() >= 2, f"left {rect.left()} < 2"
    assert rect.right() <= vp_w - 2, f"right {rect.right()} > {vp_w - 2}"


# --------------------------------------------------- trailing prose (the bug)


def test_link_copy_does_not_cover_trailing_prose(tmp_path):
    ed, owner, hl = _editor_live(
        tmp_path,
        "Prefix [Label](https://example.com) trailing text after link")
    try:
        block = ed.document().findBlockByNumber(0)
        m = MD_LINK_RE.search(block.text())
        glyph = ed._link_glyph_rect(block, m)
        ed._update_inline_hover(glyph.center())
        assert ed._hover_inline_kind == "link"
        copy = ed._hover_inline_copy_rect
        assert copy is not None
        prose = _prose_rect(ed, block, "trailing text after link")
        assert not copy.intersects(prose), (
            f"Copy {copy} covers trailing prose {prose}")
        _assert_in_viewport(ed, copy)
    finally:
        ed.close()


def test_image_copy_does_not_cover_trailing_prose(tmp_path):
    path = _png(tmp_path)
    ed, owner, hl = _editor_live(
        tmp_path, f"pre ![]({path}) trailing prose after image")
    try:
        block = ed.document().findBlockByNumber(0)
        m = MD_IMAGE_RE.search(block.text())
        pill = ed._image_pill_rect(block, m)
        ed._update_inline_hover(pill.center())
        assert ed._hover_inline_kind == "image"
        copy = ed._hover_inline_copy_rect
        assert copy is not None
        prose = _prose_rect(ed, block, "trailing prose after image")
        assert not copy.intersects(prose), (
            f"Copy {copy} covers trailing prose {prose}")
        _assert_in_viewport(ed, copy)
    finally:
        ed.close()


# --------------------------------------------------- right-edge viewport clamp


def test_link_copy_stays_in_viewport_at_right_edge(tmp_path):
    # narrow viewport so the link fills most of the row and the natural
    # right-side slot would fall off-screen
    ed, owner, hl = _editor_live(
        tmp_path, "[verylonglabeltext](https://example.com/some/long/path)",
        width=220)
    try:
        block = ed.document().findBlockByNumber(0)
        m = MD_LINK_RE.search(block.text())
        glyph = ed._link_glyph_rect(block, m)
        ed._update_inline_hover(glyph.center())
        copy = ed._hover_inline_copy_rect
        assert copy is not None
        _assert_in_viewport(ed, copy)
    finally:
        ed.close()


def test_image_copy_stays_in_viewport_at_right_edge(tmp_path):
    path = _png(tmp_path, "a_reasonably_long_name.png")
    ed, owner, hl = _editor_live(tmp_path, f"![]({path})", width=200)
    try:
        block = ed.document().findBlockByNumber(0)
        m = MD_IMAGE_RE.search(block.text())
        pill = ed._image_pill_rect(block, m)
        ed._update_inline_hover(pill.center())
        copy = ed._hover_inline_copy_rect
        assert copy is not None
        _assert_in_viewport(ed, copy)
    finally:
        ed.close()


# --------------------------------------------------- two tokens on one line


def test_two_links_stay_independent(tmp_path):
    ed, owner, hl = _editor_live(
        tmp_path, "[one](https://a.example) text [two](https://b.example)")
    try:
        block = ed.document().findBlockByNumber(0)
        matches = list(MD_LINK_RE.finditer(block.text()))
        assert len(matches) == 2
        g0 = ed._link_glyph_rect(block, matches[0])
        g1 = ed._link_glyph_rect(block, matches[1])
        ed._update_inline_hover(g0.center())
        assert ed._hover_inline_target == "https://a.example"
        # hovering the second link re-targets entirely
        ed._update_inline_hover(g1.center())
        assert ed._hover_inline_target == "https://b.example"
        copy1 = ed._hover_inline_copy_rect
        assert copy1 is not None
        _assert_in_viewport(ed, copy1)
        # Copy for link two must not sit on link one's glyph
        assert not copy1.intersects(g0)
        # and hovering back re-targets link one, not stuck on two
        ed._update_inline_hover(g0.center())
        assert ed._hover_inline_target == "https://a.example"
    finally:
        ed.close()


def test_two_images_stay_independent(tmp_path):
    p1 = _png(tmp_path, "one.png")
    p2 = _png(tmp_path, "two.png")
    ed, owner, hl = _editor_live(tmp_path, f"![]({p1}) mid ![]({p2})")
    try:
        block = ed.document().findBlockByNumber(0)
        ms = list(MD_IMAGE_RE.finditer(block.text()))
        assert len(ms) == 2
        pill0 = ed._image_pill_rect(block, ms[0])
        pill1 = ed._image_pill_rect(block, ms[1])
        ed._update_inline_hover(pill0.center())
        t0 = ed._hover_inline_target
        assert os.path.normcase(t0) == os.path.normcase(os.path.realpath(p1))
        ed._update_inline_hover(pill1.center())
        assert os.path.normcase(ed._hover_inline_target) == os.path.normcase(
            os.path.realpath(p2))
        assert ed._hover_inline_target != t0
    finally:
        ed.close()


# --------------------------------------------------- wrapped visual rows


def test_wrapped_link_keeps_copy_on_target_row(tmp_path):
    # force wrapping: long label + long url in a narrow viewport
    ed, owner, hl = _editor_live(
        tmp_path,
        "[a very long clickable label that will wrap across two rows]"
        "(https://example.com/very/long/path/segment/one/two/three)",
        width=280)
    try:
        block = ed.document().findBlockByNumber(0)
        m = MD_LINK_RE.search(block.text())
        # hover the START of the token (its first visual row)
        start = QTextCursor(block)
        start.setPosition(block.position() + m.start())
        first_row = ed.cursorRect(start)
        ed._update_inline_hover(first_row.center())
        assert ed._hover_inline_kind == "link"
        copy = ed._hover_inline_copy_rect
        assert copy is not None
        # Copy sits on the hovered (first) visual row, not the block's last row
        assert abs(copy.center().y() - first_row.center().y()) <= first_row.height()
        _assert_in_viewport(ed, copy)
    finally:
        ed.close()


# --------------------------------------------------- scroll / resize / font


def test_scroll_recomputes_or_clears_copy(tmp_path):
    lines = ["[l](https://example.com)"] + [f"line {i}" for i in range(80)]
    ed, owner, hl = _editor_live(tmp_path, "\n".join(lines), height=200)
    try:
        block = ed.document().findBlockByNumber(0)
        m = MD_LINK_RE.search(block.text())
        glyph = ed._link_glyph_rect(block, m)
        ed._update_inline_hover(glyph.center())
        assert ed._hover_inline_kind == "link"
        sb = ed.verticalScrollBar()
        sb.setValue(sb.maximum())      # scroll the link out of view
        _flush()
        # the scroll hook re-resolves from the pointer; the link is gone, so
        # no stale Copy box may remain floating
        assert ed._hover_inline_kind is None or (
            ed._hover_inline_copy_rect is not None
            and 0 <= ed._hover_inline_copy_rect.top() <= ed.viewport().height())
    finally:
        ed.close()


def test_resize_narrower_keeps_copy_in_viewport(tmp_path):
    ed, owner, hl = _editor_live(
        tmp_path, "[label](https://example.com/path)")
    try:
        block = ed.document().findBlockByNumber(0)
        m = MD_LINK_RE.search(block.text())
        ed._update_inline_hover(ed._link_glyph_rect(block, m).center())
        assert ed._hover_inline_copy_rect is not None
        ed.resize(180, 600)
        _flush()
        ed._update_inline_hover(ed._link_glyph_rect(block, m).center())
        _assert_in_viewport(ed, ed._hover_inline_copy_rect)
    finally:
        ed.close()


def test_font_change_recomputes_geometry(tmp_path):
    ed, owner, hl = _editor_live(
        tmp_path, "[label](https://example.com) after")
    try:
        block = ed.document().findBlockByNumber(0)
        m = MD_LINK_RE.search(block.text())
        ed._update_inline_hover(ed._link_glyph_rect(block, m).center())
        first = ed._hover_inline_copy_rect
        assert first is not None
        f = ed.font()
        f.setPointSizeF(f.pointSizeF() * 2.0)
        ed.setFont(f)
        _flush()
        glyph2 = ed._link_glyph_rect(block, m)
        ed._update_inline_hover(glyph2.center())
        copy2 = ed._hover_inline_copy_rect
        assert copy2 is not None
        # geometry tracks the larger layout: taller row, control follows
        assert copy2.height() >= first.height()
        _assert_in_viewport(ed, copy2)
    finally:
        ed.close()


# --------------------------------------------------- strict pill eligibility


def test_live_preview_no_highlighter_paints_no_pill(tmp_path):
    """Live Preview but highlighter=None (transient lifecycle): raw markup is
    on screen, so no pill may be eligible -- the original hybrid bug must not
    return during a highlighter gap."""
    owner = _Owner(tmp_path)
    owner.preview_combo.setCurrentIndex(0)      # Live Preview
    owner.highlighter = None
    ed = VaultTextEdit(owner)
    ed.resize(900, 600)
    ed.setPlainText(f"![]({_png(tmp_path)})")
    ed.show()
    _flush()
    try:
        assert ed._image_pills_enabled() is False
    finally:
        ed.close()
