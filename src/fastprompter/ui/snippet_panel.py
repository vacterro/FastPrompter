from PyQt6.QtWidgets import QWidget, QHBoxLayout, QVBoxLayout, QPushButton, QApplication
from PyQt6.QtCore import Qt, QMimeData
from PyQt6.QtGui import QDrag
from fastprompter.theme.themes import THEMES
from fastprompter.core.config import extract_bg, extract_color

class DraggableButton(QPushButton):
    def __init__(self, main_win, parent=None):
        super().__init__("", parent)
        self.cat, self.global_idx, self.full_text = "", -1, ""
        self.main_win, self.drag_start, self._dragging = main_win, None, False
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self.show_menu)

    def update_data(self, text_label, cat, global_idx, full_text, color, font_family):
        self.setText(text_label)
        self.cat, self.global_idx, self.full_text = cat, global_idx, full_text
        
        is_editing = getattr(self.main_win, 'editing_snippet', None) == (cat, global_idx)
        
        if is_editing:
            border_norm = "border: 2px solid; border-top-color: #000000; border-left-color: #000000; border-right-color: #808080; border-bottom-color: #808080;"
            padding_norm = "padding: 3px 3px 1px 5px;"
        else:
            border_norm = "border: 2px solid; border-top-color: #808080; border-left-color: #808080; border-right-color: #000000; border-bottom-color: #000000;"
            padding_norm = "padding: 2px 4px;"
            
        border_press = "border: 2px solid; border-top-color: #000000; border-left-color: #000000; border-right-color: #808080; border-bottom-color: #808080;"
        
        style = f"""
        QPushButton {{
            background-color: {color};
            font-size: 10px;
            {padding_norm}
            font-family: '{font_family}';
            text-align: left;
            {border_norm}
        }}
        QPushButton:pressed {{
            background-color: #141414;
            padding: 3px 3px 1px 5px;
            color: #5a7a96;
            {border_press}
        }}
        """
        self.setStyleSheet(style)
        self.show()

    def show_menu(self, pos):
        from PyQt6.QtWidgets import QMenu
        menu = QMenu(self)
        menu.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        menu.setFont(QApplication.font())
        menu.addAction("Copy", lambda: self.main_win.copy_snippet_to_clipboard(self.full_text))
        menu.addAction("Rename", lambda: self.main_win.rename_snippet(self.cat, self.global_idx))
        menu.addAction("Delete", lambda: self.main_win.prompt_delete_snippet(self.cat, self.global_idx))
        self.main_win.ignore_focus_loss = True
        try:
            menu.exec(self.mapToGlobal(pos))
        finally:
            self.main_win.ignore_focus_loss = False
        self.main_win.activateWindow()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.RightButton and e.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.main_win.prompt_delete_snippet(self.cat, self.global_idx)
            e.accept()
            return
        if e.button() == Qt.MouseButton.LeftButton:
            self.drag_start, self._dragging = e.pos(), False
            e.accept()
            return
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if getattr(self.main_win, 'is_locked', False) or not (e.buttons() & Qt.MouseButton.LeftButton) or not self.drag_start: return
        if (e.pos() - self.drag_start).manhattanLength() < QApplication.startDragDistance(): return
        self._dragging = True
        drag, mime = QDrag(self), QMimeData()
        mime.setText(f"{self.cat}:{self.global_idx}")
        drag.setMimeData(mime)
        drag.exec(Qt.DropAction.MoveAction)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton and not self._dragging:
            self.main_win.load_snippet_for_edit(self.cat, self.global_idx)
            e.accept()
            return
        super().mouseReleaseEvent(e)

class SnippetWidget(QWidget):
    def __init__(self, main_win, parent=None):
        super().__init__(parent)
        self.main_win = main_win
        self.layout = QHBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(1)

        self.main_btn = DraggableButton(main_win, self)
        from PyQt6.QtWidgets import QSizePolicy
        self.main_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        
        self.btn_top = QPushButton("▲")
        self.btn_ins = QPushButton("▶")
        self.btn_bot = QPushButton("▼")
        
        self.layout.addWidget(self.main_btn)
        for btn in (self.btn_top, self.btn_ins, self.btn_bot):
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(self.on_action_clicked)
            self.layout.addWidget(btn)

    def update_data(self, text_label, cat, global_idx, full_text, color, font_family, scale):
        self.main_btn.update_data(text_label, cat, global_idx, full_text, color, font_family)
        
        theme_name = self.main_win.data.get("theme", "Original Gold")
        theme = THEMES.get(theme_name, THEMES["Original Gold"])
        bg = extract_bg(theme.get('mini_settings', '')) or '#2b2b2b'
        fg = extract_color(theme.get('lbl_title', '')) or '#bfa65e'
        border = extract_color(theme.get('btn_save', '')) or '#4a4a4a'
        
        btn_size = max(14, int(round(22 * scale)))
        self.main_btn.setFixedHeight(btn_size)
        
        btn_style = f"background-color:{bg}; color:{fg}; border: 1px solid {border}; font-size:{max(8, int(round(9*scale)))}px; font-weight:bold; padding:0;"
        
        for btn in (self.btn_top, self.btn_ins, self.btn_bot):
            btn.setStyleSheet(btn_style)
            btn.setFixedSize(max(14, int(round(18 * scale))), btn_size)
        
        self.show()

    def on_action_clicked(self):
        sender = self.sender()
        if sender == self.btn_top: self.main_win.insert_snippet_text(self.main_btn.full_text, "top")
        elif sender == self.btn_ins: self.main_win.insert_snippet_text(self.main_btn.full_text, "ins")
        elif sender == self.btn_bot: self.main_win.insert_snippet_text(self.main_btn.full_text, "bot")

