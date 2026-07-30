"""SiloKanban — a board made of markdown, so it survives being pasted.

Same constraint as SiloTable: a silo is plain text. A board built out of
widgets would look better for exactly as long as the window stays open and
would be gone from the text you hand to an agent, so the board IS the text:

    ## To Do
    - [ ] write the thing
    - [ ] read the docs

    ## Doing
    - [ ] the other thing

    ## Done
    - [x] the easy one

Columns are level-2 headings, cards are top-level list items (a card may
carry indented continuation lines, and they travel with it). Moving a card
is a text edit; the editor supplies the caret and gets lines back.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

CARD_RE = re.compile(r"^(\s*)([-*+])\s+(\[( |x|X)\]\s*)?(.*)$")
COLUMN_RE = re.compile(r"^(#{2,3})\s+(.*)$")


@dataclass
class Card:
    first: int                      # line index of the card's own bullet
    last: int                       # last line, continuations included
    text: str                       # the card's title, markers stripped
    done: bool = False

    @property
    def span(self) -> range:
        return range(self.first, self.last + 1)


@dataclass
class Column:
    heading: int                    # line index of the "## Name"
    name: str
    end: int                        # last line owned by this column
    cards: list[Card] = field(default_factory=list)


@dataclass
class Board:
    columns: list[Column] = field(default_factory=list)

    def column_of(self, line: int) -> int | None:
        for i, col in enumerate(self.columns):
            if col.heading <= line <= col.end:
                return i
        return None

    def card_at(self, line: int) -> tuple[int, int] | None:
        """(column index, card index) for the card owning `line`."""
        for ci, col in enumerate(self.columns):
            for ki, card in enumerate(col.cards):
                if card.first <= line <= card.last:
                    return (ci, ki)
        return None


def is_card_line(text: str) -> bool:
    m = CARD_RE.match(text)
    return bool(m) and not m.group(1)          # a top-level bullet only


def card_text(text: str) -> str:
    m = CARD_RE.match(text)
    return m.group(5).strip() if m else text.strip()


def card_done(text: str) -> bool:
    m = CARD_RE.match(text)
    return bool(m and m.group(4) and m.group(4).lower() == "x")


def parse(lines: list[str]) -> Board:
    """Read the board out of the text. Columns without cards still count."""
    board = Board()
    for i, line in enumerate(lines):
        m = COLUMN_RE.match(line)
        if m:
            board.columns.append(Column(i, m.group(2).strip(), i))
    if not board.columns:
        return board
    for idx, col in enumerate(board.columns):
        col.end = (board.columns[idx + 1].heading - 1
                   if idx + 1 < len(board.columns) else len(lines) - 1)
        card = None
        for i in range(col.heading + 1, col.end + 1):
            line = lines[i]
            if is_card_line(line):
                card = Card(i, i, card_text(line), card_done(line))
                col.cards.append(card)
            elif card is not None and (line.strip() == "" or line.startswith((" ", "\t"))):
                # a blank line or an indented line belongs to the card above,
                # so a two-line card moves in one piece
                if line.strip():
                    card.last = i
            else:
                card = None
    return board


def render_card(card: Card, source: list[str]) -> list[str]:
    return [source[i] for i in card.span]


def move_card(lines: list[str], line: int, dx: int, dy: int) -> tuple[list[str], int] | None:
    """Move the card at `line` between columns (dx) or within one (dy).

    Returns (new lines, the line the card now starts on), or None when the
    move is impossible — off the end of the board, or not on a card at all.
    Never silently no-ops into a corrupted board: it either moves or refuses.
    """
    board = parse(lines)
    where = board.card_at(line)
    if where is None:
        return None
    ci, ki = where
    col = board.columns[ci]
    card = col.cards[ki]
    block = render_card(card, lines)

    if dx:
        target = ci + (1 if dx > 0 else -1)
        if not (0 <= target < len(board.columns)):
            return None
        dest = board.columns[target]
        # land at the same depth in the target column when it is that deep,
        # otherwise at the end — "the card keeps its place" is the intuition
        anchor = (dest.cards[ki].first if ki < len(dest.cards)
                  else (dest.cards[-1].last + 1 if dest.cards else dest.heading + 1))
    else:
        target_ki = ki + (1 if dy > 0 else -1)
        if not (0 <= target_ki < len(col.cards)):
            return None
        other = col.cards[target_ki]
        anchor = other.first if dy < 0 else other.last + 1
        dest = col

    rest = [l for i, l in enumerate(lines) if i not in card.span]
    # every index after the removal shifts, including the anchor
    removed_before = sum(1 for i in card.span if i < anchor)
    at = max(0, min(anchor - removed_before, len(rest)))
    out = rest[:at] + block + rest[at:]
    return out, at


def toggle_card(lines: list[str], line: int) -> list[str] | None:
    """Tick / untick the checkbox of the card at `line`, adding one if absent."""
    board = parse(lines)
    where = board.card_at(line)
    if where is None:
        return None
    ci, ki = where
    card = board.columns[ci].cards[ki]
    m = CARD_RE.match(lines[card.first])
    if not m:
        return None
    indent, bullet, box, _state, body = m.groups()
    mark = "[ ]" if (box and _state and _state.lower() == "x") else "[x]"
    out = list(lines)
    out[card.first] = f"{indent}{bullet} {mark} {body}".rstrip()
    return out


def add_card(lines: list[str], line: int, text: str = "") -> tuple[list[str], int] | None:
    """A new card at the end of the column that owns `line`."""
    board = parse(lines)
    ci = board.column_of(line)
    if ci is None:
        return None
    col = board.columns[ci]
    at = col.cards[-1].last + 1 if col.cards else col.heading + 1
    out = list(lines)
    out.insert(at, f"- [ ] {text}".rstrip())
    return out, at


def new_board(columns: tuple[str, ...] = ("To Do", "Doing", "Done")) -> list[str]:
    """A blank board. Deliberately empty cards: the old insert wrote
    "Task 1..4" into the text, which is four things to delete."""
    lines: list[str] = []
    for name in columns:
        if lines:
            lines.append("")
        lines.append(f"## {name}")
        lines.append("- [ ] ")
    return lines
