import os

filepath = 'src/fastprompter/ui/formatting_mixin.py'
with open(filepath, 'r', encoding='utf-8') as f:
    text = f.read()

lines = text.split('\n')
start_idx = -1
for i, line in enumerate(lines):
    if 'def insert_add_line(self):' in line:
        start_idx = i
        break

end_idx = -1
for i in range(start_idx + 1, len(lines)):
    if 'def insert_old_add_line(self):' in lines[i]:
        end_idx = i
        break

new_block = """    def insert_add_line(self):
        \"\"\"Push the text down and land on a fresh bullet, ready to type.

        Detects if there is already a `---` line above or below to avoid duplicating them.
        If placed between two text blocks, it just inserts a divider to split them evenly.
        \"\"\"
        cursor = self.text_area.textCursor()
        cursor.beginEditBlock()

        top_type = "NONE"
        c = self.text_area.textCursor()
        c.setPosition(cursor.position())
        while c.movePosition(QTextCursor.MoveOperation.PreviousBlock):
            txt = c.block().text().strip()
            if txt == "---":
                top_type = "DIVIDER"
                break
            elif txt:
                top_type = "TEXT"
                break

        bottom_type = "NONE"
        c = self.text_area.textCursor()
        c.setPosition(cursor.position())
        while c.movePosition(QTextCursor.MoveOperation.NextBlock):
            txt = c.block().text().strip()
            if txt == "---":
                bottom_type = "DIVIDER"
                break
            elif txt:
                bottom_type = "TEXT"
                break

        cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
        start = cursor.position()

        text_to_insert = ""
        offset = 0
        
        if top_type == "TEXT" and bottom_type == "TEXT":
            text_to_insert = "---\\n\\n"
            offset = 3
        else:
            if top_type != "DIVIDER":
                text_to_insert += "---\\n\\n"
                offset += 5

            text_to_insert += "\\u2022 "
            offset += 2

            if bottom_type != "DIVIDER":
                text_to_insert += "\\n\\n---\\n\\n\\n"
            else:
                text_to_insert += "\\n\\n"

        cursor.insertText(text_to_insert)
        cursor.endEditBlock()

        cursor.setPosition(start + offset)
        self.text_area.setTextCursor(cursor)
        self.text_area.ensureCursorVisible()
        self.text_area.setFocus()
        self.mark_dirty()
"""

lines[start_idx:end_idx] = new_block.split('\n')[:-1]

with open(filepath, 'w', encoding='utf-8') as f:
    f.write('\n'.join(lines))
print('Fixed formatting_mixin.py')
