"""Phase-7: File Container identity follows the silo, not the slot number.

The per-slot ``silo_folders`` map is FastPrompter's identity system for file
containers. This suite drives the REAL window methods and proves that text,
the folder mapping, the physical directory and any files inside stay
associated through: same-title collisions, empty titles, title renames,
renames into an occupied title, reorders, archiving, and a save/reload round
trip.
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
_tmpdir = tempfile.mkdtemp(prefix="fastprompter_folder_id_")


@pytest.fixture(scope="module")
def win():
    state_mod.get_db_path = lambda profile_id=1: os.path.join(_tmpdir, f"i_{profile_id}.db")
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
def root(win):
    r = os.path.join(_tmpdir, "identity_root")
    win._files_root = lambda: r
    win.cat_combo.setCurrentIndex(0)
    win.on_tab_changed(0)
    win.data["temp_presets"][:] = ["# A", "# B", "# C"]
    win.data["silo_folders"].clear()
    win.data["pinned_silos"][:] = []
    win.silo_docs[:] = []
    win._switch_to_slot(0, initial=True)
    yield r
    win.__dict__.pop("_files_root", None)


def _make_file(d, name="precious.txt"):
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, name), "w", encoding="utf-8") as f:
        f.write("keep me")


def _dir(win, idx, is_archive=False):
    """The physical container folder for a slot."""
    return win._silo_folder_dir(idx, is_archive=is_archive)


def _name(win, idx, is_archive=False):
    return win._silo_folder_name(idx, is_archive=is_archive)


class TestCollision:
    def test_same_title_silos_get_distinct_folders(self, win, root):
        win.data["temp_presets"][:] = ["# Notes", "# Notes", "# Notes"]
        win.silo_docs[:] = []
        win._switch_to_slot(0, initial=True)
        names = {_name(win, i) for i in range(3)}
        assert len(names) == 3, names

    def test_two_empty_silos_get_distinct_folders(self, win, root):
        win.data["temp_presets"][:] = ["", ""]
        win.silo_docs[:] = []
        win._switch_to_slot(0, initial=True)
        names = {_name(win, i) for i in range(2)}
        assert len(names) == 2, names


class TestRename:
    def test_title_rename_moves_folder_to_free_slug(self, win, root):
        win.data["temp_presets"][:] = ["# Old Title"]
        win.silo_docs[:] = []
        win._switch_to_slot(0, initial=True)
        before = _name(win, 0)
        old_dir = _dir(win, 0)
        _make_file(old_dir)

        win.data["temp_presets"][0] = "# New Title"
        after = _name(win, 0)
        new_dir = _dir(win, 0)

        assert before == "old-title"
        assert after == "new-title"
        assert os.path.isdir(new_dir)
        assert os.path.isfile(os.path.join(new_dir, "precious.txt"))
        assert not os.path.exists(old_dir)

    def test_rename_into_occupied_title_keeps_folder(self, win, root):
        win.data["temp_presets"][:] = ["# A", "# A"]
        win.silo_docs[:] = []
        win._switch_to_slot(0, initial=True)
        name0 = _name(win, 0)      # "a"
        name1 = _name(win, 1)      # "a-2"
        assert name0 != name1

        # slot1 moves onto a free slug
        win.data["temp_presets"][1] = "# B"
        assert _name(win, 1) == "b"

        # slot0 tries to take "b" — already taken, so it stays put
        win.data["temp_presets"][0] = "# B"
        assert _name(win, 0) == "a"

    def test_rename_keeps_files_inside_the_container(self, win, root):
        win.data["temp_presets"][:] = ["# Rename Me"]
        win.silo_docs[:] = []
        win._switch_to_slot(0, initial=True)
        _make_file(_dir(win, 0))
        win.data["temp_presets"][0] = "# Renamed"
        assert os.path.isfile(os.path.join(_dir(win, 0), "precious.txt"))


class TestReorder:
    def test_reorder_moves_folder_mapping_with_the_silo(self, win, root):
        win.data["temp_presets"][:] = ["# Alpha", "# Beta", "# Gamma"]
        win.silo_docs[:] = []
        win._switch_to_slot(0, initial=True)
        folders = {i: _name(win, i) for i in range(3)}
        for i in range(3):
            _make_file(_dir(win, i), f"file-{i}.txt")

        # move silo 0 ("Alpha") to position 2
        win.move_temp_to_index(0, 2)

        assert win.data["temp_presets"][2] == "# Alpha"
        assert _name(win, 2) == folders[0]
        assert os.path.isfile(os.path.join(_dir(win, 2), "file-0.txt"))
        # every other silo keeps its own folder
        assert _name(win, 0) == folders[1]
        assert _name(win, 1) == folders[2]


class TestArchive:
    def test_archive_moves_folder_identity_with_the_text(self, win, root):
        win.data["temp_presets"][:] = ["# Archivable"]
        win.silo_docs[:] = []
        win._switch_to_slot(0, initial=True)
        _make_file(_dir(win, 0))
        normal_name = _name(win, 0)

        win._archive_silo(0)

        # the folder identity moved to the archive, and the normal slot is empty
        assert win.data["archive_silo_folders"].get("0") == normal_name
        assert _name(win, 0, is_archive=True) == normal_name
        assert os.path.isfile(os.path.join(_dir(win, 0, is_archive=True), "precious.txt"))
        assert not (win.data["temp_presets"][0] or "").strip()


class TestPersistence:
    def test_folder_mapping_survives_a_save_reload(self, win, root, monkeypatch):
        monkeypatch.setattr(
            "fastprompter.utils.portable_backup.run_portable_backup",
            lambda data, profile_id=1: None)
        win.data["temp_presets"][:] = ["# Persisted"]
        win.silo_docs[:] = []
        win._switch_to_slot(0, initial=True)
        name = _name(win, 0)
        cat = win.get_current_category()
        win.mark_dirty()
        win.save_data_to_db(force=True)

        # a fresh state reloads the same mapping for the same category
        s = state_mod.FastPrompterState(profile_id=1)
        try:
            stored = s.data.get("silo_folders_all", {}).get(cat, {})
            assert stored.get("0") == name
        finally:
            s.conn.close()
