"""Tests for fastprompter.core.hashtags — in-text tags."""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

from fastprompter.core.hashtags import (  # noqa: E402
    collect_all,
    extract_tags,
    find_occurrences,
    tag_at,
    tags_in_line,
)


# ------------------------------------------------------------ what is a tag

def test_a_plain_tag_is_found():
    assert extract_tags("buy milk #todo") == ["todo"]


def test_markdown_headers_are_not_tags():
    """The space is the whole difference: "# Title" is a header."""
    assert extract_tags("# Title") == []
    assert extract_tags("## Sub") == []
    assert extract_tags("###### Deep") == []
    assert extract_tags("--- \n### Heading with #tag") == []


def test_a_tag_on_a_header_line_is_ignored_not_half_read():
    assert tags_in_line("# Title with #tag") == []


def test_tags_are_case_insensitive():
    assert extract_tags("#Todo and #todo and #TODO") == ["todo"]


def test_tags_keep_first_seen_order_and_do_not_repeat():
    assert extract_tags("#b #a #b #c") == ["b", "a", "c"]


def test_unicode_tags_work():
    assert extract_tags("надо купить #дела") == ["дела"]


def test_dashes_and_underscores_are_allowed_inside():
    assert extract_tags("#in-progress #two_words") == ["in-progress", "two_words"]


def test_a_tag_cannot_start_with_a_digit_only_rule_is_word_char():
    assert extract_tags("#2026goals") == ["2026goals"]


def test_a_bare_hash_is_not_a_tag():
    assert extract_tags("# ") == []
    assert extract_tags("nothing here #") == []
    assert extract_tags("c# is a language") == []


def test_a_hash_inside_a_word_is_not_a_tag():
    assert extract_tags("item#5") == []
    assert extract_tags("http://x/page#anchor") == []


def test_double_hash_mid_line_is_not_a_tag():
    assert extract_tags("see ##notatag") == []


def test_empty_and_none_are_safe():
    assert extract_tags("") == []
    assert extract_tags(None) == []
    assert tags_in_line(None) == []


# ------------------------------------------------------------- tag_at

def test_tag_at_finds_the_tag_under_a_click():
    line = "buy milk #todo later"
    start = line.index("#")
    assert tag_at(line, start) == "todo", "clicking the hash itself counts"
    assert tag_at(line, start + 3) == "todo"
    assert tag_at(line, start + 5) == "todo", "the far end counts too"
    assert tag_at(line, 2) is None
    assert tag_at(line, len(line) - 1) is None


def test_tag_at_picks_the_right_one_of_several():
    line = "#alpha and #beta"
    assert tag_at(line, 2) == "alpha"
    assert tag_at(line, line.index("#beta") + 2) == "beta"


# -------------------------------------------------------- across silos

SILOS = [
    "shopping\nmilk #todo\nbread",
    "# Notes\nnothing tagged here",
    "call bank #todo #urgent\nrest\nlater #todo",
]
NAMES = ["Home", "Notes", "Work"]


def test_occurrences_span_every_silo():
    hits = find_occurrences("todo", SILOS, NAMES)
    assert [(h["silo"], h["line"]) for h in hits] == [(0, 2), (2, 1), (2, 3)]
    assert hits[0]["name"] == "Home"
    assert hits[0]["text"] == "milk #todo"


def test_occurrences_accept_the_tag_written_with_its_hash():
    assert find_occurrences("#todo", SILOS) == find_occurrences("todo", SILOS)


def test_occurrences_are_case_insensitive():
    assert len(find_occurrences("TODO", SILOS)) == 3


def test_line_numbers_are_one_based_to_match_the_gutter():
    hits = find_occurrences("urgent", SILOS)
    assert hits[0]["line"] == 1


def test_a_silo_without_a_name_still_gets_a_label():
    hits = find_occurrences("todo", SILOS, ["", "", ""])
    assert hits[0]["name"] == "Silo 1"


def test_junk_silos_do_not_break_the_search():
    assert find_occurrences("todo", [None, 42, "", "x #todo"])[0]["silo"] == 3


def test_an_empty_tag_finds_nothing():
    assert find_occurrences("", SILOS) == []
    assert find_occurrences("#", SILOS) == []
    assert find_occurrences(None, SILOS) == []


def test_collect_all_counts_lines_not_mentions():
    counts = collect_all(SILOS)
    assert counts["todo"] == 3
    assert counts["urgent"] == 1
    # a tag twice on one line is still one line
    assert collect_all(["#a #a"])["a"] == 1


def test_collect_all_on_nothing():
    assert collect_all([]) == {}
    assert collect_all(None) == {}
