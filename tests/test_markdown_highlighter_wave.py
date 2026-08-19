"""T-1008 regression: Live Preview headers must be formatted immediately,
without a scroll workaround, for both small and large documents.

The old code fully SKIPPED highlighting on docs > 500 blocks, so headers
vanished. Now large docs degrade (essentials kept) instead.
"""

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtGui import QFont, QTextDocument  # noqa: E402
from PyQt6.QtWidgets import QApplication, QComboBox, QTextEdit  # noqa: E402

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

import fastprompter.ui.theme_mixin as theme_mod  # noqa: E402
from fastprompter.ui.markdown_highlighter import MarkdownHighlighter  # noqa: E402

_APP = QApplication.instance() or QApplication([])


def _flush():
    _APP.processEvents()


def _doc_with(lines):
    doc = QTextDocument()
    doc.setPlainText("\n".join(lines))
    return doc


def _bold_at(doc, block_idx):
    """Is the block's leading text bold?

    Reads the LAYOUT formats (where QSyntaxHighlighter.setFormat lands) —
    ``block.charFormat()`` does not surface per-layout formats on this Qt
    build and always reports the block's neutral weight.
    """
    blk = doc.findBlockByNumber(block_idx)
    if not blk.isValid():
        return False
    for f in blk.layout().formats():
        if f.format.fontWeight() == QFont.Weight.Bold:
            return True
    return False


def test_header_formatted_on_small_doc():
    doc = _doc_with(["# Heading", "body text"])
    hl = MarkdownHighlighter(doc)
    hl.rehighlight()
    _flush()
    assert _bold_at(doc, 0)


def test_header_formatted_on_large_degraded_doc():
    lines = ["# Heading"] + [f"line {i}" for i in range(600)]
    doc = _doc_with(lines)
    hl = MarkdownHighlighter(doc)
    hl.set_degraded(True)          # the old >500 path
    hl.rehighlight()
    _flush()
    # degraded keeps headers — it must NOT blank them
    assert _bold_at(doc, 0)
    assert hl._skip_highlighting is False


def test_degraded_skips_code_subhighlight_not_headers():
    big = "```python\n" + "x = 1  # comment\n" * 5 + "```\n"
    lines = ["# Title", big] + [f"p {i}" for i in range(600)]
    doc = _doc_with(lines)
    hl = MarkdownHighlighter(doc)
    hl.set_degraded(True)
    hl.rehighlight()
    _flush()
    assert _bold_at(doc, 0)


class _FakeWin:
    def __init__(self, lines, mode="Live Preview", data=None,
                 hl_cls=MarkdownHighlighter):
        self.data = data or {}
        self.text_area = QTextEdit()
        self.text_area.setPlainText("\n".join(lines))
        self.preview_combo = QComboBox()
        self.preview_combo.addItem("Live Preview", "Live Preview")
        self.preview_combo.addItem("Source View", "Source View")
        self.preview_combo.setCurrentIndex(
            0 if mode == "Live Preview" else 1)
        self.highlighter = hl_cls(self.text_area.document())

    def _apply_conceal_mode(self):
        pass


def _bind(win):
    win._sync_live_preview_highlighter = \
        theme_mod.ThemeMixin._sync_live_preview_highlighter.__get__(win)
    return win


def test_sync_helper_formats_headers_small():
    win = _bind(_FakeWin(["# Title", "body"]))
    win._sync_live_preview_highlighter()
    _flush()
    assert _bold_at(win.text_area.document(), 0)


def test_sync_helper_formats_headers_large_degraded():
    lines = ["# Title"] + [f"x {i}" for i in range(600)]
    win = _bind(_FakeWin(lines))
    win._sync_live_preview_highlighter()
    _flush()
    assert _bold_at(win.text_area.document(), 0)


def test_sync_helper_detaches_in_source_view():
    win = _bind(_FakeWin(["# Title"], mode="Source View"))
    win._sync_live_preview_highlighter()
    _flush()
    # Source View detaches the highlighter from the document
    assert win.highlighter.document() is None


# ==================================================== full T-1008 matrix


