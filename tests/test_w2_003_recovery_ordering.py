"""W2-003: canonical-day recovery must be REPEATABLE.

The pre-fix selection sorted complete siblings by the second-resolution
``exported_at`` text only. Two complete generations created within the same
second therefore tied, and Python's stable sort left the winner to
``os.listdir()`` enumeration order — the filesystem, not the backup, decided
which generation state became canonical.

Every test below pins the outcome against BOTH enumeration orders.
"""

import json
import os

import pytest

import fastprompter.utils.portable_backup as pb


@pytest.fixture
def backup_dir(tmp_path, monkeypatch):
    d = str(tmp_path / "portable")
    os.makedirs(d, exist_ok=True)
    monkeypatch.setattr(pb, "get_portable_backup_dir", lambda: d)
    pb.last_success_by_profile.clear()
    yield d


DAY = "2026-01-01"
SAME_SECOND = "2026-01-01T10:00:00"


def _mk_gen(root, name, meta):
    path = os.path.join(str(root), name)
    os.makedirs(path, exist_ok=True)
    with open(os.path.join(path, pb._COMPLETE_MARKER), "w",
              encoding="utf-8") as fh:
        fh.write("complete\n")
    with open(os.path.join(path, "_meta.json"), "w", encoding="utf-8") as fh:
        json.dump(meta, fh)
    return path


def _reverse_listdir(monkeypatch, root):
    """Make the filesystem enumerate the other way round."""
    real = os.listdir
    target = os.path.normcase(str(root))

    def reversed_listdir(path="."):
        entries = real(path)
        if os.path.normcase(str(path)) == target:
            return list(reversed(entries))
        return entries

    monkeypatch.setattr(pb.os, "listdir", reversed_listdir)
    return real


def _recover(backup_dir):
    day_dir = os.path.join(str(backup_dir), DAY)
    pb._recover_canonical_day(str(backup_dir), day_dir, DAY)
    return day_dir


def _promoted_identity(backup_dir):
    day = os.path.join(str(backup_dir), DAY)
    if not os.path.isdir(day):
        return None
    with open(os.path.join(day, "_meta.json"), encoding="utf-8") as fh:
        return json.load(fh).get("generation_id")


def test_newest_generation_ns_wins_in_either_enumeration_order(
        backup_dir, monkeypatch):
    # identical exported_at (same second) and names whose lexicographic order
    # is UNRELATED to chronology: only generation_ns can decide.
    _mk_gen(backup_dir, f"{DAY}.failed-aaaaaaaa",
            {"complete": True, "exported_at": SAME_SECOND,
             "generation_ns": 1_000_000_000_000_000_000, "generation_id": "old"})
    _mk_gen(backup_dir, f"{DAY}.failed-zzzzzzzz",
            {"complete": True, "exported_at": SAME_SECOND,
             "generation_ns": 2_000_000_000_000_000_000, "generation_id": "new"})

    day = _recover(backup_dir)
    assert _promoted_identity(backup_dir) == "new"
    assert os.path.isdir(day)

    # repeat from scratch with the opposite enumeration order
    os.rename(day, os.path.join(str(backup_dir), f"{DAY}.recovered-recheck"))
    _reverse_listdir(monkeypatch, backup_dir)
    _recover(backup_dir)
    assert _promoted_identity(backup_dir) == "new", (
        "recovery must not depend on os.listdir() order")


def test_legacy_exact_tie_refuses_promotion_and_preserves_all(
        backup_dir, monkeypatch):
    """No trustworthy ordering: fail closed instead of letting the FS decide."""
    a = _mk_gen(backup_dir, f"{DAY}.failed-11111111",
                {"complete": True, "exported_at": SAME_SECOND})
    b = _mk_gen(backup_dir, f"{DAY}.failed-22222222",
                {"complete": True, "exported_at": SAME_SECOND})

    _recover(backup_dir)
    assert not os.path.isdir(os.path.join(str(backup_dir), DAY))
    assert os.path.isdir(a) and os.path.isdir(b)

    # ...and the same for the reversed enumeration: still no promotion
    _reverse_listdir(monkeypatch, backup_dir)
    _recover(backup_dir)
    assert not os.path.isdir(os.path.join(str(backup_dir), DAY))
    assert os.path.isdir(a) and os.path.isdir(b)


