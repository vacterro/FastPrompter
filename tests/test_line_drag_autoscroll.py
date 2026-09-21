"""Stationary edge dragging changes only the view until the actual drop."""
from types import SimpleNamespace

import pytest
from PyQt6 import sip
from PyQt6.QtCore import QEvent, QPoint, QPointF, Qt
from PyQt6.QtGui import QMouseEvent, QTextCursor
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from fastprompter.ui.editor import VaultTextEdit


def _clear_latched_modifiers(widget):
    """Put Qt's PROCESS-WIDE modifier state back to NoModifier.

    Qt tracks the modifiers of the last event it processed in
    ``QGuiApplication::keyboardModifiers()``. A plain synthetic event resets
    it; which one lands depends on what the test left behind (a grabbed
    viewport swallows a move), so try the cheap ones in order and fail loudly
    if none of them worked rather than leaking silently.
    """
    targets = [widget, getattr(widget, "viewport", lambda: None)()]
    for target in targets:
        if target is None:
            continue
        QTest.mouseRelease(target, Qt.MouseButton.LeftButton,
                           Qt.KeyboardModifier.NoModifier, QPoint(1, 1))
        if QApplication.keyboardModifiers() == Qt.KeyboardModifier.NoModifier:
            return
        QTest.mouseMove(target, QPoint(1, 1))
        if QApplication.keyboardModifiers() == Qt.KeyboardModifier.NoModifier:
            return
    raise AssertionError(
        "this module leaked a latched keyboard modifier into the session: "
        f"{int(QApplication.keyboardModifiers().value)}")


@pytest.fixture
def editor(qapp):
    w = VaultTextEdit(SimpleNamespace(data={}))
    w.resize(350, 150)
    w.setPlainText("\n".join(f"line {i}" for i in range(180)))
    w.show()
    qapp.processEvents()
    yield w
    w._cancel_line_drag()
    # T-1260: QTest.mousePress(..., Ctrl|Shift, ...) updates Qt's PROCESS-WIDE
    # modifier state, and this module's releases are delivered straight to
    # mouseReleaseEvent(), so nothing ever cleared it. Every later test that
    # read QApplication.keyboardModifiers() then saw Ctrl+Shift held down --
    # which is how the canonical NEW route in tests/test_new_empty_silos.py
    # inherited a gesture nobody made. One plain synthetic event puts the
    # global state back; the gesture under test is untouched.
    _clear_latched_modifiers(w)
    # T-1260: deleteLater() alone only QUEUES the destruction, and the queue is
    # not drained between test files. The editors stayed alive on the shared
    # QApplication, so the next FastPrompter's apply_theme() ->
    # app.setStyleSheet() repolished them -- reaching into a VaultTextEdit
    # whose owner is a dead SimpleNamespace stub and taking the process down
    # with an access violation instead of a failure. Deliver THIS widget's
    # DeferredDelete and nothing else: a process-wide drain would destroy
    # objects another test still owns.
    w.deleteLater()
    QApplication.sendPostedEvents(w, QEvent.Type.DeferredDelete)
    assert sip.isdeleted(w), "the editor survived its own retirement"


@pytest.mark.parametrize("direction", [1, -1])
@pytest.mark.parametrize("count", [1, 3])
def test_stationary_edge_scroll_and_drop(editor, monkeypatch, direction, count):
    monkeypatch.setattr(QApplication, "mouseButtons", lambda: Qt.MouseButton.LeftButton)
    bar = editor.verticalScrollBar()
    if direction < 0:
        # T-1260: the document layout is still settling right after show(), and
        # the scrollbar maximum SHRINKS when it finishes (measured 2462 -> 2380).
        # Qt clamps the value down with the range, which is indistinguishable
        # from "the autoscroll moved the view": the wait below broke on that
        # clamp during its first 40 ms slice, before the timer had ticked once,
        # so ``_line_drag_hover_block`` was never written and the next assertion
        # died on AttributeError instead of measuring the drag. Settle the range
        # first, then take the baseline.
        for _ in range(50):
            maximum = bar.maximum()
            QTest.qWait(20)
            if bar.maximum() == maximum:
                break
        bar.setValue(bar.maximum())
    source = 2 if direction > 0 else 176 - count
    editor._line_drag_source_block = (source, source + count - 1)
    editor._line_drag_active = True
    pos = QPoint(25, editor.viewport().height() - 1 if direction > 0 else 0)
    initial_block = editor.cursorForPosition(pos).blockNumber()
    before = editor.toPlainText()
    old_scroll = bar.value()
    editor._update_line_drag_autoscroll(pos)
    # The autoscroll timer ticks every 40ms. A fixed 180ms wait is fine on an
    # idle machine and a coin flip when the rest of the suite is competing for
    # the same event loop, which is exactly how this test failed in a full run
    # and passed on its own. Wait for the effect, with a ceiling.
    for _ in range(50):
        QTest.qWait(40)
        if ((bar.value() - old_scroll) * direction > 0
                and getattr(editor, "_line_drag_hover_block", None) is not None):
            break
    assert (bar.value() - old_scroll) * direction > 0
    assert (editor._line_drag_hover_block - initial_block) * direction > 0
    assert editor.toPlainText() == before
    hover = editor._line_drag_hover_block
    event = QMouseEvent(QMouseEvent.Type.MouseButtonRelease, QPointF(pos), QPointF(pos),
                        Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton,
                        Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier)
    editor.mouseReleaseEvent(event)
    assert not editor._line_drag_autoscroll_timer.isActive()
    lines = editor.toPlainText().splitlines()
    assert lines != before.splitlines()
    moved = [f"line {i}" for i in range(source, source + count)]
    start = lines.index(moved[0])
    assert lines[start:start + count] == moved
    assert abs(start - hover) <= count


