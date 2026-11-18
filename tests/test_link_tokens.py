"""T-1494 — the shared link tokenizer (pure, no Qt)."""

from __future__ import annotations

import pytest

from fastprompter.core.link_tokens import (
    classify_destination,
    tokenize_block,
)


def _only(text, **kwargs):
    tokens = tokenize_block(text, **kwargs)
    assert len(tokens) == 1, tokens
    return tokens[0]


def test_bare_url_at_position_zero():
    token = _only("https://example.com")
    assert token.kind == "autolink"
    assert token.destination == "https://example.com"
    assert token.span == (0, len("https://example.com"))
    assert token.action == "web"


def test_bare_url_with_path_and_query():
    text = "See https://example.com/a/b?x=1&y=2 now"
    token = _only(text)
    assert token.destination == "https://example.com/a/b?x=1&y=2"
    assert token.span == (text.index("https"), text.index(" now"))
    assert token.normalized == "https://example.com/a/b?x=1&y=2"


def test_two_consecutive_url_lines_are_separate_blocks():
    first = _only("https://one.example.com")
    second = _only("https://two.example.com")
    assert first.destination != second.destination


def test_several_links_in_one_paragraph():
    text = "a https://one.example b www.two.example c mailto:x@y.example"
    tokens = tokenize_block(text)
    assert [t.destination for t in tokens] == [
        "https://one.example",
        "www.two.example",
        "mailto:x@y.example",
    ]
    assert [t.kind for t in tokens] == ["autolink", "autolink", "autolink"]
    assert [t.action for t in tokens] == ["web", "web", "email"]


def test_markdown_link_with_label():
    text = "[My Project](https://example.com?a=1&b=2)"
    token = _only(text)
    assert token.kind == "markdown"
    assert token.label == "My Project"
    assert token.destination == "https://example.com?a=1&b=2"
    assert token.span == (0, len(text))


def test_markdown_link_with_balanced_parentheses_in_destination():
    text = "[Wiki](https://en.wikipedia.org/wiki/Foo_(bar))"
    token = _only(text)
    assert token.destination == "https://en.wikipedia.org/wiki/Foo_(bar)"


def test_markdown_link_with_percent_encoded_destination_is_not_decoded():
    token = _only("[x](https://example.com/a%20b?q=%2Fpath)")
    assert token.destination == "https://example.com/a%20b?q=%2Fpath"
    assert "%20" in token.destination


def test_local_screenshot_file_url():
    token = _only("[Screenshot](file:///M:/Screenshots/example.png)")
    assert token.kind == "markdown"
    assert token.destination == "file:///M:/Screenshots/example.png"
    assert token.action == "local_file"


def test_query_parameters_with_ampersand_are_not_escaped():
    token = _only("[My Project](https://example.com?a=1&b=2)")
    assert "&" in token.destination
    assert "&amp;" not in token.destination


def test_url_containing_parentheses_keeps_them():
    token = _only("https://example.org/a_(b)_c")
    assert token.destination == "https://example.org/a_(b)_c"


def test_url_followed_by_terminal_punctuation_is_trimmed():
    token = _only("Go to https://example.com.")
    assert token.destination == "https://example.com"
    token = _only("Go to https://example.com, then stop")
    assert token.destination == "https://example.com"


def test_unbalanced_trailing_parenthesis_is_trimmed():
    token = _only("(see https://example.com)")
    assert token.destination == "https://example.com"


def test_url_inside_code_fence_stays_plain():
    assert tokenize_block("https://example.com", in_code=True) == []


def test_url_inside_inline_code_stays_plain():
    assert tokenize_block("`https://example.com`") == []


def test_no_duplicate_token_inside_markdown_destination():
    text = "[label](https://example.com)"
    tokens = tokenize_block(text)
    assert len(tokens) == 1
    assert tokens[0].kind == "markdown"


def test_markdown_image_stays_separate_from_links():
    tokens = tokenize_block("![alt](https://example.com/a.png)")
    assert len(tokens) == 1
    assert tokens[0].kind == "image"
    assert tokens[0].is_image


def test_ftp_scheme_is_supported():
    action, normalized = classify_destination("ftp://files.example.com/x")
    assert action == "web"
    assert normalized == "ftp://files.example.com/x"


def test_www_host_normalizes_to_https():
    token = _only("www.example.com")
    assert token.action == "web"
    assert token.normalized == "https://www.example.com"
    assert token.destination == "www.example.com"


@pytest.mark.parametrize("bad", [
    "javascript:alert(1)",
    "data:text/html,<script>",
    "vbscript:msgbox",
    "whatever://x",
])
def test_dangerous_and_unknown_schemes_are_unsupported(bad):
    action, _ = classify_destination(bad)
    assert action == "unsupported"


def test_arbitrary_prose_is_not_a_local_file_link():
    action, _ = classify_destination("C:\\Users\\me\\notes.txt")
    assert action == "unsupported"


def test_links_inside_list_items_and_blockquotes():
    line = "- item https://example.com"
    assert _only(line).destination == "https://example.com"
    quote = "> quoted https://example.com"
    assert _only(quote).destination == "https://example.com"


def test_bbcode_url_syntax_is_recognised():
    token = _only("[url=https://example.com]Example[/url]")
    assert token.kind == "bbcode"
    assert token.destination == "https://example.com"
    assert token.label == "Example"


def test_bbcode_bare_url_syntax_is_recognised():
    token = _only("[url]https://example.com[/url]")
    assert token.kind == "bbcode"
    assert token.destination == "https://example.com"


def test_mixed_case_scheme_is_recognised():
    token = _only("HTTPS://Example.COM/Path")
    assert token.action == "web"
    assert token.destination == "HTTPS://Example.COM/Path"


def test_unicode_domain_is_recognised():
    token = _only("https://exämple.test/pfad")
    assert token.action == "web"


def test_fragment_is_preserved_exactly():
    token = _only("[x](https://example.com/page#section-2)")
    assert token.destination == "https://example.com/page#section-2"


def test_source_spans_are_accurate():
    text = "lead [label](https://example.com) tail"
    token = _only(text)
    assert text[token.span[0]:token.span[1]] == "[label](https://example.com)"
    assert text[token.target_span[0]:token.target_span[1]] == \
        "https://example.com"


def test_empty_block_yields_nothing():
    assert tokenize_block("") == []
    assert tokenize_block("   ") == []