def _bold_at(doc, block_idx):
    """Is the block's leading text bold?

    Reads the LAYOUT formats (where QSyntaxHighlighter.setFormat lands) —
    ``block.charFormat()`` does not surface per-layout formats on this Qt
    build and always reports the block's neutral weight.
    """
    blk = doc.findBlockByNumber(block_idx)
    if not blk.isValid():
        return False
    for f in blk.layout().formats():
        if f.format.fontWeight() == QFont.Weight.Bold:
            return True
    return False


class _CountingHL(MarkdownHighlighter):
    def __init__(self, doc):
        super().__init__(doc)
        self.count = 0

    def rehighlight(self):
        self.count += 1
        super().rehighlight()


def _large_lines(n=600):
    return ["# Top Heading"] + [f"p {i}" for i in range(n)] + [
        "# Middle Heading", "mid body",
    ] + [f"q {i}" for i in range(n)] + ["# Bottom Heading", "tail"]


def test_headers_top_middle_and_below_viewport():
    lines = _large_lines()
    win = _bind(_FakeWin(lines))
    win._sync_live_preview_highlighter()
    _flush()
    doc = win.text_area.document()
    # top header (block 0)
    assert _bold_at(doc, 0)
    # middle header, far below the first screenful
    mid = 600 + 1
    assert _bold_at(doc, mid)
    # header below the viewport (near the end of the doc)
    last = doc.blockCount() - 2
    assert _bold_at(doc, last)


def test_live_source_live_cycle_reformats_without_scroll():
    win = _bind(_FakeWin(["# One", "body"]))
    win._sync_live_preview_highlighter()
    _flush()
    assert _bold_at(win.text_area.document(), 0)
    bar = win.text_area.verticalScrollBar()
    before = bar.value()
    win.preview_combo.setCurrentIndex(1)          # Source View
    win._sync_live_preview_highlighter()
    _flush()
    assert win.highlighter.document() is None
    win.preview_combo.setCurrentIndex(0)          # back to Live Preview
    win._sync_live_preview_highlighter()
    _flush()
    assert _bold_at(win.text_area.document(), 0)
    assert bar.value() == before                  # no scroll band-aid


def test_small_large_small_silo_swap_keeps_headers():
    win = _bind(_FakeWin(["# Small", "body"]))
    win._sync_live_preview_highlighter()
    _flush()
    assert _bold_at(win.text_area.document(), 0)
    # switch silo: big document
    win.text_area.setPlainText("\n".join(_large_lines()))
    win._sync_live_preview_highlighter()
    _flush()
    assert _bold_at(win.text_area.document(), 0)
    assert win.highlighter._degraded is True      # large-doc policy recomputed
    # switch back to a small silo while staying Live
    win.text_area.setPlainText("# Tiny\nbody")
    win._sync_live_preview_highlighter()
    _flush()
    assert _bold_at(win.text_area.document(), 0)
    assert win.highlighter._degraded is False     # no inherited large state


def test_conceal_toggle_keeps_headers_formatted():
    win = _bind(_FakeWin(["# H1", "plain"], data={"live_preview_conceal": "True"}))
    win._sync_live_preview_highlighter()
    _flush()
    assert _bold_at(win.text_area.document(), 0)
    win.data["live_preview_conceal"] = "False"
    win._sync_live_preview_highlighter()
    _flush()
    assert _bold_at(win.text_area.document(), 0)


def test_edit_heading_reformats_on_sync():
    win = _bind(_FakeWin(["# Old", "body"]))
    win._sync_live_preview_highlighter()
    _flush()
    doc = win.text_area.document()
    doc.setPlainText("# New heading\nbody")
    win._sync_live_preview_highlighter()
    _flush()
    assert _bold_at(doc, 0)


def test_sync_does_exactly_one_rehighlight():
    win = _bind(_FakeWin(["# T", "body"], hl_cls=_CountingHL))
    win._sync_live_preview_highlighter()
    _flush()
    assert win.highlighter.count == 1


def test_sync_one_rehighlight_even_with_conceal_on():
    """Conceal mode rehighlights internally; the sync must not add a second."""
    win = _bind(_FakeWin(["# T", "body", "## H2"],
                         data={"live_preview_conceal": "True"},
                         hl_cls=_CountingHL))
    win._sync_live_preview_highlighter()
    _flush()
    assert win.highlighter.count == 1
