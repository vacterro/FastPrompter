"""T-1473: a failed rollback must not be reported to the user as a full one.

``_restore_selected`` rolls a failed durable save back through
``mw._apply_data_state(pre_snapshot)`` behind a bare
``except Exception: pass``, and then unconditionally tells the user
"Everything was rolled back and the trash copy was kept so you can try
again."  When that apply raised, the runtime kept a partially-restored state
(silhouette, undo/redo, recovery metadata) while the dialog claimed a clean
reversal, so the operator had every reason to believe the opposite of the
truth and no log line said anything was wrong.

These tests drive the real method over a stub main window, following the
``test_core001_trash.py`` convention: no QApplication.
"""

from __future__ import annotations

import types

import pytest

os_env = None
from fastprompter.ui.trash_dialog import TrashDialog  # noqa: E402


class _Item:
    """One trash list entry."""

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
    """A main window whose durable save fails and whose apply raises."""

    def __init__(self, data, fail_apply):
        self.data = data
        self.fail_apply = fail_apply
        self.applied = 0
        self.dirty = 0
        self.data_undo_stack = []
        self.data_redo_stack = []

    def get_current_category(self):
        return ""

    def _category_files_dir(self, cat):
        return None

    def _files_root(self):
        return ""

    def _restore_trash_file_container(self, *a, **k):
        # No physical folder to move back: physical_rolled_back stays True,
        # which is the branch whose logical restore the ticket is about.
        return None

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
        self.titles = []
        self.texts = []

    def warning(self, parent, title, text):
        self.titles.append(title)
        self.texts.append(text)


def _dialog(tmp_path, text, fail_apply):
    """A TrashDialog-shaped object bound to the REAL restore method."""
    trash = tmp_path / "trash"
    trash.mkdir()
    source = trash / "silo.md"
    source.write_text(text, encoding="utf-8")

    mw = _MainWin({"temp_presets": [], "trash_text_folder": {},
                   "folder_trash_log": [], "trash_consumed": {}}, fail_apply)
    boxes = _Boxes()

    obj = types.SimpleNamespace()
    obj.main_win = mw
    obj.list_widget = _ListWidget(_Item(str(source)))
    obj.tr = lambda t: t
    obj._consumed_map = lambda: {}
    obj._load_trash = lambda: None
    obj._restore_selected = TrashDialog._restore_selected.__get__(obj)
    return obj, mw, boxes


@pytest.fixture
def box(monkeypatch):
    boxes = _Boxes()
    monkeypatch.setattr("fastprompter.ui.trash_dialog.QMessageBox", boxes)
    return boxes


def test_a_failed_state_apply_is_not_reported_as_full_rollback(
        tmp_path, monkeypatch, box, caplog):
    import logging

    obj, mw, _ = _dialog(tmp_path, "some silo text", fail_apply=True)
    with caplog.at_level(logging.WARNING,
                         logger="fastprompter.core.logging"):
        obj._restore_selected()

    assert mw.applied == 1, "the rollback was never attempted"
    assert box.texts, "the user was told nothing"
    message = box.texts[-1]
    assert "Everything was rolled back" not in message, (
        "a failed logical rollback was reported as a complete one")
    assert "could not be fully restored" in message
    # and the failure is no longer silent in the log
    assert any("Restore rollback: could not reapply" in r.message
               for r in caplog.records), "the rollback failure was not logged"


def test_a_healthy_state_apply_keeps_the_existing_message(
        tmp_path, monkeypatch, box, caplog):
    """Negative control: a clean rollback still says exactly what it said."""
    import logging

    obj, mw, _ = _dialog(tmp_path, "some silo text", fail_apply=False)
    with caplog.at_level(logging.WARNING,
                         logger="fastprompter.core.logging"):
        obj._restore_selected()

    assert mw.applied == 1
    assert box.texts
    assert box.texts[-1] == ("Everything was rolled back and the trash copy "
                             "was kept so you can try again.")
    assert [r for r in caplog.records
            if "Restore rollback: could not reapply" in r.message] == [], (
        "a successful rollback must not warn about one")
