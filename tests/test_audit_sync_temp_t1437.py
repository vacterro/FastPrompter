"""T-1437 (SRC-097) — W2-010: a sync destination's temp is owned by that write.

The mechanical sync writer allocates a unique temp sibling of each destination
and publishes it atomically. Any unsuccessful exit -- a failed write or a
failed ``os.replace`` -- must remove EXACTLY the file it created and leave no
``.sync-<uuid>.tmp`` orphan in a user-addressable directory. Never a glob.
"""

from __future__ import annotations

import os

from fastprompter import main as fpmain
from fastprompter.utils.path_safety import capture_resolved_root


def _snapshot(tmp_path, name="file.txt", text="payload"):
    dest = str(tmp_path / "sub" / name)
    return {
        "files": {dest: text},
        "root": str(tmp_path),
        "root_identity": capture_resolved_root(str(tmp_path)),
        "_write_epoch": None,
        "_write_seq": None,
    }


def _temps(directory):
    if not os.path.isdir(directory):
        return []
    return [n for n in os.listdir(directory) if n.endswith(".tmp")]


def test_w2_010_successful_write_leaves_no_temp(tmp_path):
    snap = _snapshot(tmp_path)
    dest = next(iter(snap["files"]))

    written, errors = fpmain._sync_mechanical_write(snap)

    assert written == [dest]
    assert errors == []
    assert (tmp_path / "sub" / "file.txt").read_text(encoding="utf-8") == "payload"
    assert _temps(str(tmp_path / "sub")) == []


def test_w2_010_failed_publish_removes_its_own_temp(tmp_path, monkeypatch):
    snap = _snapshot(tmp_path)
    dest = next(iter(snap["files"]))

    def boom(*_a, **_k):
        raise OSError("replace failed")

    monkeypatch.setattr(fpmain.os, "replace", boom)

    written, errors = fpmain._sync_mechanical_write(snap)

    assert written == []
    assert errors and errors[0][0] == dest
    assert not os.path.exists(dest)              # never published
    assert _temps(str(tmp_path / "sub")) == []   # temp reclaimed
