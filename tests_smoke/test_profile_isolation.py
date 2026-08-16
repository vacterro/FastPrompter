"""Regression (P0-2/3/4): filesystem containers are profile-scoped, category
physical identity is collision-safe and stable, and category delete retires
the real mapped folders through the canonical primitive.

P0-2  profiles have the same DB boundary on disk: profile 1 keeps the legacy
      root, profile 2+ gets ``_profiles/p<id>``. Trash, undo-restore and the
      File Container panel all follow the profile.
P0-3  ``silo_slug`` is lossy and must NOT be unique identity: "A:B" vs "AB",
      Japanese/emoji names, case-only and long-prefix collisions each get a
      DISTINCT physical component via the persistent ``category_file_dirs``
      map; a category rename keeps its physical component; legacy dirs are
      adopted only when unambiguous.
P0-4  deleting a category retires every normal + archive silo folder under
      its mapped physical dir into the profile-scoped trash (never a
      files_root+name join), and Ctrl+Z brings text AND folders back.
"""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import tempfile

import pytest
from PyQt6.QtWidgets import QApplication, QMessageBox

import fastprompter.core.state as state_mod
from fastprompter.main import FastPrompter
from fastprompter.ui.file_container import silo_slug

_app = QApplication.instance() or QApplication([])
_tmpdir = tempfile.mkdtemp(prefix="fastprompter_profile_iso_")


@pytest.fixture(scope="module")
def win():
    state_mod.get_db_path = lambda profile_id=1: os.path.join(_tmpdir, f"iso_{profile_id}.db")
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
def private_root(win, monkeypatch, tmp_path):
    """Point the app's data dir (and therefore DBs + files root) at a UNIQUE
    temp root, and make sure the shared window is back on profile 1 with a
    clean physical-identity map."""
    root = str(tmp_path / "profile_root")
    os.makedirs(root, exist_ok=True)
    import fastprompter.utils.paths as paths_mod
    monkeypatch.setattr(paths_mod, "get_data_dir", lambda: root)
    # ensure the window's own cached probes don't fight the new root
    win._files_root_probe = None
    pid = getattr(getattr(win, "state", None), "profile_id", 1)
    if pid != 1:
        win.change_profile(0)      # back to profile 1 (idx+1 == 1)
    win.data["category_file_dirs"].clear()
    win.data["folder_trash_log"][:] = []
    win.data_undo_stack = []
    win.data_redo_stack = []
    return root


def _write(d, name, content):
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, name), "w", encoding="utf-8") as f:
        f.write(content)


def _read(d, name):
    with open(os.path.join(d, name), encoding="utf-8") as f:
        return f.read()


