"""Which PART of a silo a visual widget owns.

A Table or Kanban silo is still a markdown silo: it can carry a title, notes
above the board, a footer below it. The visual widgets serialise themselves
back over the silo, so unless they know where they begin and end they take
the rest of the text with them.

Measured before this existed:

    silo:  "# Weekly report / Notes... / | Name | Qty | / ... / And a
            paragraph AFTER the table."
    after one edit in the table widget:  "| # Weekly report |\\n| --- |"

— the heading was parsed as the header row, the blank line ended the table,
and the serialise wrote two lines over the whole silo. The board was less
dramatic and equally wrong: title, goal line and footer all gone.

So the widgets ask here for their region, keep the lines around it, and
splice. The spans come from the same parsers the plain-text editing path
uses (`silo_table`, `silo_kanban`), which is what keeps the two paths from
drifting into disagreeing about what a table is.
"""

from __future__ import annotations

from fastprompter.ui import silo_kanban as sk
from fastprompter.ui import silo_table as st


def table_region(lines: list[str]) -> tuple[int, int] | None:
    """(first, last) of the first markdown table, or None if there is none."""
    for i, line in enumerate(lines):
        if st.is_table_row(line):
            table = st.parse(lines, i)
            if table is not None:
                return table.first_block, table.last_block
    return None


def board_region(lines: list[str]) -> tuple[int, int] | None:
    """(first, last) of the kanban board, or None if there is none."""
    return sk.board_span(lines)


def split(lines: list[str], span: tuple[int, int] | None):
    """(prefix, region, suffix) for a span. No span -> everything is prefix.

    A None span deliberately puts the whole silo in the PREFIX rather than in
    the region: text that was not recognised as a table or a board is text
    the widget must not claim, and appending after it is the only safe move.
    """
    if span is None:
        return list(lines), [], []
    first, last = span
    first = max(0, min(first, len(lines)))
    last = max(first - 1, min(last, len(lines) - 1))
    return lines[:first], lines[first:last + 1], lines[last + 1:]


def splice(prefix: list[str], region: list[str], suffix: list[str]) -> str:
    """Rebuild the silo text, keeping one blank line between the parts.

    Without the separators a heading would end up glued to the first table
    row, which is a different document to a markdown parser.
    """
    out: list[str] = []
    if prefix:
        out.extend(prefix)
        while out and not out[-1].strip():
            out.pop()
        if out and region:
            out.append("")
    out.extend(region)
    if suffix:
        tail = list(suffix)
        while tail and not tail[0].strip():
            tail.pop(0)
        if tail:
            if out:
                out.append("")
            out.extend(tail)
    return "\n".join(out)
