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

def _no_tmp_left(root):
    for base, _dirs, files in os.walk(root):
        for f in files:
            if f.endswith(".fptmp"):
                return False
    return True


def test_import_failure_leaves_no_partial_in_the_container(panel, monkeypatch):
    root, p = panel
    import shutil as _sh

    src = os.path.join(_tmpdir, "partial_src.txt")
    _write(src, "full content")

    def _flaky_copy2(s, dst, *a, **k):
        with open(dst, "w", encoding="utf-8") as f:
            f.write("partial")
        raise OSError("disk full mid-copy")

    monkeypatch.setattr(_sh, "copy2", _flaky_copy2)
    p.import_paths([src])

    assert os.listdir(root) == []          # no partial file, no temp
    assert _no_tmp_left(root)


def test_export_failure_leaves_no_partial_in_the_target(panel, monkeypatch):
    root, p = panel
    import shutil as _sh

    from PyQt6.QtWidgets import QFileDialog

    _write(os.path.join(root, "to_export.txt"), "data")
    target = os.path.join(_tmpdir, "export_target")
    os.makedirs(target, exist_ok=True)
    monkeypatch.setattr(QFileDialog, "getExistingDirectory",
                        staticmethod(lambda *a, **k: target))

    def _flaky_copy2(s, dst, *a, **k):
        with open(dst, "w", encoding="utf-8") as f:
            f.write("partial")
        raise OSError("disk full mid-copy")

    monkeypatch.setattr(_sh, "copy2", _flaky_copy2)
    p._export_all()

    assert os.listdir(target) == []        # no partial export file
    assert _no_tmp_left(target)


def test_successful_import_leaves_no_temp_files(panel):
    root, p = panel
    src = os.path.join(_tmpdir, "clean_src.txt")
    _write(src, "clean")
    p.import_paths([src])
    assert os.path.isfile(os.path.join(root, "clean_src.txt"))
    assert _no_tmp_left(root)


def test_destination_race_is_not_overwritten(panel, monkeypatch):
    """If a file appears at the destination during a copy, the copy must
    refuse rather than silently clobber it."""
    from fastprompter.ui.file_container import _copy_atomic

    root, p = panel
    src = os.path.join(_tmpdir, "race_src.txt")
    _write(src, "copied content")
    dest = os.path.join(root, "target.txt")

    # something (the user, another tool) lands at the destination mid-copy
    import fastprompter.ui.file_container as fc
    real_rename = os.rename

    def _race_rename(tmp, final):
        _write(dest, "user's own file")
        return real_rename(tmp, final)   # Windows: refuses, dest now exists

    monkeypatch.setattr(fc.os, "rename", _race_rename)
    with pytest.raises(OSError):
        _copy_atomic(src, dest, is_dir=False)

    # the user's file survived, and no temp garbage was left
    assert open(dest, encoding="utf-8").read() == "user's own file"
    assert _no_tmp_left(root)


def test_pre_existing_destination_is_refused(panel):
    from fastprompter.ui.file_container import _copy_atomic

    root, p = panel
    src = os.path.join(_tmpdir, "pre_src.txt")
    _write(src, "content")
    dest = os.path.join(root, "existing.txt")
    _write(dest, "keep me")
    with pytest.raises(OSError):
        _copy_atomic(src, dest, is_dir=False)
    assert open(dest, encoding="utf-8").read() == "keep me"


def test_stale_temp_does_not_poison_the_next_copy(panel):
    """A predictable temp name left by a crashed attempt must not break the
    next copy — the temp is now unique per attempt."""
    from fastprompter.ui.file_container import _copy_atomic

    root, p = panel
    src = os.path.join(_tmpdir, "stale_src.txt")
    _write(src, "content")
    dest = os.path.join(root, "result.txt")
    # a stale partial temp from a crashed run, named like the old scheme
    _write(dest + ".fptmp", "poisoned")
    _copy_atomic(src, dest, is_dir=False)
    assert open(dest, encoding="utf-8").read() == "content"
    # our own unique temp was cleaned up; the stale one is the crashed
    # attempt's leftover and stays (only uuid-suffixed temps must be gone)
    for base, _dirs, files in os.walk(root):
        for f in files:
            assert ".fptmp-" not in f, f"unexpected fresh temp {f}"


