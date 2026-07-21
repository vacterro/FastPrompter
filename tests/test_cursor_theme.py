"""Tests for fastprompter.ui.cursor_theme — the user's own cursor set."""

import os
import struct
import sys
import tempfile

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))


def _write_cur(path, hot_x, hot_y, kind=2, count=1):
    """A minimal .cur header: an ICO whose planes/bitcount carry the hot spot."""
    with open(path, "wb") as fh:
        fh.write(struct.pack("<HHH", 0, kind, count))
        fh.write(struct.pack("<BBBB", 32, 32, 0, 0))
        fh.write(struct.pack("<HH", hot_x, hot_y))
        fh.write(struct.pack("<II", 0, 22))


def test_hotspot_is_read_from_the_header():
    """Without this every cursor would click from its top-left corner."""
    from fastprompter.ui.cursor_theme import _cur_hotspot

    path = os.path.join(tempfile.mkdtemp(), "a.cur")
    _write_cur(path, 15, 16)
    assert _cur_hotspot(path) == (15, 16)


def test_an_icon_is_not_a_cursor():
    from fastprompter.ui.cursor_theme import _cur_hotspot

    path = os.path.join(tempfile.mkdtemp(), "b.ico")
    _write_cur(path, 3, 4, kind=1)          # kind 1 is an icon
    assert _cur_hotspot(path) is None


def test_junk_files_do_not_raise():
    from fastprompter.ui.cursor_theme import _cur_hotspot

    folder = tempfile.mkdtemp()
    empty = os.path.join(folder, "empty.cur")
    open(empty, "wb").close()
    assert _cur_hotspot(empty) is None

    short = os.path.join(folder, "short.cur")
    with open(short, "wb") as fh:
        fh.write(struct.pack("<HHH", 0, 2, 1))   # header but no entry
    assert _cur_hotspot(short) is None

    assert _cur_hotspot(os.path.join(folder, "missing.cur")) is None


def test_zero_image_count_is_rejected():
    from fastprompter.ui.cursor_theme import _cur_hotspot

    path = os.path.join(tempfile.mkdtemp(), "c.cur")
    _write_cur(path, 1, 1, count=0)
    assert _cur_hotspot(path) is None


def test_unreadable_paths_are_simply_skipped():
    """A scheme pointing at files that are gone must yield an empty map,
    not an exception on startup."""
    from fastprompter.ui.cursor_theme import build_cursor_map

    assert build_cursor_map({"Arrow": "V:/nope/does-not-exist.cur"}) == {}
    assert build_cursor_map({}) == {}


def test_the_role_table_covers_the_shapes_that_matter():
    """PyQt6 is stubbed in this suite, so the shapes themselves are checked
    in tests_smoke against real Qt; here just guard the role names, which
    are what the Windows registry actually uses."""
    from fastprompter.ui.cursor_theme import _ROLE_TO_SHAPE

    for role in ("Arrow", "IBeam", "Hand", "SizeAll", "Wait"):
        assert role in _ROLE_TO_SHAPE


def test_the_full_set_url_is_the_users_own():
    from fastprompter.ui.cursor_theme import DEVIANTART_URL

    assert DEVIANTART_URL.startswith("https://www.deviantart.com/potatoddas/")
