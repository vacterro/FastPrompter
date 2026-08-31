"""Regression (Part 2): profile runtime reload, undo path-capture, persisted
undo reload, final-sync preservation, custom-root fail-closed, transactional
folder renames, retirement-failure ownership, trash no-clobber and the
per-profile SQLite .bak throttle.

P0-1  change_profile() must rebind EVERY profile-owned runtime object from
      the active DB (timers, queues, pomodoro, language, sound ownership,
      persisted widget values) — and saving the new profile must never write
      the old profile's widget values into it.
P0-2  the undo-save worker must write to the path captured BEFORE the thread
      started, never to whatever profile is active when the write lands.
P0-3  a profile switch loads THAT profile's persisted undo file (and a
      malformed file yields an empty stack, not a foreign one).
P0-4  the final old-profile Sync snapshot is dispatched immediately on
      switch — never dropped by the debounce teardown.
P0-5  a configured-but-unreachable custom files root never silently falls
      back to the default local root (no split-brain shadow storage).
P0-6  a silo folder rename advances the persisted mapping ONLY after the
      physical rename succeeded; a failed rename keeps the old mapping.
P1-9  a failed file retirement keeps the ownership mapping (assets stay
      recoverable); ROOT_UNAVAILABLE never reads as "folder is gone".
P1-10 two trashes in the same second with the same slug each get their OWN
      file (no-clobber publication), never an overwrite.
P1-7  the SQLite .bak throttle is per profile: B backs up right after A did,
      and A's own 60s throttle still applies when switching back.
"""

import json
import os
import sqlite3
import sys
import threading
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import tempfile

import pytest
from PyQt6.QtWidgets import QApplication

import fastprompter.core.state as state_mod
from fastprompter.main import FastPrompter

_app = QApplication.instance() or QApplication([])
_tmpdir = tempfile.mkdtemp(prefix="fastprompter_profile_runtime_")


@pytest.fixture(scope="module")
def win():
    state_mod.get_db_path = lambda profile_id=1: os.path.join(_tmpdir, f"prt_{profile_id}.db")
    state_mod.run_portable_backup = lambda data, profile_id=1: None
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


@pytest.fixture()
def iso_root(win, monkeypatch, tmp_path):
    """Fresh data dir + a clean window state on profile 1."""
    root = str(tmp_path / "root")
    os.makedirs(root, exist_ok=True)
    import fastprompter.utils.paths as paths_mod
    monkeypatch.setattr(paths_mod, "get_data_dir", lambda: root)
    win._files_root_probe = None
    win.data["files_root"] = ""
    if getattr(getattr(win, "state", None), "profile_id", 1) != 1:
        win.change_profile(0)
    win.data["category_file_dirs"].clear()
    win.data["folder_trash_log"][:] = []
    win.data_undo_stack = []
    win.data_redo_stack = []
    yield root
    win.data["files_root"] = ""
    win._files_root_probe = None


def _setup_category(win, texts=("Foo", "")):
    win.data["cats_order"] = ["Same"]
    win.data["categories"] = {"Same": [None] * 10}
    win.data["temp_presets_all"] = {"Same": list(texts)}
    win.data["archive_temp_presets_all"] = {"Same": []}
    win.data["silo_folders"].clear()
    win.data["archive_silo_folders"].clear()
    win.build_categories()
    win.cat_combo.setCurrentIndex(0)
    win.on_tab_changed(0)
    win.silo_docs[:] = []
    win.data["temp_presets"] = win.data["temp_presets_all"]["Same"]
    win._switch_to_slot(0, initial=True)
    win._files_root_probe = None


def _db(profile_id):
    return os.path.join(_tmpdir, f"prt_{profile_id}.db")


