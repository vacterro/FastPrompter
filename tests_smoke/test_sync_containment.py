"""Phase-1 (second pass): Sync-to-Disk containment.

A project/category name is a UI string. It may contain traversal text,
drive-qualified paths, reserved names, Unicode and long names. EVERY path
Sync-to-Disk creates must stay under the resolved sync root — a hostile
project name must never write outside it.

The repro below drives the REAL window's sync_to_disk against a hostile
project name; the unit matrix in tests/test_path_safety.py proves the naming
codec itself.
"""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import tempfile

import pytest
from PyQt6.QtWidgets import QApplication

import fastprompter.core.state as state_mod
from fastprompter.main import FastPrompter

_app = QApplication.instance() or QApplication([])
_tmpdir = tempfile.mkdtemp(prefix="fastprompter_sync_cont_")


@pytest.fixture(scope="module")
def win():
    state_mod.get_db_path = lambda profile_id=1: os.path.join(_tmpdir, f"s_{profile_id}.db")
    state_mod.run_portable_backup = lambda data: None
    FastPrompter.setup_single_instance_server = lambda self: None
    FastPrompter.register_all_hotkeys = lambda self: None
    FastPrompter.unregister_all_hotkeys = lambda self: None
    w = FastPrompter()
    w.resize(960, 540)
    w.show()
    _app.processEvents()
    yield w
    w.auto_save_timer.stop()
    w.topmost_timer.stop()
    w.close()


def _snapshot_outside(root):
    """Top-level siblings of the sync root. An escape creates one of these."""
    parent = os.path.dirname(os.path.abspath(root))
    out = []
    for name in sorted(os.listdir(parent)):
        if name == os.path.basename(root):
            continue
        p = os.path.join(parent, name)
        out.append(("f" if os.path.isfile(p) else "d") + "/" + name)
    return out


@pytest.fixture()
def root(win, tmp_path):
    r = str(tmp_path / "sync_root")
    win.data["sync_path"] = r
    win.data["sync_mode"] = "Hierarchy"
    win._sync_written = {}
    yield r
    win.data["sync_path"] = ""
    win.data["sync_mode"] = "Off"


def _sync_with_project(win, cat, root):
    """Point the active project at `cat` (as a UI string) and sync a silo."""
    if cat not in win.data["cats_order"]:
        win.data["cats_order"].append(cat)
        win.data["categories"][cat] = [None] * 100
        win.data["temp_presets_all"][cat] = [""] * 10
    win.build_categories()
    idx = win.data["cats_order"].index(cat)
    win.cat_combo.setCurrentIndex(idx)
    win.on_tab_changed(idx)
    assert win.get_current_category() == cat, cat
    win.data["temp_presets"][0] = "# Hostile\nbody"
    win._sync_written = {}
    win.sync_to_disk(force=True)


class TestTraversalNames:
    @pytest.mark.parametrize("cat", [
        "..", "../outside", "..\\outside", "..\\..\\escape",
        "..\\..\\..\\escape2",
    ])
    def test_no_file_appears_outside_root(self, win, root, cat):
        outside = _snapshot_outside(root)
        _sync_with_project(win, cat, root)
        assert _snapshot_outside(root) == outside, (
            f"project name {cat!r} escaped the sync root")
        # a safe single project component was created inside the root
        assert len(os.listdir(root)) == 1


class TestCollisionFree:
    def test_case_only_names_map_to_distinct_paths(self, win, root):
        _sync_with_project(win, "Project", root)
        _sync_with_project(win, "project", root)
        dirs = {d for d in os.listdir(root) if os.path.isdir(os.path.join(root, d))}
        assert len(dirs) == 2, f"case-only names collided: {dirs}"

    def test_unicode_names_stay_inside(self, win, root):
        outside = _snapshot_outside(root)
        _sync_with_project(win, "Проект Ülesanne 日本語", root)
        _sync_with_project(win, "🎯 emoji project", root)
        assert _snapshot_outside(root) == outside
        assert len(os.listdir(root)) == 2
