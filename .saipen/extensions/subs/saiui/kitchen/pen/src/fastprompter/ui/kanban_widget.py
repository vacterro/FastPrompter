from PyQt6.QtCore import QMimeData, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QDrag
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)


class CardState:
    def __init__(self, title, done, continuation=None):
        self.title = title
        self.done = done
        self.continuation = continuation or []

class ColumnState:
    def __init__(self, name):
        self.name = name
        self.cards = []

class KanbanParser:
    @staticmethod
    def parse(text: str):
        lines = text.split('\n')
        columns = []
        current_col = None
        current_card = None
        
        for line in lines:
            if line.startswith('## '):
                current_col = ColumnState(line[3:].strip())
                columns.append(current_col)
                current_card = None
            elif current_col and (line.startswith('- [ ]') or line.startswith('- [x]') or line.startswith('- [X]')):
                done = line.startswith('- [x]') or line.startswith('- [X]')
                title = line[5:].strip()
                current_card = CardState(title, done)
                current_col.cards.append(current_card)
            elif current_col and line.startswith('- '):
                # Legacy uncheckboxed cards or plain list items
                title = line[2:].strip()
                current_card = CardState(title, False)
                current_col.cards.append(current_card)
            elif current_card and line.startswith('  '):
                current_card.continuation.append(line[2:])
            elif not line.strip():
                # blank lines are ignored unless we want to preserve them
                continue
            else:
                pass
        if not columns:
            columns.append(ColumnState("New Column"))
            if text.strip():
                # Dump the unrecognized text into the first column as a card so it's not lost
                columns[0].cards.append(CardState(text.strip(), False))
                
        return columns

