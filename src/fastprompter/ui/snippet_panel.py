from PyQt6.QtCore import QEvent, QMimeData, QObject, Qt, QTimer, QUrl
from PyQt6.QtGui import QDrag, QFontMetrics
from PyQt6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from fastprompter.core.config import extract_bg, extract_border_color, extract_color
from fastprompter.core.translations import tr
from fastprompter.theme.themes import THEMES
from fastprompter.utils.fonts import no_aa


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

        # The font is applied BEFORE the cache check, not after it. A theme or
        # scale pass elsewhere calls setFont on these buttons and wipes the
        # bold, while `_last_state` still says it was applied — so the next
        # refresh took the early return and the '#'-header snippet never got
        # its bold title back. The cache is there to skip the expensive
        # stylesheet work, and a QFont per refresh is not that.
        from PyQt6.QtGui import QFont
        f = no_aa(QFont(font_family))
        base_size = 10  # base size in points
        f.setPointSizeF(max(8.0, base_size * scale))
        f.setBold(title_bold)
        self.setFont(f)

        if getattr(self, '_last_state', None) == current_state:
            self.show()
            return
        self._last_state = current_state

        self.full_name = text_label
        self.cat, self.global_idx, self.full_text = cat, global_idx, full_text

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
        new_height = max(min_h, needed_height)
        if self.height() != new_height or self.minimumHeight() != new_height:
            self.setFixedHeight(new_height)
            self.updateGeometry()
            p = self.parentWidget()
            if p:
                p.updateGeometry()
                if p.parentWidget():
                    p.parentWidget().updateGeometry()

    def show_menu(self, pos):
        from PyQt6.QtWidgets import QMenu
        menu = QMenu(self)
        menu.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        menu.setFont(QApplication.font())
        le = getattr(self.main_win, "_current_lang", "EN")
        if self.cat == "Trash":
            menu.addAction(tr("♻ Restore", le), lambda: self.main_win.restore_snippet(self.global_idx))
            menu.addSeparator()
            menu.addAction(tr("🗑 Delete Permanently", le), lambda: self.main_win.prompt_delete_snippet(self.cat, self.global_idx))
        else:
            menu.addAction(tr("📋 Copy", le), lambda: self.main_win.copy_snippet_to_clipboard(self.full_text))
            menu.addAction(tr("✏ Rename", le), lambda: self.main_win.rename_snippet(self.cat, self.global_idx))
            menu.addAction(tr("📁 Files…", le), lambda: self.main_win.open_file_container(self.global_idx))
            menu.addSeparator()
            menu.addAction(tr("🗑 Delete", le), lambda: self.main_win.prompt_delete_snippet(self.cat, self.global_idx))
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
        try:
            drag, mime = QDrag(self), QMimeData()
            mime.setText(f"{self.cat}:{self.global_idx}")
            drag.setMimeData(mime)
            drag.exec(Qt.DropAction.MoveAction)
        finally:
            self._dragging = False

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
            # A size from the start, not only once update_data runs. A widget
            # that has never held a snippet was left at the layout's own idea
            # of small — measured 13x13, which is 9px of room for an 11px
            # mark once a 2px-border theme takes its cut.
            btn.setProperty("fp_icon_button", True)
            btn.setFixedSize(18, 18)
            self.layout.addWidget(btn)

    def update_data(self, text_label, cat, global_idx, full_text, color, font_family, scale,
                    title_bold=False):
        self.main_btn.update_data(text_label, cat, global_idx, full_text, color, font_family,
                                  scale, title_bold=title_bold)

        current_state = (text_label, cat, global_idx, full_text, color, font_family, scale, self.main_win.data.get("theme", "Default"), self.main_win.data.get("button_scale", "1.0"), self.main_win.data.get("snippet_arrows", "False"))
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
        btn_font = no_aa(QFont(font_family))
        btn_font.setPointSizeF(max(8.0, 9.0 * scale))
        btn_font.setBold(True)

        btn_style = f"background-color:{bg}; color:{fg}; border: 1px solid {border}; padding:0;"

        arrows_on = self.main_win.data.get("snippet_arrows", "False") == "True"
        # Size from the FONT, not from a magic 18. These are rebuilt on every
        # refresh with their own fixed size, so a box picked without asking
        # how big the glyph is simply clips it again after every repaint —
        # measured at 9px of room for an 11px mark on the vintage themes.
        from PyQt6.QtGui import QFontMetrics
        fm = QFontMetrics(btn_font)
        glyph = max(fm.height(), max(fm.horizontalAdvance(g) for g in "▲▶▼"))
        act_size = max(18, int(20 * button_scale), glyph + 4)
        for btn in (self.btn_top, self.btn_ins, self.btn_bot):
            btn.setVisible(arrows_on)
            btn.setFont(btn_font)
            btn.setStyleSheet(btn_style)
            btn.setProperty("fp_icon_button", True)
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

    # The empty colour swatch: a dashed outline while the row is hovered, and
    # nothing at all at rest. The column stays reserved either way, so titles
    # still line up down the sidebar (that is what the placeholder is for).
    _SWATCH_HINT = "background: transparent; border: 1px dashed #777; border-radius: 2px;"
    _SWATCH_BLANK = "background: transparent; border: none;"

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
        self._silo_layout.setContentsMargins(3, 1, 3, 1)
        self._silo_layout.setSpacing(1)
        self._btn_collapse = QPushButton("▾")
        self._btn_collapse.setFixedSize(14, 16)
        self._btn_collapse.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_collapse.setStyleSheet("background: transparent; border: none; padding: 0;")
        self._btn_collapse.clicked.connect(self._on_collapse_clicked)
        self._btn_collapse.hide()

        self._lbl_text = QLabel()
        self._lbl_text.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._lbl_text.setWordWrap(False)

        self._lbl_count = QLabel()
        self._lbl_count.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._lbl_count.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        # Hover-only action buttons: pin and archive
        self._btn_pin = QPushButton("📌")
        self._btn_pin.setFixedSize(14, 16)
        self._btn_pin.setToolTip(tr("Pin/Unpin this silo to top", getattr(self.main_win, "_current_lang", "EN")))
        self._btn_pin.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_pin.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        self._btn_pin.setStyleSheet("background: transparent; border: none; padding: 0; font-size: 11px;")
        self._btn_pin.clicked.connect(self._on_pin_clicked)

        self._btn_archive = QPushButton("📥")
        self._btn_archive.setFixedSize(14, 16)
        self._btn_archive.setToolTip(tr("Archive this silo", getattr(self.main_win, "_current_lang", "EN")))
        self._btn_archive.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_archive.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        self._btn_archive.setStyleSheet("background: transparent; border: none; padding: 0; font-size: 11px;")
        self._btn_archive.clicked.connect(self._on_archive_clicked)

        self._btn_files = QPushButton("📁")
        self._btn_files.setFixedSize(16, 16)
        self._btn_files.setToolTip(tr("Files: drop/drag/preview assets for this silo\n(Shift+Click: Project Config)", getattr(self.main_win, "_current_lang", "EN")))
        self._btn_files.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_files.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        self._btn_files.setStyleSheet("background: transparent; border: none; padding: 0; font-size: 11px;")
        self._btn_files.clicked.connect(self._on_files_clicked)

        self._btn_tick = QPushButton("✅")
        self._btn_tick.setFixedSize(14, 16)
        self._btn_tick.setToolTip(tr("Mark this silo as done (click again to unmark)", getattr(self.main_win, "_current_lang", "EN")))
        self._btn_tick.setCursor(Qt.CursorShape.PointingHandCursor)
        # Verdana (forced app-wide) has no color emoji — pin the tick to an
        # emoji font so ✅ stays green instead of a monochrome fallback,
        # including while the row is hovered.
        from PyQt6.QtGui import QFont
        _emoji_font = QFont("Segoe UI Emoji")
        _emoji_font.setPointSize(9)
        self._btn_tick.setFont(_emoji_font)
        self._btn_tick.setStyleSheet(
            "background: transparent; border: none; padding: 0;"
            " font-family: 'Segoe UI Emoji';")
        self._btn_tick.clicked.connect(self._on_tick_clicked)
        
        self._btn_color_box = QPushButton()
        self._btn_color_box.setFixedSize(12, 12)
        self._btn_color_box.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_color_box.setStyleSheet("background: transparent; border: 1px inset #555; border-radius: 2px;")
        self._btn_color_box.clicked.connect(self._cycle_color)
        self._btn_color_box.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._btn_color_box.customContextMenuRequested.connect(self._show_color_menu)
        self._btn_color_box.hide()

        # tick sits leftmost — before the order number in the title;
        # files button rightmost: with files it doubles as the 📁N counter
        # The colour box owns the leftmost column and never moves: it used to
        # sit after the collapse/tick buttons (each shown conditionally) and
        # inside the row's child indent, so its x drifted per row and the
        # boxes zig-zagged down the sidebar. Indent now comes from a spacer
        # AFTER the box, so nesting shifts the text and not the swatch.
        self._silo_layout.addWidget(self._btn_color_box)
        self._indent = QWidget()
        self._indent.setFixedWidth(0)
        # A bare QWidget is painted by the theme's `QWidget { background-color }`
        # rule, so on a CHILD row this 17px spacer drew a solid dark block over
        # the row's own colour — the "strange rectangle that only appears when
        # a silo has children". It is a layout gap, not a surface.
        self._indent.setStyleSheet("background: transparent; border: none;")
        self._indent.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._silo_layout.addWidget(self._indent)
        self._silo_layout.addWidget(self._btn_collapse)
        self._silo_layout.addWidget(self._btn_tick)
        self._silo_layout.addWidget(self._lbl_text)
        self._silo_layout.addStretch()
        self._silo_layout.addWidget(self._btn_pin)
        self._silo_layout.addWidget(self._btn_archive)
        self._silo_layout.addWidget(self._lbl_count)
        self._silo_layout.addWidget(self._btn_files)

        # Start with buttons hidden
        self._btn_pin.hide()
        self._btn_archive.hide()
        self._btn_files.hide()
        self._btn_tick.hide()
        # Set mouse tracking so we get hover events
        self.setMouseTracking(True)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)

    def _on_collapse_clicked(self):
        if hasattr(self.main_win, 'toggle_silo_collapse'):
            self.main_win.toggle_silo_collapse(self.global_idx)

    def _cycle_color(self):
        if not hasattr(self.main_win, "data"): return
        colors = self.main_win.data.get("silo_color_palette", ["#ff4444", "#ffaa00", "#ffff00", "#00ff00", "#00ffff", "#0000ff", "#ff00ff", "#ffffff", "#000000", "#808080", ""])
        colors = [c for c in colors if c] + [""]
        current = self.main_win.data.get("silo_colors", {}).get(str(self.global_idx), "")
        try:
            idx = colors.index(current)
            next_color = colors[(idx + 1) % len(colors)]
        except ValueError:
            next_color = colors[0]
            
        # setdefault, not get({}): data["silo_colors"] is an alias into
        # silo_colors_all[tab], so a fresh dict written back over it would
        # detach the tab's colours - the colour showed until the next tab
        # switch and then vanished. Same trap as temp_presets.
        colors_dict = self.main_win.data.setdefault("silo_colors", {})
        colors_dict[str(self.global_idx)] = next_color
        self.main_win.mark_dirty()
        if hasattr(self.main_win, "refresh_temp_presets"):
            self.main_win.refresh_temp_presets()

    def _show_color_menu(self, pos):
        if not hasattr(self.main_win, "data"): return
        from PyQt6.QtGui import QColor, QIcon, QPixmap
        from PyQt6.QtWidgets import QMenu
        menu = QMenu(self)
        colors = self.main_win.data.get("silo_color_palette", ["#ff4444", "#ffaa00", "#ffff00", "#00ff00", "#00ffff", "#0000ff", "#ff00ff", "#ffffff", "#000000", "#808080"])
        
        def _set_color(c):
            colors_dict = self.main_win.data.setdefault("silo_colors", {})
            colors_dict[str(self.global_idx)] = c
            self.main_win.mark_dirty()
            if hasattr(self.main_win, "refresh_temp_presets"):
                self.main_win.refresh_temp_presets()

        for c in colors:
            if not c: continue
            pix = QPixmap(16, 16)
            pix.fill(QColor(c))
            act = menu.addAction(QIcon(pix), c)
            act.triggered.connect(lambda checked, col=c: _set_color(col))
            
        act_none = menu.addAction("Remove Color")
        act_none.triggered.connect(lambda checked: _set_color(""))
        
        menu.exec(self._btn_color_box.mapToGlobal(pos))

    def _on_pin_clicked(self):
        """Toggle pin state for this silo."""
        if hasattr(self.main_win, '_toggle_pin_silo'):
            self.main_win._toggle_pin_silo(self.global_idx)

    def _on_archive_clicked(self):
        """Archive this silo directly."""
        if hasattr(self.main_win, 'archive_single_silo'):
            self.main_win.archive_single_silo(self.global_idx)

    def _on_files_clicked(self):
        """Open the per-silo file container drawer or settings."""
        from PyQt6.QtCore import Qt
        from PyQt6.QtWidgets import QApplication
        mods = QApplication.keyboardModifiers()
        if mods & Qt.KeyboardModifier.ControlModifier:
            if hasattr(self.main_win, 'backup_silo_to_files'):
                self.main_win.backup_silo_to_files(self.global_idx, is_archive=self.is_archive)
            return
        if mods & Qt.KeyboardModifier.ShiftModifier:
            if hasattr(self.main_win, 'open_silo_settings'):
                self.main_win.open_silo_settings(self.global_idx)
            return

        if hasattr(self.main_win, 'open_file_container'):
            self.main_win.open_file_container(self.global_idx, is_archive=self.is_archive)

    @staticmethod
    def _dim_color(hex_color):
        """Return a dimmed/grayed version of hex_color for ticked silos."""
        from PyQt6.QtGui import QColor
        c = QColor(hex_color)
        if not c.isValid():
            return hex_color
        # Mix with gray: 60% original + 40% medium gray
        r = int(c.red() * 0.6 + 128 * 0.4)
        g = int(c.green() * 0.6 + 128 * 0.4)
        b = int(c.blue() * 0.6 + 128 * 0.4)
        return QColor(r, g, b).name()

    def _is_ticked(self):
        ticked = self.main_win.data.get("silo_ticked", [])
        return isinstance(ticked, list) and self.global_idx in ticked

    def _on_tick_clicked(self):
        if hasattr(self.main_win, '_toggle_tick_silo'):
            self.main_win._toggle_tick_silo(self.global_idx)

    def _tick_column_reserved(self):
        """Whether this row's tick can ever appear, so its width is held.

        The tick sits BEFORE the title, so showing it on hover used to push
        the whole title sideways — the text ran away from under the pointer.
        The column is now reserved for any row where the tick is reachable
        (ticks enabled, or the row is already ticked) and hover changes only
        what is painted in it. A row that can never show one keeps no gap:
        nothing there can move either way.
        """
        if self.is_archive:
            return False
        if self._is_ticked():
            return True
        data = getattr(self.main_win, "data", {}) or {}
        return data.get("silo_ticks_enabled", "False") == "True"

    def _apply_tick_state(self, show_mark, reserved=None):
        """Paint the tick or leave its space blank — never resize the row."""
        if reserved is None:
            reserved = self._tick_column_reserved()
        if not reserved:
            self._btn_tick.hide()
            return
        self._btn_tick.setText("✅" if show_mark else "")
        # a blank tick must not read as a button
        self._btn_tick.setEnabled(show_mark)
        self._btn_tick.show()

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
        # Play hover sound if CS style is enabled
        if hasattr(self.main_win, 'data') and self.main_win.data.get("cs_style", "False") == "True":
            if hasattr(self.main_win, 'sound_manager'):
                self.main_win.sound_manager.play_hover()
        super().enterEvent(event)

    def leaveEvent(self, event):
        """Hide action buttons when mouse leaves."""
        self._hover_showing = False
        if self._hover_timer:
            self._hover_timer.stop()
        if getattr(self, "_swatch_empty", False):
            self._btn_color_box.setStyleSheet(self._SWATCH_BLANK)
        # pinned silos keep 📌 visible (it's the unpin control)
        self._btn_pin.setVisible(getattr(self, "_is_pinned", False) and not self.is_archive)
        self._btn_archive.hide()
        # with files the 📁N doubles as the counter — it never hides
        self._btn_files.setVisible(getattr(self, "_fcount", 0) > 0 and not self.is_archive)
        # ticked silos always show the mark; setting only gates the hover btn
        self._apply_tick_state(self._is_ticked())
        self._lbl_count.show()
        super().leaveEvent(event)

    def setText(self, text):
        self.full_name = text
        self._update_text()

    def _update_hover_buttons(self):
        """Show/hide action buttons based on hover state."""
        if self._hover_showing and not self.is_archive and self.global_idx >= 0:
            if getattr(self, "_swatch_empty", False):
                self._btn_color_box.setStyleSheet(self._SWATCH_HINT)
            self._btn_pin.show()
            self._btn_archive.show()
            self._btn_files.show()  # empty silos get the plain 📁 on hover
            if self.main_win.data.get("silo_ticks_enabled", "False") == "True":
                self._apply_tick_state(True)
            self._lbl_count.hide()
            self._btn_files.setToolTip(tr("Files: drop/drag/preview assets for this silo\n(Shift+Click: Project Config)", getattr(self.main_win, "_current_lang", "EN")))
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

    def update_data(self, text_label, global_idx, bg_color, font_family="Verdana", scale=1.0, line_count_str="", is_pushed=False, title_bold=False, is_child=False, fcount=0, has_children=False, is_collapsed=False, has_hash=False, color_hex="", is_pinned=False):
        theme_name = self.main_win.data.get("theme", "Default")
        ticked_list = self.main_win.data.get("silo_ticked", [])
        is_ticked = isinstance(ticked_list, list) and global_idx in ticked_list
        sel = getattr(self.main_win, "_silo_selection", None)
        is_selected = bool(sel) and global_idx in sel and not self.is_archive
        # in the cache key because it decides whether the tick's COLUMN is
        # held open: flipping the setting has to repaint the row, and a state
        # tuple without it silently kept the old spacing until something else
        # changed on that row.
        tick_reserved = (not self.is_archive) and (
            is_ticked
            or self.main_win.data.get("silo_ticks_enabled", "False") == "True")
        current_state = (text_label, global_idx, bg_color, font_family, scale, theme_name, line_count_str, is_pushed, title_bold, is_ticked, is_child, fcount, has_children, is_collapsed, has_hash, color_hex, is_pinned, is_selected, tick_reserved)
        if getattr(self, '_last_state', None) == current_state:
            self.show()
            return
        self._last_state = current_state

        self.full_name = text_label
        self._line_count_str = line_count_str
        self.global_idx = global_idx
        # constant left margin so the colour column is identical on every row;
        # children get their shift from the spacer after the swatch instead
        self._silo_layout.setContentsMargins(3, 1, 3, 1)
        self._indent.setFixedWidth(17 if is_child else 0)

        if has_children:
            self._btn_collapse.setText("▸" if is_collapsed else "▾")
            self._btn_collapse.show()
        else:
            self._btn_collapse.hide()

        # A ticked silo ALWAYS shows its ✅ mark (even with ticks disabled —
        # Ctrl+Shift+click can still set it). The setting only controls the
        # convenience hover button, handled in _update_hover_buttons.
        # …and the column it lives in is reserved on every row that could ever
        # show one, exactly like the colour swatch below, so hovering paints a
        # tick instead of pushing the title sideways.
        self._apply_tick_state(is_ticked, reserved=tick_reserved)

        # Pinned silos keep the 📌 button visible as the UNPIN control
        # (clicking it unpins). Unpinned silos only reveal it on hover to pin.
        self._is_pinned = is_pinned
        if is_pinned and not self.is_archive:
            self._btn_pin.setToolTip(tr("Unpin this silo", getattr(self.main_win, "_current_lang", "EN")))
            self._btn_pin.show()
        else:
            self._btn_pin.setToolTip(tr("Pin this silo to top", getattr(self.main_win, "_current_lang", "EN")))
            self._btn_pin.hide()
        
        # While the feature is ON the swatch column is reserved on EVERY row,
        # even where there is nothing to show: hiding the button collapsed its
        # width and shunted that row's title left, so titles never lined up
        # down the list. A colourless row gets an invisible, click-dead
        # placeholder. Turning the feature off reclaims the column entirely.
        if self.main_win.data.get("silo_color_box", "True") != "True":
            self._btn_color_box.hide()
        else:
            self._btn_color_box.show()
        # An empty swatch is an INVITATION, not information, so it follows the
        # same rule as 📌 and 📁: visible on hover, invisible at rest. Drawn
        # permanently it read as a stray rectangle on every titled row that
        # had not been given a colour — which is most of them.
        self._swatch_empty = bool(has_hash and not color_hex)
        if has_hash:
            if color_hex:
                self._btn_color_box.setStyleSheet(f"background: {color_hex}; border: 1px solid #777; border-radius: 2px;")
            else:
                self._btn_color_box.setStyleSheet(
                    self._SWATCH_HINT if self._hover_showing else self._SWATCH_BLANK)
            self._btn_color_box.setEnabled(True)
            self._btn_color_box.setCursor(Qt.CursorShape.PointingHandCursor)
        else:
            self._btn_color_box.setStyleSheet("background: transparent; border: none;")
            self._btn_color_box.setEnabled(False)
            self._btn_color_box.setCursor(Qt.CursorShape.ArrowCursor)
            
        # one files control, far right: with files it IS the counter and
        # stays visible; empty silos only reveal a plain 📁 on hover
        self._fcount = fcount
        if fcount > 0 and not self.is_archive:
            self._btn_files.setText(f"📁{fcount}")
            from fastprompter.utils.textfit import clip_safe_width
            self._btn_files.setFixedSize(
                max(20, clip_safe_width(self._btn_files.text(),
                                        self._btn_files.font(), pad=6)), 16)
            self._btn_files.show()
        else:
            self._btn_files.setText("📁")
            self._btn_files.setFixedSize(16, 16)
            self._btn_files.hide()

        # Apply font scaling safely
        from PyQt6.QtGui import QFont
        f = no_aa(QFont(font_family))
        base_size = 10
        f.setPointSizeF(max(8.0, base_size * scale))
        f.setBold(title_bold)
        f.setStrikeOut(is_ticked)
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
        if is_selected:
            # multi-selected: a flat golden outline overrides the 3D bevel so
            # the batch set reads at a glance
            border = "border: 3px solid #ffd54a;"
        elif is_pushed:
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
        tick_color = self._dim_color(text_color) if is_ticked else text_color
        self._lbl_text.setStyleSheet(f"background: transparent; color: {tick_color}; padding: 0 2px; border: none;")
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
        new_height = self._lbl_text.fontMetrics().height() + 10
        if self.height() != new_height or self.minimumHeight() != new_height:
            self.setFixedHeight(new_height)
            self.updateGeometry()
            p = self.parentWidget()
            if p:
                p.updateGeometry()
                if p.parentWidget():
                    p.parentWidget().updateGeometry()

    def show_menu(self, pos):
        self.main_win.show_temp_menu(self.global_idx, self.mapToGlobal(pos), is_archive=self.is_archive)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            # Ctrl+Shift+click toggles the done-tick — works even when the
            # ✅ hover button is disabled in Settings (ticks off by default)
            mods = e.modifiers()
            if (mods & Qt.KeyboardModifier.ControlModifier
                    and mods & Qt.KeyboardModifier.ShiftModifier
                    and not self.is_archive):
                if hasattr(self.main_win, "_toggle_tick_silo"):
                    self.main_win._toggle_tick_silo(self.global_idx)
                e.accept()
                return
            # Alt+click folds a parent's children away (T-714). The ▾ button
            # only exists on rows that have children and only while hovered;
            # this is the same action without hunting for it. On a childless
            # silo it does nothing rather than selecting it, so the modifier
            # never means two different things.
            if (mods & Qt.KeyboardModifier.AltModifier
                    and not self.is_archive
                    and hasattr(self.main_win, "toggle_silo_collapse")):
                kids = self.main_win._children_map().get(self.global_idx, [])
                if kids:
                    self.main_win.toggle_silo_collapse(self.global_idx)
                e.accept()
                return
            # Play click sound if CS style is enabled
            if hasattr(self.main_win, 'data') and self.main_win.data.get("cs_style", "False") == "True":
                if hasattr(self.main_win, 'sound_manager'):
                    self.main_win.sound_manager.play_click()
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
        try:
            drag, mime = QDrag(self), QMimeData()
            prefix = "arcsilo" if self.is_archive else "silo"
            mime.setText(f"{prefix}:{self.global_idx}")
            # Also offer the silo as a real file, so the same drag can land in
            # Explorer / Total Commander as a named .md. The app's own drop
            # targets read the text above and never look at the urls, so this
            # adds an exit without touching the internal reorder.
            self._attach_file_url(mime)
            drag.setMimeData(mime)
            drag.exec(Qt.DropAction.MoveAction | Qt.DropAction.CopyAction)
        finally:
            self._dragging = False

    def _silo_text(self):
        key = "archive_temp_presets" if self.is_archive else "temp_presets"
        items = self.main_win.data.get(key) or []
        idx = self.global_idx
        if isinstance(items, list) and isinstance(idx, int) and 0 <= idx < len(items):
            live = items[idx]
            # The OPEN silo's text lives in the editor until something flushes
            # it, so dragging out the silo you are typing in would otherwise
            # export a stale copy — the same trap T-716 fixed for undo.
            if (not self.is_archive
                    and idx == getattr(self.main_win, "active_temp_slot", -1)
                    and not getattr(self.main_win, "editing_snippet", None)):
                try:
                    return self.main_win.text_area.toPlainText()
                except (AttributeError, RuntimeError):
                    return live
            return live
        return ""

    def _attach_file_url(self, mime):
        from fastprompter.core.silo_export import write_drag_file

        text = self._silo_text()
        if not (text or "").strip():
            return          # an empty silo has nothing to hand over
        try:
            path = write_drag_file(text)
        except Exception:
            path = None
        if path:
            mime.setUrls([QUrl.fromLocalFile(path)])

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton and not self._dragging:
            mods = e.modifiers()
            shift = bool(mods & Qt.KeyboardModifier.ShiftModifier)
            ctrl = bool(mods & Qt.KeyboardModifier.ControlModifier)
            # Multi-select (silos only): Shift = contiguous range, Ctrl =
            # toggle one. Ctrl+Shift stays the done-tick, so require exactly
            # one of the two modifiers here.
            if not self.is_archive and shift != ctrl:
                if shift:
                    self.main_win.range_select_silos(self.global_idx)
                else:
                    self.main_win.toggle_silo_selection(self.global_idx)
                super().mouseReleaseEvent(e)
                e.accept()
                return
            # Plain click drops any selection and switches to the silo.
            if not self.is_archive:
                self.main_win.clear_silo_selection()
                self.main_win._switch_to_slot(self.global_idx)
            else:
                self.main_win._switch_to_arc_slot(self.global_idx)
            # Play button release sound if CS style is enabled
            if hasattr(self.main_win, 'data') and self.main_win.data.get("cs_style", "False") == "True":
                if hasattr(self.main_win, 'sound_manager'):
                    self.main_win.sound_manager.play_button_release()
            super().mouseReleaseEvent(e)
            e.accept()
            return
        super().mouseReleaseEvent(e)


