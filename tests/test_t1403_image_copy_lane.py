"""T-1403: an image's Copy is a fixed lane INSIDE its pill, not a slot the
generic occupancy search picked.

Operator report (clipboard_20261001_212737_5579abbc.png): the Copy icon of an
inline image pill appears detached on the LEFT of the pill, and "can appear in
apparently random positions". The cause was that image Copy went through
``_inline_copy_rect`` -- the occupancy-adaptive right/left/row-tail/vertical/
viewport-edge search -- so its position was a function of the surrounding
prose, the wrapping and the viewport, not of the pill.

The contract these tests pin:

  * the Copy square lives INSIDE its own pill, at a FIXED inset from the
    pill's right edge, vertically centred;
  * that relative position is the SAME whatever prose precedes or follows the
    image, at any viewport width and any editor font size;
  * the pill is never widened past the markdown token to make room;
  * the filename text area reserves the lane ALWAYS, so hover cannot reflow
    the label;
  * Copy is the only owner of that lane: a click there copies, a click
    anywhere else on the pill still opens the image.

Ordinary LINK Copy is untouched -- it keeps ``_inline_copy_rect`` and its
collision-aware placement. Nothing here asserts anything about links.
"""

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

import pytest  # noqa: E402
from PyQt6.QtCore import QPoint, QPointF, QRect, Qt  # noqa: E402
from PyQt6.QtGui import QFont, QMouseEvent, QTextCursor  # noqa: E402
from test_t1339_wrapped_inline_copy import _editor_live, _flush, _png  # noqa: E402

from fastprompter.ui.editor import (  # noqa: E402
    IMAGE_COPY_GAP,
    IMAGE_COPY_INSET,
    MD_IMAGE_RE,
    VaultTextEdit,
)

_LEFT = Qt.MouseButton.LeftButton
_NONE = Qt.MouseButton.NoButton
_NO_MOD = Qt.KeyboardModifier.NoModifier


def _click(editor, pos):
    """press + release at ``pos``, left button, no modifiers."""
    p = QPointF(pos)
    editor.mousePressEvent(QMouseEvent(
        QMouseEvent.Type.MouseButtonPress, p, _LEFT, _LEFT, _NO_MOD))
    editor.mouseReleaseEvent(QMouseEvent(
        QMouseEvent.Type.MouseButtonRelease, p, _LEFT, _NONE, _NO_MOD))


def _cursor_at(block, position):
    cur = QTextCursor(block)
    cur.setPosition(position)
    return cur


# ------------------------------------------------------- the lane contract


def _assert_fixed_inside_lane(ed, block, match):
    """Hover the pill under ``match`` and return (pill, copy) after proving the
    fixed internal-lane contract. One assertion set, used by every case below
    so no test can quietly check a weaker subset of it."""
    pill = ed._image_pill_rect(block, match)
    ed._update_inline_hover(pill.center())
    assert ed._hover_inline_kind == "image"
    copy = ed._hover_inline_copy_rect
    assert copy is not None

    # INSIDE the pill, at its right edge, vertically centred.
    assert pill.contains(copy), f"Copy {copy} is not inside the pill {pill}"
    assert pill.right() - copy.right() == IMAGE_COPY_INSET, (
        f"Copy right edge is not the fixed inset from the pill edge "
        f"(pill={pill}, copy={copy})")
    assert abs(copy.center().y() - pill.center().y()) <= 1, (
        f"Copy is not vertically centred: pill={pill}, copy={copy}")

    # NEVER outside the pill in any direction: not left, not above, not below,
    # not on a neighbouring row, not at a viewport edge.
    assert copy.left() >= pill.left()
    assert copy.top() >= pill.top()
    assert copy.bottom() <= pill.bottom()

    # Square-ish: the lane is sized from the row height, not free-floating.
    assert copy.height() == pill.height() - 2 or copy.height() == pill.height()
    return pill, copy


def _relative_offset(pill, copy):
    """The invariant the acceptance criteria name: a fixed distance from the
    pill's right edge, and a centred row."""
    return (pill.right() - copy.right(),
            abs(copy.center().y() - pill.center().y()))


def test_screenshot_shape_copies_from_inside_the_pill(tmp_path):
    """THE operator screenshot shape. Trailing prose occupied the right slot,
    so the old search answered LEFT and the icon looked detached."""
    path = _png(tmp_path, "clipboard_20261001_212737_5579abbc.png")
    ed, owner, hl = _editor_live(
        tmp_path, f"prefix ![]({path}) - trailing prose after the image")
    try:
        block = ed.document().firstBlock()
        _pill, _copy = _assert_fixed_inside_lane(
            ed, block, MD_IMAGE_RE.search(block.text()))
    finally:
        ed.close()
        ed.deleteLater()
        owner.preview_combo.deleteLater()
        _flush()