class TestNewFileNoClobber:
    """Phase-7: create-new operations must never overwrite a destination that
    appeared after the unique name was selected."""

    def test_publish_new_file_refuses_when_destination_appeared(self, panel):
        from fastprompter.ui.file_container import _publish_new_file

        root, p = panel
        tmp = os.path.join(root, "tmpfile")
        dest = os.path.join(root, "target.txt")
        _write(tmp, "content")
        _write(dest, "user's file")
        with pytest.raises(OSError):
            _publish_new_file(tmp, dest)
        assert open(dest, encoding="utf-8").read() == "user's file"
        assert not os.path.exists(tmp)

    def test_move_refuses_when_destination_already_exists(self, panel):
        from fastprompter.ui.file_container import _move_into_container

        root, p = panel
        src = os.path.join(_tmpdir, "move_src.txt")
        _write(src, "move me")
        dest = os.path.join(root, "moved.txt")
        _write(dest, "appeared")
        with pytest.raises(OSError):
            _move_into_container(src, dest)
        assert os.path.exists(src), "source must survive a refused move"
        assert open(dest, encoding="utf-8").read() == "appeared"
        assert _no_tmp_left(root)

    def test_move_race_during_rename_keeps_both(self, panel, monkeypatch):
        from fastprompter.ui.file_container import _move_into_container

        root, p = panel
        src = os.path.join(_tmpdir, "move_race.txt")
        _write(src, "move me")
        dest = os.path.join(root, "moved.txt")
        real_rename = os.rename

        def _race_rename(s, d):
            _write(d, "appeared mid-rename")
            return real_rename(s, d)   # Windows: fails, dest now exists

        monkeypatch.setattr(os, "rename", _race_rename)
        with pytest.raises(OSError):
            _move_into_container(src, dest)
        assert os.path.exists(src), "source must survive a raced move"
        assert open(dest, encoding="utf-8").read() == "appeared mid-rename"

    def test_move_success_removes_source(self, panel):
        from fastprompter.ui.file_container import _move_into_container

        root, p = panel
        src = os.path.join(_tmpdir, "move_ok.txt")
        _write(src, "move me")
        dest = os.path.join(root, "moved.txt")
        _move_into_container(src, dest)
        assert not os.path.exists(src)
        assert open(dest, encoding="utf-8").read() == "move me"

    def test_write_text_atomic_refuses_when_dest_appeared(self, panel):
        from fastprompter.ui.file_container import _write_text_atomic

        root, p = panel
        dest = os.path.join(root, "link.url")
        _write(dest, "appeared")
        with pytest.raises(OSError):
            _write_text_atomic(dest, "new content")
        assert open(dest, encoding="utf-8").read() == "appeared"
        assert _no_tmp_left(root)


class TestAsyncContainerOps:
    """Phase-8: large File Container operations run on the shared worker so
    an artificially slow copy cannot block the GUI event loop."""

    def test_large_import_does_not_block_the_gui(self, panel, monkeypatch):
        import time as _t

        from fastprompter.ui import file_container as fc

        root, p = panel
        monkeypatch.setattr(fc, "_async_eligible", lambda items: True)
        src = os.path.join(_tmpdir, "big_src.txt")
        _write(src, "x" * 1000)

        calls = {"n": 0}
        real_copy = fc._copy_atomic

        def slow_copy(s, d, is_dir):
            calls["n"] += 1
            _t.sleep(0.5)
            return real_copy(s, d, is_dir)

        monkeypatch.setattr(fc, "_copy_atomic", slow_copy)
        t0 = _t.monotonic()
        p.import_paths([src])                # must dispatch, not block
        elapsed = _t.monotonic() - t0
        assert elapsed < 0.3, f"large import blocked the GUI: {elapsed:.2f}s"

        deadline = _t.monotonic() + 5
        while _t.monotonic() < deadline:
            _app.processEvents()
            if os.path.exists(os.path.join(root, "big_src.txt")):
                break
            _t.sleep(0.01)
        assert os.path.exists(os.path.join(root, "big_src.txt"))
        assert calls["n"] == 1
