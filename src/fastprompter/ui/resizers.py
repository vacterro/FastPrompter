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
            self.setCursor(Qt.CursorShape.SizeHorCursor)
        elif edge in ("top", "bottom"):
            self.setCursor(Qt.CursorShape.SizeVerCursor)
        elif edge in ("topleft", "bottomright"):
            self.setCursor(Qt.CursorShape.SizeFDiagCursor)
        elif edge in ("topright", "bottomleft"):
            self.setCursor(Qt.CursorShape.SizeBDiagCursor)

    def mousePressEvent(self, event) -> None:
        if _is_deleted(self.target):
            return
        if event.button() == Qt.MouseButton.LeftButton:
            self.pressed = True
            self.mouse_start = event.globalPosition().toPoint()
            self.target_rect = self.target.geometry()

    def mouseReleaseEvent(self, event) -> None:
        self.pressed = False

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