@pytest.mark.parametrize("shape", [
    "![]({p})",                       # A bare
    "prefix ![]({p})",                 # B preceding prose
    "![]({p}) trailing prose",         # C trailing prose
    "prefix ![]({p}) trailing prose",  # D both
])
def test_surrounding_prose_never_moves_the_copy_lane(tmp_path, shape):
    """A-D. Same relative lane with and without prose on either side."""
    path = _png(tmp_path)
    ed, owner, hl = _editor_live(tmp_path, shape.format(p=path))
    try:
        block = ed.document().firstBlock()
        pill, copy = _assert_fixed_inside_lane(
            ed, block, MD_IMAGE_RE.search(block.text()))
        assert _relative_offset(pill, copy) == (IMAGE_COPY_INSET, 0)
    finally:
        ed.close()
        ed.deleteLater()
        owner.preview_combo.deleteLater()
        _flush()


def test_two_images_own_separate_lanes(tmp_path):
    """E. `![](a.png) text ![](b.png)` -- hovering one arms only that one."""
    p1 = _png(tmp_path, "one.png")
    p2 = _png(tmp_path, "two.png")
    ed, owner, hl = _editor_live(tmp_path, f"![]({p1}) text ![]({p2})")
    try:
        block = ed.document().firstBlock()
        ms = list(MD_IMAGE_RE.finditer(block.text()))
        assert len(ms) == 2
        pill0, copy0 = _assert_fixed_inside_lane(ed, block, ms[0])
        assert os.path.normcase(ed._hover_inline_target) == os.path.normcase(
            os.path.realpath(p1))
        pill1, copy1 = _assert_fixed_inside_lane(ed, block, ms[1])
        assert os.path.normcase(ed._hover_inline_target) == os.path.normcase(
            os.path.realpath(p2))
        # No state survives from image A, and image B's lane never appears in
        # the prose gap between the two pills.
        assert not copy1.intersects(pill0)
        gap = QRect(pill0.right() + 1, pill0.top(),
                    max(0, pill1.left() - pill0.right() - 1), pill0.height())
        assert not copy1.intersects(gap), f"lane landed between the pills: {gap}"
        assert copy1 != copy0
    finally:
        ed.close()
        ed.deleteLater()
        owner.preview_combo.deleteLater()
        _flush()


@pytest.mark.parametrize("width", [240, 400, 900])
def test_viewport_width_never_moves_the_copy_lane(tmp_path, width):
    """F/G. Narrow and wide viewports, and a wrapped token at the narrow one."""
    path = _png(tmp_path)
    ed, owner, hl = _editor_live(tmp_path, f"prefix ![]({path}) trailing prose",
                                 width=width)
    try:
        block = ed.document().firstBlock()
        pill, copy = _assert_fixed_inside_lane(
            ed, block, MD_IMAGE_RE.search(block.text()))
        assert _relative_offset(pill, copy) == (IMAGE_COPY_INSET, 0)
    finally:
        ed.close()
        ed.deleteLater()
        owner.preview_combo.deleteLater()
        _flush()


@pytest.mark.parametrize("points", [8, 9, 14])
def test_font_size_scales_the_lane_but_never_moves_it(tmp_path, points):
    """H. Row height may size the square; the lane stays pinned to the edge."""
    path = _png(tmp_path)
    ed, owner, hl = _editor_live(tmp_path, f"prefix ![]({path}) trailing prose")
    try:
        ed.setFont(QFont("Verdana", points))
        hl.rehighlight()
        _flush()
        ed._idle_timer.stop()
        block = ed.document().firstBlock()
        pill, copy = _assert_fixed_inside_lane(
            ed, block, MD_IMAGE_RE.search(block.text()))
        assert _relative_offset(pill, copy) == (IMAGE_COPY_INSET, 0)
    finally:
        ed.close()
        ed.deleteLater()
        owner.preview_combo.deleteLater()
        _flush()


# ------------------------------------------------------- pill is not widened


def test_pill_is_never_widened_to_fit_the_copy_lane(tmp_path):
    """A short token sacrifices filename width instead of growing into prose."""
    path = _png(tmp_path, "a.png")
    ed, owner, hl = _editor_live(tmp_path, f"prefix ![]({path}) trailing prose")
    try:
        block = ed.document().firstBlock()
        m = MD_IMAGE_RE.search(block.text())
        pill = ed._image_pill_rect(block, m)
        # the pill still ends where the markdown token ends: the hidden markup
        # is what measures it, and nothing about Copy may extend that.
        end = ed.cursorRect(
            _cursor_at(block, block.position() + m.end()))
        assert end.left() - pill.left() <= pill.width() + 1

        ed._update_inline_hover(pill.center())
        copy = ed._hover_inline_copy_rect
        assert copy.right() <= pill.right() - IMAGE_COPY_INSET
        assert copy.right() <= end.left() - IMAGE_COPY_INSET or \
            end.top() != ed.cursorRect(
                _cursor_at(block, block.position() + m.start())).top()
    finally:
        ed.close()
        ed.deleteLater()
        owner.preview_combo.deleteLater()
        _flush()


