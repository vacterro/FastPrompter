"""Regression: File Container operations cannot escape the container root.

Drives the REAL panel methods (rename / clipboard->file / new folder /
template build) with malicious names and proves no file or directory appears
outside the resolved container folder (or, for the drive-qualified case, that
os.path.join cannot be tricked into discarding the root).
"""

import os
import shutil
import sys
import threading
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import tempfile

import pytest
from PyQt6.QtCore import QThread
from PyQt6.QtWidgets import QApplication

import fastprompter.core.state as state_mod
from fastprompter.main import FastPrompter
from fastprompter.ui.file_container import FileContainerPanel

_app = QApplication.instance() or QApplication([])
_tmpdir = tempfile.mkdtemp(prefix="fastprompter_containment_")


@pytest.fixture(scope="module")
def win():
    state_mod.get_db_path = lambda profile_id=1: os.path.join(_tmpdir, f"c_{profile_id}.db")
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


def _reparse_ok():
    try:
        base = tempfile.mkdtemp()
        target = tempfile.mkdtemp()
        link = os.path.join(base, "link")
        os.symlink(target, link, target_is_directory=True)
        os.rmdir(link)
        os.rmdir(base)
        os.rmdir(target)
        return True
    except (OSError, NotImplementedError):
        return False


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
    p._rename(os.path.join(root, "unicode.txt"), new_name="заметка с пробелами")
    assert os.path.isdir(os.path.join(root, "заметка с пробелами")) or \
        os.path.isfile(os.path.join(root, "заметка с пробелами"))
    p.new_folder(name="папка 1")
    assert os.path.isdir(os.path.join(root, "папка 1"))


# ===================== P1-2: mutation-time root revalidation ================


def test_rename_revalidates_against_current_root(panel, tmp_path):
    """A stale path listed before the panel was re-bound to a DIFFERENT
    container must never be renamed across container roots."""
    root, p = panel
    _write(os.path.join(root, "note.txt"))
    p.refresh()
    other = os.path.join(str(tmp_path), "other_root")
    os.makedirs(other, exist_ok=True)
    p.open_for(other)                 # panel re-bound to another container
    p._rename(os.path.join(root, "note.txt"), new_name="moved")
    assert os.path.isfile(os.path.join(root, "note.txt")), \
        "a stale path must not be renamed across container roots"
    assert os.listdir(other) == []


def test_delete_revalidates_against_current_root(panel, tmp_path, monkeypatch):
    """A stale path must never be deleted outside the CURRENT captured root."""
    from PyQt6.QtWidgets import QMessageBox

    root, p = panel
    _write(os.path.join(root, "note.txt"))
    p.refresh()
    other = os.path.join(str(tmp_path), "other_root")
    os.makedirs(other, exist_ok=True)
    p.open_for(other)
    monkeypatch.setattr(QMessageBox, "exec",
                        lambda self: QMessageBox.StandardButton.Yes)
    p._delete([os.path.join(root, "note.txt")])
    assert os.path.isfile(os.path.join(root, "note.txt")), \
        "a stale path must not be deleted outside the current root"
    assert os.listdir(other) == []


# ==================== P1-3: SOURCE_REMAINS partial outcome ==================


def test_move_returns_source_remains_when_source_removal_fails(
        panel, monkeypatch):
    from fastprompter.ui import file_container as fc

    root, p = panel
    src = os.path.join(_tmpdir, "move_src.txt")
    _write(src, "payload")
    dest = os.path.join(root, "moved.txt")
    real_rename = os.rename

    def flaky_rename(a, b):
        if a == src and b == dest:
            raise OSError("cross-volume")
        return real_rename(a, b)

    monkeypatch.setattr(os, "rename", flaky_rename)
    real_remove = os.remove

    def flaky_remove(path):
        if path == src:
            raise OSError("source locked")
        return real_remove(path)

    monkeypatch.setattr(os, "remove", flaky_remove)

    status = fc._move_into_container(src, dest, root, p._folder_root_identity)
    assert status == "SOURCE_REMAINS"
    assert os.path.isfile(dest), "the destination is published"
    assert open(dest, encoding="utf-8").read() == "payload"
    assert os.path.isfile(src), "the source stayed behind"


def test_move_returns_moved_when_source_is_gone(panel, monkeypatch):
    from fastprompter.ui import file_container as fc

    root, p = panel
    src = os.path.join(_tmpdir, "move_src2.txt")
    _write(src, "payload2")
    dest = os.path.join(root, "moved2.txt")
    real_rename = os.rename

    def flaky_rename(a, b):
        if a == src and b == dest:
            raise OSError("cross-volume")
        return real_rename(a, b)

    monkeypatch.setattr(os, "rename", flaky_rename)
    status = fc._move_into_container(src, dest, root, p._folder_root_identity)
    assert status == "MOVED"
    assert os.path.isfile(dest)
    assert not os.path.exists(src)


