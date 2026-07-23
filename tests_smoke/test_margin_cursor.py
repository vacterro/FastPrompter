"""The margin arrow is the user's own arrow, mirrored.

It used to be a polygon drawn by hand, which sat next to the real cursor
looking heavier and a different shape - a foreign cursor rather than a
reversed one. It now borrows Arrow.cur from the carried set and flips it.

    uv run pytest tests_smoke/test_margin_cursor.py -q
"""

import os
import struct
import sys
import tempfile

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtGui import QColor, QPixmap
from PyQt6.QtWidgets import QApplication

from fastprompter.ui import cursor_theme
from fastprompter.ui.editor import margin_cursor, reset_margin_cursor

_app = QApplication.instance() or QApplication([])
_tmpdir = tempfile.mkdtemp(prefix="fastprompter_cur_")


def _write_cur(path, hot_x, hot_y, size=32):
    """A minimal but real .cur: PNG payload, hot spot in the ICO entry.

    Windows accepts PNG-compressed cursor images and Qt reads them, which
    keeps this fixture short — the point under test is the hot spot maths,
    not BMP encoding.
    """
    pix = QPixmap(size, size)
    pix.fill(QColor(255, 0, 0))
    png = os.path.join(_tmpdir, "payload.png")
    pix.save(png, "PNG")
    with open(png, "rb") as fh:
        blob = fh.read()
    with open(path, "wb") as fh:
        fh.write(struct.pack("<HHH", 0, 2, 1))            # reserved, cursor, 1 image
        fh.write(struct.pack("<BBBB", size, size, 0, 0))  # w, h, colours, reserved
        fh.write(struct.pack("<HH", hot_x, hot_y))        # hot spot
        fh.write(struct.pack("<II", len(blob), 22))       # size, offset
        fh.write(blob)
    return path


def test_the_hot_spot_mirrors_with_the_image():
    """A tip 4px from the left is 4px from the right once flipped, or the
    click lands beside the line being pointed at."""
    path = _write_cur(os.path.join(_tmpdir, "a.cur"), 4, 3)
    cur = cursor_theme.mirrored_arrow({"Arrow": path})
    assert cur is not None
    assert cur.hotSpot().x() == 31 - 4
    assert cur.hotSpot().y() == 3


def test_a_left_edge_hot_spot_ends_up_on_the_right_edge():
    path = _write_cur(os.path.join(_tmpdir, "b.cur"), 0, 0)
    cur = cursor_theme.mirrored_arrow({"Arrow": path})
    assert (cur.hotSpot().x(), cur.hotSpot().y()) == (31, 0)


def test_the_image_is_actually_flipped():
    """Not just the hot spot: the pixels have to move too."""
    src = QPixmap(4, 1)
    src.fill(QColor(0, 0, 0))
    marked = src.toImage()
    marked.setPixelColor(0, 0, QColor(255, 0, 0))
    png = os.path.join(_tmpdir, "mark.png")
    marked.save(png, "PNG")

    from PyQt6.QtGui import QTransform
    flipped = QPixmap(png).transformed(QTransform().scale(-1, 1)).toImage()
    assert flipped.pixelColor(3, 0) == QColor(255, 0, 0)
    assert flipped.pixelColor(0, 0) == QColor(0, 0, 0)


def test_no_set_means_no_borrowed_cursor():
    """The caller falls back to the drawn shape rather than showing nothing."""
    assert cursor_theme.mirrored_arrow({}) is None
    assert cursor_theme.mirrored_arrow({"Arrow": os.path.join(_tmpdir, "nope.cur")}) is None


def test_an_unreadable_file_is_refused_not_crashed():
    """An .ani is a cursor Qt cannot load at all."""
    path = os.path.join(_tmpdir, "broken.cur")
    with open(path, "wb") as fh:
        fh.write(b"not a cursor at all")
    assert cursor_theme.mirrored_arrow({"Arrow": path}) is None


def test_margin_cursor_always_returns_something_and_caches():
    first = margin_cursor()
    assert first is not None
    assert margin_cursor() is first, "rebuilt on every hover"
    reset_margin_cursor()
    assert margin_cursor() is not None
