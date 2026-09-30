"""Copy must avoid every painted row, including short concealed image rows."""

from pathlib import Path

import pytest
from PyQt6.QtCore import QRect, QUrl
from PyQt6.QtGui import QFont, QTextCursor, QTextLayout
from test_t1339_wrapped_inline_copy import (
    MD_IMAGE_RE,
    _editor_live,
    _flush,
    _prose_rects,
)


@pytest.mark.parametrize("points", [8, 9, 14])
@pytest.mark.parametrize("target_length", [80, 160, 240])
@pytest.mark.parametrize("width", [240, 280, 320, 400])
def test_image_copy_clears_all_wrapped_prose(tmp_path, points, target_length, width):
    # Keep the token's length independent of the host's temporary directory.
    target = "file:///C:/images/" + "x" * target_length + ".png"
    ed, owner, hl = _editor_live(tmp_path, f"pre ![]({target}) trailing prose", width=width)
    try:
        ed.setFont(QFont("Verdana", points))
        hl.rehighlight()
        _flush()
        ed._idle_timer.stop()
        block = ed.document().firstBlock()
        pill = ed._image_pill_rect(block, MD_IMAGE_RE.search(block.text()))
        ed._update_inline_hover(pill.center())
        copy = ed._hover_inline_copy_rect
        assert copy is not None
        assert ed.viewport().rect().contains(copy)
        assert not copy.intersects(pill)
        for prose in _prose_rects(ed, block, "trailing prose"):
            assert not copy.intersects(prose), f"Copy {copy} covers prose {prose}"
        assert Path(ed._image_copy_at(copy.center())[0]) == Path(QUrl(target).toLocalFile())
    finally:
        ed.close()
        ed.deleteLater()
        owner.preview_combo.deleteLater()
        _flush()


def test_copy_does_not_cover_second_following_block(tmp_path):
    # A tall Copy beside a short next paragraph can reach the paragraph AFTER
    # it too. Checking only immediate neighbours is not sufficient.
    text = "[label](https://example.com/" + "x" * 120 + ")\nx\n" + "prose " * 50
    ed, owner, hl = _editor_live(tmp_path, text, width=240)
    try:
        from fastprompter.ui.editor import MD_LINK_RE

        block = ed.document().firstBlock()
        target = ed._link_glyph_rects(block, MD_LINK_RE.search(block.text()))[-1]
        copy = ed._inline_copy_rect(block, target)
        assert ed.viewport().rect().contains(copy)
        for number in (1, 2):
            for row in ed._block_visual_rows(ed.document().findBlockByNumber(number)):
                rect = QRect(row["left"], row["top"], row["right"] - row["left"], row["height"])
                assert not copy.intersects(rect), f"Copy {copy} covers block {number}: {rect}"
    finally:
        ed.close()
        ed.deleteLater()
        owner.preview_combo.deleteLater()
        _flush()


def test_copy_occupancy_scans_only_viewport_blocks(tmp_path, monkeypatch):
    ed, owner, hl = _editor_live(tmp_path, "[label](https://example.com)\n" * 1500,
                                  width=300, height=140)
    try:
        from fastprompter.ui.editor import MD_LINK_RE

        cursor = QTextCursor(ed.document().findBlockByNumber(900))
        ed.setTextCursor(cursor)
        ed.ensureCursorVisible()
        _flush()
        ed._idle_timer.stop()
        block = ed._first_visible_block().next()
        target = ed._link_glyph_rects(block, MD_LINK_RE.search(block.text()))[0]
        visited = []
        original = ed._block_visual_rows

        def record(block, **kwargs):
            visited.append(block.blockNumber())
            return original(block, **kwargs)

        monkeypatch.setattr(ed, "_block_visual_rows", record)
        copy = ed._inline_copy_rect(block, target)
        assert ed.viewport().rect().contains(copy)
        assert len(visited) < 20, f"Copy scanned {len(visited)} blocks for a 140px viewport"
        assert min(visited) > 850
    finally:
        ed.close()
        ed.deleteLater()
        owner.preview_combo.deleteLater()
        _flush()


def test_huge_wrapped_block_scans_only_on_screen_lines(tmp_path, monkeypatch):
    ed, owner, hl = _editor_live(tmp_path, "words " * 15000, width=300, height=140)
    try:
        ed.setFont(QFont("Verdana", 9))
        cursor = QTextCursor(ed.document())
        cursor.setPosition(45000)
        ed.setTextCursor(cursor)
        ed.ensureCursorVisible()
        _flush()
        ed._idle_timer.stop()
        assert ed.document().firstBlock().layout().lineCount() > 1000
        calls = []
        original = QTextLayout.lineAt

        def record(layout, index):
            calls.append(index)
            return original(layout, index)

        monkeypatch.setattr(QTextLayout, "lineAt", record)
        rows = ed._block_visual_rows(ed.document().firstBlock(), visible_only=True)
        assert rows
        assert len(calls) < 20, f"Scrolled Copy scanned {len(calls)} wrapped lines"
        assert min(calls) > 500
    finally:
        ed.close()
        ed.deleteLater()
        owner.preview_combo.deleteLater()
        _flush()
