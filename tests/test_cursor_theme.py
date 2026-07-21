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

# --------------------------------------------------- the program's own copy

def test_scheme_order_matches_what_windows_writes():
    """A saved scheme is one comma-separated string with no role names in
    it, so this order IS the schema. Getting it wrong would silently map
    the wrong file to every role."""
    from fastprompter.ui.cursor_theme import _SCHEME_ORDER

    assert _SCHEME_ORDER[:6] == (
        "Arrow", "Help", "AppStarting", "Wait", "Crosshair", "IBeam")
    assert len(_SCHEME_ORDER) == 17
    assert len(set(_SCHEME_ORDER)) == 17


def test_capture_copies_the_files_rather_than_pointing_at_them(monkeypatch):
    """The whole reason this exists: the set must keep working after the
    system scheme is switched to something else."""
    import fastprompter.ui.cursor_theme as ct

    source = tempfile.mkdtemp()
    store = tempfile.mkdtemp()
    arrow = os.path.join(source, "arrow.cur")
    _write_cur(arrow, 0, 0)

    monkeypatch.setattr(ct, "bundle_dir", lambda: os.path.join(store, "cursors"))
    monkeypatch.setattr(ct, "_manifest_path",
                        lambda: os.path.join(store, "cursors", "scheme.json"))
    monkeypatch.setattr(ct, "best_available_scheme",
                        lambda: ("MySet", {"Arrow": arrow}))

    name, paths = ct.capture_current_scheme()
    assert name == "MySet"
    copied = paths["Arrow"]
    assert os.path.isfile(copied)
    assert os.path.dirname(copied) != source, "it must be a copy, not a link"

    # the source disappearing must not matter any more
    os.remove(arrow)
    back_name, back = ct.load_bundle()
    assert back_name == "MySet"
    assert os.path.isfile(back["Arrow"])


def test_load_bundle_without_a_copy_is_empty(monkeypatch):
    import fastprompter.ui.cursor_theme as ct

    empty = tempfile.mkdtemp()
    monkeypatch.setattr(ct, "bundle_dir", lambda: empty)
    monkeypatch.setattr(ct, "_manifest_path",
                        lambda: os.path.join(empty, "scheme.json"))
    assert ct.load_bundle() == ("", {})


def test_a_corrupt_manifest_does_not_raise(monkeypatch):
    import fastprompter.ui.cursor_theme as ct

    folder = tempfile.mkdtemp()
    manifest = os.path.join(folder, "scheme.json")
    with open(manifest, "w", encoding="utf-8") as fh:
        fh.write("{not json at all")
    monkeypatch.setattr(ct, "bundle_dir", lambda: folder)
    monkeypatch.setattr(ct, "_manifest_path", lambda: manifest)
    assert ct.load_bundle() == ("", {})


def test_a_manifest_naming_missing_files_yields_nothing(monkeypatch):
    import json

    import fastprompter.ui.cursor_theme as ct

    folder = tempfile.mkdtemp()
    manifest = os.path.join(folder, "scheme.json")
    with open(manifest, "w", encoding="utf-8") as fh:
        json.dump({"name": "Gone", "files": {"Arrow": "arrow.cur"}}, fh)
    monkeypatch.setattr(ct, "bundle_dir", lambda: folder)
    monkeypatch.setattr(ct, "_manifest_path", lambda: manifest)
    name, paths = ct.load_bundle()
    assert name == "Gone" and paths == {}


def test_best_available_prefers_the_applied_scheme(monkeypatch):
    import fastprompter.ui.cursor_theme as ct

    monkeypatch.setattr(ct, "read_scheme", lambda: ("Live", {"Arrow": "a.cur"}))
    monkeypatch.setattr(ct, "read_named_schemes",
                        lambda: {"___CURRENT___": {"Arrow": "b.cur"}})
    assert ct.best_available_scheme() == ("Live", {"Arrow": "a.cur"})


def test_best_available_falls_back_to_the_users_own_saved_scheme(monkeypatch):
    """Switching Windows back to stock empties the applied values while the
    user's scheme stays saved - which is exactly when they want to grab it."""
    import fastprompter.ui.cursor_theme as ct

    monkeypatch.setattr(ct, "read_scheme", lambda: ("", {}))
    monkeypatch.setattr(ct, "read_named_schemes", lambda: {
        "Some Other": {"Arrow": "x.cur"},
        "___CURRENT___": {"Arrow": "mine.cur", "IBeam": "beam.cur"},
    })
    name, paths = ct.best_available_scheme()
    assert name == "___CURRENT___"
    assert paths["Arrow"] == "mine.cur"


def test_with_no_obvious_set_the_richest_one_wins(monkeypatch):
    import fastprompter.ui.cursor_theme as ct

    monkeypatch.setattr(ct, "read_scheme", lambda: ("", {}))
    monkeypatch.setattr(ct, "read_named_schemes", lambda: {
        "small": {"Arrow": "a.cur"},
        "big": {"Arrow": "a.cur", "IBeam": "b.cur", "Hand": "c.cur"},
    })
    assert ct.best_available_scheme()[0] == "big"


def test_nothing_saved_and_nothing_applied(monkeypatch):
    import fastprompter.ui.cursor_theme as ct

    monkeypatch.setattr(ct, "read_scheme", lambda: ("", {}))
    monkeypatch.setattr(ct, "read_named_schemes", lambda: {})
    assert ct.best_available_scheme() == ("", {})
