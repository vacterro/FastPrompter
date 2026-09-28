"""T-1224: middle-button rapid repeat must not lose every second press.

Qt reports the second press of a rapid sequence as ``MouseButtonDblClick``,
so a handler that only implements ``mousePressEvent`` silently drops it.
These tests drive the REAL event types (press / dblclick / press) through the
same public handlers the widget receives, and assert one event -> one logical
action.
"""

from types import SimpleNamespace

from PyQt6.QtCore import QEvent, QPointF, Qt
from PyQt6.QtGui import QMouseEvent, QTextCursor

from fastprompter.ui.editor import VaultTextEdit

_MIDDLE = Qt.MouseButton.MiddleButton
_LEFT = Qt.MouseButton.LeftButton
_CTRL = Qt.KeyboardModifier.ControlModifier
_ALT = Qt.KeyboardModifier.AltModifier
_NONE = Qt.KeyboardModifier.NoModifier


def _main_window():
    return SimpleNamespace(
        data={
            "show_line_numbers": "False",
            "code_auto_gutter": "False",
            "line_marks": "False",
        },
        highlighter=None,
        _LARGE_DOC_THRESHOLD=500_000,
        mark_dirty=lambda: None,
        play_tick_sound=lambda checked: None,
        save_line_marks=lambda: None,
    )


def _editor(text):
    ed = VaultTextEdit(_main_window())
    ed.setPlainText(text)
    return ed


def _pos(ed, block_num, offset=0):
    block = ed.document().findBlockByNumber(block_num)
    cur = QTextCursor(block)
    cur.setPosition(block.position() + offset)
    return ed.cursorRect(cur).center()


def _fire(ed, kind, pos, button, mods):
    event = QMouseEvent(kind, QPointF(pos), button, button, mods)
    if kind == QEvent.Type.MouseButtonDblClick:
        ed.mouseDoubleClickEvent(event)
    else:
        ed.mousePressEvent(event)


def test_editor_plain_middle_rapid_press_dblclick_press(qapp):
    ed = _editor("buy milk")
    pos = _pos(ed, 0)
    _fire(ed, QEvent.Type.MouseButtonPress, pos, _MIDDLE, _NONE)
    assert ed.toPlainText() == "[x] ~~buy milk~~"
    _fire(ed, QEvent.Type.MouseButtonDblClick, pos, _MIDDLE, _NONE)
    assert ed.toPlainText() == "[ ] buy milk"
    _fire(ed, QEvent.Type.MouseButtonPress, pos, _MIDDLE, _NONE)
    assert ed.toPlainText() == "buy milk"


def test_editor_middle_dblclick_is_exactly_one_action(qapp):
    # The routed double-click must not also run the press handler's own
    # super() path: one event, one state transition.
    ed = _editor("solo")
    pos = _pos(ed, 0)
    _fire(ed, QEvent.Type.MouseButtonPress, pos, _MIDDLE, _NONE)
    assert ed.toPlainText() == "[x] ~~solo~~"
    _fire(ed, QEvent.Type.MouseButtonDblClick, pos, _MIDDLE, _NONE)
    assert ed.toPlainText() == "[ ] solo"


def test_editor_ctrl_middle_rapid_deletes_exactly_one_line(qapp):
    # T-1335 redefined Ctrl+Middle in the editor: it deletes the whole line
    # under the pointer (the colored line mark moved to the gutter box). The
    # W2 invariant that still matters is the one this test was written for --
    # one gesture, one line. A fast double middle click sends Press, Release,
    # DblClick, Release, and the DblClick is swallowed, so the rapid sequence
    # cannot delete a SECOND line.
    ed = _editor("alpha\nbeta\ngamma")
    _fire(ed, QEvent.Type.MouseButtonPress, _pos(ed, 0), _MIDDLE, _CTRL)
    assert ed.toPlainText() == "beta\ngamma"
    _fire(ed, QEvent.Type.MouseButtonDblClick, _pos(ed, 0), _MIDDLE, _CTRL)
    assert ed.toPlainText() == "beta\ngamma"
    _fire(ed, QEvent.Type.MouseButtonPress, _pos(ed, 0), _MIDDLE, _CTRL)
    assert ed.toPlainText() == "gamma"


