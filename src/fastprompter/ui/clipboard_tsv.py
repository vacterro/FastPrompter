"""One clipboard TSV codec for the table grid (T-1457 Stage 2).

Tab-separated values is the only interchange every spreadsheet and every
shell agrees on, but plain TSV has no way to carry a tab, a line break or a
quotation mark INSIDE a cell.  Excel and every other spreadsheet therefore
use the RFC-4180 quoting convention with a tab delimiter: a field whose text
contains a quote, a tab or a line break is wrapped in double quotes, and each
quote inside it is doubled.  ``"alpha<TAB>beta"<TAB>X`` is TWO cells, and the
first one contains a literal tab.

Both directions of the table clipboard go through this module, so a copy can
never produce something the paste reads differently.

Why the parse is not ``str.split``: a quoted field may contain the delimiter
and the row separator, so the payload is a single pass over characters with a
quoting state.  The pass is also the budget guard -- :func:`scan_shape`
counts rows and columns without allocating a single cell string, so an
oversized clipboard is refused before the grid is materialised.

The decoder is deliberately LENIENT about a leading quote that is not a
well-formed quoted field (a payload from a plain text editor whose cell text
happens to start with a quote): such a field is read literally, exactly as
the pre-T-1457 split did, so an ordinary paste is never refused and never
silently altered.  A well-formed quoted field is always decoded, and this
module's encoder always emits well-formed output, so a copy/paste round-trip
is exact.
"""

from __future__ import annotations

QUOTE = '"'
DELIMITER = "\t"


def encode_cell(cell) -> str:
    """One cell as a TSV field: quoted only when quoting is required."""
    text = "" if cell is None else str(cell)
    if any(ch in text for ch in (QUOTE, DELIMITER, "\n", "\r")):
        return QUOTE + text.replace(QUOTE, QUOTE * 2) + QUOTE
    return text


def encode_grid(rows) -> str:
    """A rectangular grid as a TSV payload, one row per line."""
    if not rows:
        return ""
    encoded_rows = []
    for row in rows:
        if len(row) == 1 and (row[0] == "" or row[0] is None):
            encoded_rows.append(QUOTE * 2)
        else:
            encoded_rows.append(DELIMITER.join(encode_cell(c) for c in row))
    return "\n".join(encoded_rows)


def _quoted_end(payload: str, start: int) -> int | None:
    """Index of the closing quote of a well-formed quoted field, or None.

    ``None`` means "not a quoted field": no closing quote before the end, or
    a closing quote followed by something other than a delimiter, a line
    break or the end of the payload.  The caller then reads the field
    literally, which is what keeps a stray quote harmless.
    """
    i = start + 1
    n = len(payload)
    while i < n:
        ch = payload[i]
        if ch == QUOTE:
            if i + 1 < n and payload[i + 1] == QUOTE:
                i += 2
                continue
            nxt = payload[i + 1] if i + 1 < n else ""
            return i if nxt in ("", DELIMITER, "\r", "\n") else None
        i += 1
    return None


def _parse(payload: str, collect: bool):
    """Single pass over ``payload``.

    Returns ``(grid, n_rows, n_cols)``.  ``grid`` is None unless ``collect``
    is true; the row/column counts are produced by the SAME state machine, so
    a cheap shape check and the materialised grid can never disagree.
    """
    if not payload:
        return ([] if collect else None), 0, 0

    grid = [] if collect else None
    row: list[str] = []
    field: list[str] = []
    n_rows = 1
    n_cols = 1
    trailing_empty = 0
    # Per-row state, kept identically in both modes: how many delimiters this
    # row has seen, and whether ANY character (or quoted body) landed in it.
    fields_in_row = 0
    row_any_char = False
    field_empty = True
    i = 0
    n = len(payload)

    def end_row() -> None:
        nonlocal n_rows, n_cols, trailing_empty, fields_in_row, row_any_char, field_empty
        n_cols = max(n_cols, fields_in_row + 1)
        if collect:
            row.append("".join(field))
            grid.append(row[:])
            row.clear()
            field.clear()
        field_empty = True
        # A row is "empty" only when it is exactly one zero-length field.  The
        # pre-T-1457 split-then-pop behaviour dropped every trailing blank
        # line, and a payload whose last line is blank must still read as one
        # row fewer.
        trailing_empty = trailing_empty + 1 if not row_any_char \
            and fields_in_row == 0 else 0
        fields_in_row = 0
        row_any_char = False
        n_rows += 1

    while i < n:
        ch = payload[i]
        # A quote starts a quoted field only at the very start of a field;
        # anywhere else it is ordinary cell text.
        if ch == QUOTE and field_empty:
            end = _quoted_end(payload, i)
            if end is not None:
                if collect:
                    field.append(payload[i + 1:end].replace(QUOTE * 2, QUOTE))
                row_any_char = True
                field_empty = False
                # The scanner steps over the whole field body; the terminator
                # that follows is handled by the main loop next iteration.
                i = end + 1
                continue
        if ch == DELIMITER:
            if collect:
                row.append("".join(field))
                field.clear()
            field_empty = True
            fields_in_row += 1
            i += 1
            continue
        if ch in "\r\n":
            if ch == "\r" and i + 1 < n and payload[i + 1] == "\n":
                i += 1
            end_row()
            i += 1
            continue
        if collect:
            field.append(ch)
        row_any_char = True
        field_empty = False
        i += 1

    # Final row: the same evaluation, without counting a new row for it.
    n_cols = max(n_cols, fields_in_row + 1)
    if collect:
        row.append("".join(field))
        grid.append(row)
    if not row_any_char and fields_in_row == 0:
        trailing_empty += 1
    else:
        trailing_empty = 0

    if collect:
        for _ in range(trailing_empty):
            if grid:
                grid.pop()
    final_rows = max(0, n_rows - trailing_empty)
    final_cols = n_cols if final_rows > 0 else 0
    return grid, final_rows, final_cols


def scan_shape(payload: str) -> tuple[int, int]:
    """``(rows, columns)`` of a payload, without materialising any cell."""
    _, rows, cols = _parse(payload, collect=False)
    return rows, cols


def decode_grid(payload: str) -> list[list[str]]:
    """The rectangular grid a payload describes.

    Raises nothing: a payload this module's encoder produced always decodes
    back to the grid it was encoded from.
    """
    grid, _, _ = _parse(payload, collect=True)
    return grid


def has_multiline_cell(grid) -> bool:
    """True when any cell holds a line break.

    The canonical markdown table format is ONE LINE PER ROW, so a cell
    containing a line break cannot be written back losslessly: the caller
    must refuse the payload instead of silently corrupting the document.
    """
    for row in grid:
        for cell in row:
            if "\n" in cell or "\r" in cell:
                return True
    return False
