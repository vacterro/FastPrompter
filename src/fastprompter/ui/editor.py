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
    QPen,
    QTextCursor,
)
from PyQt6.QtWidgets import QApplication, QTextEdit, QWidget

from fastprompter.core.logging import logger
from fastprompter.core.translations import tr

# Matches every stamp shape Ctrl+E ever wrote: "17.07 - 04:19",
# "17 Jul - 04:19", optional seconds, optional day-part word prefix.
# The refresh glyph lives on this regex — a stamp format added in
# main.py MUST be reflected here or the glyph silently disappears.
TS_STAMP_LINE_RE = re.compile(
    r"(?:Morning |Day |Evening |Night )?"
    r"(?:\d{2}\.\d{2}|\d{1,2} [A-Za-z]{3}) - \d{2}:\d{2}(?::\d{2})?(?: [AP]M)?"
)

# File types the editor can meaningfully load as plain text
TEXT_EXTENSIONS = {
    ".txt", ".md", ".py", ".js", ".ts", ".jsx", ".tsx", ".html", ".css",
    ".json", ".xml", ".yaml", ".yml", ".csv", ".ini", ".cfg", ".conf",
    ".log", ".bat", ".sh", ".ps1", ".sql", ".rb", ".php", ".java",
    ".c", ".cpp", ".h", ".hpp", ".cs", ".go", ".rs", ".swift",
    ".kt", ".scala", ".pl", ".lua", ".r", ".m", ".mm", ".tex",
    ".rst", ".toml", ".lock", ".env", ".gitignore", ".editorconfig",
    ".properties", ".gradle", ".sln", ".csproj", ".vcxproj",
}


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
        """The line-number gutter follows the user's toggle alone — a reliable
        master on/off. (It used to force itself on whenever the document held
        a code block, which made the # toggle appear dead on code silos.)
        Code auto-numbering is opt-in via the 'code_auto_gutter' setting."""
        if not hasattr(self, 'main_win'):
            return False
        if self.main_win.data.get("show_line_numbers", "False") == "True":
            return True
        if (self.main_win.data.get("code_auto_gutter", "False") == "True"
                and self._doc_has_code):
            return True
        return False

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
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            painter.setFont(self.font())
            theme_name = self.main_win.data.get("theme", "Default")
            bg = self.palette().window().color()
            text_color = QColor("#808080")
            
            if "vintage" in theme_name.lower():
                bg = QColor("#2A1C0A")
                text_color = QColor("#D4B87A")
            elif theme_name in ("Default",) and bg.lightness() > 128:
                bg = QColor("#e0e0e0")
            elif bg.lightness() < 30:
                bg = QColor("#1e1e1e")
            painter.fillRect(event.rect(), bg)

            first = self._first_visible_block()
            if not first:
                return
            first_number = first.blockNumber()
            last_visible = min(block_count, first_number + 200)

            for block_number in range(first_number, last_visible):
                block = doc.findBlockByNumber(block_number)
                if not block.isValid():
                    break
                if not block.isVisible():  # folded away
                    continue
                cursor = QTextCursor(block)
                rect = self.cursorRect(cursor)

                number = str(block_number + 1)
                painter.setPen(text_color)
                painter.drawText(0, int(rect.top()), self.line_number_area.width() - 4,
                                 self.fontMetrics().height(), Qt.AlignmentFlag.AlignRight, number)

                mark = max(0, block.userState()) & 0xFF
                is_hovered = getattr(self.line_number_area, "hover_y", -1) != -1 and rect.top() <= self.line_number_area.hover_y <= rect.bottom()
                
                marks_enabled = self.main_win.data.get("line_marks", "False") == "True"

                if marks_enabled and (mark > 0 or is_hovered):
                    h = self.fontMetrics().height()
                    cx = 8
                    cy = int(rect.top()) + h // 2
                    size = min(h - 4, 10)
                    
                    if mark == 1 or (mark == 0 and is_hovered):
                        # Checked Box
                        box_color = QColor("#44AA44") if mark == 1 else QColor(68, 170, 68, 120)
                        painter.setPen(QPen(box_color, 1))
                        if mark == 1:
                            painter.setBrush(QColor("#2A1C0A") if "vintage" in theme_name.lower() else QColor("#FFFFFF"))
                        else:
                            painter.setBrush(Qt.BrushStyle.NoBrush)
                        painter.drawRect(cx - size//2, cy - size//2, size, size)
                        if mark == 1:
                            painter.setPen(QPen(QColor("#44AA44"), 2))
                            painter.drawLine(cx - size//2 + 2, cy, cx - 1, cy + size//2 - 2)
                            painter.drawLine(cx - 1, cy + size//2 - 2, cx + size//2 - 1, cy - size//2 + 1)
                    elif mark == 2:
                        # Red Dot
                        painter.setPen(Qt.PenStyle.NoPen)
                        painter.setBrush(QColor("#FF4444"))
                        painter.drawEllipse(cx - size//2, cy - size//2, size, size)
                    elif mark == 3:
                        # Yellow Rhombus
                        painter.setPen(Qt.PenStyle.NoPen)
                        painter.setBrush(QColor("#FFDD44"))
                        poly = [QPoint(cx, cy - size//2), QPoint(cx + size//2, cy), QPoint(cx, cy + size//2), QPoint(cx - size//2, cy)]
                        painter.drawPolygon(poly)
                    elif mark == 4:
                        # Blue Square
                        painter.setPen(Qt.PenStyle.NoPen)
                        painter.setBrush(QColor("#4488FF"))
                        painter.drawRect(cx - size//2, cy - size//2, size, size)
        finally:
            painter.end()

    def line_number_area_mouse_press_event(self, event):
        if self.main_win.data.get("line_marks", "False") != "True":
            return
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
                new_mark = (mark + 1) % 5
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
            logger.debug(f"checkbox hit test error: {e}")
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
            logger.debug(f"checkbox toggle error: {e}")

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
            logger.debug(f"checkbox/anchor mouse error: {e}")
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
            logger.debug(f"checkbox cursor error: {e}")
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

        # Handle "Open Folder" for local file links
        cursor = self.cursorForPosition(event.pos())
        if cursor.charFormat().isAnchor():
            url = QUrl(cursor.charFormat().anchorHref())
            if url.isValid() and url.isLocalFile():
                import os
                import subprocess
                path = os.path.normpath(url.toLocalFile())
                def _open_folder():
                    if os.name == 'nt':
                        subprocess.run(["explorer", "/select,", path])
                    else:
                        QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.dirname(path)))
                open_folder_action = menu.addAction(f"Open folder containing {os.path.basename(path)}")
                open_folder_action.triggered.connect(_open_folder)
                menu.addSeparator()

        lang = getattr(self.main_win, '_current_lang', 'EN')
        menu.addAction(tr("Expand All Folds", lang), self.unfold_all)
        # rare toolbar actions live here too (hidden from narrow headers)
        menu.addAction(tr("Clear Formatting", lang), self.main_win.clear_formatting)
        menu.addAction(tr("Insert Divider Line\tCtrl+W", lang), self.main_win.insert_divider_line)
        menu.addAction(tr("Insert Table", lang), self._insert_table)
        menu.addAction(tr("Insert Kanban", lang), self._insert_kanban)
        state = tr("ON", lang) if self.main_win.data.get("auto_bullet", "False") == "True" else tr("OFF", lang)
        menu.addAction(f"{tr('Auto-Bullet:', lang)} {state}", self._toggle_auto_bullet)
        menu.exec(event.globalPos())

    def _insert_table(self):
        from PyQt6.QtWidgets import (
            QDialog,
            QGridLayout,
            QHBoxLayout,
            QLabel,
            QPushButton,
            QSpinBox,
            QVBoxLayout,
        )
        
        dlg = QDialog(self)
        dlg.setWindowTitle(tr("Insert Table", getattr(self.main_win, "_current_lang", "EN")))
        dlg.setStyleSheet(self.main_win.styleSheet())
        layout = QVBoxLayout(dlg)
        
        grid = QGridLayout()
        grid.addWidget(QLabel(tr("Rows:", getattr(self.main_win, "_current_lang", "EN"))), 0, 0)
        spin_rows = QSpinBox()
        spin_rows.setRange(1, 100)
        spin_rows.setValue(3)
        grid.addWidget(spin_rows, 0, 1)
        
        grid.addWidget(QLabel(tr("Columns:", getattr(self.main_win, "_current_lang", "EN"))), 1, 0)
        spin_cols = QSpinBox()
        spin_cols.setRange(1, 100)
        spin_cols.setValue(3)
        grid.addWidget(spin_cols, 1, 1)
        
        layout.addLayout(grid)
        
        btn_layout = QHBoxLayout()
        btn_ok = QPushButton("OK")
        btn_ok.clicked.connect(dlg.accept)
        btn_cancel = QPushButton("Cancel")
        btn_cancel.clicked.connect(dlg.reject)
        btn_layout.addWidget(btn_ok)
        btn_layout.addWidget(btn_cancel)
        layout.addLayout(btn_layout)
        
        if dlg.exec():
            r = spin_rows.value()
            c = spin_cols.value()
            
            headers = "| " + " | ".join([f"Column {i+1}" for i in range(c)]) + " |\n"
            sep = "| " + " | ".join([":---" for i in range(c)]) + " |\n"
            
            rows = ""
            for i in range(r):
                rows += "| " + " | ".join([f"Row {i+1}" for j in range(c)]) + " |\n"
                
            cursor = self.textCursor()
            cursor.insertText(headers + sep + rows)

    def _insert_kanban(self):
        cursor = self.textCursor()
        kanban = "## Kanban Board\n\n| To Do | In Progress | Done |\n| :--- | :--- | :--- |\n| [ ] Task 1 | [ ] Task 2 | [x] Task 3 |\n| [ ] Task 4 | | |\n"
        cursor.insertText(kanban)

    def _toggle_auto_bullet(self):
        cur = self.main_win.data.get("auto_bullet", "False") == "True"
        self.main_win.data["auto_bullet"] = "False" if cur else "True"
        if hasattr(self.main_win, "btn_bullet_toggle"):
            self.main_win.btn_bullet_toggle.setChecked(not cur)
        self.main_win.mark_dirty()

    def _ask_text_drop_choice(self, name):
        """Dropped a text-based file: insert as text, or store as a file?
        Returns 'text', 'file', 'files_link', 'editor_link', or 'cancel'."""
        from PyQt6.QtWidgets import QMessageBox
        box = QMessageBox(self.main_win)
        lang = getattr(self.main_win, '_current_lang', 'EN')
        box.setWindowTitle(tr("Add dropped file", lang))
        box.setText(tr("How should '{}' be added?", lang).format(name))
        btn_text = box.addButton(tr("📄 Insert as Text", lang), QMessageBox.ButtonRole.AcceptRole)
        btn_editor_link = box.addButton(tr("🔗 Link in Text", lang), QMessageBox.ButtonRole.ActionRole)
        btn_file = box.addButton(tr("📥 Copy to Silo Files 📁", lang), QMessageBox.ButtonRole.ActionRole)
        btn_files_link = box.addButton(tr("🔗 Link in Silo Files 📁", lang), QMessageBox.ButtonRole.ActionRole)
        box.addButton(QMessageBox.StandardButton.Cancel)
        box.setDefaultButton(btn_text)
        box.exec()
        clicked = box.clickedButton()
        if clicked is btn_text: return "text"
        if clicked is btn_editor_link: return "editor_link"
        if clicked is btn_file: return "file"
        if clicked is btn_files_link: return "files_link"
        return "cancel"

    def _ask_binary_drop_choice(self, name):
        from PyQt6.QtWidgets import QMessageBox
        box = QMessageBox(self.main_win)
        lang = getattr(self.main_win, '_current_lang', 'EN')
        box.setWindowTitle(tr("Add dropped file", lang))
        box.setText(tr("How should '{}' be added?", lang).format(name))
        btn_file = box.addButton(tr("📥 Copy to Silo Files 📁", lang), QMessageBox.ButtonRole.AcceptRole)
        btn_files_link = box.addButton(tr("🔗 Link in Silo Files 📁", lang), QMessageBox.ButtonRole.ActionRole)
        btn_editor_link = box.addButton(tr("🔗 Link in Text", lang), QMessageBox.ButtonRole.ActionRole)
        box.addButton(QMessageBox.StandardButton.Cancel)
        box.setDefaultButton(btn_file)
        box.exec()
        clicked = box.clickedButton()
        if clicked is btn_file: return "file"
        if clicked is btn_files_link: return "files_link"
        if clicked is btn_editor_link: return "editor_link"
        return "cancel"

    def _drop_overlay(self):
        from fastprompter.ui.drop_overlay import DropOverlay
        if getattr(self, "_overlay", None) is None:
            self._overlay = DropOverlay(self)
        return self._overlay

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls() and any(
            u.isLocalFile() for u in event.mimeData().urls()
        ):
            paths = [u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()]
            any_text = any(
                os.path.splitext(p)[1].lower() in TEXT_EXTENSIONS
                or not os.path.splitext(p)[1]
                for p in paths
            )
            self._drop_overlay().begin(has_text_option=any_text)
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        ov = getattr(self, "_overlay", None)
        if ov is not None and ov.isVisible():
            ov.track(event.position().toPoint())
            event.acceptProposedAction()
            return
        super().dragMoveEvent(event)

    def dragLeaveEvent(self, event):
        ov = getattr(self, "_overlay", None)
        if ov is not None:
            ov.end()
        super().dragLeaveEvent(event)

    def dropEvent(self, event):
        ov = getattr(self, "_overlay", None)
        if ov is not None and ov.isVisible():
            zone = ov.zone_at(event.position().toPoint())
            ov.end()
            paths = [u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()]
            self._drop_paths(paths, zone)
            event.acceptProposedAction()
            return
        super().dropEvent(event)

    def _drop_paths(self, paths, zone):
        """Route dropped files according to the chosen zone."""
        to_files = []
        to_links = []
        for path in paths:
            ext = os.path.splitext(path)[1].lower()
            is_text = ext in TEXT_EXTENSIONS or not ext
            if zone == "text" and is_text:
                try:
                    with open(path, encoding="utf-8", errors="replace") as f:
                        self.insertPlainText(f.read())
                except OSError:
                    import traceback
                    traceback.print_exc()
            elif zone == "editor_link":
                name = os.path.basename(path)
                clean_path = path.replace("\\", "/")
                self.insertPlainText(f"[{name}](file:///{clean_path})")
            elif zone == "files_link":
                to_links.append(path)
            else:
                to_files.append(path)

        if to_files:
            self.main_win.add_files_to_active_silo(to_files)
        if to_links:
            self.main_win.add_links_to_active_silo(to_links)

    def insertFromMimeData(self, source):
        if source.hasUrls():
            # Paste of copied files (Ctrl+V from Explorer) — no drag overlay,
            # ask per file like before
            for url in source.urls():
                if url.isLocalFile():
                    path = url.toLocalFile()
                    ext = os.path.splitext(path)[1].lower()
                    if ext in TEXT_EXTENSIONS or not ext:
                        choice = self._ask_text_drop_choice(os.path.basename(path))
                        if choice == "file":
                            self.main_win.add_files_to_active_silo([path])
                        elif choice == "text":
                            try:
                                with open(path, encoding="utf-8", errors="replace") as f:
                                    self.insertPlainText(f.read())
                            except Exception:
                                import traceback
                                traceback.print_exc()
                        elif choice == "files_link":
                            self.main_win.add_links_to_active_silo([path])
                        elif choice == "editor_link":
                            name = os.path.basename(path)
                            clean_path = path.replace("\\", "/")
                            self.insertPlainText(f"[{name}](file:///{clean_path})")
                    else:
                        choice = self._ask_binary_drop_choice(os.path.basename(path))
                        if choice == "file":
                            self.main_win.add_files_to_active_silo([path])
                        elif choice == "files_link":
                            self.main_win.add_links_to_active_silo([path])
                        elif choice == "editor_link":
                            name = os.path.basename(path)
                            clean_path = path.replace("\\", "/")
                            self.insertPlainText(f"[{name}](file:///{clean_path})")
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
            
        mw = self.main_win
        
        if mods == Qt.KeyboardModifier.NoModifier and event.key() == Qt.Key.Key_Delete:
            if not self.toPlainText().strip():
                from PyQt6.QtWidgets import QMessageBox
                reply = QMessageBox.question(
                    self,
                    tr("Trash, not delete", getattr(mw, "_current_lang", "EN")),
                    tr("Delete this silo and move it to trash?", getattr(mw, "_current_lang", "EN")),
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No
                )
                if reply == QMessageBox.StandardButton.Yes:
                    is_archive = getattr(mw, "active_is_archive", False)
                    mw.trash_silo(mw.active_temp_slot, is_archive)
                event.accept()
                return

        from PyQt6.QtGui import QKeySequence
        key_val = event.key()
        if key_val > 0 and key_val != Qt.Key.Key_unknown:
            # Need to handle Qt's quirk where Shift+Ctrl+S can parse strangely if we don't use exact match
            # But QKeySequence(key_val | mods.value) is standard.
            seq_str = QKeySequence(key_val | mods.value).toString()

            def matches(name, default):
                return seq_str and seq_str == QKeySequence(mw.data.get(name, default)).toString()

            if matches("hk_header", "Ctrl+E"):
                mw.apply_header_timestamp(); event.accept(); return
            if matches("hk_bold", "Ctrl+B"):
                mw.apply_bold_smart(); event.accept(); return
            if matches("hk_undo", "Ctrl+Z"):
                if hasattr(mw, "_smart_undo"): mw._smart_undo()
                event.accept(); return
            if matches("hk_new_snippet", "Ctrl+N"):
                mw.select_empty_silo(); event.accept(); return
            if matches("hk_save_snippet", "Ctrl+S"):
                mw.save_snippet(); event.accept(); return
            if matches("hk_export_silo", "Ctrl+Shift+S"):
                mw.save_silo_to_file(); event.accept(); return
            if matches("hk_find", "Ctrl+F"):
                mw.show_find(); event.accept(); return
            if matches("hk_replace", "Ctrl+H"):
                mw.show_replace(); event.accept(); return
            if matches("hk_focus", "Ctrl+D"):
                mw.toggle_focus_mode(); event.accept(); return
            if matches("hk_divider", "Ctrl+W"):
                mw.insert_divider_line(); event.accept(); return
            if matches("hk_snap", "Ctrl+Q"):
                mw.cycle_snap_corner(); event.accept(); return

        if mods == Qt.KeyboardModifier.ControlModifier and event.key() in (
            Qt.Key.Key_B, Qt.Key.Key_I, Qt.Key.Key_U, Qt.Key.Key_T
        ):
            # Markdown marker toggles for non-configurable ones — must run before QTextEdit's built-in
            if event.key() == Qt.Key.Key_I: mw.apply_format("italic")
            elif event.key() == Qt.Key.Key_U: mw.apply_format("underline")
            elif event.key() == Qt.Key.Key_T: mw.apply_format("strike")
            event.accept()
            return

        if mods == Qt.KeyboardModifier.ControlModifier and event.key() in (Qt.Key.Key_Z, Qt.Key.Key_Y):
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
                if cursor.atBlockEnd() and cursor.block().length() > 1:
                    cursor.select(QTextCursor.SelectionType.BlockUnderCursor)
                else:
                    cursor.select(QTextCursor.SelectionType.Document)
                self.setTextCursor(cursor)
            super().keyPressEvent(event)
            if self.main_win.cb_ctrl_c.isChecked():
                QTimer.singleShot(10, lambda: not sip.isdeleted(self) and not sip.isdeleted(
                    self.main_win) and self.main_win.hide_and_save())
            return

        if event.key() == Qt.Key.Key_V and mods == Qt.KeyboardModifier.ControlModifier:
            clipboard = QApplication.clipboard()
            if clipboard.mimeData().hasUrls():
                urls = [u for u in clipboard.mimeData().urls() if u.isLocalFile()]
                if urls:
                    links = []
                    for u in urls:
                        path = u.toLocalFile()
                        name = os.path.basename(path)
                        # Ensure forward slashes for Markdown links
                        links.append(f"[{name}](file:///{path.replace(os.sep, '/')})")
                    self.textCursor().insertText("\n".join(links))
                    event.accept()
                    return

        if event.key() in (Qt.Key.Key_Tab, Qt.Key.Key_Backtab) and mods in (Qt.KeyboardModifier.NoModifier, Qt.KeyboardModifier.ShiftModifier):
            cursor = self.textCursor()
            if cursor.hasSelection():
                # Block indentation
                start_block = self.document().findBlock(cursor.selectionStart()).blockNumber()
                end_block = self.document().findBlock(cursor.selectionEnd()).blockNumber()
                
                # if selection ends exactly at the start of a block, don't indent that block
                if cursor.selectionEnd() == self.document().findBlockByNumber(end_block).position() and end_block > start_block:
                    end_block -= 1
                
                edit_cursor = QTextCursor(self.document())
                edit_cursor.beginEditBlock()
                for b in range(start_block, end_block + 1):
                    edit_cursor.setPosition(self.document().findBlockByNumber(b).position())
                    if event.key() == Qt.Key.Key_Tab and mods == Qt.KeyboardModifier.NoModifier:
                        edit_cursor.insertText("    ")
                    elif event.key() == Qt.Key.Key_Backtab or mods == Qt.KeyboardModifier.ShiftModifier:
                        edit_cursor.movePosition(QTextCursor.MoveOperation.EndOfBlock, QTextCursor.MoveMode.KeepAnchor)
                        text = edit_cursor.selectedText()
                        if text.startswith("    "):
                            edit_cursor.insertText(text[4:])
                        elif text.startswith("\t"):
                            edit_cursor.insertText(text[1:])
                edit_cursor.endEditBlock()
                event.accept()
                return
            else:
                # Single line Tab handling: "shift the cursor with the • accordingly"
                block = cursor.block()
                text = block.text()
                pos = cursor.positionInBlock()
                if text.lstrip().startswith("• "):
                    indent = len(text) - len(text.lstrip())
                    if pos <= indent + 2:
                        edit_cursor = QTextCursor(self.document())
                        edit_cursor.beginEditBlock()
                        edit_cursor.setPosition(block.position())
                        if event.key() == Qt.Key.Key_Tab and mods == Qt.KeyboardModifier.NoModifier:
                            edit_cursor.insertText("    ")
                        elif event.key() == Qt.Key.Key_Backtab or mods == Qt.KeyboardModifier.ShiftModifier:
                            if text.startswith("    "):
                                edit_cursor.movePosition(QTextCursor.MoveOperation.Right, QTextCursor.MoveMode.KeepAnchor, 4)
                                edit_cursor.removeSelectedText()
                            elif text.startswith("\t"):
                                edit_cursor.movePosition(QTextCursor.MoveOperation.Right, QTextCursor.MoveMode.KeepAnchor, 1)
                                edit_cursor.removeSelectedText()
                        edit_cursor.endEditBlock()
                        event.accept()
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
