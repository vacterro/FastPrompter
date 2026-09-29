"""T-1349: inline hover Copy reachability, temporal grace, vertical safety.

The defect under test. A Copy placed far from its token (a row tail, a
neighbouring row, an overlay) is spatially disconnected from it on purpose --
T-1338 forbade the giant bounding-union ownership region. But the
consequence was that the pointer had to cross a dead pixel gap to reach a
control that was plainly on screen, and the control was killed on the first
pixel of that gap. T-1349 bridges the gap in TIME, not in space, and repairs
the vertical placement that used to leave the viewport entirely.

Matrix:
  A adjacent Copy            -- no grace needed; the narrow bridge suffices
  B far Copy through a gap   -- alive and actionable within the grace
  C grace expiry             -- unrelated movement cannot hold it forever
  D new token wins           -- a real token always beats stale grace
  E bottom viewport          -- fully inside on BOTH axes
  F top viewport             -- same invariant at the top edge
  G next-block collision     -- the fallback may not cover block 1 prose
  H scroll during grace      -- stale geometry stops being authoritative
  I leave during grace       -- timer cancelled, control cleared
  J destruction during grace -- no callback into a dead widget
  K document mutation        -- a deleted token cannot be copied
  L preview switch           -- a re-rendered view drops the control
"""

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

from PyQt6 import sip  # noqa: E402
from PyQt6.QtCore import QEvent, QPoint, QRect  # noqa: E402
from PyQt6.QtGui import QTextCursor  # noqa: E402
from PyQt6.QtTest import QTest  # noqa: E402
from PyQt6.QtWidgets import QApplication, QComboBox  # noqa: E402

from fastprompter.ui.editor import (  # noqa: E402
    INLINE_HOVER_GRACE_MS,
    MD_LINK_RE,
    VaultTextEdit,
)
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
        self.data = {
            "sound_ui": "False",
            "sound_typewriter": "False",
            "auto_bullet": "False",
            "bullet_double_line": "False",
            "ctrl_c_closes": "False",
            "image_paste_style": "pill",
            "hover_line": "False",
        }
        self._current_lang = "EN"
        self._tmp = tmp_path
        self.preview_combo = QComboBox()
        self.preview_combo.addItem("Live Preview", "Live Preview")
        self.preview_combo.addItem("Source View", "Source View")

    def _silo_folder_dir(self, *_a):
        return str(self._tmp)

    def play_tick_sound(self):
        pass

    def capture_silo_state(self):
        pass

    def mark_dirty(self, *_a):
        pass

    def themed_cursor(self, shape):
        from PyQt6.QtGui import QCursor
        return QCursor(shape)


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


def _first_link_frag(ed, block_number=0):
    """(block, match, first visual fragment) for a link in one block."""
    block = ed.document().findBlockByNumber(block_number)
    m = MD_LINK_RE.search(block.text())
    assert m is not None, f"no link in block {block_number}"
    return block, m, ed._link_glyph_rects(block, m)[0]


def _assert_inside_viewport(ed, rect, what):
    vp = ed.viewport().rect()
    assert rect.left() >= 2, f"{what}: left {rect.left()} < 2"
    assert rect.right() <= vp.width() - 2, \
        f"{what}: right {rect.right()} > {vp.width() - 2}"
    assert rect.top() >= 2, f"{what}: top {rect.top()} < 2"
    assert rect.bottom() <= vp.height() - 2, \
        f"{what}: bottom {rect.bottom()} > {vp.height() - 2}"


def _premium_slots(ed, block, target):
    """The slots the placement authority tries BEFORE its fallbacks, kept
    only when they are legal under the same two rules it uses.

    Exists so the hard-placement tests can PROVE they really are forced onto
    the fallback: a test that accidentally picked an easy adjacent slot would
    assert nothing about vertical safety.
    """
    size = max(14, target.height() - 2)
    top = target.top() + (target.height() - size) // 2
    vp_w = ed.viewport().width()
    occupied = ed._row_text_extents(block, target, target)
    cands = [QRect(target.right() + 6, top, size, size),
             QRect(target.left() - 6 - size, top, size, size)]
    for row in ed._block_visual_rows(block):
        cands.append(QRect(row["right"] + 6,
                           row["top"] + (row["height"] - size) // 2,
                           size, size))
    return [c for c in cands
            if c.left() >= 2 and c.right() <= vp_w - 2
            and not any(c.intersects(o) for o in occupied)]