class TestProfileRuntimeReload:
    """P0-1: one profile-runtime application path, used by change_profile."""

    def test_runtime_objects_rebind_from_active_data(self, win, iso_root):
        """Data-derived runtime objects (timers, queues, pomodoro, language,
        sound ownership) are rebuilt by the ONE apply path."""
        w = win
        w.data["language"] = "ET"
        w.data["timers"] = [{"name": "timerB", "target": "2030-01-01T12:00:00",
                            "repeat": "daily"}]
        w.data["watcher_queues"] = {"1": [{"id": "qB", "text": "queue B"}]}
        w.data["productivity_timer"] = {"work_seconds": 777, "break_seconds": 33}

        old_timers = w.timers
        old_queues = w.prompt_queues
        old_pomo = w.productivity_timer
        w._apply_profile_runtime_state()
        assert w.timers is not old_timers, "timers must be reloaded"
        assert w.prompt_queues is not old_queues, "queues must be reloaded"
        assert w.productivity_timer is not old_pomo, "pomodoro must be rebuilt"
        assert w.productivity_timer.work_seconds == 777
        assert w._current_lang == "ET"
        assert w.sound_manager._data is w.data
        assert [t.name for t in w.timers] == ["timerB"]
        assert list(w.prompt_queues.keys()) == ["1"]

    def test_widget_values_survive_real_switches(self, win, iso_root):
        """DB-persisted widget settings follow the profile across real
        switches, and saving B never writes A's widget values into B."""
        w = win
        w.data["font_size"] = 9
        w.data["preview_mode"] = "Source View"
        w.data["tray_visible"] = "False"
        w.data["close_on_focus_loss"] = "False"
        w.data["ctrl_c_closes"] = "False"
        w.data["window_locked"] = "False"
        w.data["always_on_top"] = "False"
        w._apply_profile_runtime_state()   # widgets re-stamp from A's data
        assert w.font_spin.value() == 9
        w.save_data_to_db(force=True)      # DB receives A's real values
        w.change_profile(0)                # re-apply on profile 1
        assert w.font_spin.value() == 9

        # -- switch to profile 2 with OPPOSITE sentinel values -------------
        w.change_profile(1)   # profile 2 (fresh data from an empty DB)
        w.data["font_size"] = 15
        w.data["preview_mode"] = "Reading"
        w.data["tray_visible"] = "True"
        w.data["close_on_focus_loss"] = "True"
        w.data["ctrl_c_closes"] = "True"
        w.data["window_locked"] = "True"
        w.data["always_on_top"] = "True"
        w._apply_profile_runtime_state()

        # widget values must already match the ACTIVE profile (P2-19: the
        # values save_data_to_db() reads must equal the active data BEFORE
        # any save — otherwise saving B writes A's widget values into B)
        assert w.font_spin.value() == 15
        assert w.preview_combo.currentData() == "Reading"
        assert w.cb_tray.isChecked() is True
        assert w.cb_focus.isChecked() is True
        assert w.cb_ctrl_c.isChecked() is True
        assert w.cb_lock_window.isChecked() is True
        assert w.cb_top.isChecked() is True

        # save B: the DB must receive B's values, not A's stale widgets
        w.save_data_to_db(force=True)
        conn = sqlite3.connect(_db(2))
        try:
            rows = dict(conn.execute("SELECT key, value FROM settings").fetchall())
        finally:
            conn.close()
        assert rows.get("font_size") == "15", "B must be saved with B's font"
        assert rows.get("preview_mode") == "Reading"
        assert rows.get("ctrl_c_closes") == "True"
        assert rows.get("window_locked") == "True"
        # tray_visible / close_on_focus_loss default to "True" in
        # DEFAULT_PROFILE, so on a FRESH profile the save diffs them against
        # the in-memory default snapshot and skips the row. The meaningful
        # assertion is that A's "False" did NOT leak into B's save (a stale
        # A widget would have written "False").
        for key in ("tray_visible", "close_on_focus_loss"):
            assert rows.get(key, "True") != "False", \
                f"A's {key}=False must not be written into B"
        assert w.data["tray_visible"] == "True"
        assert w.data["close_on_focus_loss"] == "True"

        # -- back to A: A keeps its own exact values ------------------------
        w.change_profile(0)
        assert w.font_spin.value() == 9
        assert w.preview_combo.currentData() == "Source View"
        assert w.cb_tray.isChecked() is False
        assert w.cb_focus.isChecked() is False
        assert w.cb_ctrl_c.isChecked() is False
        assert w.cb_lock_window.isChecked() is False

        # and A -> B again: B still has B's values (nothing drifted)
        w.change_profile(1)
        assert w.font_spin.value() == 15
        assert w.preview_combo.currentData() == "Reading"
        w.change_profile(0)   # leave the window on profile 1


