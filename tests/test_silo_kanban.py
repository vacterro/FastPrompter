"""SiloKanban: the board IS the text, so every test is text in / text out."""

from fastprompter.ui import silo_kanban as sk

BOARD = [
    "# Sprint",
    "",
    "## To Do",
    "- [ ] write the thing",
    "- [ ] read the docs",
    "",
    "## Doing",
    "- [ ] the other thing",
    "  with a second line",
    "",
    "## Done",
    "- [x] the easy one",
]


def test_parses_columns_and_cards():
    b = sk.parse(BOARD)
    assert [c.name for c in b.columns] == ["To Do", "Doing", "Done"]
    assert [len(c.cards) for c in b.columns] == [2, 1, 1]
    assert b.columns[0].cards[1].text == "read the docs"
    assert b.columns[2].cards[0].done is True
    assert b.columns[0].cards[0].done is False


def test_a_continuation_line_belongs_to_its_card():
    b = sk.parse(BOARD)
    card = b.columns[1].cards[0]
    assert card.first == 7 and card.last == 8
    assert sk.render_card(card, BOARD) == ["- [ ] the other thing",
                                           "  with a second line"]


def test_card_at_finds_the_card_from_a_continuation():
    b = sk.parse(BOARD)
    assert b.card_at(8) == (1, 0)
    assert b.card_at(3) == (0, 0)
    assert b.card_at(2) is None          # the heading is not a card


def test_move_right_carries_the_whole_card():
    out, at = sk.move_card(BOARD, 7, 1, 0)
    b = sk.parse(out)
    assert [len(c.cards) for c in b.columns] == [2, 0, 2]
    moved = b.columns[2].cards[0]
    assert sk.render_card(moved, out) == ["- [ ] the other thing",
                                          "  with a second line"]
    assert out[at] == "- [ ] the other thing"


def test_move_left_and_back_is_the_identity():
    right, _ = sk.move_card(BOARD, 3, 1, 0)
    where = sk.parse(right).card_at(0) or sk.parse(right).card_at(1)
    b = sk.parse(right)
    ci, ki = b.card_at(b.columns[1].cards[0].first)
    back, _ = sk.move_card(right, b.columns[1].cards[0].first, -1, 0)
    assert sk.parse(back).columns[0].cards[0].text == "write the thing"
    assert [len(c.cards) for c in sk.parse(back).columns] == [2, 1, 1]


def test_move_off_the_board_refuses():
    assert sk.move_card(BOARD, 3, -1, 0) is None      # already leftmost
    assert sk.move_card(BOARD, 11, 1, 0) is None      # already rightmost
    assert sk.move_card(BOARD, 0, 1, 0) is None       # not a card
    assert sk.move_card(BOARD, 3, 0, -1) is None      # already first in column


def test_move_within_a_column():
    out, at = sk.move_card(BOARD, 3, 0, 1)
    assert [c.text for c in sk.parse(out).columns[0].cards] == [
        "read the docs", "write the thing"]
    up, _ = sk.move_card(out, at, 0, -1)
    assert [c.text for c in sk.parse(up).columns[0].cards] == [
        "write the thing", "read the docs"]


def test_toggle_card():
    out = sk.toggle_card(BOARD, 3)
    assert out[3] == "- [ ] write the thing".replace("[ ]", "[x]")
    again = sk.toggle_card(out, 3)
    assert again[3] == "- [ ] write the thing"
    assert sk.toggle_card(BOARD, 0) is None


def test_toggle_adds_a_box_to_a_plain_bullet():
    lines = ["## Ideas", "- just an idea"]
    out = sk.toggle_card(lines, 1)
    assert out[1] == "- [x] just an idea"


def test_add_card_lands_at_the_end_of_its_column():
    out, at = sk.add_card(BOARD, 3, "new one")
    assert out[at] == "- [ ] new one"
    assert [c.text for c in sk.parse(out).columns[0].cards] == [
        "write the thing", "read the docs", "new one"]
    assert sk.add_card(["no columns here"], 0) is None


def test_new_board_is_empty_but_parseable():
    lines = sk.new_board()
    b = sk.parse(lines)
    assert [c.name for c in b.columns] == ["To Do", "Doing", "Done"]
    assert all(len(c.cards) == 1 for c in b.columns)
    assert all(c.cards[0].text == "" for c in b.columns)