def test_lost_button_cancels_without_mutation(editor, monkeypatch):
    before = editor.toPlainText()
    editor._line_drag_source_block = (0, 0)
    editor._line_drag_active = True
    editor._update_line_drag_autoscroll(QPoint(0, 0))
    monkeypatch.setattr(QApplication, "mouseButtons", lambda: Qt.MouseButton.NoButton)
    editor._line_drag_autoscroll_tick()
    assert not editor._line_drag_autoscroll_timer.isActive()
    assert editor._line_drag_source_block is None
    assert editor.toPlainText() == before


def test_plain_shift_keeps_native_selection(editor):
    QTest.mousePress(editor.viewport(), Qt.MouseButton.LeftButton,
                     Qt.KeyboardModifier.ShiftModifier, QPoint(40, 40))
    assert getattr(editor, "_line_drag_source_block", None) is None
    assert getattr(editor, "_line_drag_autoscroll_timer", None) is None
    assert editor.textCursor().hasSelection()
    QTest.mouseRelease(editor.viewport(), Qt.MouseButton.LeftButton)


def test_true_gesture_press_moves_releases_through_real_input(editor, monkeypatch):
    """Audit 4: the gesture must start from actual mouse input, not internal
    state assignment. Ctrl+Shift+LMB press -> move to the bottom edge -> the
    autoscroll timer keeps scrolling -> release moves the line."""
    monkeypatch.setattr(QApplication, "mouseButtons", lambda: Qt.MouseButton.LeftButton)
    bar = editor.verticalScrollBar()
    bar.setValue(0)
    press_pos = QPoint(60, 30)
    QTest.mousePress(editor.viewport(), Qt.MouseButton.LeftButton,
                     Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier,
                     press_pos)
    source = editor._line_drag_source_block
    assert source is not None, "Ctrl+Shift press must arm the line drag"
    assert not editor._line_drag_active
    before = editor.toPlainText()
    move_pos = QPoint(editor.viewport().width() - 10, editor.viewport().height() - 1)
    move = QMouseEvent(QMouseEvent.Type.MouseMove, QPointF(move_pos), QPointF(move_pos),
                       Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton,
                       Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier)
    editor.mouseMoveEvent(move)
    assert editor._line_drag_active, "a real move past the drag threshold activates"
    old_scroll = bar.value()
    QTest.qWait(150)
    assert bar.value() > old_scroll, "stationary pointer at the edge must scroll"
    hover = editor._line_drag_hover_block
    assert hover is not None and hover > source[1]
    assert editor.toPlainText() == before, "no text mutation before the drop"
    release = QMouseEvent(QMouseEvent.Type.MouseButtonRelease, QPointF(move_pos), QPointF(move_pos),
                          Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton,
                          Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier)
    editor.mouseReleaseEvent(release)
    assert not editor._line_drag_autoscroll_timer.isActive()
    # The dropped line must have MOVED: the source slot no longer holds it,
    # and the whole document is the expected permutation. `hover` is the
    # block under the pointer at release, so the exact result is computable:
    # the source line is removed, then re-inserted around block `hover`
    # (after it when dragged down), shifting the in-between lines up by one.
    lines = editor.toPlainText().splitlines()
    before_lines = before.splitlines()
    s = source[0]
    rest = before_lines[:s] + before_lines[s + 1:]
    expected = rest[:hover] + [before_lines[s]] + rest[hover:]
    assert lines == expected, (
        f"line {s} must land exactly at the hovered block: "
        f"hover={hover}, dropped to index "
        f"{lines.index(before_lines[s]) if before_lines[s] in lines else '?'}")
    assert before_lines[s] not in lines[s:s + 1], (
        "the source slot must no longer hold the dropped line")
    assert lines != before_lines