def test_editor_alt_middle_dblclick_bulletizes(qapp):
    ed = _editor("alpha")
    _fire(ed, QEvent.Type.MouseButtonDblClick, _pos(ed, 0), _MIDDLE, _ALT)
    assert ed.toPlainText() == "\u2022 alpha"


def test_editor_left_double_click_is_not_routed_to_middle_route(qapp):
    # The MButton repair must not become a generic ``self.mousePressEvent``
    # for every button: a left double-click must not toggle a checkbox.
    ed = _editor("hello world")
    _fire(ed, QEvent.Type.MouseButtonDblClick, _pos(ed, 0, 2), _LEFT, _NONE)
    assert ed.toPlainText() == "hello world"


# ---------------------------------------------------------------------------
# T-1283 / audit/9 CORE-003: the SiloRow half of the same invariant.
#
# The editor test above pins VaultTextEdit. The sidebar row
# (DraggableSiloButton) has the analogous MiddleButton delegation at
# snippet_panel.py:1172 (mouseDoubleClickEvent -> mousePressEvent), routing
# plain MiddleButton -> trash_silo and Shift+MiddleButton -> clear_silo. It
# had no durable regression, so a future refactor could drop the second
# (double-click) press of a rapid sequence while the editor test stayed green.
# ---------------------------------------------------------------------------

from fastprompter.ui.snippet_panel import DraggableSiloButton  # noqa: E402


class _SiloMainSpy:
    """Records the destructive silo actions the row routes to the main window."""

    def __init__(self):
        self._current_lang = "EN"
        self.data = {}
        self.calls = []

    def trash_silo(self, idx, is_archive=False):
        self.calls.append(("trash", idx, is_archive))

    def clear_silo(self, idx, is_archive=False):
        self.calls.append(("clear", idx, is_archive))


def _silo_row(is_archive=False):
    spy = _SiloMainSpy()
    row = DraggableSiloButton(spy, is_archive=is_archive)
    row.global_idx = 4
    return row, spy


def _fire_row(row, kind, button, mods):
    event = QMouseEvent(kind, QPointF(5.0, 5.0), button, button, mods)
    if kind == QEvent.Type.MouseButtonDblClick:
        row.mouseDoubleClickEvent(event)
    else:
        row.mousePressEvent(event)


def test_silo_row_plain_middle_rapid_press_dblclick_press(qapp):
    row, spy = _silo_row()
    _fire_row(row, QEvent.Type.MouseButtonPress, _MIDDLE, _NONE)
    _fire_row(row, QEvent.Type.MouseButtonDblClick, _MIDDLE, _NONE)
    _fire_row(row, QEvent.Type.MouseButtonPress, _MIDDLE, _NONE)
    assert spy.calls == [("trash", 4, False)] * 3


def test_silo_row_shift_middle_rapid_press_dblclick_press(qapp):
    row, spy = _silo_row()
    shift = Qt.KeyboardModifier.ShiftModifier
    _fire_row(row, QEvent.Type.MouseButtonPress, _MIDDLE, shift)
    _fire_row(row, QEvent.Type.MouseButtonDblClick, _MIDDLE, shift)
    _fire_row(row, QEvent.Type.MouseButtonPress, _MIDDLE, shift)
    assert spy.calls == [("clear", 4, False)] * 3


def test_silo_row_archive_routes_is_archive_true(qapp):
    row, spy = _silo_row(is_archive=True)
    _fire_row(row, QEvent.Type.MouseButtonDblClick, _MIDDLE, _NONE)
    assert spy.calls == [("trash", 4, True)]


def test_silo_row_left_double_click_is_not_routed_to_middle_route(qapp):
    row, spy = _silo_row()
    _fire_row(row, QEvent.Type.MouseButtonDblClick, _LEFT, _NONE)
    assert spy.calls == []

