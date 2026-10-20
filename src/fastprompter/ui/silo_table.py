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


def fenced_mask(lines: list[str]) -> list[bool]:
    """True where a line sits inside a ``` or ~~~ code fence.

    A pipe run inside a fence is sample text, not a table: claiming it as one
    would let the visual widget rewrite the user's code.
    """
    mask = [False] * len(lines)
    fence = None
    for i, raw in enumerate(lines):
        s = raw.lstrip()
        if fence is None:
            if s.startswith("```") or s.startswith("~~~"):
                fence = s[:3]
            continue
        if s.startswith(fence) and not s.strip().strip(fence).strip():
            fence = None
            continue
        mask[i] = True
    return mask


#: Boundary whitespace is serialized as numeric character references, not as
#: backslash escapes: no Markdown engine treats backslash-before-space as an
#: escape (the backslash survives as literal text and GFM cell trimming drops
#: the whitespace after it), while every engine decodes `&#32;`/`&#9;` AFTER
#: cell trimming, so the logical value survives an external consumer.
_BOUNDARY_ENTITIES = {" ": "&#32;", "\t": "&#9;"}


def escape(text: str) -> str:
    """Make `text` safe to place inside a markdown table cell.

    Backslash and pipe are escaped (`\\\\`, `\\|`) — both are real GFM cell
    escapes. Leading and trailing whitespace characters (spaces and tabs)
    become numeric character references (`&#32;`, `&#9;`): Markdown table
    trimming strips cell-boundary whitespace before inline parsing, and only
    an entity survives that trim and still decodes to the original character
    in every standard consumer. A literal `&` is escaped to `&amp;` so that
    user-entered entity-like text (`&#32;`, `&copy;`) is not itself decoded
    into whitespace or symbols on the way out.
    """
    if not text:
        return ""
    l_idx = 0
    while l_idx < len(text) and text[l_idx] in " \t":
        l_idx += 1
    if l_idx == len(text):
        return "".join(_BOUNDARY_ENTITIES[ch] for ch in text)

    r_idx = len(text)
    while r_idx > l_idx and text[r_idx - 1] in " \t":
        r_idx -= 1

    lead = "".join(_BOUNDARY_ENTITIES[ch] for ch in text[:l_idx])
    middle = (text[l_idx:r_idx]
              .replace("&", "&amp;")
              .replace("\\", "\\\\")
              .replace("|", "\\|"))
    trail = "".join(_BOUNDARY_ENTITIES[ch] for ch in text[r_idx:])
    return lead + middle + trail


def unescape(text: str) -> str:
    """Inverse of `escape`: the text a user typed, for display and editing.

    Left to right: `\\\\` is a literal backslash, `\\|` is a literal pipe,
    `&amp;`/`&#32;`/`&#9;` decode to their characters, and backslash-escaped
    boundary whitespace from T-1464-era documents (`\\ `, `\\`+tab) decodes
    too, so saved documents keep their logical values across the format
    change. Every other backslash and ampersand sequence stays itself —
    literal entity-like text is never decoded beyond the forms `escape`
    itself emits.
    """
    out: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch == "\\" and i + 1 < n and text[i + 1] in "\\| \t":
            out.append(text[i + 1])
            i += 2
            continue
        if ch == "&":
            for entity, value in (("&amp;", "&"), ("&#32;", " "), ("&#9;", "\t")):
                if text.startswith(entity, i):
                    out.append(value)
                    i += len(entity)
                    break
            else:
                out.append(ch)
                i += 1
            continue
        out.append(ch)
        i += 1
    return "".join(out)


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
    """Cells of a row, pipes and outer formatting padding removed.

    An escaped pipe (`\\|`) is content, not a boundary. An escaped space or tab
    (`\\ `) is content, not alignment padding. Outer unescaped spaces and tabs
    are formatting padding and are stripped.
    """
    s = text.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        # Trailing pipe is a border only when preceded by an even number of backslashes
        k = len(s) - 2
        bs_count = 0
        while k >= 0 and s[k] == "\\":
            bs_count += 1
            k -= 1
        if bs_count % 2 == 0:
            s = s[:-1]

    cells: list[str] = []
    current_items: list[tuple[str, bool]] = []
    escaped = False

    def finish_cell():
        start = 0
        while start < len(current_items) and (not current_items[start][1]) and current_items[start][0] in " \t":
            start += 1
        end = len(current_items)
        while end > start and (not current_items[end - 1][1]) and current_items[end - 1][0] in " \t":
            end -= 1
        cell_parts = []
        for ch, is_esc in current_items[start:end]:
            if is_esc:
                cell_parts.append("\\" + ch)
            else:
                cell_parts.append(ch)
        cells.append("".join(cell_parts))

    for ch in s:
        if escaped:
            current_items.append((ch, True))
            escaped = False
            continue
        if ch == "\\":
            escaped = True
            continue
        if ch == "|":
            finish_cell()
            current_items = []
            continue
        current_items.append((ch, False))

    if escaped:
        current_items.append(("\\", False))
    finish_cell()
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