def test_sync_move_partial_is_classified_not_failed(
        panel, monkeypatch, caplog):
    """A published-but-source-stuck move counts as DONE (with a warning),
    never as a plain failure."""
    from fastprompter.ui import file_container as fc

    root, p = panel
    src = os.path.join(_tmpdir, "classify_src.txt")
    _write(src, "payload")
    dest = os.path.join(root, "classify_src.txt")   # _unique_dest keeps the name
    monkeypatch.setattr(fc, "_async_eligible", lambda items: False)
    real_rename = os.rename

    def flaky_rename(a, b):
        if a == src and b == dest:
            raise OSError("cross-volume")
        return real_rename(a, b)

    monkeypatch.setattr(os, "rename", flaky_rename)
    real_remove = os.remove

    def flaky_remove(path):
        if path == src:
            raise OSError("source locked")
        return real_remove(path)

    monkeypatch.setattr(os, "remove", flaky_remove)
    ref = []
    monkeypatch.setattr(p, "refresh", lambda: ref.append(1))

    p.import_paths([src], do_move=True)

    assert os.path.isfile(dest), "the destination is published"
    assert os.path.isfile(src), "the source stayed behind"
    assert ref, "the panel refreshed: the command was classified as done"
    assert "could not be removed" in caplog.text


# ============================ P1-7: tracked export worker ====================


def test_export_all_writes_a_zip_and_cleans_its_temp(panel, monkeypatch, tmp_path):
    import zipfile as _zf

    from PyQt6.QtWidgets import QFileDialog

    from fastprompter.ui import file_container as fc

    root, p = panel
    for i in range(5):
        _write(os.path.join(root, f"f{i}.txt"), f"data{i}")
    target = os.path.join(str(tmp_path), "out.zip")
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a, **k: (target, "")))

    p._export_all()
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        _app.processEvents()
        live = [t for t in fc._EXPORT_THREADS if t.is_alive()]
        if not live:
            break
        time.sleep(0.01)

    assert os.path.isfile(target), "the zip was published"
    assert os.path.isfile(target)
    with _zf.ZipFile(target) as z:
        assert set(z.namelist()) == {f"f{i}.txt" for i in range(5)}
    assert not list(tmp_path.glob("out.zip.fpbak-*")), "temp cleaned"