class TestProfileFileIsolation:
    """P0-2: two profiles with identical project/silo names never share,
    adopt or delete each other's file folders."""

    def test_same_names_stay_isolated_across_switches(self, win, private_root):
        p1 = win
        p1.data["cats_order"] = ["Same"]
        p1.data["categories"] = {"Same": [None] * 10}
        p1.data["temp_presets_all"] = {"Same": ["# Same", ""]}
        p1.data["archive_temp_presets_all"] = {"Same": []}
        p1.data["silo_folders"].clear()
        p1.build_categories()
        p1.cat_combo.setCurrentIndex(0)
        p1.on_tab_changed(0)
        p1.silo_docs[:] = []
        p1.data["temp_presets"] = p1.data["temp_presets_all"]["Same"]
        p1._switch_to_slot(0, initial=True)

        folder_p1 = p1._silo_folder_dir(0)
        _write(folder_p1, "P1.txt", "profile one payload")
        assert "_profiles" not in folder_p1, "profile 1 keeps the legacy layout"

        # --- switch to profile 2, same names, different file -------------
        p1.change_profile(1)          # idx+1 -> profile 2
        p2 = p1
        p2.data["cats_order"] = ["Same"]
        p2.data["categories"] = {"Same": [None] * 10}
        p2.data["temp_presets_all"] = {"Same": ["# Same", ""]}
        p2.data["archive_temp_presets_all"] = {"Same": []}
        p2.data["silo_folders"].clear()
        p2.build_categories()
        p2.cat_combo.setCurrentIndex(0)
        p2.on_tab_changed(0)
        p2.silo_docs[:] = []
        p2.data["temp_presets"] = p2.data["temp_presets_all"]["Same"]
        p2._switch_to_slot(0, initial=True)

        folder_p2 = p2._silo_folder_dir(0)
        assert os.sep + "_profiles" + os.sep in folder_p2
        _write(folder_p2, "P2.txt", "profile two payload")

        assert _read(folder_p2, "P2.txt") == "profile two payload"
        assert not os.path.exists(os.path.join(folder_p2, "P1.txt"))
        assert _read(folder_p1, "P1.txt") == "profile one payload"
        assert not os.path.exists(os.path.join(folder_p1, "P2.txt"))

        # --- switch back to profile 1 ------------------------------------
        p2.change_profile(0)          # back to profile 1
        assert p1._files_root() == os.path.dirname(os.path.dirname(folder_p1))
        assert p1._silo_folder_dir(0) == folder_p1
        assert _read(folder_p1, "P1.txt") == "profile one payload"
        assert not os.path.exists(os.path.join(folder_p1, "P2.txt")), \
            "profile 1 must never see profile 2's file"

        # --- switch to profile 2 again: P2 still owns its file -----------
        p1.change_profile(1)
        assert p2._silo_folder_dir(0) == folder_p2
        assert _read(folder_p2, "P2.txt") == "profile two payload"

    def test_trash_and_undo_restore_are_isolated(self, win, private_root):
        win.data["cats_order"] = ["Iso"]
        win.data["categories"] = {"Iso": [None] * 10}
        win.data["temp_presets_all"] = {"Iso": ["# Trash Me", ""]}
        win.data["archive_temp_presets_all"] = {"Iso": []}
        win.data["silo_folders"].clear()
        win.data["folder_trash_log"][:] = []
        win.build_categories()
        win.cat_combo.setCurrentIndex(0)
        win.on_tab_changed(0)
        win.silo_docs[:] = []
        win.data["temp_presets"] = win.data["temp_presets_all"]["Iso"]
        win._switch_to_slot(0, initial=True)

        folder_p1 = win._silo_folder_dir(0)
        _write(folder_p1, "keep.txt", "precious")
        p1_root = win._files_root()

        win.change_profile(1)         # profile 2
        win.data["cats_order"] = ["Iso"]
        win.data["categories"] = {"Iso": [None] * 10}
        win.data["temp_presets_all"] = {"Iso": ["# Trash Me", ""]}
        win.data["archive_temp_presets_all"] = {"Iso": []}
        win.data["silo_folders"].clear()
        win.data["folder_trash_log"][:] = []
        win.build_categories()
        win.cat_combo.setCurrentIndex(0)
        win.on_tab_changed(0)
        win.silo_docs[:] = []
        win.data["temp_presets"] = win.data["temp_presets_all"]["Iso"]
        win._switch_to_slot(0, initial=True)
        # profile 2 owns a REAL folder+file (this is what allocates the
        # per-slot mapping the undo snapshot must carry)
        folder_p2 = win._silo_folder_dir(0)
        _write(folder_p2, "keep.txt", "precious")
        p2_root = win._files_root()

        # profile 2 deletes its silo -> trash goes to PROFILE 2's trash
        win.del_silo(0)
        p2_trash = os.path.join(p2_root, "_trash")
        assert os.path.isdir(p2_trash) and os.listdir(p2_trash), \
            "profile 2's trash must hold the retired folder"
        p1_trash = os.path.join(p1_root, "_trash")
        assert not os.path.exists(p1_trash) or not os.listdir(p1_trash), \
            "profile 1's trash must be untouched by profile 2's delete"
        assert os.path.isfile(os.path.join(folder_p1, "keep.txt")), \
            "profile 1's folder must be untouched"

        # profile 2 undoes -> its own folder comes back, profile 1 untouched
        assert win.undo_action() is True
        folder_p2 = win._silo_folder_dir(0)
        assert os.path.isfile(os.path.join(folder_p2, "keep.txt"))
        assert os.path.isfile(os.path.join(folder_p1, "keep.txt"))
        assert not os.path.exists(p1_trash)

    def test_file_panel_rebinds_after_profile_switch(self, win, private_root):
        win.data["cats_order"] = ["Panel"]
        win.data["categories"] = {"Panel": [None] * 10}
        win.data["temp_presets_all"] = {"Panel": ["# Panel", ""]}
        win.data["archive_temp_presets_all"] = {"Panel": []}
        win.data["silo_folders"].clear()
        win.build_categories()
        win.cat_combo.setCurrentIndex(0)
        win.on_tab_changed(0)
        win.silo_docs[:] = []
        win.data["temp_presets"] = win.data["temp_presets_all"]["Panel"]
        win._switch_to_slot(0, initial=True)

        panel = win._ensure_file_container()
        panel.docked = True
        panel.open_for(win._silo_folder_dir(0))
        _write(panel.folder, "p1-only.txt", "one")
        folder_p1 = panel.folder

        win.change_profile(1)         # profile 2
        win.data["cats_order"] = ["Panel"]
        win.data["categories"] = {"Panel": [None] * 10}
        win.data["temp_presets_all"] = {"Panel": ["# Panel", ""]}
        win.data["archive_temp_presets_all"] = {"Panel": []}
        win.data["silo_folders"].clear()
        win.build_categories()
        win.cat_combo.setCurrentIndex(0)
        win.on_tab_changed(0)
        win.silo_docs[:] = []
        win.data["temp_presets"] = win.data["temp_presets_all"]["Panel"]
        win._switch_to_slot(0, initial=True)

        # the panel must NOT keep showing (or accepting drops for) profile 1
        assert panel.folder != folder_p1, \
            "the panel must not keep pointing at the old profile's folder"
        assert os.path.dirname(panel.folder) == os.path.dirname(
            win._silo_folder_dir(0)), "panel must point at the new profile's silo folder"
        assert not os.path.exists(os.path.join(panel.folder, "p1-only.txt"))


