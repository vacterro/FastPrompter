"""T-1437 (SRC-097) — W2-001: recovery journals are untrusted metadata.

Crash-recovery journals (transfer, retirement, merge) store physical paths as
plain JSON. A stale, corrupted or hand-edited record must never make startup
rename a directory outside the current files root. ``recovery_path_owned`` is
the reparse-aware authority every journal now goes through.
"""

from __future__ import annotations

from fastprompter.ui import snippet_ops_mixin as som
from fastprompter.ui.snippet_ops_mixin import (
    _journal_load_records,
    _journal_store_records,
    _reconcile_retirement_journal,
)


def _owned():
    # imported in-test so the red control fails at the assertion, not collection
    from fastprompter.utils.path_safety import recovery_path_owned
    return recovery_path_owned


# --- the authority itself --------------------------------------------------

def test_w2_001_owned_inside_root(tmp_path):
    recovery_path_owned = _owned()
    root = tmp_path / "files"
    (root / "_trash" / "silo-1").mkdir(parents=True)
    inside = root / "_trash" / "silo-1"

    assert recovery_path_owned(str(root), str(inside)) is True
    assert recovery_path_owned(str(root), str(inside), subtree="_trash") is True


def test_w2_001_refuses_outside_root(tmp_path):
    recovery_path_owned = _owned()
    root = tmp_path / "files"
    root.mkdir()
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    # A LEXICAL prefix sibling: "files2".startswith("files") is True, an
    # abspath startswith check would have accepted it.
    sibling = tmp_path / "files2"
    sibling.mkdir()

    assert recovery_path_owned(str(root), str(outside)) is False
    assert recovery_path_owned(str(root), str(sibling)) is False
    assert recovery_path_owned(str(root), "") is False


def test_w2_001_subtree_demand(tmp_path):
    recovery_path_owned = _owned()
    root = tmp_path / "files"
    (root / "_trash").mkdir(parents=True)
    live = root / "live-silo"
    live.mkdir()

    # owned by root, but not beneath _trash
    assert recovery_path_owned(str(root), str(live)) is True
    assert recovery_path_owned(str(root), str(live), subtree="_trash") is False


# --- the call site: retirement reconciliation ------------------------------

def _journal(root, records):
    assert _journal_store_records(str(root), records) is True


def test_w2_001_retirement_refuses_outside_root(tmp_path):
    (tmp_path / "_trash").mkdir(parents=True)
    outside = tmp_path.parent / "foreign-dir"
    outside.mkdir(exist_ok=True)
    _journal(tmp_path, [{"original": str(tmp_path / "keep-silo"),
                         "trashed": str(outside)}])
    data = {}

    _reconcile_retirement_journal(str(tmp_path), data, lambda o: False)

    # nothing adopted, nothing moved, record retained for the operator
    assert data["folder_trash_log"] == []
    records = _journal_load_records(str(tmp_path))
    assert len(records) == 1


def test_w2_001_retirement_refuses_trash_outside_trash_branch(tmp_path):
    (tmp_path / "_trash").mkdir(parents=True)
    (tmp_path / "not-trash").mkdir()
    _journal(tmp_path, [{"original": str(tmp_path / "keep-silo"),
                         "trashed": str(tmp_path / "not-trash" / "keep-silo")}])
    data = {}

    _reconcile_retirement_journal(str(tmp_path), data, lambda o: False)

    assert data["folder_trash_log"] == []
    assert len(_journal_load_records(str(tmp_path))) == 1


def test_w2_001_retirement_still_adopts_an_owned_record(tmp_path):
    (tmp_path / "_trash" / "keep-silo").mkdir(parents=True)
    _journal(tmp_path, [{"original": str(tmp_path / "keep-silo"),
                         "trashed": str(tmp_path / "_trash" / "keep-silo")}])
    data = {}

    _reconcile_retirement_journal(str(tmp_path), data, lambda o: False)

    assert len(data["folder_trash_log"]) == 1
    records = _journal_load_records(str(tmp_path))
    assert len(records) == 1 and records[0].get("merged") is True


# --- the call site: merge reconciliation -----------------------------------

def test_w2_001_merge_refuses_outside_root(tmp_path):
    (tmp_path / "_trash").mkdir(parents=True)
    outside = tmp_path.parent / "merge-foreign"
    outside.mkdir(exist_ok=True)
    som._merge_journal_write(str(tmp_path), [
        {"original": str(tmp_path / "child-a"), "trashed": str(outside),
         "done": True}])

    som._reconcile_merge_journal(str(tmp_path), {})

    remaining = som._merge_journal_load(str(tmp_path))
    assert len(remaining) == 1
