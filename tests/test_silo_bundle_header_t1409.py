"""T-1409: the Pack control on the silo's primary header.

The control is SILO-level, not heading-level: a document may have fifty
Markdown headers and exactly one of them may own Pack. These tests drive the
real ``VaultTextEdit`` over the same minimal owner stand-in the other editor
suites use, and prove the geometry authority, the routing contract and the
modifier-timelock that makes Shift+Click trustworthy.

Contract under test:
  A the first top-level heading owns Pack; no other block does
  B the visual order is timestamp, then fold, then pack, with no overlap
  C a plain click asks for a quick pack, a Shift+press asks for options, and
    the modifier is read at PRESS so release-time drift cannot choose
  D a press that starts elsewhere and ends on Pack fires nothing
"""

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

import pytest  # noqa: E402
from PyQt6.QtCore import QEvent, QPoint, QPointF, Qt  # noqa: E402
from PyQt6.QtGui import QMouseEvent, QTextCursor  # noqa: E402
from PyQt6.QtWidgets import QApplication, QComboBox  # noqa: E402

from fastprompter.ui.editor import SILO_BUNDLE_GLYPH, VaultTextEdit  # noqa: E402

_APP = QApplication.instance() or QApplication([])

# The operator's own shape: a Ctrl+E stamped title, a divider, then body.
STAMPED = "# FastPrompter: (Evening 03 Oct - 17:39)\n---\nbody text\n"

MULTI = ("# First heading\nbody\n"
         "## Second level\nbody\n"
         "# Second top level\nbody\n")


class _Owner:
    """Records which backend the editor asked for."""

    highlighter = None
    _LARGE_DOC_THRESHOLD = 500_000
    _LARGE_DOC_BLOCK_THRESHOLD = 2000
    cb_ctrl_c = None

    def __init__(self, tmp_path):
        self.data = {"sound_ui": "False", "sound_typewriter": "False",
                     "auto_bullet": "False", "bullet_double_line": "False",
                     "ctrl_c_closes": "False", "image_paste_style": "pill",
                     "hover_line": "False", "show_line_numbers": "False",
                     "code_auto_gutter": "False", "line_marks": "False"}
        self._current_lang = "EN"
        self.calls = []
        self.preview_combo = QComboBox()
        self.preview_combo.addItem("Live Preview", "Live Preview")
        self.preview_combo.addItem("Source View", "Source View")

    def silo_bundle_quick_pack(self):
        self.calls.append("quick")

    def silo_bundle_with_options(self):
        self.calls.append("options")

    def _silo_folder_dir(self, *_a):
        return str(self._)

    def play_tick_sound(self):
        pass

    def mark_dirty(self):
        pass

    def themed_cursor(self, shape):
        from PyQt6.QtGui import QCursor
        return QCursor(shape)


def _editor(tmp_path, text):
    owner = _Owner(tmp_path)
    ed = VaultTextEdit(owner)
    ed.resize(900, 600)
    ed.setPlainText(text)
    ed.show()
    for _ in range(6):
        _APP.processEvents()
    return ed, owner


def _block(ed, number):
    return ed.document().findBlockByNumber(number)


def _mouse(kind, pos, modifiers=Qt.KeyboardModifier.NoModifier,
           button=Qt.MouseButton.LeftButton):
    point = QPointF(pos)
    return QMouseEvent(kind, point, point, button, button, modifiers)


def _click(ed, owner, pos, modifiers=Qt.KeyboardModifier.NoModifier):
    ed.mousePressEvent(_mouse(QEvent.Type.MouseButtonPress, pos, modifiers))
    ed.mouseReleaseEvent(_mouse(QEvent.Type.MouseButtonRelease, pos,
                                Qt.KeyboardModifier.NoModifier))


# ------------------------------------------------------------- ownership

def test_first_top_level_heading_owns_pack(tmp_path):
    ed, _owner = _editor(tmp_path, STAMPED)
    try:
        assert ed._primary_header_block().blockNumber() == 0
        assert ed._silo_bundle_rect(_block(ed, 0)) is not None
    finally:
        ed.close()


def test_no_header_means_no_pack_control(tmp_path):
    ed, _owner = _editor(tmp_path, "just prose\nno heading here\n")
    try:
        assert ed._primary_header_block() is None
        for number in range(ed.document().blockCount()):
            assert ed._silo_bundle_rect(_block(ed, number)) is None
    finally:
        ed.close()


def test_only_the_first_of_several_top_level_headings_owns_pack(tmp_path):
    ed, _owner = _editor(tmp_path, MULTI)
    try:
        assert ed._primary_header_block().blockNumber() == 0
        assert ed._silo_bundle_rect(_block(ed, 0)) is not None
        assert ed._silo_bundle_rect(_block(ed, 2)) is None     # ##
        assert ed._silo_bundle_rect(_block(ed, 4)) is None     # second #
        assert ed._silo_bundle_rect(_block(ed, 1)) is None     # body
    finally:
        ed.close()


def test_a_hash_line_inside_a_code_fence_never_claims_pack(tmp_path):
    text = ("# Real heading\n"
            "```python\n"
            "# a python comment, not a heading\n"
            "```\n")
    ed, _owner = _editor(tmp_path, text)
    try:
        assert ed._primary_header_block().blockNumber() == 0
        assert ed._silo_bundle_rect(_block(ed, 2)) is None
    finally:
        ed.close()


def test_leading_prose_does_not_hide_the_first_heading(tmp_path):
    ed, _owner = _editor(tmp_path, "intro line\n\n# Title\nbody\n")
    try:
        assert ed._primary_header_block().blockNumber() == 2
    finally:
        ed.close()


