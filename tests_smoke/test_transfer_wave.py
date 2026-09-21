"""Transfer wave: live ownership, allocation and atomic rollback."""
# ruff: noqa: F811
import copy
import os

import pytest
from PyQt6.QtCore import QPoint
from PyQt6.QtWidgets import QApplication, QMenu


@pytest.fixture
def win(fresh_win):
    return fresh_win


def prepare(win, stored="OLD", live="NEW", archive=False):
    QApplication.processEvents()
    win._initializing_ui = False
    src = win.get_current_category()
    from fastprompter.core.state import bind_active_category
    bind_active_category(win.data, src)
    win.silo_last_edited = win.data.setdefault("silo_last_edited_all", {}).setdefault(src, {})
    dst = next(c for c in win.data["categories"] if c != src)
    win.editing_snippet = None
    win.active_temp_slot = 0
    win.active_is_archive = archive
    key = "archive_temp_presets" if archive else "temp_presets"
    win.data[key][:] = [stored, "OTHER"]
    if archive:
        # T-1227: the editor must actually OWN the archive slot before the
        # live text is typed into it, or the transfer's fail-closed flush
        # refuses the mismatch (and correctly so)
        win._switch_to_slot(0, initial=True, is_archive=True)
    win.text_area.setPlainText(live)
    win._cache_timer.stop()
    win.data[key][0] = stored
    win.data["temp_presets_all"][dst] = [""]
    # This module intentionally reuses one temporary DB.  Clear only the
    # physical-folder ownership relevant to this transfer so an earlier test's
    # collision suffix cannot change the path under test.
    folder_key = ("archive_silo_folders_all" if archive
                  else "silo_folders_all")
    win.data.setdefault(folder_key, {}).setdefault(src, {}).clear()
    win.data.setdefault("silo_folders_all", {}).setdefault(dst, {}).clear()
    win.data.setdefault("silo_folders", {}).clear()
    for store_key in win._TRANSFER_STORE_KEYS:
        if store_key in ("temp_presets_all", "archive_temp_presets_all"):
            continue
        store = win.data.get(store_key)
        if isinstance(store, dict) and dst in store:
            value = store[dst]
            store[dst] = [] if isinstance(value, list) else {}
    win.data["temp_presets_all"][dst] = [""]
    # The shared temporary profile may have left a deliberately retained
    # recovery receipt from an earlier crash-window test.  Those tests own
    # their isolated tmp_path; start ordinary transfer cases with no receipt.
    win._clear_transfer_journal()
    return src, dst, key


@pytest.mark.parametrize("stored,archive", [("", False), ("OLD", False), ("", True), ("OLD", True)])
def test_direct_transfer_flushes_live_owner(win, stored, archive):
    _, dst, key = prepare(win, stored, "NEW LIVE TEXT", archive)
    assert win.transfer_silo_to_project(0, dst, archive)
    assert "NEW LIVE TEXT" in win.data["temp_presets_all"][dst]
    assert win.data[key][0] == ""


def test_empty_live_silo_menu_offers_transfer(win, monkeypatch):
    prepare(win, "", "NEW LIVE TEXT")
    menus = []
    monkeypatch.setattr(QMenu, "exec", lambda self, *a: menus.append(self))
    win.show_temp_menu(0, QPoint(0, 0))
    assert any("Transfer to Project" in a.text() for m in menus for a in m.actions())


@pytest.mark.parametrize("key,value", [
    ("pinned_silos_all", [0]), ("silo_collapsed_all", [0]),
    ("silo_children_all", {1: [0]}), ("silo_gaps_all", [0]),
    ("silo_gap_names_all", {"0": "gap"}),
])
def test_transfer_does_not_reuse_residual_slot(win, key, value):
    _, dst, _ = prepare(win)
    win.data[key][dst] = value
    assert win.transfer_silo_to_project(0, dst)
    dest = win.data["temp_presets_all"][dst]
    assert dest[0] == ""
    assert dest[-1] == "NEW"
    if key == "silo_children_all":
        assert dest[1] == ""  # the residual parent is occupied too


def test_transfer_rolls_back_metadata_failure(win, monkeypatch):
    src, dst, _ = prepare(win)
    win.commit_current_text()
    win._snapshot_current()
    before = {c: win._capture_category_stores(c) for c in (src, dst)}

    def fail(*args):
        win.data["silo_colors_all"].setdefault(dst, {})["0"] = "bad"
        raise RuntimeError("injected commit failure")

    monkeypatch.setattr(win, "_move_silo_identity", fail)
    assert win.transfer_silo_to_project(0, dst) is False
    for cat in (src, dst):
        for key, value in before[cat].items():
            assert win._capture_category_stores(cat)[key] == copy.deepcopy(value), key
    assert win.text_area.toPlainText() == "NEW"


@pytest.mark.parametrize("archive", [False, True])
def test_namespace_and_other_silo_do_not_flush_wrong_owner(win, archive):
    _, dst, _ = prepare(win, "NORMAL", "LIVE NORMAL")
    win.data["archive_temp_presets"][:] = ["ARCHIVE"]
    idx = 0 if archive else 1
    assert win.transfer_silo_to_project(idx, dst, archive)
    assert win.text_area.toPlainText() == "LIVE NORMAL"
    assert ("ARCHIVE" if archive else "OTHER") in win.data["temp_presets_all"][dst]


def test_transfer_full_target_preserves_live_source(win):
    _, dst, _ = prepare(win)
    win.data["temp_presets_all"][dst] = ["FULL"] * win.MAX_SILOS_PER_CATEGORY
    assert not win.transfer_silo_to_project(0, dst)
    assert win.text_area.toPlainText() == win.data["temp_presets"][0] == "NEW"


