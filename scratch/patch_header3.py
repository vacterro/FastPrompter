import os
import re

filepath = 'src/fastprompter/main.py'
with open(filepath, 'r', encoding='utf-8') as f:
    text = f.read()

pattern = re.compile(r'nxt = cursor\.block\(\)\.next\(\).*?(?=\s*# Center the header block)', re.DOTALL)

new_logic = """nxt = cursor.block().next()
        
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

if pattern.search(text):
    text = pattern.sub(lambda m: new_logic, text)
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(text)
    print("Patched header logic successfully via regex.")
else:
    print("WARNING: Could not find regex pattern in main.py!")
