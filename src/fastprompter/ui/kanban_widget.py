import re
from PyQt6.QtWidgets import (
    QScrollArea, QWidget, QHBoxLayout, QVBoxLayout, QFrame,
    QLabel, QLineEdit, QCheckBox, QMenu, QApplication
)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer, QMimeData, QPoint
from PyQt6.QtGui import QDrag, QFont, QAction, QCursor

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
        
        self.layout = QHBoxLayout(self)
        self.layout.setContentsMargins(4, 4, 4, 4)
        self.layout.setSpacing(4)
        
        self.checkbox = QCheckBox()
        self.checkbox.setChecked(self.card_state.done)
        self.checkbox.toggled.connect(self._on_check)
        
        title_text = self.card_state.title
        if self.card_state.continuation:
            title_text += "\n" + "\n".join(self.card_state.continuation)

        self.lbl_title = QLabel(title_text)
        self.lbl_title.setWordWrap(True)
        self.lbl_title.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        
        self.layout.addWidget(self.checkbox)
        self.layout.addWidget(self.lbl_title, 1)
        
        self.editor = QLineEdit(self.card_state.title)
        self.editor.hide()
        self.editor.editingFinished.connect(self._on_edit_finished)
        self.layout.addWidget(self.editor, 1)
        
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_menu)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        
    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Space:
            self.checkbox.setChecked(not self.checkbox.isChecked())
            e.accept()
        elif e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.mouseDoubleClickEvent(e)
            e.accept()
        elif e.key() == Qt.Key.Key_Delete:
            # Simple delete for now
            self._do_delete()
            e.accept()
        # Alt+arrows would go here, but for simplicity we rely on drag and drop 
        # or we implement manual move logic.
        else:
            super().keyPressEvent(e)
        
    def mouseDoubleClickEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.lbl_title.hide()
            self.editor.show()
            self.editor.setText(self.card_state.title)
            self.editor.setFocus()
            self.editor.selectAll()
            
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
                
    def _on_check(self, checked):
        if self.card_state.done != checked:
            self.card_state.done = checked
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
        menu.addAction("Delete", self._do_delete)
        menu.exec(self.mapToGlobal(pos))
        
    def _get_column_widget(self):
        w = self
        while w:
            if isinstance(w, KanbanColumnWidget):
                return w
            w = w.parentWidget()
        return None

    def _do_delete(self):
        col_widget = self._get_column_widget()
        if col_widget:
            col_widget.remove_card(self)

class KanbanColumnWidget(QFrame):
    changed = pyqtSignal()
    
    def __init__(self, column_state, parent=None):
        super().__init__(parent)
        self.column_state = column_state
        self.setObjectName("kanban_column")
        self.setAcceptDrops(True)
        
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(4, 4, 4, 4)
        
        header_layout = QHBoxLayout()
        self.lbl_name = QLabel(f"<b>{column_state.name}</b>")
        self.lbl_count = QLabel(f"({len(column_state.cards)})")
        self.lbl_count.setStyleSheet("color: gray;")
        
        btn_add = QLabel("＋")
        btn_add.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_add.mousePressEvent = self._on_add_clicked
        
        header_layout.addWidget(self.lbl_name)
        header_layout.addWidget(self.lbl_count, 1)
        header_layout.addWidget(btn_add)
        self.layout.addLayout(header_layout)
        
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.cards_widget = QWidget()
        self.cards_layout = QVBoxLayout(self.cards_widget)
        self.cards_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.cards_layout.setContentsMargins(2, 2, 2, 2)
        self.cards_layout.setSpacing(4)
        self.scroll.setWidget(self.cards_widget)
        self.layout.addWidget(self.scroll, 1)
        
        for card in self.column_state.cards:
            self._add_card_widget(card)

    def _add_card_widget(self, card_state):
        cw = KanbanCardWidget(card_state, self.cards_widget)
        cw.changed.connect(self.changed.emit)
        self.cards_layout.addWidget(cw)
        
    def _on_add_clicked(self, e):
        new_card = CardState("New Card", False)
        self.column_state.cards.append(new_card)
        cw = KanbanCardWidget(new_card, self.cards_widget)
        cw.changed.connect(self.changed.emit)
        self.cards_layout.addWidget(cw)
        self.lbl_count.setText(f"({len(self.column_state.cards)})")
        self.changed.emit()
        cw.mouseDoubleClickEvent(e)
        
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
                source_col.remove_card(source_cw)
                self.column_state.cards.append(source_cw.card_state)
                self._add_card_widget(source_cw.card_state)
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
        while self.board_layout.count():
            item = self.board_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
                
        self.columns = KanbanParser.parse(text)
        
        for col in self.columns:
            cw = KanbanColumnWidget(col, self.container)
            cw.changed.connect(self._schedule_sync)
            self.board_layout.addWidget(cw)
            
    def _schedule_sync(self):
        self._sync_timer.start()
        
    def _do_serialize(self):
        self.changed.emit(self.serialize())
        
    def serialize(self):
        lines = []
        for col in self.columns:
            lines.append(f"## {col.name}")
            for card in col.cards:
                mark = "[x]" if card.done else "[ ]"
                lines.append(f"- {mark} {card.title}")
                for line in card.continuation:
                    lines.append(f"  {line}")
            lines.append("")
        return "\n".join(lines).strip()
