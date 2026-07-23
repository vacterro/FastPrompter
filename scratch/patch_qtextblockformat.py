import os

filepath = 'src/fastprompter/ui/formatting_mixin.py'
with open(filepath, 'r', encoding='utf-8') as f:
    text = f.read()

text = text.replace(
    'from PyQt6.QtGui import QFont, QTextCharFormat, QTextCursor',
    'from PyQt6.QtGui import QFont, QTextBlockFormat, QTextCharFormat, QTextCursor'
)

with open(filepath, 'w', encoding='utf-8') as f:
    f.write(text)

print("Added QTextBlockFormat import to formatting_mixin.py")