def _force_hard_placement(ed, block_number=0, size=14):
    """Narrow the editor until the link's row is FULL to the right edge.

    The hard-placement tests only mean something when no adjacent or row-tail
    slot can exist. Whether one is free depends on how wide the raw markdown
    renders, which depends on whatever font the rest of the suite left
    installed -- so the width is MEASURED, never hardcoded. A row that fills
    to the edge is the font-independent way to force the fallback.
    """
    for _ in range(8):
        block = ed.document().findBlockByNumber(block_number)
        m = MD_LINK_RE.search(block.text())
        assert m is not None, f"no link in block {block_number}"
        frags = ed._link_glyph_rects(block, m)
        frag = frags[0]
        # a WRAPPED link already fills row 0 to the wrap point: forced
        if len(frags) > 1 or frag.right() + 2 + size + 6 > ed.viewport().width() - 2:
            return block, m, frag
        ed.resize(frag.right() + 2 + size + 6 + 3, ed.height())
        _flush()
    block, m, frag = _first_link_frag(ed, block_number)
    assert not _premium_slots(ed, block, frag), \
        "could not force a hard placement at any width"
    return block, m, frag


def _row_text_rects(ed, block):
    """Exact per-row visible text rects (QTextLayout naturalTextRect)."""
    return [QRect(r["left"], r["top"], max(0, r["right"] - r["left"]), r["height"])
            for r in ed._block_visual_rows(block) if r["right"] - r["left"] > 1]


def _neutral_point(ed, rects, height):
    """A viewport point owned by no token, no Copy, and no ownership zone."""
    for y in (height - 10, height - 30, 10):
        for x in (5, 15, ed.viewport().width() - 5):
            pt = QPoint(x, y)
            if ed._inline_token_at(pt) is None:
                assert not ed._inline_hover_zone_contains(pt)
                assert not any(r.adjusted(-8, -8, 8, 8).contains(pt) for r in rects)
                return pt
    raise AssertionError("no neutral point available")


# --------------------------------------------------- A. adjacent Copy


def test_adjacent_copy_needs_no_grace(tmp_path):
    """A lone link owns its whole row, so Copy lands immediately to its right
    and the T-1338 narrow bridge alone keeps the hover alive -- the grace
    timer must stay idle, or grace has become the normal path."""
    url = "https://example.com/adjacent"
    ed, owner, hl = _editor_live(tmp_path, f"[a]({url})")
    try:
        block, m, frag = _first_link_frag(ed)
        ed._update_inline_hover(frag.center())
        cr = ed._hover_inline_copy_rect
        assert cr is not None
        assert cr.top() < frag.bottom() and cr.bottom() > frag.top(), \
            f"Copy {cr} is not on the target's row {frag}"
        assert cr.left() - frag.right() <= 16, \
            f"Copy {cr} is not adjacent to {frag}"

        # step into the Copy's own padded zone: alive, and NO grace needed
        pt = cr.adjusted(2, 2, -2, -2).center()
        ed._update_inline_hover(pt)
        assert ed._hover_inline_kind == "link"
        assert not ed._inline_hover_grace_timer.isActive()
        hit = ed._link_copy_at(pt)
        assert hit is not None and hit[0] == url
    finally:
        ed.close()


# --------------------------------------------------- B. far Copy through gap


