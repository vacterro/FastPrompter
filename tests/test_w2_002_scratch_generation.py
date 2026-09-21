"""W2-002: a failed/partial cleanup of an incomplete scratch tree must never
contaminate the next published backup generation.

The pre-fix shape deleted the fixed ``<day>.partial`` with
``rmtree(..., ignore_errors=True)`` and then rebuilt with
``makedirs(..., exist_ok=True)``. A surviving stale file was therefore merged
into the new generation, which was then stamped ``_COMPLETE`` — a false-complete
recovery artifact. Every test here is a real fault injection:

* legacy cleanup cannot remove the stale tree (Windows-style locked/read-only
  child, antivirus, sharing violation);
* an existing scratch candidate must never be adopted;
* scratch allocation failure must leave the canonical generation untouched.
"""

import datetime
import hashlib
import json
import os
import shutil

import pytest

import fastprompter.utils.portable_backup as pb

STALE = "STALE_GENERATION"


@pytest.fixture
def backup_dir(tmp_path, monkeypatch):
    d = str(tmp_path / "portable")
    os.makedirs(d, exist_ok=True)
    monkeypatch.setattr(pb, "get_portable_backup_dir", lambda: d)
    pb.last_success_by_profile.clear()
    yield d


def _data(project="New", text="new generation text"):
    return {
        "cats_order": [project],
        "categories": {project: [{"name": "s1", "text": "snip"}]},
        "temp_presets_all": {project: [text]},
        "archive_temp_presets_all": {},
        "temp_presets": [],
        "archive_temp_presets": [],
    }


def _day(backup_dir):
    return os.path.join(backup_dir, pb.time.strftime("%Y-%m-%d"))


def _walk_texts(root):
    """Every file beneath ``root`` as {relative_path: content}."""
    out = {}
    for dirpath, _dirs, files in os.walk(root):
        for name in files:
            p = os.path.join(dirpath, name)
            with open(p, encoding="utf-8", errors="replace") as fh:
                out[os.path.relpath(p, root).replace("\\", "/")] = fh.read()
    return out


def _tree_fingerprint(root):
    return {rel: hashlib.sha256(txt.encode("utf-8")).hexdigest()
            for rel, txt in _walk_texts(root).items()}


def _make_stale_legacy_scratch(day):
    """The audit's exact scenario: an incomplete old generation left behind."""
    stale_dir = day + ".partial"
    victim = os.path.join(stale_dir, "silos", "Old")
    os.makedirs(victim, exist_ok=True)
    with open(os.path.join(victim, "silo_001.md"), "w", encoding="utf-8") as fh:
        fh.write(STALE)
    return stale_dir


def _refuse_removal(monkeypatch, victim):
    """Simulate a recursive delete that cannot remove ``victim``."""
    real_rmtree = shutil.rmtree

    def fake_rmtree(path, *args, **kwargs):
        if os.path.normcase(str(path)) == os.path.normcase(str(victim)):
            raise PermissionError("simulated locked/read-only child")
        return real_rmtree(path, *args, **kwargs)

    monkeypatch.setattr(pb.shutil, "rmtree", fake_rmtree)


def test_failed_legacy_cleanup_does_not_contaminate_new_generation(
        backup_dir, monkeypatch):
    day = _day(backup_dir)
    stale_dir = _make_stale_legacy_scratch(day)
    _refuse_removal(monkeypatch, stale_dir)

    pb._do_export(_data(), profile_id=1)

    assert os.path.isfile(os.path.join(day, pb._COMPLETE_MARKER))
    texts = _walk_texts(day)
    assert not any(STALE in t for t in texts.values()), texts
    assert not any(rel.startswith("silos/Old/") for rel in texts), texts
    # The survivor was reported, not silently pretended away...
    assert os.path.isdir(stale_dir)
    # ...and it was never adopted as the construction root: no stale artifact
    # reached the published tree, and no scratch generation was left behind.
    assert [e for e in os.listdir(backup_dir) if ".partial-" in e] == []


def test_published_generation_contains_only_current_artifacts(
        backup_dir, monkeypatch):
    """Every file beneath a published generation is attributable to it."""
    day = _day(backup_dir)
    stale_dir = _make_stale_legacy_scratch(day)
    _refuse_removal(monkeypatch, stale_dir)
    # an unrelated stale artifact too: no export input produces this name
    with open(os.path.join(stale_dir, "leftover.txt"), "w",
              encoding="utf-8") as fh:
        fh.write(STALE)

    pb._do_export(_data(), profile_id=1)

    files = set(_walk_texts(day))
    assert pb._COMPLETE_MARKER in files
    assert "_meta.json" in files
    assert not any("Old" in f or "leftover" in f for f in files), files
    with open(os.path.join(day, "_meta.json"), encoding="utf-8") as fh:
        assert json.load(fh)["complete"] is True