def test_transfer_gaps_move_and_hierarchy_detaches(win):
    src, dst, _ = prepare(win)
    win.data["silo_gaps"][:] = [0]
    win.data["silo_gap_names"]["0"] = "my gap"
    assert win.data["silo_gap_names_all"].get(src, {}).get("0") == "my gap"
    win.data["pinned_silos"][:] = [0]
    win.data["silo_collapsed"][:] = [0]
    win.data["silo_children"].update({0: [1]})
    assert win.transfer_silo_to_project(0, dst)
    slot = win.data["temp_presets_all"][dst].index("NEW")
    assert win.data["silo_gaps_all"][dst] == [slot]
    assert win.data["silo_gap_names_all"][dst][str(slot)] == "my gap"
    for key in ("silo_gaps", "pinned_silos", "silo_collapsed", "silo_children"):
        assert not win.data[key]
    assert not win.data["silo_gap_names_all"][src]


@pytest.mark.parametrize("fail", [None, "rename", "metadata"])
def test_physical_folder_transaction(win, tmp_path, monkeypatch, fail):
    import os
    src, dst, _ = prepare(win)
    monkeypatch.setattr(win, "_files_root", lambda: str(tmp_path))
    win.data["silo_folders"]["0"] = "assets"
    source = tmp_path / win._category_files_dir(src) / "assets"
    source.mkdir(parents=True)
    (source / "keep.txt").write_text("bytes")
    destination = tmp_path / win._category_files_dir(dst) / "assets"
    if fail == "rename":
        monkeypatch.setattr(os, "rename", lambda *a: (_ for _ in ()).throw(OSError("injected rename")))
    if fail == "metadata":
        monkeypatch.setattr(win, "_move_silo_identity", lambda *a: (_ for _ in ()).throw(RuntimeError("injected metadata")))
    assert win.transfer_silo_to_project(0, dst) == (fail is None)
    actual = destination if fail is None else source
    assert (actual / "keep.txt").read_text() == "bytes"
    assert not (source if fail is None else destination).exists()
    if fail:
        assert win.data["silo_folders"]["0"] == "assets"
        assert win.data["temp_presets"][0] == "NEW"


def test_transfer_switch_undo_redo_restores_both_sides(win):
    src, dst, _ = prepare(win)
    win.data["silo_colors"]["0"] = "#123456"
    win.data["silo_gaps"][:] = [0]
    assert win.transfer_silo_to_project(0, dst)
    assert win.data["temp_presets_all"][dst][0] == "NEW"
    from fastprompter.core.state import bind_active_category
    bind_active_category(win.data, dst)
    assert win.data["temp_presets"][0] == "NEW"
    win.undo_action()
    assert win.data["temp_presets_all"][src][0] == "NEW"
    assert win.data["temp_presets_all"][dst] == [""]
    win.redo_action()
    assert win.data["temp_presets_all"][src][0] == ""
    assert win.data["temp_presets_all"][dst][0] == "NEW"
    assert win.data["silo_colors_all"][dst]["0"] == "#123456"


def test_forward_ok_commit_fail_rollback_fail_requires_recovery(
        win, tmp_path, monkeypatch):
    """A failed reverse rename is failure, never a fabricated success."""
    import os
    src, dst, _ = prepare(win)
    monkeypatch.setattr(win, "_files_root", lambda: str(tmp_path))
    win.data["silo_folders"]["0"] = "assets"
    source = tmp_path / win._category_files_dir(src) / "assets"
    source.mkdir(parents=True)
    (source / "keep.txt").write_text("bytes")
    destination = tmp_path / win._category_files_dir(dst) / "assets"
    real_rename = os.rename
    real_move_identity = win._move_silo_identity

    def rename(src_path, dst_path):
        if str(dst_path) == str(destination):
            return real_rename(src_path, dst_path)  # forward succeeds
        raise OSError("injected reverse rename failure")

    monkeypatch.setattr(os, "rename", rename)
    monkeypatch.setattr(win, "_move_silo_identity",
                        lambda *a: (_ for _ in ()).throw(RuntimeError("injected metadata")))
    assert win.transfer_silo_to_project(0, dst) is False
    assert (destination / "keep.txt").read_text() == "bytes"
    assert not source.exists()
    journal = win._read_transfer_journal()
    assert journal is not None and journal["phase"] == "FILES_MOVED"
    assert journal["dst_dir"] == str(destination)
    # Startup arbitration sees durable source ownership and rolls the bytes back.
    monkeypatch.setattr(os, "rename", real_rename)
    monkeypatch.setattr(win, "_move_silo_identity", real_move_identity)
    win.data.setdefault("silo_folders_all", {}).setdefault(src, {})["0"] = "assets"
    win._reconcile_transfer_journal()
    assert win._read_transfer_journal() is None
    assert (source / "keep.txt").read_text() == "bytes"
    assert not destination.exists()


def test_physical_move_refused_without_journal(win, tmp_path, monkeypatch):
    """CORE-004b: no durable journal -> no physical rename, transfer refused."""
    src, dst, _ = prepare(win)
    monkeypatch.setattr(win, "_files_root", lambda: str(tmp_path))
    win.data["silo_folders"]["0"] = "assets"
    source = tmp_path / win._category_files_dir(src) / "assets"
    source.mkdir(parents=True)
    (source / "keep.txt").write_text("bytes")
    monkeypatch.setattr(win, "_write_transfer_journal", lambda record: False)
    assert win.transfer_silo_to_project(0, dst) is False
    assert (source / "keep.txt").read_text() == "bytes"
    assert win.data["temp_presets"][0] == "NEW"
    assert win._read_transfer_journal() is None