class TestUndoPathCapture:
    """P0-2: the undo worker writes only the path captured pre-thread."""

    def test_undo_worker_writes_captured_profile_path(self, win, iso_root, monkeypatch):
        w = win
        a_undo = os.path.splitext(_db(1))[0] + "_undo.json"
        b_undo = os.path.splitext(_db(2))[0] + "_undo.json"
        for p in (a_undo, b_undo):
            if os.path.exists(p):
                os.remove(p)
        w.state.switch_profile(1, save_current=False)
        w.data_undo_stack = [{"marker": "A"}]
        w.data_redo_stack = [{"marker": "AR"}]

        ev = threading.Event()
        real_dump = json.dump

        def blocking_dump(obj, f, **kw):
            ev.wait(10)
            return real_dump(obj, f, **kw)

        monkeypatch.setattr(json, "dump", blocking_dump)
        w._save_undo_state()            # A's path + stacks captured at ARM time
        if w._undo_timer is not None:
            w._undo_timer.stop()
        w._dispatch_undo_save()         # force the pending snapshot out NOW
        time.sleep(0.4)                 # let the worker reach the block

        # profile identity changes BEFORE the worker's write lands
        w.state.switch_profile(2, save_current=False)
        ev.set()
        for t in list(w._undo_save_threads):
            t.join(5)
        w._undo_save_threads.clear()

        assert os.path.exists(a_undo), "A snapshot must land in A's undo file"
        assert not os.path.exists(b_undo), "B's undo file must be untouched"
        with open(a_undo, encoding="utf-8") as f:
            raw = json.load(f)
        assert [s.get("marker") for s in raw["undo"]] == ["A"]
        assert [s.get("marker") for s in raw["redo"]] == ["AR"]

        w.state.switch_profile(1, save_current=False)
        for p in (a_undo, b_undo):
            if os.path.exists(p):
                os.remove(p)


class TestProfileDocumentCacheBoundary:
    def test_same_category_and_slot_never_reuse_foreign_document(
            self, win, iso_root):
        w = win
        w.change_profile(0)
        w.data["temp_presets"][0] = "PROFILE A"
        w.silo_docs[:] = []
        w._switch_to_slot(0, initial=True, sync_outgoing=False)
        profile_a_doc = w.text_area.document()
        profile_a_id = id(profile_a_doc)
        w._remember_category_documents(w.get_current_category())
        assert w._category_document_cache

        w.change_profile(1)
        w.data["temp_presets"][0] = "PROFILE B"
        w._switch_to_slot(0, initial=True, sync_outgoing=False)

        assert w.text_area.toPlainText() == "PROFILE B"
        assert w.text_area.document() is not profile_a_doc
        assert all(
            doc is not profile_a_doc
            for silo_docs, archive_docs in w._category_document_cache.values()
            for doc in (*silo_docs, *archive_docs)
            if doc is not None
        )
        assert all(key[0] != profile_a_id
                   for key in w._document_fingerprint_cache)
        assert all(cached[0] != "PROFILE A"
                   for cached in w._line_count_cache.values())
        w.change_profile(0)


class TestPersistedUndoReload:
    """P0-3: a profile switch loads that profile's persisted undo file."""

    def _write_undo(self, path, undo, redo):
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"undo": undo, "redo": redo}, f)

    def test_switch_loads_that_profiles_undo(self, win, iso_root):
        w = win
        a_undo = os.path.splitext(_db(1))[0] + "_undo.json"
        b_undo = os.path.splitext(_db(2))[0] + "_undo.json"
        self._write_undo(a_undo, [{"src": "A"}], [])
        self._write_undo(b_undo, [{"src": "B"}], [{"src": "BR"}])

        w.change_profile(0)
        assert [s.get("src") for s in w.data_undo_stack] == ["A"]

        w.change_profile(1)
        assert [s.get("src") for s in w.data_undo_stack] == ["B"], \
            "profile B must see B's persisted undo"
        assert [s.get("src") for s in w.data_redo_stack] == ["BR"]

        w.change_profile(0)
        assert [s.get("src") for s in w.data_undo_stack] == ["A"], \
            "profile A must see A's persisted undo again"

        for p in (a_undo, b_undo):
            if os.path.exists(p):
                os.remove(p)

    def test_malformed_undo_file_yields_empty_stack(self, win, iso_root):
        w = win
        a_undo = os.path.splitext(_db(1))[0] + "_undo.json"
        b_undo = os.path.splitext(_db(2))[0] + "_undo.json"
        self._write_undo(a_undo, [{"src": "A"}], [])
        with open(b_undo, "w", encoding="utf-8") as f:
            f.write("not json at all {{{")

        w.change_profile(0)
        assert w.data_undo_stack
        w.change_profile(1)
        assert w.data_undo_stack == [], "malformed B undo must yield an empty stack"
        assert w.data_redo_stack == []
        w.change_profile(0)
        assert [s.get("src") for s in w.data_undo_stack] == ["A"], \
            "A's undo must remain intact"

        for p in (a_undo, b_undo):
            if os.path.exists(p):
                os.remove(p)


