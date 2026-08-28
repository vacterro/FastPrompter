"""W2-002 (acb-mtbqjyvd): nested alias import — _copy_tree_safe rejects
aliases that point back into the container root, form cycles, or escape the
source ancestry.
"""

import os
import sys

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC = os.path.join(ROOT, "src")
sys.path.insert(0, SRC)


def test_copy_tree_safe_rejects_alias_into_container(tmp_path):
    from fastprompter.ui.file_container import _copy_tree_safe
    src = tmp_path / "external"
    src.mkdir(parents=True, exist_ok=True)
    container = tmp_path / "container"
    container.mkdir()
    # a nested symlink inside external pointing back into the container
    alias = src / "escape"
    os.symlink(str(container), str(alias))
    dst = tmp_path / "dst"
    _copy_tree_safe(str(src), str(dst), reject_aliases_into=str(container))
    # the alias directory was skipped
    assert not (dst / "escape").exists()
    # normal files survive
    (src / "keep.txt").write_text("ok")
    _copy_tree_safe(str(src), str(dst), reject_aliases_into=str(container))
    assert (dst / "keep.txt").read_text() == "ok"


def test_copy_tree_safe_rejects_cycle(tmp_path):
    from fastprompter.ui.file_container import _copy_tree_safe
    a = tmp_path / "a"
    a.mkdir()
    b = a / "b"
    b.mkdir()
    # a -> ... -> b -> a (cycle)
    os.symlink(str(a), str(b / "cycle"))
    dst = tmp_path / "dst"
    _copy_tree_safe(str(a), str(dst))
    # the cycle directory was skipped (no infinite recursion)
    assert (dst / "b").exists()
    assert not (dst / "b" / "cycle").exists()


def test_copy_tree_safe_rejects_alias_into_source_ancestor(tmp_path):
    from fastprompter.ui.file_container import _copy_tree_safe
    src = tmp_path / "src"
    src.mkdir()
    sub = src / "sub"
    sub.mkdir()
    # alias pointing back to the source root
    os.symlink(str(src), str(sub / "back"))
    dst = tmp_path / "dst"
    fp = os.path.normcase(os.path.realpath(str(src)))
    _copy_tree_safe(str(src), str(dst), reject_aliases_into=fp)
    assert not (dst / "sub" / "back").exists()
    assert (dst / "sub").exists()