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


def test_transfer_moves_full_identity(win, tmp_path, monkeypatch):
    # Point the files root at a PRIVATE temp dir so the transfer's physical
    # folder move (CORE-004) never touches the real data/files tree and no
    # F/F-2/F-3 residue accumulates across runs.
    files_root = str(tmp_path / "files")
    os.makedirs(files_root, exist_ok=True)
    monkeypatch.setattr(win, "_files_root", lambda: files_root)
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
    # W2-003: use canonical store names, never the nonexistent silo_types_all
    win.data.setdefault("silo_type_all", {})[CUR] = {"0": "kanban"}
    win.data.setdefault("silo_colors_all", {})[CUR] = {"0": "C"}
    win.data.setdefault("silo_last_edited_all", {})[CUR] = {0: 123}
    win.data.setdefault("silo_view_state_all", {})[CUR] = {"s0": {"cursor": 5}}
    win.data.setdefault("watcher_queues_all", {})[CUR] = {"0": ["q"]}
    # CORE-004: the mapped source folder must exist on disk or transfer refuses
    comp = win._category_files_dir(CUR)
    src_dir = os.path.join(win._files_root(), comp, "F")
    os.makedirs(src_dir, exist_ok=True)

    ok = win.transfer_silo_to_project(0, "B")
    assert ok is True

    # destination B owns the full identity (allocated at slot 1)
    assert win.data["temp_presets_all"]["B"][1] == "SRC"
    assert win.data["silo_folders_all"]["B"].get("1") == "F"
    assert win.data["silo_project_paths_all"]["B"].get("1") == "P"
    # W2-003: read from canonical store
    assert win.data["silo_type_all"]["B"].get("1") == "kanban"
    assert win.data["silo_colors_all"]["B"].get("1") == "C"
    assert win.data["silo_last_edited_all"]["B"].get(1) == 123
    assert win.data["watcher_queues_all"]["B"].get("1") == ["q"]
    assert win.data["silo_view_state_all"]["B"].get("s1", {}).get("cursor") == 5

    # source owns none
    assert "0" not in win.data["silo_folders_all"][CUR]
    assert "0" not in win.data["silo_project_paths_all"][CUR]
    # W2-003: source canonical stores cleared
    assert "0" not in win.data["silo_type_all"][CUR]
    assert "0" not in win.data["silo_colors_all"][CUR]
    assert 0 not in win.data["silo_last_edited_all"][CUR]
    assert "0" not in win.data["watcher_queues_all"][CUR]
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


# ----------------------------------------------------------------- W2-003
def test_transfer_sync_map_resolves_absolute_file_identity(win, tmp_path, monkeypatch):
    """W2-003: a Sync-Project map entry's identity is (root, relative path).
    Cross-project transfer with DIFFERENT roots must preserve the EXACT
    physical file as an absolute link, never reinterpret the relative path
    under the destination root."""
    files_root = str(tmp_path / "files")
    os.makedirs(files_root, exist_ok=True)
    monkeypatch.setattr(win, "_files_root", lambda: files_root)

    rootA = str(tmp_path / "projA")
    rootB = str(tmp_path / "projB")
    os.makedirs(rootA, exist_ok=True)
    os.makedirs(rootB, exist_ok=True)
    with open(os.path.join(rootA, "same.txt"), "w", encoding="utf-8") as f:
        f.write("CONTENT-A")
    with open(os.path.join(rootB, "same.txt"), "w", encoding="utf-8") as f:
        f.write("CONTENT-B")

    if "B" not in win.data["categories"]:
        win.data["categories"]["B"] = [None] * 100
        win.data["cats_order"].append("B")
        win.data["temp_presets_all"]["B"] = ["", "", ""]
    _set_silos(win, ["SRC", "", ""])
    win.active_is_archive = False

    win.data.setdefault("project_sync_all", {})[CUR] = {"root": rootA}
    win.data.setdefault("project_sync_all", {})["B"] = {"root": rootB}
    win.data.setdefault("project_sync_map_all", {})[CUR] = {"0": "same.txt"}
    # the physical source file must exist (transfer preflight resolves it)
    src_dir = os.path.join(files_root, win._category_files_dir(CUR), "F") \
        if os.path.isdir(os.path.join(files_root, win._category_files_dir(CUR))) \
        else os.path.join(files_root)
    os.makedirs(os.path.join(files_root), exist_ok=True)

    ok = win.transfer_silo_to_project(0, "B")
    assert ok is True

    # destination must NOT carry a stale relative map under B's root
    assert "0" not in (win.data.get("project_sync_map_all", {}).get("B") or {})
    # the source map entry is gone
    assert "0" not in (win.data.get("project_sync_map_all", {}).get(CUR) or {})
    # the EXACT physical file is preserved as an absolute link
    links = win.data.get("silo_links_all", {}).get("B", {})
    assert links, "expected an absolute per-silo link in destination"
    link = next(iter(links.values()))
    assert os.path.normcase(link) == os.path.normcase(
        os.path.join(rootA, "same.txt")), link
    assert open(link, encoding="utf-8").read() == "CONTENT-A"


