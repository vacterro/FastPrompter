"""T-694: replace the broken _move_lines body in ui/editor.py.

The shipped version duplicated the dragged lines, ate a neighbouring line and
left blank ones behind (measured: (1,1,3) on one/two/three/four returned
'\\nthree\\nfour\\ntwo' -- 'one' gone). Replaced wholesale rather than patched:
the removal logic was wrong in three separate places.
"""
import io
import re

PATH = r"V:\___VAC\__K\__CODE\_PY\_FastPrompter\src\fastprompter\ui\editor.py"

NEW = '''    def _move_lines(self, start_num, end_num, target_num):
        """Line-blocking drop: move a block of lines to a new position.

        The dragged range lands AFTER the drop line when dragged down and
        BEFORE it when dragged up, which is what the drop indicator draws.
        Rich content (bold, checkboxes, image pills) survives the trip: the
        lines travel as a QTextDocumentFragment, not as plain text.
        """
        if start_num > end_num:
            start_num, end_num = end_num, start_num
        if start_num <= target_num <= end_num:
            return  # target is inside the dragged range

        doc = self.document()
        if not (0 <= start_num and end_num < doc.blockCount() and 0 <= target_num < doc.blockCount()):
            return

        start_block = doc.findBlockByNumber(start_num)
        end_block = doc.findBlockByNumber(end_num)
        if not start_block.isValid() or not end_block.isValid():
            return

        count = end_num - start_num + 1
        last_num = doc.blockCount() - 1

        with edit_block(self.textCursor(), self):
            c = QTextCursor(doc)
            c.setPosition(start_block.position())
            # length() counts the block separator, so -1 lands on end-of-block
            c.setPosition(end_block.position() + end_block.length() - 1,
                          QTextCursor.MoveMode.KeepAnchor)
            fragment = c.selection()

            # Swallow exactly ONE newline with the lines, or the move leaves a
            # blank line where they were. Prefer the one after; at the end of
            # the document there is none, so take the one before instead.
            if end_num < last_num:
                c.setPosition(c.position() + 1, QTextCursor.MoveMode.KeepAnchor)
            elif start_num > 0:
                sel_end = c.position()
                c.setPosition(start_block.position() - 1)
                c.setPosition(sel_end, QTextCursor.MoveMode.KeepAnchor)
            c.removeSelectedText()

            # Blocks after the removed range shifted down by `count`
            new_target = target_num if target_num < start_num else target_num - count
            target_block = doc.findBlockByNumber(new_target)
            if not target_block.isValid():
                target_block = doc.lastBlock()

            ins = QTextCursor(target_block)
            if target_num > end_num:
                ins.movePosition(QTextCursor.MoveOperation.EndOfBlock)
                ins.insertText("\\n")
                ins.insertFragment(fragment)
            else:
                ins.movePosition(QTextCursor.MoveOperation.StartOfBlock)
                ins.insertFragment(fragment)
                ins.insertText("\\n")

'''


def main() -> None:
    with io.open(PATH, encoding="utf-8", newline="") as fh:
        src = fh.read()

    nl = "\r\n" if "\r\n" in src else "\n"
    flat = src.replace("\r\n", "\n")

    m = re.search(r"    def _move_lines\(self.*?(?=\n    def mouseReleaseEvent\()",
                  flat, flags=re.DOTALL)
    if not m:
        raise SystemExit("anchor not found")
    old = m.group(0)
    print("old body lines:", old.count("\n") + 1)
    flat = flat[:m.start()] + NEW.rstrip("\n") + "\n" + flat[m.end():]

    with io.open(PATH, "w", encoding="utf-8", newline="") as fh:
        fh.write(flat.replace("\n", nl) if nl == "\r\n" else flat)
    print("patched, newline:", repr(nl))


if __name__ == "__main__":
    main()
