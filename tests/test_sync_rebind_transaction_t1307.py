"""W2-002 (audit/12, SRC-041 R005): Sync-Project folder rebind is ONE
transaction bounded by the authoritative save.

The old method mutated config, mapping, presets, caches and leases, then
called ``save_data_to_db(force=True)`` and DISCARDED the result: a failed save
still started the new watcher, replaced the editor text and announced a
completed two-way binding while the database still owned the old folder.
These tests inject False and an exception, and prove the complete rollback.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtWidgets import QApplication

import fastprompter.core.state as state_mod
from fastprompter.core import project_sync as ps

_APP = QApplication.instance() or QApplication([])


@pytest.fixture(scope="module")
def win(tmp_path_factory):
    tmp_path = tmp_path_factory.mktemp("w2_002")
    original_db_path = state_mod.get_db_path
    state_mod.get_db_path = (
        lambda profile_id=1: str(tmp_path / f"w2_002_{profile_id}.db"))
    import fastprompter.utils.portable_backup as backup_mod
    original_backup = backup_mod.run_portable_backup
    backup_mod.run_portable_backup = lambda data, profile_id=1, **_kw: None

    from fastprompter.main import FastPrompter
    originals = {
        name: getattr(FastPrompter, name)
        for name in ("setup_single_instance_server", "register_all_hotkeys",
                     "unregister_all_hotkeys")
    }
    FastPrompter.setup_single_instance_server = lambda self: None
    FastPrompter.register_all_hotkeys = lambda self: None
    FastPrompter.unregister_all_hotkeys = lambda self: None
    w = FastPrompter()
    for _ in range(5):
        _APP.processEvents()
    w._initializing_ui = False
    w._suspend_temp_sync = False
    try:
        yield w
    finally:
        for name in ("auto_save_timer", "topmost_timer", "_cache_timer"):
            timer = getattr(w, name, None)
            if timer is not None:
                timer.stop()
        service = getattr(w, "limit_service", None)
        if service is not None:
            service.shutdown()
        # closeEvent deliberately leaves resident Sync workers alive. This
        # fixture owns a whole application window and must use the physical
        # retirement path before its QThread wrapper can be collected.
        w._in_physical_teardown = True
        push_clean = w._push_shutdown()
        if getattr(w, "state", None) is not None:
            w.state.conn = None
        w.close()
        from _qt_retire import retire
        retire(w)
        for name, value in originals.items():
            setattr(FastPrompter, name, value)
        state_mod.get_db_path = original_db_path
        backup_mod.run_portable_backup = original_backup
        assert push_clean


def _prepare_binding(win, old_root, new_root):
    os.makedirs(old_root, exist_ok=True)
    os.makedirs(new_root, exist_ok=True)
    with open(os.path.join(old_root, "old.txt"), "w", encoding="utf-8") as fh:
        fh.write("OLD-FILE")
    with open(os.path.join(new_root, "new.txt"), "w", encoding="utf-8") as fh:
        fh.write("NEW-FILE")
    cat = win.get_current_category()
    cfg = {
        "root": str(old_root),
        "recursive": True,
        "include": "*.txt",
        "exclude": "",
        "enabled": True,
    }
    win.data["project_sync"] = dict(cfg)
    win.data["project_sync_all"] = {cat: dict(cfg)}
    mapping = {"0": "old.txt"}
    win.data["project_sync_map"] = mapping
    win.data["project_sync_map_all"] = {cat: mapping}
    win.data["sync_path"] = str(old_root)
    presets = win._ensure_temp_presets()
    presets[:] = ["OLD-FILE"]
    key = win._sync_baseline_key(0, os.path.join(str(old_root), "old.txt"))
    win._sync_eol_cache[key] = "\n"
    win._sync_bom_cache[key] = False
    win._sync_last_applied[key] = win._sync_side_digest("OLD-FILE")
    return cat, presets, key


def _stub_ui(win, monkeypatch, new_root):
    import fastprompter.main as main_mod
    infos, criticals, starts = [], [], []
    monkeypatch.setattr(
        main_mod.QFileDialog, "getExistingDirectory",
        staticmethod(lambda *a, **k: str(new_root)))
    monkeypatch.setattr(
        main_mod.QMessageBox, "information",
        staticmethod(lambda *a, **k: infos.append(a)))
    monkeypatch.setattr(
        main_mod.QMessageBox, "critical",
        staticmethod(lambda *a, **k: criticals.append(a)))
    monkeypatch.setattr(win, "_start_project_watcher",
                        lambda: starts.append(1))
    monkeypatch.setattr(win, "_update_project_tooltip", lambda: None)
    return infos, criticals, starts


def _snapshot(win, presets, key):
    return {
        "cfg": dict(win.data["project_sync"]),
        "map": dict(win.data["project_sync_map"]),
        "presets": list(presets),
        "eol": dict(win._sync_eol_cache),
        "bom": dict(win._sync_bom_cache),
        "applied": dict(win._sync_last_applied),
        "editor": win.text_area.toPlainText(),
    }


def _assert_restored(win, presets, snap):
    assert win.data["project_sync"] == snap["cfg"]
    assert win.data["project_sync_map"] == snap["map"]
    assert list(presets) == snap["presets"]
    assert dict(win._sync_eol_cache) == snap["eol"]
    assert dict(win._sync_bom_cache) == snap["bom"]
    assert dict(win._sync_last_applied) == snap["applied"]
    assert win.text_area.toPlainText() == snap["editor"]


class TestRefusedRebind:
    def test_false_save_rolls_back_everything(self, win, tmp_path,
                                              monkeypatch):
        old_root = tmp_path / "old"
        new_root = tmp_path / "new"
        cat, presets, key = _prepare_binding(win, old_root, new_root)
        assert win.save_data_to_db(force=True) is True  # old root is durable
        snap = _snapshot(win, presets, key)
        infos, criticals, starts = _stub_ui(win, monkeypatch, new_root)

        monkeypatch.setattr(ps, "scan_folder", lambda *a, **k: ["new.txt"])
        monkeypatch.setattr(win, "save_data_to_db",
                            lambda force=False, **kw: False)
        recaptured = []
        monkeypatch.setattr(win, "_push_sync_files",
                            lambda *a, **k: recaptured.append(True))

        win._change_project_sync_folder()

        _assert_restored(win, presets, snap)
        assert starts == [], "no new watcher may start on a refused rebind"
        assert infos == [], "no success message on a refused rebind"
        assert len(criticals) == 1
        assert recaptured == [True], "fresh old-binding work is recaptured"
        assert not win._push_jobs_pending, "no job may target the new root"
        assert win.data.get("project_sync_map_all", {}).get(cat) == \
            snap["map"]

        fresh = state_mod.FastPrompterState(profile_id=1)
        try:
            assert fresh.data.get("project_sync", {}).get("root") == \
                str(old_root), "the old root stays the DB truth"
        finally:
            if fresh.conn is not None:
                fresh.conn.close()

    def test_raising_save_rolls_back_everything(self, win, tmp_path,
                                                monkeypatch):
        old_root = tmp_path / "old"
        new_root = tmp_path / "new"
        cat, presets, key = _prepare_binding(win, old_root, new_root)
        assert win.save_data_to_db(force=True) is True
        snap = _snapshot(win, presets, key)
        infos, criticals, starts = _stub_ui(win, monkeypatch, new_root)

        monkeypatch.setattr(ps, "scan_folder", lambda *a, **k: ["new.txt"])

        def exploding_save(force=False, **kw):
            raise RuntimeError("storage failure")

        monkeypatch.setattr(win, "save_data_to_db", exploding_save)
        monkeypatch.setattr(win, "_push_sync_files", lambda *a, **k: None)

        win._change_project_sync_folder()

        _assert_restored(win, presets, snap)
        assert starts == []
        assert infos == []
        assert len(criticals) == 1
        assert not win._push_jobs_pending


class TestSuccessfulRebind:
    def test_success_commits_then_activates(self, win, tmp_path, monkeypatch):
        old_root = tmp_path / "old"
        new_root = tmp_path / "new"
        cat, presets, key = _prepare_binding(win, old_root, new_root)
        assert win.save_data_to_db(force=True) is True
        infos, criticals, starts = _stub_ui(win, monkeypatch, new_root)

        monkeypatch.setattr(ps, "scan_folder", lambda *a, **k: ["new.txt"])
        monkeypatch.setattr(win, "_push_sync_files", lambda *a, **k: None)

        win._change_project_sync_folder()

        assert win.data["project_sync"]["root"] == str(new_root)
        assert win.data["project_sync_map"] == {"0": "new.txt"}
        assert presets[0] == "NEW-FILE"
        assert starts == [1], "the new watcher starts only after the commit"
        assert len(infos) == 1 and criticals == []
        assert win.text_area.toPlainText() == "NEW-FILE"

        fresh = state_mod.FastPrompterState(profile_id=1)
        try:
            assert fresh.data.get("project_sync", {}).get("root") == \
                str(new_root), "a restart reproduces the committed rebind"
        finally:
            if fresh.conn is not None:
                fresh.conn.close()
