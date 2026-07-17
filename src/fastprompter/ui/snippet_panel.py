from PyQt6.QtCore import QEvent, QMimeData, QObject, Qt, QTimer
from PyQt6.QtGui import QDrag, QFontMetrics
from PyQt6.QtWidgets import QApplication, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from fastprompter.core.config import extract_bg, extract_border_color, extract_color
from fastprompter.theme.themes import THEMES


class WheelPager(QObject):
    """Maps mouse-wheel over a widget (and its wheel-ignoring children) to
    a paging callback: wheel up → callback(-1), wheel down → callback(1).

    An optional ``ctrl_callback`` handles Ctrl+wheel separately (e.g. plain
    wheel flips pages, Ctrl+wheel walks the selection item by item).

    Usage::

        WheelPager(section_widget, main_win.change_silo_page,
                   ctrl_callback=main_win.navigate_silo)
    """

    def __init__(self, widget, callback, ctrl_callback=None):
        super().__init__(widget)
        self._cb = callback
        self._ctrl_cb = ctrl_callback
        widget.installEventFilter(self)

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.Wheel:
            delta = event.angleDelta().y()
            if delta:
                direction = -1 if delta > 0 else 1
                if self._ctrl_cb and event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                    self._ctrl_cb(direction)
                else:
                    self._cb(direction)
            return True
        return False


def _word_wrap_text(font_metrics: QFontMetrics, text: str, avail_width: int) -> str:
    """Insert newlines into text at word boundaries so it can be displayed multi-line."""
    words = text.split()
    if not words:
        return text
    lines = []
    cur_line = words[0]
    for word in words[1:]:
        if font_metrics.horizontalAdvance(cur_line + " " + word) <= avail_width:
            cur_line += " " + word
        else:
            lines.append(cur_line)
            cur_line = word
    lines.append(cur_line)
    return "\n".join(lines)