class TestFinalSyncPreserved:
    """P0-4: the final old-profile Sync snapshot is dispatched, not dropped."""

    def test_switch_dispatches_pending_snapshot(self, win, iso_root, tmp_path):
        w = win
        root = str(tmp_path / "syncroot")
        w.data["temp_presets"] = ["final A text", ""]
        w.data["sync_mode"] = "Silo"
        w.data["sync_path"] = root
        w.sync_to_disk(force=True)
        assert w._sync_pending is not None, "final snapshot must be pending"
        gen = w._sync_pending["gen"]

        w._sync_on_profile_change()
        assert w._sync_pending is None, "pending slot cleared"
        assert w._sync_inflight_gen == gen, \
            "the final snapshot must be dispatched, not dropped"

        # the worker writes it (wait, bounded, pumping the event loop)
        found = []
        deadline = time.time() + 5
        while time.time() < deadline:
            _app.processEvents()
            time.sleep(0.02)
            found = [p for p in __import__("pathlib").Path(root).rglob("*.md")]
            if found and w._sync_inflight_gen == 0:
                break
        assert found, "the final old-profile mirror must reach disk"
        with open(found[0], encoding="utf-8") as f:
            assert f.read() == "final A text"

        w.data["sync_mode"] = "Off"
        w.data["sync_path"] = ""


class TestCustomRootFailClosed:
    """P0-5: an unreachable custom root never silently becomes the local root."""

    def test_custom_root_unavailable_never_falls_back(self, win, iso_root, monkeypatch, tmp_path):
        w = win
        custom = str(tmp_path / "nas_root")
        os.makedirs(custom)
        w.data["files_root"] = custom
        w._files_root_probe = None
        assert w._files_root() == custom

        default_files = os.path.join(iso_root, "files")
        import fastprompter.utils.paths as paths_mod
        monkeypatch.setattr(paths_mod, "isdir_within", lambda p: False)
        w._files_root_probe = None
        assert w._files_root() == custom, \
            "unavailable custom root must NOT fall back to the default local root"

        # a mutation must target the configured path, never the default root
        w._trash_silo_content("no shadow")
        assert not os.path.exists(default_files), \
            "no shadow copy may appear under the default data/files root"
        assert os.path.isdir(os.path.join(custom, "_trash")), \
            "the write went to the configured root, which is unchanged"


class TestFolderRenameTransactional:
    """P0-6: the mapping follows the physical rename, never leads it."""

    def test_failed_rename_keeps_old_mapping(self, win, iso_root, monkeypatch):
        w = win
        _setup_category(win, ("Foo", ""))
        name0 = w._silo_folder_name(0)
        folder = w._silo_folder_dir(0)
        os.makedirs(folder, exist_ok=True)
        assert w.data["silo_folders"].get("0") == name0

        def boom(src, dst):
            raise PermissionError("denied")

        real_rename = os.rename
        monkeypatch.setattr(os, "rename", boom)
        w.data["temp_presets"][0] = "Bar"
        assert w._silo_folder_name(0) == name0, \
            "a failed rename must NOT advance the persisted mapping"
        assert os.path.isdir(folder), "the physical folder is untouched"

        monkeypatch.setattr(os, "rename", real_rename)   # restore, keep other patches
        w.data["temp_presets"][0] = "Baz"
        name2 = w._silo_folder_name(0)
        assert name2 != name0, "a successful rename advances the mapping"
        assert w.data["silo_folders"].get("0") == name2
        assert os.path.isdir(w._silo_folder_dir(0))
        assert not os.path.exists(folder), "the old physical folder was renamed"


