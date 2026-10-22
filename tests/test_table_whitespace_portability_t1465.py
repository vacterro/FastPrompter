r"""T-1465: boundary-whitespace portability across Markdown consumers.

T-1464 protected leading/trailing spaces and tabs with backslash escapes
(`\ x`). FastPrompter's own parser restores those values, but no standard
Markdown engine treats backslash-before-whitespace as an escape: the
backslash survives as literal text and GFM cell trimming drops the
whitespace after it, so an external consumer sees `\ x` instead of ` x`
and loses the trailing space and boundary tabs entirely.

The contract now serializes boundary whitespace as numeric character
references (`&#32;`, `&#9;`), which every engine decodes AFTER cell
trimming, and ampersand-escapes a literal `&` so user-entered entity-like
text stays literal. These tests assert BOTH sides independently:

A. FastPrompter's own escape -> split_row -> unescape round-trip.
B. The logical cell value produced by an INDEPENDENT Markdown parser,
   read straight out of its AST -- never through FastPrompter's unescape.
"""

import pytest

from fastprompter.ui import silo_table as st

markdown_it = pytest.importorskip(
    "markdown_it",
    reason="markdown-it-py provides the independent GFM table oracle",
)

# Every value the contract must represent, straight from the mission list.
CELL_CASES = [
    # empty cell
    "",
    # one space / multiple spaces / whitespace-only
    " ",
    "   ",
    "\t",
    "\t\t",
    " \t ",
    # leading / trailing / both, spaces and tabs
    " x",
    "  leading",
    "x ",
    "trailing  ",
    " x ",
    "  both  ",
    "\tleading_tab",
    "trailing_tab\t",
    " \t x \t ",
    # literal ampersand and literal entity-like text
    "AT&T",
    "&#32;",
    "&#9;",
    "&amp;",
    "&copy;",
    "a&#32;b",
    "R&D amp; text",
    # backslash followed by space / pipe / multiple backslashes
    "\\ ",
    " \\",
    "\\ \\",
    "\\|",
    "\\\\",
    "C:\\Users\\test",
    # escaped pipe
    "a|b",
    "grep a|b|c",
    # whitespace plus Markdown punctuation
    " x*",
    " x_",
    "- x",
    ">q",
    "  x**",
    # unicode and emoji
    "\U0001F984|\U0001F308",
    "日本語|テスト",
    "Ünïcødé  ",
    "  \U0001F642 emoji  ",
]

# The exact rows a T-1464-era document contains: the old escape() output.
LEGACY_DOCS = [
    ("| A | B |\n| --- | --- |\n| \\ x | y\\ |\n| \\ | \\\t |\n| \\\\ | \\\\\\ |\n",
     [" x", "y ", " ", "\t", "\\", "\\ "]),
]


def _serialize(value: str) -> str:
    return "| " + st.escape(value) + " |"


def _external_cell_text(line: str) -> str:
    """The logical cell content an independent GFM parser produces.

    Reads markdown-it's own AST tokens: text tokens verbatim, any other
    inline token (html_inline, entity, ...) flattened to its raw source.
    No FastPrompter decoding is applied anywhere on this path.
    """
    md = markdown_it.MarkdownIt("commonmark").enable("table")
    doc = "| A |\n| --- |\n" + line + "\n"
    texts: list[str] = []

    def walk(tokens):
        for tok in tokens:
            if tok.type == "inline":
                for child in tok.children:
                    if child.type == "text":
                        texts.append(child.content)
                    elif child.type == "html_inline":
                        texts.append(child.content)
                    elif child.type == "softbreak":
                        texts.append("\n")
            if tok.children:
                walk(tok.children)

    walk(md.parse(doc))
    body = texts[1:] if texts else []
    return body[0] if body else ""


