"""W2-004 (acb-mtbqjyvd): retention must never delete the sole validated
complete recovery generation just because an invalid canonical pathname for the
same date exists.
"""

import os
import sys

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC = os.path.join(ROOT, "src")
sys.path.insert(0, SRC)


def _mk_gen(path, complete=True, marker=True, meta=True):
    os.makedirs(path, exist_ok=True)
    if marker:
        open(os.path.join(path, "_COMPLETE"), "w").close()
    if meta:
        with open(os.path.join(path, "_meta.json"), "w") as f:
            f.write('{"complete": %s}' % ("true" if complete else "false"))


def _cleanup(backup_dir, max_days=0):
    # max_days=0 -> everything is "old"
    from fastprompter.utils import portable_backup as pb
    return pb._cleanup_old_backups(str(backup_dir), max_days=max_days)


def test_invalid_canonical_does_not_delete_valid_recovery(tmp_path):
    from fastprompter.utils import portable_backup as pb
    day = "2000-01-01"
    invalid_canon = tmp_path / day
    _mk_gen(invalid_canon, marker=False, meta=False)   # invalid canonical
    valid_recovery = tmp_path / f"{day}.recovered-abcd1234"
    _mk_gen(valid_recovery, complete=True, marker=True, meta=True)
    pb._cleanup_old_backups(str(tmp_path), max_days=0)
    # the invalid canonical may be pruned, but the valid recovery must survive
    assert valid_recovery.exists(), \
        "the only valid complete recovery generation was deleted"

def test_missing_complete_canonical_does_not_delete_valid_recovery(tmp_path):
    from fastprompter.utils import portable_backup as pb
    day = "2000-01-02"
    no_marker = tmp_path / day
    _mk_gen(no_marker, marker=False, meta=True)
    valid_recovery = tmp_path / f"{day}.recovered-deadbeef"
    _mk_gen(valid_recovery, complete=True, marker=True, meta=True)
    pb._cleanup_old_backups(str(tmp_path), max_days=0)
    assert valid_recovery.exists()

def test_incomplete_manifest_canonical_does_not_delete_valid_recovery(tmp_path):
    from fastprompter.utils import portable_backup as pb
    day = "2000-01-03"
    incomplete = tmp_path / day
    _mk_gen(incomplete, complete=False, marker=True, meta=True)
    valid_recovery = tmp_path / f"{day}.recovered-cafebabe"
    _mk_gen(valid_recovery, complete=True, marker=True, meta=True)
    pb._cleanup_old_backups(str(tmp_path), max_days=0)
    assert valid_recovery.exists()

def test_valid_canonical_permits_recovery_pruning(tmp_path):
    from fastprompter.utils import portable_backup as pb
    day = "2000-01-04"
    valid_canon = tmp_path / day
    _mk_gen(valid_canon, complete=True, marker=True, meta=True)
    recovery = tmp_path / f"{day}.recovered-12345678"
    _mk_gen(recovery, complete=True, marker=True, meta=True)
    pb._cleanup_old_backups(str(tmp_path), max_days=0)
    assert not recovery.exists(), \
        "valid canonical should permit pruning old recovery siblings"