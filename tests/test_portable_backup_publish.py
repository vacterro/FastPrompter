"""P1-7 regression: a portable-backup publish DOUBLE failure must preserve
BOTH generations on disk.

The old code, when the restore of the previous generation AND the rename of
the new generation both failed, ran ``shutil.rmtree(tmp_dir)`` — destroying
the ONLY complete copy of the new snapshot. The fix preserves the complete
generation under its temp path and leaves the old one under its rollback
sibling, logging both recovery paths.
"""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

import pytest

import fastprompter.utils.portable_backup as pb


def test_publish_double_failure_preserves_both_generations(tmp_path, monkeypatch):
    backup = tmp_path / "backup"
    day_dir = backup / "2026-01-01"
    tmp_dir = backup / "2026-01-01.partial"
    day_dir.mkdir(parents=True)
    tmp_dir.mkdir()
    (day_dir / "old.txt").write_text("old", encoding="utf-8")
    (tmp_dir / "complete.txt").write_text("new", encoding="utf-8")

    # Only the very first rename (day_dir -> .rollback-*) may succeed; every
    # later rename (publish, restore, preserve) fails like a locked volume.
    real_rename = os.rename

    def failing_rename(src, dst):
        if str(dst).startswith(str(day_dir) + ".rollback-"):
            return real_rename(src, dst)
        raise OSError(13, "Permission denied", str(dst))

    monkeypatch.setattr(os, "rename", failing_rename)

    with pytest.raises(OSError):
        pb._publish_snapshot(str(tmp_dir), str(day_dir))

    # The COMPLETE new generation survives under its temp path (P1-7).
    assert (tmp_dir / "complete.txt").read_text(encoding="utf-8") == "new"
    # The previous generation survives under its unique rollback sibling.
    rollbacks = list(backup.glob("2026-01-01.rollback-*"))
    assert len(rollbacks) == 1
    assert (rollbacks[0] / "old.txt").read_text(encoding="utf-8") == "old"
    assert not day_dir.exists()


def test_publish_single_failure_keeps_old_and_drops_new(tmp_path, monkeypatch):
    backup = tmp_path / "backup"
    day_dir = backup / "2026-01-01"
    tmp_dir = backup / "2026-01-01.partial"
    day_dir.mkdir(parents=True)
    tmp_dir.mkdir()
    (day_dir / "old.txt").write_text("old", encoding="utf-8")

    # The relocation of the OLD generation fails: the old one must stay put
    # and the incomplete new one is discarded — nothing may be deleted first.
    def failing_rename(src, dst):
        raise OSError(5, "Access denied", str(dst))

    monkeypatch.setattr(os, "rename", failing_rename)

    with pytest.raises(OSError):
        pb._publish_snapshot(str(tmp_dir), str(day_dir))

    assert (day_dir / "old.txt").read_text(encoding="utf-8") == "old"
    assert not tmp_dir.exists()


def test_publish_restore_success_preserves_complete_new_generation(
        tmp_path, monkeypatch):
    """P1-6: step-2 failure + successful rollback must NOT delete the
    COMPLETE new generation — it is preserved under a unique .failed-* name."""
    backup = tmp_path / "backup"
    day_dir = backup / "2026-01-01"
    tmp_dir = backup / "2026-01-01.partial"
    day_dir.mkdir(parents=True)
    tmp_dir.mkdir()
    (day_dir / "old.txt").write_text("old", encoding="utf-8")
    (tmp_dir / "complete.txt").write_text("new", encoding="utf-8")

    real_rename = os.rename

    def failing_rename(src, dst):
        if str(dst).startswith(str(day_dir) + ".rollback-"):
            return real_rename(src, dst)      # step-1 relocate old: allowed
        if str(src).startswith(str(day_dir) + ".rollback-"):
            return real_rename(src, dst)      # restore old back: allowed
        if str(dst).startswith(str(day_dir) + ".failed-"):
            return real_rename(src, dst)      # preserve complete new: allowed
        raise OSError(13, "Permission denied", str(dst))   # publish: blocks

    monkeypatch.setattr(os, "rename", failing_rename)

    with pytest.raises(OSError):
        pb._publish_snapshot(str(tmp_dir), str(day_dir))

    assert (day_dir / "old.txt").read_text(encoding="utf-8") == "old", \
        "the previous generation was restored"
    assert not tmp_dir.exists()
    assert not list(backup.glob("2026-01-01.rollback-*"))
    failed = list(backup.glob("2026-01-01.failed-*"))
    assert len(failed) == 1, failed
    assert (failed[0] / "complete.txt").read_text(encoding="utf-8") == "new", \
        "the complete new generation must survive under .failed-*"


def test_publish_success_swaps_and_discards_old(tmp_path):
    backup = tmp_path / "backup"
    day_dir = backup / "2026-01-01"
    tmp_dir = backup / "2026-01-01.partial"
    day_dir.mkdir(parents=True)
    tmp_dir.mkdir()
    (day_dir / "old.txt").write_text("old", encoding="utf-8")
    (tmp_dir / "complete.txt").write_text("new", encoding="utf-8")

    pb._publish_snapshot(str(tmp_dir), str(day_dir))

    assert (day_dir / "complete.txt").read_text(encoding="utf-8") == "new"
    assert not (day_dir / "old.txt").exists()
    assert not tmp_dir.exists()
    assert not list(backup.glob("2026-01-01.rollback-*"))
    assert not list(backup.glob("2026-01-01.failed-*"))