# ------------------------------------------------------- no label reflow


def test_filename_area_reserves_the_lane_at_idle_and_on_hover(tmp_path):
    """The pill's text rect is the SAME whatever the hover state is, and it
    stops short of the lane -- so the filename cannot shift when Copy appears."""
    path = _png(tmp_path, "shot.png")
    ed, owner, hl = _editor_live(tmp_path, f"prefix ![]({path})")
    try:
        block = ed.document().firstBlock()
        pill = ed._image_pill_rect(block, MD_IMAGE_RE.search(block.text()))
        lane = ed._image_copy_lane_rect(pill)
        idle = ed._image_pill_text_rect(pill)
        assert idle.right() <= lane.left() - IMAGE_COPY_GAP
        ed._update_inline_hover(pill.center())
        assert ed._hover_inline_copy_rect == lane
        assert ed._image_pill_text_rect(pill) == idle, (
            "the filename area moved when Copy was revealed")
    finally:
        ed.close()
        ed.deleteLater()
        owner.preview_combo.deleteLater()
        _flush()


# ------------------------------------------------------- hover behaviour


def test_moving_from_the_filename_into_the_lane_keeps_the_control(tmp_path):
    """No flicker, no relocation: the lane is inside the pill, so the walk from
    the label to the icon never crosses a dead gap."""
    path = _png(tmp_path)
    ed, owner, hl = _editor_live(tmp_path, f"prefix ![]({path}) trailing prose")
    try:
        block = ed.document().firstBlock()
        pill = ed._image_pill_rect(block, MD_IMAGE_RE.search(block.text()))
        ed._update_inline_hover(pill.center())
        lane = ed._hover_inline_copy_rect
        assert not ed._inline_hover_grace_timer.isActive()
        for step in range(1, 6):
            pos = QPoint(pill.left() + pill.width() * step // 6, pill.center().y())
            ed._update_inline_hover(pos)
            assert ed._hover_inline_kind == "image", f"lost the hover at step {step}"
            assert ed._hover_inline_copy_rect == lane, f"lane moved at step {step}"
            assert not ed._inline_hover_grace_timer.isActive()
    finally:
        ed.close()
        ed.deleteLater()
        owner.preview_combo.deleteLater()
        _flush()


def test_leaving_the_pill_hides_the_copy_at_once(tmp_path):
    """Images sit their lane INSIDE the pill, so there is no far-placement gap
    to cross and no reason to spend the link grace interval. Links keep it."""
    path = _png(tmp_path)
    ed, owner, hl = _editor_live(tmp_path, f"prefix ![]({path}) trailing prose")
    try:
        block = ed.document().firstBlock()
        pill = ed._image_pill_rect(block, MD_IMAGE_RE.search(block.text()))
        ed._update_inline_hover(pill.center())
        assert ed._hover_inline_kind == "image"
        ed._update_inline_hover(QPoint(pill.left(), pill.bottom() + 60))
        assert ed._hover_inline_kind is None
        assert ed._hover_inline_copy_rect is None
        assert not ed._inline_hover_grace_timer.isActive()
    finally:
        ed.close()
        ed.deleteLater()
        owner.preview_combo.deleteLater()
        _flush()


# ------------------------------------------------------- click semantics


def test_click_in_the_lane_copies_and_click_elsewhere_opens(tmp_path, monkeypatch):
    """The lane owns its clicks; the rest of the pill still opens the image."""
    path = _png(tmp_path, "click.png")
    opened = []
    copied = []
    monkeypatch.setattr(
        VaultTextEdit, "authorize_and_open_url",
        classmethod(lambda cls, url, *a, **k: opened.append(url.toString())))
    ed, owner, hl = _editor_live(tmp_path, f"prefix ![]({path}) trailing prose")
    try:
        ed.copy_image_at = lambda p: copied.append(p) or True
        block = ed.document().firstBlock()
        pill = ed._image_pill_rect(block, MD_IMAGE_RE.search(block.text()))
        lane = ed._image_copy_lane_rect(pill)
        # Copy is hover-only, so nothing is clickable until the pill is armed.
        ed._update_inline_hover(pill.center())
        assert ed._image_copy_at(lane.center()) is not None
        assert ed.image_hit_at(lane.center()) is not None

        # a click in the lane copies and never opens the viewer
        _click(ed, lane.center())
        assert copied, "a click in the Copy lane did not copy"
        assert not opened, "a click in the Copy lane opened the viewer"
        copied.clear()

        # a click on the filename half still opens the image
        rest = QPoint(pill.left() + 4, pill.center().y())
        assert not ed._image_copy_at(rest)
        _click(ed, rest)
        assert opened, "a click outside the lane stopped opening the image"
        assert not copied, "a click outside the lane copied instead"
    finally:
        ed.close()
        ed.deleteLater()
        owner.preview_combo.deleteLater()
        _flush()
