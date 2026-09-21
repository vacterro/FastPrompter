"""Colored line marks UX: Ctrl+MiddleButton toggle + clickable gutter.

Covers the user slice contract:
A/B  toggle add/remove, text byte-for-byte unchanged
C    deterministic palette choice via patched random
D    Ctrl+MiddleButton never deletes text (no _delete_line_smart)
E    rapid press/dblclick/press = add/remove/add, no lost events
F/G  plain middle + alt middle behaviors unchanged
H    marks work in a 3000-line document (no >2000 dead zone)
I    gutter left/right click cycles through the palette incl. OFF
J    marks survive collect_view_metadata -> apply_line_marks
K    QUEUED_BIT/SENT_BIT survive mark changes
L    unrelated userState bits survive mark mutation
M    line_marks disabled -> explicit toggle enables visibility + creates mark
N    T-1257: every MARK_PALETTE id survives the REAL gutter paint path and
     lands in the gutter as its exact palette colour
O    T-1257: an empty hovered slot still paints as an outline (NoBrush)
P    T-1257: queue stripes still render their exact colours
Q    T-1257: palette hexes and persistent ids are unchanged
"""

import sys
from types import SimpleNamespace

from PyQt6.QtCore import QEvent, QPointF, Qt
from PyQt6.QtGui import QMouseEvent, QPixmap, QTextCursor
from PyQt6.QtWidgets import QApplication

from fastprompter.ui.editor import (
    _RANDOM_MARK_IDS,
    MARK_PALETTE,
    MARK_ZONE_PX,
    VaultTextEdit,
)
from fastprompter.ui.markdown_highlighter import QUEUED_BIT, SENT_BIT

_MIDDLE = Qt.MouseButton.MiddleButton
_LEFT = Qt.MouseButton.LeftButton
_RIGHT = Qt.MouseButton.RightButton
_CTRL = Qt.KeyboardModifier.ControlModifier
_ALT = Qt.KeyboardModifier.AltModifier
_NONE = Qt.KeyboardModifier.NoModifier
_PRESS = QEvent.Type.MouseButtonPress
_DBL = QEvent.Type.MouseButtonDblClick


def _main_window():
    return SimpleNamespace(
        data={
            "show_line_numbers": "True",
            "code_auto_gutter": "False",
            "line_marks": "True",
        },
        highlighter=None,
        _LARGE_DOC_THRESHOLD=500_000,
        mark_dirty=lambda *a, **k: None,
        play_tick_sound=lambda checked: None,
        save_line_marks=lambda: None,
    )


def _editor(text, line_marks="True"):
    mw = _main_window()
    mw.data["line_marks"] = line_marks
    ed = VaultTextEdit(mw)
    ed.setPlainText(text)
    # Real layout: cursorRect collapses to ~zero for a never-shown widget,
    # which would make every click land on block 0 regardless of intent.
    ed.resize(400, 600)
    ed.show()
    return ed


def _scroll_to_block(ed, num):
    """Bring a block into the viewport so mouse events can reach it."""
    block = ed.document().findBlockByNumber(num)
    cur = QTextCursor(block)
    ed.setTextCursor(cur)
    ed.ensureCursorVisible()
    return cur


def _mark_of(ed, num=0):
    block = ed.document().findBlockByNumber(num)
    return max(0, block.userState()) & 0xFF


def _set_mark(ed, num, mark):
    block = ed.document().findBlockByNumber(num)
    state = max(0, block.userState())
    block.setUserState((state & ~0xFF) | mark)


def _pos(ed, block_num, offset=0):
    block = ed.document().findBlockByNumber(block_num)
    cur = QTextCursor(block)
    cur.setPosition(block.position() + offset)
    return ed.cursorRect(cur).center()


def _fire(ed, kind, pos, button, mods):
    event = QMouseEvent(kind, QPointF(pos), button, button, mods)
    if kind == _DBL:
        ed.mouseDoubleClickEvent(event)
    else:
        ed.mousePressEvent(event)


# ---- A / C / D -----------------------------------------------------------


def test_a_ctrl_middle_marks_unmarked_line(qapp):
    ed = _editor("hello world")
    text_before = ed.toPlainText()
    _fire(ed, _PRESS, _pos(ed, 0), _MIDDLE, _CTRL)
    mark = _mark_of(ed, 0)
    assert mark != 0
    assert mark in MARK_PALETTE            # belongs to the curated palette
    assert ed.toPlainText() == text_before  # byte-for-byte unchanged