def parse(lines: list[str], index: int, mask: list[bool] | None = None) -> Table | None:
    """The table containing line `index`, or None if that line is not in one.

    A separator line belongs to the table above it, which is what lets Tab
    work when the caret happens to be sitting on the dashes.

    Two things make this strict rather than "any run of pipe lines": the run
    must be OUTSIDE a code fence (fenced pipes are the user's sample text),
    and it must contain a separator row (a pipe run with no `|---|` is prose
    that happens to hold pipes, and rewriting it would be data loss).
    """
    if not (0 <= index < len(lines)) or not is_table_row(lines[index]):
        return None
    if mask is None:
        mask = fenced_mask(lines)
    if mask[index]:
        return None
    first = index
    while (first > 0 and is_table_row(lines[first - 1])
           and not mask[first - 1]):
        first -= 1
    last = index
    while (last + 1 < len(lines) and is_table_row(lines[last + 1])
           and not mask[last + 1]):
        last += 1

    body: list[list[str]] = []
    aligns_list: list[str] = []
    has_header = False
    separator_seen = False
    for i in range(first, last + 1):
        cells = split_row(lines[i])
        if is_separator_row(lines[i]) and not aligns_list:
            aligns_list = [align_of(c) for c in cells]
            has_header = i > first
            separator_seen = True
            continue
        body.append(cells)
    if not separator_seen:
        return None
    width = max((len(r) for r in body), default=0)
    if len(aligns_list) < width:
        aligns_list += [ALIGN_LEFT] * (width - len(aligns_list))
    return Table(first, last, body, aligns_list, has_header)


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

    lines: list[str] = []
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
    trail = 0
    k = len(slot) - 1
    while k >= lead and slot[k] in " \t":
        p = k - 1
        bs_count = 0
        while p >= 0 and slot[p] == "\\":
            bs_count += 1
            p -= 1
        if bs_count % 2 == 1:
            break
        trail += 1
        k -= 1
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
    """A fresh table with an empty header row and an empty body.

    The old insert wrote "Row 1" into every cell, which is text the user then
    has to delete in every single one. The header used to carry "Column N"
    placeholders, and the QTableView already paints A/B/C there, so those
    labels were document content duplicating a header the view owns.
    """
    columns = max(1, columns)
    rows = max(0, rows)
    body = []
    if header:
        body.append(blank_row(columns))
    body.extend(blank_row(columns) for _ in range(rows))
    return Table(0, 0, body, [ALIGN_LEFT] * columns, header)


# The shape a NEW table gets when there is no usable saved template, and the
# answer to malformed template data.
FACTORY_COLUMNS = 7
FACTORY_VISIBLE_ROWS = 10
# Bounds: a corrupt profile must never be able to ask for an unbounded grid.
MAX_COLUMNS = 200
MAX_VISIBLE_ROWS = 500


def _bounded(value, ceiling):
    """`value` as an int within 1..ceiling, or None when it is not one."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if isinstance(value, float) and not value.is_integer():
        return None
    value = int(value)
    return value if 1 <= value <= ceiling else None


def template_shape(template):
    """(columns, visible_rows) of a stored ``table_default_layout`` template.

    `visible_rows` counts the header row, so the body has `visible_rows - 1`
    rows. Malformed data falls back to the factory shape instead of raising:
    a corrupt profile must not stop the user creating a table.
    """
    if isinstance(template, str):
        import json
        try:
            template = json.loads(template)
        except ValueError:
            template = None
    if not isinstance(template, dict) or template.get("version") != 1:
        return FACTORY_COLUMNS, FACTORY_VISIBLE_ROWS
    columns = _bounded(template.get("columns"), MAX_COLUMNS)
    visible = _bounded(template.get("visible_rows"), MAX_VISIBLE_ROWS)
    if columns is None:
        widths = template.get("col_widths")
        if isinstance(widths, list) and 1 <= len(widths) <= MAX_COLUMNS:
            columns = len(widths)
    if visible is None:
        heights = template.get("row_heights")
        if isinstance(heights, list) and 1 <= len(heights) <= MAX_VISIBLE_ROWS:
            visible = len(heights)
    return (columns if columns is not None else FACTORY_COLUMNS,
            visible if visible is not None else FACTORY_VISIBLE_ROWS)


def parse_default_layout(template: dict | str | None) -> dict | None:
    """Normalize a stored ``table_default_layout`` into a presentation dict (T-1466 / T-1468).

    Returns a normalized dict with version, columns, visible_rows, cols, rows,
    manual_cols, manual_rows, and word_wrap; or None if missing or invalid.
    """
    if isinstance(template, str):
        import json
        try:
            template = json.loads(template)
        except ValueError:
            return None
    if not isinstance(template, dict) or template.get("version") != 1:
        return None
    columns, visible_rows = template_shape(template)
    cols = template.get("col_widths")
    rows = template.get("row_heights")
    manual_cols = template.get("manual_cols")
    manual_rows = template.get("manual_rows")
    return {
        "version": 1,
        "columns": columns,
        "visible_rows": visible_rows,
        "cols": cols if isinstance(cols, list) and len(cols) == columns else [],
        "rows": rows if isinstance(rows, list) and len(rows) == visible_rows else [],
        "manual_cols": manual_cols if isinstance(manual_cols, list) else [],
        "manual_rows": manual_rows if isinstance(manual_rows, list) else [],
        "word_wrap": template.get("word_wrap") in (True, "True"),
    }


def default_table(template=None) -> Table:
    """A new table in the user's saved shape, every logical cell empty.

    `template` is the ``table_default_layout`` setting (dict, or its JSON
    text); its ``columns``/``visible_rows`` decide the shape and the factory
    7x10 is the fallback for a missing or malformed template. The header row
    holds EMPTY cells -- QTableView already paints A/B/C there through
    ``headerData()`` -- so the document never repeats its own column labels
    as cell content.
    """
    columns, visible_rows = template_shape(template)
    body = [blank_row(columns)]
    body.extend(blank_row(columns) for _ in range(visible_rows - 1))
    return Table(0, 0, body, [ALIGN_LEFT] * columns, True)
