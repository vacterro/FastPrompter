from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import QGridLayout, QLabel, QLineEdit, QWidget


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
            menu.addAction("Insert row above", lambda _: grid.insert_row(self, -1))
            menu.addAction("Insert row below", lambda _: grid.insert_row(self, 1))
            menu.addAction("Delete row", lambda _: grid.delete_row(self))
            menu.addSeparator()
            menu.addAction("Insert column left", lambda _: grid.insert_col(self, -1))
            menu.addAction("Insert column right", lambda _: grid.insert_col(self, 1))
            menu.addAction("Delete column", lambda _: grid.delete_col(self))
        menu.exec(e.globalPos())

    def keyPressEvent(self, e):
        grid = self.parentWidget()
        if not isinstance(grid, TableGridWidget):
            return super().keyPressEvent(e)
            
        if e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            # Move to cell below
            r, c = grid._pos_of(self)
            if r + 1 < len(grid.cells):
                grid.cells[r + 1][c].setFocus()
            else:
                # We are at the bottom, insert a new row!
                grid.insert_row(self, 1)
                # focus the new cell below
                grid.cells[-1][c].setFocus()
            e.accept()
            return
            
        if e.key() in (Qt.Key.Key_Tab, Qt.Key.Key_Backtab):
            mods = e.modifiers()
            r, c = grid._pos_of(self)
            # Shift+Tab arrives as Key_Backtab, NOT as Tab with a modifier, so
            # testing only the modifier left the backwards branch unreachable
            if (mods & Qt.KeyboardModifier.ShiftModifier
                    or e.key() == Qt.Key.Key_Backtab):
                # previous cell
                if c > 0:
                    grid.cells[r][c - 1].setFocus()
                elif r > 0:
                    grid.cells[r - 1][-1].setFocus()
            else:
                # next cell
                if c + 1 < len(grid.cells[r]):
                    grid.cells[r][c + 1].setFocus()
                elif r + 1 < len(grid.cells):
                    grid.cells[r + 1][0].setFocus()
                else:
                    # last cell — add new row
                    grid.insert_row(self, 1)
                    grid.cells[-1][0].setFocus()
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
    undoRequested = pyqtSignal()
    
    def __init__(self, parent=None):
        super().__init__(parent)
        # NOT `self.layout`: that name is QWidget.layout(), and shadowing it
        # with a QGridLayout instance makes `widget.layout()` raise
        # "'QGridLayout' object is not callable" in any generic code that
        # walks widgets — of which this app has several passes.
        self._grid = QGridLayout(self)
        self._grid.setSpacing(1)
        self._grid.setContentsMargins(4, 4, 4, 4)
        
        self._sync_timer = QTimer(self)
        self._sync_timer.setInterval(500)
        self._sync_timer.setSingleShot(True)
        self._sync_timer.timeout.connect(self._do_serialize)
        
        self.cells = [] # 2D array of CellWidgets
        self.alignments = [] # List of alignments (left, center, right)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        
    def keyPressEvent(self, e):
        mods = e.modifiers()
        if mods == Qt.KeyboardModifier.ControlModifier and e.key() == Qt.Key.Key_Z:
            self.undoRequested.emit()
            e.accept()
            return
        super().keyPressEvent(e)
        
    def load_markdown(self, text):
        # The silo is not only this table: it can have a title above and notes
        # below, and serialize() writes back over the WHOLE silo. Keep the
        # lines around the table and splice them back on the way out.
        # Measured without this: a silo whose first line was "# Weekly report"
        # came back as "| # Weekly report |\n| --- |" — heading parsed as the
        # header row, everything else gone.
        from fastprompter.ui import silo_region
        all_lines = (text or "").split("\n")
        span = silo_region.table_region(all_lines)
        self._prefix, region, self._suffix = silo_region.split(all_lines, span)
        text = "\n".join(region)

        # Clear existing
        while self._grid.count():
            item = self._grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        self.cells = []
        self.alignments = []

        def _split_pipe(s):
            cells, current, escaped = [], [], False
            for ch in s:
                if escaped:
                    escaped = False
                    if ch == '|':
                        current.append('|')
                        continue
                    current.append('\\')
                    current.append(ch)
                    continue
                if ch == '\\':
                    escaped = True
                    continue
                if ch == '|':
                    cells.append(''.join(current).strip())
                    current = []
                    continue
                current.append(ch)
            cells.append(''.join(current).strip())
            return cells

        lines = text.strip().split('\n')
        # Skip empty lines at start
        while lines and not lines[0].strip():
            lines.pop(0)
            
        if not lines:
            lines = ["New Column 1 | New Column 2", "--- | ---", " | "]
            
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
            if line.endswith('|') and not line.endswith('\\|'):
                line = line[:-1]
            cols = _split_pipe(line)
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
                    # a PROPERTY, not an inline stylesheet: an inline sheet on
                    # the widget overrides the themed one and the header cell
                    # stopped following the theme entirely
                    cw.setProperty("header", "true")
                
                if c_idx < len(self.alignments):
                    cw.setAlignment(self.alignments[c_idx])
                    
                cw.textEdited.connect(self._schedule_sync)
                self._grid.addWidget(cw, r_idx, c_idx)
                cell_row.append(cw)
            self.cells.append(cell_row)
            
        self._add_action_buttons()
            
    def _add_action_buttons(self):
        if not self.cells or not self.cells[0]:
            return          # nothing to hang them off; indexing [0] would raise
        if hasattr(self, "btn_add_col"):
            self.btn_add_col.deleteLater()
        if hasattr(self, "btn_add_row"):
            self.btn_add_row.deleteLater()
            
        self.btn_add_col = QLabel("+")
        self.btn_add_col.setObjectName("table_add")
        self.btn_add_col.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_add_col.setToolTip("Add Column")
        self.btn_add_col.mousePressEvent = lambda e: self.insert_col(self.cells[0][-1], 1)
        self._grid.addWidget(self.btn_add_col, 0, len(self.cells[0]))
        
        self.btn_add_row = QLabel("+ Row")
        self.btn_add_row.setObjectName("table_add")
        self.btn_add_row.setToolTip("Add Row")
        self.btn_add_row.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_add_row.mousePressEvent = lambda e: self.insert_row(self.cells[-1][0], 1)
        self._grid.addWidget(self.btn_add_row, len(self.cells), 0,
                             Qt.AlignmentFlag.AlignLeft)

        # All the slack goes into a phantom row BELOW everything, so the table
        # packs to the top and "+ Row" sits under the last row instead of
        # floating in the middle of the empty space the grid handed it.
        for r in range(self._grid.rowCount()):
            self._grid.setRowStretch(r, 0)
        self._grid.setRowStretch(len(self.cells) + 1, 1)
        
    def _schedule_sync(self):
        self._sync_timer.start()
        
    def _do_serialize(self):
        self.changed.emit(self.serialize())
        
    def serialize(self):
        """The whole silo: the text around the table, with the table rebuilt.

        Returning only the table here is what deleted the rest of the silo.
        """
        from fastprompter.ui import silo_region
        prefix = getattr(self, "_prefix", [])
        suffix = getattr(self, "_suffix", [])
        return silo_region.splice(prefix, self._table_lines(), suffix)

    def _table_lines(self):
        """The table as markdown, through the SAME formatter the plain-text
        path uses (`silo_table.render`).

        Two serialisers for one format is two definitions of the format: this
        one wrote `---` for a left column while the text path wrote `:---`, so
        a silo edited in both spun that difference back and forth on every
        save. Rendering through one place also aligns the pipes, which is what
        makes the raw text readable — the only view a pasted silo has.
        """
        if not self.cells:
            return []
        from fastprompter.ui import silo_table as st

        align_of = {
            Qt.AlignmentFlag.AlignCenter: st.ALIGN_CENTER,
            Qt.AlignmentFlag.AlignRight: st.ALIGN_RIGHT,
        }
        rows = [[cw.text().strip().replace("|", "\\|") for cw in row]
                for row in self.cells]
        aligns = [align_of.get(a, st.ALIGN_LEFT) for a in self.alignments]
        width = max((len(r) for r in rows), default=0)
        if len(aligns) < width:
            aligns += [st.ALIGN_LEFT] * (width - len(aligns))
        return st.render(st.Table(0, 0, rows, aligns[:width] or [st.ALIGN_LEFT],
                                 has_header=True))

    def swap_row_up(self, cell):
        r, c = self._pos_of(cell)
        if r > 1: # Don't swap with header (row 0)
            for i in range(len(self.cells[r])):
                t1 = self.cells[r][i].text()
                t2 = self.cells[r-1][i].text()
                self.cells[r][i].setText(t2)
                self.cells[r-1][i].setText(t1)
            self.cells[r-1][c].setFocus()
            self._schedule_sync()
        
    def swap_row_down(self, cell):
        r, c = self._pos_of(cell)
        if r >= 1 and r < len(self.cells) - 1:
            for i in range(len(self.cells[r])):
                t1 = self.cells[r][i].text()
                t2 = self.cells[r+1][i].text()
                self.cells[r][i].setText(t2)
                self.cells[r+1][i].setText(t1)
            self.cells[r+1][c].setFocus()
            self._schedule_sync()
        
    def swap_col_left(self, cell):
        r, c = self._pos_of(cell)
        if c > 0:
            for row in self.cells:
                t1 = row[c].text()
                t2 = row[c-1].text()
                row[c].setText(t2)
                row[c-1].setText(t1)
            # Swap alignments too
            if len(self.alignments) > c:
                self.alignments[c], self.alignments[c-1] = self.alignments[c-1], self.alignments[c]
                # Re-apply alignments
                for row in self.cells:
                    row[c].setAlignment(self.alignments[c])
                    row[c-1].setAlignment(self.alignments[c-1])
            self.cells[r][c-1].setFocus()
            self._schedule_sync()
        
    def swap_col_right(self, cell):
        r, c = self._pos_of(cell)
        if c >= 0 and c < len(self.cells[0]) - 1:
            for row in self.cells:
                t1 = row[c].text()
                t2 = row[c+1].text()
                row[c].setText(t2)
                row[c+1].setText(t1)
            if len(self.alignments) > c + 1:
                self.alignments[c], self.alignments[c+1] = self.alignments[c+1], self.alignments[c]
                for row in self.cells:
                    row[c].setAlignment(self.alignments[c])
                    row[c+1].setAlignment(self.alignments[c+1])
            self.cells[r][c+1].setFocus()
            self._schedule_sync()

    def _pos_of(self, cell):
        for r, row in enumerate(self.cells):
            if cell in row:
                return r, row.index(cell)
        return -1, -1
        
    def insert_row(self, cell, offset):
        r, _ = self._pos_of(cell)
        if r == -1: return
        
        target_r = r if offset < 0 else r + 1
        # Prevent inserting a row above the header (row 0)
        target_r = max(1, target_r)
        
        cols = len(self.cells[0]) if self.cells else 0
        new_row = []
        
        # shift widgets down
        for move_r in range(len(self.cells)-1, target_r-1, -1):
            for c in range(cols):
                w = self.cells[move_r][c]
                self._grid.removeWidget(w)
                self._grid.addWidget(w, move_r + 1, c)
                
        for c in range(cols):
            cw = CellWidget("", self)
            if c < len(self.alignments):
                cw.setAlignment(self.alignments[c])
            cw.textEdited.connect(self._schedule_sync)
            self._grid.addWidget(cw, target_r, c)
            new_row.append(cw)
            
        self.cells.insert(target_r, new_row)
        self._add_action_buttons()
        self._schedule_sync()
        
    def delete_row(self, cell):
        r, _ = self._pos_of(cell)
        if r <= 0 or len(self.cells) <= 2: return
        
        # remove widgets
        for cw in self.cells[r]:
            self._grid.removeWidget(cw)
            cw.deleteLater()
            
        # shift widgets up
        for move_r in range(r + 1, len(self.cells)):
            for c in range(len(self.cells[0])):
                w = self.cells[move_r][c]
                self._grid.removeWidget(w)
                self._grid.addWidget(w, move_r - 1, c)
                
        self.cells.pop(r)
        self._add_action_buttons()
        self._schedule_sync()
        
    def insert_col(self, cell, offset):
        _, c = self._pos_of(cell)
        if c == -1: return
        
        target_c = c if offset < 0 else c + 1
        
        # shift right
        for r in range(len(self.cells)):
            for move_c in range(len(self.cells[0])-1, target_c-1, -1):
                w = self.cells[r][move_c]
                self._grid.removeWidget(w)
                self._grid.addWidget(w, r, move_c + 1)
                
        for r in range(len(self.cells)):
            cw = CellWidget("", self)
            cw.textEdited.connect(self._schedule_sync)
            self._grid.addWidget(cw, r, target_c)
            self.cells[r].insert(target_c, cw)
            
        self.alignments.insert(target_c, Qt.AlignmentFlag.AlignLeft)
        self._add_action_buttons()
        self._schedule_sync()
        
    def delete_col(self, cell):
        _, c = self._pos_of(cell)
        if c == -1 or len(self.cells[0]) <= 1: return
        
        for r in range(len(self.cells)):
            cw = self.cells[r][c]
            self._grid.removeWidget(cw)
            cw.deleteLater()
            self.cells[r].pop(c)
            
            # shift left
            for move_c in range(c, len(self.cells[0])):
                w = self.cells[r][move_c]
                self._grid.removeWidget(w)
                self._grid.addWidget(w, r, move_c)
                
        if c < len(self.alignments):
            self.alignments.pop(c)
            
        self._add_action_buttons()
        self._schedule_sync()