def test_editing_the_document_re_resolves_the_owner(tmp_path):
    ed, _owner = _editor(tmp_path, "prose only\n")
    try:
        assert ed._primary_header_block() is None
        ed.setPlainText("# Added later\nbody\n")
        assert ed._primary_header_block().blockNumber() == 0
    finally:
        ed.close()


# -------------------------------------------------------------- geometry

def test_controls_are_ordered_timestamp_fold_pack(tmp_path):
    ed, _owner = _editor(tmp_path, STAMPED)
    try:
        block = _block(ed, 0)
        ts = ed._ts_glyph_rect(block)
        fold = ed._fold_rect(block)
        pack = ed._silo_bundle_rect(block)
        assert ts is not None and fold is not None and pack is not None
        assert ts.right() < fold.left()
        assert fold.right() < pack.left()
    finally:
        ed.close()


def test_no_control_overlaps_another(tmp_path):
    ed, _owner = _editor(tmp_path, STAMPED)
    try:
        block = _block(ed, 0)
        ts = ed._ts_glyph_rect(block)
        fold = ed._fold_rect(block)
        pack = ed._silo_bundle_rect(block)
        assert not ts.intersects(fold)
        assert not ts.intersects(pack)
        assert not fold.intersects(pack)
        assert pack.height() > 8 and pack.width() > 8
    finally:
        ed.close()


def test_pack_is_a_hover_target_and_leaves_the_text_selectable(tmp_path):
    ed, _owner = _editor(tmp_path, STAMPED)
    try:
        pack = ed._silo_bundle_rect(_block(ed, 0))
        assert ed._interactive_target_at(pack.center()) is True
        # A press on the text itself must still be ordinary text editing:
        # the control is outside every text row.
        assert not pack.intersects(ed.cursorRect(QTextCursor(_block(ed, 0))))
    finally:
        ed.close()


def test_hit_testing_matches_the_rect(tmp_path):
    ed, _owner = _editor(tmp_path, STAMPED)
    try:
        block = _block(ed, 0)
        pack = ed._silo_bundle_rect(block)
        assert ed._silo_bundle_block_at(pack.center()) is not None
        assert ed._silo_bundle_block_at(QPoint(4, 4)) is None
    finally:
        ed.close()


def test_the_glyph_is_a_single_stable_constant():
    assert SILO_BUNDLE_GLYPH == "\u25a4"


# --------------------------------------------------------------- routing

def test_plain_click_asks_for_a_quick_pack(tmp_path):
    ed, owner = _editor(tmp_path, STAMPED)
    try:
        _click(ed, owner, ed._silo_bundle_rect(_block(ed, 0)).center())
        assert owner.calls == ["quick"]
    finally:
        ed.close()


def test_shift_click_asks_for_options(tmp_path):
    ed, owner = _editor(tmp_path, STAMPED)
    try:
        _click(ed, owner, ed._silo_bundle_rect(_block(ed, 0)).center(),
               Qt.KeyboardModifier.ShiftModifier)
        assert owner.calls == ["options"]
    finally:
        ed.close()


def test_shift_is_read_at_press_not_at_release(tmp_path):
    """A modifier released before the button must not downgrade the action."""
    ed, owner = _editor(tmp_path, STAMPED)
    try:
        pos = ed._silo_bundle_rect(_block(ed, 0)).center()
        ed.mousePressEvent(_mouse(QEvent.Type.MouseButtonPress, pos,
                                  Qt.KeyboardModifier.ShiftModifier))
        # release with NO modifier at all -- the press decided the gesture
        ed.mouseReleaseEvent(_mouse(QEvent.Type.MouseButtonRelease, pos))
        assert owner.calls == ["options"]
    finally:
        ed.close()


def test_a_press_elsewhere_released_on_pack_does_nothing(tmp_path):
    ed, owner = _editor(tmp_path, STAMPED)
    try:
        pack = ed._silo_bundle_rect(_block(ed, 0)).center()
        ed.mousePressEvent(_mouse(QEvent.Type.MouseButtonPress, QPoint(20, 40)))
        ed.mouseReleaseEvent(_mouse(QEvent.Type.MouseButtonRelease, pack))
        assert owner.calls == []
    finally:
        ed.close()


def test_a_press_on_pack_released_elsewhere_does_nothing(tmp_path):
    ed, owner = _editor(tmp_path, STAMPED)
    try:
        pack = ed._silo_bundle_rect(_block(ed, 0)).center()
        ed.mousePressEvent(_mouse(QEvent.Type.MouseButtonPress, pack))
        ed.mouseReleaseEvent(_mouse(QEvent.Type.MouseButtonRelease,
                                    QPoint(20, 40)))
        assert owner.calls == []
    finally:
        ed.close()


def test_a_press_on_a_second_heading_never_packs(tmp_path):
    ed, owner = _editor(tmp_path, MULTI)
    try:
        second = _block(ed, 4)
        rect = ed.cursorRect(QTextCursor(second))
        pos = rect.center()
        ed.mousePressEvent(_mouse(QEvent.Type.MouseButtonPress, pos))
        ed.mouseReleaseEvent(_mouse(QEvent.Type.MouseButtonRelease, pos))
        assert owner.calls == []
    finally:
        ed.close()


@pytest.mark.parametrize("text", ["# One\n# Two\n", "## Only second level\n"])
def test_a_document_without_an_owned_header_has_no_pack_hit(tmp_path, text):
    ed, _owner = _editor(tmp_path, text)
    try:
        number = 1 if text.startswith("# One") else 0
        block = _block(ed, number)
        if text.startswith("## "):
            assert ed._primary_header_block() is None
        else:
            assert ed._primary_header_block().blockNumber() == 0
        assert ed._silo_bundle_block_at(
            ed.cursorRect(QTextCursor(block)).center()) is None
    finally:
        ed.close()
