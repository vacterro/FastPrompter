"""T-1437 (SRC-097) — W2-007: the operation's own result owns retention slot 1.

In a content-reversion reuse the archive the caller is about to hand to the
clipboard is an OLDER history record. Plain newest-first counting would delete
it while reporting "Bundle unchanged". ``protect`` names it, and a protected
path that is provably a FastPrompter bundle consumes the newest retention slot.
"""

from __future__ import annotations

import json
import zipfile

from fastprompter.core import silo_bundle as sb


def _bundle(path, fingerprint):
    """A minimal bundle that ``_is_proven_fastprompter_bundle`` accepts."""
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("manifest.json", json.dumps({
            "schema_version": 6,
            "producer": "FastPrompter",
            "bundle_kind": "silo_bundle",
            "content_fingerprint": fingerprint,
        }))


def _history(tmp_path, names):
    records = []
    for i, name in enumerate(names):
        p = tmp_path / name
        _bundle(p, f"fp-{name}")
        records.append({"path": str(p), "content_fingerprint": f"fp-{name}",
                        "bundle_kind": "silo_bundle"})
    return records          # newest-first, as the caller orders them


def test_w2_007_protected_older_result_survives_retention(tmp_path):
    records = _history(tmp_path, ["new.zip", "mid.zip", "old.zip"])
    protected = str(tmp_path / "old.zip")

    kept, pruned = sb.prune_silo_history(records, str(tmp_path), 1,
                                         protect=protected)

    assert [r["path"] for r in kept] == [protected]
    assert sorted(pruned) == [str(tmp_path / "mid.zip"),
                              str(tmp_path / "new.zip")]
    assert (tmp_path / "old.zip").is_file()


def test_w2_007_without_protection_the_newest_wins(tmp_path):
    records = _history(tmp_path, ["new.zip", "mid.zip", "old.zip"])

    kept, pruned = sb.prune_silo_history(records, str(tmp_path), 1)

    assert [r["path"] for r in kept] == [str(tmp_path / "new.zip")]
    assert (tmp_path / "new.zip").is_file()
    assert not (tmp_path / "old.zip").exists()


def test_w2_007_an_unprovable_protect_path_earns_no_slot(tmp_path):
    records = _history(tmp_path, ["new.zip", "mid.zip", "old.zip"])
    foreign = tmp_path / "foreign.zip"
    with zipfile.ZipFile(foreign, "w") as zf:
        zf.writestr("readme.txt", "not a FastPrompter bundle")

    kept, _pruned = sb.prune_silo_history(records, str(tmp_path), 1,
                                          protect=str(foreign))

    assert [r["path"] for r in kept] == [str(tmp_path / "new.zip")]
    assert foreign.is_file()          # never touched