class SiloGapBar(QFrame):
    """A user-placed separator in the silo list (T-590), draggable with
    Ctrl+LeftButton to re-park it under a different row (T-593).

    Ctrl is required so a stray click on a thin 8px strip cannot move the
    layout by accident. The bar owns no silo: it is a position, so dragging
    it rewrites its anchor slot and nothing about the silos themselves."""

    GRAB_PX = 3

    def __init__(self, main_win, parent=None):
        super().__init__(parent)
        self.main_win = main_win
        self.slot_idx = -1
        self._press_pos = None
        self.setCursor(Qt.CursorShape.SizeVerCursor)
        self.setToolTip(tr("Ctrl+drag to move this gap",
                           getattr(main_win, "_current_lang", "EN")))

    def mousePressEvent(self, e):
        if (e.button() == Qt.MouseButton.LeftButton
                and e.modifiers() & Qt.KeyboardModifier.ControlModifier):
            self._press_pos = e.globalPosition().toPoint()
            e.accept()
            return
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        """Re-park the gap as the cursor crosses rows, so the divider follows
        the drag instead of jumping only on release."""
        if self._press_pos is None or not (e.buttons() & Qt.MouseButton.LeftButton):
            super().mouseMoveEvent(e)
            return
        here = e.globalPosition().toPoint()
        if (here - self._press_pos).manhattanLength() < self.GRAB_PX:
            e.accept()
            return
        target = self._slot_under(here)
        if target is not None and target != self.slot_idx:
            if self.main_win.move_silo_gap(self.slot_idx, target):
                # the refresh re-places this same pooled bar; keep dragging it
                self.slot_idx = target
        e.accept()

    def mouseReleaseEvent(self, e):
        if self._press_pos is None:
            super().mouseReleaseEvent(e)
            return
        start, self._press_pos = self._press_pos, None
        drop = e.globalPosition().toPoint()
        if (drop - start).manhattanLength() < self.GRAB_PX:
            e.accept()
            return                      # a click, not a drag
        target = self._slot_under(drop)
        if target is not None and target != self.slot_idx:
            self.main_win.move_silo_gap(self.slot_idx, target)
        e.accept()

    def _slot_under(self, global_pos):
        """Slot index of the silo button the cursor was released over."""
        best = None
        for btn in getattr(self.main_win, "silo_buttons", []):
            if btn.isHidden() or getattr(btn, "global_idx", -1) < 0:
                continue
            top = btn.mapToGlobal(btn.rect().topLeft()).y()
            if global_pos.y() >= top:
                # keep the lowest row whose top edge is above the cursor, so
                # the gap lands UNDER the row it was dropped on
                if best is None or top > best[0]:
                    best = (top, btn.global_idx)
        return None if best is None else best[1]


