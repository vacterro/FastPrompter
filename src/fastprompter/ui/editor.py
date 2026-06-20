from PyQt6.QtWidgets import QTextEdit
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QTextCursor
from PyQt6 import sip

class VaultTextEdit(QTextEdit):
    def __init__(self, main_win):
        super().__init__()
        self.main_win = main_win
        self.document().setUndoRedoEnabled(True)

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
        
        if mods == Qt.KeyboardModifier.ControlModifier:
            if event.key() == Qt.Key.Key_Z:
                self.undo()
                event.accept()
                return
            if event.key() == Qt.Key.Key_Y:
                self.redo()
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
        super().keyPressEvent(event)
