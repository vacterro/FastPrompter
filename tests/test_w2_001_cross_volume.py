"""W2-001 (acb-mtbqjyvd): cross-volume source ownership for _move_into_container.

A pathname-only post-copy source removal deletes whatever replaced the source
during the copy. The fix acquires source-side ownership (staging rename)
BEFORE the copy and removes only the owned staging object.
"""

import os
import shutil
import sys

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC = os.path.join(ROOT, "src")
sys.path.insert(0, SRC)


def _move_into_container(src, dest, root=None, root_identity=None,
                         publish_guard=None):
    """Call the real primitive from the module under test."""
    import fastprompter.ui.file_container as fc
    from fastprompter.utils.path_safety import capture_resolved_root
    if root is not None and root_identity is None:
        root_identity = capture_resolved_root(root)
    return fc._move_into_container(
        src, dest, root=root, root_identity=root_identity,
        publish_guard=publish_guard)


def _force_cross_volume(monkeypatch):
    """Make every os.rename in the module raise EXDEV for the src->dest rename,
    but allow staging-related renames (source acquisition and restore)."""
    import fastprompter.ui.file_container as fc
    real_rename = os.rename

    def fake_rename(src_path, dst_path):
        # allow staging acquisition (src -> staging), restore (staging ->
        # src), and the destination-side publish (tmp -> dest); only the
        # ORIGINAL src -> dest attempt raises EXDEV (cross-volume).
        if ".fpstaging-" in str(src_path) or ".fpstaging-" in str(dst_path):
            return real_rename(src_path, dst_path)
        if ".fptmp-" in str(src_path):
            return real_rename(src_path, dst_path)
        raise OSError(18, "Invalid cross-device link")

    monkeypatch.setattr(fc.os, "rename", fake_rename)
    return fc


def test_cross_volume_replacement_is_never_deleted(tmp_path, monkeypatch):
    src = tmp_path / "src.txt"
    src.write_text("ORIGINAL")
    dest = tmp_path / "dest.txt"
    _force_cross_volume(monkeypatch)

    # Replace the original source pathname after the staging rename but before
    # the copy — the copy primitive reads from the staging, not the pathname,
    # so the replacement at the original pathname is never deleted.
    import fastprompter.ui.file_container as fc
    real_copy2 = fc.shutil.copy2

    def copy2_with_replacement(staging, tmp):
        # the original visible pathname is replaced while the copy runs
        with open(str(src), "w", encoding="utf-8") as f:
            f.write("REPLACEMENT")
        return real_copy2(staging, tmp)

    monkeypatch.setattr(fc.shutil, "copy2", copy2_with_replacement)

    result = _move_into_container(str(src), str(dest))
    assert result in ("MOVED", "SOURCE_REMAINS")
    # the replacement at the original pathname was preserved
    assert src.read_text(encoding="utf-8") == "REPLACEMENT"
    assert dest.read_text(encoding="utf-8") == "ORIGINAL"


def test_cross_volume_moves_content(tmp_path, monkeypatch):
    src = tmp_path / "s.txt"
    src.write_text("PAYLOAD")
    dest = tmp_path / "d.txt"
    _force_cross_volume(monkeypatch)
    result = _move_into_container(str(src), str(dest))
    assert result in ("MOVED", "SOURCE_REMAINS")
    assert dest.read_text(encoding="utf-8") == "PAYLOAD"


def test_publish_failure_restores_source(tmp_path, monkeypatch):
    src = tmp_path / "s.txt"
    src.write_text("PAYLOAD")
    dest = tmp_path / "d.txt"
    fc = _force_cross_volume(monkeypatch)
    real_publish = fc._publish_new_file

    def broken_publish(tmp, d, root, root_identity):
        raise OSError("publication boom")

    monkeypatch.setattr(fc, "_publish_new_file", broken_publish)
    with pytest.raises(OSError):
        _move_into_container(str(src), str(dest))
    # source restored (staging moved back to the original pathname)
    assert src.read_text(encoding="utf-8") == "PAYLOAD"