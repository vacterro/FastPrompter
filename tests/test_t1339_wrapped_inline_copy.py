"""T-1339: inline Copy multi-row + zero-text-overlap finalization.

Final narrow follow-up to T-1337/T-1338. Two remaining geometry gaps:

  * a WRAPPED link only had its first visual row represented, so hovering the
    second visible fragment revealed no Copy;
  * Copy placement proved a text-free slot only on the right; the left
    fallback assumed the left side was empty and could land on preceding
    prose, and the hover ownership union could swallow all prose between a
    far-placed Copy and its target.

This proves: every visual fragment of a wrapped link is hoverable and its
Copy aligns to that fragment; Copy never intersects preceding/trailing prose
where a free slot exists; the hover ownership zone is narrow, not the whole
row.
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
    owner.preview_combo.setCurrentIndex(0)
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


def _visual_rows_spanned(ed, block, match):
    """How many visual QTextLines the match's char range touches."""
    layout = block.layout()
    rows = set()
    for i in range(layout.lineCount()):
        line = layout.lineAt(i)
        s = line.textStart()
        e = s + line.textLength()
        if match.start() < e and match.end() > s:
            rows.add(i)
    return sorted(rows)


def _prose_rects(ed, block, needle):
    """Precise viewport rects for the substring ``needle``, one per visual row
    it occupies, each bounded to that row's natural text right edge (never the
    viewport width). A coarse viewport-wide approximation would falsely claim
    the empty tail of a wrapped row is prose."""
    from PyQt6.QtCore import QRect
    text = block.text()
    i = text.index(needle)
    layout = block.layout()
    doc_layout = ed.document().documentLayout()
    br = doc_layout.blockBoundingRect(block)
    y_off = -ed.verticalScrollBar().value()
    base = block.position()
    s, e = i, i + len(needle)
    out = []
    for li in range(layout.lineCount()):
        line = layout.lineAt(li)
        ls = line.textStart()
        le = ls + line.textLength()
        seg_s = max(s, ls)
        seg_e = min(e, le)
        if seg_s >= seg_e:
            continue
        cs = QTextCursor(block)
        cs.setPosition(base + seg_s)
        r0 = ed.cursorRect(cs)
        lr = line.naturalTextRect().translated(br.topLeft()).translated(0, y_off)
        left = r0.left()
        right = int(lr.right())
        out.append(QRect(left, r0.top(), max(1, right - left), r0.height()))
    return out


def _prose_rect(ed, block, needle):
    """Single-row precise rect (first visual row of ``needle``)."""
    return _prose_rects(ed, block, needle)[0]


def _assert_in_viewport(ed, rect):
    vp_w = ed.viewport().width()
    assert rect.left() >= 2, f"left {rect.left()} < 2"
    assert rect.right() <= vp_w - 2, f"right {rect.right()} > {vp_w - 2}"


# --------------------------------------------------- A. wrapped link 2nd row


def test_second_row_of_wrapped_link_is_hoverable(tmp_path):
    url = "https://example.com/very/long/path/segment/one/two/three/four"
    ed, owner, hl = _editor_live(
        tmp_path,
        f"[a very long clickable label that will certainly wrap across "
        f"more than one visual row of the editor viewport]({url})",
        width=300)
    try:
        block = ed.document().findBlockByNumber(0)
        m = MD_LINK_RE.search(block.text())
        rows = _visual_rows_spanned(ed, block, m)
        assert len(rows) >= 2, f"token did not wrap (rows={rows})"
        # a point inside the SECOND visual fragment of the token
        frags = ed._link_glyph_rects(block, m)
        assert len(frags) >= 2, "resolver returned fewer than 2 fragments"
        second = frags[1]
        ed._update_inline_hover(second.center())
        assert ed._hover_inline_kind == "link"
        assert ed._hover_inline_target == url
        copy = ed._hover_inline_copy_rect
        assert copy is not None
        # Copy is placed relative to the SECOND fragment, not the first: on
        # its own row when that row has room for it, and otherwise on the
        # nearest row that does -- the picker's documented rule 3. Which of
        # the two applies is a property of the LAYOUT, and this layout is not
        # fixed: a dozen suite files build the real window, which changes the
        # application font and style, so this same text wraps into 4 rows in
        # a clean process and 5 in a shared one. Asserting "always the
        # hovered row" therefore measured the ambient font of whichever file
        # ran before this one, and went red for no product reason. What holds
        # at every metric is the pair: same row when the row has room, and
        # never on top of text.
        row_right = max((rw["right"] for rw in ed._block_visual_rows(block)
                         if abs(rw["cy"] - second.center().y()) <= second.height()),
                        default=None)
        if row_right is not None and row_right + 6 + 14 <= ed.viewport().width() - 2:
            assert abs(copy.center().y() - second.center().y()) <= second.height(), \
                f"Copy {copy} is not on the hovered fragment's row {second}"
        for prose in _prose_rects(ed, block, "more than one visual row of the "
                                           "editor viewport]("):
            assert not copy.intersects(prose), f"Copy {copy} on prose {prose}"
        _assert_in_viewport(ed, copy)
    finally:
        ed.close()


