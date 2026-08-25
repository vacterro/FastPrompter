"""SiloTable — markdown tables you can actually edit.

The silo is stored as PLAIN TEXT (that is what the DB holds, what the disk
mirror writes and what a paste into an agent needs), so a real QTextTable is
not an option: it would not survive the first save. The markdown stays the
source of truth and the editing behaviour is built on top of it — Tab walks
the cells, Enter adds a row, the pipes are re-aligned as you leave a row.

Everything here is pure text in, text out. No Qt, so it is testable without
a window, and the editor holds the only knowledge about cursors.
"""

from __future__ import annotations

from dataclasses import dataclass, field

ALIGN_LEFT, ALIGN_CENTER, ALIGN_RIGHT = "left", "center", "right"


def is_table_row(text: str) -> bool:
    """A markdown table row: starts and ends with a pipe once stripped."""
    s = text.strip()
    return len(s) >= 2 and s.startswith("|") and s.endswith("|")


def is_separator_row(text: str) -> bool:
    """The `| :--- | ---: |` line under the header."""
    if not is_table_row(text):
        return False
    cells = split_row(text)
    if not cells:
        return False
    for cell in cells:
        c = cell.strip()
        if not c:
            return False
        if set(c) - set(":-"):
            return False
        if "-" not in c:
            return False
    return True


def split_row(text: str) -> list[str]:
    """Cells of a row, pipes and outer padding removed.

    An escaped pipe (`\\|`) is content, not a boundary — a table holding a
    shell command or a regex alternation is not an exotic case.
    """
    s = text.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|") and not s.endswith("\\|"):
        s = s[:-1]
    cells, current, escaped = [], [], False
    for ch in s:
        if escaped:
            current.append(ch)
            escaped = False
            continue
        if ch == "\\":
            current.append(ch)
            escaped = True
            continue
        if ch == "|":
            cells.append("".join(current).strip())
            current = []
            continue
        current.append(ch)
    cells.append("".join(current).strip())
    return cells


def align_of(spec: str) -> str:
    """Alignment encoded by one separator cell."""
    s = spec.strip()
    if s.startswith(":") and s.endswith(":"):
        return ALIGN_CENTER
    if s.endswith(":"):
        return ALIGN_RIGHT
    return ALIGN_LEFT


def spec_of(align: str, width: int) -> str:
    """One separator cell for this alignment, padded to `width`."""
    width = max(3, width)
    if align == ALIGN_CENTER:
        return ":" + "-" * (width - 2) + ":"
    if align == ALIGN_RIGHT:
        return "-" * (width - 1) + ":"
    return ":" + "-" * (width - 1)


@dataclass
class Table:
    """A parsed table: the rows, the alignments, and where it sat."""

    first_block: int
    last_block: int
    rows: list[list[str]] = field(default_factory=list)
    aligns: list[str] = field(default_factory=list)
    has_header: bool = True

    @property
    def columns(self) -> int:
        return max((len(r) for r in self.rows), default=0)

    def normalised(self) -> list[list[str]]:
        """Rows padded to the same width, so a ragged table still renders."""
        width = max(self.columns, len(self.aligns))
        return [list(r) + [""] * (width - len(r)) for r in self.rows]


def parse(lines: list[str], index: int) -> Table | None:
    """The table containing line `index`, or None if that line is not in one.

    A separator line belongs to the table above it, which is what lets Tab
    work when the caret happens to be sitting on the dashes.
    """
    if not (0 <= index < len(lines)) or not is_table_row(lines[index]):
        return None
    first = index
    while first > 0 and is_table_row(lines[first - 1]):
        first -= 1
    last = index
    while last + 1 < len(lines) and is_table_row(lines[last + 1]):
        last += 1

    body, aligns, has_header = [], [], False
    for i in range(first, last + 1):
        cells = split_row(lines[i])
        if is_separator_row(lines[i]) and not aligns:
            aligns = [align_of(c) for c in cells]
            has_header = i > first
            continue
        body.append(cells)
    width = max((len(r) for r in body), default=0)
    if not aligns:
        aligns = [ALIGN_LEFT] * width
    elif len(aligns) < width:
        aligns += [ALIGN_LEFT] * (width - len(aligns))
    return Table(first, last, body, aligns, has_header)


def render(table: Table) -> list[str]:
    """Markdown lines for this table, every pipe column-aligned.

    Alignment is cosmetic to a parser and everything to a human reading the
    raw text — which, in a tool whose whole point is pasting raw text, is the
    only view that exists.
    """
    rows = table.normalised()
    width = max(len(table.aligns), max((len(r) for r in rows), default=0))
    aligns = list(table.aligns) + [ALIGN_LEFT] * (width - len(table.aligns))
    widths = [3] * width
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(cell))

    def line(cells):
        out = []
        for i in range(width):
            cell = cells[i] if i < len(cells) else ""
            if aligns[i] == ALIGN_RIGHT:
                out.append(cell.rjust(widths[i]))
            elif aligns[i] == ALIGN_CENTER:
                out.append(cell.center(widths[i]))
            else:
                out.append(cell.ljust(widths[i]))
        return "| " + " | ".join(out) + " |"

    lines = []
    if not rows:
        return lines
    start = 0
    if table.has_header:
        lines.append(line(rows[0]))
        start = 1
    lines.append("| " + " | ".join(
        spec_of(aligns[i], widths[i]) for i in range(width)) + " |")
    for row in rows[start:]:
        lines.append(line(row))
    return lines