class DraggableButton(QPushButton):
    def __init__(self, main_win, parent=None):
        super().__init__("", parent)
        self.cat, self.global_idx, self.full_text = "", -1, ""
        self.full_name = ""
        self.main_win, self.drag_start, self._dragging = main_win, None, False
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self.show_menu)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        if not self.full_name:
            return super().heightForWidth(width)
        from PyQt6.QtCore import QRect, Qt
        from PyQt6.QtGui import QFontMetrics
        fm = QFontMetrics(self.font())
        available_width = max(0, width - 10)
        if available_width <= 0:
            available_width = 150
        wrapped = _word_wrap_text(fm, self.full_name, available_width)
        bounding = fm.boundingRect(QRect(0, 0, available_width, 0), int(Qt.TextFlag.TextWordWrap), wrapped)
        needed_height = bounding.height() + 8
        min_h = fm.height() + 8
        return max(min_h, needed_height)

    def sizeHint(self):
        from PyQt6.QtCore import QSize
        # Allow the button to be narrow/compact, but height depends on heightForWidth
        return QSize(10, self.heightForWidth(100))

    def minimumSizeHint(self):
        return self.sizeHint()

    def update_data(self, text_label, cat, global_idx, full_text, color, font_family, scale=1.0,
                    title_bold=False):
        is_editing = getattr(self.main_win, 'editing_snippet', None) == (cat, global_idx)
        current_state = (text_label, cat, global_idx, full_text, color, font_family, scale,
                         is_editing, title_bold)
        if getattr(self, '_last_state', None) == current_state:
            self.show()
            return
        self._last_state = current_state

        self.full_name = text_label
        self.cat, self.global_idx, self.full_text = cat, global_idx, full_text

        # Apply font scaling safely
        from PyQt6.QtGui import QFont
        f = QFont(font_family)
        base_size = 10  # base size in points
        f.setPointSizeF(max(8.0, base_size * scale))
        f.setBold(title_bold)
        self.setFont(f)

        self._last_width = -1
        self._update_text()

        theme_name = self.main_win.data.get("theme", "Default")
        theme = THEMES.get(theme_name, THEMES["Default"])
        raw = theme.get("raw_colors", {})
        bd = raw.get("border_dark", "#0a0a0a")
        bl = raw.get("border_light", "#4d4d4d")

        if is_editing:
            border_norm = f"border: 2px solid; border-top-color: {bd}; border-left-color: {bd}; border-right-color: {bl}; border-bottom-color: {bl};"
            padding_norm = "padding: 3px 3px 1px 5px;"
            custom_colors = self.main_win.data.get("custom_colors", {})
            if isinstance(custom_colors, str):
                import ast
                try: custom_colors = ast.literal_eval(custom_colors)
                except Exception: custom_colors = {}
            if isinstance(custom_colors, dict) and "edit_bg" in custom_colors:
                color = custom_colors["edit_bg"]
            else:
                color = "#363b40"
        else:
            border_norm = f"border: 2px solid; border-top-color: {bl}; border-left-color: {bl}; border-right-color: {bd}; border-bottom-color: {bd};"
            padding_norm = "padding: 2px 4px;"

        border_press = f"border: 2px solid; border-top-color: {bd}; border-left-color: {bd}; border-right-color: {bl}; border-bottom-color: {bl};"
        pressed_bg = raw.get("btn_pressed", "#141414")
        pressed_fg = raw.get("accent", "#5a7a96")

        style = f"""
        QPushButton {{
            background-color: {color};
            {padding_norm}
            text-align: left;
            {border_norm}
            outline: none;
        }}
        QPushButton:pressed {{
            background-color: {pressed_bg};
            padding: 3px 3px 1px 5px;
            color: {pressed_fg};
            {border_press}
            outline: none;
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

        from PyQt6.QtCore import QRect, Qt
        fm = QFontMetrics(self.font())
        available_width = max(0, self.width() - 10)
        wrapped = _word_wrap_text(fm, self.full_name, available_width)
        bounding = fm.boundingRect(QRect(0, 0, available_width, 0), int(Qt.TextFlag.TextWordWrap), wrapped)
        needed_height = bounding.height() + 8
        self.setText(wrapped)
        min_h = fm.height() + 8
        self.setFixedHeight(max(min_h, needed_height))

    def show_menu(self, pos):
        from PyQt6.QtWidgets import QMenu
        menu = QMenu(self)
        menu.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        menu.setFont(QApplication.font())
        menu.addAction("📋 Copy", lambda: self.main_win.copy_snippet_to_clipboard(self.full_text))
        menu.addAction("✏ Rename", lambda: self.main_win.rename_snippet(self.cat, self.global_idx))
        menu.addAction("📁 Files…", lambda: self.main_win.open_file_container(self.global_idx))
        menu.addSeparator()
        menu.addAction("🗑 Delete", lambda: self.main_win.prompt_delete_snippet(self.cat, self.global_idx))
        self.main_win.ignore_focus_loss = True
        try:
            menu.exec(self.mapToGlobal(pos))
        finally:
            self.main_win.ignore_focus_loss = False
        self.main_win.activateWindow()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.RightButton and e.modifiers() & Qt.KeyboardModifier.ControlModifier:
            super().mousePressEvent(e)
            self.main_win.prompt_delete_snippet(self.cat, self.global_idx)
            e.accept()
            return
        if e.button() == Qt.MouseButton.LeftButton:
            super().mousePressEvent(e)
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
            super().mouseReleaseEvent(e)
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
        self.main_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.btn_top = QPushButton("▲")
        self.btn_ins = QPushButton("▶")
        self.btn_bot = QPushButton("▼")

        self.layout.addWidget(self.main_btn)
        for btn in (self.btn_top, self.btn_ins, self.btn_bot):
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(self.on_action_clicked)
            self.layout.addWidget(btn)

    def update_data(self, text_label, cat, global_idx, full_text, color, font_family, scale,
                    title_bold=False):
        self.main_btn.update_data(text_label, cat, global_idx, full_text, color, font_family,
                                  scale, title_bold=title_bold)

        current_state = (text_label, cat, global_idx, full_text, color, font_family, scale, self.main_win.data.get("theme", "Default"), self.main_win.data.get("button_scale", "1.0"))
        if getattr(self, '_last_state', None) == current_state:
            self.show()
            return
        self._last_state = current_state

        theme_name = self.main_win.data.get("theme", "Default")
        theme = THEMES.get(theme_name, THEMES["Default"])
        bg = extract_bg(theme.get('mini_settings', '')) or '#2b2b2b'
        fg = extract_color(theme.get('lbl_title', '')) or '#bfa65e'
        border = extract_border_color(theme.get('btn_save', '')) or '#4a4a4a'

        try: button_scale = float(self.main_win.data.get("button_scale", "1.0"))
        except Exception: button_scale = 1.0

        from PyQt6.QtGui import QFont
        btn_font = QFont(font_family)
        btn_font.setPointSizeF(max(8.0, 9.0 * scale))
        btn_font.setBold(True)

        btn_style = f"background-color:{bg}; color:{fg}; border: 1px solid {border}; padding:0;"

        for btn in (self.btn_top, self.btn_ins, self.btn_bot):
            btn.setFont(btn_font)
            btn.setStyleSheet(btn_style)
            act_size = max(18, int(20 * button_scale))
            btn.setFixedSize(act_size, act_size)

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

    def dragMoveEvent(self, e):
        pos = e.position().toPoint()
        target_view_idx = -1
        for i in range(self.layout.count()):
            btn = self.layout.itemAt(i).widget()
            if btn and btn.isVisible():
                if pos.y() < btn.geometry().center().y():
                    target_view_idx = i
                    break
        if target_view_idx == -1:
            target_view_idx = sum(1 for i in range(self.layout.count()) if self.layout.itemAt(i).widget().isVisible())

        if getattr(self, '_drop_indicator_index', -1) != target_view_idx:
            self._drop_indicator_index = target_view_idx
            self.update()
        e.acceptProposedAction()

    def dragLeaveEvent(self, e):
        self._drop_indicator_index = -1
        self.update()

    def paintEvent(self, e):
        super().paintEvent(e)
        idx = getattr(self, '_drop_indicator_index', -1)
        if idx >= 0:
            from PyQt6.QtCore import Qt
            from PyQt6.QtGui import QColor, QPainter, QPen
            painter = QPainter(self)
            try:
                accent = "#bfa65e"
                if hasattr(self.main_win, 'data') and "theme" in self.main_win.data:
                    theme_name = self.main_win.data.get("theme", "Default")
                    theme = THEMES.get(theme_name, THEMES.get("Default", {}))
                    accent = extract_color(theme.get('lbl_title', '')) or accent

                painter.setPen(QPen(QColor(accent), 2, Qt.PenStyle.SolidLine))

                y = 0
                visible_btns = [self.layout.itemAt(i).widget() for i in range(self.layout.count()) if self.layout.itemAt(i).widget().isVisible()]
                if idx == 0:
                    y = visible_btns[0].geometry().top() - 1 if visible_btns else 0
                elif idx < len(visible_btns):
                    y = visible_btns[idx].geometry().top() - 1
                elif visible_btns:
                    y = visible_btns[-1].geometry().bottom() + 1

                painter.drawLine(0, y, self.width(), y)
            finally:
                painter.end()

    def dropEvent(self, e):
        self._drop_indicator_index = -1
        self.update()
        my_cat = self.target_category or self.main_win.get_current_category()
        pos, source_data = e.position().toPoint(), e.mimeData().text().split(':')
        if len(source_data) != 2: e.ignore(); return
        source_cat, source_idx = source_data[0], int(source_data[1])

        page = self.main_win.arc_page if my_cat == "__Archive__" else self.main_win.current_pages.get(my_cat, 0)

        # Compute drop target properly based on half-height
        target_view_idx = -1
        for i in range(self.layout.count()):
            btn = self.layout.itemAt(i).widget()
            if btn and btn.isVisible():
                if pos.y() < btn.geometry().center().y():
                    target_view_idx = i
                    break
        if target_view_idx == -1:
            target_view_idx = sum(1 for i in range(self.layout.count()) if self.layout.itemAt(i).widget().isVisible())

        target_global_idx = page * 10 + max(0, min(9, target_view_idx))

        if source_cat == my_cat:
            self.main_win.move_preset_to_index(my_cat, source_idx, target_global_idx)
        else:
            self.main_win.move_preset_cross_category(source_cat, source_idx, my_cat, target_global_idx)
        e.acceptProposedAction()


class DraggableSiloButton(QWidget):
    """QWidget-based silo button with left-aligned text, right-aligned line count, and hover pin/archive buttons."""

    def __init__(self, main_win, parent=None, is_archive=False):
        super().__init__(parent)
        from PyQt6.QtWidgets import QSizePolicy
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        self.setObjectName("DraggableSiloButton")
        # Plain QWidget subclasses ignore stylesheet background/border unless
        # WA_StyledBackground is set — without it the 3D bevel doesn't render.
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.is_archive = is_archive
        self.full_name = ""
        self._line_count_str = ""
        self.global_idx = -1
        self.main_win = main_win
        self.drag_start = None
        self._dragging = False
        self._hover_timer = None
        self._hover_showing = False
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self.show_menu)

        # Use QHBoxLayout for left-aligned text + stretch + action buttons + line count
        self._silo_layout = QHBoxLayout(self)
        self._silo_layout.setContentsMargins(4, 2, 4, 2)
        self._silo_layout.setSpacing(2)

        self._lbl_text = QLabel()
        self._lbl_text.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._lbl_text.setWordWrap(False)

        self._lbl_count = QLabel()
        self._lbl_count.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._lbl_count.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        # Hover-only action buttons: pin and archive
        self._btn_pin = QPushButton("📌")
        self._btn_pin.setFixedSize(16, 16)
        self._btn_pin.setToolTip("Pin/Unpin this silo to top")
        self._btn_pin.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_pin.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        self._btn_pin.setStyleSheet("background: transparent; border: none; padding: 0; font-size: 11px;")
        self._btn_pin.clicked.connect(self._on_pin_clicked)

        self._btn_archive = QPushButton("📥")
        self._btn_archive.setFixedSize(16, 16)
        self._btn_archive.setToolTip("Archive this silo")
        self._btn_archive.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_archive.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        self._btn_archive.setStyleSheet("background: transparent; border: none; padding: 0; font-size: 11px;")
        self._btn_archive.clicked.connect(self._on_archive_clicked)

        self._btn_files = QPushButton("📁")
        self._btn_files.setFixedSize(16, 16)
        self._btn_files.setToolTip("Files: drop/drag/preview assets for this silo")
        self._btn_files.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_files.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        self._btn_files.setStyleSheet("background: transparent; border: none; padding: 0; font-size: 11px;")
        self._btn_files.clicked.connect(self._on_files_clicked)

        self._btn_tick = QPushButton("✅")
        self._btn_tick.setFixedSize(16, 16)
        self._btn_tick.setToolTip("Mark this silo as done (click again to unmark)")
        self._btn_tick.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_tick.setStyleSheet("background: transparent; border: none; padding: 0; font-size: 11px;")
        self._btn_tick.clicked.connect(self._on_tick_clicked)

        # tick sits leftmost — before the order number in the title
        self._silo_layout.addWidget(self._btn_tick)
        self._silo_layout.addWidget(self._lbl_text)
        self._silo_layout.addStretch()
        self._silo_layout.addWidget(self._btn_files)
        self._silo_layout.addWidget(self._btn_pin)
        self._silo_layout.addWidget(self._btn_archive)
        self._silo_layout.addWidget(self._lbl_count)

        # Start with buttons hidden
        self._btn_pin.hide()
        self._btn_archive.hide()
        self._btn_files.hide()
        self._btn_tick.hide()
        # Set mouse tracking so we get hover events
        self.setMouseTracking(True)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)

    def _on_pin_clicked(self):
        """Toggle pin state for this silo."""
        if hasattr(self.main_win, '_toggle_pin_silo'):
            self.main_win._toggle_pin_silo(self.global_idx)

    def _on_archive_clicked(self):
        """Archive this silo directly."""
        if hasattr(self.main_win, 'archive_single_silo'):
            self.main_win.archive_single_silo(self.global_idx)

    def _on_files_clicked(self):
        """Open the per-silo file container drawer."""
        if hasattr(self.main_win, 'open_file_container'):
            self.main_win.open_file_container(self.global_idx, is_archive=self.is_archive)

    def _is_ticked(self):
        ticked = self.main_win.data.get("silo_ticked", [])
        return isinstance(ticked, list) and self.global_idx in ticked

    def _on_tick_clicked(self):
        if hasattr(self.main_win, '_toggle_tick_silo'):
            self.main_win._toggle_tick_silo(self.global_idx)

    def enterEvent(self, event):
        """Show action buttons on hover with a tiny delay for smooth feel."""
        if self.is_archive:
            super().enterEvent(event)
            return
        self._hover_showing = True
        if self._hover_timer is None:
            self._hover_timer = QTimer(self)
            self._hover_timer.setSingleShot(True)
            self._hover_timer.setInterval(80)
            self._hover_timer.timeout.connect(self._update_hover_buttons)
        self._hover_timer.start()
        super().enterEvent(event)

    def leaveEvent(self, event):
        """Hide action buttons when mouse leaves."""
        self._hover_showing = False
        if self._hover_timer:
            self._hover_timer.stop()
        self._btn_pin.hide()
        self._btn_archive.hide()
        self._btn_files.hide()
        self._btn_tick.setVisible(self._is_ticked())
        super().leaveEvent(event)

    def setText(self, text):
        self.full_name = text
        self._update_text()

    def _update_hover_buttons(self):
        """Show/hide action buttons based on hover state."""
        if self._hover_showing and not self.is_archive and self.global_idx >= 0:
            self._btn_pin.show()
            self._btn_archive.show()
            self._btn_files.show()
            if self.main_win.data.get("silo_ticks_enabled", "True") == "True":
                self._btn_tick.setText("☑" if self._is_ticked() else "✅")
                self._btn_tick.show()
            try:
                from fastprompter.ui.file_container import folder_summary
                presets = self.main_win.data.get("temp_presets", [])
                text = presets[self.global_idx] if 0 <= self.global_idx < len(presets) else ""
                self._btn_files.setToolTip(
                    "Files: drop/drag/preview assets for this silo\n\n"
                    + folder_summary(self.main_win._files_root(),
                                     self.main_win.get_current_category(), text)
                )
            except Exception:
                pass  # tooltip is decoration; hover must never break
        else:
            self._btn_pin.hide()
            self._btn_archive.hide()
            self._btn_files.hide()

    def sizeHint(self):
        from PyQt6.QtCore import QSize
        return QSize(10, self._lbl_text.fontMetrics().height() + 10)

    def minimumSizeHint(self):
        from PyQt6.QtCore import QSize
        return QSize(10, self._lbl_text.fontMetrics().height() + 10)

    def update_data(self, text_label, global_idx, bg_color, font_family="Verdana", scale=1.0, line_count_str="", is_pushed=False, title_bold=False, is_child=False):
        theme_name = self.main_win.data.get("theme", "Default")
        ticked_list = self.main_win.data.get("silo_ticked", [])
        is_ticked = isinstance(ticked_list, list) and global_idx in ticked_list
        current_state = (text_label, global_idx, bg_color, font_family, scale, theme_name, line_count_str, is_pushed, title_bold, is_ticked, is_child)
        if getattr(self, '_last_state', None) == current_state:
            self.show()
            return
        self._last_state = current_state

        self.full_name = text_label
        self._line_count_str = line_count_str
        self.global_idx = global_idx
        # children sit shifted right under their parent
        self._silo_layout.setContentsMargins(22 if is_child else 4, 2, 4, 2)
        self._btn_tick.setText("✅")
        ticks_on = self.main_win.data.get("silo_ticks_enabled", "True") == "True"
        self._btn_tick.setVisible(is_ticked and ticks_on and not self.is_archive)

        # Apply font scaling safely
        from PyQt6.QtGui import QFont
        f = QFont(font_family)
        base_size = 10
        f.setPointSizeF(max(8.0, base_size * scale))
        f.setBold(title_bold)
        self._lbl_text.setFont(f)
        f2 = QFont(f)
        f2.setBold(False)
        self._lbl_count.setFont(f2)

        self._update_text()

        # Get theme colors using same pattern as SnippetWidget
        theme = THEMES.get(theme_name, THEMES["Default"])
        text_color = extract_color(theme.get('lbl_title', '')) or '#c4ba9f'
        raw = theme.get("raw_colors", {})
        bd = raw.get("border_dark", "#0a0a0a")
        bl = raw.get("border_light", "#4d4d4d")

        # Win95 3D bevel: raised = top/left light, bottom/right dark
        #               sunken = top/left dark, bottom/right light (pushed)
        if is_pushed:
            border = f"border: 3px solid; border-top-color: {bd}; border-left-color: {bd}; border-right-color: {bl}; border-bottom-color: {bl};"
        else:
            border = f"border: 3px solid; border-top-color: {bl}; border-left-color: {bl}; border-right-color: {bd}; border-bottom-color: {bd};"

        # Style the container widget with background and borders
        self.setStyleSheet(f"""
            #DraggableSiloButton {{
                background-color:{bg_color}; {border} outline: none;
            }}
        """)
        # Style the text labels transparent (inherits parent bg/border)
        self._lbl_text.setStyleSheet(f"background: transparent; color: {text_color}; padding: 0 2px; border: none;")
        self._lbl_count.setStyleSheet(f"background: transparent; color: {text_color}; padding: 0 2px; border: none;")
        self.show()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._update_text()

    def _update_text(self):
        if not self.full_name:
            self._lbl_text.setText("")
            self._lbl_count.setText("")
            return

        self._lbl_text.setText(self.full_name)
        self._lbl_count.setText(self._line_count_str)
        self.setFixedHeight(self._lbl_text.fontMetrics().height() + 10)

    def show_menu(self, pos):
        self.main_win.show_temp_menu(self.global_idx, self.mapToGlobal(pos), is_archive=self.is_archive)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            super().mousePressEvent(e)
            self.drag_start, self._dragging = e.pos(), False
            e.accept()
            return
        elif e.button() == Qt.MouseButton.MiddleButton:
            super().mousePressEvent(e)
            # middle-click retires the silo into the trash (text + files
            # both land in data/files/_trash — recoverable, not a wipe)
            self.main_win.trash_silo(self.global_idx, is_archive=self.is_archive)
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
            super().mouseReleaseEvent(e)
            e.accept()
            return
        super().mouseReleaseEvent(e)


class SiloDropWidget(QWidget):
    """Drop target for silo drag-reorder and cross-container moves."""

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

    def _visible_buttons(self):
        out = []
        for i in range(self.layout.count()):
            w = self.layout.itemAt(i).widget()
            if w and w.isVisible() and hasattr(w, "global_idx") and type(w).__name__ == "DraggableSiloButton":
                out.append(w)
        return out

    def _drop_target_at(self, pos):
        """Classify a drop position.

        Returns ("swap", button) when pos is over the middle band of a silo,
        or ("move", gap_index) when pos is near a silo edge / between silos
        (gap_index counts insertion boundaries among visible buttons).
        """
        btns = self._visible_buttons()
        for i, btn in enumerate(btns):
            g = btn.geometry()
            if pos.y() <= g.bottom():
                band = max(3, int(g.height() * 0.28))
                if pos.y() < g.top() + band:
                    return "move", i
                if pos.y() > g.bottom() - band:
                    return "move", i + 1
                return "swap", btn
        return "move", len(btns)

    def dragMoveEvent(self, e):
        mode, target = self._drop_target_at(e.position().toPoint())
        if mode == "swap":
            new_state = ("swap", target.geometry())
        else:
            new_state = ("move", target)
        if getattr(self, '_drop_state', None) != new_state:
            self._drop_state = new_state
            self.update()
        e.acceptProposedAction()

    def dragLeaveEvent(self, e):
        self._drop_state = None
        self.update()

    def paintEvent(self, e):
        super().paintEvent(e)
        state = getattr(self, '_drop_state', None)
        if not state:
            return
        from PyQt6.QtCore import Qt
        from PyQt6.QtGui import QColor, QPainter, QPen
        painter = QPainter(self)
        try:
            accent = "#bfa65e"
            if hasattr(self.main_win, 'data') and "theme" in self.main_win.data:
                theme_name = self.main_win.data.get("theme", "Default")
                theme = THEMES.get(theme_name, THEMES.get("Default", {}))
                accent = extract_color(theme.get('lbl_title', '')) or accent
            painter.setPen(QPen(QColor(accent), 2, Qt.PenStyle.SolidLine))

            mode, target = state
            if mode == "swap":
                # Highlight the hovered silo: drop here swaps places
                painter.drawRect(target.adjusted(1, 1, -2, -2))
            else:
                # Insertion line between silos: drop here reorders
                visible_btns = self._visible_buttons()
                y = 0
                if target == 0:
                    y = visible_btns[0].geometry().top() - 1 if visible_btns else 0
                elif target < len(visible_btns):
                    y = visible_btns[target].geometry().top() - 1
                elif visible_btns:
                    y = visible_btns[-1].geometry().bottom() + 1
                painter.drawLine(0, y, self.width(), y)
        finally:
            painter.end()

    def dropEvent(self, e):
        self._drop_state = None
        self.update()
        mime = e.mimeData()
        if not mime.hasText():
            return
        data, pos = mime.text().split(':'), e.position().toPoint()
        if len(data) != 2 or data[0] not in ("silo", "arcsilo"):
            return

        source_is_archive = (data[0] == "arcsilo")
        source_idx = int(data[1])

        mode, target = self._drop_target_at(pos)
        btns = self._visible_buttons()

        shift_held = bool(QApplication.keyboardModifiers()
                          & Qt.KeyboardModifier.ShiftModifier)
        if mode == "swap":
            target_global_idx = target.global_idx
            if source_is_archive == self.is_archive:
                # Plain drop ON a silo nests it as a child;
                # Shift+drop keeps the old swap behavior
                if (not self.is_archive and not shift_held
                        and source_idx != target_global_idx
                        and hasattr(self.main_win, "make_silo_child")):
                    self.main_win.make_silo_child(source_idx, target_global_idx)
                    e.acceptProposedAction()
                    return
                if not self.is_archive and hasattr(self.main_win, "handle_pinned_drop"):
                    if self.main_win.handle_pinned_drop(source_idx, swap_idx=target_global_idx):
                        e.acceptProposedAction()
                        return
                if source_idx != target_global_idx:
                    self.main_win.swap_temp_slots(source_idx, target_global_idx, is_archive=self.is_archive)
            else:
                self.main_win.swap_cross_temp_slots(source_idx, target_global_idx, source_is_archive, self.is_archive)
        else:
            # Insertion gap → slot index: before the button below the gap,
            # or to the very end when dropped past the last button.
            if source_is_archive != self.is_archive:
                # Cross-container: land on the boundary slot
                if target < len(btns):
                    target_global_idx = btns[target].global_idx
                else:
                    presets = self.main_win.data["archive_temp_presets" if self.is_archive else "temp_presets"]
                    target_global_idx = max(0, len(presets) - 1)
                self.main_win.swap_cross_temp_slots(source_idx, target_global_idx, source_is_archive, self.is_archive)
            else:
                # dragging a child out to a boundary promotes it first
                if not self.is_archive and hasattr(self.main_win, "unnest_silo"):
                    self.main_win.unnest_silo(source_idx)
                if target < len(btns):
                    boundary_idx = btns[target].global_idx
                    if not self.is_archive and hasattr(self.main_win, "handle_pinned_drop"):
                        if self.main_win.handle_pinned_drop(source_idx, boundary_idx=boundary_idx):
                            e.acceptProposedAction()
                            return
                    to_idx = boundary_idx - 1 if source_idx < boundary_idx else boundary_idx
                else:
                    if not self.is_archive and hasattr(self.main_win, "handle_pinned_drop"):
                        if self.main_win.handle_pinned_drop(source_idx, boundary_idx=None):
                            # It unpinned it, we still want it to move to the end!
                            pass
                    presets = self.main_win.data["archive_temp_presets" if self.is_archive else "temp_presets"]
                    to_idx = len(presets) - 1
                self.main_win.move_temp_to_index(source_idx, to_idx, is_archive=self.is_archive)

        e.acceptProposedAction()
