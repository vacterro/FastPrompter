from PyQt6.QtWidgets import (
    QWidget, QGridLayout, QLineEdit, QMenu, QApplication, QLabel
)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer

class CellWidget(QLineEdit):
    def __init__(self, text, parent=None):
        super().__init__(text, parent)
        self.setFrame(False)
        self.setAlignment(Qt.AlignmentFlag.AlignLeft)
        # Empty cells show em-dash placeholder in muted color when unfocused
        self.setPlaceholderText("—")
        
    def contextMenuEvent(self, e):
        menu = self.createStandardContextMenu()
        menu.addSeparator()
        # The parent grid will hook into these actions
        grid = self.parentWidget()
        if isinstance(grid, TableGridWidget):
            menu.addAction("Insert row above", lambda: grid.insert_row(self, -1))
            menu.addAction("Insert row below", lambda: grid.insert_row(self, 1))
            menu.addAction("Delete row", lambda: grid.delete_row(self))
            menu.addSeparator()
            menu.addAction("Insert column left", lambda: grid.insert_col(self, -1))
            menu.addAction("Insert column right", lambda: grid.insert_col(self, 1))
            menu.addAction("Delete column", lambda: grid.delete_col(self))
        menu.exec(e.globalPos())

    def keyPressEvent(self, e):
        grid = self.parentWidget()
        if not isinstance(grid, TableGridWidget):
            return super().keyPressEvent(e)
            
        if e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            # Move to cell below
            r, c, _, _ = grid.layout.getItemPosition(grid.layout.indexOf(self))
            if r + 1 < grid.layout.rowCount():
                item = grid.layout.itemAtPosition(r + 1, c)
                if item and item.widget():
                    item.widget().setFocus()
            e.accept()
            return
            
        mods = e.modifiers()
        if mods == (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier):
            if e.key() == Qt.Key.Key_Up:
                grid.swap_row_up(self)
                e.accept()
                return
            elif e.key() == Qt.Key.Key_Down:
                grid.swap_row_down(self)
                e.accept()
                return
                
        if mods == Qt.KeyboardModifier.AltModifier:
            if e.key() == Qt.Key.Key_Left:
                grid.swap_col_left(self)
                e.accept()
                return
            elif e.key() == Qt.Key.Key_Right:
                grid.swap_col_right(self)
                e.accept()
                return
                
        super().keyPressEvent(e)