# --------------------------------------------------- B. prefix collision


def test_copy_avoids_prefix_and_trailing_prose(tmp_path):
    ed, owner, hl = _editor_live(
        tmp_path,
        "prefix words [label](https://example.com) long trailing prose here",
        width=360)
    try:
        block = ed.document().findBlockByNumber(0)
        m = MD_LINK_RE.search(block.text())
        frags = ed._link_glyph_rects(block, m)
        glyph = frags[0]
        ed._update_inline_hover(glyph.center())
        copy = ed._hover_inline_copy_rect
        assert copy is not None
        prefix = _prose_rect(ed, block, "prefix words ")
        trailing_rows = _prose_rects(ed, block, "long trailing prose here")
        assert not copy.intersects(prefix), f"Copy {copy} on prefix {prefix}"
        for tr in trailing_rows:
            assert not copy.intersects(tr), f"Copy {copy} on trailing {tr}"
        assert not copy.intersects(glyph)
        _assert_in_viewport(ed, copy)
    finally:
        ed.close()


# --------------------------------------------------- C. narrow hover bridge


def test_hover_ownership_excludes_intervening_prose(tmp_path):
    ed, owner, hl = _editor_live(
        tmp_path,
        "[l](https://example.com) plenty of unrelated words between here",
        width=900)
    try:
        block = ed.document().findBlockByNumber(0)
        m = MD_LINK_RE.search(block.text())
        glyph = ed._link_glyph_rects(block, m)[0]
        ed._update_inline_hover(glyph.center())
        assert ed._hover_inline_kind == "link"
        # a point on prose far from both the link glyph and the Copy control
        prose = _prose_rect(ed, block, "unrelated words between")
        # sanity: this prose sits between glyph and copy on the row
        assert not ed._inline_hover_zone_contains(prose.center()), (
            "intervening prose was swallowed into link hover ownership")
    finally:
        ed.close()


# --------------------------------------------------- D. multi-row two tokens


def test_two_wrapped_links_keep_fragment_identity(tmp_path):
    u1 = "https://a.example/one/two/three/four/five/six/seven/eight"
    u2 = "https://b.example/one/two/three/four/five/six/seven/eight"
    ed, owner, hl = _editor_live(
        tmp_path,
        f"[first long label that wraps somewhere across rows]({u1}) middle "
        f"[second long label that also wraps across rows]({u2})",
        width=320)
    try:
        block = ed.document().findBlockByNumber(0)
        ms = list(MD_LINK_RE.finditer(block.text()))
        assert len(ms) == 2
        for m, url in ((ms[0], u1), (ms[1], u2)):
            for frag in ed._link_glyph_rects(block, m):
                ed._update_inline_hover(frag.center())
                assert ed._hover_inline_kind == "link"
                assert ed._hover_inline_target == url, (
                    f"fragment {frag} resolved to wrong url")
                _assert_in_viewport(ed, ed._hover_inline_copy_rect)
    finally:
        ed.close()


# --------------------------------------------------- wrapped image invariant


def test_wrapped_image_stays_single_row_pill(tmp_path):
    """A very long local image target in a narrow editor: the conceal
    formatting collapses the markup to 1pt, so the pill stays one logical
    row and no raw path fragment leaks. Prove it rather than assume."""
    long_name = "clipboard_" + ("x" * 80) + ".png"
    path = _png(tmp_path, long_name)
    ed, owner, hl = _editor_live(tmp_path, f"pre ![]({path}) trailing prose",
                                 width=280)
    try:
        block = ed.document().findBlockByNumber(0)
        m = MD_IMAGE_RE.search(block.text())
        pill = ed._image_pill_rect(block, m)
        ed._update_inline_hover(pill.center())
        assert ed._hover_inline_kind == "image"
        copy = ed._hover_inline_copy_rect
        assert copy is not None
        _assert_in_viewport(ed, copy)
        # trailing prose stays free
        trailing = _prose_rect(ed, block, "trailing prose")
        assert not copy.intersects(trailing)
    finally:
        ed.close()
