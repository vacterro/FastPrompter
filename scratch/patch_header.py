import os

filepath = 'src/fastprompter/main.py'
with open(filepath, 'r', encoding='utf-8') as f:
    text = f.read()

old_logic = """        plain = QTextCharFormat()
        cursor.movePosition(QTextCursor.MoveOperation.EndOfBlock)
        cursor.setCharFormat(plain)
        nxt = cursor.block().next()
        if not nxt.isValid() or nxt.text().strip():
            cursor.insertText("\\n\\n\\u2022 ", plain)
        else:
            nxt2 = nxt.next()
            if not nxt2.isValid():
                cursor.setPosition(nxt.position())
                cursor.movePosition(QTextCursor.MoveOperation.EndOfBlock)
                cursor.insertText("\\n\\u2022 ", plain)
            else:
                cursor.setPosition(nxt2.position())
                cursor.movePosition(QTextCursor.MoveOperation.EndOfBlock)
                if not nxt2.text().strip():
                    cursor.insertText("\\u2022 ", plain)"""

new_logic = """        plain = QTextCharFormat()
        cursor.movePosition(QTextCursor.MoveOperation.EndOfBlock)
        cursor.setCharFormat(plain)
        nxt = cursor.block().next()
        
        if nxt.isValid() and nxt.text().strip() == "---":
            # Divider is already there, skip over it
            cursor.setPosition(nxt.position())
            cursor.movePosition(QTextCursor.MoveOperation.EndOfBlock)
            nxt2 = nxt.next()
            if not nxt2.isValid() or nxt2.text().strip():
                cursor.insertText("\\n\\n\\u2022 ", plain)
            else:
                cursor.setPosition(nxt2.position())
                cursor.movePosition(QTextCursor.MoveOperation.EndOfBlock)
                if not nxt2.text().strip():
                    cursor.insertText("\\u2022 ", plain)
        else:
            if not nxt.isValid() or nxt.text().strip():
                cursor.insertText("\\n---\\n\\n\\u2022 ", plain)
            else:
                # nxt is an empty line
                cursor.setPosition(nxt.position())
                cursor.movePosition(QTextCursor.MoveOperation.EndOfBlock)
                # Does the next line after the empty line have text?
                nxt2 = nxt.next()
                if not nxt2.isValid() or nxt2.text().strip():
                    cursor.insertText("---\\n\\n\\u2022 ", plain)
                else:
                    # Replace the empty line with divider, then use the next empty line
                    cursor.insertText("---\\n\\u2022 ", plain)"""

if old_logic in text:
    text = text.replace(old_logic, new_logic)
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(text)
    print("Patched header logic successfully.")
else:
    print("WARNING: Could not find old_logic in main.py!")