def test_far_copy_reachability_through_gap(tmp_path):
    """RED regression: far Copy reached across an intermediate gap.

    Layout:
      Block 0 has left prefix words, then [target link], then trailing words.
      Right and left of the link on its row are occupied, so Copy can only be
      placed away from the token. Moving through a point owned by neither must
      not kill the hover if the pointer reaches Copy within the grace.
    """
    url = "https://example.com/target"
    text = (
        f"prefix word [a]({url}) trailing words occupying row zero\n"
        f"second line is a short tail"
    )
    ed, owner, hl = _editor_live(tmp_path, text, width=120, height=200)
    try:
        block, m, target_frag = _first_link_frag(ed)

        ed._update_inline_hover(target_frag.center())
        assert ed._hover_inline_kind == "link"
        assert ed._hover_inline_target == url
        copy_rect = ed._hover_inline_copy_rect
        assert copy_rect is not None
        _assert_inside_viewport(ed, copy_rect, "far Copy")

        # the Copy really is far: a spatial bridge is impossible
        dist = (copy_rect.center() - target_frag.center()).manhattanLength()
        assert dist > 16, f"Copy rect {copy_rect} is adjacent to {target_frag}"

        gap_pt = _neutral_point(ed, (target_frag, copy_rect), 200)
        ed._update_inline_hover(gap_pt)
        assert ed._inline_hover_grace_timer.isActive()

        # hover survived the dead zone and stays actionable
        assert ed._hover_inline_copy_rect is not None, \
            "Copy rect was cleared at intermediate gap!"
        assert ed._hover_inline_target == url

        ed._update_inline_hover(copy_rect.center())
        assert not ed._inline_hover_grace_timer.isActive()
        assert ed._hover_inline_copy_rect is not None
        assert ed._hover_inline_target == url

        hit = ed._link_copy_at(copy_rect.center())
        assert hit is not None
        assert hit[0] == url
    finally:
        ed.close()


# --------------------------------------------------- C. grace expiry


def test_grace_expiry_clears_hover(tmp_path):
    """Grace is bounded in wall-clock time, not in movement: unrelated mouse
    motion elsewhere must not extend it, and the real timer must fire."""
    url = "https://example.com/expire"
    ed, owner, hl = _editor_live(tmp_path, f"[a]({url})")
    try:
        _block, _m, frag = _first_link_frag(ed)
        ed._update_inline_hover(frag.center())
        copy_rect = ed._hover_inline_copy_rect
        gap_pt = _neutral_point(ed, (frag, copy_rect), 600)
        ed._update_inline_hover(gap_pt)
        assert ed._hover_inline_kind == "link"
        assert ed._inline_hover_grace_timer.isActive()

        # noise in unrelated places does not re-arm anything
        for _ in range(20):
            ed._update_inline_hover(_neutral_point(ed, (), 600))
        assert ed._inline_hover_grace_timer.interval() == INLINE_HOVER_GRACE_MS

        QTest.qWait(INLINE_HOVER_GRACE_MS + 150)
        _flush()
        assert ed._hover_inline_kind is None
        assert ed._hover_inline_copy_rect is None
        assert ed._link_copy_at(copy_rect.center()) is None
    finally:
        ed.close()


# --------------------------------------------------- D. new token wins


def test_new_token_wins_during_grace(tmp_path):
    """T-1339's token-first authority must survive the grace: a real token
    under the pointer replaces the stale one immediately, and the old grace
    is dropped with it."""
    url_a, url_b = "https://example.com/a", "https://example.com/b"
    ed, owner, hl = _editor_live(tmp_path, f"[a]({url_a}) and [b]({url_b})")
    try:
        block = ed.document().findBlockByNumber(0)
        matches = list(MD_LINK_RE.finditer(block.text()))
        assert len(matches) == 2, "the two-token layout is required here"
        frag_a = ed._link_glyph_rects(block, matches[0])[0]
        frag_b = ed._link_glyph_rects(block, matches[1])[0]
        assert not frag_a.intersects(frag_b)

        ed._update_inline_hover(frag_a.center())
        assert ed._hover_inline_target == url_a
        copy_a = ed._hover_inline_copy_rect
        gap_pt = _neutral_point(ed, (frag_a, copy_a), 600)
        ed._update_inline_hover(gap_pt)
        assert ed._hover_inline_kind == "link"
        assert ed._inline_hover_grace_timer.isActive()

        ed._update_inline_hover(frag_b.center())
        assert ed._hover_inline_target == url_b
        assert not ed._inline_hover_grace_timer.isActive()
        assert ed._hover_inline_copy_rect == ed._inline_copy_rect(block, frag_b)
    finally:
        ed.close()


# --------------------------------------------------- E. bottom viewport