def test_journal_update_failure_after_rename_rolls_back(win, tmp_path, monkeypatch):
    """A lost FILES_MOVED receipt must not leave a moved, ownerless folder."""
    src, dst, _ = prepare(win)
    monkeypatch.setattr(win, "_files_root", lambda: str(tmp_path))
    win.data["silo_folders"]["0"] = "assets"
    source = tmp_path / win._category_files_dir(src) / "assets"
    source.mkdir(parents=True)
    (source / "keep.txt").write_text("bytes")
    destination = tmp_path / win._category_files_dir(dst) / "assets"
    real_write = win._write_transfer_journal
    calls = []

    def write(record):
        calls.append(record["phase"])
        return len(calls) == 1 and real_write(record)

    monkeypatch.setattr(win, "_write_transfer_journal", write)
    assert win.transfer_silo_to_project(0, dst) is False
    assert calls == ["PREPARED", "FILES_MOVED"]
    assert (source / "keep.txt").read_text() == "bytes"
    assert not destination.exists()


def test_crash_after_rename_reconciles_back(monkeypatch, tmp_path):
    """FILES_MOVED journal + missing source -> startup reconciles dst -> src."""
    import os

    from fastprompter.main import FastPrompter
    src_dir, dst_dir = tmp_path / "s", tmp_path / "d"
    dst_dir.mkdir()
    (dst_dir / "f.txt").write_text("x")
    stub = type("W", (), {})()
    stub._TRANSFER_JOURNAL = ".transfer_journal.json"
    stub._files_root = lambda: str(tmp_path)
    stub._transfer_journal_path = lambda: os.path.join(
        str(tmp_path), "_trash", ".transfer_journal.json")
    stub._data = {"archive_silo_folders_all": {},
                  "silo_folders_all": {"a": {"0": "s"}, "b": {}},
                  }
    stub.data = stub._data
    import types
    for name in ("_read_transfer_journal", "_clear_transfer_journal",
                 "_reconcile_transfer_journal", "_write_transfer_journal"):
        setattr(stub, name, types.MethodType(getattr(FastPrompter, name), stub))
    FastPrompter._write_transfer_journal(stub, {
        "txn": "1", "phase": "FILES_MOVED", "src_cat": "a", "src_idx": 0,
        "dst_cat": "b", "dst_idx": 0, "src_dir": str(src_dir),
        "dst_dir": str(dst_dir), "src_name": "s", "dst_name": "s",
        "is_archive_src": False, "ts": 0})
    FastPrompter._reconcile_transfer_journal(stub)
    assert (src_dir / "f.txt").read_text() == "x"
    assert not dst_dir.exists()
    assert FastPrompter._read_transfer_journal(stub) is None


def test_committed_destination_acknowledges_stale_journal(monkeypatch, tmp_path):
    """Durable destination ownership wins when only journal ACK was missed."""
    import os

    from fastprompter.main import FastPrompter
    src_dir, dst_dir = tmp_path / "s", tmp_path / "d"
    dst_dir.mkdir()
    (dst_dir / "f.txt").write_text("x")
    stub = type("W", (), {})()
    stub._TRANSFER_JOURNAL = ".transfer_journal.json"
    stub._files_root = lambda: str(tmp_path)
    stub._transfer_journal_path = lambda: os.path.join(
        str(tmp_path), "_trash", ".transfer_journal.json")
    stub.data = {"silo_folders_all": {"a": {}, "b": {"0": "s"}},
                 "archive_silo_folders_all": {}}
    import types
    for name in ("_read_transfer_journal", "_clear_transfer_journal",
                 "_reconcile_transfer_journal", "_write_transfer_journal"):
        setattr(stub, name, types.MethodType(getattr(FastPrompter, name), stub))
    FastPrompter._write_transfer_journal(stub, {
        "txn": "1", "phase": "FILES_MOVED", "src_cat": "a", "src_idx": 0,
        "dst_cat": "b", "dst_idx": 0, "src_dir": str(src_dir),
        "dst_dir": str(dst_dir), "src_name": "s", "dst_name": "s",
        "is_archive_src": False, "ts": 0})
    FastPrompter._reconcile_transfer_journal(stub)
    assert (dst_dir / "f.txt").read_text() == "x"
    assert FastPrompter._read_transfer_journal(stub) is None


def test_ambiguous_transfer_state_keeps_journal(monkeypatch, tmp_path):
    """Both physical locations are evidence, not permission to guess."""
    import os

    from fastprompter.main import FastPrompter
    src_dir, dst_dir = tmp_path / "s", tmp_path / "d"
    src_dir.mkdir()
    dst_dir.mkdir()
    (src_dir / "source.txt").write_text("s")
    (dst_dir / "dest.txt").write_text("d")
    stub = type("W", (), {})()
    stub._TRANSFER_JOURNAL = ".transfer_journal.json"
    stub._files_root = lambda: str(tmp_path)
    stub._transfer_journal_path = lambda: os.path.join(
        str(tmp_path), "_trash", ".transfer_journal.json")
    stub.data = {"silo_folders_all": {"a": {"0": "s"}, "b": {}},
                 "archive_silo_folders_all": {}}
    import types
    for name in ("_read_transfer_journal", "_clear_transfer_journal",
                 "_reconcile_transfer_journal", "_write_transfer_journal"):
        setattr(stub, name, types.MethodType(getattr(FastPrompter, name), stub))
    FastPrompter._write_transfer_journal(stub, {
        "txn": "1", "phase": "FILES_MOVED", "src_cat": "a", "src_idx": 0,
        "dst_cat": "b", "dst_idx": 0, "src_dir": str(src_dir),
        "dst_dir": str(dst_dir), "src_name": "s", "dst_name": "s",
        "is_archive_src": False, "ts": 0})
    FastPrompter._reconcile_transfer_journal(stub)
    assert FastPrompter._read_transfer_journal(stub) is not None
    assert (src_dir / "source.txt").read_text() == "s"
    assert (dst_dir / "dest.txt").read_text() == "d"


# ----------------------------------------------------- cross-category routes
def _cross_routes_setup(win):
    QApplication.processEvents()
    win._initializing_ui = False
    from fastprompter.core.state import bind_active_category
    src = win.get_current_category()
    bind_active_category(win.data, src)
    # default profile ships with a single category; add two scratch destinations.
    for name in ("AUDIT_B", "AUDIT_C"):
        if name not in win.data["categories"]:
            win.data["categories"][name] = [None] * 4
            win.data.setdefault("cats_order", []).append(name)
            win.data.setdefault("temp_presets_all", {})[name] = [""] * 4
    dst = "AUDIT_B"
    dst2 = "AUDIT_C"
    return src, dst, dst2


