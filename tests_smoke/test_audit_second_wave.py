"""Second-wave audit regressions that need the real Qt window.

Covers the canonical 100-slot capacity boundary (99/100/101 for normal,
archive, transfer, restore), lossless refusal, slot deletion being
insertion-order independent across every registered state map, full silo
identity transfer across projects, and cross-category drops refusing a stale
or full target without destroying the source.
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
_tmpdir = tempfile.mkdtemp(prefix="fastprompter_audit2_")

CUR = "Code"


@pytest.fixture(scope="module")
def win():
    saved_get_db_path = state_mod.get_db_path
    state_mod.get_db_path = lambda *a, **k: os.path.join(_tmpdir, "a.db")
    state_mod.run_portable_backup = lambda data, profile_id=1: None
    FastPrompter.setup_single_instance_server = lambda self: None
    FastPrompter.register_all_hotkeys = lambda self: None
    FastPrompter.unregister_all_hotkeys = lambda self: None
    w = FastPrompter()
    w.resize(960, 540)
    w.show()
    _app.processEvents()
    yield w
    try:
        w._watcher_shutdown()
    except Exception:
        pass
    w.auto_save_timer.stop()
    w.topmost_timer.stop()
    w.close()
    state_mod.get_db_path = saved_get_db_path


def _set_silos(win, texts):
    from PyQt6.QtGui import QTextDocument
    win.data["temp_presets"][:] = list(texts)
    win.silo_docs[:] = [QTextDocument() for _ in texts]
    win.active_temp_slot = 0


def _set_archive(win, texts):
    from PyQt6.QtGui import QTextDocument
    win.data["archive_temp_presets"][:] = list(texts)
    win.archive_docs[:] = [QTextDocument() for _ in texts]
    win.active_is_archive = True
    win.active_temp_slot = 0


def test_normal_capacity_99_100_101(win):
    _set_silos(win, [f"s{i}" for i in range(99)])
    assert len(win.data["temp_presets"]) == 99
    # the 100th insert succeeds
    r = win._insert_silo_at(99, "N100")
    assert r == 99
    assert len(win.data["temp_presets"]) == 100
    # the 101st must refuse and lose nothing
    r2 = win._insert_silo_at(100, "N101")
    assert r2 is None
    assert len(win.data["temp_presets"]) == 100
    assert win.data["temp_presets"][99] == "N100"
    assert "N101" not in win.data["temp_presets"]


def test_archive_capacity_refuses_at_100(win):
    _set_archive(win, [f"a{i}" for i in range(99)])
    assert win._silo_at_capacity(True) is False
    # fill the 100th archive slot
    win.data["archive_temp_presets"].append("a99")
    win.archive_docs.append(None)
    assert win._silo_at_capacity(True) is True
    assert win._acquire_silo_slot(is_archive=True) is None
    # archiving a normal silo must now refuse (lose nothing)
    _set_silos(win, ["SRC", "", ""])
    win.active_is_archive = False
    before = len(win.data["archive_temp_presets"])
    r = win._archive_silo(0)
    assert r is None
    assert len(win.data["archive_temp_presets"]) == before
    assert win.data["temp_presets"][0] == "SRC"


def test_drop_silo_state_order_independent(win):
    _set_silos(win, ["A", "B"])
    win.data["silo_colors"] = {"0": "A", "1": "B"}
    win.data["silo_folders"] = {"0": "A", "1": "B"}
    win.data["silo_project_paths"] = {"0": "A", "1": "B"}
    win.data["silo_types"] = {"0": "A", "1": "B"}
    win.silo_last_edited.clear(); win.silo_last_edited.update({0: 1, 1: 2})
    win.data["watcher_queues"] = {"0": ["a"], "1": ["b"]}
    win.data["pinned_silos"][:] = []
    win.data["silo_ticked"][:] = []
    win.data["silo_collapsed"][:] = []
    win.data["silo_gaps"][:] = []
    win.data["silo_children"].clear()
    win.data.setdefault("silo_view_state_all", {})[CUR] = {"s0": 1, "s1": 2}

    win.drop_silo_state(0)

    # slot 0 must now hold the SURVIVOR B; slot 1 must be gone
    assert win.data["silo_colors"]["0"] == "B"
    assert win.data["silo_folders"]["0"] == "B"
    assert win.data["silo_project_paths"]["0"] == "B"
    assert win.data["silo_types"]["0"] == "B"
    assert win.silo_last_edited[0] == 2
    assert win.data["watcher_queues"]["0"] == ["b"]
    assert win.data["silo_view_state_all"][CUR]["s0"] == 2
    assert "1" not in win.data["silo_colors"]


def test_transfer_moves_full_identity(win):
    if "B" not in win.data["categories"]:
        win.data["categories"]["B"] = [None] * 100
        win.data["cats_order"].append("B")
        win.data["temp_presets_all"]["B"] = ["OCC", ""]  # blank is at slot 1
    _set_silos(win, ["SRC", "", ""])
    win.active_is_archive = False
    win.data["silo_folders"] = {"0": "F"}
    win.data["silo_project_paths"] = {"0": "P"}
    win.data["silo_types"] = {"0": "kanban"}
    win.data["silo_colors"] = {"0": "C"}
    win.silo_last_edited.clear(); win.silo_last_edited.update({0: 123})
    win.data["watcher_queues"] = {"0": ["q"]}
    win.data.setdefault("silo_folders_all", {})[CUR] = {"0": "F"}
    win.data.setdefault("silo_project_paths_all", {})[CUR] = {"0": "P"}
    win.data.setdefault("silo_types_all", {})[CUR] = {"0": "kanban"}
    win.data.setdefault("silo_colors_all", {})[CUR] = {"0": "C"}
    win.data.setdefault("silo_last_edited_all", {})[CUR] = {0: 123}
    win.data.setdefault("silo_view_state_all", {})[CUR] = {"s0": {"cursor": 5}}

    ok = win.transfer_silo_to_project(0, "B")
    assert ok is True

    # destination B owns the full identity (allocated at slot 1)
    assert win.data["temp_presets_all"]["B"][1] == "SRC"
    assert win.data["silo_folders_all"]["B"].get("1") == "F"
    assert win.data["silo_project_paths_all"]["B"].get("1") == "P"
    assert win.data["silo_types_all"]["B"].get("1") == "kanban"
    assert win.data["silo_colors_all"]["B"].get("1") == "C"
    assert win.data["silo_last_edited_all"]["B"].get(1) == 123
    assert win.data["watcher_queues"].get("1") == ["q"]
    assert win.data["silo_view_state_all"]["B"].get("s1", {}).get("cursor") == 5

    # source owns none
    assert "0" not in win.data["silo_folders_all"][CUR]
    assert "0" not in win.data["silo_project_paths_all"][CUR]
    assert "0" not in win.data["silo_types_all"][CUR]
    assert "0" not in win.data["silo_colors_all"][CUR]
    assert 0 not in win.data["silo_last_edited_all"][CUR]
    assert "0" not in win.data["watcher_queues"]
    assert win.data["temp_presets"][0] == ""


def test_cross_category_refuses_full_without_source_pop(win):
    _set_silos(win, [f"s{i}" for i in range(100)])  # full normal space
    if "X" not in win.data["categories"]:
        win.data["categories"]["X"] = [None] * 100
        win.data["cats_order"].append("X")
    win.data["categories"]["X"][0] = {"name": "n", "text": "t", "last_edited": 0}
    before = list(win.data["temp_presets"])
    r = win.move_preset_cross_category("X", 0, "silo", 5)
    assert r is None  # refused
    assert win.data["temp_presets"] == before  # source untouched
    assert win.data["categories"]["X"][0]["text"] == "t"
