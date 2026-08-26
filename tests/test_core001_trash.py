"""CORE-001: the durable trash-text copy must be fail-closed.

The root primitive ``_trash_silo_content`` is exercised without Qt: a real
OSError on the atomic write must make it return ``False`` (never ``None``),
so callers can refuse the destructive delete/clear. A blank text is a
successful no-op (``True``); a successful write returns the written path.
"""

import os
import types

import fastprompter.ui.file_container as fc
from fastprompter.ui.snippet_ops_mixin import SnippetOpsMixin


def _stub(root, data):
    obj = types.SimpleNamespace()
    obj._files_root = lambda: str(root)
    obj.data = data
    obj._trash_silo_content = SnippetOpsMixin._trash_silo_content.__get__(obj)
    return obj


def test_trash_write_failure_is_fail_closed(tmp_path, monkeypatch):
    def _boom(*a, **k):
        raise OSError("disk full")
    monkeypatch.setattr(fc, "_write_text_atomic", _boom)
    obj = _stub(tmp_path, {})
    assert obj._trash_silo_content("some real text") is False
    # no .md recovery copy was written (the empty _trash dir may exist)
    trash = tmp_path / "_trash"
    assert not any(p.suffix == ".md" for p in trash.glob("*.md"))


def test_trash_blank_text_is_noop(tmp_path):
    obj = _stub(tmp_path, {})
    assert obj._trash_silo_content("   \n  ") is True
    assert not (tmp_path / "_trash").exists()


def test_trash_success_returns_written_path(tmp_path):
    obj = _stub(tmp_path, {})
    result = obj._trash_silo_content("hello world")
    assert isinstance(result, str) and result.endswith(".md")
    written = os.path.join(tmp_path, "_trash", os.path.basename(result))
    assert written and open(written, encoding="utf-8").read() == "hello world"


def test_trash_records_folder_link_on_success(tmp_path):
    data = {}
    obj = _stub(tmp_path, data)
    # CORE-003: the link stores the EXACT original folder path (abspath),
    # not merely its basename.
    result = obj._trash_silo_content("hello world", folder_name="Cat_silo123")
    assert isinstance(result, str)
    link = data.get("trash_text_folder", {})
    assert link.get(os.path.basename(result)) == os.path.abspath("Cat_silo123")