def _own_live(win, text, archive=False):
    """Make the live editor the authoritative owner of (0, archive) with text."""
    win.editing_snippet = None
    win.active_temp_slot = 0
    win.active_is_archive = archive
    win.text_area.setPlainText(text)
    win._cache_timer.stop()


@pytest.mark.parametrize("route", [("silo", "arcsilo"), ("arcsilo", "silo")])
def test_silo_space_routes_preserve_identity(win, route):
    """Normal<->archive follows the explicit identity ownership matrix.

    Folder/project path and saved view are silo identity and move.  Colours,
    type, ticks, selection, links/sync, gaps, recency and hierarchy are
    normal-list-local in the current schema (archive has no corresponding
    stores), so they are detached rather than orphaned under the old slot.
    """
    _cross_routes_setup(win)
    from_cat, to_cat = route
    for key in ("silo_folders", "silo_project_paths", "archive_silo_folders",
                "archive_project_paths"):
        win.data[key].clear()
    win.data["temp_presets"][:] = ["S", "OTHER"]
    win.data["archive_temp_presets"][:] = ["A", "OTHER"]
    win.data["silo_folders"]["0"] = "fold"
    win.data["silo_project_paths"]["0"] = "project-path"
    win.data["archive_silo_folders"]["0"] = "fold"
    win.data["archive_project_paths"]["0"] = "project-path"
    win.data["silo_colors"]["0"] = "#ABCDEF"
    win.data["silo_types"]["0"] = "kanban"
    win.data["silo_ticked"][:] = [0]
    win.data["silo_selected"][:] = [0]
    win.data["silo_links"]["0"] = "linked.txt"
    win.data["project_sync_map"]["0"] = "linked.txt"
    win.data["silo_gaps"][:] = [0]
    win.data["silo_gap_names"]["0"] = "named gap"
    win.silo_last_edited[0] = 123
    win.data.setdefault("silo_children", {})[0] = [1]
    win.data.setdefault("silo_view_state_all", {}).setdefault(
        win.get_current_category(), {})["s0"] = {"pos": 7}
    win.data["silo_view_state_all"][win.get_current_category()]["a0"] = {"pos": 7}
    _own_live(win, "S" if from_cat == "silo" else "A", from_cat == "arcsilo")
    if from_cat == "arcsilo":
        win.data["archive_silo_folders"]["0"] = "fold"
        win.data["archive_project_paths"]["0"] = "project-path"
    assert win.move_preset_cross_category(from_cat, 0, to_cat, 0) is True
    dest_key = "archive_temp_presets" if to_cat == "arcsilo" else "temp_presets"
    assert ("S" if from_cat == "silo" else "A") in win.data[dest_key]
    source_key = "archive_temp_presets" if from_cat == "arcsilo" else "temp_presets"
    assert ("S" if from_cat == "silo" else "A") not in win.data[source_key]
    if from_cat == "silo":
        assert win.data["archive_silo_folders"]["0"] == "fold"
        assert win.data["archive_project_paths"]["0"] == "project-path"
        assert win.data["silo_view_state_all"][win.get_current_category()]["a0"] == {"pos": 7}
        assert "0" not in win.data["silo_colors"]
        assert "0" not in win.data["silo_types"]
        assert not win.data["silo_ticked"]
        assert not win.data["silo_selected"]
        assert "0" not in win.data["silo_links"]
        assert "0" not in win.data["project_sync_map"]
        assert not win.data["silo_gaps"]
        assert "0" not in win.data["silo_gap_names"]
        assert 0 not in win.silo_last_edited
        assert not win.data["silo_children"]
    else:
        assert win.data["silo_folders"]["0"] == "fold"
        assert win.data["silo_project_paths"]["0"] == "project-path"
        assert win.data["silo_view_state_all"][win.get_current_category()]["s0"] == {"pos": 7}
        assert "0" not in win.data["archive_silo_folders"]
        assert "0" not in win.data["archive_project_paths"]


def test_silo_to_snippet_route(win):
    _cross_routes_setup(win)
    win.data["temp_presets"][:] = ["SILO TEXT", "OTHER"]
    _own_live(win, "SILO TEXT")
    ok = win.move_preset_cross_category("silo", 0, "AUDIT_B", 0)
    assert ok is True
    dest = win.data["categories"]["AUDIT_B"]
    slot = next(i for i, v in enumerate(dest) if v and v.get("text") == "SILO TEXT")
    assert dest[slot]["text"] == "SILO TEXT"
    assert "SILO TEXT" not in win.data["temp_presets"]


def test_snippet_to_silo_route_uses_pristine_slot(win):
    _cross_routes_setup(win)
    win.data["categories"]["AUDIT_B"][0] = {"name": "n", "text": "SNIP", "last_edited": 0}
    # The destination slot is genuinely reusable; no source-local pin is
    # allowed to make a successful route conditional.
    win.data["pinned_silos"][:] = []
    _own_live(win, "SNIP")
    assert win.move_preset_cross_category("AUDIT_B", 0, "silo", 0) is True
    assert "SNIP" in win.data["temp_presets"]
    assert 0 not in win.data.get("pinned_silos", [])


