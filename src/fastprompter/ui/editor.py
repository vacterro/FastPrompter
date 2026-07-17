import os
import re

from PyQt6 import sip
from PyQt6.QtCore import QPoint, QRect, QRectF, QSize, Qt, QTimer, QUrl
from PyQt6.QtGui import (
    QColor,
    QDesktopServices,
    QFont,
    QPainter,
    QPainterPath,
    QTextCursor,
)
from PyQt6.QtWidgets import QApplication, QTextEdit, QWidget

# Matches every stamp shape Ctrl+E ever wrote: "17.07 - 04:19",
# "17 Jul - 04:19", optional seconds, optional day-part word prefix.
# The refresh glyph lives on this regex — a stamp format added in
# main.py MUST be reflected here or the glyph silently disappears.
TS_STAMP_LINE_RE = re.compile(
    r"(?:Morning |Day |Evening |Night )?"
    r"(?:\d{2}\.\d{2}|\d{1,2} [A-Za-z]{3}) - \d{2}:\d{2}(?::\d{2})?"
)


def _draw_horizontal_rule(painter, hr_color, y_pos, width):
    """Draw a horizontal rule line at the given y position."""
    margin = 4
    painter.setPen(QColor(hr_color))
    painter.drawLine(margin, y_pos, width - margin, y_pos)
    painter.setPen(QColor(0, 0, 0, 30))
    painter.drawLine(margin, y_pos + 2, width - margin, y_pos + 2)


