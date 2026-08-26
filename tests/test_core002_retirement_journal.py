"""CORE-002: the retirement journal is a mandatory precondition.

A journal write failure must refuse the physical folder move entirely, and
a successful move must NOT clear the journal until it is durably reconciled.
"""

import os
import types

import fastprompter.ui.file_container as fc
from fastprompter.ui import snippet_ops_mixin as som
from fastprompter.ui.snippet_ops_mixin import (
    SnippetOpsMixin,
    _journal_path,
)


def _stub(root, data):
    obj = types.SimpleNamespace()
    obj._files_root = lambda: str(root)
    obj.data = data
    obj._prune_folder_trash_log = lambda log: None
    obj._delete_file_container = (
        SnippetOpsMixin._delete_file_container.__get__(obj))
    return obj


def test_journal_write_failure_aborts_move(tmp_path, monkeypatch):
    monkeypatch.setattr(som, "_write_retirement_journal", lambda r, e: False)
    src = tmp_path / "silo_src"
    src.mkdir()
    (src / "a.txt").write_text("x", encoding="utf-8")
    obj = _stub(tmp_path, {})
    result = obj._delete_file_container("Cat", str(src))
    assert result == "FAILED"
    # physical folder was NOT moved — it still exists in place, and nothing
    # was moved into _trash
    assert src.is_dir()
    assert (src / "a.txt").exists()
    trash = tmp_path / "_trash"
    if trash.exists():
        assert not any(p.is_dir() for p in trash.iterdir())


def test_successful_move_keeps_journal(tmp_path, monkeypatch):
    captured = {}
    orig = som._write_retirement_journal

    def _cap(r, e):
        captured.update(root=r, entry=e)
        return orig(r, e)
    monkeypatch.setattr(som, "_write_retirement_journal", _cap)
    src = tmp_path / "silo_src"
    src.mkdir()
    (src / "a.txt").write_text("x", encoding="utf-8")
    obj = _stub(tmp_path, {})
    result = obj._delete_file_container("Cat", str(src))
    assert result == "MOVED_TO_TRASH"
    # folder moved to _trash
    assert not src.exists()
    assert (tmp_path / "_trash").is_dir()
    # journal still present (not cleared in the move path) and holds the
    # exact original->trashed mapping
    jp = _journal_path(str(tmp_path))
    assert os.path.isfile(jp)
    assert os.path.abspath(str(src)) == captured["entry"]["original"]
    # the in-memory log carries the recovery record
    assert obj.data["folder_trash_log"]
