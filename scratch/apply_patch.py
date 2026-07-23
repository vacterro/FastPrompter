import os

filepath = 'src/fastprompter/ui/formatting_mixin.py'
with open(filepath, 'r', encoding='utf-8') as f:
    text = f.read()

lines = text.split('\n')
start_idx = -1
for i, line in enumerate(lines):
    if 'def divider_counts(self)' in line:
        start_idx = i
        break

end_idx = -1
for i in range(start_idx, len(lines)):
    if 'def insert_old_add_line(self)' in line:
        end_idx = i
        break

new_block = """    def divider_counts(self):
        \"\"\"User-configured blank-line counts around a --- divider.
        Single source of truth for every divider entry point (toolbar,
        Ctrl+W, Enter on a bare --- line).\"\"\"
        try:
            before = max(0, min(6, int(self.data.get("divider_lines_before", 2))))
        except (TypeError, ValueError):
            before = 2
        try:
            after = max(1, min(6, int(self.data.get("divider_lines_after", 3))))
        except (TypeError, ValueError):
            after = 3
        return before, after

    def insert_add_line(self):
        \"\"\"Push the text down and land on a fresh bullet, ready to type.

        Detects if there is already a `---` line above or below to avoid duplicating them.
        \"\"\"
        cursor = self.text_area.textCursor()
        cursor.beginEditBlock()

        has_top = False
        c = self.text_area.textCursor()
        c.setPosition(cursor.position())
        while c.movePosition(QTextCursor.MoveOperation.PreviousBlock):
            txt = c.block().text().strip()
            if txt == "---":
                has_top = True
                break
            elif txt:
                break

        has_bottom = False
        c = self.text_area.textCursor()
        c.setPosition(cursor.position())
        while c.movePosition(QTextCursor.MoveOperation.NextBlock):
            txt = c.block().text().strip()
            if txt == "---":
                has_bottom = True
                break
            elif txt:
                break

        cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
        start = cursor.position()

        text_to_insert = ""
        offset = 0
        if not has_top:
            text_to_insert += "---\\n\\n"
            offset += 5

        text_to_insert += "\\u2022 "
        offset += 2

        if not has_bottom:
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
