from types import SimpleNamespace

from PyQt6.QtCore import QEvent, QPointF, QRect, QRectF, Qt
from PyQt6.QtGui import QColor, QImage, QMouseEvent, QPainter

from fastprompter.ui.editor import (
    VaultTextEdit,
    _paint_task_checkbox,
    _task_checkbox_rect,
)


def _render(checked):
    image = QImage(24, 24, QImage.Format.Format_ARGB32)
    image.fill(QColor("#010203"))
    painter = QPainter(image)
    rect = QRect(6, 6, 12, 12)
    _paint_task_checkbox(painter, rect, checked)
    painter.end()
    return image, rect


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
    )


def test_task_checkbox_rect_is_integer_bounded_and_centered():
    for height in (14, 15, 16, 17):
        marker = QRectF(5.4, 7.6, 30.0, float(height))
        rect = _task_checkbox_rect(marker)
        bounds = marker.toRect()
        assert isinstance(rect, QRect)
        assert bounds.contains(rect)
        assert abs(rect.center().x() - bounds.center().x()) <= 1
        assert abs(rect.center().y() - bounds.center().y()) <= 1
        assert 9 <= rect.width() == rect.height() <= 14


def test_task_checkbox_pixels_are_square_and_state_stable():
    unchecked, unchecked_rect = _render(False)
    checked, checked_rect = _render(True)
    background = QColor("#010203").rgba()
    white = QColor("#ffffff").rgba()

    assert unchecked_rect == checked_rect
    for image in (unchecked, checked):
        for point in (
            image.pixel(unchecked_rect.topLeft()),
            image.pixel(unchecked_rect.topRight()),
            image.pixel(unchecked_rect.bottomLeft()),
            image.pixel(unchecked_rect.bottomRight()),
        ):
            assert point != background
        for x in range(unchecked_rect.left(), unchecked_rect.right() + 1):
            assert QColor.fromRgba(image.pixel(x, unchecked_rect.top() - 1)).alpha() == 255
            assert image.pixel(x, unchecked_rect.top() - 1) == background

    assert white not in {
        unchecked.pixel(x, y)
        for y in range(unchecked_rect.top(), unchecked_rect.bottom() + 1)
        for x in range(unchecked_rect.left(), unchecked_rect.right() + 1)
    }
    assert white in {
        checked.pixel(x, y)
        for y in range(checked_rect.top(), checked_rect.bottom() + 1)
        for x in range(checked_rect.left(), checked_rect.right() + 1)
    }
    check_points = [
        (x, y)
        for y in range(checked_rect.top(), checked_rect.bottom() + 1)
        for x in range(checked_rect.left(), checked_rect.right() + 1)
        if checked.pixel(x, y) == white
    ]
    check_center_x = sum(x for x, _y in check_points) / len(check_points)
    assert check_center_x >= checked_rect.center().x()


def test_editor_checkbox_toggle_preserves_layout_and_other_lines(qapp):
    editor = VaultTextEdit(_main_window())
    editor.setPlainText("[ ] one\n[x] ~~two~~\n[ ] three\n[x] ~~four~~")
    before_blocks = editor.document().blockCount()
    editor.moveCursor(editor.textCursor().MoveOperation.Start)
    editor._toggle_checkboxes()

    assert editor.toPlainText() == "[x] ~~one~~\n[x] ~~two~~\n[ ] three\n[x] ~~four~~"
    assert editor.document().blockCount() == before_blocks
    assert editor._doc_has_checkbox is True


def test_large_document_checkbox_rendering_is_not_skipped():
    import inspect

    source = inspect.getsource(VaultTextEdit.paintEvent)
    assert "if self._doc_has_checkbox:" in source
    assert "self._doc_has_checkbox and not is_large" not in source


def test_middle_double_click_is_processed_as_another_checkbox_click(qapp):
    editor = VaultTextEdit(_main_window())
    editor.setPlainText("buy milk")
    pos = QPointF(editor.cursorRect(editor.textCursor()).center())

    def click(kind):
        event = QMouseEvent(
            kind,
            pos,
            Qt.MouseButton.MiddleButton,
            Qt.MouseButton.MiddleButton,
            Qt.KeyboardModifier.NoModifier,
        )
        if kind == QEvent.Type.MouseButtonDblClick:
            editor.mouseDoubleClickEvent(event)
        else:
            editor.mousePressEvent(event)

    click(QEvent.Type.MouseButtonPress)
    assert editor.toPlainText() == "[x] ~~buy milk~~"
    click(QEvent.Type.MouseButtonDblClick)
    assert editor.toPlainText() == "[ ] buy milk"
    click(QEvent.Type.MouseButtonPress)
    assert editor.toPlainText() == "buy milk"
