from PyQt6.QtWidgets import QWidget, QHBoxLayout, QVBoxLayout, QPushButton, QApplication
from PyQt6.QtCore import Qt, QMimeData
from PyQt6.QtGui import QDrag
from fastprompter.theme.themes import THEMES
from fastprompter.core.config import extract_bg, extract_color

class DraggableButton(QPushButton):
    def __init__(self, main_win, parent=None):
        super().__init__("", parent)
        self.cat, self.global_idx, self.full_text = "", -1, ""
        self.full_name = ""
        self.main_win, self.drag_start, self._dragging = main_win, None, False
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self.show_menu)

    def sizeHint(self):
        from PyQt6.QtCore import QSize
        return QSize(10, super().sizeHint().height())

    def minimumSizeHint(self):
        from PyQt6.QtCore import QSize
        return QSize(10, super().minimumSizeHint().height())

    def update_data(self, text_label, cat, global_idx, full_text, color, font_family, scale=1.0):
        is_editing = getattr(self.main_win, 'editing_snippet', None) == (cat, global_idx)
        current_state = (text_label, cat, global_idx, full_text, color, font_family, scale, is_editing)
        if getattr(self, '_last_state', None) == current_state:
            self.show()
            return
        self._last_state = current_state
        
        self.full_name = text_label
        self.cat, self.global_idx, self.full_text = cat, global_idx, full_text
        
        # Apply font scaling safely
        from PyQt6.QtGui import QFont
        f = QFont(font_family)
        base_size = 9 # base size in points
        f.setPointSizeF(max(7.0, base_size * scale))
        self.setFont(f)
        
        self._update_text()
        
        
        if is_editing:
            border_norm = "border: 2px solid; border-top-color: #0a0a0a; border-left-color: #0a0a0a; border-right-color: #4d4d4d; border-bottom-color: #4d4d4d;"
            padding_norm = "padding: 3px 3px 1px 5px;"
            # Fetch custom color for editing background if available
            custom_colors = self.main_win.data.get("custom_colors", {})
            if isinstance(custom_colors, str):
                import ast
                try: custom_colors = ast.literal_eval(custom_colors)
                except: custom_colors = {}
            if isinstance(custom_colors, dict) and "edit_bg" in custom_colors:
                color = custom_colors["edit_bg"]
            else:
                color = "#363b40"
        else:
            border_norm = "border: 2px solid; border-top-color: #4d4d4d; border-left-color: #4d4d4d; border-right-color: #0a0a0a; border-bottom-color: #0a0a0a;"
            padding_norm = "padding: 2px 4px;"
            
        border_press = "border: 2px solid; border-top-color: #0a0a0a; border-left-color: #0a0a0a; border-right-color: #4d4d4d; border-bottom-color: #4d4d4d;"
        
        style = f"""
        QPushButton {{
            background-color: {color};
            {padding_norm}
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

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._update_text()

    def _update_text(self):
        if not self.full_name:
            self.setText("")
            return
            
        from PyQt6.QtGui import QFontMetrics
        fm = QFontMetrics(self.font())
        # Account for roughly 10px of padding
        available_width = max(0, self.width() - 10)
        elided = fm.elidedText(self.full_name, Qt.TextElideMode.ElideRight, available_width)
        self.setText(elided)

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
            # 2-sided button logic: left half = open at start, right half = open at end
            half = self.width() // 2
            if e.pos().x() < half:
                # LEFT side: open snippet and place cursor at start
                self.main_win.load_snippet_for_edit(self.cat, self.global_idx, cursor_pos="start")
            else:
                # RIGHT side: open snippet and place cursor at end
                self.main_win.load_snippet_for_edit(self.cat, self.global_idx, cursor_pos="end")
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
        self.main_btn.update_data(text_label, cat, global_idx, full_text, color, font_family, scale)
        
        current_state = (text_label, cat, global_idx, full_text, color, font_family, scale, self.main_win.data.get("theme", "Default"), self.main_win.data.get("button_scale", "1.0"))
        if getattr(self, '_last_state', None) == current_state:
            self.show()
            return
        self._last_state = current_state
        
        theme_name = self.main_win.data.get("theme", "Default")
        theme = THEMES.get(theme_name, THEMES["Default"])
        bg = extract_bg(theme.get('mini_settings', '')) or '#2b2b2b'
        fg = extract_color(theme.get('lbl_title', '')) or '#bfa65e'
        border = extract_color(theme.get('btn_save', '')) or '#4a4a4a'
        
        button_scale = float(self.main_win.data.get("button_scale", "1.0"))
        btn_size = max(18, int(24 * button_scale))
        self.main_btn.setFixedHeight(btn_size)
        
        from PyQt6.QtGui import QFont
        btn_font = QFont(font_family)
        btn_font.setPointSizeF(max(7.0, 9.0 * scale))
        btn_font.setBold(True)
        
        btn_style = f"background-color:{bg}; color:{fg}; border: 1px solid {border}; padding:0;"
        
        for btn in (self.btn_top, self.btn_ins, self.btn_bot):
            btn.setFont(btn_font)
            btn.setStyleSheet(btn_style)
            act_size = max(18, int(20 * button_scale))
            btn.setFixedSize(act_size, btn_size)

    def on_action_clicked(self):
        sender = self.sender()
        if sender == self.btn_top: self.main_win.insert_snippet_text(self.main_btn.full_text, "top")
        elif sender == self.btn_ins: self.main_win.insert_snippet_text(self.main_btn.full_text, "ins")
        elif sender == self.btn_bot: self.main_win.insert_snippet_text(self.main_btn.full_text, "bot")

class DropVerticalWidget(QWidget):
    def __init__(self, main_win, target_category=None):
        super().__init__()
        self.setAcceptDrops(True)
        from PyQt6.QtWidgets import QSizePolicy
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.main_win = main_win
        self.target_category = target_category
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(2)
        self.layout.setAlignment(Qt.AlignmentFlag.AlignTop)

    def dragEnterEvent(self, e):
        if e.mimeData().hasText() and ":" in e.mimeData().text(): e.acceptProposedAction()

    def dropEvent(self, e):
        my_cat = self.target_category or self.main_win.get_current_category()
        pos, source_data = e.position().toPoint(), e.mimeData().text().split(':')
        if len(source_data) != 2: e.ignore(); return
        source_cat, source_idx = source_data[0], int(source_data[1])
        
        page = self.main_win.arc_page if my_cat == "__Archive__" else self.main_win.current_pages.get(my_cat, 0)
        
        target_view_idx = -1
        for i in range(self.layout.count()):
            item = self.layout.itemAt(i).widget()
            if item and item.isVisible() and item.geometry().contains(pos): target_view_idx = i; break
        
        if target_view_idx == -1:
            visible_count = sum(1 for i in range(self.layout.count()) if self.layout.itemAt(i).widget().isVisible())
            target_view_idx = 0 if pos.y() < self.height() // 2 else visible_count - 1
            
        target_global_idx = page * 10 + max(0, min(9, target_view_idx))
        
        if source_cat == my_cat:
            self.main_win.move_preset_to_index(my_cat, source_idx, target_global_idx)
        else:
            self.main_win.move_preset_cross_category(source_cat, source_idx, my_cat, target_global_idx)
        e.acceptProposedAction()

class DraggableSiloButton(QPushButton):
    def __init__(self, main_win, parent=None, is_archive=False):
        super().__init__("", parent)
        self.is_archive = is_archive
        self.full_name = ""
        self.global_idx, self.main_win, self.drag_start, self._dragging = -1, main_win, None, False
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self.show_menu)

    def sizeHint(self):
        from PyQt6.QtCore import QSize
        return QSize(10, super().sizeHint().height())

    def minimumSizeHint(self):
        from PyQt6.QtCore import QSize
        return QSize(10, super().minimumSizeHint().height())

    def update_data(self, text_label, global_idx, bg_color, font_family="Verdana", scale=1.0):
        theme_name = self.main_win.data.get("theme", "Default")
        current_state = (text_label, global_idx, bg_color, font_family, scale, theme_name)
        if getattr(self, '_last_state', None) == current_state:
            self.show()
            return
        self._last_state = current_state
        
        self.full_name = text_label
        self.global_idx = global_idx
        
        # Apply font scaling safely
        from PyQt6.QtGui import QFont
        f = QFont(font_family)
        base_size = 9 # base size in points
        f.setPointSizeF(max(7.0, base_size * scale))
        self.setFont(f)
        
        self._update_text()
        
        # Active color check logic
        theme = THEMES.get(theme_name, THEMES["Default"])
        active_color = theme.get("active_temp_color", "#364757")
        
        # Selected = sunken (inset), Unselected = raised (outset)
        if bg_color == active_color:
            border = "border: 2px solid; border-top-color: #0a0a0a; border-left-color: #0a0a0a; border-right-color: #4d4d4d; border-bottom-color: #4d4d4d;"
            padding = "padding:3px 3px 1px 5px;" # shift text right/down for sunken feel
        else:
            border = "border: 2px solid; border-top-color: #4d4d4d; border-left-color: #4d4d4d; border-right-color: #0a0a0a; border-bottom-color: #0a0a0a;"
            padding = "padding:2px 4px;"
            
        self.setStyleSheet(f"{padding} text-align:left; background-color:{bg_color}; {border}")
        self.show()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._update_text()

    def _update_text(self):
        if not self.full_name:
            self.setText("")
            return
            
        from PyQt6.QtGui import QFontMetrics
        from PyQt6.QtCore import Qt
        fm = QFontMetrics(self.font())
        # Account for roughly 10px of padding
        available_width = max(0, self.width() - 10)
        elided = fm.elidedText(self.full_name, Qt.TextElideMode.ElideRight, available_width)
        self.setText(elided)

    def show_menu(self, pos):
        self.main_win.show_temp_menu(self.global_idx, self.mapToGlobal(pos), is_archive=self.is_archive)

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
        prefix = "arcsilo" if self.is_archive else "silo"
        mime.setText(f"{prefix}:{self.global_idx}")
        drag.setMimeData(mime)
        drag.exec(Qt.DropAction.MoveAction)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton and not self._dragging:
            if self.is_archive:
                self.main_win._switch_to_arc_slot(self.global_idx)
            else:
                self.main_win._switch_to_slot(self.global_idx)
            e.accept()
            return
        super().mouseReleaseEvent(e)

class SiloDropWidget(QWidget):
    def __init__(self, main_win, is_archive=False):
        super().__init__()
        self.setAcceptDrops(True)
        from PyQt6.QtWidgets import QSizePolicy
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.main_win = main_win
        self.is_archive = is_archive
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(2)
        self.layout.setAlignment(Qt.AlignmentFlag.AlignTop)

    def dragEnterEvent(self, e):
        if e.mimeData().hasText() and (e.mimeData().text().startswith("silo:") or e.mimeData().text().startswith("arcsilo:")):
            e.acceptProposedAction()

    def dropEvent(self, e):
        mime = e.mimeData()
        if not mime.hasText(): return
        data, pos = mime.text().split(':'), e.position().toPoint()
        if len(data) != 2 or data[0] not in ("silo", "arcsilo"): return
        
        source_is_archive = (data[0] == "arcsilo")
        
        visible = 10 if self.is_archive else getattr(self.main_win, '_visible_silos', 10)
        start_idx = (self.main_win.arc_silo_page if self.is_archive else self.main_win.silo_page) * visible
        target_view_idx = -1
        for i in range(self.layout.count()):
            btn = self.layout.itemAt(i).widget()
            if btn and btn.isVisible() and btn.geometry().contains(pos): target_view_idx = i; break
        
        if target_view_idx == -1:
            visible_count = sum(1 for i in range(self.layout.count()) if self.layout.itemAt(i).widget().isVisible())
            target_view_idx = 0 if pos.y() < self.height() // 2 else visible_count - 1

        target_global_idx = start_idx + target_view_idx
        source_idx = int(data[1])
        
        if source_is_archive == self.is_archive:
            if source_idx != target_global_idx:
                self.main_win.swap_temp_slots(source_idx, target_global_idx, is_archive=self.is_archive)
        else:
            self.main_win.swap_cross_temp_slots(source_idx, target_global_idx, source_is_archive, self.is_archive)
            
        e.acceptProposedAction()