def test_escape_cancels_gesture_and_timer(editor, monkeypatch):
    monkeypatch.setattr(QApplication, "mouseButtons", lambda: Qt.MouseButton.LeftButton)
    QTest.mousePress(editor.viewport(), Qt.MouseButton.LeftButton,
                     Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier,
                     QPoint(60, 30))
    assert editor._line_drag_source_block is not None
    from PyQt6.QtCore import QEvent
    from PyQt6.QtGui import QKeyEvent
    editor.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape,
                                   Qt.KeyboardModifier.NoModifier))
    assert editor._line_drag_source_block is None
    assert not getattr(editor, "_line_drag_autoscroll_timer", None) or \
        not editor._line_drag_autoscroll_timer.isActive()


# -- real-input helpers ----------------------------------------------------

def _expected_after_block_move(before_lines, start, end, target):
    """Exact post-`_move_lines` ordering for a unique-line document.

    Mirrors the contract: the block travels as one unit, drops AFTER the
    target line when dragged down and BEFORE it when dragged up, and exactly
    one newline boundary is consumed/recreated. A target inside the block is
    a no-op.
    """
    if start <= target <= end:
        return list(before_lines)
    block = before_lines[start:end + 1]
    count = end - start + 1
    rest = before_lines[:start] + before_lines[end + 1:]
    if target > end:
        at = target - count + 1
    else:
        at = target
    return rest[:at] + block + rest[at:]


def _line_top(editor, number):
    block = editor.document().findBlockByNumber(number)
    cursor = editor.textCursor()
    cursor.setPosition(block.position())
    return editor.cursorRect(cursor).topLeft()


def _real_move(editor, pos):
    move = QMouseEvent(QMouseEvent.Type.MouseMove, QPointF(pos), QPointF(pos),
                       Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton,
                       Qt.KeyboardModifier.ControlModifier
                       | Qt.KeyboardModifier.ShiftModifier)
    editor.mouseMoveEvent(move)


def _real_release(editor, pos):
    release = QMouseEvent(QMouseEvent.Type.MouseButtonRelease, QPointF(pos),
                          QPointF(pos), Qt.MouseButton.LeftButton,
                          Qt.MouseButton.NoButton,
                          Qt.KeyboardModifier.ControlModifier
                          | Qt.KeyboardModifier.ShiftModifier)
    editor.mouseReleaseEvent(release)


def _permutation_holds(before_lines, result_lines, block):
    """Whole-line reorder must never lose, duplicate or corrupt content."""
    assert len(result_lines) == len(before_lines), "line count changed"
    assert sorted(result_lines) == sorted(before_lines), "content changed"
    assert result_lines.count(block[0]) == 1, "moved line duplicated/lost"


def test_true_gesture_upward_edge_autoscroll_and_drop(editor, monkeypatch):
    """Symmetric REAL-input path: drag from the lower viewport to the TOP
    edge, hold stationary, the timer scrolls up, release drops the line."""
    monkeypatch.setattr(QApplication, "mouseButtons", lambda: Qt.MouseButton.LeftButton)
    bar = editor.verticalScrollBar()
    bar.setValue(bar.maximum())
    editor.show()
    QApplication.processEvents()
    press_pos = QPoint(60, editor.viewport().height() - 30)
    QTest.mousePress(editor.viewport(), Qt.MouseButton.LeftButton,
                     Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier,
                     press_pos)
    source = editor._line_drag_source_block
    assert source is not None, "Ctrl+Shift press must arm the line drag"
    before = editor.toPlainText()
    before_lines = before.splitlines()
    top_hover_start = editor.cursorForPosition(QPoint(25, 0)).blockNumber()
    edge_pos = QPoint(editor.viewport().width() - 10, 0)
    _real_move(editor, edge_pos)
    assert editor._line_drag_active, "a real move past the threshold activates"
    old_scroll = bar.value()
    QTest.qWait(200)
    assert bar.value() < old_scroll, "stationary pointer at the TOP edge must scroll up"
    hover = editor._line_drag_hover_block
    assert hover is not None and hover < top_hover_start, (
        "hover must travel above the initially visible range")
    assert editor.toPlainText() == before, "no text mutation before the drop"
    _real_release(editor, edge_pos)
    assert not editor._line_drag_autoscroll_timer.isActive()
    lines = editor.toPlainText().splitlines()
    s = source[0]
    _permutation_holds(before_lines, lines, [before_lines[s]])
    assert lines == _expected_after_block_move(
        before_lines, s, s, hover), (
        f"line {s} must land exactly at the hovered block (hover={hover})")


