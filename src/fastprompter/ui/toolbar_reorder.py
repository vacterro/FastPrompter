"""Drag-to-reorder for the header toolbar.

The header is a token list persisted in data["toolbar_order"]; the engine
here rebuilds the QHBoxLayout from that list (self-healing) and a QObject
event filter turns button drags into reorders when the user enables
"Customize Toolbar" in settings. Buttons carry stable string tokens; the
two flexible spacers are the "<stretch>" tokens and the counter divider is
"<sep>" — those stay put so the left / centre / right zones survive.
"""

from PyQt6.QtCore import QEvent, QMimeData, QObject, Qt
from PyQt6.QtGui import QDrag
from PyQt6.QtWidgets import QApplication, QPushButton

# Default header order AFTER the fixed sidebar-toggle anchor (index 0).
DEFAULT_TOOLBAR_ORDER = [
    "btn_settings_toggle", "btn_pin_top", "btn_line_nums",
    "cat_combo", "btn_new", "btn_save", "btn_home", "btn_end",
    "btn_trash", "btn_toggle_search", "btn_toggle_snippets", "btn_arc_snip", "btn_toggle_archive", 
    "btn_project_folder", "btn_project_run", "btn_files",
    "<stretch>",
    "btn_bold", "btn_italic", "btn_under", "btn_strike", "btn_header", "btn_quote", "btn_overflow",
    "btn_clear_fmt", "btn_add_line", "btn_bullet_toggle", "btn_copy", "btn_clear",
    "<stretch>",
    "analog_clock", "lbl_date", "lbl_timer",
    "<sep>", "lbl_line_count", "btn_settings_toggle_right", "btn_help",
]

_MIME = "application/x-fastprompter-toolbar-token"


class ToolbarReorderFilter(QObject):
    """Installed on the header widget + its movable buttons. Only active
    while data['customize_toolbar'] == 'True'."""

    def __init__(self, main_win):
        super().__init__(main_win)
        self.main_win = main_win
        self._press_pos = None
        self._press_token = None

    def _enabled(self):
        return self.main_win.data.get("customize_toolbar", "False") == "True"

    def eventFilter(self, obj, event):
        if not self._enabled():
            return False
        et = event.type()
        # Header widget is the drop target
        if obj is self.main_win.header_widget:
            if et == QEvent.Type.DragEnter and event.mimeData().hasFormat(_MIME):
                event.acceptProposedAction()
                return True
            if et == QEvent.Type.DragMove and event.mimeData().hasFormat(_MIME):
                event.acceptProposedAction()
                return True
            if et == QEvent.Type.Drop and event.mimeData().hasFormat(_MIME):
                token = bytes(event.mimeData().data(_MIME)).decode("utf-8")
                x = event.position().toPoint().x()
                self.main_win.reorder_toolbar_token(token, x)
                event.acceptProposedAction()
                return True
            return False
        # Buttons are the drag sources
        if isinstance(obj, QPushButton):
            token = self.main_win.toolbar_token_of(obj)
            if token is None:
                return False
            if et == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
                self._press_pos = event.position().toPoint()
                self._press_token = token
                return True  # swallow the click while customizing
            if et == QEvent.Type.MouseMove and self._press_token == token and self._press_pos:
                if (event.position().toPoint() - self._press_pos).manhattanLength() \
                        >= QApplication.startDragDistance():
                    self._start_drag(obj, token)
                return True
            if et == QEvent.Type.MouseButtonRelease:
                self._press_pos = None
                self._press_token = None
                return True
        return False

    def _start_drag(self, button, token):
        drag = QDrag(button)
        mime = QMimeData()
        mime.setData(_MIME, token.encode("utf-8"))
        drag.setMimeData(mime)
        pm = button.grab()
        drag.setPixmap(pm)
        self._press_pos = None
        self._press_token = None
        drag.exec(Qt.DropAction.MoveAction)


def install_toolbar_reorder(main_win):
    """Wire the filter onto the header + movable buttons and set cursors."""
    flt = ToolbarReorderFilter(main_win)
    main_win._toolbar_reorder_filter = flt
    main_win.header_widget.setAcceptDrops(True)
    main_win.header_widget.installEventFilter(flt)
    main_win.refresh_toolbar_customize_state()