def test_destination_residual_identity_row_is_not_inserted_over(win):
    """The below-capacity positional insertion branch must remap destination
    state or refuse, never overwrite a row with residual identity."""
    _cross_routes_setup(win)
    win.data["temp_presets"][:] = ["SRC"]
    win.data["categories"]["AUDIT_B"][0] = {"name": "old", "text": "DEST-ORIG",
                                            "last_edited": 0}
    win.data["categories"]["AUDIT_B"].append(None)  # guarantee a free slot
    free = win.data["categories"]["AUDIT_B"].index(None)
    _own_live(win, "SRC")
    ok = win.move_preset_cross_category("silo", 0, "AUDIT_B", free)
    assert ok is True
    dest = win.data["categories"]["AUDIT_B"]
    assert dest[0] and dest[0]["text"] == "DEST-ORIG"  # original preserved
    assert "SRC" in [v["text"] for v in dest if v]


@pytest.mark.parametrize("key,value", [
    ("pinned_silos_all", [0]), ("silo_collapsed_all", [0]),
    ("silo_children_all", {1: [0]}), ("silo_gaps_all", [0]),
    ("silo_gap_names_all", {"0": "gap"}),
    ("silo_colors_all", {"0": "#111"}),
    ("silo_project_paths_all", {"0": "p"}),
])
def test_cross_category_max_capacity_reuses_only_pristine(win, key, value):
    """At MAX capacity a genuinely pristine slot may be reused; a row with
    residual identity must not be (audit 2.3)."""
    _cross_routes_setup(win)
    target = win.MAX_SILOS_PER_CATEGORY - 1
    win.data["temp_presets"][:] = ["X"] * win.MAX_SILOS_PER_CATEGORY
    win.data["temp_presets"][target] = ""
    win.data["categories"]["AUDIT_B"][0] = {
        "name": "src", "text": "SRC", "last_edited": 0
    }
    state_key = key.removesuffix("_all")
    state = win.data.get(state_key)
    if isinstance(state, list):
        state[:] = [target]
    elif isinstance(state, dict):
        state.clear()
        state[str(target)] = value
    assert win.move_preset_cross_category("AUDIT_B", 0, "silo", target) is not True
    assert win.data["categories"]["AUDIT_B"][0]["text"] == "SRC"


def test_cross_category_max_capacity_pristine_slot_succeeds(win):
    _cross_routes_setup(win)
    target = win.MAX_SILOS_PER_CATEGORY - 1
    win.data["temp_presets"][:] = ["X"] * win.MAX_SILOS_PER_CATEGORY
    win.data["temp_presets"][target] = ""
    win.data["categories"]["AUDIT_B"][0] = {
        "name": "src", "text": "SRC", "last_edited": 0
    }
    for key in (
        "pinned_silos", "silo_collapsed", "silo_children", "silo_gaps",
        "silo_gap_names", "silo_colors", "silo_project_paths",
    ):
        state = win.data.get(key)
        if isinstance(state, list):
            state.clear()
        elif isinstance(state, dict):
            state.clear()
    assert win.move_preset_cross_category("AUDIT_B", 0, "silo", target) is True
    assert win.data["temp_presets"][target] == "SRC"


def test_silo_to_snippet_refuses_real_assets(win, tmp_path, monkeypatch):
    """Conversion silo->snippet with real assets on disk is refused (2.3)."""

    _cross_routes_setup(win)
    monkeypatch.setattr(win, "_files_root", lambda: str(tmp_path))
    win.data["temp_presets"][:] = ["ASSET SILO"]
    src = win.get_current_category()
    # pre-register the folder mapping so _silo_folder_name never renames it
    win.data["silo_folders"]["0"] = "asset-silo"
    folder = tmp_path / win._category_files_dir(src) / "asset-silo"
    folder.mkdir(parents=True)
    (folder / "f.txt").write_text("x")
    free = win.data["categories"]["AUDIT_B"].index(None)
    _own_live(win, "ASSET SILO")
    assert win.move_preset_cross_category("silo", 0, "AUDIT_B", free) is not True
    assert (folder / "f.txt").read_text() == "x"
    assert "ASSET SILO" in win.data["temp_presets"]


# ============================================================= T-1217 wave 2
# Strict identity matrix, stranger-slot allocation, real menu action,
# immediate switch, physical undo/redo, collision/refusal safety, capacity.

def test_transfer_residual_parametrize_extended(fresh_win):
    win = fresh_win
    """Empty-looking destination rows that own ANY registered state namespace
    must never be offered as pristine by the canonical allocator."""
    _, dst, _ = prepare(win)
    win.data["temp_presets_all"][dst] = ["X", ""]  # slot 1 is the candidate
    extra = [
        ("silo_ticked_all", [1]), ("silo_selected_all", [1]),
        ("silo_last_edited_all", {1: 55}), ("silo_colors_all", {"1": "#111"}),
        ("silo_project_paths_all", {"1": "p"}), ("silo_folders_all", {"1": "F"}),
        ("silo_links_all", {"1": "link.txt"}),
        ("project_sync_map_all", {"1": "rel.txt"}),
        ("silo_type_all", {"1": "kanban"}),
        ("silo_view_state_all", {"s1": {"cursor": 3}}),
    ]
    for key, value in extra:
        assert not win._category_slot_has_state(dst, 1), f"{key} pre-state leaked"
        win.data[key][dst] = value
        assert win._category_slot_has_state(dst, 1), (
            f"{key} must register as slot state")
        chosen = win._acquire_silo_slot_for_category(dst)
        assert chosen != 1 and (chosen is None or chosen >= 2), (
            f"a row owning {key} must not be offered as pristine (got {chosen})")
        win.data[key][dst] = [] if isinstance(value, list) else ({})


def test_transfer_residual_parametrize_extended_and_pristine(fresh_win):
    win = fresh_win
    """With the SAME seeded row cleaned, slot 1 becomes reusable again."""
    _, dst, _ = prepare(win)
    win.data["temp_presets_all"][dst] = ["X", ""]
    win.data["silo_colors_all"][dst] = {"1": "#111"}
    assert win._acquire_silo_slot_for_category(dst) != 1
    win.data["silo_colors_all"][dst] = {}
    assert win._acquire_silo_slot_for_category(dst) == 1