class TableGridWidget(QWidget):
    changed = pyqtSignal(str)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.layout = QGridLayout(self)
        self.layout.setSpacing(1)
        self.layout.setContentsMargins(4, 4, 4, 4)
        
        self._sync_timer = QTimer(self)
        self._sync_timer.setInterval(500)
        self._sync_timer.setSingleShot(True)
        self._sync_timer.timeout.connect(self._do_serialize)
        
        self.cells = [] # 2D array of CellWidgets
        self.alignments = [] # List of alignments (left, center, right)
        
    def load_markdown(self, text):
        # Clear existing
        while self.layout.count():
            item = self.layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
                
        self.cells = []
        self.alignments = []
        
        lines = text.strip().split('\n')
        # Skip empty lines at start
        while lines and not lines[0].strip():
            lines.pop(0)
            
        if not lines:
            return
            
        # Parse table
        # We expect header, separator, body
        # Simple markdown table parser
        rows = []
        for line in lines:
            line = line.strip()
            if not line:
                break # stop at empty line
            if line.startswith('|'):
                line = line[1:]
            if line.endswith('|'):
                line = line[:-1]
            cols = [c.strip() for c in line.split('|')]
            rows.append(cols)
            
        if len(rows) >= 2:
            # Check separator
            sep = rows[1]
            self.alignments = []
            for col in sep:
                col = col.strip()
                if col.startswith(':') and col.endswith(':'):
                    self.alignments.append(Qt.AlignmentFlag.AlignCenter)
                elif col.endswith(':'):
                    self.alignments.append(Qt.AlignmentFlag.AlignRight)
                else:
                    self.alignments.append(Qt.AlignmentFlag.AlignLeft)
                    
            rows.pop(1) # remove separator
        else:
            if rows:
                self.alignments = [Qt.AlignmentFlag.AlignLeft] * len(rows[0])
            
        for r_idx, row in enumerate(rows):
            cell_row = []
            for c_idx, text in enumerate(row):
                cw = CellWidget(text, self)
                if r_idx == 0:
                    cw.setStyleSheet("font-weight: bold;")
                
                if c_idx < len(self.alignments):
                    cw.setAlignment(self.alignments[c_idx])
                    
                cw.textEdited.connect(self._schedule_sync)
                self.layout.addWidget(cw, r_idx, c_idx)
                cell_row.append(cw)
            self.cells.append(cell_row)
            
    def _schedule_sync(self):
        self._sync_timer.start()
        
    def _do_serialize(self):
        self.changed.emit(self.serialize())
        
    def serialize(self):
        if not self.cells:
            return ""
            
        lines = []
        for r_idx, row in enumerate(self.cells):
            line_cells = []
            for c_idx, cw in enumerate(row):
                line_cells.append(cw.text().strip())
            lines.append("| " + " | ".join(line_cells) + " |")
            
            if r_idx == 0:
                # build separator
                sep_cells = []
                for c_idx in range(len(row)):
                    align = self.alignments[c_idx] if c_idx < len(self.alignments) else Qt.AlignmentFlag.AlignLeft
                    if align == Qt.AlignmentFlag.AlignCenter:
                        sep_cells.append(":---:")
                    elif align == Qt.AlignmentFlag.AlignRight:
                        sep_cells.append("---:")
                    else:
                        sep_cells.append("---")
                lines.append("| " + " | ".join(sep_cells) + " |")
                
        return "\n".join(lines)
        
    def _pos_of(self, cell):
        for r, row in enumerate(self.cells):
            if cell in row:
                return r, row.index(cell)
        return -1, -1
        
    def insert_row(self, cell, offset):
        r, _ = self._pos_of(cell)
        if r == -1: return
        
        target_r = r if offset < 0 else r + 1
        cols = len(self.cells[0]) if self.cells else 0
        new_row = []
        
        # shift widgets down
        for move_r in range(len(self.cells)-1, target_r-1, -1):
            for c in range(cols):
                w = self.cells[move_r][c]
                self.layout.removeWidget(w)
                self.layout.addWidget(w, move_r + 1, c)
                
        for c in range(cols):
            cw = CellWidget("", self)
            if c < len(self.alignments):
                cw.setAlignment(self.alignments[c])
            cw.textEdited.connect(self._schedule_sync)
            self.layout.addWidget(cw, target_r, c)
            new_row.append(cw)
            
        self.cells.insert(target_r, new_row)
        self._do_serialize()
        
    def delete_row(self, cell):
        r, _ = self._pos_of(cell)
        if r == -1 or len(self.cells) <= 1: return
        
        for w in self.cells[r]:
            self.layout.removeWidget(w)
            w.deleteLater()
            
        self.cells.pop(r)
        
        # shift up
        cols = len(self.cells[0])
        for move_r in range(r, len(self.cells)):
            for c in range(cols):
                w = self.cells[move_r][c]
                self.layout.removeWidget(w)
                self.layout.addWidget(w, move_r, c)
                
        self._do_serialize()
        
    def insert_col(self, cell, offset):
        _, c = self._pos_of(cell)
        if c == -1: return
        
        target_c = c if offset < 0 else c + 1
        
        # shift widgets right
        for r in range(len(self.cells)):
            for move_c in range(len(self.cells[r])-1, target_c-1, -1):
                w = self.cells[r][move_c]
                self.layout.removeWidget(w)
                self.layout.addWidget(w, r, move_c + 1)
                
        self.alignments.insert(target_c, Qt.AlignmentFlag.AlignLeft)
        
        for r in range(len(self.cells)):
            cw = CellWidget("", self)
            cw.setAlignment(Qt.AlignmentFlag.AlignLeft)
            cw.textEdited.connect(self._schedule_sync)
            self.layout.addWidget(cw, r, target_c)
            self.cells[r].insert(target_c, cw)
            
        self._do_serialize()
        
    def delete_col(self, cell):
        _, c = self._pos_of(cell)
        if c == -1 or len(self.cells[0]) <= 1: return
        
        for r in range(len(self.cells)):
            w = self.cells[r][c]
            self.layout.removeWidget(w)
            w.deleteLater()
            self.cells[r].pop(c)
            
        self.alignments.pop(c)
        
        # shift left
        for r in range(len(self.cells)):
            for move_c in range(c, len(self.cells[r])):
                w = self.cells[r][move_c]
                self.layout.removeWidget(w)
                self.layout.addWidget(w, r, move_c)
                
        self._do_serialize()