def test_export_cancel_leaves_no_partial(panel, monkeypatch, tmp_path):
    from PyQt6.QtWidgets import QFileDialog

    from fastprompter.ui import file_container as fc

    root, p = panel
    for i in range(50):
        _write(os.path.join(root, f"f{i}.txt"), f"data{i}")
    target = os.path.join(str(tmp_path), "cancel.zip")
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a, **k: (target, "")))

    p._export_all()
    p._export_cancel.set()                 # cancel immediately
    threads = list(fc._EXPORT_THREADS)
    for t in threads:
        t.join(5)
    _app.processEvents()

    assert not os.path.exists(target), "a cancelled export leaves no zip"
    assert not list(tmp_path.glob("cancel.zip.fpbak-*")), "no temp left behind"


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
    # _export_all asks for a SAVE-FILE path (returns (name, filter)); the
    # old export implementation asked for a directory, and the stale patch
    # silently opened a real modal dialog that hung the suite.
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a, **k: (target, "")))

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

        def slow_copy(s, d, is_dir, root=None, root_identity=None):
            calls["n"] += 1
            _t.sleep(0.5)
            return real_copy(s, d, is_dir, root, root_identity)

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

    def test_explicit_commands_finish_fifo_and_report_every_result(
        self, panel, monkeypatch, caplog
    ):
        import threading
        import time as _t

        from fastprompter.ui import file_container as fc

        root, p = panel
        src_a = os.path.join(_tmpdir, "command_a.txt")
        src_b = os.path.join(_tmpdir, "command_b.txt")
        dest_a = os.path.join(root, "command_a.txt")
        dest_b = os.path.join(root, "command_b.txt")
        _write(src_a, "A")
        _write(src_b, "B")

        started = threading.Event()
        release = threading.Event()
        events = []
        real_copy = fc._copy_atomic

        def command_copy(
            src, dest, is_dir, intended_root=None, root_identity=None
        ):
            events.append(("start", os.path.basename(src)))
            if src == src_a:
                started.set()
                assert release.wait(5.0), "test did not release command A"
                events.append(("fail", os.path.basename(src)))
                raise RuntimeError("command A exploded")
            result = real_copy(
                src, dest, is_dir, intended_root, root_identity
            )
            events.append(("done", os.path.basename(src)))
            return result

        monkeypatch.setattr(fc, "_copy_atomic", command_copy)
        request_a = p._dispatch_container_ops(
            [("copy", src_a, dest_a, False)]
        )
        assert started.wait(2.0), "command A never reached worker"
        request_b = p._dispatch_container_ops(
            [("copy", src_b, dest_b, False)]
        )
        release.set()

        deadline = _t.monotonic() + 5.0
        while _t.monotonic() < deadline:
            _app.processEvents()
            if os.path.isfile(dest_b):
                break
            _t.sleep(0.01)

        assert request_a != request_b
        assert request_a and request_b
        assert not os.path.exists(dest_a)
        assert open(dest_b, encoding="utf-8").read() == "B"
        assert events == [
            ("start", "command_a.txt"),
            ("fail", "command_a.txt"),
            ("start", "command_b.txt"),
            ("done", "command_b.txt"),
        ]
        assert request_a in caplog.text
        assert "command A exploded" in caplog.text

    def test_completion_is_delivered_only_to_originating_panel(
        self, panel, monkeypatch
    ):
        import time as _t

        from fastprompter.ui import file_container as fc

        root, origin = panel
        other_root = os.path.join(_tmpdir, "other_panel")
        os.makedirs(other_root, exist_ok=True)
        other = FileContainerPanel(origin.main_win)
        other.open_for(other_root)
        monkeypatch.setattr(fc, "_async_eligible", lambda items: True)
        worker = fc.container_worker()
        worker.done.connect(other._on_container_done)
        other._container_done_worker = worker

        origin_refreshes = []
        other_refreshes = []
        monkeypatch.setattr(origin, "refresh", lambda: origin_refreshes.append(1))
        monkeypatch.setattr(other, "refresh", lambda: other_refreshes.append(1))

        src = os.path.join(_tmpdir, "owned_command.txt")
        _write(src, "owned")
        origin.import_paths([src])

        deadline = _t.monotonic() + 5.0
        while _t.monotonic() < deadline:
            _app.processEvents()
            if origin_refreshes:
                break
            _t.sleep(0.01)

        assert os.path.isfile(os.path.join(root, "owned_command.txt"))
        assert origin_refreshes
        assert other_refreshes == []
        other.close()

    def test_real_worker_completion_returns_to_gui_thread(
        self, panel, monkeypatch
    ):
        import time as _t

        from fastprompter.ui import file_container as fc

        root, p = panel
        src = os.path.join(_tmpdir, "affinity_source.txt")
        _write(src, "affinity")
        worker_threads = []
        completion_threads = []
        real_copy = fc._copy_atomic
        real_done = p._on_container_done

        def record_copy(*args, **kwargs):
            worker_threads.append(QThread.currentThread())
            return real_copy(*args, **kwargs)

        def record_done(*args):
            completion_threads.append(QThread.currentThread())
            return real_done(*args)

        monkeypatch.setattr(fc, "_async_eligible", lambda items: True)
        monkeypatch.setattr(fc, "_copy_atomic", record_copy)
        monkeypatch.setattr(p, "_on_container_done", record_done)
        p._container_done_worker = None
        p.import_paths([src])
        deadline = _t.monotonic() + 5.0
        while _t.monotonic() < deadline:
            _app.processEvents()
            if completion_threads:
                break
            _t.sleep(0.01)

        assert os.path.isfile(os.path.join(root, "affinity_source.txt"))
        assert worker_threads == [fc._CONTAINER_THREAD]
        assert completion_threads == [_app.thread()]

    @pytest.mark.skipif(not _reparse_ok(), reason="cannot create junctions/symlinks")
    @pytest.mark.parametrize("operation", ["copy", "move"])
    def test_root_swap_fails_closed_and_move_keeps_source(
        self, panel, monkeypatch, tmp_path, caplog, operation
    ):
        import time as _t

        from fastprompter.ui import file_container as fc

        root, p = panel
        outside = str(tmp_path / "outside-swap")
        os.makedirs(outside)
        src = str(tmp_path / f"source-{operation}.txt")
        _write(src, operation)

        entered = threading.Event()
        release = threading.Event()
        real_copy = fc._copy_atomic
        real_move = fc._move_into_container

        def blocked_copy(*args, **kwargs):
            entered.set()
            assert release.wait(5.0), "test did not release copy"
            return real_copy(*args, **kwargs)

        def blocked_move(*args, **kwargs):
            entered.set()
            assert release.wait(5.0), "test did not release move"
            return real_move(*args, **kwargs)

        monkeypatch.setattr(fc, "_async_eligible", lambda items: True)
        monkeypatch.setattr(fc, "_copy_atomic", blocked_copy)
        monkeypatch.setattr(fc, "_move_into_container", blocked_move)
        p.import_paths([src], do_move=operation == "move")
        assert entered.wait(2.0), f"{operation} never reached worker"

        shutil.rmtree(root)
        os.symlink(outside, root, target_is_directory=True)
        release.set()

        deadline = _t.monotonic() + 5.0
        while _t.monotonic() < deadline:
            _app.processEvents()
            if "captured container root" in caplog.text:
                break
            _t.sleep(0.01)

        assert os.listdir(outside) == []
        assert os.path.isfile(src), "MOVE source must survive failed publication"
        assert "captured container root" in caplog.text

    @pytest.mark.skipif(not _reparse_ok(), reason="cannot create junctions/symlinks")
    def test_export_policy_allows_external_destination(self, panel, tmp_path):
        from fastprompter.ui.file_container import _copy_atomic

        _root, _panel = panel
        target = str(tmp_path / "user-selected-export")
        os.makedirs(target)
        src = str(tmp_path / "export-source.txt")
        dest = os.path.join(target, "exported.txt")
        _write(src, "external export")

        _copy_atomic(src, dest, False, root=None, root_identity=None)
        assert open(dest, encoding="utf-8").read() == "external export"

    @pytest.mark.skipif(not _reparse_ok(), reason="cannot create junctions/symlinks")
    def test_async_export_rejects_swapped_user_destination(
        self, panel, monkeypatch, tmp_path, caplog
    ):
        import time as _t

        from fastprompter.ui import file_container as fc

        _root, p = panel
        target = str(tmp_path / "selected-export-target")
        outside = str(tmp_path / "outside-export-target")
        os.makedirs(target)
        os.makedirs(outside)
        src = str(tmp_path / "export-swap-source.txt")
        dest = os.path.join(target, "exported.txt")
        _write(src, "export payload")

        entered = threading.Event()
        release = threading.Event()
        real_copy = fc._copy_atomic

        def blocked_copy(*args, **kwargs):
            entered.set()
            assert release.wait(5.0), "test did not release export"
            return real_copy(*args, **kwargs)

        monkeypatch.setattr(fc, "_copy_atomic", blocked_copy)
        p._dispatch_container_ops(
            [("copy", src, dest, False)], is_export=True
        )
        assert entered.wait(2.0), "export never reached worker"

        os.rmdir(target)
        os.symlink(outside, target, target_is_directory=True)
        release.set()

        deadline = _t.monotonic() + 5.0
        while _t.monotonic() < deadline:
            _app.processEvents()
            if "captured container root" in caplog.text:
                break
            _t.sleep(0.01)

        assert os.listdir(outside) == []
        assert os.path.isfile(src)
        assert "captured container root" in caplog.text