class TestCategoryPhysicalIdentity:
    """P0-3: distinct logical categories can never alias one physical dir."""

    COLLISIONS = [
        ("A:B", "AB"),
        ("A?B", "A:B"),
        ("??", "???"),
        ("??", "??"),
        ("Case", "case"),
        ("x" * 40 + "prefix-one", "x" * 40 + "prefix-two"),
        ("x" * 60 + "AAAA", "x" * 60 + "BBBB"),
    ]

    def test_collision_matrix_is_distinct(self, win, private_root):
        win.data["category_file_dirs"].clear()
        comps = {}
        for a, b in self.COLLISIONS:
            if a not in comps:
                comps[a] = win._category_files_dir(a)
            if b not in comps:
                comps[b] = win._category_files_dir(b)
        for (a, b) in self.COLLISIONS:
            ca, cb = comps[a], comps[b]
            assert ca != cb, f"{a!r} and {b!r} alias one physical dir: {ca!r}"
            assert os.path.normcase(ca) != os.path.normcase(cb)
            assert ca and cb
        # every component is a single safe name
        from fastprompter.utils.path_safety import validate_component
        for comp in comps.values():
            assert validate_component(comp)[0] == comp, comp

    def test_legacy_dir_adopted_only_when_unambiguous(self, win, private_root):
        win.data["category_file_dirs"].clear()
        root = win._files_root()
        os.makedirs(os.path.join(root, "code"), exist_ok=True)   # legacy "Code"
        assert win._category_files_dir("Code") == "code"
        assert os.path.normcase(win._category_files_dir("Code")) == \
            os.path.normcase("code")

        # two slug-colliding categories: the second must NEVER adopt "ab"
        win.data["cats_order"] = ["A:B", "AB"]
        os.makedirs(os.path.join(root, "ab"), exist_ok=True)
        ca = win._category_files_dir("A:B")
        cb = win._category_files_dir("AB")
        assert os.path.normcase(ca) != os.path.normcase(cb), \
            "ambiguous legacy dir was shared by two categories"
        assert os.path.normcase(ca) == os.path.normcase("ab") or \
            os.path.normcase(cb) == os.path.normcase("ab")
        # the loser did not adopt the ambiguous dir, and it is preserved
        assert os.path.isdir(os.path.join(root, "ab"))

    def test_rename_keeps_the_physical_component(self, win, private_root):
        win.data["category_file_dirs"].clear()
        win.data["cats_order"] = ["Old Name"]
        before = win._category_files_dir("Old Name")
        win.data["category_file_dirs"]["New Name"] = \
            win.data["category_file_dirs"].pop("Old Name")
        after = win._category_files_dir("New Name")
        assert after == before, "rename must keep the physical folder"
        assert win.data["category_file_dirs"].get("Old Name") is None

    def test_category_slug_lossy_pairs_never_share(self, win, private_root):
        """silo_slug alone WOULD collapse these — the mapping must not."""
        win.data["category_file_dirs"].clear()
        for a, b in self.COLLISIONS:
            if silo_slug(a) == silo_slug(b):
                ca = win._category_files_dir(a)
                cb = win._category_files_dir(b)
                assert ca != cb, f"{a!r} vs {b!r}: slugs collide and dirs alias"


