"""Regression: File Container operations cannot escape the container root.

Drives the REAL panel methods (rename / clipboard->file / new folder /
template build) with malicious names and proves no file or directory appears
outside the resolved container folder (or, for the drive-qualified case, that
os.path.join cannot be tricked into discarding the root).
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
from fastprompter.ui.file_container import FileContainerPanel

_app = QApplication.instance() or QApplication([])
_tmpdir = tempfile.mkdtemp(prefix="fastprompter_containment_")


@pytest.fixture(scope="module")
def win():
    state_mod.get_db_path = lambda profile_id=1: os.path.join(_tmpdir, f"c_{profile_id}.db")
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


@pytest.fixture()
def panel(win, tmp_path):
    root = str(tmp_path / "container_root")
    os.makedirs(root, exist_ok=True)
    p = FileContainerPanel(win)
    p.open_for(root)
    yield root, p
    p.close()


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


def _write(path, text="payload"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


@pytest.mark.parametrize("bad", ["..\\evil.txt", "C:\\evil.txt", "c:/evil.txt", "..", "CON.txt"])
def test_rename_cannot_leave_root(panel, bad, tmp_path):
    root, p = panel
    outside = _outside_dir(tmp_path)
    before = _snapshot(outside)
    _write(os.path.join(root, "note.txt"))
    p.refresh()
    p._rename(os.path.join(root, "note.txt"), new_name=bad)
    assert os.path.isfile(os.path.join(root, "note.txt"))      # untouched
    assert _snapshot(outside) == before                         # nothing escaped
    assert not os.path.exists(os.path.join(outside, "evil.txt"))


def test_rename_valid_stays_inside(panel):
    root, p = panel
    _write(os.path.join(root, "note.txt"))
    p.refresh()
    p._rename(os.path.join(root, "note.txt"), new_name="renamed")
    assert os.path.isfile(os.path.join(root, "renamed.txt")) is False
    assert os.path.isfile(os.path.join(root, "renamed")) is True
    assert not os.path.isfile(os.path.join(root, "note.txt"))


def test_clipboard_save_cannot_leave_root(panel, tmp_path):
    root, p = panel
    outside = _outside_dir(tmp_path)
    before = _snapshot(outside)
    QApplication.clipboard().setText("clip payload")
    p.save_clipboard_as_file(filename="..\\..\\evil")
    assert _snapshot(outside) == before
    p.save_clipboard_as_file(filename="C:\\evil")
    assert _snapshot(outside) == before
    assert os.listdir(root) == []


def test_clipboard_save_valid_stays_inside(panel):
    root, p = panel
    QApplication.clipboard().setText("clip payload")
    p.save_clipboard_as_file(filename="note")
    assert os.path.isfile(os.path.join(root, "note.txt"))
    _write(os.path.join(root, "note.txt"), "clip payload")


def test_new_folder_rejects_traversal(panel, tmp_path):
    root, p = panel
    outside = _outside_dir(tmp_path)
    before = _snapshot(outside)
    for bad in ("..", "..\\x", "C:\\x"):
        p.new_folder(name=bad)
    assert _snapshot(outside) == before
    assert os.listdir(root) == []


def test_new_folder_valid_stays_inside(panel):
    root, p = panel
    p.new_folder(name="assets")
    assert os.path.isdir(os.path.join(root, "assets"))


def test_template_build_cannot_leave_root(panel, tmp_path):
    root, p = panel
    outside = _outside_dir(tmp_path)
    before = _snapshot(outside)
    p.build_template_folders(
        template="ae, ..\\evil, C:\\Windows, good, CON, a/b")
    # valid single names only; everything hostile is skipped. Assert on the
    # real listing (os.path.isdir(root\\C:) is a Windows drive-relative
    # quirk that answers True for a path Windows never created).
    entries = sorted(os.listdir(root))
    assert entries == ["ae", "good"], entries
    assert _snapshot(outside) == before


def test_unicode_and_spaces_stay_inside(panel):
    root, p = panel
    _write(os.path.join(root, "unicode.txt"))
    p.refresh()
    p._rename(os.path.join(root, "unicode.txt"), new_name="Р·Р°РјРµС‚РєР° СЃ РїСЂРѕР±РµР»Р°РјРё")
    assert os.path.isdir(os.path.join(root, "Р·Р°РјРµС‚РєР° СЃ РїСЂРѕР±РµР»Р°РјРё")) or \
        os.path.isfile(os.path.join(root, "Р·Р°РјРµС‚РєР° СЃ РїСЂРѕР±РµР»Р°РјРё"))
    p.new_folder(name="РїР°РїРєР° 1")
    assert os.path.isdir(os.path.join(root, "РїР°РїРєР° 1"))