def test_true_gesture_multiline_block_moves_as_one(editor, monkeypatch):
    """REAL selection -> pickup -> autoscroll wiring for a 3-line block:
    select with QTextCursor, press INSIDE the selection, drag to the edge,
    hold, release. The block must travel as ONE unit."""
    monkeypatch.setattr(QApplication, "mouseButtons", lambda: Qt.MouseButton.LeftButton)
    bar = editor.verticalScrollBar()
    bar.setValue(0)
    doc = editor.document()
    start, end = 4, 6
    cursor = editor.textCursor()
    cursor.setPosition(doc.findBlockByNumber(start).position())
    b3 = doc.findBlockByNumber(end)
    cursor.setPosition(b3.position() + b3.length() - 1,
                       QTextCursor.MoveMode.KeepAnchor)
    editor.setTextCursor(cursor)
    press_pos = _line_top(editor, 5) + QPoint(5, 2)
    QTest.mousePress(editor.viewport(), Qt.MouseButton.LeftButton,
                     Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier,
                     press_pos)
    assert editor._line_drag_source_block == (start, end), (
        "a press inside a selection must pick the whole selected range")
    before = editor.toPlainText()
    before_lines = before.splitlines()
    edge_pos = QPoint(editor.viewport().width() - 10,
                      editor.viewport().height() - 1)
    _real_move(editor, edge_pos)
    assert editor._line_drag_active
    old_scroll = bar.value()
    QTest.qWait(200)
    assert bar.value() > old_scroll, "stationary pointer at the edge must scroll"
    hover = editor._line_drag_hover_block
    assert hover is not None and hover > end
    assert editor.toPlainText() == before, "no text mutation before the drop"
    _real_release(editor, edge_pos)
    assert not editor._line_drag_autoscroll_timer.isActive()
    lines = editor.toPlainText().splitlines()
    _permutation_holds(before_lines, lines, before_lines[start:end + 1])
    block = [f"line {i}" for i in range(start, end + 1)]
    at = lines.index(block[0])
    assert lines[at:at + 3] == block, "the 3 lines must stay contiguous, in order"
    assert at == hover - 3 + 1, (
        f"the block must land after the hovered block: at={at}, hover={hover}")


def test_drop_inside_source_range_is_noop(editor, monkeypatch):
    """Pin the _move_lines guard through the REAL gesture: releasing with the
    hover inside the selected block must not touch the document at all —
    no remove/reinsert round-trip, no newline churn."""
    monkeypatch.setattr(QApplication, "mouseButtons", lambda: Qt.MouseButton.LeftButton)
    editor.verticalScrollBar().setValue(0)
    doc = editor.document()
    start, end = 10, 12
    cursor = editor.textCursor()
    cursor.setPosition(doc.findBlockByNumber(start).position())
    b3 = doc.findBlockByNumber(end)
    cursor.setPosition(b3.position() + b3.length() - 1,
                       QTextCursor.MoveMode.KeepAnchor)
    editor.setTextCursor(cursor)
    press_pos = _line_top(editor, 11) + QPoint(5, 2)
    QTest.mousePress(editor.viewport(), Qt.MouseButton.LeftButton,
                     Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier,
                     press_pos)
    assert editor._line_drag_source_block == (start, end)
    # activate the drag, then bring the pointer back INSIDE the block
    _real_move(editor, QPoint(editor.viewport().width() - 10,
                              editor.viewport().height() - 1))
    assert editor._line_drag_active
    inside_pos = _line_top(editor, 12) + QPoint(5, 2)
    _real_move(editor, inside_pos)
    assert editor._line_drag_hover_block in (start, start + 1, end)
    before = editor.toPlainText()
    _real_release(editor, inside_pos)
    assert editor.toPlainText() == before, (
        "dropping inside the source range must be a no-op")
    # direct pin of the guard for every interior target
    for target in (start, start + 1, end):
        editor._move_lines(start, end, target)
        assert editor.toPlainText() == before


