"""The model/view half of the interactive table grid.

A markdown table is the source of truth: the DB holds text, the disk mirror
writes text, and a paste into an agent is text. So the grid is built from
`silo_table.parse` and serialised through `silo_table.render`, exactly like
the plain-text editing path. What changes here is only the VIEW and the
interaction: a QTableView over a QAbstractTableModel gives single-cell
editing, rectangular selection, column resizing and a real keyboard model for
free, instead of a hand-built QGridLayout of QLineEdits where every one of
those had to be reinvented — and where the grid silently lost the user's
selection the moment it reflowed.

No formulas, no macros, no spreadsheet engine: every cell is the unescaped
markdown cell text and nothing else.
"""

from __future__ import annotations

from PyQt6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PyQt6.QtGui import QFont

from fastprompter.ui import clipboard_tsv
from fastprompter.ui import silo_table as st


class TableCellsModel(QAbstractTableModel):
    """Rows/columns of one markdown table.

    The model owns the data, the view renders it. Everything that changes the
    shape of the table goes through the begin/endInsert/Remove APIs so the
    view stays in sync, and the marks stay markdown: escaping happens once,
    on the way out, through `silo_table.escape`.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.rows: list[list[str]] = []
        self.aligns: list[str] = []
        self.has_header = True
        #: Reason the last `paste_tsv` was refused, or "" when it was accepted.
        #: The caller uses it to tell the user WHY instead of failing silently.
        self.paste_refusal = ""
        #: Reason the last direct edit was refused, or "" when accepted.
        self.edit_refusal = ""

    # ---- QAbstractTableModel ------------------------------------------
    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else self._width()

    def _width(self) -> int:
        return max([len(r) for r in self.rows] + [len(self.aligns)] + [0])

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        r, c = index.row(), index.column()
        if not (0 <= r < len(self.rows) and 0 <= c < len(self.rows[r])):
            return None
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole):
            return self.rows[r][c]
        if role == Qt.ItemDataRole.FontRole and self.has_header and r == 0:
            # T-1462 Stage 7: row 0 IS the markdown header. It is a normal,
            # editable row (no index offset), so the only thing that tells the
            # user which row the separator line belongs to is its weight.
            f = QFont()
            f.setBold(True)
            return f
        if role == Qt.ItemDataRole.TextAlignmentRole:
            a = self.aligns[c] if c < len(self.aligns) else st.ALIGN_LEFT
            return {
                st.ALIGN_CENTER: int(Qt.AlignmentFlag.AlignCenter
                                     | Qt.AlignmentFlag.AlignVCenter),
                st.ALIGN_RIGHT: int(Qt.AlignmentFlag.AlignRight
                                    | Qt.AlignmentFlag.AlignVCenter),
            }.get(a, int(Qt.AlignmentFlag.AlignLeft
                         | Qt.AlignmentFlag.AlignVCenter))
        return None

    def flags(self, index):
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        return (Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
                | Qt.ItemFlag.ItemIsEditable)

    @staticmethod
    def validate_cell_value(value: str) -> tuple[bool, str]:
        """Validate cell content against the canonical markdown representability contract.

        The canonical markdown table is ONE LINE PER ROW, so a cell with a line
        break cannot be written back losslessly. Refusing before mutation protects
        the document from silent corruption.
        """
        if "\n" in value or "\r" in value:
            return False, (
                "a cell contains a line break, which a markdown table "
                "cannot store without losing the row"
            )
        return True, ""

    def setData(self, index, value, role=Qt.ItemDataRole.EditRole):
        if not index.isValid() or role != Qt.ItemDataRole.EditRole:
            return False
        r, c = index.row(), index.column()
        if not (0 <= r < len(self.rows) and 0 <= c < len(self.rows[r])):
            return False
        text = "" if value is None else (value if isinstance(value, str)
                                         else str(value))
        is_valid, reason = self.validate_cell_value(text)
        if not is_valid:
            self.edit_refusal = reason
            self.paste_refusal = reason
            return False
        self.edit_refusal = ""
        if self.rows[r][c] == text:
            return False
        self.rows[r][c] = text
        self.dataChanged.emit(index, index, [role])
        return True

    @staticmethod
    def column_label(section: int) -> str:
        """Spreadsheet-style column identifier: A, B, ..., Z, AA, AB, ..."""
        i = max(0, int(section))
        label = ""
        while True:
            label = chr(ord("A") + i % 26) + label
            i = i // 26 - 1
            if i < 0:
                return label

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.AccessibleTextRole:
            if orientation == Qt.Orientation.Vertical:
                return str(section + 1)
            return self.column_label(section)
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Vertical:
            return str(section + 1)
        # T-1462 Stage 7: the horizontal label is a COLUMN IDENTIFIER, not the
        # markdown header text. The old code painted `rows[0]` here while row 0
        # was ALSO a normal, editable row, so the header row's text appeared
        # twice — once in the header band and once in the first row — and every
        # cell the user edited there changed a label that looked like chrome.
        # The markdown header row stays a real row (editable, selectable,
        # copied, part of the undo transaction), so the grid needs NO index
        # offset: model row == markdown line, and the header band names columns.
        return self.column_label(section)

    # ---- load / save ---------------------------------------------------
    def load_markdown(self, text, span=None):
        """Fill the model from `text`, owning the table region in it.

        Returns the span that was actually used, so the caller can record the
        same ownership the plain-text path uses.
        """
        from fastprompter.ui import silo_region

        all_lines = (text or "").split("\n")
        if span is None:
            span = silo_region.table_region(all_lines)
        region = all_lines
        if span is not None:
            region = all_lines[span[0]:span[1] + 1]
        table = st.parse(region, 0) if region else None
        if table is None:
            # No recognised table: a fresh empty grid, through the one
            # authority for creating tables rather than a bespoke text sample.
            table = st.new_table(1, 2)
        self.beginResetModel()
        try:
            self.rows = [[st.unescape(c) for c in row]
                         for row in table.normalised()]
            self.aligns = list(table.aligns)
            self.has_header = table.has_header
        finally:
            self.endResetModel()
        return span

    def table_lines(self) -> list[str]:
        """The table as markdown, through the one shared formatter.

        One serialiser for one format: this used to write `---` for a left
        column while the text path wrote `:---`, so a silo edited in both spun
        that difference back and forth on every save. Rendering here also
        aligns the pipes, which is what makes the raw text readable — the only
        view a pasted silo has.
        """
        rows = [[st.escape(c) for c in row] for row in self.rows]
        width = self._width()
        aligns = list(self.aligns) + [st.ALIGN_LEFT] * (width - len(self.aligns))
        return st.render(st.Table(0, 0, rows, aligns,
                                 has_header=self.has_header))

    # ---- shape commands ------------------------------------------------
    def insert_rows(self, row: int, count: int = 1) -> bool:
        if not (0 <= row <= len(self.rows)) or count < 1:
            return False
        # T-1462 Stage 1: the header invariant belongs to the MODEL, not to
        # individual callers. With a header the first row IS the column names
        # and the separator line below it describes THEM; a row inserted at or
        # above row zero pushes the header into the body and the table silently
        # becomes a different table. The widget wrappers guard their own
        # callers, but the context menu calls this model directly, so the
        # refusal lives here and no caller can break the invariant.
        if self.has_header and row < 1:
            return False
        self.beginInsertRows(QModelIndex(), row, row + count - 1)
        try:
            for _ in range(count):
                self.rows.insert(row, [""] * self._width())
        finally:
            self.endInsertRows()
        return True

    def remove_rows(self, row: int, count: int = 1) -> bool:
        if count < 1 or not self.rows:
            return False
        if row < 0:
            row = 0
        # T-1462 Stage 1: row zero is the header when has_header is set, so the
        # removal of row zero AND any batch that spans it is refused here. The
        # check runs BEFORE begin/endRemoveRows, so a rejected mutation leaves
        # the model byte-identical — no rows, no notifications, no alignment
        # drift — and a rejected multi-row batch never deletes its permitted
        # subset silently.
        if self.has_header and row < 1:
            return False
        # A markdown table needs at least a header and one body row; deleting
        # the header is never offered, and emptying the table would make the
        # parse drop the region on the next load.
        floor = 2 if self.has_header else 1
        if len(self.rows) - count < floor:
            return False
        count = min(count, len(self.rows) - row)
        if count < 1 or row + count > len(self.rows):
            return False
        self.beginRemoveRows(QModelIndex(), row, row + count - 1)
        try:
            del self.rows[row:row + count]
        finally:
            self.endRemoveRows()
        return True

    def insert_columns(self, column: int, count: int = 1) -> bool:
        width = self._width()
        if not (0 <= column <= width) or count < 1:
            return False
        self.beginInsertColumns(QModelIndex(), column, column + count - 1)
        try:
            for row in self.rows:
                row[column:column] = [""] * count
            self.aligns[column:column] = [st.ALIGN_LEFT] * count
        finally:
            self.endInsertColumns()
        return True

    def remove_columns(self, column: int, count: int = 1) -> bool:
        if count < 1 or not self.rows:
            return False
        if column < 0:
            column = 0
        width = self._width()
        if width - count < 1:
            return False
        count = min(count, width - column)
        if count < 1:
            return False
        self.beginRemoveColumns(QModelIndex(), column, column + count - 1)
        try:
            for row in self.rows:
                del row[column:column + count]
            del self.aligns[column:column + count]
        finally:
            self.endRemoveColumns()
        return True

    def set_alignment(self, column: int, align: str) -> bool:
        """Alignment is a COLUMN property, because markdown says it once."""
        if not (0 <= column < self._width()) or align not in (
                st.ALIGN_LEFT, st.ALIGN_CENTER, st.ALIGN_RIGHT):
            return False
        self.aligns[column] = align
        self.headerDataChanged.emit(Qt.Orientation.Horizontal, column, column)
        self.layoutChanged.emit()
        return True

    # ---- moves (T-1457 Stage 3) ------------------------------------------
    # A move is a swap of two adjacent rows/columns. It is a MODEL operation
    # so the ONE implementation is shared by the keyboard path and the context
    # menu, and so the view is told (layoutChanged) instead of being left to
    # notice a silent in-place mutation.
    def move_row(self, row: int, offset: int) -> bool:
        """Swap ``row`` with its neighbour ``offset`` (-1 up, +1 down)."""
        if offset not in (-1, 1):
            return False
        # Row 0 is the header when has_header is set, so it is neither moved
        # nor moved past: the header names the columns and must stay first.
        if self.has_header and min(row, row + offset) < 1:
            return False
        if not (0 <= row < len(self.rows)) \
                or not (0 <= row + offset < len(self.rows)):
            return False
        target = row + offset
        self.rows[row], self.rows[target] = self.rows[target], self.rows[row]
        self.layoutChanged.emit()
        return True

    def move_column(self, column: int, offset: int) -> bool:
        """Swap ``column`` with its neighbour ``offset`` (-1 left, +1 right)."""
        if offset not in (-1, 1):
            return False
        width = self._width()
        if not (0 <= column < width) or not (0 <= column + offset < width):
            return False
        target = column + offset
        for row in self.rows:
            if column < len(row) and target < len(row):
                row[column], row[target] = row[target], row[column]
        if column < len(self.aligns) and target < len(self.aligns):
            self.aligns[column], self.aligns[target] = \
                self.aligns[target], self.aligns[column]
        self.layoutChanged.emit()
        return True

    # ---- clipboard safety budget (T-1462 Stage 4) ------------------------
    _PASTE_MAX_ROWS = 10_000
    _PASTE_MAX_COLS = 2_000
    #: Raw clipboard ceiling, checked with `len()` BEFORE the payload is split.
    #: A 100 MB clipboard is refused without allocating the line list, let
    #: alone the per-cell grid — the parse itself is the memory hazard.
    _PASTE_MAX_CHARS = 4_000_000
    #: Ceiling on the TOTAL cells the table would hold AFTER the paste, so the
    #: bound is the resulting footprint (existing shape + growth), not one axis
    #: at a time: a 2000-column paste into a 2000-column table is 4M cells even
    #: though each axis is individually legal.
    _PASTE_MAX_CELLS = 4_000_000

    # ---- rectangular clipboard ----------------------------------------
    def clipboard_range(self, indexes) -> str:
        """TSV for the rectangular bounding box of `indexes`.

        Tab-separated is the only interchange every spreadsheet and every
        shell agrees on, and it is all this table needs.  A cell that itself
        contains a tab, a line break or a quote is quoted (RFC-4180 field
        quoting with a tab delimiter), which is exactly the convention Excel
        writes and reads, so a copy from here and a paste into Excel describe
        the same rectangle -- including a literal tab inside one cell.
        """
        cells = [i for i in indexes if i.isValid()]
        if not cells:
            return ""
        r0 = min(i.row() for i in cells)
        r1 = max(i.row() for i in cells)
        c0 = min(i.column() for i in cells)
        c1 = max(i.column() for i in cells)
        rows = []
        for r in range(r0, r1 + 1):
            row = self.rows[r] if r < len(self.rows) else []
            rows.append([row[c] if c < len(row) else ""
                         for c in range(c0, c1 + 1)])
        return clipboard_tsv.encode_grid(rows)

    def paste_tsv(self, top_row: int, left_col: int, text: str) -> tuple[int, int]:
        """Write a rectangular TSV payload at (top_row, left_col).

        The table GROWS to fit the payload: the alternative is dropping what
        the user pasted, which is never acceptable. Returns
        (rows_written, columns_written), or (0, 0) when the paste is refused.

        T-1462 Stage 4: the payload is bounded BEFORE it is parsed, because the
        parse is the hazard — a 100k x 100k clipboard is 10^10 cell strings,
        which OOMs the process before any ceiling on the RESULT could run. The
        checks are cheapest-first: the raw character count is O(1), the row and
        column counts are one incremental pass with no per-cell list, and only
        a payload that passes all three is materialised into a grid.

        T-1457 Stage 2: the payload is parsed by the shared clipboard codec,
        which honours RFC-4180 quoted fields, so a tab, a line break or a
        quote INSIDE a cell survives a copy from a spreadsheet.  A cell that
        really holds a line break is refused: the canonical markdown table
        format is one line per row, so storing it would silently corrupt the
        document.

        A refusal is TOTAL and side-effect free: no rows, no columns, no
        alignment, no `dataChanged`. `self.paste_refusal` carries the reason for
        the caller's feedback, and stays "" on success.
        """
        self.paste_refusal = ""
        payload = text or ""
        if not payload:
            return 0, 0
        if top_row < 0 or left_col < 0:
            self.paste_refusal = (
                f"Invalid paste destination ({top_row}, {left_col})")
            return 0, 0
        # 1. Byte/character budget BEFORE parsing. `len()` is O(1) and the
        #    giant clipboard never reaches the scanner.
        if len(payload) > self._PASTE_MAX_CHARS:
            self.paste_refusal = (
                f"Clipboard too large to paste "
                f"({len(payload)} characters, limit {self._PASTE_MAX_CHARS})")
            return 0, 0

        # 2. Count rows and columns INCREMENTALLY — one cheap pass, no
        #    per-cell list — so an over-wide or over-tall payload is refused
        #    before a single cell is allocated. The count is quote-aware and
        #    comes from the same state machine that will materialise the grid,
        #    so the two can never disagree.
        n_rows, n_cols = clipboard_tsv.scan_shape(payload)
        if not n_rows or not n_cols:
            return 0, 0
        need_rows = top_row + n_rows
        need_cols = left_col + n_cols

        # 3. Total resulting-cell budget, including the existing table's
        #    dimensions and the destination offset.
        total_rows = max(len(self.rows), need_rows, 0)
        total_cols = max(self._width(), need_cols, 0)
        if (n_rows > self._PASTE_MAX_ROWS or n_cols > self._PASTE_MAX_COLS
                or total_rows * total_cols > self._PASTE_MAX_CELLS):
            self.paste_refusal = (
                f"Paste refused: {n_rows}x{n_cols} at ({top_row}, {left_col}) "
                f"would exceed the table budget")
            return 0, 0

        # Only now is the payload materialised: every ceiling above passed.
        grid = clipboard_tsv.decode_grid(payload)
        # 4. Verify materialized shape matches preflight scan shape.
        #    Any disagreement fails closed without mutating the model.
        mat_rows = len(grid)
        mat_cols = max((len(r) for r in grid), default=0)
        if mat_rows != n_rows or mat_cols != n_cols:
            self.paste_refusal = (
                f"Paste refused: parser shape divergence "
                f"(scanned {n_rows}x{n_cols}, materialized {mat_rows}x{mat_cols})")
            return 0, 0

        # 5. The canonical markdown table is ONE LINE PER ROW, so a cell with
        #    a line break cannot be written back losslessly. Refusing is the
        #    only honest answer; storing it would corrupt the silo text on the
        #    next save.
        for row in grid:
            for cell in row:
                is_valid, reason = self.validate_cell_value(cell)
                if not is_valid:
                    self.paste_refusal = f"Paste refused: {reason}"
                    self.edit_refusal = self.paste_refusal
                    return 0, 0

        add_rows = max(0, need_rows - len(self.rows))
        add_cols = max(0, need_cols - self._width())
        if add_rows > 0:
            self.insert_rows(len(self.rows), add_rows)
        if add_cols > 0:
            self.insert_columns(self._width(), add_cols)

        for r, cells in enumerate(grid):
            row_idx = top_row + r
            for c, val in enumerate(cells):
                col_idx = left_col + c
                if row_idx < len(self.rows):
                    while col_idx >= len(self.rows[row_idx]):
                        self.rows[row_idx].append("")
                    self.rows[row_idx][col_idx] = val
        rows_written = mat_rows
        cols_written = mat_cols
        if rows_written > 0 and cols_written > 0:
            top = self.index(top_row, left_col)
            bottom = self.index(top_row + rows_written - 1,
                                left_col + cols_written - 1)
            if top.isValid() and bottom.isValid():
                self.dataChanged.emit(top, bottom)
        return rows_written, cols_written