class TestInternalRoundTrip:
    @pytest.mark.parametrize("val", CELL_CASES)
    def test_escape_split_unescape_is_identity(self, val):
        line = _serialize(val)
        cells = st.split_row(line)
        assert len(cells) == 1, line
        assert st.unescape(cells[0]) == val, (
            f"internal round-trip failed for {val!r}: line={line!r}"
        )

    @pytest.mark.parametrize("val", CELL_CASES)
    def test_repeated_cycles_are_stable(self, val):
        current = val
        for _ in range(3):
            row = _serialize(current)
            current = st.unescape(st.split_row(row)[0])
        assert current == val

    def test_full_table_render_parse_round_trip(self):
        rows = [["H1", "H2"]] + [[v, "companion"] for v in CELL_CASES]
        escaped = [[st.escape(c) for c in row] for row in rows]
        table = st.Table(0, 0, escaped, [st.ALIGN_LEFT, st.ALIGN_RIGHT], True)
        lines = st.render(table)
        again = st.parse(lines, 1)
        assert again is not None
        got = [[st.unescape(c) for c in row] for row in again.normalised()]
        assert got == [list(r) + [""] * (2 - len(r)) for r in rows]


class TestExternalConsumer:
    """The independent-parser oracle. FastPrompter's unescape is never used
    to produce or repair the expected value on this path."""

    @pytest.mark.parametrize("val", CELL_CASES)
    def test_markdown_it_recovers_the_logical_value(self, val):
        line = _serialize(val)
        assert _external_cell_text(line) == val, (
            f"markdown-it-py produced {_external_cell_text(line)!r} for "
            f"{val!r} via line {line!r}"
        )

    @pytest.mark.parametrize("val", CELL_CASES)
    def test_python_markdown_cell_renders_the_logical_value(self, val):
        # python-markdown (the declared dependency) is the second independent
        # consumer: the td content it emits, read as a browser would read it
        # (stdlib html.unescape -- NOT FastPrompter's unescape), must be the
        # original value.
        import html as html_mod
        import re

        markdown = pytest.importorskip("markdown")
        line = _serialize(val)
        html = markdown.markdown(
            "| A |\n| --- |\n" + line + "\n", extensions=["tables"]
        )
        tds = re.findall(r"<(?:th|td)[^>]*>(.*?)</(?:th|td)>", html)
        assert len(tds) == 2, html
        assert html_mod.unescape(tds[1]) == val, html


class TestLegacyCompatibility:
    def test_t1464_documents_keep_their_logical_values(self):
        for doc, expected in LEGACY_DOCS:
            lines = doc.split("\n")
            table = st.parse(lines, 1)
            assert table is not None
            got = [[st.unescape(c) for c in row] for row in table.rows]
            assert got[0] == ["A", "B"]
            assert got[1:] == [list(expected[i:i + 2])
                               for i in range(0, len(expected), 2)], doc

    def test_pre_t1464_documents_load_unchanged(self):
        doc = "| A | B |\n| --- | --- |\n| x | y |\n"
        table = st.parse(doc.split("\n"), 1)
        got = [[st.unescape(c) for c in row] for row in table.rows]
        assert got == [["A", "B"], ["x", "y"]]

    def test_resaving_a_legacy_document_migrates_to_the_portable_form(self):
        for doc, expected in LEGACY_DOCS:
            lines = doc.split("\n")
            table = st.parse(lines, 1)
            values = [[st.unescape(c) for c in row] for row in table.rows]
            rewritten = st.render(st.Table(0, 0, [[st.escape(c) for c in row]
                                                  for row in values],
                                           table.aligns, True))
            reloaded = st.parse(rewritten, 1)
            assert [[st.unescape(c) for c in row] for row in reloaded.rows] == values
            # the migrated form is externally portable
            for row in reloaded.rows[1:]:
                for cell in row:
                    assert _external_cell_text("| " + cell + " |") == st.unescape(cell)