def cell_index(text: str, column: int) -> int:
    """Which cell a caret at character offset `column` sits in."""
    s = text
    lead = len(s) - len(s.lstrip())
    idx, escaped = 0, False
    seen_first_pipe = False
    for pos, ch in enumerate(s):
        if pos >= column:
            break
        if escaped:
            escaped = False
            continue
        if ch == "\\":
            escaped = True
            continue
        if ch == "|":
            if not seen_first_pipe and pos <= lead:
                seen_first_pipe = True
                continue
            idx += 1
    cells = split_row(text)
    return max(0, min(idx, max(0, len(cells) - 1)))


def cell_span(text: str, index: int) -> tuple[int, int]:
    """(start, end) character offsets of cell `index`'s CONTENT in `text`.

    Content, not the padded slot: Tab landing on a cell should select the
    word in it, and typing should replace the word rather than the spaces
    around it.
    """
    bounds, escaped = [], False
    for pos, ch in enumerate(text):
        if escaped:
            escaped = False
            continue
        if ch == "\\":
            escaped = True
            continue
        if ch == "|":
            bounds.append(pos)
    if len(bounds) < 2:
        return (0, len(text))
    index = max(0, min(index, len(bounds) - 2))
    raw_start, raw_end = bounds[index] + 1, bounds[index + 1]
    slot = text[raw_start:raw_end]
    if not slot.strip():
        # An empty cell has no content to select, so both ends collapse onto
        # one caret position inside the padding. Deriving it from lstrip and
        # rstrip separately gave start > end here (9, 5) and the caller then
        # selected backwards across the pipe.
        return (raw_start + min(1, len(slot)),) * 2
    lead = len(slot) - len(slot.lstrip())
    trail = len(slot) - len(slot.rstrip())
    return (raw_start + lead, raw_end - trail)


def blank_row(columns: int) -> list[str]:
    return [""] * max(1, columns)


def with_row(table: Table, after: int) -> Table:
    """Copy with an empty row inserted after body row `after`."""
    rows = [list(r) for r in table.normalised()]
    at = max(0, min(after + 1, len(rows)))
    rows.insert(at, blank_row(max(table.columns, len(table.aligns))))
    return Table(table.first_block, table.last_block, rows,
                 list(table.aligns), table.has_header)


def without_row(table: Table, index: int) -> Table:
    rows = [list(r) for r in table.normalised()]
    # never delete the header: a table whose header row is gone reads as a
    # different table, and the separator would then describe nothing
    floor = 1 if table.has_header else 0
    if len(rows) <= floor + 1 or not (floor <= index < len(rows)):
        return table
    rows.pop(index)
    return Table(table.first_block, table.last_block, rows,
                 list(table.aligns), table.has_header)


def with_column(table: Table, after: int) -> Table:
    rows = [list(r) for r in table.normalised()]
    at = max(0, min(after + 1, table.columns))
    for row in rows:
        row.insert(at, "")
    aligns = list(table.aligns)
    aligns.insert(min(at, len(aligns)), ALIGN_LEFT)
    return Table(table.first_block, table.last_block, rows, aligns,
                 table.has_header)


def without_column(table: Table, index: int) -> Table:
    if table.columns <= 1 or not (0 <= index < table.columns):
        return table
    rows = [list(r) for r in table.normalised()]
    for row in rows:
        del row[index]
    aligns = list(table.aligns)
    if index < len(aligns):
        del aligns[index]
    return Table(table.first_block, table.last_block, rows, aligns,
                 table.has_header)


def set_align(table: Table, index: int, align: str) -> Table:
    aligns = list(table.aligns)
    if 0 <= index < len(aligns):
        aligns[index] = align
    return Table(table.first_block, table.last_block,
                 [list(r) for r in table.normalised()], aligns,
                 table.has_header)


def new_table(rows: int, columns: int, header: bool = True) -> Table:
    """A fresh table, header filled with placeholders and the body empty.

    The old insert wrote "Row 1" into every cell, which is text the user then
    has to delete in every single one.
    """
    columns = max(1, columns)
    rows = max(1, rows)
    body = []
    if header:
        body.append([f"Column {i + 1}" for i in range(columns)])
    body.extend(blank_row(columns) for _ in range(rows))
    return Table(0, 0, body, [ALIGN_LEFT] * columns, header)