def test_transfer_sync_map_same_root_keeps_relative_map(win, tmp_path, monkeypatch):
    """W2-003: when both projects share the SAME root, the relative map entry
    stays a project map entry (the path keeps its meaning)."""
    files_root = str(tmp_path / "files")
    os.makedirs(files_root, exist_ok=True)
    monkeypatch.setattr(win, "_files_root", lambda: files_root)

    rootX = str(tmp_path / "projX")
    os.makedirs(rootX, exist_ok=True)
    with open(os.path.join(rootX, "file.txt"), "w", encoding="utf-8") as f:
        f.write("X")

    # isolate from prior tests sharing the session `win` fixture
    for store in ("temp_presets_all", "silo_links_all", "project_sync_map_all",
                  "project_sync_all"):
        if isinstance(win.data.get(store), dict):
            win.data[store].pop("B", None)

    if "B" not in win.data["categories"]:
        win.data["categories"]["B"] = [None] * 100
        win.data["cats_order"].append("B")
        win.data["temp_presets_all"]["B"] = ["", "", ""]
    _set_silos(win, ["SRC", "", ""])
    win.active_is_archive = False

    win.data.setdefault("project_sync_all", {})[CUR] = {"root": rootX}
    win.data.setdefault("project_sync_all", {})["B"] = {"root": rootX}
    win.data.setdefault("project_sync_map_all", {})[CUR] = {"0": "file.txt"}

    ok = win.transfer_silo_to_project(0, "B")
    assert ok is True
    assert (win.data.get("project_sync_map_all", {}).get("B") or {}).get("0") == "file.txt"


# ----------------------------------------------------------------- W2-004
def test_sync_baseline_scoped_to_owner(win, tmp_path, monkeypatch):
    """W2-004: a sync baseline written under one category must not leak into
    another category sharing the same physical file."""
    files_root = str(tmp_path / "files")
    os.makedirs(files_root, exist_ok=True)
    monkeypatch.setattr(win, "_files_root", lambda: files_root)

    shared = os.path.join(str(tmp_path), "shared.txt")
    with open(shared, "w", encoding="utf-8") as f:
        f.write("FILE")

    if "B" not in win.data["categories"]:
        win.data["categories"]["B"] = [None] * 100
        win.data["cats_order"].append("B")
    win.data.setdefault("temp_presets_all", {}).setdefault("B", ["", "", ""])
    _set_silos(win, ["A-TEXT", "", ""])

    # category A: slot 0 binds the shared file, baseline = FILE content
    win.data.setdefault("silo_links", {})["0"] = shared
    win.data.setdefault("silo_links_all", {})[CUR] = {"0": shared}
    win._sync_last_applied[win._sync_baseline_key(0, shared, CUR)] = "FILE"

    # category B: slot 0 binds the SAME file, B has written a newer version
    win.data.setdefault("silo_links_all", {})["B"] = {"0": shared}
    win._sync_last_applied[win._sync_baseline_key(0, shared, "B")] = "B-TEXT"

    # A must NOT see B's baseline as its own
    assert win._sync_last_applied.get(
        win._sync_baseline_key(0, shared, CUR)) == "FILE"
    assert win._sync_last_applied.get(
        win._sync_baseline_key(0, shared, "B")) == "B-TEXT"
    # the path alone resolves to nothing: every baseline is owner-scoped
    assert not any(
        (isinstance(k, tuple) and k[2] == os.path.normcase(shared)
         and k[0] not in (CUR, "B")) for k in win._sync_last_applied)


# ----------------------------------------------------------------- T-1037
def test_sync_baseline_stores_digest_not_body(win, tmp_path):
    """T-1037 (PERF-007 remainder): _sync_last_applied values are compact
    digests, never full document bodies."""
    shared = os.path.join(str(tmp_path), "digest.txt")
    with open(shared, "w", encoding="utf-8") as f:
        f.write("x" * 100000)
    big_text = "y" * 100000
    key = win._sync_baseline_key(0, shared, CUR)
    win._sync_last_applied[key] = win._sync_side_digest(big_text)
    stored = win._sync_last_applied[key]
    # compact: a (len, digest) tuple, not the 100k body
    assert isinstance(stored, tuple) and len(stored) == 2
    assert stored[0] == 100000
    assert len(stored[1]) == 16  # blake2b digest_size=16
    # self-write recognition still works through the digest
    assert stored == win._sync_side_digest(big_text)
    assert stored != win._sync_side_digest("different")