class TestRetirementFailureOwnership:
    """P1-9: a failed retirement never drops the ownership mapping."""

    def test_failed_retirement_keeps_mapping(self, win, iso_root, monkeypatch, tmp_path):
        w = win
        _setup_category(win, ("Keep", ""))
        name0 = w._silo_folder_name(0)
        folder = w._silo_folder_dir(0)
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, "asset.txt"), "w", encoding="utf-8") as f:
            f.write("precious")

        def boom(src, dst):
            raise PermissionError("denied")

        monkeypatch.setattr(os, "rename", boom)
        status = w._delete_file_container("Same", folder)
        assert status == "FAILED"
        assert w.data["silo_folders"].get("0") == name0, \
            "the ownership mapping survives a failed retirement"
        assert os.path.isfile(os.path.join(folder, "asset.txt")), \
            "the assets stay exactly where they were"

        # custom root offline: isdir() lies, so the folder must NOT be
        # reported as absent either
        custom = str(tmp_path / "nas2")
        os.makedirs(custom)
        w.data["files_root"] = custom
        w._files_root_probe = None
        import fastprompter.utils.paths as paths_mod
        monkeypatch.setattr(paths_mod, "isdir_within", lambda p: False)
        w._files_root_probe = None
        status2 = w._delete_file_container("Same", folder)
        assert status2 == "ROOT_UNAVAILABLE"
        assert w.data["silo_folders"].get("0") == name0
        assert os.path.isfile(os.path.join(folder, "asset.txt"))


class TestTrashNoClobber:
    """P1-10: two same-second trashes with the same slug never overwrite."""

    def test_same_second_same_slug_gets_two_files(self, win, iso_root, monkeypatch):
        w = win
        import fastprompter.ui.snippet_ops_mixin as som
        monkeypatch.setattr(som, "_trash_stamp", lambda: "01.01.24-120000")
        w._trash_silo_content("same payload")
        w._trash_silo_content("same payload")

        trash = os.path.join(w._files_root(), "_trash")
        files = sorted(os.listdir(trash))
        assert len(files) == 2, f"expected 2 independent trash files, got {files}"
        contents = set()
        for f in files:
            with open(os.path.join(trash, f), encoding="utf-8") as fh:
                contents.add(fh.read())
        assert contents == {"same payload"}


class TestBakThrottlePerProfile:
    """P1-7: the SQLite .bak throttle is independent per profile."""

    def test_b_backs_up_immediately_after_a(self, monkeypatch, tmp_path):
        db1 = str(tmp_path / "throttle_1.db")
        db2 = str(tmp_path / "throttle_2.db")
        monkeypatch.setattr(state_mod, "get_db_path",
                            lambda profile_id=1: db1 if profile_id == 1 else db2)
        monkeypatch.setattr(
            "fastprompter.utils.portable_backup.run_portable_backup",
            lambda data, profile_id=1: None)
        calls = {"n": 0}
        real_bak = state_mod._backup_atomically

        def counting(src, dest, validate=True):
            calls["n"] += 1
            return real_bak(src, dest, validate=validate)

        monkeypatch.setattr(state_mod, "_backup_atomically", counting)

        s = state_mod.FastPrompterState(profile_id=1)
        try:
            s._last_backup_time_by_profile.clear()
            before = calls["n"]
            s.data["temp_presets_all"]["Code"][0] = "a"
            s.mark_dirty()
            s.save_data_to_db("a", force=True)
            assert calls["n"] == before + 1, "profile A's first save backs up"

            # immediate switch: B's own throttle is empty -> B backs up too
            s.switch_profile(2, save_current=False)
            s.data["temp_presets_all"]["Code"][0] = "b"
            s.mark_dirty()
            s.save_data_to_db("b", force=True)
            assert calls["n"] == before + 2, \
                "B must back up despite A's backup being <60s ago"

            # back to A <60s: A's own throttle still applies -> no new backup
            s.switch_profile(1, save_current=False)
            n_before_a2 = calls["n"]
            s.data["temp_presets_all"]["Code"][0] = "a2"
            s.mark_dirty()
            s.save_data_to_db("a2", force=True)
            assert calls["n"] == n_before_a2, \
                "A's own throttle still applies after the round trip"
        finally:
            s.conn.close()


