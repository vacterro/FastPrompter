"""Project reorder: the right-click menu + box-mode drag path (T-1336).

The dropdown and number-box faces of the project list both reorder through
one method, ``_move_project``. It moves a project among the VISIBLE tabs by
swapping absolute positions in ``cats_order`` — so a hidden project wedged
between two visible ones is never disturbed — and keeps the moved project
selected. These checks pin that behaviour and the hidden-project invariant.
"""

import os
import tempfile

from PyQt6.QtCore import QEvent, Qt
from PyQt6.QtWidgets import QApplication

import fastprompter.core.state as state_mod
from fastprompter.main import FastPrompter

_app = QApplication.instance() or QApplication([])
_tmpdir = tempfile.mkdtemp(prefix="fastprompter_proj_reorder_")


def _make_window():
    state_mod.get_db_path = lambda profile_id=1: os.path.join(
        _tmpdir, f"test_{profile_id}.db")
    state_mod.run_portable_backup = lambda data, profile_id=1: None
    FastPrompter.setup_single_instance_server = lambda self: None
    FastPrompter.register_all_hotkeys = lambda self: None
    FastPrompter.unregister_all_hotkeys = lambda self: None
    FastPrompter._init_limit_service = lambda self: None

    # T-1343: the real window's own setup calls QApplication.setFont and
    # setStyleSheet, and closing the window undoes neither -- so every test
    # after this one inherited a 10pt font and a 3487-character global
    # stylesheet instead of the 8.25pt default. Measured: a later editor at
    # a 300px viewport then wrapped its text differently and
    # tests/test_t1339_wrapped_inline_copy.py put its inline Copy on the
    # wrong visual row, red only when both files shared a process. Snapshot
    # BEFORE the window is built -- that is the state to put back.
    before_font, before_sheet = _app.font(), _app.styleSheet()

    w = FastPrompter()
    w.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    w.data["cats_order"] = ["A", "B", "C", "D"]
    w.data["categories"] = {c: [None] * 100 for c in ["A", "B", "C", "D"]}
    w.data["hidden_categories"] = []
    w.rebuild_cat_combo(keep="A")
    _app.processEvents()
    w._test_app_typography = (before_font, before_sheet)
    return w


def _teardown(w):
    for name in ("auto_save_timer", "topmost_timer", "date_timer", "_cache_timer"):
        t = getattr(w, name, None)
        if t is not None:
            t.stop()
    if getattr(w, "_static_cursor_applied", False):
        QApplication.restoreOverrideCursor()
        w._static_cursor_applied = False
    w.close()
    _app.processEvents()
    QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    # T-1343: put back what the window's own setup changed on the SHARED
    # QApplication. Without this the process keeps the 10pt font and the
    # global stylesheet for every test that follows, in this file and in
    # every other one.
    font, sheet = getattr(w, "_test_app_typography", (None, None))
    if font is not None and _app.font() != font:
        _app.setFont(font)
    if sheet is not None and _app.styleSheet() != sheet:
        _app.setStyleSheet(sheet)


def test_the_window_leaves_no_typography_behind():
    """T-1343 oracle: the leak this file caused, asserted where it happens.

    Read the application state after _make_window + _teardown rather than
    trusting a later, differently-laid-out test to notice it: by the time a
    downstream geometry test fails the cause is one file away and invisible.
    """
    font, sheet = _app.font(), _app.styleSheet()
    w = _make_window()
    _teardown(w)
    assert _app.font() == font, f"leaked font {_app.font().family()} " \
                                 f"{_app.font().pointSizeF()}"
    assert _app.styleSheet() == sheet, \
        f"leaked {len(_app.styleSheet())} chars of global stylesheet"


def test_move_right_swaps_visible_neighbours():
    w = _make_window()
    try:
        w._move_project(1, 1)  # move B right, past C
        assert w.data["cats_order"] == ["A", "C", "B", "D"]
        # the moved project stays selected under the pointer
        assert w.get_current_category() == "B"
    finally:
        _teardown(w)


def test_move_left_swaps_visible_neighbours():
    w = _make_window()
    try:
        w._move_project(2, -1)  # move C left, past B
        assert w.data["cats_order"] == ["A", "C", "B", "D"]
        assert w.get_current_category() == "C"
    finally:
        _teardown(w)


def test_move_at_ends_is_noop():
    w = _make_window()
    try:
        w._move_project(0, -1)          # already leftmost
        w._move_project(3, 1)           # already rightmost
        assert w.data["cats_order"] == ["A", "B", "C", "D"]
    finally:
        _teardown(w)


def test_hidden_project_between_neighbours_is_undisturbed():
    """B hidden; visible list is [A, C, D]. Moving A right past C must swap
    only A and C in cats_order and leave hidden B exactly where it sat."""
    w = _make_window()
    try:
        w.data["hidden_categories"] = ["B"]
        w.rebuild_cat_combo(keep="A")
        assert w.visible_categories() == ["A", "C", "D"]
        w._move_project(0, 1)  # move A right, past the visible neighbour C
        # A and C swapped; B (hidden) stayed between them in absolute order
        assert w.data["cats_order"] == ["C", "B", "A", "D"]
        assert w.visible_categories() == ["C", "A", "D"]
    finally:
        _teardown(w)


if __name__ == "__main__":
    test_move_right_swaps_visible_neighbours()
    test_move_left_swaps_visible_neighbours()
    test_move_at_ends_is_noop()
    test_hidden_project_between_neighbours_is_undisturbed()
    print("OK")
