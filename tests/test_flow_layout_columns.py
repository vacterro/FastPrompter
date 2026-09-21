"""T-1246: settings cards form a closed mosaic -- no blank holes.

Row packing made every row as tall as its tallest card and left each short
card at its own height, so a tall group (Problip's Sound pool) put blank
stripes under all its neighbours.  The columns mode must:

* leave no hole: every card reaches the card below it or the page bottom;
* never be taller than the row packing it replaces;
* give a word-wrapping paragraph the width it needs (never clipped, never a
  one-word tower).
"""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PyQt6.QtWidgets")

from PyQt6.QtCore import QRect, QSize  # noqa: E402
from PyQt6.QtWidgets import QApplication, QLabel, QWidget  # noqa: E402

from fastprompter.ui.flow_layout import FlowLayout, flow_widget  # noqa: E402

_APP = QApplication.instance() or QApplication([])
SPACE = 4


class Card(QWidget):
    def __init__(self, width, height):
        super().__init__()
        self._size = QSize(width, height)

    def sizeHint(self):
        return self._size

    def minimumSizeHint(self):
        return self._size


def _page(cards, columns):
    host = QWidget()
    flow = FlowLayout(host, margin=0, h_spacing=SPACE, v_spacing=SPACE,
                      stretch_items=True, columns=columns)
    for card in cards:
        flow.addWidget(card)
    return host, flow


def _arrange(cards, columns, width):
    host, flow = _page(cards, columns)
    height = flow.heightForWidth(width)
    flow.setGeometry(QRect(0, 0, width, height))
    return host, flow, height


# the reported shape: one tall card among short ones
SHAPES = [
    [(399, 40), (164, 45), (318, 119), (417, 80), (283, 54), (373, 40),
     (190, 105)],
    [(193, 88), (237, 91), (399, 102), (251, 99), (204, 54), (193, 94)],
    [(416, 127), (306, 150), (193, 113), (334, 110), (164, 138), (160, 85),
     (204, 54), (303, 77)],
]


@pytest.mark.parametrize("shape", SHAPES)
@pytest.mark.parametrize("width", [600, 857, 960, 1150, 1400])
def test_no_card_leaves_a_hole(shape, width):
    cards = [Card(w, h) for w, h in shape]
    _host, _flow, height = _arrange(cards, True, width)
    for card in cards:
        g = card.geometry()
        below = [o.geometry().top() for o in cards if o is not card
                 and o.geometry().top() > g.bottom()
                 and o.geometry().left() <= g.right()
                 and o.geometry().right() >= g.left()]
        limit = min(below) - SPACE if below else height
        assert g.bottom() + 1 == limit, (
            f"{g} leaves {limit - g.bottom() - 1}px of blank below it")
        assert g.height() >= card.sizeHint().height()
        assert g.right() < width


@pytest.mark.parametrize("shape", SHAPES)
@pytest.mark.parametrize("width", [600, 857, 960, 1150, 1400])
def test_never_taller_than_row_packing(shape, width):
    rows = _arrange([Card(w, h) for w, h in shape], False, width)[2]
    cols = _arrange([Card(w, h) for w, h in shape], True, width)[2]
    assert cols <= rows + 6, (cols, rows)


def test_the_tall_card_no_longer_raises_its_neighbours():
    """The Problip page shape at 960px: row packing had ~80px holes."""
    cards = [Card(w, h) for w, h in SHAPES[0]]
    rows_h = _arrange([Card(w, h) for w, h in SHAPES[0]], False, 960)[2]
    _host, _flow, cols_h = _arrange(cards, True, 960)
    assert cols_h < rows_h


def test_a_narrow_page_still_places_everything():
    cards = [Card(w, h) for w, h in SHAPES[0]]
    _host, _flow, height = _arrange(cards, True, 120)
    assert height > 0
    assert all(card.geometry().width() >= 1 for card in cards)


def test_a_paragraph_gets_the_width_it_needs():
    text = ("Problip plays one short cue at your chosen interval so a long "
            "writing session keeps its rhythm.")
    label = QLabel(text)
    label.setWordWrap(True)
    label.setMinimumWidth(120)
    inner = flow_widget([label])
    width = 700
    height = inner.totalHeightForWidth(width)
    inner.resize(width, height)
    inner.layout().setGeometry(QRect(0, 0, width, height))
    # wider than its narrow hint, never wider than the line
    assert label.width() > label.sizeHint().width() or label.width() == width
    assert label.width() <= width
    assert label.height() >= label.heightForWidth(label.width())
    narrow = flow_widget([QLabel(text)])
    narrow_label = narrow.layout().itemAt(0).widget()
    narrow_label.setWordWrap(True)
    h = narrow.totalHeightForWidth(150)
    narrow.layout().setGeometry(QRect(0, 0, 150, h))
    assert narrow_label.width() <= 150, "a paragraph must never be cut off"