class KanbanCardWidget(QFrame):
    changed = pyqtSignal()
    
    def __init__(self, card_state, parent=None):
        super().__init__(parent)
        self.card_state = card_state
        self.setObjectName("kanban_card")
        self.setAcceptDrops(True)
        
        # not `self.layout` — see the note in table_widget: it shadows
        # QWidget.layout() and breaks every generic widget walk
        self._box = QHBoxLayout(self)
        self._box.setContentsMargins(4, 4, 4, 4)
        self._box.setSpacing(4)
        
        self.checkbox = QCheckBox()
        self.checkbox.setChecked(self.card_state.done)
        self.checkbox.toggled.connect(self._on_check)
        
        title_text = self.card_state.title
        if self.card_state.continuation:
            title_text += "\n" + "\n".join(self.card_state.continuation)

        self.lbl_title = QLabel(title_text)
        self.lbl_title.setWordWrap(True)
        # Removed TextSelectableByMouse so right-click falls through to the card's context menu
        self.lbl_title.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        
        self._box.addWidget(self.checkbox)
        self._box.addWidget(self.lbl_title, 1)
        
        self.editor = QLineEdit(self.card_state.title)
        self.editor.hide()
        self.editor.editingFinished.connect(self._on_edit_finished)
        self._box.addWidget(self.editor, 1)
        
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_menu)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._mark_done_state()
        
    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Space:
            self.checkbox.setChecked(not self.checkbox.isChecked())
            e.accept()
        elif e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._enter_edit_mode()
            e.accept()
        elif e.key() == Qt.Key.Key_Delete:
            # Simple delete for now
            self._do_delete()
            e.accept()
        # Alt+arrows would go here, but for simplicity we rely on drag and drop
        # or we implement manual move logic.
        else:
            super().keyPressEvent(e)
            
    def _enter_edit_mode(self):
        self.lbl_title.hide()
        self.editor.show()
        self.editor.setFocus()
        self.editor.selectAll()
        
    def mouseDoubleClickEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._enter_edit_mode()
            
    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.drag_start = e.pos()
        super().mousePressEvent(e)
            
    def mouseMoveEvent(self, e):
        if not hasattr(self, 'drag_start'):
            return
        if e.buttons() & Qt.MouseButton.LeftButton:
            dist = (e.pos() - self.drag_start).manhattanLength()
            if dist > QApplication.startDragDistance():
                drag = QDrag(self)
                mime = QMimeData()
                mime.setText("kanban_card")
                drag.setMimeData(mime)
                drag.exec(Qt.DropAction.MoveAction)
                
    def _mark_done_state(self):
        """Tell the stylesheet whether this card is done, and re-polish.

        A dynamic property does not re-evaluate the sheet on its own, so a
        ticked card kept full-strength text until something else repainted it.
        """
        self.setProperty("done", "true" if self.card_state.done else "false")
        style = self.style()
        if style is not None:
            style.unpolish(self)
            style.polish(self)

    def _on_check(self, checked):
        if self.card_state.done != checked:
            self.card_state.done = checked
            self._mark_done_state()
            self.changed.emit()
        
    def _on_edit_finished(self):
        self.editor.hide()
        self.lbl_title.show()
        if self.editor.text() != self.card_state.title:
            self.card_state.title = self.editor.text()
            title_text = self.card_state.title
            if self.card_state.continuation:
                title_text += "\n" + "\n".join(self.card_state.continuation)
            self.lbl_title.setText(title_text)
            self.changed.emit()
            
    def _show_menu(self, pos):
        menu = QMenu(self)
        act_edit = menu.addAction("✏️ Edit")
        act_edit.triggered.connect(self._enter_edit_mode)
        menu.addAction("❌ Delete", self._do_delete)
        menu.exec(self.mapToGlobal(pos))
        
    def _get_column_widget(self):
        w = self
        while w:
            if isinstance(w, KanbanColumnWidget):
                return w
            w = w.parentWidget()
        return None

    def _do_delete(self, _checked=None):
        col_widget = self._get_column_widget()
        if col_widget:
            col_widget.remove_card(self)
            
    def dragEnterEvent(self, e):
        if e.mimeData().hasText() and e.mimeData().text() == "kanban_card":
            e.acceptProposedAction()
            
    def dropEvent(self, e):
        source_cw = e.source()
        if source_cw and isinstance(source_cw, KanbanCardWidget) and source_cw != self:
            source_col = source_cw._get_column_widget()
            target_col = self._get_column_widget()
            if source_col and target_col:
                # Detach from source WITHOUT deleteLater
                if source_cw.card_state in source_col.column_state.cards:
                    source_col.column_state.cards.remove(source_cw.card_state)
                source_col.cards_layout.removeWidget(source_cw)
                source_col.lbl_count.setText(f"({len(source_col.column_state.cards)})")
                source_col.changed.emit()

                # Insert into target at correct position
                idx = target_col.column_state.cards.index(self.card_state)
                if e.position().y() > self.height() / 2:
                    idx += 1
                target_col.column_state.cards.insert(idx, source_cw.card_state)
                target_col.cards_layout.insertWidget(idx, source_cw)

                target_col.lbl_count.setText(f"({len(target_col.column_state.cards)})")
                target_col.changed.emit()
                e.acceptProposedAction()