class TestProfileCategorySelection:
    """P2-21: a profile switch lands on the first VISIBLE project, resolved
    by combo itemData identity — never by a raw cats_order row index (hidden
    projects shift visible indices) and never by a fake 'Text' search."""

    def test_first_visible_project_wins_with_hidden_first(self, win, iso_root):
        w = win
        w.change_profile(1)   # profile 2: fresh data
        w.data["cats_order"] = ["Hidden First", "Visible One", "Visible Two"]
        w.data["categories"] = {"Hidden First": [None] * 10,
                                "Visible One": [None] * 10,
                                "Visible Two": [None] * 10}
        w.data["temp_presets_all"] = {"Hidden First": [""] * 10,
                                      "Visible One": ["# V1", ""],
                                      "Visible Two": [""] * 10}
        w.data["archive_temp_presets_all"] = {"Hidden First": [],
                                              "Visible One": [],
                                              "Visible Two": []}
        w.data["hidden_categories"] = ["Hidden First"]
        w.build_categories()

        # build_categories selected the first VISIBLE project by identity
        assert w.cat_combo.currentData() == "Visible One"
        assert w.cat_combo.currentIndex() == 0
        assert w.get_current_category() == "Visible One"

        # a real profile switch out and back must land the same way
        w.change_profile(0)                 # back to profile 1
        w.change_profile(1)                 # back to profile 2
        assert w.get_current_category() == "Visible One", \
            "the visible-first contract must survive a round trip"
        assert "Hidden First" in w.data["cats_order"], \
            "the hidden project still exists in the data store (nothing deleted)"
        assert w.cat_combo.findData("Hidden First") < 0, \
            "the hidden project must not reappear in the combo"
        w.change_profile(0)                 # leave the window on profile 1


class TestFolderTrashLogRetention:
    """P2-23: a recovery entry survives exactly while a restorable action
    references it; unreferenced orphans are swept only above the derived
    floor (undo capacity 50 x 20 folders per category)."""

    def _make_stub(self):
        import types

        from fastprompter.ui.snippet_ops_mixin import SnippetOpsMixin
        stub = types.SimpleNamespace(
            data={"silo_folders_all": {}, "archive_silo_folders_all": {}},
            data_undo_stack=[],
            dirty=0,
        )
        stub.mark_dirty = lambda: setattr(stub, "dirty", stub.dirty + 1)
        return stub, SnippetOpsMixin

    def test_floor_is_derived_not_magic(self):
        import fastprompter.ui.snippet_ops_mixin as som
        assert som._FOLDER_TRASH_LOG_FLOOR == \
            som._UNDO_MAX_ACTIONS * som._MAX_FOLDERS_PER_CATEGORY
        assert som._FOLDER_TRASH_LOG_FLOOR == 1000
        # the persisted undo file keeps 10 snapshots; the in-memory stack 50
        assert som._FOLDER_TRASH_LOG_FLOOR >= 10 * som._MAX_FOLDERS_PER_CATEGORY

    def test_referenced_entry_survives_past_the_floor(self):
        stub, Mixin = self._make_stub()
        stub.data["silo_folders_all"]["Code"] = {"0": "keep-folder"}
        log = [("C:/x/keep-folder", "C:/trash/keep-folder-1"),
               ("C:/x/old-folder", "C:/trash/old-folder-2")] * 600   # 1200 entries
        Mixin._prune_folder_trash_log(stub, log)
        assert len(log) == 600, "referenced entries must survive the floor"
        assert all(o == "C:/x/keep-folder" for o, _t in log)
        assert stub.dirty == 1

    def test_snapshot_reference_keeps_the_entry(self):
        """The category-delete case: the map lives in a live undo snapshot,
        not in the current data — those entries must survive."""
        stub, Mixin = self._make_stub()
        stub.data_undo_stack = [{
            "silo_folders_all": {"Nuke": {"1": "a-folder"}},
            "archive_silo_folders_all": {"Nuke": {"0": "arc-folder"}},
        }]
        log = [("C:/x/a-folder", "C:/trash/a-folder-1"),
               ("C:/x/arc-folder", "C:/trash/arc-folder-2")] * 600
        Mixin._prune_folder_trash_log(stub, log)
        assert len(log) == 1200, "snapshot-referenced entries must survive"
        assert stub.dirty == 0

    def test_unreferenced_orphans_stay_below_the_floor(self):
        stub, Mixin = self._make_stub()
        log = [("C:/x/unref", "C:/trash/unref-1")] * 500
        Mixin._prune_folder_trash_log(stub, log)
        assert len(log) == 500, "below the floor nothing is swept"
        assert stub.dirty == 0
