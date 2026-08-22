"""Typecheck (typo checker): tokenizer skips, dictionary rules, suggestions."""

import pytest

from fastprompter.core.typecheck import Dictionary, find_unknown, iter_tokens


def make_dict(*extra):
    from fastprompter.core.typecheck_words import BASE_WORDS
    return Dictionary(base_words=BASE_WORDS, user_words=list(extra))


# ---------------------------------------------------------------- tokenizer


def test_tokens_are_words_with_offsets():
    toks = list(iter_tokens("hello world"))
    assert toks == [("hello", 0, 5), ("world", 6, 11)]


def test_code_fences_are_skipped():
    text = "```python\nhello wrold\nthere\n```\nplain text"
    words = [w for w, _s, _e in iter_tokens(text)]
    assert "hello" not in words
    assert "wrold" not in words
    assert "plain" in words and "text" in words


def test_inline_code_is_skipped():
    text = "run `wrold` now"
    words = [w for w, _s, _e in iter_tokens(text)]
    assert "wrold" not in words
    assert "run" in words and "now" in words


def test_urls_and_emails_are_skipped():
    text = "see https://example.com/wrold or mail wrold@example.com now"
    words = [w for w, _s, _e in iter_tokens(text)]
    assert "wrold" not in words
    assert "see" in words and "now" in words


def test_identifiers_are_skipped():
    text = "foo.bar snake_case myVar path/to #tag @user C:\\wrold"
    words = [w for w, _s, _e in iter_tokens(text)]
    for w in ("foo", "bar", "snake", "case", "my", "Var", "path", "to",
              "tag", "user", "C", "wrold"):
        assert w not in words, w


def test_acronyms_and_numbers_are_not_tokens():
    words = [w for w, _s, _e in iter_tokens("NASA API v2 done")]
    assert "NASA" in words  # still tokenized (filtered later by checkable)
    assert "API" in words
    assert "done" in words


# -------------------------------------------------------------- dictionary


def test_unknown_flags_typos():
    d = make_dict()
    assert d.unknown("wrold")
    assert not d.unknown("world")
    assert not d.unknown("Hello")       # capitalised normal word
    assert not d.unknown("NASA")        # acronym
    assert not d.unknown("a")           # single letter


def test_unknown_skips_identifiers():
    d = make_dict()
    assert not d.unknown("camelCase")
    assert not d.unknown("myVar")


def test_contractions():
    d = make_dict()
    assert not d.unknown("don't")
    assert not d.unknown("you're")


def test_non_latin_scripts_are_never_flagged_without_coverage():
    d = make_dict()  # English base: no Cyrillic coverage
    assert not d.unknown("привет")
    assert not d.unknown("こんにちは")


def test_user_words_extend_the_pool():
    d = make_dict("specialword")
    assert not d.unknown("specialword")
    d2 = make_dict()
    assert d2.unknown("specialword")


def test_add_grows_the_pool():
    d = make_dict()
    assert d.unknown("kzqwxv")
    d.add("kzqwxv")
    assert not d.unknown("kzqwxv")


def test_suggestions_are_close_matches():
    d = make_dict()
    sug = d.suggest("wrold")
    assert "world" in sug
    assert isinstance(sug, list) and len(sug) <= 3


def test_find_unknown_returns_offsets():
    d = make_dict()
    hits = find_unknown("the wrold is wrold", d)
    assert [(w, s) for w, s, _e in hits] == [("wrold", 4), ("wrold", 13)]


def test_find_unknown_is_bounded():
    d = make_dict()
    text = " ".join(["wrold"] * 5000)
    assert len(find_unknown(text, d, limit=100)) == 100


def test_ui_vocabulary_accepts_foreign_ui_words():
    from fastprompter.core.typecheck import ui_vocabulary
    vocab = ui_vocabulary()
    assert isinstance(vocab, frozenset)
    assert len(vocab) > 100  # the UI packs contributed real words


@pytest.mark.parametrize("word", [
    "world", "because", "should", "quickly", "interesting", "yesterday",
    "beautiful", "morning", "dictionary", "suggestion",
])
def test_common_words_are_in_the_shipped_dictionary(word):
    from fastprompter.core.typecheck_words import BASE_WORDS
    assert word in BASE_WORDS, word
