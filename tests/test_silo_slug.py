"""PERF-002: silo_slug must stay byte-for-byte equivalent to its prior
first-line semantics while only inspecting the document prefix."""

import re

from fastprompter.ui.file_container import silo_slug


def _reference_slug(text):
    """The exact pre-optimization semantics, kept as an oracle."""
    first = (text or "").strip().splitlines()[0] if (text or "").strip() else ""
    _TS = re.compile(r"\([^()]*\d{1,2}[:.]\d{2}[^()]*\)")
    _STRIP = re.compile(r"[#*_`•\[\]]+")
    _BAD = re.compile(
        "[^a-z0-9" + chr(0x0430) + "-" + chr(0x044F) + chr(0x0451) + "\\- ]+")
    first = _TS.sub("", first)
    first = _STRIP.sub("", first).strip().lower()
    first = _BAD.sub("", first)
    first = re.sub(r"\s+", "-", first).strip("-")[:40].strip("-")
    return first or "untitled"


_CASES = [
    "",                                  # empty
    "   ",                               # all whitespace
    "\n\n\n",                            # only blank lines
    "\n\n\nhello world",                 # leading blank lines
    "  hello world  ",                   # leading/trailing whitespace
    "hello world\r\nmore body",          # CRLF
    "hello world\nmore body",            # LF
    "hello world\rmore body",            # CR
    "   leading unicode ws",             # Unicode whitespace
    "(17.07 - 04:19) my title",          # timestamp removed
    "## Section *bold* _x_ [link]",      # punctuation stripped
    "Привет мир заголовок",              # Cyrillic kept
    "a" * 100,                           # long title truncated to 40
    "title\n" + ("x" * 100000),          # huge body, short title
    "  (17 Jul - 04:19:33)  ## Title  ", # combined
    "123 Main Street",                   # ascii
]


def test_slug_reference_equivalence():
    for text in _CASES:
        assert silo_slug(text) == _reference_slug(text), repr(text)


def test_slug_only_reads_prefix():
    body = "short title\n" + ("y" * 200000)
    assert silo_slug(body) == "short-title"
    assert silo_slug(body) == _reference_slug(body)