def test_edge_timer_stops_when_pointer_returns_to_center(editor, monkeypatch):
    """Returning the pointer to the center stops edge scrolling but must NOT
    cancel the drag: the block stays picked up and another edge re-arms."""
    monkeypatch.setattr(QApplication, "mouseButtons", lambda: Qt.MouseButton.LeftButton)
    bar = editor.verticalScrollBar()
    bar.setValue(0)
    QTest.mousePress(editor.viewport(), Qt.MouseButton.LeftButton,
                     Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier,
                     QPoint(60, 30))
    before = editor.toPlainText()
    bottom = QPoint(editor.viewport().width() - 10, editor.viewport().height() - 1)
    _real_move(editor, bottom)
    assert editor._line_drag_active
    QTest.qWait(120)
    assert bar.value() > 0, "edge drag must scroll"
    assert editor._line_drag_autoscroll_timer.isActive()
    center = QPoint(editor.viewport().width() // 2, editor.viewport().height() // 2)
    _real_move(editor, center)
    assert not editor._line_drag_autoscroll_timer.isActive(), (
        "pointer back in the center must stop the autoscroll timer")
    assert editor._line_drag_source_block is not None, (
        "stopping edge scrolling is not cancelling the drag")
    assert editor._line_drag_active
    held_scroll = bar.value()
    QTest.qWait(120)  # > 2 timer intervals: a running timer would move the bar
    assert bar.value() == held_scroll, "the scrollbar must not move from the center"
    assert editor.toPlainText() == before
    _real_move(editor, QPoint(10, 0))
    assert editor._line_drag_autoscroll_timer.isActive(), (
        "moving to another edge must restart the timer")
    QTest.mouseRelease(editor.viewport(), Qt.MouseButton.LeftButton,
                       Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier,
                       QPoint(10, 0))


@pytest.mark.parametrize("edge", ["bottom", "top"])
def test_scroll_limits_hold_safely(editor, monkeypatch, edge):
    """At scrollbar.maximum() (bottom hold) and minimum() (top hold) the tick
    must stay safe: no mutation, a valid hover block, a clean release."""
    monkeypatch.setattr(QApplication, "mouseButtons", lambda: Qt.MouseButton.LeftButton)
    bar = editor.verticalScrollBar()
    if edge == "bottom":
        bar.setValue(bar.maximum())
        press_pos = QPoint(60, editor.viewport().height() - 10)
        edge_pos = QPoint(editor.viewport().width() - 10, editor.viewport().height() - 1)
    else:
        bar.setValue(bar.minimum())
        press_pos = QPoint(60, 10)
        edge_pos = QPoint(editor.viewport().width() - 10, 0)
    QTest.mousePress(editor.viewport(), Qt.MouseButton.LeftButton,
                     Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier,
                     press_pos)
    source = editor._line_drag_source_block
    assert source is not None
    _real_move(editor, edge_pos)
    assert editor._line_drag_active
    before = editor.toPlainText()
    for _ in range(20):
        editor._line_drag_autoscroll_tick()
    assert bar.value() in (bar.minimum(), bar.maximum())
    assert editor._line_drag_hover_block is not None, "hover must stay valid"
    assert editor.toPlainText() == before, "no document mutation while pinned"
    _real_release(editor, edge_pos)
    assert not editor._line_drag_autoscroll_timer.isActive()
    assert editor.toPlainText() == before, "release at the scroll limit stays safe"


def test_move_lines_permutation_matrix(editor):
    """`_move_lines` information safety across the whole boundary matrix:
    every move preserves the line multiset, lands the block exactly where the
    contract says, and never invents or eats a line boundary."""
    editor.setPlainText("\n".join(f"line {i}" for i in range(40)))
    before_lines = editor.toPlainText().splitlines()
    cases = [
        (0, 0, 5),      # first line down
        (0, 0, 39),     # first line to the end
        (39, 39, 0),    # last line to the top
        (20, 20, 10),   # middle single up
        (10, 10, 30),   # middle single down
        (10, 12, 30),   # 3-line block down
        (10, 12, 3),    # 3-line block up
        (38, 39, 5),    # block ending at the last line
    ]
    for start, end, target in cases:
        editor.setPlainText("\n".join(f"line {i}" for i in range(40)))
        expected = _expected_after_block_move(before_lines, start, end, target)
        editor._move_lines(start, end, target)
        lines = editor.toPlainText().splitlines()
        _permutation_holds(before_lines, lines, before_lines[start:end + 1])
        assert lines == expected, (
            f"move ({start},{end}) -> {target} corrupted the order")
        at = lines.index(before_lines[start])
        assert lines[at:end - start + at + 1] == before_lines[start:end + 1], (
            f"move ({start},{end}) -> {target}: block not contiguous/in order")
