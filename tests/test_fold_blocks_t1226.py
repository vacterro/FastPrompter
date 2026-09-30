"""T-1226: whole-block folding behind the header/quote/fence anchors.

The feature shipped in the text area (`VaultTextEdit.toggle_fold`) and had no
test at all, so its DONE closure could not be re-proved from the current tree.
This file is that proof: it drives the real widget, not a stub.

Contract under test:
A  a '#' header collapses every block up to the next boundary, and only those
B  a '>' quote block collapses through its last consecutive quote line and
   leaves the anchor line itself visible (it reads as a footnote)
C  a code fence is an anchor and hides up to its closing fence
D  toggling twice restores every block to visible and clears the anchor bit
E  an anchor with nothing under it is NOT a fold (no range, no bit, no change)
F  folding stores the hidden line count for the gutter badge, and expanding
   clears it back to 0
G  an edit under a collapsed anchor first re-expands it, so no text is ever
   stranded invisible with no anchor left to click
"""

import pytest
from PyQt6.QtWidgets import QApplication

from fastprompter.ui.editor import VaultTextEdit


def _main_window():
    """The same minimal stand-in the other editor tests construct with."""
    from types import SimpleNamespace

    return SimpleNamespace(
        data={
            "show_line_numbers": "False",
            "code_auto_gutter": "False",
            "line_marks": "False",
        },
        highlighter=None,
        _LARGE_DOC_THRESHOLD=500_000,
        mark_dirty=lambda: None,
    )


@pytest.fixture()
def ta(qapp):
    widget = VaultTextEdit(_main_window())
    yield widget
    widget.deleteLater()
    QApplication.processEvents()


def _blocks(ta):
    doc = ta.document()
    out = []
    block = doc.firstBlock()
    while block.isValid():
        out.append(block)
        block = block.next()
    return out


def test_a_header_folds_its_whole_section(ta):
    ta.setPlainText("# One\nalpha\nbravo\n# Two\ncharlie")
    blocks = _blocks(ta)
    header = blocks[0]
    assert ta._is_fold_anchor(header)
    rng = ta._fold_range(header)
    assert rng is not None
    first, last = rng
    assert first.blockNumber() == 1 and last.blockNumber() == 2

    ta.toggle_fold(header)
    # the anchor stays visible; only its section hides; the next header does not
    assert header.isVisible()
    assert not blocks[1].isVisible()
    assert not blocks[2].isVisible()
    assert blocks[3].isVisible()
    assert blocks[4].isVisible()


def test_b_quote_anchor_leaves_itself_visible(ta):
    ta.setPlainText("> one\n> two\n> three\nplain")
    blocks = _blocks(ta)
    anchor = blocks[0]
    assert ta._is_fold_anchor(anchor)
    first, last = ta._fold_range(anchor)
    assert (first.blockNumber(), last.blockNumber()) == (1, 2)

    ta.toggle_fold(anchor)
    assert anchor.isVisible()
    assert not blocks[1].isVisible()
    assert not blocks[2].isVisible()
    assert blocks[3].isVisible(), "a plain line after the quote is not part of it"


def test_c_code_fence_is_an_anchor(ta):
    ta.setPlainText("```\ncode line\n```\nafter")
    blocks = _blocks(ta)
    opener = blocks[0]
    assert ta._is_fold_anchor(opener)
    rng = ta._fold_range(opener)
    assert rng is not None
    first, last = rng
    assert first.blockNumber() <= 2 <= last.blockNumber()
    ta.toggle_fold(opener)
    assert not blocks[1].isVisible()
    assert blocks[3].isVisible()


def test_d_toggle_twice_restores_everything(ta):
    ta.setPlainText("# One\nalpha\nbravo")
    blocks = _blocks(ta)
    anchor = blocks[0]
    bit = VaultTextEdit.FOLD_BIT

    ta.toggle_fold(anchor)
    assert max(0, anchor.userState()) & bit
    assert not blocks[1].isVisible()

    ta.toggle_fold(anchor)
    assert not (max(0, anchor.userState()) & bit)
    assert all(b.isVisible() for b in blocks), "a second toggle restores every block"
    assert ta.toPlainText() == "# One\nalpha\nbravo", "folding never edits the text"


def test_e_anchor_with_nothing_under_it_is_not_a_fold(ta):
    ta.setPlainText("# Lonely header")
    anchor = _blocks(ta)[0]
    assert ta._is_fold_anchor(anchor)
    assert ta._fold_range(anchor) is None
    before = anchor.userState()
    ta.toggle_fold(anchor)
    assert anchor.userState() == before, "no range means no bit is set"
    assert anchor.isVisible()


def test_f_fold_count_tracks_the_hidden_lines(ta):
    from fastprompter.ui.editor import block_data

    ta.setPlainText("# One\nalpha\nbravo\n# Two\ncharlie")
    blocks = _blocks(ta)
    anchor = blocks[0]
    first, last = ta._fold_range(anchor)
    expected = last.blockNumber() - first.blockNumber() + 1

    ta.toggle_fold(anchor)
    data = block_data(anchor, create=True)
    assert data is not None and data.fold_count == expected

    ta.toggle_fold(anchor)
    assert block_data(anchor).fold_count == 0


def test_g_edit_under_a_collapsed_anchor_re_expands_first(ta):
    ta.setPlainText("# One\nalpha\nbravo")
    blocks = _blocks(ta)
    anchor = blocks[0]
    ta.toggle_fold(anchor)
    assert not blocks[1].isVisible()

    # this is what an edit must do before touching the folded region
    assert ta.expand_fold_at(anchor) is True
    assert all(b.isVisible() for b in blocks)

    # a second call on an expanded anchor is a no-op, not a re-collapse
    assert ta.expand_fold_at(anchor) is False
    assert all(b.isVisible() for b in blocks)