def test_destination_never_inherits_a_stranger(fresh_win):
    win = fresh_win
    """Slots 0-3 own SOME state, slot 4 is truly pristine: the incoming silo
    must land on 4 and every stranger keeps its own state."""
    _, dst, _ = prepare(win)
    win.data["temp_presets_all"][dst] = ["OCC0", "", "", "", ""]
    win.data["silo_colors_all"][dst] = {"1": "COLOR-ONE"}
    win.data["silo_gap_names_all"][dst] = {"2": "GAPNAME-TWO"}
    win.data["silo_children_all"][dst] = {1: [3]}
    slot = win._acquire_silo_slot_for_category(dst)
    assert slot == 4, f"pristine slot 4 expected, allocator chose {slot}"
    assert win.transfer_silo_to_project(0, dst)
    dest = win.data["temp_presets_all"][dst]
    assert dest[4] == "NEW"
    assert dest[0] == "OCC0" and dest[1] == dest[2] == dest[3] == ""
    assert win.data["silo_colors_all"][dst]["1"] == "COLOR-ONE"
    assert "4" not in win.data["silo_colors_all"].get(dst, {})
    assert win.data["silo_gap_names_all"][dst]["2"] == "GAPNAME-TWO"
    assert "4" not in win.data["silo_gap_names_all"].get(dst, {})
    assert win.data["silo_children_all"][dst] == {1: [3]}


def test_transfer_full_identity_matrix(fresh_win, tmp_path, monkeypatch):
    win = fresh_win
    """ONE strict matrix: every identity field crosses with a DISTINCT
    sentinel, source-local state never crosses, source cleanup leaves no
    ghost, and the moved text appears exactly once globally."""
    monkeypatch.setattr(win, "_files_root", lambda: str(tmp_path / "files"))
    os.makedirs(tmp_path / "files", exist_ok=True)
    src, dst, _ = prepare(win, stored="OLD", live="MATRIX-LIVE-TEXT")
    rootX = str(tmp_path / "projX")
    os.makedirs(os.path.join(rootX), exist_ok=True)
    sync_payload = os.path.join(rootX, "synced-file.txt")
    with open(sync_payload, "w", encoding="utf-8") as f:
        f.write("SYNC-SENTINEL")
    win.data["project_sync_all"] = {src: {"root": rootX}, dst: {"root": rootX}}
    win.data["project_sync_map_all"] = {src: {"0": "synced-file.txt"}}
    win.data["silo_colors_all"][src] = {"0": "#A1B2C3"}
    win.data["silo_type_all"][src] = {"0": "kanban"}
    win.data["silo_folders_all"][src] = {"0": "F"}
    folder = tmp_path / "files" / win._category_files_dir(src) / "F"
    folder.mkdir(parents=True)
    (folder / "payload.txt").write_text("FOLDER-SENTINEL")
    win.data["silo_project_paths_all"][src] = {"0": "PROJ-PATH-9"}
    win.data["silo_links_all"][src] = {"0": "LINK-FILE.txt"}
    win.data["silo_last_edited_all"][src] = {0: 777}
    win.data["silo_view_state_all"][src] = {"s0": {"cursor": 42}}
    win.data["silo_ticked_all"][src] = [0]
    win.data["silo_selected_all"][src] = [0]
    win.data["silo_gaps_all"][src] = [0]
    win.data["silo_gap_names_all"][src] = {"0": "NAMED-GAP"}
    # source-local layout state is read from the FLAT aliases (the current
    # category's own lists); seeding the _all dict directly would leave the
    # flat alias stale
    win.data["pinned_silos"][:] = [0]
    win.data["silo_collapsed"][:] = [0]
    win.data["silo_children"].update({0: [1]})
    assert win.transfer_silo_to_project(0, dst) is True
    ds = win.data["temp_presets_all"][dst].index("MATRIX-LIVE-TEXT")

    # destination owns EVERY identity field, each exactly with its sentinel
    dst_colors = win.data["silo_colors_all"][dst]
    assert dst_colors.get(str(ds)) == "#A1B2C3"
    assert win.data["silo_type_all"][dst].get(str(ds)) == "kanban"
    assert win.data["silo_folders_all"][dst].get(str(ds)) == "F"
    assert win.data["silo_project_paths_all"][dst].get(str(ds)) == "PROJ-PATH-9"
    assert win.data["silo_links_all"][dst].get(str(ds)) == "LINK-FILE.txt"
    # sync map: SAME root -> the relative map entry keeps its meaning and
    # moves into the destination's map namespace with the same relative path
    assert (win.data["project_sync_map_all"].get(dst) or {}).get(str(ds)) == "synced-file.txt"
    assert open(os.path.join(rootX, "synced-file.txt"), encoding="utf-8").read() == "SYNC-SENTINEL"
    assert win.data["silo_last_edited_all"][dst].get(ds) == 777
    assert win.data["silo_view_state_all"][dst].get(f"s{ds}") == {"cursor": 42}
    assert win.data["silo_ticked_all"][dst] == [ds]
    assert win.data["silo_selected_all"][dst] == [ds]
    assert win.data["silo_gaps_all"][dst] == [ds]
    assert win.data["silo_gap_names_all"][dst][str(ds)] == "NAMED-GAP"
    # source-local layout state never crossed
    assert not (win.data["pinned_silos_all"].get(dst) or [])
    assert not (win.data["silo_collapsed_all"].get(dst) or [])
    assert not (win.data["silo_children_all"].get(dst) or {})

    # source cleanup: no ghost anywhere
    s_all = win.data["silo_colors_all"].get(src, {})
    assert "0" not in s_all
    assert "0" not in win.data["silo_type_all"].get(src, {})
    assert "0" not in win.data["silo_folders_all"].get(src, {})
    assert "0" not in win.data["silo_project_paths_all"].get(src, {})
    assert "0" not in win.data["silo_links_all"].get(src, {})
    assert "0" not in (win.data["project_sync_map_all"].get(src) or {})
    assert 0 not in win.data["silo_last_edited_all"].get(src, {})
    # the MOVED saved-view sentinel is gone from the source; the durable save
    # legitimately re-captures the now-empty active slot's fresh view state
    assert win.data["silo_view_state_all"].get(src, {}).get("s0") != {"cursor": 42}
    assert 0 not in win.data["silo_ticked_all"].get(src, [])
    assert 0 not in win.data["silo_selected_all"].get(src, [])
    assert not win.data["silo_gaps_all"].get(src, [])
    assert "0" not in win.data["silo_gap_names_all"].get(src, {})
    assert not win.data["pinned_silos_all"].get(src, [])
    assert not win.data["silo_collapsed_all"].get(src, [])
    assert not win.data["silo_children_all"].get(src, {})
    assert win.data["temp_presets_all"][src][0] == ""
    # the moved text exists exactly once globally
    occurrences = sum(
        str(t).count("MATRIX-LIVE-TEXT")
        for t in win.data["temp_presets_all"].get(src, [])
    ) + sum(
        str(t).count("MATRIX-LIVE-TEXT")
        for t in win.data["temp_presets_all"].get(dst, [])
    )
    assert occurrences == 1


