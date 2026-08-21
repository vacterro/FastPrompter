"""Regression tests for the SECOND WAVE audit tickets (W2-002..W2-012).

Focus on the deterministic, non-Qt core:
  W2-002  the 100-slot snippet capacity invariant (serializer never writes 100+)
  W2-008  portable backup exports orphan snippet categories and counts them
  W2-009  a COMPLETE .partial recovery generation is preserved, never deleted
  W2-012  _copy_atomic aborts publication when the ownership guard rejects
"""

import json
import os

import pytest

import fastprompter.utils.portable_backup as pb


# ----------------------------------------------------------------- W2-008
@pytest.fixture
def backup_dir(tmp_path, monkeypatch):
    d = str(tmp_path / "portable")
    os.makedirs(d, exist_ok=True)
    monkeypatch.setattr(pb, "get_portable_backup_dir", lambda: d)
    pb.last_success_by_profile.clear()
    yield d


def _orphan_data():
    return {
        "cats_order": ["Visible"],
        "categories": {
            "Visible": [{"name": "v1", "text": "visible-snippet"}],
            # orphan: populated but absent from cats_order
            "Orphan": [{"name": "o1", "text": "orphan-snippet"}],
        },
        "temp_presets_all": {"Visible": ["v silo"]},
        "archive_temp_presets_all": {},
        "temp_presets": [],
        "archive_temp_presets": [],
    }


def test_orphan_snippet_category_is_exported(backup_dir):
    pb._do_export(_orphan_data(), profile_id=1)
    day = os.path.join(backup_dir, pb.time.strftime("%Y-%m-%d"))
    assert os.path.isfile(os.path.join(day, pb._COMPLETE_MARKER))
    snips = os.path.join(day, "snippets")
    files = set(os.listdir(snips))
    assert any("Orphan" in f for f in files), files
    content = ""
    for f in files:
        p = os.path.join(snips, f)
        with open(p, encoding="utf-8") as fh:
            content += fh.read()
    assert "orphan-snippet" in content
    assert "visible-snippet" in content


def test_manifest_counts_orphan_snippets(backup_dir):
    pb._do_export(_orphan_data(), profile_id=1)
    day = os.path.join(backup_dir, pb.time.strftime("%Y-%m-%d"))
    with open(os.path.join(day, "_meta.json"), encoding="utf-8") as fh:
        meta = json.load(fh)
    assert meta["snippet_count"] == 2  # both Visible and Orphan counted


# ----------------------------------------------------------------- W2-009
def test_complete_partial_is_preserved_not_deleted(backup_dir, monkeypatch):
    pb._do_export(_orphan_data(), profile_id=1)
    day = os.path.join(backup_dir, pb.time.strftime("%Y-%m-%d"))
    # simulate the double-failure publish that leaves COMPLETE at .partial
    tmp = day + ".partial"
    import shutil
    shutil.copytree(day, tmp)

    # force publish failure so the retry path runs
    real_rename = os.rename

    def failing_rename(src, dst):
        # fail EVERY rename of the COMPLETE tmp (step-2 publish AND the
        # recovery-preserve), so the double-failure path leaves COMPLETE
        # at .partial exactly as the audit describes.
        if src == tmp:
            raise OSError("simulated double failure")
        return real_rename(src, dst)

    monkeypatch.setattr(os, "rename", failing_rename)
    with pytest.raises(OSError):
        pb._publish_snapshot(tmp, day)

    # now COMPLETE lives at .partial again (per the preserve path); a NEW
    # export must preserve it under a .recovered-* name, not destroy it.
    monkeypatch.setattr(os, "rename", real_rename)
    pb._do_export(_orphan_data(), profile_id=1)
    prefix = os.path.basename(day) + ".recovered-"
    recovered = [e for e in os.listdir(backup_dir) if e.startswith(prefix)]
    assert recovered, "COMPLETE .partial recovery generation must be preserved"
    rec_path = os.path.join(backup_dir, recovered[0])
    assert os.path.isfile(os.path.join(rec_path, pb._COMPLETE_MARKER))


def test_incomplete_partial_is_cleanable(backup_dir):
    day = os.path.join(backup_dir, pb.time.strftime("%Y-%m-%d"))
    tmp = day + ".partial"
    os.makedirs(tmp, exist_ok=True)
    with open(os.path.join(tmp, "half.txt"), "w") as fh:
        fh.write("incomplete")
    # no COMPLETE marker: a normal export must clean it and rebuild
    pb._do_export(_orphan_data(), profile_id=1)
    assert not os.path.exists(tmp)


# ----------------------------------------------------------------- W2-002 (updated to CORE-001 fail-closed)
def test_state_saver_never_writes_snippet_slot_100(tmp_path):
    import sqlite3
    from fastprompter.core import state as state_mod

    path = str(tmp_path / "db.db")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    state_mod.get_db_path = lambda profile_id=1: path
    s = state_mod.FastPrompterState(profile_id=1)
    try:
        # inject a 101st item (slot 100) directly into memory — must fail closed
        s.data["categories"]["Code"].append(
            {"name": "overflow", "text": "x"})
        s._dirty_snippets = getattr(s, "_dirty_snippets", 0) + 1
        s.mark_dirty()
        assert not s.save_data_to_db(None, force=True, sync=True)
        assert s._db_dirty is True

        conn = sqlite3.connect(path)
        try:
            rows = conn.execute(
                "SELECT slot FROM presets WHERE slot >= 100").fetchall()
        finally:
            conn.close()
        assert rows == [], "slot >= 100 must never be reported as durable"
    finally:
        s.conn.close()


# ----------------------------------------------------------------- W2-012
def test_copy_atomic_aborts_when_publish_guard_rejects(tmp_path):
    from fastprompter.ui.file_container import _copy_atomic

    src = str(tmp_path / "src")
    dst = str(tmp_path / "dst")
    os.makedirs(src)
    with open(os.path.join(src, "a.txt"), "w") as fh:
        fh.write("data")

    def _guard():
        return False  # the owner vanished while the copy ran

    with pytest.raises(OSError):
        _copy_atomic(src, dst, True, str(tmp_path), None, publish_guard=_guard)
    assert not os.path.exists(dst)
    # no leftover temp
    leftovers = [e for e in os.listdir(str(tmp_path))
                 if "fptmp" in e]
    assert leftovers == []


def test_copy_atomic_publishes_when_guard_accepts(tmp_path):
    from fastprompter.ui.file_container import _copy_atomic

    src = str(tmp_path / "src")
    dst = str(tmp_path / "dst")
    os.makedirs(src)
    with open(os.path.join(src, "a.txt"), "w") as fh:
        fh.write("data")

    def _guard():
        return True

    _copy_atomic(src, dst, True, str(tmp_path), None, publish_guard=_guard)
    assert os.path.isdir(dst)
    assert os.path.isfile(os.path.join(dst, "a.txt"))