def test_legacy_distinct_exported_at_still_promotes_newer(backup_dir):
    """Backward compatibility: legacy manifests with distinct stamps order."""
    _mk_gen(backup_dir, f"{DAY}.failed-aaaaaaaa",
            {"complete": True, "exported_at": "2026-01-01T09:00:00",
             "generation_id": "older"})
    _mk_gen(backup_dir, f"{DAY}.failed-bbbbbbbb",
            {"complete": True, "exported_at": "2026-01-01T11:00:00",
             "generation_id": "newer"})

    _recover(backup_dir)

    assert _promoted_identity(backup_dir) == "newer"


def test_unknown_identity_candidate_refuses_promotion(backup_dir):
    """A candidate of unknown age could be the newest: do not guess."""
    known = _mk_gen(backup_dir, f"{DAY}.failed-cccccccc",
                    {"complete": True, "exported_at": SAME_SECOND,
                     "generation_id": "known"})
    unknown = _mk_gen(backup_dir, f"{DAY}.failed-dddddddd",
                      {"complete": True})

    _recover(backup_dir)

    assert not os.path.isdir(os.path.join(str(backup_dir), DAY))
    assert os.path.isdir(known) and os.path.isdir(unknown)


def test_single_unknown_identity_alone_is_not_promoted(backup_dir):
    only = _mk_gen(backup_dir, f"{DAY}.recovered-eeeeeeee",
                   {"complete": True})

    _recover(backup_dir)

    assert not os.path.isdir(os.path.join(str(backup_dir), DAY))
    assert os.path.isdir(only)


def test_recovery_is_idempotent_after_promotion(backup_dir):
    _mk_gen(backup_dir, f"{DAY}.failed-aaaaaaaa",
            {"complete": True, "exported_at": SAME_SECOND,
             "generation_ns": 10, "generation_id": "winner"})
    _mk_gen(backup_dir, f"{DAY}.failed-bbbbbbbb",
            {"complete": True, "exported_at": SAME_SECOND,
             "generation_ns": 20, "generation_id": "also"})

    day = _recover(backup_dir)
    first = _promoted_identity(backup_dir)
    _recover(backup_dir)          # canonical now exists: no-op

    assert first is not None
    assert _promoted_identity(backup_dir) == first
    assert os.path.isdir(day)


def test_manifest_persists_orderable_generation_identity(tmp_path):
    first = tmp_path / "gen1"
    second = tmp_path / "gen2"
    first.mkdir()
    second.mkdir()
    data = {"cats_order": ["A"], "categories": {"A": []}}

    pb._write_manifest(str(first), data, ["A"], {"A": []})
    pb._write_manifest(str(second), data, ["A"], {"A": []})

    metas = []
    for d in (first, second):
        with open(d / "_meta.json", encoding="utf-8") as fh:
            metas.append(json.load(fh))

    for meta in metas:
        assert isinstance(meta["generation_ns"], int)
        assert meta["generation_ns"] > 0
        assert isinstance(meta["generation_id"], str) and meta["generation_id"]
        assert meta["exported_at"]          # still human readable

    # finer than the second-resolution stamp: two generations written inside
    # the same second are still strictly ordered (and distinguishable)
    assert metas[0]["generation_ns"] < metas[1]["generation_ns"]
    assert metas[0]["generation_id"] != metas[1]["generation_id"]


def test_generation_ns_is_what_recovery_orders_by(backup_dir):
    """A legacy stamp alone must not outrank a newer generation_ns."""
    _mk_gen(backup_dir, f"{DAY}.failed-aaaaaaaa",
            {"complete": True, "exported_at": "2026-01-01T23:59:59",
             "generation_id": "legacy-late"})
    _mk_gen(backup_dir, f"{DAY}.failed-bbbbbbbb",
            {"complete": True, "exported_at": "2026-01-01T00:00:01",
             "generation_ns": 1_800_000_000_000_000_000,
             "generation_id": "new-with-ns"})

    _recover(backup_dir)

    # the ns-bearing generation is genuinely newer (2027) than the legacy
    # 2026-01-01 23:59:59 stamp, so the absolute-time comparison picks it
    assert _promoted_identity(backup_dir) == "new-with-ns"


def test_unrelated_siblings_are_ignored_by_recovery(backup_dir):
    other = os.path.join(str(backup_dir), f"{DAY}.custom-thing")
    os.makedirs(other, exist_ok=True)
    with open(os.path.join(other, pb._COMPLETE_MARKER), "w") as fh:
        fh.write("complete\n")
    with open(os.path.join(other, "_meta.json"), "w") as fh:
        json.dump({"complete": True, "generation_ns": 10 ** 24}, fh)

    _recover(backup_dir)

    assert not os.path.isdir(os.path.join(str(backup_dir), DAY))
    assert os.path.isdir(other)