def test_bottom_viewport_clamp(tmp_path):
    """Forced hard placement near the bottom edge: the immediate right slot,
    the immediate left slot and the row-tail slot are all PROVEN unavailable,
    so the authority has to reach its fallback -- and the fallback must land
    fully inside the viewport on both axes.

    Pre-fix: it placed the control below the block, bottom 33 in a viewport
    of 25, i.e. painted off-screen and impossible to click.
    """
    text = "[a](https://ex.com)"
    ed, owner, hl = _editor_live(tmp_path, text, width=250, height=25)
    try:
        block, m, frag = _force_hard_placement(ed)
        assert not _premium_slots(ed, block, frag), \
            "the preferred slots were free; this test would prove nothing"

        ed._update_inline_hover(frag.center())
        cr = ed._hover_inline_copy_rect
        assert cr is not None, "Copy rect must be armed"
        _assert_inside_viewport(ed, cr, "bottom Copy")
        # This viewport is 25 px tall on purpose: a target row plus a 14 px
        # control cannot both fit, so overlap is physically unavoidable here
        # and is NOT asserted against. What must hold is the §9 contract --
        # never off-screen. The non-covering preference is proven where the
        # viewport can actually hold both (top and next-block cases).
    finally:
        ed.close()


# --------------------------------------------------- F. top viewport


def test_top_viewport_clamp(tmp_path):
    """Same invariant at the top edge. The target sits on the document's
    first row, so the fallback is tempted to step ABOVE it -- negative y --
    and must instead stay inside the viewport. Kept to three trailing lines
    so no vertical scrollbar appears and the row cannot be narrowed into a
    wrap (that would make an easy adjacent slot legal and prove nothing)."""
    text = "\n".join(["[a](https://ex.com)"] + [f"filler {i}" for i in range(3)])
    ed, owner, hl = _editor_live(tmp_path, text, width=250, height=120)
    try:
        block, m, frag = _force_hard_placement(ed)
        assert frag.top() <= 4, f"target is not at the top edge: {frag}"
        assert not _premium_slots(ed, block, frag), \
            "the preferred slots were free; this test would prove nothing"

        ed._update_inline_hover(frag.center())
        cr = ed._hover_inline_copy_rect
        assert cr is not None
        _assert_inside_viewport(ed, cr, "top Copy")
        assert not cr.intersects(frag), "Copy must not cover its own target"
    finally:
        ed.close()


# --------------------------------------------------- G. next-block collision


def test_fallback_never_covers_the_next_block(tmp_path):
    """The removed assumption was "below the QTextBlock there is no text".
    In a one-paragraph-per-line document that is exactly where the next
    paragraph is. The fallback may not land on block 1's glyphs."""
    text = "[a](https://ex.com)\nnext line is prose"
    ed, owner, hl = _editor_live(tmp_path, text, width=250, height=200)
    try:
        block, m, frag = _force_hard_placement(ed)
        assert not _premium_slots(ed, block, frag), \
            "the preferred slots were free; this test would prove nothing"

        ed._update_inline_hover(frag.center())
        cr = ed._hover_inline_copy_rect
        assert cr is not None
        assert not cr.intersects(frag)

        b1 = ed.document().findBlockByNumber(1)
        b1_rects = _row_text_rects(ed, b1)
        assert b1_rects, "block 1 must actually have visible text geometry"
        for r in b1_rects:
            assert not cr.intersects(r), \
                f"Copy rect {cr} collides with block 1 text row {r}"
    finally:
        ed.close()


# --------------------------------------------------- H. scroll during grace


def test_scroll_during_grace_drops_stale_geometry(tmp_path):
    """Scrolling invalidates the geometry the grace was holding. What must
    not survive is the OLD rect, still clickable, still carrying the old
    URL."""
    url = "https://example.com/scroll"
    lines = [f"[a]({url})"] + [f"line {i}" for i in range(60)]
    ed, owner, hl = _editor_live(tmp_path, "\n".join(lines), width=200, height=200)
    try:
        _block, _m, frag = _first_link_frag(ed)
        ed._update_inline_hover(frag.center())
        before = ed._hover_inline_copy_rect
        assert before is not None
        ed._update_inline_hover(_neutral_point(ed, (frag, before), 200))
        assert ed._inline_hover_grace_timer.isActive()

        sb = ed.verticalScrollBar()
        sb.setValue(min(40, sb.maximum()))
        _flush()

        after = ed._hover_inline_copy_rect
        assert after is None or after != before, \
            f"pre-scroll Copy rect {before} survived as authoritative"
        if after is not None:
            _assert_inside_viewport(ed, after, "post-scroll Copy")
    finally:
        ed.close()