class TestCategoryDeleteRetirement:
    """P0-4: category delete retires the mapped folders, undo restores them."""

    def _seed_category(self, win, cat):
        win.data["cats_order"] = [cat, "Other"]
        win.data["categories"] = {cat: [None] * 10, "Other": [None] * 10}
        win.data["temp_presets_all"] = {cat: ["# Normal", "# Archived"], "Other": [""] * 10}
        win.data["archive_temp_presets_all"] = {cat: ["# Archived"], "Other": []}
        win.data["silo_folders_all"].setdefault(cat, {})
        win.data["archive_silo_folders_all"].setdefault(cat, {})
        win.data["silo_folders"].clear()
        win.data["archive_silo_folders"].clear()
        win.data["folder_trash_log"][:] = []
        win.build_categories()
        win.cat_combo.setCurrentIndex(0)
        win.on_tab_changed(0)
        win.silo_docs[:] = []
        win.data["temp_presets"] = win.data["temp_presets_all"][cat]
        win._switch_to_slot(0, initial=True)
        return cat

    def test_delete_retires_mapped_folders_and_undo_restores(
            self, win, private_root, monkeypatch):
        cat = self._seed_category(win, "Nuke")
        cat_dir = win._category_files_dir(cat)
        root = win._files_root()

        # two normal silos with real folders + files
        normal = win._silo_folder_dir(0)
        _write(normal, "n.txt", "normal file")
        second = win._silo_folder_dir(1)
        _write(second, "s.txt", "second file")
        # archive the middle silo through the REAL flow: text + folder move
        # together into the archive space (slot-0 insert, identity preserved)
        win._archive_silo(1)
        arc = win._silo_folder_dir(0, is_archive=True)
        _write(arc, "a.txt", "archive file")

        monkeypatch.setattr(QMessageBox, "question",
                            staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes))
        win.del_category()

        # every folder retired into the profile-scoped trash, nothing left
        trash = os.path.join(root, "_trash")
        assert os.path.isdir(trash)
        retired = set()
        for base, _dirs, files in os.walk(trash):
            for n in files:
                retired.add(n)
        assert {"n.txt", "a.txt", "s.txt"} <= retired, retired
        assert not os.path.exists(os.path.join(normal, "n.txt"))
        assert not os.path.exists(os.path.join(arc, "a.txt"))
        assert not os.path.exists(os.path.join(second, "s.txt"))
        assert cat not in win.data["cats_order"]
        assert cat not in win.data["categories"]
        assert cat not in win.data["category_file_dirs"]

        # undo: text AND folders return, files restored to the SAME dirs
        assert win.undo_action() is True
        assert cat in win.data["cats_order"]
        assert win._category_files_dir(cat) == cat_dir, \
            "undo must restore the original physical component"
        assert os.path.isfile(os.path.join(normal, "n.txt")), "normal silo folder lost"
        assert os.path.isfile(os.path.join(arc, "a.txt")), "archive silo folder lost"
        assert os.path.isfile(os.path.join(second, "s.txt")), "second silo folder lost"

    def test_delete_aborts_when_trash_move_fails(self, win, private_root, monkeypatch):
        """P0-1: a retirement that fails (simulated trash-move OSError) must
        ABORT the category deletion — the tab, the maps and the assets all
        survive, and no fake undo entry lingers."""
        import fastprompter.ui.file_container as fc
        cat = self._seed_category(win, "Keep")
        normal = win._silo_folder_dir(0)
        _write(normal, "n.txt", "precious")

        def boom_move(src, dest, root=None, root_identity=None):
            raise OSError("simulated trash move failure")

        monkeypatch.setattr(fc, "_move_into_container", boom_move)
        monkeypatch.setattr(
            QMessageBox, "question",
            staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes))
        n_undo = len(win.data_undo_stack)
        win.del_category()

        assert cat in win.data["cats_order"], "the tab must survive a failed retirement"
        assert cat in win.data["categories"]
        assert win.data["category_file_dirs"].get(cat), \
            "ownership mapping must survive a failed retirement"
        assert os.path.isfile(os.path.join(normal, "n.txt")), \
            "the assets must be exactly where they were"
        assert len(win.data_undo_stack) == n_undo, \
            "no undo entry may linger for a deletion that never happened"

    def test_delete_aborts_when_custom_root_is_unavailable(
            self, win, private_root, monkeypatch, tmp_path):
        """ROOT_UNAVAILABLE through the full category delete: the deletion
        must abort and never write anywhere."""
        cat = self._seed_category(win, "Offline")
        normal = win._silo_folder_dir(0)
        _write(normal, "n.txt", "precious")
        custom = str(tmp_path / "nas_offline")
        os.makedirs(custom)
        win.data["files_root"] = custom
        win._files_root_probe = None
        import fastprompter.utils.paths as paths_mod
        monkeypatch.setattr(paths_mod, "isdir_within", lambda p: False)
        win._files_root_probe = None
        monkeypatch.setattr(
            QMessageBox, "question",
            staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes))
        n_undo = len(win.data_undo_stack)
        win.del_category()

        assert cat in win.data["cats_order"]
        assert win.data["category_file_dirs"].get(cat)
        assert len(win.data_undo_stack) == n_undo
        # nothing was written anywhere: no trash dir, no shadow under local
        assert not os.path.exists(os.path.join(win._files_root(), "_trash"))
        assert os.path.isfile(os.path.join(normal, "n.txt"))