class TestDocumentPipeline:
    def test_prose_before_and_after_and_multiple_tables(self):
        doc = [
            "# ünïcødé heading",
            "",
            "prose with pipes | not a table",
            "",
            "| A | B |",
            "| --- | --- |",
            "| &#32;x&#32; | y&#9; |",
            "",
            "more prose",
            "",
            "| C | D |",
            "| :---: | ---: |",
            "| \\ | a\\|b |",
            "",
            "tail",
        ]
        first = st.parse(doc, 4)
        second = st.parse(doc, 11)
        assert (first.first_block, first.last_block) == (4, 6)
        assert (second.first_block, second.last_block) == (10, 12)
        v1 = [[st.unescape(c) for c in row] for row in first.rows]
        v2 = [[st.unescape(c) for c in row] for row in second.rows]
        assert v1 == [["A", "B"], [" x ", "y\t"]]
        assert v2 == [["C", "D"], [" ", "a|b"]]
        # re-render both and reload: values survive, alignments survive
        out = st.render(first)
        out2 = st.render(second)
        r1 = st.parse(out, 0)
        r2 = st.parse(out2, 0)
        assert [[st.unescape(c) for c in row] for row in r1.rows] == v1
        assert [[st.unescape(c) for c in row] for row in r2.rows] == v2
        assert r2.aligns == [st.ALIGN_CENTER, st.ALIGN_RIGHT]

    def test_alignment_with_whitespace_cells(self):
        for align, spec in ((st.ALIGN_LEFT, ":---"), (st.ALIGN_RIGHT, "---:"),
                            (st.ALIGN_CENTER, ":---:")):
            table = st.Table(0, 0,
                             [[st.escape(c) for c in ["H", " x ", "a|b", " "]]],
                             [align] * 4, False)
            lines = st.render(table)
            assert st.spec_of(align, 3) in lines[0]
            again = st.parse(lines, 0)
            assert again is not None
            got = [st.unescape(c) for c in again.rows[0]]
            assert got == ["H", " x ", "a|b", " "]


class TestModelPipeline:
    """The grid path: load -> edit -> serialize -> reload, through the model."""

    def test_model_round_trip_with_boundary_whitespace(self):
        from fastprompter.ui.table_model import TableCellsModel

        m = TableCellsModel()
        m.has_header = True
        m.rows = [["H1", "H2"], [" x ", "y\t"], [" ", "a|b"]]
        m.aligns = [st.ALIGN_LEFT, st.ALIGN_RIGHT]
        lines = m.table_lines()
        m2 = TableCellsModel()
        m2.load_markdown("\n".join(lines))
        assert m2.rows == [["H1", "H2"], [" x ", "y\t"], [" ", "a|b"]]
        assert m2.aligns == [st.ALIGN_LEFT, st.ALIGN_RIGHT]

    def test_repeated_save_reload_cycles_through_the_model(self):
        from fastprompter.ui.table_model import TableCellsModel

        values = [["H", " x "], ["a|b", "\t"], ["&#32;", " "]]
        m = TableCellsModel()
        m.has_header = True
        m.rows = [list(r) for r in values]
        m.aligns = [st.ALIGN_LEFT, st.ALIGN_LEFT]
        for _ in range(3):
            m2 = TableCellsModel()
            m2.load_markdown("\n".join(m.table_lines()))
            assert m2.rows == values
            m = m2

    def test_literal_entity_text_is_not_double_decoded(self):
        from fastprompter.ui.table_model import TableCellsModel

        m = TableCellsModel()
        m.has_header = True
        m.rows = [["H", "&#32;"], ["&amp;", "&copy;"]]
        m.aligns = [st.ALIGN_LEFT, st.ALIGN_LEFT]
        m2 = TableCellsModel()
        m2.load_markdown("\n".join(m.table_lines()))
        assert m2.rows[0] == ["H", "&#32;"]
        assert m2.rows[1] == ["&amp;", "&copy;"]
        # and the independent parser agrees the literal text survived
        for row in m2.rows:
            for cell in row:
                assert _external_cell_text("| " + st.escape(cell) + " |") == cell