def test_transfer_menu_action_moves_live_text(fresh_win, monkeypatch):
    win = fresh_win
    """The REAL temp-menu QAction for a destination project moves the
    unflushed live text - the original 'Transfer to Project doesn't work'
    report at the UI action level."""
    _, dst, _ = prepare(win, stored="OLD", live="NEW LIVE TEXT")
    menus = []
    monkeypatch.setattr(QMenu, "exec", lambda self, *a: menus.append(self))
    win.show_temp_menu(0, QPoint(0, 0))
    transfer_menu = next(
        (a.menu() for m in menus for a in m.actions()
         if a.menu() is not None and "Transfer to Project" in a.menu().title()),
        None)
    assert transfer_menu is not None
    act = next(a for a in transfer_menu.actions() if a.text() == dst)
    snippets_before = [dict(v) if isinstance(v, dict) else v
                       for v in win.data["categories"][dst]]
    act.trigger()
    assert "NEW LIVE TEXT" in win.data["temp_presets_all"][dst]
    assert win.data["temp_presets_all"][win.get_current_category()][0] == ""
    assert win.data["categories"][dst] == snippets_before, (
        "transfer to project must not create a snippet")


def test_transfer_immediate_destination_switch_is_deterministic(fresh_win):
    win = fresh_win
    """src -> dst -> src -> dst through the real category binding must show
    deterministic state both times (the flat-alias bug class from T-1222)."""
    _, dst, _ = prepare(win, stored="OLD", live="SWITCH-LIVE")
    win.data["silo_colors_all"][win.get_current_category()] = {"0": "#FEED01"}
    win.data["silo_gaps_all"].setdefault(win.get_current_category(), []).append(0)
    win.data["silo_gap_names_all"].setdefault(win.get_current_category(), {})["0"] = "SWITCH-GAP"
    assert win.transfer_silo_to_project(0, dst)
    from fastprompter.core.state import bind_active_category
    cur = win.get_current_category()

    def read_dst():
        bind_active_category(win.data, dst)
        win.silo_last_edited = win.data.setdefault(
            "silo_last_edited_all", {}).setdefault(dst, {})
        idx = win.data["temp_presets"].index("SWITCH-LIVE")
        return (win.data["temp_presets"],
                win.data["silo_colors"].get(str(idx)),
                win.data["silo_gap_names"].get(str(idx)))

    def read_src():
        bind_active_category(win.data, cur)
        win.silo_last_edited = win.data.setdefault(
            "silo_last_edited_all", {}).setdefault(cur, {})
        return win.data["temp_presets"][0]

    first = read_dst()
    assert first[0].count("SWITCH-LIVE") == 1
    assert first[1] == "#FEED01" and first[2] == "SWITCH-GAP"
    assert read_src() == ""
    second = read_dst()
    assert second == first, "destination state must be deterministic"
    assert read_src() == ""
    bind_active_category(win.data, cur)
    win.silo_last_edited = win.data.setdefault(
        "silo_last_edited_all", {}).setdefault(cur, {})


@pytest.fixture
def folder_transfer(win, tmp_path, monkeypatch):
    """A real private attachment folder transferred source -> destination."""
    monkeypatch.setattr(win, "_files_root", lambda: str(tmp_path))
    src, dst, _ = prepare(win)
    win.data["silo_folders"]["0"] = "assets"
    win.data.setdefault("silo_folders_all", {}).setdefault(src, {})["0"] = "assets"
    source = tmp_path / win._category_files_dir(src) / "assets"
    source.mkdir(parents=True)
    (source / "keep.txt").write_text("KEEP-BYTES")
    destination = tmp_path / win._category_files_dir(dst) / "assets"
    return win, src, dst, source, destination


def test_physical_folder_undo_redo_moves_bytes(folder_transfer):
    win, src, dst, source, destination = folder_transfer
    assert win.transfer_silo_to_project(0, dst) is True
    assert (destination / "keep.txt").read_text() == "KEEP-BYTES"
    assert not source.exists()
    ds = win.data["temp_presets_all"][dst].index("NEW")
    assert (win.data["silo_folders_all"].get(dst) or {}).get(str(ds)) == "assets"

    # UNDO: bytes AND mapping return to the source, exactly one copy exists
    win.undo_action()
    assert (source / "keep.txt").read_text() == "KEEP-BYTES"
    assert not destination.exists()
    assert (win.data["silo_folders_all"].get(src) or {}).get("0") == "assets"
    assert not (win.data["silo_folders_all"].get(dst) or {})
    assert win.data["temp_presets_all"][src][0] == "NEW"
    assert win.data["temp_presets_all"][dst][ds] == ""

    # REDO: bytes and mapping follow the text to the destination again
    win.redo_action()
    assert (destination / "keep.txt").read_text() == "KEEP-BYTES"
    assert not source.exists()
    assert (win.data["silo_folders_all"].get(dst) or {}).get(str(ds)) == "assets"
    assert win.data["temp_presets_all"][dst][ds] == "NEW"
    assert win.data["temp_presets_all"][src][0] == ""


