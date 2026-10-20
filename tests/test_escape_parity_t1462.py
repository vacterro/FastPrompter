"""T-1462: escape/split/unescape pipeline must round-trip every cell value.

The bug: escape() inserts a backslash before every pipe without accounting
for an existing run of backslashes preceding that pipe. split_row() interprets
escaping according to backslash parity. A literal cell value containing a
backslash directly before a pipe gets split into multiple columns.
"""

from fastprompter.ui import silo_table as st


def test_escape_split_unescape_round_trip():
    """decode(split(encode(value))) == value for every supported cell value."""
    test_cases = [
        # Zero backslashes before a pipe
        "simple",
        "a|b",
        "grep a|b|c",
        # One backslash before a pipe
        "x\\|y",
        "C:\\Users\\file|name",
        # Two backslashes before a pipe
        "x\\\\|y",
        "C:\\\\Users|backup",
        # Three or more backslashes before a pipe
        "x\\\\\\|y",
        "\\\\\\\\|pipe",
        # Multiple pipes
        "a|b|c|d",
        "x\\|y|w\\|z",
        # Trailing backslashes
        "path\\",
        "path\\\\",
        "path\\\\\\",
        # Empty cells
        "",
        # Windows paths
        "C:\\Users\\test",
        "D:\\data\\file.txt",
        # Regex and shell command strings
        "grep -E 'a|b'",
        "sed 's/|/_/g'",
        "awk -F'|' '{print $1}'",
        # Unicode characters
        "🦄|🌈",
        "naïve|café",
        "日本語|テスト",
        # Mixed content
        "path\\to|file",
        "regex\\d+|value",
    ]

    for val in test_cases:
        escaped = st.escape(val)
        row = "| " + escaped + " | z |"
        cells = st.split_row(row)
        assert len(cells) == 2, f"Expected 2 cells for {repr(val)}, got {len(cells)}: {cells}"
        unescaped = st.unescape(cells[0])
        assert unescaped == val, f"Round-trip failed for {repr(val)}: got {repr(unescaped)}"


def test_visual_edit_cycle_is_stable():
    """Repeated escape->split->unescape cycles must be stable.

    Visual edit cycle: user sees unescaped value, edits, saves escaped,
    reloads unescaped. Each round-trip must preserve the original value.
    """
    test_cases = [
        "simple",
        "a|b",
        "x\\|y",
        "x\\\\|y",
        "x\\\\\\|y",
        "C:\\Users",
        "grep a|b|c",
        "🦄|🌈",
    ]
    for val in test_cases:
        # First cycle: encode -> split -> decode
        escaped = st.escape(val)
        row = "| " + escaped + " |"
        cells = st.split_row(row)
        decoded = st.unescape(cells[0])
        assert decoded == val, f"Cycle 1 failed for {repr(val)}: {repr(decoded)}"

        # Second cycle: decode -> encode -> split -> decode
        escaped2 = st.escape(decoded)
        row2 = "| " + escaped2 + " |"
        cells2 = st.split_row(row2)
        decoded2 = st.unescape(cells2[0])
        assert decoded2 == val, f"Cycle 2 failed for {repr(val)}: {repr(decoded2)}"


def test_split_row_backslash_parity():
    """split_row must correctly handle arbitrary backslash runs."""
    # Zero backslashes: pipe is delimiter
    assert st.split_row("| a | b |") == ["a", "b"]
    # One backslash: pipe is escaped (content)
    assert st.split_row(r"| a\|b | c |") == [r"a\|b", "c"]
    # Two backslashes: first escapes second, pipe is delimiter
    assert st.split_row(r"| a\\|b | c |") == [r"a\\", "b", "c"]
    # Three backslashes: first escapes second, third escapes pipe
    assert st.split_row(r"| a\\\|b | c |") == [r"a\\\|b", "c"]


def test_unescape_handles_escaped_backslashes():
    """unescape must handle both escaped backslashes and escaped pipes."""
    assert st.unescape(r"a\|b") == "a|b"
    assert st.unescape(r"a\\b") == "a\\b"
    assert st.unescape(r"a\\\|b") == "a\\|b"
    assert st.unescape("plain") == "plain"