class LineNumberArea(QWidget):
    def __init__(self, editor):
        super().__init__(editor)
        self.editor = editor
        self.setMouseTracking(True)
        self.hover_y = -1

    def sizeHint(self):
        return QSize(self.editor.line_number_area_width(), 0)

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)

    def paintEvent(self, event):
        self.editor.line_number_area_paint_event(event)

    def mousePressEvent(self, event):
        self.editor.line_number_area_mouse_press_event(event)

    def mouseMoveEvent(self, event):
        self.hover_y = event.pos().y()
        self.update()
        super().mouseMoveEvent(event)

    def leaveEvent(self, event):
        self.hover_y = -1
        self.update()
        super().leaveEvent(event)


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
        self.textChanged.connect(self._refresh_checkbox_flag)
        self.textChanged.connect(self.line_number_area.update)
        self.cursorPositionChanged.connect(self.line_number_area.update)
        self._last_hover_pos = QPoint(-10000, -10000)
        self._doc_has_checkbox = False
        self._doc_has_code = False
        QTimer.singleShot(0, self._refresh_checkbox_flag)

    def _first_visible_block(self):
        doc = self.document()
        if not doc or sip.isdeleted(doc):
            return None
        cursor = self.cursorForPosition(QPoint(0, 0))
        if cursor.isNull():
            return None
        blk = cursor.block()
        return blk if blk.isValid() else None

    def _refresh_checkbox_flag(self):
        doc = self.document()
        if doc and not sip.isdeleted(doc):
            # Full scan up to paintEvent threshold (2000 blocks) to avoid blind spot.
            # For very large docs (>2000 blocks), limit scan to first 200 blocks
            # since paintEvent skips checkbox rendering beyond 2000 anyway.
            scan_limit = doc.blockCount()
            if scan_limit > 2000:
                # Won't render checkboxes beyond 2000 blocks, so skip deep scan
                scan_limit = 200
            has_cb = False
            has_code = False
            for i in range(scan_limit):
                txt = doc.findBlockByNumber(i).text()
                if not has_cb and "[" in txt:
                    has_cb = True
                if not has_code and txt.lstrip().startswith("```"):
                    has_code = True
                if has_cb and has_code:
                    break
            self._doc_has_checkbox = has_cb
            if has_code != self._doc_has_code:
                self._doc_has_code = has_code
                # gutter appears/disappears with the code blocks
                self.update_line_number_area_width()

    def _gutter_active(self):
        """Line numbers show when the user turned them on OR the document
        contains fenced code blocks (auto-numbering for code)."""
        if not hasattr(self, 'main_win'):
            return False
        if self.main_win.data.get("show_line_numbers", "False") == "True":
            return True
        return self._doc_has_code

    def set_active_document(self, doc):
        hl = getattr(self.main_win, 'highlighter', None)
        if hl and not sip.isdeleted(hl) and hl.document() != doc:
            hl.setDocument(None)
        cur_doc = self.document()
        if cur_doc and not sip.isdeleted(cur_doc):
            try:
                cur_doc.documentLayout().documentSizeChanged.disconnect(self.update_line_number_area_width)
            except Exception:
                pass
        self.setDocument(doc)
        self.document().setUndoRedoEnabled(True)
        self.document().documentLayout().documentSizeChanged.connect(self.update_line_number_area_width)
        self.update_line_number_area_width()
        font = self.font()
        font.setStyleStrategy(QFont.StyleStrategy.NoAntialias | QFont.StyleStrategy.NoSubpixelAntialias)
        self.document().setDefaultFont(font)
        if hl and not sip.isdeleted(hl) and hl.document() != doc:
            hl.setDocument(doc)
        self._refresh_checkbox_flag()

    def line_number_area_width(self):
        if not self._gutter_active():
            return 0
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
        if not self._gutter_active():
            return
        doc = self.document()
        if not doc or sip.isdeleted(doc):
            return
        block_count = doc.blockCount()
        if block_count > 2000:
            return
        painter = QPainter(self.line_number_area)
        try:
            painter.setFont(self.font())
            theme_name = self.main_win.data.get("theme", "Default")
            bg = self.palette().window().color()
            if theme_name in ("Default",) and bg.lightness() > 128:
                bg = QColor("#e0e0e0")
            elif bg.lightness() < 30:
                bg = QColor("#1e1e1e")
            painter.fillRect(event.rect(), bg)

            first = self._first_visible_block()
            if not first:
                return
            first_number = first.blockNumber()
            last_visible = min(block_count, first_number + 200)
            show_all = self.main_win.data.get("show_line_numbers", "False") == "True"
            
            for block_number in range(first_number, last_visible):
                block = doc.findBlockByNumber(block_number)
                if not block.isValid():
                    break
                if not block.isVisible():  # folded away
                    continue
                cursor = QTextCursor(block)
                rect = self.cursorRect(cursor)
                
                is_code = bool(max(0, block.userState()) & (1 << 8))
                
                if show_all or is_code:
                    number = str(block_number + 1)
                    painter.setPen(QColor("#808080"))
                    painter.drawText(0, int(rect.top()), self.line_number_area.width() - 4,
                                     self.fontMetrics().height(), Qt.AlignmentFlag.AlignRight, number)
                                     
                mark = max(0, block.userState()) & 0xFF
                is_hovered = getattr(self.line_number_area, "hover_y", -1) != -1 and rect.top() <= self.line_number_area.hover_y <= rect.bottom()
                
                if mark == 1 or (mark == 0 and is_hovered):
                    painter.setPen(QColor("#a8cc8c") if mark == 1 else QColor(168, 204, 140, 80))
                    # draw ✅ justified to the left
                    painter.drawText(2, int(rect.top()), self.line_number_area.width(),
                                     self.fontMetrics().height(), Qt.AlignmentFlag.AlignLeft, "✅")
        finally:
            painter.end()

    def line_number_area_mouse_press_event(self, event):
        doc = self.document()
        if doc.blockCount() > 2000:
            return
        block = doc.begin()
        while block.isValid():
            cursor = QTextCursor(block)
            rect = self.cursorRect(cursor)
            block_height = doc.documentLayout().blockBoundingRect(block).height()
            if rect.top() <= event.pos().y() <= rect.top() + block_height:
                state = max(0, block.userState())
                mark = state & 0xFF
                new_mark = 1 if mark == 0 else 0
                block.setUserState((state & ~0xFF) | new_mark)
                self.line_number_area.update()
                break
            block = block.next()

    def _ts_glyph_rect(self, block):
        """Rect of the inline timestamp-refresh glyph for a stamped line."""
        if not TS_STAMP_LINE_RE.search(block.text()):
            return None
        cur = QTextCursor(block)
        cur.movePosition(QTextCursor.MoveOperation.EndOfBlock)
        if block.length() > 1:
            cur.movePosition(QTextCursor.MoveOperation.Left)
        r = self.cursorRect(cur)
        size = max(16, r.height())
        return QRect(r.right() + 8, r.top() + (r.height() - size) // 2, size + 2, size)

    def _ts_glyph_block_at(self, pos):
        """Return the block whose refresh glyph contains pos, else None."""
        block = self._first_visible_block()
        vp_h = self.viewport().height()
        while block is not None and block.isValid():
            if not block.isVisible():
                block = block.next()
                continue
            r = self.cursorRect(QTextCursor(block))
            if r.top() > vp_h:
                break
            g = self._ts_glyph_rect(block)
            if g is not None and g.contains(pos):
                return block
            block = block.next()
        return None

    def _fence_is_opener(self, block):
        """True when this ``` line OPENS a code block (O(1) lookup via highlighter state)."""
        if not block.text().strip().startswith("```"):
            return False
        prev = block.previous()
        if not prev.isValid():
            return True
            
        ustate = prev.userState()
        if ustate != -1:
            return not (ustate & 256) # CODE_BIT is 1 << 8
            
        # Fallback to O(N) if highlighter hasn't parsed the block yet (e.g. in tests)
        opens = True
        b = self.document().firstBlock()
        while b.isValid() and b.blockNumber() < block.blockNumber():
            if b.text().strip().startswith("```"):
                opens = not opens
            b = b.next()
        return opens

    # ---- folding (code fences + markdown headers) -------------------------

    FOLD_BIT = 1 << 9

    @staticmethod
    def _header_level(text):
        """1-6 for '# ...' .. '###### ...' lines, else 0."""
        stripped = text.lstrip()
        n = 0
        while n < len(stripped) and stripped[n] == "#":
            n += 1
        return n if 0 < n <= 6 and stripped[n:n + 1] == " " else 0

    def _is_fold_anchor(self, block):
        text = block.text()
        if self._header_level(text):
            return True
        return text.strip().startswith("```") and self._fence_is_opener(block)

    def _fold_range(self, block):
        """Blocks hidden when this anchor folds: (first, last) or None."""
        text = block.text()
        lvl = self._header_level(text)
        first = block.next()
        if not first.isValid():
            return None
        if lvl:
            last = None
            b = first
            while b.isValid():
                other = self._header_level(b.text())
                if other and other <= lvl:
                    break
                last = b
                b = b.next()
            return (first, last) if last is not None else None
        # fence opener: hide through the closing fence
        b = first
        last = None
        while b.isValid():
            last = b
            if b.text().strip().startswith("```"):
                break
            b = b.next()
        return (first, last) if last is not None else None

    def _fold_rect(self, block):
        """Rect of the fold toggle box on an anchor line."""
        if block.text().strip().startswith("```"):
            c = self._code_copy_rect(block)
            return QRect(c.right() + 6, c.top(), c.width(), c.height())
        ts = self._ts_glyph_rect(block)
        if ts is not None:
            size = ts.height()
            return QRect(ts.right() + 6, ts.top(), size, size)
        cur = QTextCursor(block)
        cur.movePosition(QTextCursor.MoveOperation.EndOfBlock)
        r = self.cursorRect(cur)
        size = max(14, r.height() - 2)
        return QRect(r.right() + 6, r.top() + (r.height() - size) // 2, size, size)

    def _fold_block_at(self, pos):
        if self.document().blockCount() > 2000:
            return None
        block = self._first_visible_block()
        vp_h = self.viewport().height()
        while block is not None and block.isValid():
            if block.isVisible():
                r = self.cursorRect(QTextCursor(block))
                if r.top() > vp_h:
                    break
                if self._is_fold_anchor(block) and self._fold_rect(block).contains(pos):
                    return block
            block = block.next()
        return None

    def toggle_fold(self, anchor):
        """Collapse/expand the region under a header or code fence."""
        rng = self._fold_range(anchor)
        if rng is None:
            return
        first, last = rng
        state = max(0, anchor.userState())
        collapse = not (state & self.FOLD_BIT)
        b = first
        while b.isValid():
            b.setVisible(not collapse)
            if b.blockNumber() >= last.blockNumber():
                break
            b = b.next()
        anchor.setUserState(state | self.FOLD_BIT if collapse else state & ~self.FOLD_BIT)
        doc = self.document()
        doc.markContentsDirty(anchor.position(),
                              last.position() + last.length() - anchor.position())
        self.viewport().update()
        if hasattr(self, "line_number_area"):
            self.line_number_area.update()

    def unfold_all(self):
        """Safety hatch: show every block and clear all fold bits."""
        doc = self.document()
        b = doc.firstBlock()
        changed = False
        while b.isValid():
            if not b.isVisible():
                b.setVisible(True)
                changed = True
            state = max(0, b.userState())
            if state & self.FOLD_BIT:
                b.setUserState(state & ~self.FOLD_BIT)
            b = b.next()
        if changed:
            doc.markContentsDirty(0, doc.characterCount())
            self.viewport().update()
            if hasattr(self, "line_number_area"):
                self.line_number_area.update()

    def _code_copy_rect(self, block):
        """Rect of the inline copy button on an opening fence line."""
        cur = QTextCursor(block)
        cur.movePosition(QTextCursor.MoveOperation.EndOfBlock)
        r = self.cursorRect(cur)
        size = max(14, r.height() - 2)
        return QRect(r.right() + 6, r.top() + (r.height() - size) // 2, size, size)

    def _code_copy_block_at(self, pos):
        """Return the opening fence block whose copy button contains pos."""
        if self.document().blockCount() > 2000:
            return None
        block = self._first_visible_block()
        vp_h = self.viewport().height()
        while block is not None and block.isValid():
            if not block.isVisible():
                block = block.next()
                continue
            r = self.cursorRect(QTextCursor(block))
            if r.top() > vp_h:
                break
            if block.text().strip().startswith("```") and self._fence_is_opener(block):
                if self._code_copy_rect(block).contains(pos):
                    return block
            block = block.next()
        return None

    def copy_code_block(self, opener_block):
        """Copy the fenced block's content (between the fences) to clipboard."""
        lines = []
        b = opener_block.next()
        while b.isValid():
            if b.text().strip().startswith("```"):
                break
            lines.append(b.text())
            b = b.next()
        QApplication.clipboard().setText("\n".join(lines))
        try:
            self.main_win.play_tick_sound()
        except Exception:
            pass

    def _checkbox_at_pos(self, pos):
        try:
            if not self._doc_has_checkbox:
                return None
            doc = self.document()
            if not doc:
                return None
            vp_h = self.viewport().height()
            block = self._first_visible_block()
            if not block:
                return None
            while block.isValid():
                r = self.cursorRect(QTextCursor(block))
                if r.top() > vp_h:
                    break
                if r.bottom() >= 0:
                    text = block.text()
                    stripped = text.lstrip()
                    indent = len(text) - len(stripped)
                    if stripped.startswith("[ ] ") or stripped.startswith("[x] ") or stripped.startswith("[X] "):
                        cursor = QTextCursor(block)
                        cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
                        cursor.movePosition(QTextCursor.MoveOperation.Right, QTextCursor.MoveMode.MoveAnchor, indent)
                        r_start = self.cursorRect(cursor)
                        cursor.movePosition(QTextCursor.MoveOperation.Right, QTextCursor.MoveMode.MoveAnchor, 4)
                        r_end = self.cursorRect(cursor)
                        b_w = int(r_end.x() - r_start.x())
                        if QRect(int(r_start.x()), int(r_start.top()), b_w, int(r_start.height())).contains(pos):
                            return block
                block = block.next()
        except Exception as e:
            print("checkbox hit test error:", e)
        return None

    def _toggle_single_line(self, block):
        try:
            text = block.text()
            stripped = text.lstrip()
            indent = text[:len(text) - len(stripped)]
            if stripped.startswith("[x] ") or stripped.startswith("[X] "):
                new_text = f"{indent}[ ] {stripped[4:]}"
            elif stripped.startswith("[ ] "):
                new_text = f"{indent}[x] {stripped[4:]}"
            else:
                return
            bcursor = QTextCursor(block)
            bcursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
            bcursor.movePosition(QTextCursor.MoveOperation.EndOfBlock, QTextCursor.MoveMode.KeepAnchor)
            bcursor.insertText(new_text)
        except Exception as e:
            print("checkbox toggle error:", e)

    def mousePressEvent(self, event):
        if sip.isdeleted(self):
            return
        try:
            if event.button() == Qt.MouseButton.LeftButton:
                fold_block = self._fold_block_at(event.pos())
                if fold_block is not None:
                    self._fold_pressed_block = fold_block.blockNumber()
                    self.viewport().update()
                    event.accept()
                    return
                code_block = self._code_copy_block_at(event.pos())
                if code_block is not None:
                    self._copy_pressed_block = code_block.blockNumber()
                    self.viewport().update()
                    event.accept()
                    return
                ts_block = self._ts_glyph_block_at(event.pos())
                if ts_block is not None:
                    # show the pushed state; the action fires on release
                    self._ts_pressed_block = ts_block.blockNumber()
                    self.viewport().update()
                    event.accept()
                    return
                cb_block = self._checkbox_at_pos(event.pos())
                if cb_block:
                    self._toggle_single_line(cb_block)
                    event.accept()
                    return
                # Handle anchor/link clicks (replaces removed anchorClicked signal in Qt 6.8+)
                cursor = self.cursorForPosition(event.pos())
                if cursor.charFormat().isAnchor():
                    url = QUrl(cursor.charFormat().anchorHref())
                    if url.isValid():
                        QDesktopServices.openUrl(url)
                        event.accept()
                        return
        except Exception as e:
            print("checkbox mouse error:", e)
        if event.button() == Qt.MouseButton.LeftButton and event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            super().mousePressEvent(event)
            cursor = self.textCursor()
            cursor.beginEditBlock()
            cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
            cursor.movePosition(QTextCursor.MoveOperation.EndOfBlock, QTextCursor.MoveMode.KeepAnchor)
            line = cursor.selectedText()
            if re.match(r'^\s*\u2022\s*', line):
                new_line = re.sub(r'^(\s*)\u2022\s*', r'\1- ', line)
            elif re.match(r'^\s*-\s+', line):
                new_line = re.sub(r'^(\s*)-\s+', r'\1\u2022 ', line)
            else:
                cursor.endEditBlock()
                return
            cursor.insertText(new_line)
            cursor.endEditBlock()
            event.accept()
            return
        if event.button() == Qt.MouseButton.MiddleButton:
            self.main_win.clear_temp(self.main_win.active_temp_slot,
                                     is_archive=getattr(self.main_win, 'active_is_archive', False))
            event.accept()
            return
        if event.button() == Qt.MouseButton.RightButton:
            self._right_drag_start = event.globalPosition().toPoint()
            self._dragged = False
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        pressed_fold = getattr(self, "_fold_pressed_block", None)
        if pressed_fold is not None and event.button() == Qt.MouseButton.LeftButton:
            self._fold_pressed_block = None
            self.viewport().update()
            block = self._fold_block_at(event.pos())
            if block is not None and block.blockNumber() == pressed_fold:
                self.toggle_fold(block)
            event.accept()
            return
        pressed_copy = getattr(self, "_copy_pressed_block", None)
        if pressed_copy is not None and event.button() == Qt.MouseButton.LeftButton:
            self._copy_pressed_block = None
            self.viewport().update()
            block = self._code_copy_block_at(event.pos())
            if block is not None and block.blockNumber() == pressed_copy:
                self.copy_code_block(block)
            event.accept()
            return
        pressed = getattr(self, "_ts_pressed_block", None)
        if pressed is not None and event.button() == Qt.MouseButton.LeftButton:
            self._ts_pressed_block = None
            self.viewport().update()
            block = self._ts_glyph_block_at(event.pos())
            if block is not None and block.blockNumber() == pressed:
                self.main_win.refresh_timestamp_in_block(block)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def mouseMoveEvent(self, event):
        if sip.isdeleted(self):
            return
        try:
            if not event.buttons():
                p = event.pos()
                if (p - self._last_hover_pos).manhattanLength() > 3:
                    self._last_hover_pos = p
                    over_cb = self._checkbox_at_pos(p)
                    over_ts = self._ts_glyph_block_at(p) is not None
                    over_fold = self._fold_block_at(p) is not None
                    over_copy = self._code_copy_block_at(p) is not None
                    is_link = bool(self.anchorAt(p))
                    target = Qt.CursorShape.PointingHandCursor if (over_cb or over_ts or over_fold or over_copy or is_link) else Qt.CursorShape.IBeamCursor
                    cur = self.viewport().cursor()
                    if cur.shape() != target:
                        self.viewport().setCursor(target)
        except Exception as e:
            print("checkbox cursor error:", e)
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
        menu = self.createStandardContextMenu()
        menu.addSeparator()
        menu.addAction("Expand All Folds", self.unfold_all)
        menu.exec(event.globalPos())

    def _ask_text_drop_choice(self, name):
        """Dropped a text-based file: insert as text, or store as a file?
        Returns 'text', 'file' or 'cancel'."""
        from PyQt6.QtWidgets import QMessageBox
        box = QMessageBox(self.main_win)
        box.setWindowTitle("Add dropped file")
        box.setText(f"How should '{name}' be added?")
        btn_text = box.addButton("Insert as Text", QMessageBox.ButtonRole.AcceptRole)
        btn_file = box.addButton("Add to Silo Files 📁", QMessageBox.ButtonRole.ActionRole)
        box.addButton(QMessageBox.StandardButton.Cancel)
        box.setDefaultButton(btn_text)
        box.exec()
        clicked = box.clickedButton()
        if clicked is btn_text:
            return "text"
        if clicked is btn_file:
            return "file"
        return "cancel"

    def insertFromMimeData(self, source):
        if source.hasUrls():
            for url in source.urls():
                if url.isLocalFile():
                    path = url.toLocalFile()
                    ext = os.path.splitext(path)[1].lower()
                    text_extensions = {
                        ".txt", ".md", ".py", ".js", ".ts", ".jsx", ".tsx", ".html", ".css",
                        ".json", ".xml", ".yaml", ".yml", ".csv", ".ini", ".cfg", ".conf",
                        ".log", ".bat", ".sh", ".ps1", ".sql", ".rb", ".php", ".java",
                        ".c", ".cpp", ".h", ".hpp", ".cs", ".go", ".rs", ".swift",
                        ".kt", ".scala", ".pl", ".lua", ".r", ".m", ".mm", ".tex",
                        ".rst", ".toml", ".lock", ".env", ".gitignore", ".editorconfig",
                        ".properties", ".gradle", ".sln", ".csproj", ".vcxproj"
                    }
                    if ext in text_extensions or not ext:
                        choice = self._ask_text_drop_choice(os.path.basename(path))
                        if choice == "file":
                            self.main_win.add_files_to_active_silo([path])
                        elif choice == "text":
                            try:
                                with open(path, encoding="utf-8", errors="replace") as f:
                                    content = f.read()
                                self.insertPlainText(content)
                            except Exception:
                                import traceback
                                traceback.print_exc()
                    else:
                        # binary files go into the silo's file container
                        self.main_win.add_files_to_active_silo([path])
            return
        if source.hasText():
            self.insertPlainText(source.text())

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

        if mods == Qt.KeyboardModifier.ControlModifier and event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._toggle_checkboxes()
            event.accept()
            return

        if mods == Qt.KeyboardModifier.ControlModifier and event.key() == Qt.Key.Key_E:
            # Delegate to main window's combined header+timestamp method
            self.main_win.apply_header_timestamp()
            event.accept()
            return

        if mods == Qt.KeyboardModifier.ControlModifier and event.key() in (
            Qt.Key.Key_B, Qt.Key.Key_I, Qt.Key.Key_U, Qt.Key.Key_T
        ):
            # Markdown marker toggles — must run before QTextEdit's built-in
            # rich-text shortcuts, whose formatting is lost on save
            mw = self.main_win
            key = event.key()
            if key == Qt.Key.Key_B:
                mw.apply_bold_smart()
            else:
                mw.apply_format({Qt.Key.Key_I: "italic", Qt.Key.Key_U: "underline",
                                 Qt.Key.Key_T: "strike"}[key])
            event.accept()
            return

        if mods == Qt.KeyboardModifier.ControlModifier and event.key() in (Qt.Key.Key_Z, Qt.Key.Key_Y):
            # Ctrl+Z: route to the data-undo stack (silo clear/delete/move)
            # when appropriate; _smart_undo decides.
            if event.key() == Qt.Key.Key_Z and hasattr(self.main_win, "_smart_undo"):
                self.main_win._smart_undo()
                event.accept()
                return
            super().keyPressEvent(event)
            return

        if mods & Qt.KeyboardModifier.ControlModifier and event.key() in (Qt.Key.Key_Home, Qt.Key.Key_End):
            cursor = self.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.Start if event.key() == Qt.Key.Key_Home else QTextCursor.MoveOperation.End)
            self.setTextCursor(cursor)
            self.ensureCursorVisible()
            event.accept()
            return

        if mods & Qt.KeyboardModifier.ControlModifier and event.key() in (
                Qt.Key.Key_Plus, Qt.Key.Key_Equal, Qt.Key.Key_Minus, Qt.Key.Key_Underscore):
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
                QTimer.singleShot(10, lambda: not sip.isdeleted(self) and not sip.isdeleted(
                    self.main_win) and self.main_win.hide_and_save())
            return

        if event.key() == Qt.Key.Key_Backspace and (mods & Qt.KeyboardModifier.AltModifier):
            try:
                cursor = self.textCursor()
                if cursor.hasSelection():
                    cursor.removeSelectedText()
                else:
                    cursor.movePosition(QTextCursor.MoveOperation.PreviousWord, QTextCursor.MoveMode.KeepAnchor)
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
                    stripped = text_before.lstrip()
                    if stripped in ("-", "*", "+"):
                        cursor.movePosition(QTextCursor.MoveOperation.Left,
                                            QTextCursor.MoveMode.KeepAnchor, len(text_before))
                        cursor.insertText(text_before[:len(text_before) - len(stripped)] + "\u2022 ")
                        self.setTextCursor(cursor)
                        event.accept()
                        return

        # Auto-bullet continuation: Enter on a bullet line starts the next
        # line with the same bullet (blank line between them if
        # bullet_double_line is on); Enter on an empty bullet removes it.
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and mods == Qt.KeyboardModifier.NoModifier:
            cursor = self.textCursor()
            if not cursor.hasSelection():
                block_text = cursor.block().text()
                stripped = block_text.lstrip()
                
                if stripped == "---":
                    before, after = self.main_win.divider_counts()
                    cursor.beginEditBlock()
                    cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
                    cursor.movePosition(QTextCursor.MoveOperation.EndOfBlock, QTextCursor.MoveMode.KeepAnchor)
                    cursor.insertText("\n" * before + "---" + "\n" * after + "\u2022 ")
                    cursor.endEditBlock()
                    self.setTextCursor(cursor)
                    self.ensureCursorVisible()
                    event.accept()
                    return

                indent = block_text[:len(block_text) - len(stripped)]
                m = re.match(r'^([\u2022\-\*\+])[ \t]+(.*)$', stripped)
                
                # The user requested double line to work independently of the 'auto_bullet' check if toggled,
                # or just ensure double lines append correctly. We will allow auto-continuation if either
                # auto_bullet is True OR bullet_double_line is True.
                wants_auto_bullet = self.main_win.data.get("auto_bullet", "False") == "True"
                double = self.main_win.data.get("bullet_double_line", "False") == "True"
                
                if m and cursor.positionInBlock() >= len(block_text) - len(m.group(2)) and (wants_auto_bullet or double):
                    if m.group(2).strip():
                        sep = "\n\n" if double else "\n"
                        cursor.insertText(sep + indent + m.group(1) + " ")
                        self.setTextCursor(cursor)
                        self.ensureCursorVisible()
                        event.accept()
                        return
                    # Empty bullet: Enter clears the marker instead of continuing
                    cursor.beginEditBlock()
                    cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
                    cursor.movePosition(QTextCursor.MoveOperation.EndOfBlock,
                                        QTextCursor.MoveMode.KeepAnchor)
                    cursor.removeSelectedText()
                    cursor.endEditBlock()
                    self.setTextCursor(cursor)
                    event.accept()
                    return

        try:
            super().keyPressEvent(event)
        except Exception:
            event.accept()
            return

        # Typewriter sound: fires for actual typed symbols (gated by the
        # sound_typewriter toggle inside SoundManager).
        txt = event.text()
        if txt and txt.isprintable() and not (
            mods & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier)
        ):
            try:
                self.main_win.play_sound("type")
            except Exception:
                pass

    def paintEvent(self, event):
        super().paintEvent(event)
        doc = self.document()
        if not doc:
            return
        block_count = doc.blockCount()
        is_large = block_count > 2000
        vp_rect = self.viewport().rect()
        painter = QPainter(self.viewport())
        try:
            # Zebra striping: skip for large docs (>2000 blocks)
            zebra_enabled = not is_large and self.main_win.data.get("zebra_lines", "False") == "True"
            try:
                zebra_alpha = min(90, max(2, int(self.main_win.data.get("zebra_opacity", "32"))))
            except Exception:
                zebra_alpha = 32
            zebra_odd = QColor(self.main_win.data.get("zebra_stripe_color", "#000000"))
            if not zebra_odd.isValid():
                zebra_odd = QColor(0, 0, 0)
            zebra_odd.setAlpha(zebra_alpha)

            # --- visual lines color
            try:
                hr_color = QColor(self.main_win.data.get("zebra_color", "#5a4a2a"))
            except Exception:
                hr_color = QColor("#5a4a2a")
            hr_drawn = set()

            # Checkbox rendering bg
            bg_color = self.viewport().palette().window().color()

            doc_layout = doc.documentLayout()
            y_off = -self.verticalScrollBar().value()
            block = self._first_visible_block()
            if block:
                while block.isValid():
                    if not block.isVisible():  # folded away
                        block = block.next()
                        continue
                    # Full block geometry (covers wrapped lines), viewport coords
                    br = doc_layout.blockBoundingRect(block).translated(0, y_off)
                    r = self.cursorRect(QTextCursor(block))
                    if br.top() > vp_rect.height():
                        break
                    if br.bottom() >= 0:
                        bnum = block.blockNumber()
                        text = block.text()
                        stripped = text.lstrip()

                        # Zebra background
                        if zebra_enabled and bnum % 2 == 1:
                            line_rect = QRectF(0, br.top(), vp_rect.width(), br.height())
                            painter.fillRect(line_rect, zebra_odd)

                        # Inline copy button on opening code fences:
                        # click copies the block's content to the clipboard
                        if not is_large and stripped.startswith("```") and self._fence_is_opener(block):
                            gc = QRectF(self._code_copy_rect(block))
                            pressed_c = getattr(self, "_copy_pressed_block", -1) == bnum
                            painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
                            painter.fillRect(gc, QColor("#1e1e1e"))
                            light = QColor("#3a3a3a")
                            dark = QColor("#0a0a0a")
                            painter.setPen(dark if pressed_c else light)
                            painter.drawLine(gc.topLeft(), gc.topRight())
                            painter.drawLine(gc.topLeft(), gc.bottomLeft())
                            painter.setPen(light if pressed_c else dark)
                            painter.drawLine(gc.bottomLeft(), gc.bottomRight())
                            painter.drawLine(gc.topRight(), gc.bottomRight())
                            painter.setPen(QColor("#D9B340"))
                            gfc = self.font()
                            gfc.setPointSizeF(max(8.0, gfc.pointSizeF() * 0.95))
                            painter.setFont(gfc)
                            tgc = gc.adjusted(2, 2, 2, 2) if pressed_c else gc
                            painter.drawText(tgc, Qt.AlignmentFlag.AlignCenter, "\u2398")
                            painter.setFont(self.font())

                        # Fold toggle box on headers and code fences:
                        # ▾ expanded, ▸ collapsed (hides the section)
                        if not is_large and self._is_fold_anchor(block):
                            fr = QRectF(self._fold_rect(block))
                            collapsed = bool(max(0, block.userState()) & self.FOLD_BIT)
                            pressed_f = getattr(self, "_fold_pressed_block", -1) == bnum
                            painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
                            painter.fillRect(fr, QColor("#1e1e1e"))
                            light = QColor("#3a3a3a")
                            dark = QColor("#0a0a0a")
                            painter.setPen(dark if pressed_f else light)
                            painter.drawLine(fr.topLeft(), fr.topRight())
                            painter.drawLine(fr.topLeft(), fr.bottomLeft())
                            painter.setPen(light if pressed_f else dark)
                            painter.drawLine(fr.bottomLeft(), fr.bottomRight())
                            painter.drawLine(fr.topRight(), fr.bottomRight())
                            painter.setPen(QColor("#D9B340"))
                            ff = self.font()
                            ff.setPointSizeF(max(8.0, ff.pointSizeF() * 0.9))
                            painter.setFont(ff)
                            tf = fr.adjusted(2, 2, 2, 2) if pressed_f else fr
                            painter.drawText(tf, Qt.AlignmentFlag.AlignCenter,
                                             "▸" if collapsed else "▾")
                            painter.setFont(self.font())
                            if collapsed:
                                painter.setPen(QColor("#808080"))
                                painter.drawText(
                                    int(fr.right()) + 6, int(fr.bottom()) - 2, "…")

                        # Inline refresh button after lines ending with a
                        # Ctrl+E timestamp: a small 3D box (pushes when
                        # clicked) that re-stamps the line to now
                        m_ts = TS_STAMP_LINE_RE.search(text)
                        if m_ts:
                            g_rect = self._ts_glyph_rect(block)
                            if g_rect is not None:
                                g = QRectF(g_rect)
                                pressed = getattr(self, "_ts_pressed_block", -1) == bnum
                                painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
                                
                                painter.fillRect(g, QColor("#1e1e1e"))
                                
                                light = QColor("#3a3a3a")
                                dark = QColor("#0a0a0a")
                                top_left = dark if pressed else light
                                bottom_right = light if pressed else dark
                                
                                painter.setPen(top_left)
                                painter.drawLine(g.topLeft(), g.topRight())
                                painter.drawLine(g.topLeft(), g.bottomLeft())
                                
                                painter.setPen(bottom_right)
                                painter.drawLine(g.bottomLeft(), g.bottomRight())
                                painter.drawLine(g.topRight(), g.bottomRight())
                                
                                painter.setPen(QColor("#a0a0a0"))
                                gf = self.font()
                                gf.setPointSizeF(max(8.0, gf.pointSizeF() * 1.1))
                                painter.setFont(gf)
                                tg = g.adjusted(2, 2, 2, 2) if pressed else g
                                painter.drawText(tg, Qt.AlignmentFlag.AlignCenter, "\u27f3")
                                painter.setFont(self.font())

                        # --- horizontal rule visual line (skip for large docs)
                        if not is_large and re.match(r'^[-*_]{3,}$', text.strip()):
                            mid_y = r.top() + r.height() // 2
                            if mid_y not in hr_drawn:
                                hr_drawn.add(mid_y)
                                _draw_horizontal_rule(painter, hr_color, mid_y, vp_rect.width())

                        # Checkbox rendering (skip for large docs, >2000 blocks)
                        if self._doc_has_checkbox and not is_large:
                            indent = len(text) - len(stripped)
                            if stripped.startswith("[ ] "):
                                checked = False
                            elif stripped.startswith("[x] ") or stripped.startswith("[X] "):
                                checked = True
                            else:
                                block = block.next()
                                continue

                            cursor = QTextCursor(block)
                            cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
                            cursor.movePosition(QTextCursor.MoveOperation.Right,
                                                QTextCursor.MoveMode.MoveAnchor, indent)
                            r_start = self.cursorRect(cursor)
                            cursor.movePosition(QTextCursor.MoveOperation.Right,
                                                QTextCursor.MoveMode.MoveAnchor, 4)
                            r_end = self.cursorRect(cursor)
                            bg_left = int(r_start.x())
                            bg_top = int(r_start.top())
                            bg_w = int(r_end.x() - r_start.x())
                            bg_h = int(r_start.height())

                            painter.fillRect(QRectF(bg_left, bg_top, bg_w, bg_h), bg_color)
                            cb_size = int(r_start.height() * 0.75)
                            cy = bg_top + (bg_h - cb_size) / 2
                            cx = bg_left + (bg_w - cb_size) / 2
                            cb_rect = QRectF(cx, cy, cb_size, cb_size)
                            path = QPainterPath()
                            path.addRoundedRect(cb_rect, 2, 2)
                            if checked:
                                painter.fillPath(path, QColor("#5cb85c"))
                                painter.strokePath(path, QColor("#4a9a4a"))
                                painter.setPen(QColor("white"))
                                check_font = self.font()
                                check_font.setPixelSize(max(8, int(cb_size * 0.65)))
                                painter.setFont(check_font)
                                painter.drawText(cb_rect, Qt.AlignmentFlag.AlignCenter, "\u2714")
                            else:
                                painter.fillPath(path, QColor("#333333"))
                                painter.strokePath(path, QColor("#666666"))
                    block = block.next()

        finally:
            painter.end()

    def _toggle_checkboxes(self):
        doc = self.document()
        cursor = self.textCursor()
        has_sel = cursor.hasSelection()
        if has_sel:
            start_block = doc.findBlock(cursor.selectionStart())
            end_block = doc.findBlock(cursor.selectionEnd())
        else:
            start_block = end_block = cursor.block()
        block = start_block
        cursor.beginEditBlock()
        while True:
            text = block.text()
            stripped = text.lstrip()
            if not stripped:
                # empty lines never become checkboxes
                if block == end_block:
                    break
                block = block.next()
                continue
            indent = text[:len(text) - len(stripped)]
            if stripped.startswith("[x] ") or stripped.startswith("[X] "):
                new_text = f"{indent}{stripped[4:]}"
            elif stripped.startswith("[ ] "):
                new_text = f"{indent}[x] {stripped[4:]}"
            else:
                new_text = f"{indent}[ ] {stripped}"
            if new_text != text:
                bcursor = QTextCursor(block)
                bcursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
                bcursor.movePosition(QTextCursor.MoveOperation.EndOfBlock, QTextCursor.MoveMode.KeepAnchor)
                bcursor.insertText(new_text)
            if block == end_block:
                break
            block = block.next()
        cursor.endEditBlock()
