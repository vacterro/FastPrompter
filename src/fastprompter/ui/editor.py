from PyQt6.QtWidgets import QTextEdit, QWidget
from PyQt6.QtCore import Qt, QTimer, QSize, QRect, QPoint, QPointF
from PyQt6.QtGui import QTextCursor, QPainter, QColor, QPolygon, QFont
from PyQt6 import sip

class LineNumberArea(QWidget):
    def __init__(self, editor):
        super().__init__(editor)
        self.editor = editor
        
    def sizeHint(self):
        return QSize(self.editor.line_number_area_width(), 0)
        
    def paintEvent(self, event):
        self.editor.line_number_area_paint_event(event)
        
    def mousePressEvent(self, event):
        self.editor.line_number_area_mouse_press_event(event)

class VaultTextEdit(QTextEdit):
    def __init__(self, main_win):
        super().__init__()
        self.main_win = main_win
        self.document().setUndoRedoEnabled(True)
        self._right_drag_start = None
        self._dragged = False
        
        self.line_number_area = LineNumberArea(self)
        self.document().documentLayout().documentSizeChanged.connect(self.update_line_number_area_width)
        self.verticalScrollBar().valueChanged.connect(self.line_number_area.update)
        self.textChanged.connect(self.line_number_area.update)
        self.cursorPositionChanged.connect(self.line_number_area.update)

    def set_active_document(self, doc):
        try:
            self.document().documentLayout().documentSizeChanged.disconnect(self.update_line_number_area_width)
        except: pass
        self.setDocument(doc)
        self.document().setUndoRedoEnabled(True)
        self.document().documentLayout().documentSizeChanged.connect(self.update_line_number_area_width)
        self.update_line_number_area_width()
        font = self.font()
        font.setStyleStrategy(QFont.StyleStrategy.NoAntialias | QFont.StyleStrategy.NoSubpixelAntialias)
        self.document().setDefaultFont(font)

    def line_number_area_width(self):
        if not hasattr(self, 'main_win') or self.main_win.data.get("show_line_numbers", "False") != "True": return 0
        digits = 1
        m = max(1, self.document().blockCount())
        while m >= 10:
            m /= 10
            digits += 1
        return 3 + self.fontMetrics().horizontalAdvance('9') * digits + 10

    def update_line_number_area_width(self):
        self.setViewportMargins(self.line_number_area_width(), 0, 0, 0)
        cr = self.contentsRect()
        self.line_number_area.setGeometry(QRect(cr.left(), cr.top(), self.line_number_area_width(), cr.height()))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        cr = self.contentsRect()
        self.line_number_area.setGeometry(QRect(cr.left(), cr.top(), self.line_number_area_width(), cr.height()))

    def line_number_area_paint_event(self, event):
        if not hasattr(self, 'main_win') or self.main_win.data.get("show_line_numbers", "False") != "True": return
        try:
            painter = QPainter(self.line_number_area)
            painter.setFont(self.font())
            painter.fillRect(event.rect(), QColor("#1e1e1e" if self.main_win.data.get("theme", "Default") != "Default" else "#e0e0e0"))
            
            block = self.document().begin()
            block_number = block.blockNumber()
            
            while block.isValid():
                cursor = QTextCursor(block)
                rect = self.cursorRect(cursor)
                
                if rect.bottom() >= event.rect().top() and rect.top() <= event.rect().bottom():
                    number = str(block_number + 1)
                    painter.setPen(QColor("#808080"))
                    painter.drawText(0, int(rect.top()), self.line_number_area.width() - 10, self.fontMetrics().height(), Qt.AlignmentFlag.AlignRight, number)
                    
                    mark = block.userState()
                    if mark > 0:
                        y_center = int(rect.top() + self.fontMetrics().height() / 2)
                        x_center = self.line_number_area.width() - 5
                        if mark == 1:
                            painter.setBrush(QColor("red"))
                            painter.setPen(Qt.PenStyle.NoPen)
                            painter.drawEllipse(QPoint(x_center, y_center), 3, 3)
                        elif mark == 2:
                            painter.setBrush(QColor("cyan"))
                            painter.setPen(Qt.PenStyle.NoPen)
                            painter.drawRect(x_center - 3, y_center - 3, 6, 6)
                        elif mark == 3:
                            painter.setBrush(QColor("yellow"))
                            painter.setPen(Qt.PenStyle.NoPen)
                            poly = QPolygon([QPoint(x_center, y_center - 4), QPoint(x_center - 4, y_center + 3), QPoint(x_center + 4, y_center + 3)])
                            painter.drawPolygon(poly)
                block = block.next()
                block_number += 1
        except Exception as e:
            print("PAINT ERROR", e)




    def line_number_area_mouse_press_event(self, event):
        block = self.document().begin()
        while block.isValid():
            cursor = QTextCursor(block)
            rect = self.cursorRect(cursor)
            
            # Since cursorRect gives the rect of the first character, we'll estimate the block height
            block_height = self.document().documentLayout().blockBoundingRect(block).height()
            
            if rect.top() <= event.pos().y() <= rect.top() + block_height:
                current = block.userState()
                if current == -1: current = 0
                block.setUserState((current + 1) % 4)
                self.line_number_area.update()
                break
            block = block.next()

    def mousePressEvent(self, event):
        if sip.isdeleted(self): return
        if event.button() == Qt.MouseButton.LeftButton and event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            # Ctrl+LClick: Toggle the current line's bullet state (- ↔ •)
            import re
            super().mousePressEvent(event)  # Move cursor first
            cursor = self.textCursor()
            cursor.beginEditBlock()
            cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
            cursor.movePosition(QTextCursor.MoveOperation.EndOfBlock, QTextCursor.MoveMode.KeepAnchor)
            line = cursor.selectedText()
            if re.match(r'^\s*•\s*', line):
                new_line = re.sub(r'^(\s*)•\s*', r'\1- ', line)
            elif re.match(r'^\s*-\s+', line):
                new_line = re.sub(r'^(\s*)-\s+', r'\1• ', line)
            else:
                cursor.endEditBlock()
                return
            cursor.insertText(new_line)
            cursor.endEditBlock()
            event.accept()
            return
        if event.button() == Qt.MouseButton.RightButton:
            self._right_drag_start = event.globalPosition().toPoint()
            self._dragged = False
        super().mousePressEvent(event)


    def mouseMoveEvent(self, event):
        if sip.isdeleted(self): return
        if event.buttons() & Qt.MouseButton.RightButton and self._right_drag_start is not None:
            delta = event.globalPosition().toPoint() - self._right_drag_start
            if not self._dragged and delta.manhattanLength() > 3:
                self._dragged = True
            if self._dragged:
                self.main_win.move(self.main_win.pos() + delta)
                self._right_drag_start = event.globalPosition().toPoint()
                return
        super().mouseMoveEvent(event)

    def contextMenuEvent(self, event):
        if self._dragged:
            self._dragged = False
            event.ignore()
            return
        super().contextMenuEvent(event)

    def insertFromMimeData(self, source):
        if self.main_win.btn_format.text() == "Plain":
            if source.hasText(): self.insertPlainText(source.text())
        else:
            super().insertFromMimeData(source)

    def wheelEvent(self, event):
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            delta = event.angleDelta().y()
            if delta:
                self.main_win.adjust_font_size(1 if delta > 0 else -1)
                event.accept()
                return
        super().wheelEvent(event)

    def keyPressEvent(self, event):
        mods = event.modifiers()
        
        if mods == Qt.KeyboardModifier.ControlModifier and event.key() in (Qt.Key.Key_Z, Qt.Key.Key_Y):
            event.accept()
            return

        if mods & Qt.KeyboardModifier.ControlModifier and event.key() in (Qt.Key.Key_Home, Qt.Key.Key_End):
            cursor = self.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.Start if event.key() == Qt.Key.Key_Home else QTextCursor.MoveOperation.End)
            self.setTextCursor(cursor)
            self.ensureCursorVisible()
            event.accept()
            return

        if mods & Qt.KeyboardModifier.ControlModifier and event.key() in (Qt.Key.Key_Plus, Qt.Key.Key_Equal, Qt.Key.Key_Minus, Qt.Key.Key_Underscore):
            self.main_win.adjust_ui_scale(0.05 if event.key() in (Qt.Key.Key_Plus, Qt.Key.Key_Equal) else -0.05)
            event.accept()
            return

        if event.key() == Qt.Key.Key_Home:
            cursor = self.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.Start)
            self.setTextCursor(cursor)
            self.ensureCursorVisible()
            event.accept()
            return

        if event.key() == Qt.Key.Key_End:
            cursor = self.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.End)
            self.setTextCursor(cursor)
            self.ensureCursorVisible()
            event.accept()
            return

        if event.key() == Qt.Key.Key_C and mods == Qt.KeyboardModifier.ControlModifier:
            cursor = self.textCursor()
            if not cursor.hasSelection():
                cursor.select(QTextCursor.SelectionType.Document)
                self.setTextCursor(cursor)
            super().keyPressEvent(event)
            if self.main_win.cb_ctrl_c.isChecked():
                QTimer.singleShot(10, lambda: not sip.isdeleted(self) and not sip.isdeleted(self.main_win) and self.main_win.hide_and_save())
            return

        if event.key() == Qt.Key.Key_Backspace and (mods & Qt.KeyboardModifier.AltModifier):
            try:
                cursor = self.textCursor()
                if cursor.hasSelection():
                    cursor.removeSelectedText()
                else:
                    cursor.movePosition(
                        QTextCursor.MoveOperation.PreviousWord,
                        QTextCursor.MoveMode.KeepAnchor
                    )
                    cursor.removeSelectedText()
                self.setTextCursor(cursor)
            except Exception:
                pass
            event.accept()
            return

        if event.key() == Qt.Key.Key_Space and mods == Qt.KeyboardModifier.NoModifier:
            if self.main_win.data.get("auto_bullet", "False") == "True":
                cursor = self.textCursor()
                if not cursor.hasSelection():
                    block = cursor.block()
                    text_in_block = block.text()
                    pos_in_block = cursor.positionInBlock()
                    text_before = text_in_block[:pos_in_block]
                    if text_before.strip() == "-":
                        # We only want to replace the text before the cursor, not the whole block using KeepAnchor.
                        # Instead of KeepAnchor, we move the cursor backwards by len(text_before) characters.
                        cursor.movePosition(QTextCursor.MoveOperation.Left, QTextCursor.MoveMode.KeepAnchor, len(text_before))
                        cursor.insertText(text_before.replace("-", "•", 1) + " ")
                        self.setTextCursor(cursor)
                        event.accept()
                        return

        try:
            super().keyPressEvent(event)
        except Exception:
            event.accept()