class SiloDropWidget(QWidget):
    """Drop target for silo drag-reorder and cross-container moves."""

    def __init__(self, main_win, is_archive=False):
        super().__init__()
        self.setAcceptDrops(True)
        from PyQt6.QtWidgets import QSizePolicy
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.main_win = main_win
        self.is_archive = is_archive
        self.horizontal = False
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(2)
        self.layout.setAlignment(Qt.AlignmentFlag.AlignTop)

    def set_horizontal(self, horizontal):
        """Lay the silos out as a ROW of tabs instead of a column.

        Same button widgets, same order, same drag machinery — only the axis
        changes, so nothing downstream needs to know which mode it is in.
        """
        horizontal = bool(horizontal)
        want = QHBoxLayout if horizontal else QVBoxLayout
        if isinstance(self.layout, want):
            self.horizontal = horizontal
            return
        old = self.layout
        widgets = [old.itemAt(i).widget() for i in range(old.count())]
        widgets = [w for w in widgets if w is not None]
        for w in widgets:
            old.removeWidget(w)
        # A widget can own only one layout, and Qt refuses to attach a second
        # while the first is installed. Handing the old one to a throwaway
        # parent is the documented way to detach it.
        QWidget().setLayout(old)
        new = want()
        new.setContentsMargins(0, 0, 0, 0)
        new.setSpacing(2)
        new.setAlignment(Qt.AlignmentFlag.AlignLeft if horizontal
                         else Qt.AlignmentFlag.AlignTop)
        for w in widgets:
            new.addWidget(w)
        self.setLayout(new)
        self.layout = new
        self.horizontal = horizontal

    def _axis(self, rect):
        """(near edge, far edge, extent) along the layout's own axis."""
        if self.horizontal:
            return rect.left(), rect.right(), rect.width()
        return rect.top(), rect.bottom(), rect.height()

    def dragEnterEvent(self, e):
        if e.mimeData().hasText() and (e.mimeData().text().startswith("silo:") or e.mimeData().text().startswith("arcsilo:")):
            e.acceptProposedAction()

    def _visible_buttons(self):
        # isVisibleTo(self), not isVisible(): the latter is False for every
        # child while the window itself is hidden, which made the drop
        # classifier see an empty list and answer "append at the end" for
        # every position.
        out = []
        for i in range(self.layout.count()):
            w = self.layout.itemAt(i).widget()
            if (w and w.isVisibleTo(self) and hasattr(w, "global_idx")
                    and type(w).__name__ == "DraggableSiloButton"):
                out.append(w)
        return out

    # How much of a row counts as "drop it INTO this silo" (nest / swap).
    # It used to be the middle 44%, with only 28% at each edge meaning
    # "put it above / below" — so releasing over the top of a row usually
    # nested the silo instead of moving it there, which is the single
    # biggest reason silo dragging felt unpredictable. The move bands are
    # now the majority of the row and the nest band is a deliberate aim at
    # its centre.
    _NEST_BAND = 0.20

    def _drop_target_at(self, pos):
        """Classify a drop position.

        Returns ("swap", button) when pos is over the centre band of a silo,
        or ("move", gap_index) when pos is anywhere in its top or bottom
        band (gap_index counts insertion boundaries among visible buttons).
        """
        btns = self._visible_buttons()
        # One rule, both axes: in tab mode "above/below" is "left/right" and
        # the bands are measured across the button's width instead of its
        # height. Duplicating the maths per orientation is how the two
        # surfaces in T-702 drifted apart in the first place.
        coord = pos.x() if self.horizontal else pos.y()
        for i, btn in enumerate(btns):
            near, far, extent = self._axis(btn.geometry())
            if coord <= far:
                nest = max(2, int(extent * self._NEST_BAND))
                edge = (extent - nest) / 2.0
                if coord < near + edge:
                    return "move", i
                if coord > far - edge:
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
                # Insertion line between silos: drop here reorders. Same
                # answer the drop itself will use, drawn across whichever
                # axis the layout runs on.
                visible_btns = self._visible_buttons()
                at = 0
                if target == 0:
                    at = self._axis(visible_btns[0].geometry())[0] - 1 if visible_btns else 0
                elif target < len(visible_btns):
                    at = self._axis(visible_btns[target].geometry())[0] - 1
                elif visible_btns:
                    at = self._axis(visible_btns[-1].geometry())[1] + 1
                if self.horizontal:
                    painter.drawLine(at, 0, at, self.height())
                else:
                    painter.drawLine(0, at, self.width(), at)
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
                # A gap drop used to promote the dragged silo unconditionally,
                # so simply reordering two children threw them out of their
                # parent. Only leaving the parent's own run of children counts
                # as dragging it out; inside that run it is a sibling reorder.
                parent = (None if self.is_archive
                          else self.main_win.silo_parent_of(source_idx))
                if parent is not None:
                    # The parent's run on screen: the parent button itself,
                    # then its children. Gaps strictly inside that run (and the
                    # one right after the last child) reorder the siblings;
                    # anywhere else really is dragging the child out.
                    rows = [b.global_idx for b in btns]
                    parent_row = rows.index(parent) if parent in rows else -1
                    last_child_row = parent_row
                    for row in range(parent_row + 1, len(rows)):
                        if self.main_win.silo_parent_of(rows[row]) != parent:
                            break
                        last_child_row = row
                    if parent_row >= 0 and parent_row < target <= last_child_row + 1:
                        before = (rows[target]
                                  if target <= last_child_row
                                  else None)      # dropped past the last sibling
                        self.main_win.reorder_sibling(source_idx, before)
                        e.acceptProposedAction()
                        return
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
