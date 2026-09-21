"""Window edge resizer for frameless FastPrompter windows.

Provides a draggable resize handle for each edge and corner
of a frameless QWidget or QMainWindow.
"""

from PyQt6 import sip
from PyQt6.QtCore import QRect, Qt
from PyQt6.QtWidgets import QWidget

_is_deleted = sip.isdeleted


class EdgeResizer(QWidget):
    """A transparent resize handle attached to an edge of a target widget.

    Usage::

        resizer = EdgeResizer(self, "left")
        resizer = EdgeResizer(self, "bottomright")
    """

    def __init__(self, target: QWidget, edge: str) -> None:
        super().__init__(target)
        self.target: QWidget = target
        self.edge: str = edge
        self.pressed: bool = False
        self.mouse_start = None
        self.target_rect = None

        if edge in ("left", "right"):
            self._resize_cursor = Qt.CursorShape.SizeHorCursor
        elif edge in ("top", "bottom"):
            self._resize_cursor = Qt.CursorShape.SizeVerCursor
        elif edge in ("topleft", "bottomright"):
            self._resize_cursor = Qt.CursorShape.SizeFDiagCursor
        elif edge in ("topright", "bottomleft"):
            self._resize_cursor = Qt.CursorShape.SizeBDiagCursor
        else:
            self._resize_cursor = Qt.CursorShape.ArrowCursor
        self.setCursor(self._resize_cursor)

    def _show_static_resize_cursor(self) -> None:
        if _is_deleted(self.target):
            return
        apply_shape = getattr(self.target, "apply_static_cursor_shape", None)
        if callable(apply_shape):
            apply_shape(self._resize_cursor)

    def _restore_static_cursor(self) -> None:
        if _is_deleted(self.target):
            return
        apply_static = getattr(self.target, "apply_static_cursor", None)
        if callable(apply_static):
            apply_static()

    def enterEvent(self, event) -> None:
        self._show_static_resize_cursor()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        if not self.pressed:
            self._restore_static_cursor()
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:
        if _is_deleted(self.target):
            return
        if event.button() == Qt.MouseButton.LeftButton:
            self._show_static_resize_cursor()
            self.pressed = True
            self.mouse_start = event.globalPosition().toPoint()
            self.target_rect = self.target.geometry()

    def mouseReleaseEvent(self, event) -> None:
        self.pressed = False
        if not self.rect().contains(event.position().toPoint()):
            self._restore_static_cursor()

    def mouseMoveEvent(self, event) -> None:
        if not self.pressed or _is_deleted(self.target):
            return
        delta = event.globalPosition().toPoint() - self.mouse_start
        rect = QRect(self.target_rect)
        if "left" in self.edge:
            max_dx = rect.width() - self.target.minimumWidth()
            clamped = min(delta.x(), max_dx)
            rect.setLeft(rect.left() + clamped)
        if "right" in self.edge:
            rect.setWidth(max(self.target.minimumWidth(), rect.width() + delta.x()))
        if "top" in self.edge:
            max_dy = rect.height() - self.target.minimumHeight()
            clamped = min(delta.y(), max_dy)
            rect.setTop(rect.top() + clamped)
        if "bottom" in self.edge:
            rect.setHeight(max(self.target.minimumHeight(), rect.height() + delta.y()))
        self.target.setGeometry(rect)