def test_undo_collides_with_unexpected_source_dir(folder_transfer):
    """A stranger directory at the source location must refuse the undo
    fail-closed and stay retryable - never clobber."""
    import shutil

    win, src, dst, source, destination = folder_transfer
    assert win.transfer_silo_to_project(0, dst) is True
    source.mkdir(parents=True)  # unexpected re-creation before undo
    (source / "stranger.txt").write_text("DO-NOT-CLOBBER")
    stack_depth = len(win.data_undo_stack)
    win.undo_action()
    assert (destination / "keep.txt").read_text() == "KEEP-BYTES", (
        "destination bytes must stay untouched while the undo is refused")
    assert len(win.data_undo_stack) == stack_depth, (
        "a refused undo must stay retryable")
    # remove the collision -> retry succeeds
    shutil.rmtree(source)
    win.undo_action()
    assert (source / "keep.txt").read_text() == "KEEP-BYTES"
    assert not destination.exists()


def test_undo_refuses_abandoned_files_root(folder_transfer, tmp_path, monkeypatch):
    """After a Files-root re-root the historical physical half must refuse to
    mutate the abandoned root; restoring the root lets the undo proceed."""
    win, src, dst, source, destination = folder_transfer
    original_root = str(tmp_path)
    assert win.transfer_silo_to_project(0, dst) is True
    other_root = str(tmp_path / "abandoned-other-root")
    monkeypatch.setattr(win, "_files_root", lambda: other_root)
    stack_depth = len(win.data_undo_stack)
    win.undo_action()
    assert (destination / "keep.txt").read_text() == "KEEP-BYTES"
    assert not source.exists(), "the abandoned root must never be mutated"
    assert len(win.data_undo_stack) == stack_depth
    monkeypatch.setattr(win, "_files_root", lambda: original_root)
    win.undo_action()
    assert (source / "keep.txt").read_text() == "KEEP-BYTES"
    assert not destination.exists()


def test_capacity_boundary_is_strict(fresh_win):
    win = fresh_win
    """MAX==100, full destination refuses untouched, a pristine blank at the
    boundary is reusable, and no path may create slot index 100."""
    assert win.MAX_SILOS_PER_CATEGORY == 100
    _, dst, _ = prepare(win)
    win.data["temp_presets_all"][dst] = ["X"] * 100
    assert win._acquire_silo_slot_for_category(dst) is None
    assert win.transfer_silo_to_project(0, dst) is False
    assert win.data["temp_presets_all"][dst] == ["X"] * 100
    assert win.data["temp_presets_all"][win.get_current_category()][0] == "NEW"
    assert len(win.data["temp_presets_all"][dst]) == 100, "no slot 100 may appear"
    # one genuinely pristine blank at the boundary is reusable
    win.data["temp_presets_all"][dst][7] = ""
    assert win._acquire_silo_slot_for_category(dst) == 7
    assert win.transfer_silo_to_project(0, dst) is True
    assert win.data["temp_presets_all"][dst][7] == "NEW"
    assert len(win.data["temp_presets_all"][dst]) == 100


def test_stale_folder_mapping_conversion_silo_to_snippet(fresh_win, tmp_path, monkeypatch):
    win = fresh_win
    """A folder mapping without a physical folder cannot lose bytes (there
    are none): silo->snippet proceeds and the stale mapping is dropped."""
    _cross_routes_setup(win)
    monkeypatch.setattr(win, "_files_root", lambda: str(tmp_path))
    win.data["temp_presets"][:] = ["GHOST SILO", "OTHER"]
    win.data["silo_folders"]["0"] = "ghost-folder"
    assert not (tmp_path / win._category_files_dir(win.get_current_category()) / "ghost-folder").exists()
    free = win.data["categories"]["AUDIT_B"].index(None)
    _own_live(win, "GHOST SILO")
    assert win.move_preset_cross_category("silo", 0, "AUDIT_B", free) is True
    dest = win.data["categories"]["AUDIT_B"]
    assert [v["text"] for v in dest if isinstance(v, dict)].count("GHOST SILO") == 1
    assert "GHOST SILO" not in win.data["temp_presets"]
    assert "OTHER" in win.data["temp_presets"], "neighbour must survive"
    # the stale ghost mapping must be gone; the neighbour's synthesized
    # folder name (refresh may name slots from text) is not a ghost
    assert "ghost-folder" not in (win.data["silo_folders"] or {}).values()


def test_snippet_to_silo_neighbour_ownership(fresh_win):
    win = fresh_win
    """BEFORE / SOURCE / AFTER snippet neighbours keep their ownership; the
    moved SOURCE text exists exactly once in silo space."""
    _cross_routes_setup(win)
    snippets = win.data["categories"]["AUDIT_B"]
    snippets[0] = {"name": "before", "text": "BEFORE-TEXT", "last_edited": 0}
    snippets[1] = {"name": "source", "text": "SOURCE-TEXT", "last_edited": 1}
    snippets[2] = {"name": "after", "text": "AFTER-TEXT", "last_edited": 2}
    _own_live(win, "")
    slot = win._acquire_silo_slot_for_category("silo")
    assert slot is not None
    assert win.move_preset_cross_category("AUDIT_B", 1, "silo", slot) is True
    assert win.data["temp_presets"].count("SOURCE-TEXT") == 1
    dest_texts = [v["text"] for v in snippets if isinstance(v, dict)]
    assert "SOURCE-TEXT" not in dest_texts
    assert dest_texts == ["BEFORE-TEXT", "AFTER-TEXT"], (
        "neighbour snippets must keep their own slots and order")
