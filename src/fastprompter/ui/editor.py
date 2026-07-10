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
    QPolygon,
    QTextCursor,
)
from PyQt6.QtWidgets import QTextEdit, QWidget


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

    def sizeHint(self):
        return QSize(self.editor.line_number_area_width(), 0)

    def paintEvent(self, event):
        self.editor.line_number_area_paint_event(event)

    def mousePressEvent(self, event):
        self.editor.line_number_area_mouse_press_event(event)


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
            for i in range(scan_limit):
                if "[" in doc.findBlockByNumber(i).text():
                    self._doc_has_checkbox = True
                    return
            self._doc_has_checkbox = False

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
        if not hasattr(self, 'main_win') or self.main_win.data.get("show_line_numbers", "False") != "True":
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
        if not hasattr(self, 'main_win') or self.main_win.data.get("show_line_numbers", "False") != "True":
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
            for block_number in range(first_number, last_visible):
                block = doc.findBlockByNumber(block_number)
                if not block.isValid():
                    break
                cursor = QTextCursor(block)
                rect = self.cursorRect(cursor)
                number = str(block_number + 1)
                painter.setPen(QColor("#808080"))
                painter.drawText(0, int(rect.top()), self.line_number_area.width() - 10,
                                 self.fontMetrics().height(), Qt.AlignmentFlag.AlignRight, number)
                mark = block.userState()
                if mark > 0:
                    y_center = int(rect.top() + self.fontMetrics().height() / 2)
                    x_center = self.line_number_area.width() - 5
                    if mark == 1:
                        painter.setBrush(QColor("red"))
                        painter.setPen(Qt.PenStyle.NoPen)
                        painter.drawEllipse(QPoint(x_center, y_center), 3, 3)
                    elif mark == 2:
                        painter.setBrush(QColor("cyan"))
                        painter.setPen(Qt.PenStyle.NoPen)
                        painter.drawRect(x_center - 3, y_center - 3, 6, 6)
                    elif mark == 3:
                        painter.setBrush(QColor("yellow"))
                        painter.setPen(Qt.PenStyle.NoPen)
                        poly = QPolygon([QPoint(x_center, y_center - 4),
                                         QPoint(x_center - 4, y_center + 3),
                                         QPoint(x_center + 4, y_center + 3)])
                        painter.drawPolygon(poly)
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
                current = block.userState()
                if current == -1:
                    current = 0
                block.setUserState((current + 1) % 4)
                self.line_number_area.update()
                break
            block = block.next()

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

    def mouseMoveEvent(self, event):
        if sip.isdeleted(self):
            return
        try:
            if not event.buttons():
                p = event.pos()
                if (p - self._last_hover_pos).manhattanLength() > 3:
                    self._last_hover_pos = p
                    over_cb = self._checkbox_at_pos(p)
                    target = Qt.CursorShape.PointingHandCursor if over_cb else Qt.CursorShape.IBeamCursor
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
        super().contextMenuEvent(event)

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
                        try:
                            with open(path, encoding="utf-8", errors="replace") as f:
                                content = f.read()
                            self.insertPlainText(content)
                        except Exception:
                            import traceback
                            traceback.print_exc()
                    else:
                        self.insertPlainText(f"[Dropped file: {os.path.basename(path)} - unsupported format]\n")
            return
        if self.main_win.btn_format.text() == "Plain":
            if source.hasText():
                self.insertPlainText(source.text())
        else:
            super().insertFromMimeData(source)

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

        if mods == Qt.KeyboardModifier.ControlModifier and event.key() == Qt.Key.Key_Return:
            self._toggle_checkboxes()
            event.accept()
            return

        if mods == Qt.KeyboardModifier.ControlModifier and event.key() == Qt.Key.Key_E:
            # Delegate to main window's combined header+timestamp method
            self.main_win.apply_header_timestamp()
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
        # line with the same bullet; Enter on an empty bullet removes it.
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and mods == Qt.KeyboardModifier.NoModifier:
            if self.main_win.data.get("auto_bullet", "False") == "True":
                cursor = self.textCursor()
                if not cursor.hasSelection():
                    block_text = cursor.block().text()
                    stripped = block_text.lstrip()
                    indent = block_text[:len(block_text) - len(stripped)]
                    m = re.match(r'^([\u2022\-\*\+])[ \t]+(.*)$', stripped)
                    if m and cursor.positionInBlock() >= len(block_text) - len(m.group(2)):
                        if m.group(2).strip():
                            cursor.insertText("\n" + indent + m.group(1) + " ")
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