def test_c_patched_random_assigns_expected_palette_mark(qapp):
    ed = _editor("deterministic")
    import fastprompter.ui.editor as mod
    orig = mod.random.choice
    mod.random.choice = lambda seq: 3      # patch the chooser
    try:
        _fire(ed, _PRESS, _pos(ed, 0), _MIDDLE, _CTRL)
    finally:
        mod.random.choice = orig
    assert _mark_of(ed, 0) == 3
    assert MARK_PALETTE[3][1] == "yellow"  # and 3 is a real palette colour


def test_d_ctrl_middle_never_deletes_text(qapp):
    ed = _editor("alpha\nbeta\ngamma")
    calls = []
    ed._delete_line_smart = lambda block: calls.append(block)
    for num in (0, 1, 2):
        _fire(ed, _PRESS, _pos(ed, num), _MIDDLE, _CTRL)
    assert calls == []                      # destructive path never reached
    assert ed.toPlainText() == "alpha\nbeta\ngamma"
    assert _mark_of(ed, 0) and _mark_of(ed, 1) and _mark_of(ed, 2)


# ---- B: strict second click ----------------------------------------------


def test_b_second_ctrl_middle_removes_mark(qapp):
    ed = _editor("toggle me")
    _fire(ed, _PRESS, _pos(ed, 0), _MIDDLE, _CTRL)
    first = _mark_of(ed, 0)
    assert first != 0
    _fire(ed, _PRESS, _pos(ed, 0), _MIDDLE, _CTRL)
    assert _mark_of(ed, 0) == 0             # removed, NOT re-rolled
    assert ed.toPlainText() == "toggle me"
    # remove -> apply again may choose a fresh colour
    import fastprompter.ui.editor as mod
    orig = mod.random.choice
    mod.random.choice = lambda seq: (_RANDOM_MARK_IDS[-1])
    try:
        _fire(ed, _PRESS, _pos(ed, 0), _MIDDLE, _CTRL)
    finally:
        mod.random.choice = orig
    assert _mark_of(ed, 0) == _RANDOM_MARK_IDS[-1]


# ---- E: rapid routing -----------------------------------------------------


def test_e_rapid_press_dblclick_press_toggles_three_times(qapp):
    ed = _editor("rapid")
    pos = _pos(ed, 0)
    _fire(ed, _PRESS, pos, _MIDDLE, _CTRL)
    assert _mark_of(ed, 0) != 0
    _fire(ed, _DBL, pos, _MIDDLE, _CTRL)     # dblclick routes to press
    assert _mark_of(ed, 0) == 0
    _fire(ed, _PRESS, pos, _MIDDLE, _CTRL)
    assert _mark_of(ed, 0) != 0              # fresh mark, no lost event


# ---- F / G: untouched gestures -------------------------------------------


def test_f_plain_middle_still_cycles_checkbox(qapp):
    ed = _editor("buy milk")
    _fire(ed, _PRESS, _pos(ed, 0), _MIDDLE, _NONE)
    assert ed.toPlainText() == "[x] ~~buy milk~~"


def test_g_alt_middle_still_bulletizes(qapp):
    ed = _editor("alpha")
    _fire(ed, _PRESS, _pos(ed, 0), _MIDDLE, _ALT)
    assert ed.toPlainText() == "\u2022 alpha"


# ---- H: large document ----------------------------------------------------


