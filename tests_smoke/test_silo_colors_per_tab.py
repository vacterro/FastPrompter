"""Silo colours belong to a tab, not to a slot number.

`silo_colors_all` sat in the schema and in the rename/delete remaps from the
start, but nothing ever wrote to it and nothing aliased it, so the colours
lived in one flat dict shared by every tab. A silo has no id - it IS its
slot index - so the colour put on slot 3 in one tab showed up on whatever
silo sat at slot 3 in the next one, and disappeared again as soon as that
tab recoloured its own slot 3.

    uv run pytest tests_smoke/test_silo_colors_per_tab.py -q
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtWidgets import QApplication

import fastprompter.core.state as state_mod
from fastprompter.main import FastPrompter

_app = QApplication.instance() or QApplication([])
_tmpdir = tempfile.mkdtemp(prefix="fastprompter_colors_")


@pytest.fixture(scope="module")
def win():
    state_mod.get_db_path = lambda profile_id=1: os.path.join(_tmpdir, f"c_{profile_id}.db")
    state_mod.run_portable_backup = lambda data: None
    FastPrompter.setup_single_instance_server = lambda self: None
    FastPrompter.register_all_hotkeys = lambda self: None
    FastPrompter.unregister_all_hotkeys = lambda self: None
    w = FastPrompter()
    yield w
    w.auto_save_timer.stop()
    w.topmost_timer.stop()
    w._cache_timer.stop()
    w.state.conn = None
    w.conn = None
    w.close()


def _two_tabs(win):
    cats = win.data["cats_order"]
    if len(cats) < 2:
        pytest.skip("needs two tabs")
    return cats[0], cats[1]


def test_colours_are_aliased_to_the_current_tab(win):
    a, _b = _two_tabs(win)
    win.on_tab_changed(0)
    assert win.data["silo_colors"] is win.data["silo_colors_all"][a]


def test_a_colour_set_on_one_tab_does_not_appear_on_the_other(win):
    """The whole bug in one assertion."""
    a, b = _two_tabs(win)
    win.on_tab_changed(0)
    win.data["silo_colors"]["3"] = "#ff4444"

    win.on_tab_changed(1)
    assert win.data["silo_colors"].get("3", "") == ""
    assert win.data["silo_colors_all"][a]["3"] == "#ff4444"

    win.on_tab_changed(0)
    assert win.data["silo_colors"]["3"] == "#ff4444"
    assert b not in win.data["silo_colors_all"] or "3" not in win.data["silo_colors_all"][b]


def test_each_tab_keeps_its_own_colour_on_the_same_slot(win):
    a, b = _two_tabs(win)
    win.on_tab_changed(0)
    win.data["silo_colors"]["5"] = "#00ff00"
    win.on_tab_changed(1)
    win.data["silo_colors"]["5"] = "#0000ff"

    win.on_tab_changed(0)
    assert win.data["silo_colors"]["5"] == "#00ff00"
    win.on_tab_changed(1)
    assert win.data["silo_colors"]["5"] == "#0000ff"
    assert win.data["silo_colors_all"][a]["5"] == "#00ff00"
    assert win.data["silo_colors_all"][b]["5"] == "#0000ff"


def test_the_colour_picker_writes_through_the_alias(win):
    """A rebind here detached the tab store - colour showed, then vanished."""
    from fastprompter.ui.snippet_panel import DraggableSiloButton

    a, _b = _two_tabs(win)
    win.on_tab_changed(0)
    win.data["silo_colors"].pop("7", None)

    holder = win.data["silo_colors"]
    # drive the picker's write path without building a widget tree
    picker = DraggableSiloButton.__new__(DraggableSiloButton)
    picker.main_win = win
    picker.global_idx = 7
    DraggableSiloButton._cycle_color(picker)

    assert win.data["silo_colors"] is holder, "picker rebound the alias"
    assert win.data["silo_colors_all"][a].get("7", "") != ""


def test_colours_survive_a_save_and_reload(win):
    a, b = _two_tabs(win)
    win.on_tab_changed(0)
    win.data["silo_colors"]["9"] = "#ffaa00"
    win.on_tab_changed(1)
    win.data["silo_colors"]["9"] = "#ff00ff"
    win.save_data_to_db(force=True)

    fresh = FastPrompter()
    try:
        assert fresh.data["silo_colors_all"][a]["9"] == "#ffaa00"
        assert fresh.data["silo_colors_all"][b]["9"] == "#ff00ff"
        # a fresh window restores the tab the user left on, so the alias
        # must follow THAT tab - not blindly the first one
        cur = fresh.get_current_category()
        assert fresh.data["silo_colors"] is fresh.data["silo_colors_all"][cur]
    finally:
        fresh.auto_save_timer.stop()
        fresh.topmost_timer.stop()
        fresh._cache_timer.stop()
        fresh.state.conn = None
        fresh.conn = None
        fresh.close()
