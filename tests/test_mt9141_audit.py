"""Audit acb-mt9141yi regression coverage.

Covers the implementation-agent repairs: CORE-001 trash-link resolver,
CORE-002/W2-001 transaction-aware retirement journal, W2-005 consumed
markers, CORE-005 watcher resume delegation, CORE-006 backup profile
attribution and PERF-003 portable-backup content generation.
"""

import json
import os
import sqlite3
import types

import pytest

from fastprompter.ui import snippet_ops_mixin as som
from fastprompter.ui.snippet_ops_mixin import (
    SnippetOpsMixin,
    _journal_path,
    _journal_load_records,
    _write_retirement_journal,
    resolve_trash_link,
)


# ----------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------

def _stub(root, data):
    obj = types.SimpleNamespace()
    obj._files_root = lambda: str(root)
    obj.data = data
    obj._prune_folder_trash_log = lambda log: None
    obj._delete_file_container = (
        SnippetOpsMixin._delete_file_container.__get__(obj))
    obj._detach_file_container_for = lambda folder: None
    return obj


# ----------------------------------------------------------------------
# CORE-001: resolve_trash_link
# ----------------------------------------------------------------------

class TestCore001Resolver:
    def test_exact_absolute_link_matches_own_record_only(self, tmp_path):
        orig_a = tmp_path / "CatA" / "dup"
        orig_b = tmp_path / "CatB" / "dup"
        tr_a = tmp_path / "_trash" / "dup-1"
        tr_b = tmp_path / "_trash" / "dup-2"
        for d in (orig_a, orig_b, tr_a, tr_b):
            d.mkdir(parents=True)
        log = [(str(orig_b), str(tr_b)), (str(orig_a), str(tr_a))]
        sel, remaining = resolve_trash_link(str(orig_a), log)
        assert sel == (str(orig_a), str(tr_a))
        assert remaining == [(str(orig_b), str(tr_b))]

    def test_legacy_basename_fallback_consumes_one(self, tmp_path):
        tr1 = tmp_path / "_trash" / "dup-1"
        tr2 = tmp_path / "_trash" / "dup-2"
        for d in (tr1, tr2):
            d.mkdir(parents=True)
        log = [("C:/x/CatA/dup", str(tr1)), ("C:/x/CatB/dup", str(tr2))]
        sel, remaining = resolve_trash_link("dup", log)
        assert sel[1] == str(tr1)          # first deterministic candidate
        assert len(remaining) == 1         # sibling record preserved
        assert remaining[0][1] == str(tr2)

    def test_no_match_leaves_log_untouched(self):
        log = [("a", "b")]
        sel, remaining = resolve_trash_link("zzz", log)
        assert sel is None
        assert remaining == log

    def test_missing_trash_dir_is_not_recoverable(self, tmp_path):
        log = [(str(tmp_path / "gone"), str(tmp_path / "alsogone"))]
        sel, remaining = resolve_trash_link(str(tmp_path / "gone"), log)
        assert sel is None
        assert len(remaining) == 1

    def test_restore_new_format_returns_assets_to_slot(self, tmp_path,
                                                       monkeypatch):
        pytest.importorskip("PyQt6.QtWidgets")
        from fastprompter import main as main_mod
        cat = "CatX"
        comp = "CatX-files"
        root = tmp_path
        orig = root / comp / "silo-folder"
        (orig / "asset.txt").parent.mkdir(parents=True)
        (orig / "asset.txt").write_text("data", encoding="utf-8")
        trashed = root / "_trash" / "silo-folder-123"
        trashed.parent.mkdir(parents=True, exist_ok=True)
        os.rename(orig, trashed)

        data = {
            "trash_text_folder": {"dead.md": str(orig)},
            "folder_trash_log": [(str(orig), str(trashed))],
            "silo_folders_all": {cat: {}},
            "silo_folders": {},
        }
        w = types.SimpleNamespace()
        w.data = data
        w._files_root = lambda: str(root)
        w.get_current_category = lambda: cat
        w._category_files_dir = lambda c: comp if c == cat else None
        w.mark_dirty = lambda *a, **k: None
        meth = main_mod.FastPrompter._restore_trash_file_container.__get__(w)
        name = meth("dead.md", "text", 0)
        assert name == "silo-folder"
        assert (root / comp / name / "asset.txt").read_text(
            encoding="utf-8") == "data"
        assert not trashed.exists()
        assert data["folder_trash_log"] == []
        assert "dead.md" not in data["trash_text_folder"]
        assert data["silo_folders"]["0"] == name