def test_stale_owner_command_error_stays_observable(win, monkeypatch):
    """P1-18: an explicit File Container command that fails AFTER the panel's
    owner changed must still report its error.

    The old ordering returned on the owner check BEFORE errors were logged,
    so a command started on the old profile/panel could fail and leave zero
    trace. The failure of an explicit user command is a fact that must
    survive the switch; only the UI side effects (sound, refresh) belong to
    the CURRENT owner, and a new owner must never refresh with old paths.
    """
    from fastprompter.ui import file_container as fc_mod

    panel = FileContainerPanel(win)
    try:
        panel.folder = os.path.join(os.path.dirname(__file__), "stale-folder")
        old_owner = panel._container_owner_id
        panel._container_owner_id = "NEW-OWNER"   # panel/profile switched mid-command

        logged = []
        monkeypatch.setattr(fc_mod.logger, "error",
                            lambda *a, **k: logged.append((a, k)))
        refreshed = []
        monkeypatch.setattr(panel, "refresh", lambda: refreshed.append(1))
        sounds = []
        monkeypatch.setattr(panel.main_win.sound_manager, "play_tick",
                            lambda: sounds.append(1))

        request = {
            "request_id": "req-1",
            "owner_id": old_owner,
            "refresh_identity": os.path.normcase(os.path.abspath(panel.folder)),
            "kind": "import",
        }
        panel._on_container_done(
            "req-1", request, done=[], partial=[], errors=[(r"C:\src\a.txt", "boom")])

        assert logged, "the failed command's error must remain observable"
        assert any("req-1" in str(a) for a in logged), logged
        assert refreshed == [], "a new owner must not refresh with old paths"
        assert sounds == [], "a new owner must not play the old command's tick"
    finally:
        panel.close()
