import os

filepath = 'src/fastprompter/ui/formatting_mixin.py'
with open(filepath, 'r', encoding='utf-8') as f:
    text = f.read()

# 1. Fix clear_formatting()
# We will replace it with the optimized version that doesn't use _set_plain_text_clean
old_clear = """    def clear_formatting(self):
        \"\"\"Reset text formatting to base font with plain style.\"\"\"
        self.sound_manager.play(\"clear\")
        cursor = self.text_area.textCursor()

        clean_format = QTextCharFormat()
        clean_format.setFontStyleStrategy(QFont.StyleStrategy.NoAntialias | QFont.StyleStrategy.NoSubpixelAntialias)
        try:
            base_size = self._font_size
        except Exception:
            base_size = 11
        font_name = self._font_family
        try:
            scale = self._ui_scale
        except Exception:
            scale = 1.0
        font_size = max(8, int(round(base_size * scale)))
        font = QFont(font_name, font_size)
        font.setStyleStrategy(
            QFont.StyleStrategy(
                int(QFont.StyleStrategy.NoAntialias.value)
                | int(QFont.StyleStrategy.NoSubpixelAntialias.value)
            )
        )
        clean_format.setFont(font)
        clean_format.setFontWeight(QFont.Weight.Normal)
        clean_format.setFontItalic(False)
        clean_format.setFontUnderline(False)
        clean_format.setFontStrikeOut(False)

        self.text_area.blockSignals(True)
        cursor.beginEditBlock()  # balance the endEditBlock() in finally
        try:
            if cursor.hasSelection():
                raw_text = cursor.selectedText().replace(\"\\u2029\", \"\\n\")
                cursor.insertText(raw_text, clean_format)
            else:
                raw_text = self.text_area.toPlainText()
                self._set_plain_text_clean(self.text_area, raw_text)
                cursor = self.text_area.textCursor()
                cursor.select(QTextCursor.SelectionType.Document)
                cursor.setCharFormat(clean_format)
                cursor.clearSelection()
                self.text_area.setTextCursor(cursor)
        finally:
            cursor.endEditBlock()
            self.text_area.blockSignals(False)

        self.apply_font()
        self.mark_dirty()
        self.cache_current_text()"""

new_clear = """    def clear_formatting(self):
        \"\"\"Reset text formatting to base font with plain style.\"\"\"
        self.sound_manager.play(\"clear\")
        cursor = self.text_area.textCursor()

        clean_format = QTextCharFormat()
        clean_format.setFontStyleStrategy(QFont.StyleStrategy.NoAntialias | QFont.StyleStrategy.NoSubpixelAntialias)
        try:
            base_size = self._font_size
        except Exception:
            base_size = 11
        font_name = self._font_family
        try:
            scale = self._ui_scale
        except Exception:
            scale = 1.0
        font_size = max(8, int(round(base_size * scale)))
        font = QFont(font_name, font_size)
        font.setStyleStrategy(
            QFont.StyleStrategy(
                int(QFont.StyleStrategy.NoAntialias.value)
                | int(QFont.StyleStrategy.NoSubpixelAntialias.value)
            )
        )
        clean_format.setFont(font)
        clean_format.setFontWeight(QFont.Weight.Normal)
        clean_format.setFontItalic(False)
        clean_format.setFontUnderline(False)
        clean_format.setFontStrikeOut(False)

        cursor.beginEditBlock()
        try:
            if not cursor.hasSelection():
                cursor.select(QTextCursor.SelectionType.Document)
            cursor.setCharFormat(clean_format)
            
            # Reset block format (alignment) to default
            block_format = QTextBlockFormat()
            cursor.setBlockFormat(block_format)
            
            if not cursor.hasSelection():
                cursor.clearSelection()
        finally:
            cursor.endEditBlock()

        self.apply_font()
        self.mark_dirty()"""

if old_clear in text:
    text = text.replace(old_clear, new_clear)
else:
    print("WARNING: old_clear not found!")


# 2. Fix insert_add_line() to handle being at the end of a block
old_insert = """        cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
        start = cursor.position()"""

new_insert = """        # If we are at the end of a non-empty block, we should insert AFTER this block,
        # otherwise we insert BEFORE it.
        # But wait, the previous block logic already searched from the CURRENT block.
        # So we should just stay where we are if we are at the end, and let it insert there!
        if cursor.position() == cursor.block().position() + cursor.block().length() - 1 and cursor.block().text().strip():
            # We are at the end of a non-empty block (e.g. just pasted an image or text)
            # Insert a newline first to move to the next block cleanly before inserting
            cursor.insertText("\\n")
        else:
            cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
        start = cursor.position()"""

if old_insert in text:
    text = text.replace(old_insert, new_insert)
else:
    print("WARNING: old_insert not found!")

with open(filepath, 'w', encoding='utf-8') as f:
    f.write(text)
print('Patched formatting_mixin.py')