class KanbanColumnWidget(QFrame):
    changed = pyqtSignal()
    
    def __init__(self, column_state, parent=None):
        super().__init__(parent)
        self.column_state = column_state
        self.setObjectName("kanban_column")
        self.setAcceptDrops(True)
        
        self._box = QVBoxLayout(self)
        self._box.setContentsMargins(4, 4, 4, 4)
        
        header_layout = QHBoxLayout()
        self.lbl_name = QLabel(column_state.name)
        self.lbl_name.setObjectName("kanban_column_name")
        self.lbl_name.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.editor_name = QLineEdit(column_state.name)
        self.editor_name.hide()
        self.editor_name.editingFinished.connect(self._on_name_edit_finished)
        
        self.lbl_count = QLabel(f"({len(column_state.cards)})")
        self.lbl_count.setObjectName("kanban_column_count")

        btn_add = QLabel("+")
        btn_add.setObjectName("kanban_add")
        btn_add.setToolTip("Add a card to this column")
        btn_add.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_add.mousePressEvent = self._on_add_clicked
        
        header_layout.addWidget(self.lbl_name)
        header_layout.addWidget(self.editor_name)
        header_layout.addWidget(self.lbl_count, 1)
        header_layout.addWidget(btn_add)
        self._box.addLayout(header_layout)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.cards_widget = QWidget()
        self.cards_layout = QVBoxLayout(self.cards_widget)
        self.cards_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.cards_layout.setContentsMargins(2, 2, 2, 2)
        self.cards_layout.setSpacing(4)
        self.scroll.setWidget(self.cards_widget)
        self._box.addWidget(self.scroll, 1)

        for card in self.column_state.cards:
            self._add_card_widget(card)

        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_menu)
        
    def _enter_edit_mode(self):
        self.lbl_name.hide()
        self.editor_name.show()
        self.editor_name.setText(self.column_state.name)
        self.editor_name.setFocus()
        self.editor_name.selectAll()
        
    def mouseDoubleClickEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._enter_edit_mode()
            e.accept()
            
    def _on_name_edit_finished(self):
        self.editor_name.hide()
        if self.editor_name.text() != self.column_state.name:
            self.column_state.name = self.editor_name.text()
            self.lbl_name.setText(self.column_state.name)
            self.changed.emit()
        self.lbl_name.show()
        
    def _show_menu(self, pos):
        menu = QMenu(self)
        
        act_edit = menu.addAction("✏️ Edit")
        act_edit.triggered.connect(self._enter_edit_mode)
        
        menu.addAction("❌ Delete", self._do_delete_column)
        menu.exec(self.mapToGlobal(pos))
        
    def _do_delete_column(self, _checked=None):
        # find the board and remove this column
        p = self.parentWidget()
        while p and not hasattr(p, "columns"):
            p = p.parentWidget()
        if p and hasattr(p, "columns"):
            if self.column_state in p.columns:
                p.columns.remove(self.column_state)
            p.board_layout.removeWidget(self)
            self.deleteLater()
            if hasattr(p, "_schedule_sync"):
                p._schedule_sync()

    def _add_card_widget(self, card_state):
        cw = KanbanCardWidget(card_state, self.cards_widget)
        cw.changed.connect(self.changed.emit)
        self.cards_layout.addWidget(cw)
        
    def _on_add_clicked(self, e=None):
        new_card = CardState("New Card", False)
        self.column_state.cards.append(new_card)
        cw = KanbanCardWidget(new_card, self.cards_widget)
        cw.changed.connect(self.changed.emit)
        self.cards_layout.addWidget(cw)
        self.lbl_count.setText(f"({len(self.column_state.cards)})")
        self.changed.emit()
        cw._enter_edit_mode()
        
    def remove_card(self, cw):
        if cw.card_state in self.column_state.cards:
            self.column_state.cards.remove(cw.card_state)
        self.cards_layout.removeWidget(cw)
        cw.deleteLater()
        self.lbl_count.setText(f"({len(self.column_state.cards)})")
        self.changed.emit()
        
    def dragEnterEvent(self, e):
        if e.mimeData().hasText() and e.mimeData().text() == "kanban_card":
            e.acceptProposedAction()
            
    def dropEvent(self, e):
        source_cw = e.source()
        if source_cw and isinstance(source_cw, KanbanCardWidget):
            source_col = source_cw._get_column_widget()
            if source_col:
                if source_cw.card_state in source_col.column_state.cards:
                    source_col.column_state.cards.remove(source_cw.card_state)
                source_col.cards_layout.removeWidget(source_cw)
                source_col.lbl_count.setText(f"({len(source_col.column_state.cards)})")
                source_col.changed.emit()
                
                self.column_state.cards.append(source_cw.card_state)
                self.cards_layout.addWidget(source_cw)
                self.lbl_count.setText(f"({len(self.column_state.cards)})")
                self.changed.emit()
                e.acceptProposedAction()