class DropVerticalWidget(QWidget):
    def __init__(self, main_win):
        super().__init__()
        self.setAcceptDrops(True)
        self.main_win = main_win
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(2)
        self.layout.setAlignment(Qt.AlignmentFlag.AlignTop)

    def dragEnterEvent(self, e):
        cat = self.main_win.get_current_category()
        if e.mimeData().hasText() and e.mimeData().text().startswith(cat + ":"): e.acceptProposedAction()

    def dropEvent(self, e):
        cat = self.main_win.get_current_category()
        pos, source_data = e.position().toPoint(), e.mimeData().text().split(':')
        if len(source_data) != 2 or source_data[0] != cat: e.ignore(); return
        source_idx, page = int(source_data[1]), self.main_win.current_pages.get(cat, 0)
        
        target_view_idx = -1
        for i in range(self.layout.count()):
            item = self.layout.itemAt(i).widget()
            if item and item.isVisible() and item.geometry().contains(pos): target_view_idx = i; break
        
        if target_view_idx == -1:
            visible_count = sum(1 for i in range(self.layout.count()) if self.layout.itemAt(i).widget().isVisible())
            target_view_idx = 0 if pos.y() < self.height() // 2 else visible_count - 1
            
        target_global_idx = page * 10 + max(0, min(9, target_view_idx))
        self.main_win.move_preset_to_index(cat, source_idx, target_global_idx)
        e.acceptProposedAction()

class DraggableSiloButton(QPushButton):
    def __init__(self, main_win, parent=None):
        super().__init__("", parent)
        self.global_idx, self.main_win, self.drag_start, self._dragging = -1, main_win, None, False
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self.show_menu)

    def update_data(self, text_label, global_idx, bg_color):
        self.setText(text_label)
        self.global_idx = global_idx
        # Active color check logic
        theme_name = self.main_win.data.get("theme", "Original Gold")
        theme = THEMES.get(theme_name, THEMES["Original Gold"])
        active_color = theme.get("active_temp_color", "#364757")
        
        # Selected = sunken (inset), Unselected = raised (outset)
        if bg_color == active_color:
            border = "border: 2px solid; border-top-color: #000000; border-left-color: #000000; border-right-color: #808080; border-bottom-color: #808080;"
            padding = "padding:3px 3px 1px 5px;" # shift text right/down for sunken feel
        else:
            border = "border: 2px solid; border-top-color: #808080; border-left-color: #808080; border-right-color: #000000; border-bottom-color: #000000;"
            padding = "padding:2px 4px;"
            
        self.setStyleSheet(f"font-size:10px; {padding} font-family:Verdana; text-align:left; background-color:{bg_color}; {border}")
        self.show()

    def show_menu(self, pos):
        self.main_win.show_temp_menu(self.global_idx, self.mapToGlobal(pos))

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.drag_start, self._dragging = e.pos(), False
            e.accept()
            return
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if getattr(self.main_win, 'is_locked', False) or not (e.buttons() & Qt.MouseButton.LeftButton) or not self.drag_start: return
        if (e.pos() - self.drag_start).manhattanLength() < QApplication.startDragDistance(): return
        self._dragging = True
        drag, mime = QDrag(self), QMimeData()
        mime.setText(f"silo:{self.global_idx}")
        drag.setMimeData(mime)
        drag.exec(Qt.DropAction.MoveAction)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton and not self._dragging:
            self.main_win._switch_to_slot(self.global_idx)
            e.accept()
            return
        super().mouseReleaseEvent(e)

class SiloDropWidget(QWidget):
    def __init__(self, main_win):
        super().__init__()
        self.setAcceptDrops(True)
        self.main_win = main_win
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(2)
        self.layout.setAlignment(Qt.AlignmentFlag.AlignTop)

    def dragEnterEvent(self, e):
        if e.mimeData().hasText() and e.mimeData().text().startswith("silo:"): e.acceptProposedAction()

    def dropEvent(self, e):
        mime = e.mimeData()
        if not mime.hasText(): return
        data, pos = mime.text().split(':'), e.position().toPoint()
        if len(data) != 2 or data[0] != "silo": return
        
        start_idx, target_view_idx = self.main_win.silo_page * 10, -1
        for i in range(self.layout.count()):
            btn = self.layout.itemAt(i).widget()
            if btn and btn.isVisible() and btn.geometry().contains(pos): target_view_idx = i; break
        
        if target_view_idx == -1:
            visible_count = sum(1 for i in range(self.layout.count()) if self.layout.itemAt(i).widget().isVisible())
            target_view_idx = 0 if pos.y() < self.height() // 2 else visible_count - 1

        target_global_idx = start_idx + target_view_idx
        if int(data[1]) != target_global_idx: self.main_win.swap_temp_slots(int(data[1]), target_global_idx)
        e.acceptProposedAction()
