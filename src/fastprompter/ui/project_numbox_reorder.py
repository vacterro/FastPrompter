"""Drag-to-reorder for the project number-box row (box/digits mode).

The dropdown face of the project list reorders through the right-click menu
(Move Left / Move Right). The number-box face is a QGridLayout of numbered
QPushButtons; this filter turns a button drag into a reorder by mapping the
drop position back to the target button's visible index and calling the same
``_move_project`` the menu uses. Left-click still selects the project — a
drag only starts once the pointer passes the platform drag distance, so a
plain click is never eaten.
"""

from PyQt6.QtCore import QEvent, QMimeData, QObject, Qt
from PyQt6.QtGui import QDrag
from PyQt6.QtWidgets import QApplication, QPushButton

_MIME = "application/x-fastprompter-project-numbox"


class ProjectNumboxReorderFilter(QObject):
    """Installed on the cat_numbox container + each number button."""

    def __init__(self, main_win):
        super().__init__(main_win)
        self.main_win = main_win
        self._press_pos = None
        self._press_idx = None

    def _index_of(self, obj):
        buttons = getattr(self.main_win, "_cat_num_buttons", ())
        for i, btn in enumerate(buttons):
            if btn is obj:
                return i
        return None

    def _drop_index(self, x, y):
        """Visible index of the button under (x, y) in container coords."""
        buttons = getattr(self.main_win, "_cat_num_buttons", ())
        for i, btn in enumerate(buttons):
            g = btn.geometry()
            if g.contains(x, y):
                return i
        return None

    def eventFilter(self, obj, event):
        et = event.type()
        box = getattr(self.main_win, "cat_numbox", None)
        # Container is the drop target.
        if obj is box:
            if et == QEvent.Type.DragEnter and event.mimeData().hasFormat(_MIME):
                event.acceptProposedAction()
                return True
            if et == QEvent.Type.DragMove and event.mimeData().hasFormat(_MIME):
                event.acceptProposedAction()
                return True
            if et == QEvent.Type.Drop and event.mimeData().hasFormat(_MIME):
                src = int(bytes(event.mimeData().data(_MIME)).decode("utf-8"))
                pt = event.position().toPoint()
                dst = self._drop_index(pt.x(), pt.y())
                if dst is not None and dst != src:
                    # _move_project steps one slot at a time and keeps the
                    # dragged project selected; walk it to the target.
                    step = 1 if dst > src else -1
                    for cur in range(src, dst, step):
                        self.main_win._move_project(cur, step)
                event.acceptProposedAction()
                return True
            return False
        # Buttons are the drag sources.
        if isinstance(obj, QPushButton):
            idx = self._index_of(obj)
            if idx is None:
                return False
            if (et == QEvent.Type.MouseButtonPress
                    and event.button() == Qt.MouseButton.LeftButton):
                self._press_pos = event.position().toPoint()
                self._press_idx = idx
                return False  # let the click through so selection still works
            if (et == QEvent.Type.MouseMove and self._press_idx == idx
                    and self._press_pos is not None):
                if (event.position().toPoint() - self._press_pos).manhattanLength() \
                        >= QApplication.startDragDistance():
                    self._start_drag(obj, idx)
                    return True
            if et == QEvent.Type.MouseButtonRelease:
                self._press_pos = None
                self._press_idx = None
        return False

    def _start_drag(self, button, idx):
        drag = QDrag(button)
        mime = QMimeData()
        mime.setData(_MIME, str(idx).encode("utf-8"))
        drag.setMimeData(mime)
        drag.setPixmap(button.grab())
        self._press_pos = None
        self._press_idx = None
        drag.exec(Qt.DropAction.MoveAction)


def install_project_numbox_reorder(main_win):
    """Create the filter and mark the container a drop target.

    Per-button installation happens in ``_rebuild_cat_numbox`` because the
    buttons are recreated on every rebuild; the container is stable so it is
    wired once here."""
    box = getattr(main_win, "cat_numbox", None)
    if box is None:
        return None
    flt = ProjectNumboxReorderFilter(main_win)
    main_win._project_numbox_reorder_filter = flt
    box.setAcceptDrops(True)
    box.installEventFilter(flt)
    return flt