def test_h_marks_work_above_2000_lines(qapp):
    ed = _editor("\n".join(f"line {i}" for i in range(3000)))
    assert ed.document().blockCount() > 2000
    # gutter click on a visible line: no >2000 dead zone
    y = ed.cursorRect(QTextCursor(
        ed.document().findBlockByNumber(2))).center().y()
    ev = QMouseEvent(_PRESS, QPointF(MARK_ZONE_PX // 2, y),
                     _LEFT, _LEFT, _NONE)
    ed.line_number_area_mouse_press_event(ev)
    assert _mark_of(ed, 2) == 1              # OFF -> first palette colour
    # and Ctrl+Middle deep in the document, after scrolling it into view
    cur = _scroll_to_block(ed, 2500)
    pos = ed.cursorRect(cur).center()
    assert ed.viewport().rect().contains(pos)
    _fire(ed, _PRESS, pos, _MIDDLE, _CTRL)
    assert _mark_of(ed, 2500) != 0


# ---- I: gutter cycling ----------------------------------------------------


def test_i_gutter_left_right_cycles_palette_and_off(qapp):
    ed = _editor("one\ntwo")
    y = ed.cursorRect(QTextCursor(ed.document().firstBlock())).center().y()

    def click(button):
        ev = QMouseEvent(_PRESS, QPointF(MARK_ZONE_PX // 2, y),
                         button, button, _NONE)
        ed.line_number_area_mouse_press_event(ev)

    click(_LEFT)
    assert _mark_of(ed, 0) == 1
    click(_LEFT)
    assert _mark_of(ed, 0) == 2
    click(_RIGHT)                             # backward: 2 -> 1
    assert _mark_of(ed, 0) == 1
    click(_RIGHT)                             # 1 -> OFF
    assert _mark_of(ed, 0) == 0
    click(_RIGHT)                             # OFF -> wraps to top colour
    assert _mark_of(ed, 0) == len(MARK_PALETTE)


# ---- J: persistence --------------------------------------------------------


def test_j_marks_survive_metadata_roundtrip(qapp):
    ed = _editor("keep\nthese\nmarks")
    _set_mark(ed, 0, 2)
    _set_mark(ed, 2, 5)
    marks, _heat, _folded = ed.collect_view_metadata()
    ed2 = _editor("keep\nthese\nmarks")
    ed2.apply_line_marks(dict(marks))
    assert _mark_of(ed2, 0) == 2
    assert _mark_of(ed2, 2) == 5
    assert _mark_of(ed2, 1) == 0


# ---- K / L: bit isolation ---------------------------------------------------


def test_k_queue_bits_survive_mark_toggle(qapp):
    from fastprompter.ui.markdown_highlighter import QUEUED_BIT, SENT_BIT
    ed = _editor("queued line")
    block = ed.document().firstBlock()
    block.setUserState(QUEUED_BIT | SENT_BIT)
    _fire(ed, _PRESS, _pos(ed, 0), _MIDDLE, _CTRL)
    state = max(0, block.userState())
    assert state & QUEUED_BIT and state & SENT_BIT
    assert state & 0xFF != 0                  # and the mark landed
    _fire(ed, _PRESS, _pos(ed, 0), _MIDDLE, _CTRL)
    state = max(0, block.userState())
    assert state & QUEUED_BIT and state & SENT_BIT
    assert state & 0xFF == 0


def test_l_unrelated_userstate_bits_survive(qapp):
    from fastprompter.ui.editor import VaultTextEdit as _V
    fold_bit = _V.FOLD_BIT
    other_bit = 1 << 12                      # outside the mark byte (0xFF)
    ed = _editor("folded header")
    block = ed.document().firstBlock()
    block.setUserState(fold_bit | other_bit)
    _fire(ed, _PRESS, _pos(ed, 0), _MIDDLE, _CTRL)
    state = max(0, block.userState())
    assert state & fold_bit
    assert state & other_bit
    assert state & 0xFF != 0
    # clearing the mark leaves the other bits intact too
    _fire(ed, _PRESS, _pos(ed, 0), _MIDDLE, _CTRL)
    state = max(0, block.userState())
    assert state & fold_bit and state & other_bit
    assert state & 0xFF == 0


# ---- M: disabled setting -----------------------------------------------------


def test_m_ctrl_middle_enables_hidden_line_marks(qapp):
    ed = _editor("invisible mark risk", line_marks="False")
    assert ed.main_win.data.get("line_marks") == "False"
    _fire(ed, _PRESS, _pos(ed, 0), _MIDDLE, _CTRL)
    assert ed.main_win.data.get("line_marks") == "True"   # visibility enabled
    assert _mark_of(ed, 0) != 0                            # and mark created
    # gutter geometry follows the widened zone
    assert ed.line_number_area_width() >= MARK_ZONE_PX + 14


# ---- N / O / P / Q: T-1257 real gutter paint --------------------------------
#
# The defect this pins was `painter.setBrush(color)` with `color` still the
# PERSISTENT PALETTE STRING ("#3DA43D"). PyQt6 does not propagate an exception
# raised inside a C++ virtual: it routes it to ``sys.excepthook`` and then
# calls ``qFatal()``, so the whole process aborts (Windows exit code 3) with no
# failing test to point at. That is why these tests do two things a
# ``QColor(...).isValid()`` assertion cannot:
#
#   * they drive the REAL ``LineNumberArea.paintEvent`` (via repaint/render),
#     not a reimplementation of its arithmetic;
#   * they read the RESULT back as pixels, so "it did not raise" is backed by
#     "the right colour is actually on the gutter".


def _gutter_rows(ed):
    """The visible (block, top, height) rows the paint path will walk."""
    return list(ed.gutter_rows())


def _gutter_image(ed):
    """Render the real line-number area and read it back as an image."""
    area = ed.line_number_area
    pixmap = QPixmap(area.size())
    area.render(pixmap)
    return pixmap.toImage()


def _paint_for_real(ed):
    """Repaint the gutter through Qt, returning anything PyQt could not raise.

    PyQt6 hands an exception from a virtual to ``sys.excepthook`` instead of
    the caller, so a plain ``pytest.raises``-free call would pass even while
    the widget was throwing on every frame. Capturing the hook is the only way
    to assert the paint was actually clean.
    """
    captured = []
    original = sys.excepthook
    sys.excepthook = lambda *exc: captured.append(exc)
    try:
        ed.line_number_area.repaint()
        QApplication.processEvents()
    finally:
        sys.excepthook = original
    return captured


def _marked_editor(mark):
    """A shown editor whose first visible row carries ``mark``."""
    ed = _editor("alpha\nbeta\ngamma")
    _set_mark(ed, 0, mark)
    return ed


def test_n_every_palette_mark_paints_through_the_real_gutter_path(qapp):
    for mark, (hex_colour, name) in MARK_PALETTE.items():
        ed = _marked_editor(mark)
        text_before = ed.toPlainText()

        problems = _paint_for_real(ed)
        assert not problems, f"mark {mark} ({name}) raised in paintEvent: {problems}"

        rows = _gutter_rows(ed)
        assert rows, "no gutter rows were painted at all"
        _block, top, height = rows[0]
        image = _gutter_image(ed)
        painted = image.pixelColor(9, top + height // 2).name()
        # The square is FILLED with the palette colour. A raw string brush
        # could never reach this: it raises before anything is drawn.
        assert painted == hex_colour.lower(), (
            f"mark {mark} ({name}) painted {painted}, expected {hex_colour}")

        # the paint path is read-only over the document
        assert ed.toPlainText() == text_before
        assert _mark_of(ed, 0) == mark
        ed.deleteLater()


def test_o_an_empty_hovered_slot_still_paints_as_an_outline(qapp):
    ed = _editor("alpha\nbeta\ngamma")
    _set_mark(ed, 0, 0)
    rows = _gutter_rows(ed)
    _block, top, height = rows[0]
    ed.line_number_area.hover_y = top + 2

    problems = _paint_for_real(ed)
    assert not problems, f"hover affordance raised in paintEvent: {problems}"

    image = _gutter_image(ed)
    centre = image.pixelColor(9, top + height // 2).name()
    background = image.pixelColor(1, top + height // 2).name()
    # Qt.BrushStyle.NoBrush: the box is drawn but NOT filled, so its centre is
    # still the gutter background.
    assert centre == background
    size = max(6, min(height - 4, 14))
    border = image.pixelColor(9 - size // 2, top + height // 2).name()
    assert border != background, "the empty-slot outline was not drawn"
    ed.line_number_area.hover_y = -1
    ed.deleteLater()


def test_p_queue_stripes_still_render_their_exact_colours(qapp):
    ed = _editor("alpha\nbeta\ngamma")
    rows = _gutter_rows(ed)
    _block, top, height = rows[1]
    block = ed.document().findBlockByNumber(1)
    width = ed.line_number_area.width()

    for bit, expected in ((QUEUED_BIT, "#6aa9ff"), (SENT_BIT, "#46b98a")):
        block.setUserState((max(0, block.userState())
                            & ~(QUEUED_BIT | SENT_BIT)) | bit)
        problems = _paint_for_real(ed)
        assert not problems, f"queue stripe raised in paintEvent: {problems}"
        image = _gutter_image(ed)
        assert image.pixelColor(width - 3, top + 2).name() == expected
        assert image.pixelColor(width - 2, top + 2).name() == expected
    ed.deleteLater()


def test_p2_a_mark_and_a_queue_stripe_coexist_in_one_row(qapp):
    """Both branches in one paint pass — the stripe must not eat the mark."""
    ed = _editor("alpha\nbeta\ngamma")
    block = ed.document().findBlockByNumber(0)
    block.setUserState((max(0, block.userState()) & ~0xFF) | 2 | QUEUED_BIT)

    problems = _paint_for_real(ed)
    assert not problems, f"mark+stripe raised in paintEvent: {problems}"

    _b, top, height = _gutter_rows(ed)[0]
    image = _gutter_image(ed)
    width = ed.line_number_area.width()
    assert image.pixelColor(9, top + height // 2).name() == MARK_PALETTE[2][0].lower()
    assert image.pixelColor(width - 3, top + 2).name() == "#6aa9ff"
    assert _mark_of(ed, 0) == 2
    ed.deleteLater()


def test_q_palette_hexes_and_persistent_ids_are_unchanged(qapp):
    """The ids ride in saved view metadata; the hexes are hand-checked."""
    assert MARK_PALETTE == {
        1: ("#3DA43D", "green"),
        2: ("#D9483B", "red"),
        3: ("#E0A400", "yellow"),
        4: ("#3D6FD9", "blue"),
        5: ("#A26FD9", "purple"),
    }
    assert _RANDOM_MARK_IDS == (1, 2, 3, 4, 5)
