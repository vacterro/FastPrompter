"""T-1476: the OTHER rollback branch must not swallow a failed apply either.

``_restore_selected`` compensates a failed durable save in two branches.
T-1473 fixed the branch where the physical move-back succeeded; this one runs
when the move-back itself failed, so the folder stays at its live destination
and the runtime is rolled back logically through
``mw._apply_data_state`` instead — behind a bare ``except Exception: pass``
(``trash_dialog.py:255-259``).

A failure there is not a false success claim: the dialog already says the
folder was left recoverable. It is a missing diagnostic. The branch goes on to
re-record the folder association so the folder stays recoverable, which is
correct for the disk, so nothing surfaces the fact that the logical half of
the rollback never landed.

Same stub-main-window harness as ``test_t1473_trash_rollback_truth.py``, with
the folder restored and a real directory at its destination so the physical
rename is genuinely attempted and refused.
"""

from __future__ import annotations

import logging
import os
import types

import pytest

from fastprompter.ui.trash_dialog import TrashDialog

_LOGGER_NAME = "fastprompter.core.logging"


class _Item:
    def __init__(self, path):
        self._path = path

    def data(self, role):
        return self._path


class _ListWidget:
    def __init__(self, item):
        self._item = item

    def selectedItems(self):
        return [self._item]


class _MainWin:
    """A main window whose durable save fails and whose apply can raise."""

    def __init__(self, data, fail_apply, folder, dest):
        self.data = data
        self.fail_apply = fail_apply
        self._folder = folder
        self._dest = dest
        self.applied = 0
        self.dirty = 0
        self.data_undo_stack = []
        self.data_redo_stack = []

    def get_current_category(self):
        return "cat"

    def _category_files_dir(self, cat):
        return "comp"

    def _files_root(self):
        return self._dest

    def _restore_trash_file_container(self, md_basename, text, inserted):
        return self._folder

    def save_data_to_db(self, force=False):
        return False

    def insert_silo_at(self, text):
        return 0

    def _snapshot_current(self):
        return {"temp_presets": []}

    def mark_dirty(self):
        self.dirty += 1

    def _apply_data_state(self, snapshot):
        self.applied += 1
        if self.fail_apply:
            raise RuntimeError("slot index out of range")


class _Boxes:
    def __init__(self):
        self.texts = []

    def warning(self, parent, title, text):
        self.texts.append(text)


def _dialog(tmp_path, fail_apply):
    """A TrashDialog-shaped object bound to the REAL restore method.

    The folder is restored, its destination directory really exists, and the
    rename back to the pre-trash path is refused, which is what sends the
    method down the physical-move-back-failure branch.
    """
    trash = tmp_path / "trash"
    trash.mkdir()
    source = trash / "silo.md"
    source.write_text("some silo text", encoding="utf-8")

    root = tmp_path / "files"
    # original lives directly under the category component, so the branch's
    # destination path (root/component/folder) is exactly this directory and
    # the rename back to the pre-trash path is really attempted
    original = root / "comp" / "FOLDERNAME"
    trashed = root / "TRASH" / "FOLDERNAME"
    original.mkdir(parents=True)
    # the resolver only selects a record whose trashed directory still exists
    trashed.mkdir(parents=True)
    dest = root

    md_basename = source.name
    data = {
        "temp_presets": [],
        # an exact-path association, so resolve_trash_link selects this entry
        "trash_text_folder": {md_basename: str(original)},
        "folder_trash_log": [(str(original), str(trashed))],
        "trash_consumed": {},
    }
    mw = _MainWin(data, fail_apply, original.name, dest)

    obj = types.SimpleNamespace()
    obj.main_win = mw
    obj.list_widget = _ListWidget(_Item(str(source)))
    obj.tr = lambda t: t
    obj._consumed_map = lambda: {}
    obj._load_trash = lambda: None
    obj._restore_selected = TrashDialog._restore_selected.__get__(obj)
    return obj, mw, data, original, dest


@pytest.fixture
def box(monkeypatch):
    boxes = _Boxes()
    monkeypatch.setattr("fastprompter.ui.trash_dialog.QMessageBox", boxes)
    return boxes


def test_a_failed_apply_in_the_physical_failure_branch_is_logged(
        tmp_path, monkeypatch, box, caplog):
    obj, mw, data, original, dest = _dialog(tmp_path, fail_apply=True)

    def refusing_rename(*a, **k):
        raise OSError("file in use")

    monkeypatch.setattr(os, "rename", refusing_rename)
    with caplog.at_level(logging.WARNING, logger=_LOGGER_NAME):
        obj._restore_selected()

    assert mw.applied == 1, "the logical rollback was never attempted"
    assert any("Restore rollback: could not reapply" in r.message
               for r in caplog.records), "the failed apply was not logged"
    # the branch's own message is unchanged: it never claimed a full rollback
    assert box.texts and "could not be restored persistently" in box.texts[-1]
    # and the recoverability bookkeeping still ran, so the folder is not
    # orphaned just because the logical half failed
    assert data["folder_trash_log"], "the folder association was not re-recorded"
    assert data["folder_trash_log"][-1][1] == os.path.join(
        str(dest), "comp", original.name), (
        "the re-recorded association does not point at the live location")


def test_a_healthy_apply_in_the_physical_failure_branch_stays_silent(
        tmp_path, monkeypatch, box, caplog):
    """Negative control: the same branch, with the apply succeeding."""
    obj, mw, data, original, dest = _dialog(tmp_path, fail_apply=False)

    def refusing_rename(*a, **k):
        raise OSError("file in use")

    monkeypatch.setattr(os, "rename", refusing_rename)
    with caplog.at_level(logging.WARNING, logger=_LOGGER_NAME):
        obj._restore_selected()

    assert mw.applied == 1
    assert [r for r in caplog.records
            if "Restore rollback: could not reapply" in r.message] == [], (
        "a successful logical rollback must not warn about one")
    assert data["folder_trash_log"], "the association bookkeeping must run"
