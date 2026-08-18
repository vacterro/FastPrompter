"""Regression (P0-1): backup_silo_to_files cannot escape the container.

The old implementation built its folder by hand:

    folder = os.path.join(self._files_root(), self.get_current_category(), safe)
    path = os.path.join(folder, name)
    open(path, "w")

which (a) used the RAW category name вЂ” ``..\\outside`` escapes the files
root entirely вЂ” (b) accepted ANY user filename, so ``..\\evil.txt`` or
``C:\\evil.txt`` escaped the folder, and (c) silently overwrote an existing
destination with a plain ``open(..., "w")``.

This suite drives the REAL method through the same dialog path production
uses and proves nothing is ever written outside the canonical per-slot silo
folder, hostile names are rejected by the shared validator, existing files
are never overwritten, and batch save goes through the same safe path.
"""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import tempfile

import pytest
from PyQt6.QtWidgets import QApplication, QDialog, QLineEdit, QMessageBox

import fastprompter.core.state as state_mod
from fastprompter.main import FastPrompter

_app = QApplication.instance() or QApplication([])
_tmpdir = tempfile.mkdtemp(prefix="fastprompter_backup_bypass_")


@pytest.fixture(scope="module")
def win():
    state_mod.get_db_path = lambda profile_id=1: os.path.join(_tmpdir, f"bb_{profile_id}.db")
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
def hostile_win(win, monkeypatch):
    """A window whose ACTIVE category is a hostile name, on a private root."""
    root = os.path.join(_tmpdir, "bypass_root")
    os.makedirs(root, exist_ok=True)
    win._files_root = lambda: root
    win.data["cats_order"] = ["..\\outside", "Safe"]
    win.data["categories"] = {"..\\outside": [None] * 10, "Safe": [None] * 10}
    win.data["temp_presets_all"] = {"..\\outside": ["# My Silo\\ncontent"], "Safe": [""] * 10}
    win.data["archive_temp_presets_all"] = {"..\\outside": [], "Safe": []}
    win.data["silo_folders"].clear()
    win.data["category_file_dirs"].clear()
    win.build_categories()
    win.cat_combo.setCurrentIndex(0)   # the hostile category
    win.on_tab_changed(0)
    win.silo_docs[:] = []
    win.data["temp_presets"] = win.data["temp_presets_all"]["..\\outside"]
    win._switch_to_slot(0, initial=True)
    # the backup dialog's buttons: "Copy" (never "Copy + Clear")
    yield win, root
    win.data["temp_presets_all"] = {"..\\outside": [""] * 10, "Safe": [""] * 10}
    win.__dict__.pop("_files_root", None)


def _outside_dir(tmp_path):
    d = os.path.join(str(tmp_path), "outside")
    os.makedirs(d, exist_ok=True)
    return d


def _snapshot(path):
    out = []
    for base, dirs, files in os.walk(path):
        rel = os.path.relpath(base, path)
        for n in files:
            out.append(os.path.normpath(os.path.join(rel, n)))
        for d in dirs:
            out.append(os.path.normpath(os.path.join(rel, d)) + "/")
    return sorted(out)


def _fake_dialog(monkeypatch, name):
    """Auto-accept the backup dialog with ``name`` as the filename."""

    def fake_exec(dlg):
        le = dlg.findChild(QLineEdit)
        if le is not None:
            le.setText(name)
        return 1   # QDialog.Accepted

    monkeypatch.setattr(QDialog, "exec", fake_exec)
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: None)


@pytest.mark.parametrize("bad", ["..\\evil.txt", "C:\\evil.txt", "CON", "foo/bar.txt", "foo\\bar.txt", ".."])
def test_hostile_filename_cannot_escape_the_canonical_folder(hostile_win, tmp_path, monkeypatch, bad):
    win, root = hostile_win
    outside = _outside_dir(tmp_path)
    before = _snapshot(outside)
    _fake_dialog(monkeypatch, bad)
    win.backup_silo_to_files(0)
    # the canonical silo folder is the ONLY place a file may appear
    assert _snapshot(outside) == before, "a hostile filename escaped the container"
    canon = win._silo_folder_dir(0)
    assert _snapshot(canon) == [], f"a hostile filename was written into the container: {_snapshot(canon)}"
    # no stray folder may appear beside the canonical one, either
    allowed = {win._category_files_dir("..\\outside"), "_trash"}
    assert set(os.listdir(root)) <= allowed, \
        f"unexpected entries under the files root: {sorted(os.listdir(root))}"
    canon_dir = win._silo_folder_dir(0)
    if os.path.isdir(canon_dir):
        assert os.listdir(canon_dir) == []


def test_unicode_filename_stays_inside(hostile_win, tmp_path):
    win, root = hostile_win
    win.backup_silo_to_files.__self__  # sanity: method exists
    from fastprompter.ui.snippet_ops_mixin import SnippetOpsMixin
    dest, err = SnippetOpsMixin._write_backup_file(
        win, win._silo_folder_dir(0), "заметка.txt", "silo payload")
    assert dest is not None, err
    assert os.path.dirname(dest) == win._silo_folder_dir(0)
    with open(dest, encoding="utf-8") as f:
        assert f.read() == "silo payload"
    assert not os.path.exists(os.path.join(_outside_dir(tmp_path), "заметка.txt"))


def test_existing_destination_is_never_overwritten(hostile_win):
    win, root = hostile_win
    folder = win._silo_folder_dir(0)
    os.makedirs(folder, exist_ok=True)
    existing = os.path.join(folder, "backup.txt")
    with open(existing, "w", encoding="utf-8") as f:
        f.write("KEEP ME")
    from fastprompter.ui.snippet_ops_mixin import SnippetOpsMixin
    dest, err = SnippetOpsMixin._write_backup_file(win, folder, "backup.txt", "new payload")
    assert dest is not None, err
    assert dest != existing, "the existing file was silently overwritten"
    with open(existing, encoding="utf-8") as f:
        assert f.read() == "KEEP ME"
    with open(dest, encoding="utf-8") as f:
        assert f.read() == "new payload"


def test_batch_save_goes_through_the_same_safe_path(hostile_win, tmp_path, monkeypatch):
    """batch_save_selected_silos must route through backup_silo_to_files (and
    therefore through the canonical folder + validator), never a side path."""
    win, root = hostile_win
    outside = _outside_dir(tmp_path)
    before = _snapshot(outside)
    _fake_dialog(monkeypatch, "batch.txt")
    win._silo_selection = {0}
    win.batch_save_selected_silos()
    canon = win._silo_folder_dir(0)
    assert os.path.isfile(os.path.join(canon, "batch.txt"))
    assert _snapshot(outside) == before
    win._silo_selection = set()


def test_hostile_category_name_still_resolves_inside_the_root(hostile_win):
    """The canonical helper must map the hostile category to a SAFE component
    inside the files root вЂ” never use the raw name as a path segment."""
    win, root = hostile_win
    comp = win._category_files_dir("..\\outside")
    assert os.path.sep not in comp and "\\" not in comp and "/" not in comp
    assert os.path.isabs(os.path.join(root, comp))
    assert os.path.abspath(os.path.join(root, comp)).startswith(os.path.abspath(root))
