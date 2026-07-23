from PyQt6.QtWidgets import QApplication, QTextEdit
from PyQt6.QtGui import QTextCursor

app = QApplication([])
t = QTextEdit()
t.setText("Line 1\nLine 2\nLine 3")
c = t.textCursor()
c.movePosition(QTextCursor.MoveOperation.End)

print("Current block:", c.block().text())

c.movePosition(QTextCursor.MoveOperation.PreviousBlock)
print("Previous block:", c.block().text())