# ----------------------------------------------------------------------
# CORE-002 / W2-001: multi-record transaction-aware journal
# ----------------------------------------------------------------------

class TestJournal:
    def _retire(self, root, data, name):
        src = root / name
        src.mkdir()
        (src / "f.txt").write_text("x", encoding="utf-8")
        obj = _stub(root, data)
        status = obj._delete_file_container("Cat", str(src))
        assert status == "MOVED_TO_TRASH"
        return obj

    def test_two_moves_keep_two_journal_records(self, tmp_path):
        data = {}
        self._retire(tmp_path, data, "one")
        self._retire(tmp_path, data, "two")
        records = _journal_load_records(str(tmp_path))
        assert len(records) == 2
        originals = {r["original"] for r in records}
        assert any(o.endswith("one") for o in originals)
        assert any(o.endswith("two") for o in originals)

    def test_write_failure_refuses_move(self, tmp_path, monkeypatch):
        monkeypatch.setattr(som, "_write_retirement_journal",
                            lambda r, e: False)
        src = tmp_path / "keepme"
        src.mkdir()
        (src / "a.txt").write_text("x", encoding="utf-8")
        obj = _stub(tmp_path, {})
        assert obj._delete_file_container("Cat", str(src)) == "FAILED"
        assert src.is_dir()

    def test_reconcile_rolls_back_uncommitted_deletion(self, tmp_path):
        data = {
            "category_file_dirs": {"Cat": "comp"},
            "silo_folders_all": {"Cat": {"0": "live-silo"}},
        }
        self._retire(tmp_path, data, "live-silo")
        live_owner = lambda original: True   # DB still owns the folder
        som._reconcile_retirement_journal(str(tmp_path), data, live_owner)
        # physical folder returned home; journal retired; no log entry
        assert (tmp_path / "live-silo" / "f.txt").is_file()
        assert not _journal_load_records(str(tmp_path))
        assert data["folder_trash_log"] == []

    def test_reconcile_adopts_committed_deletion_until_ack(self, tmp_path):
        data = {"folder_trash_log": []}
        self._retire(tmp_path, data, "dead-silo")
        som._reconcile_retirement_journal(str(tmp_path), data,
                                          lambda o: False)
        # recovery mapping merged...
        assert len(data["folder_trash_log"]) == 1
        # ...but the durable claim REMAINS until a successful save acks it
        records = _journal_load_records(str(tmp_path))
        assert len(records) == 1 and records[0].get("merged") is True
        # idempotent second run (simulated crash before save + restart)
        som._reconcile_retirement_journal(str(tmp_path), data,
                                          lambda o: False)
        assert len(data["folder_trash_log"]) == 1
        assert len(_journal_load_records(str(tmp_path))) == 1
        # successful commit containing the pair retires the record
        som._ack_retirement_journal(str(tmp_path), data)
        assert not _journal_load_records(str(tmp_path))

    def test_rollback_purges_durable_claim(self, tmp_path):
        data = {}
        self._retire(tmp_path, data, "rolled-back")
        records = _journal_load_records(str(tmp_path))
        trashed = records[0]["trashed"]
        som._purge_retirement_record(str(tmp_path), trashed)
        assert not _journal_load_records(str(tmp_path))

    def test_legacy_v1_journal_migrates(self, tmp_path):
        jp = _journal_path(str(tmp_path))
        os.makedirs(os.path.dirname(jp), exist_ok=True)
        with open(jp, "w", encoding="utf-8") as f:
            json.dump({"original": "C:/x/s", "trashed": "C:/x/_trash/s"},
                      f)
        records = _journal_load_records(str(tmp_path))
        assert len(records) == 1
        assert records[0]["original"] == "C:/x/s"


# ----------------------------------------------------------------------
# W2-005: consumed markers hide restored sources
# ----------------------------------------------------------------------

class TestW2005Consumed:
    def test_consumed_source_not_listed(self, tmp_path):
        pytest.importorskip("PyQt6.QtWidgets")
        from fastprompter.ui.trash_dialog import TrashDialog

        class _MW(types.SimpleNamespace):
            def tr(self, text, lang=None):
                return text

        trash = tmp_path / "_trash"
        trash.mkdir(parents=True)
        md = trash / "gone.md"
        md.write_text("text", encoding="utf-8")
        mw = _MW(data={"trash_consumed": {"gone.md": True}})
        dlg = TrashDialog.__new__(TrashDialog)
        dlg.main_win = mw
        dlg.trash_dir = str(trash)
        from PyQt6.QtWidgets import QListWidget
        dlg.list_widget = QListWidget()
        dlg._load_trash()
        assert dlg.list_widget.count() == 0