# --------------------------------------------------- I. leave during grace


def test_leave_event_cancels_grace_and_clears(tmp_path):
    url = "https://example.com/leave"
    ed, owner, hl = _editor_live(tmp_path, f"[a]({url})")
    try:
        _block, _m, frag = _first_link_frag(ed)
        ed._update_inline_hover(frag.center())
        copy_rect = ed._hover_inline_copy_rect
        ed._update_inline_hover(_neutral_point(ed, (frag, copy_rect), 600))
        assert ed._inline_hover_grace_timer.isActive()

        ed.leaveEvent(QEvent(QEvent.Type.Leave))
        assert ed._hover_inline_kind is None
        assert ed._hover_inline_copy_rect is None
        assert not ed._inline_hover_grace_timer.isActive()
        QTest.qWait(INLINE_HOVER_GRACE_MS + 100)
        _flush()
        assert ed._hover_inline_kind is None
    finally:
        ed.close()


# --------------------------------------------------- J. destruction during grace


def test_destruction_during_grace_is_safe(tmp_path):
    """The editor is a normal QObject parent of the grace timer, so the
    timer dies with it. A timeout must never fire into a destroyed widget."""
    url = "https://example.com/destroy"
    ed, owner, hl = _editor_live(tmp_path, f"[a]({url})")
    _block, _m, frag = _first_link_frag(ed)
    ed._update_inline_hover(frag.center())
    copy_rect = ed._hover_inline_copy_rect
    ed._update_inline_hover(_neutral_point(ed, (frag, copy_rect), 600))
    assert ed._inline_hover_grace_timer.isActive()

    ed.close()
    ed.deleteLater()
    QTest.qWait(INLINE_HOVER_GRACE_MS + 150)
    _flush()
    _flush()
    # no exception above is the assertion; report the object state honestly
    assert sip.isdeleted(ed) or not ed._inline_hover_grace_timer.isActive()


# --------------------------------------------------- K. document mutation


def test_document_mutation_during_grace_refuses_stale_copy(tmp_path):
    """Grace keeps a control alive for a quarter second. It must never be a
    licence to copy a URL the document no longer contains."""
    url = "https://example.com/doomed"
    ed, owner, hl = _editor_live(tmp_path, f"[a]({url})")
    try:
        block, m, frag = _first_link_frag(ed)
        ed._update_inline_hover(frag.center())
        copy_rect = ed._hover_inline_copy_rect
        ed._update_inline_hover(_neutral_point(ed, (frag, copy_rect), 600))
        assert ed._inline_hover_grace_timer.isActive()
        stale_point = copy_rect.center()

        cur = QTextCursor(block)
        cur.select(QTextCursor.SelectionType.BlockUnderCursor)
        cur.insertText("the link is gone")
        _flush()

        assert ed._hover_inline_kind is None
        assert ed._hover_inline_copy_rect is None
        assert not ed._inline_hover_grace_timer.isActive()
        assert ed._link_copy_at(stale_point) is None
    finally:
        ed.close()


# --------------------------------------------------- L. preview switch


def test_preview_mode_switch_drops_the_control(tmp_path):
    """A view switch re-renders the markup, so the armed rect and its URL
    belong to a document that no longer exists on screen."""
    url = "https://example.com/view"
    ed, owner, hl = _editor_live(tmp_path, f"[a]({url})")
    try:
        _block, _m, frag = _first_link_frag(ed)
        ed._update_inline_hover(frag.center())
        copy_rect = ed._hover_inline_copy_rect
        ed._update_inline_hover(_neutral_point(ed, (frag, copy_rect), 600))
        assert ed._inline_hover_grace_timer.isActive()

        owner.preview_combo.setCurrentIndex(1)   # -> Source View
        _flush()
        assert ed._hover_inline_kind is None
        assert ed._hover_inline_copy_rect is None
        assert not ed._inline_hover_grace_timer.isActive()
        assert ed._link_copy_at(copy_rect.center()) is None
    finally:
        ed.close()