class KanbanBoardWidget(QScrollArea):
    changed = pyqtSignal(str)
    
    undoRequested = pyqtSignal()
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.container = QWidget()
        self.board_layout = QHBoxLayout(self.container)
        self.board_layout.setAlignment(Qt.AlignmentFlag.AlignLeft)
        self.setWidget(self.container)
        self.columns = []
        self._sync_timer = QTimer(self)
        self._sync_timer.setInterval(300)
        self._sync_timer.setSingleShot(True)
        self._sync_timer.timeout.connect(self._do_serialize)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        
    def keyPressEvent(self, e):
        mods = e.modifiers()
        if mods == Qt.KeyboardModifier.ControlModifier and e.key() == Qt.Key.Key_Z:
            self.undoRequested.emit()
            e.accept()
            return
            
        if e.key() == Qt.Key.Key_N and self.columns:
            # Add to first column
            first_col_widget = self.board_layout.itemAt(0).widget()
            if first_col_widget:
                first_col_widget._on_add_clicked(e)
            e.accept()
        else:
            super().keyPressEvent(e)
        
    def load_markdown(self, text):
        # A board silo can still have a title, a goal line, a footer. The
        # parser recognises only "## column" and "- [ ] card" and silently
        # drops the rest, and serialize() writes back over the WHOLE silo —
        # so without keeping the lines around the board, "# Sprint 12" and
        # every note vanished on the first click. Measured.
        from fastprompter.ui import silo_region
        all_lines = (text or "").split("\n")
        span = silo_region.board_region(all_lines)
        self._prefix, region, self._suffix = silo_region.split(all_lines, span)
        text = "\n".join(region)

        while self.board_layout.count():
            item = self.board_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        self.columns = KanbanParser.parse(text)
        
        for col in self.columns:
            cw = KanbanColumnWidget(col, self.container)
            cw.changed.connect(self._schedule_sync)
            self.board_layout.addWidget(cw)
            
        # Add a prominent "Add Column" button
        self.btn_add_col = QLabel("+ Column")
        self.btn_add_col.setObjectName("kanban_add")
        self.btn_add_col.setToolTip("Add a column to this board")
        self.btn_add_col.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_add_col.mousePressEvent = self._on_add_column_clicked
        
        self.add_col_container = QWidget()
        add_col_layout = QVBoxLayout(self.add_col_container)
        add_col_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        add_col_layout.addWidget(self.btn_add_col)
        self.board_layout.addWidget(self.add_col_container)
            
    def _on_add_column_clicked(self, e=None):
        new_col = ColumnState("New Column")
        self.columns.append(new_col)
        cw = KanbanColumnWidget(new_col, self.container)
        cw.changed.connect(self._schedule_sync)
        # Insert before the add button container
        self.board_layout.insertWidget(self.board_layout.count() - 1, cw)
        self._schedule_sync()
        cw._enter_edit_mode()
        
    def _schedule_sync(self):
        self._sync_timer.start()
        
    def _do_serialize(self):
        self.changed.emit(self.serialize())
        
    def serialize(self):
        """The whole silo: the text around the board, with the board rebuilt."""
        from fastprompter.ui import silo_region
        lines = []
        for col in self.columns:
            lines.append(f"## {col.name}")
            for card in col.cards:
                mark = "[x]" if card.done else "[ ]"
                lines.append(f"- {mark} {card.title}")
                for line in card.continuation:
                    lines.append(f"  {line}")
            lines.append("")
        while lines and not lines[-1].strip():
            lines.pop()
        return silo_region.splice(getattr(self, "_prefix", []), lines,
                                 getattr(self, "_suffix", []))