def test_readonly_locked_child_survivor_is_never_reused(backup_dir, monkeypatch):
    day = _day(backup_dir)
    stale_dir = _make_stale_legacy_scratch(day)
    victim = os.path.join(stale_dir, "silos", "Old", "silo_001.md")
    os.chmod(victim, 0o444)
    _refuse_removal(monkeypatch, stale_dir)

    pb._do_export(_data(project="Other", text="current"), profile_id=1)

    texts = _walk_texts(day)
    assert not any(STALE in t for t in texts.values()), texts
    assert any("current" in t for t in texts.values()), texts
    assert os.path.isfile(os.path.join(day, pb._COMPLETE_MARKER))


def test_existing_scratch_candidate_is_never_adopted(backup_dir, monkeypatch):
    """A colliding scratch NAME must be skipped, not built into."""
    day = _day(backup_dir)
    squatted = day + ".partial-deadbeef"
    os.makedirs(os.path.join(squatted, "silos", "Old"), exist_ok=True)
    with open(os.path.join(squatted, "silos", "Old", "silo_001.md"), "w",
              encoding="utf-8") as fh:
        fh.write(STALE)

    names = iter(["deadbeef", "cafe0001"])
    monkeypatch.setattr(pb, "_gen_suffix", lambda: next(names, "beeffeed"))

    pb._do_export(_data(), profile_id=1)

    # the squatted tree is untouched and was NOT the construction root
    assert os.path.isfile(
        os.path.join(squatted, "silos", "Old", "silo_001.md"))
    texts = _walk_texts(day)
    assert not any(STALE in t for t in texts.values()), texts
    assert not any("Old" in rel for rel in texts), texts


def test_scratch_allocation_failure_leaves_canonical_intact(
        backup_dir, monkeypatch):
    pb._do_export(_data(text="known good"), profile_id=1)
    day = _day(backup_dir)
    before = _tree_fingerprint(day)

    def boom(_day_dir):
        raise RuntimeError("simulated scratch allocation failure")

    monkeypatch.setattr(pb, "_alloc_scratch_root", boom)
    with pytest.raises(RuntimeError):
        pb._do_export(_data(text="must not publish"), profile_id=1)

    assert _tree_fingerprint(day) == before
    leftovers = [e for e in os.listdir(backup_dir) if ".partial" in e]
    assert leftovers == [], leftovers


def test_incomplete_scratch_growth_is_bounded_and_canonical_untouched(
        backup_dir):
    """Retention still recognises and prunes an old incomplete scratch tree."""
    old_date = (datetime.date.today() - datetime.timedelta(days=30)).isoformat()
    scratch = os.path.join(backup_dir, old_date + ".partial-abc12345")
    os.makedirs(os.path.join(scratch, "silos", "Old"), exist_ok=True)
    with open(os.path.join(scratch, "silos", "Old", "silo_001.md"), "w",
              encoding="utf-8") as fh:
        fh.write(STALE)

    pb._do_export(_data(), profile_id=1)
    # a valid canonical for TODAY exists; the old scratch must be pruned
    pb._cleanup_old_backups(backup_dir, max_days=7)

    assert not os.path.isdir(scratch), "old incomplete scratch must not grow forever"
    assert os.path.isfile(os.path.join(_day(backup_dir), pb._COMPLETE_MARKER))


def test_complete_per_generation_scratch_is_preserved_when_canonical_missing(
        backup_dir):
    pb._do_export(_data(text="recoverable"), profile_id=1)
    day = _day(backup_dir)
    old_date = (datetime.date.today() - datetime.timedelta(days=30)).isoformat()
    scratch = os.path.join(backup_dir, old_date + ".partial-ffeeddcc")
    shutil.copytree(day, scratch)
    shutil.rmtree(day)

    pb._cleanup_old_backups(backup_dir, max_days=7)

    assert os.path.isfile(os.path.join(scratch, pb._COMPLETE_MARKER)), (
        "the only complete generation must never be pruned")


def test_recovery_promotes_complete_per_generation_scratch(backup_dir):
    """A complete generation left in a per-generation scratch root recovers."""
    pb._do_export(_data(text="recover me"), profile_id=1)
    day = _day(backup_dir)
    date_str = os.path.basename(day)
    scratch = day + ".partial-00112233"
    os.rename(day, scratch)

    pb._recover_canonical_day(backup_dir, day, date_str)

    assert os.path.isdir(day)
    assert os.path.isfile(os.path.join(day, pb._COMPLETE_MARKER))
    assert "recover me" in "".join(_walk_texts(day).values())


def test_unrelated_digit_prefixed_dir_is_left_alone(backup_dir):
    """The shared grammar must not start deleting unrelated directories."""
    other = os.path.join(backup_dir, "2020-01-01.custom-thing")
    os.makedirs(other, exist_ok=True)
    with open(os.path.join(other, "keep.txt"), "w", encoding="utf-8") as fh:
        fh.write("keep me")

    pb._do_export(_data(), profile_id=1)
    pb._cleanup_old_backups(backup_dir, max_days=7)

    assert os.path.isfile(os.path.join(other, "keep.txt"))
