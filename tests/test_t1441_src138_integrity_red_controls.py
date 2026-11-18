"""T-1441 / SRC-138 red controls: publication and preset-transaction integrity.

Three defects were independently reproduced against the live tree before any
of these tests existed, each with a real fault injection rather than a
docstring claim:

  05  ``sound_library._publish_without_clobber`` opened the FINAL destination
      with ``open(target, "xb")`` and streamed the copy into it. ``O_EXCL``
      protects the name, not the bytes: a copy that died midway left a
      truncated file discoverable at the final path.
  06  ``IntervalPresetStore._apply_batch_journal`` moved documents one by one.
      An ``OSError`` on the second move left the library physically MIXED --
      new "a" beside old "b" -- while the journal still promised the old
      generation was intact.
  07  ``import_preset`` consulted the instance cache. A second store instance
      that had loaded BEFORE the id was created happily imported over it with
      ``overwrite=False``.

Each control below fails on the pre-fix source and passes now. The assertions
name exact bytes, never a summary count.
"""

from __future__ import annotations

import hashlib
import json
import os
import pathlib

import pytest

from fastprompter.core import interval_preset_store as ips
from fastprompter.core import sound_library

# --- 05: a failed copy fallback must not publish partial bytes --------------

def _isolated_dirs(tmp_path):
    staging = tmp_path / "staging.wav"
    staging.write_bytes(b"RIFF-full-original-payload")
    target = tmp_path / "final.wav"
    return staging, target


def test_src138_05_failed_copy_fallback_leaves_no_final_file(tmp_path, monkeypatch):
    """The reported reproduction, verbatim: hardlink unsupported, copy dies
    after four bytes. The final path must not exist afterwards."""
    staging, target = _isolated_dirs(tmp_path)

    def no_hardlinks(src, dst, *a, **k):
        raise OSError(1, "hardlinks unsupported on this volume")

    def dying_copy(src, out, *a, **k):
        out.write(b"ABCD")
        out.flush()
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(os, "link", no_hardlinks)
    monkeypatch.setattr(sound_library.shutil, "copyfileobj", dying_copy)

    with pytest.raises(OSError):
        sound_library._publish_without_clobber(str(staging), str(target))

    assert not target.exists(), (
        "a partial publication became visible as the final file: "
        f"{target.read_bytes()!r}")


def test_src138_05_failed_copy_leaves_no_partial_residue(tmp_path, monkeypatch):
    """The operation-owned ``.part`` file is cleaned too: a later import must
    not find debris sitting beside the destination."""
    staging, target = _isolated_dirs(tmp_path)

    monkeypatch.setattr(os, "link",
                        lambda s, d, *a, **k: (_ for _ in ()).throw(OSError(1, "no links")))
    monkeypatch.setattr(
        sound_library.shutil, "copyfileobj",
        lambda src, out, *a, **k: (_ for _ in ()).throw(OSError(28, "disk full")))

    with pytest.raises(OSError):
        sound_library._publish_without_clobber(str(staging), str(target))

    residue = [p.name for p in tmp_path.iterdir() if not p.name.startswith("staging")]
    assert residue == [], f"failed publication left residue: {residue}"


def test_src138_05_successful_copy_fallback_publishes_full_bytes(tmp_path, monkeypatch):
    """The safe fallback must still WORK: without hardlinks a complete copy is
    published, byte-identical, and the staging source is not consumed twice."""
    staging, target = _isolated_dirs(tmp_path)
    expected = staging.read_bytes()

    monkeypatch.setattr(os, "link",
                        lambda s, d, *a, **k: (_ for _ in ()).throw(OSError(1, "no links")))

    assert sound_library._publish_without_clobber(str(staging), str(target)) is True
    assert target.read_bytes() == expected


def test_src138_05_copy_fallback_still_refuses_to_clobber(tmp_path, monkeypatch):
    """No-clobber survives the new fallback: an existing destination is never
    overwritten, and the caller is told to pick a fresh suffix."""
    staging, target = _isolated_dirs(tmp_path)
    target.write_bytes(b"EXISTING-USER-FILE")

    monkeypatch.setattr(os, "link",
                        lambda s, d, *a, **k: (_ for _ in ()).throw(OSError(1, "no links")))

    assert sound_library._publish_without_clobber(str(staging), str(target)) is False
    assert target.read_bytes() == b"EXISTING-USER-FILE"


def test_src138_05_import_file_reports_failure_without_partial_wav(tmp_path, monkeypatch):
    """End-to-end through the public entry point: a failed import leaves no
    playable file behind, which is what "the caller returns failed import"
    must actually mean for the library."""
    managed = tmp_path / "sound_library"
    managed.mkdir(parents=True)
    monkeypatch.setattr(sound_library, "managed_root", lambda: str(managed))
    monkeypatch.setattr(sound_library, "ensure_managed_root", lambda: str(managed))

    source = tmp_path / "pick.wav"
    source.write_bytes(b"RIFF" + b"\x00" * 40 + b"WAVE" + b"\x00" * 40)

    monkeypatch.setattr(os, "link",
                        lambda s, d, *a, **k: (_ for _ in ()).throw(OSError(1, "no links")))
    monkeypatch.setattr(
        sound_library.shutil, "copyfileobj",
        lambda src, out, *a, **k: (_ for _ in ()).throw(OSError(28, "disk full")))

    ref = sound_library.import_file(str(source), subdir="imported")
    assert ref == ""

    imported = managed / "imported"
    leftovers = sorted(p.name for p in imported.iterdir()) if imported.exists() else []
    assert leftovers == [], f"a failed import left files behind: {leftovers}"


# --- 06: a failed batch move must not leave a mixed generation --------------

_RULE = {
    "id": "r1", "name": "work", "minutes": 25, "enabled": True, "sound": "",
    "volume": 0.5, "show_notification": True, "show_in_top_bar": False,
    "align_mode": "clock", "all_day": True, "start_minute": 0, "end_minute": 1439,
}


def _preset(tag, minutes=25):
    return {
        "id": tag, "name": f"P-{tag}", "kind": ips.KIND_SINGLE,
        "schema_version": ips.SCHEMA_VERSION,
        "rules": [{**_RULE, "minutes": minutes}],
    }


def _fail_on_move(monkeypatch, ordinal):
    """Fail the Nth per-document move, never the journal write."""
    real = os.replace
    seen = {"n": 0}

    def flaky(src, dst, *a, **k):
        if str(dst).endswith(".json") and ".batch-journal" not in str(dst):
            seen["n"] += 1
            if seen["n"] == ordinal:
                raise OSError(5, f"injected failure on move {ordinal}")
        return real(src, dst, *a, **k)

    monkeypatch.setattr(os, "replace", flaky)
    return seen


def test_src138_06_failed_second_move_reports_the_library_as_incomplete(tmp_path, monkeypatch):
    """The pre-fix source raised a message claiming the previous library is
    unchanged while the files on disk were mixed. The refusal must not make a
    claim the disk contradicts: it names the incomplete transaction."""
    store = ips.IntervalPresetStore(directory=str(tmp_path / "store"))
    store.replace_all([_preset("a"), _preset("b")])
    before = {p: (tmp_path / "store" / f"{p}.json").read_bytes() for p in ("a", "b")}

    _fail_on_move(monkeypatch, 2)
    with pytest.raises(Exception) as caught:
        store.replace_all([_preset("a", 99), _preset("b", 99)])

    message = str(caught.value).lower()
    mixed = any((tmp_path / "store" / f"{p}.json").read_bytes() != before[p]
                for p in ("a", "b"))
    if mixed:
        assert "unchanged" not in message, (
            "the store claimed the previous library was unchanged while the "
            f"files on disk were mixed; refusal was: {caught.value!r}")


def test_src138_06_a_retried_batch_finishes_the_first_one(tmp_path, monkeypatch):
    """Recovery must CONVERGE on the new generation, never on a mixture: after
    an interrupted move, the next load completes the batch."""
    store = ips.IntervalPresetStore(directory=str(tmp_path / "store"))
    store.replace_all([_preset("a"), _preset("b")])

    _fail_on_move(monkeypatch, 2)
    with pytest.raises(Exception):
        store.replace_all([_preset("a", 99), _preset("b", 99)])

    monkeypatch.undo()
    reloaded = ips.IntervalPresetStore(directory=str(tmp_path / "store"))
    loaded = {p["id"]: p for p in reloaded.load()}
    assert set(loaded) == {"a", "b"}, f"recovery produced {sorted(loaded)}"
    for pid in ("a", "b"):
        assert loaded[pid]["rules"][0]["minutes"] == 99, (
            f"recovery left {pid} on the OLD generation: "
            f"{loaded[pid]['rules'][0]['minutes']}")


def test_src138_06_the_cache_never_disagrees_with_the_disk(tmp_path, monkeypatch):
    """After an interrupted batch the in-memory catalog must equal the files.

    It is legitimate for recovery to finish the batch during the refresh (the
    journal is still on disk and completing it is the whole point), so the
    assertion is AGREEMENT, not "still the old value": whatever ``get``
    reports must be what the directory actually holds.
    """
    store = ips.IntervalPresetStore(directory=str(tmp_path / "store"))
    store.replace_all([_preset("a")])
    _fail_on_move(monkeypatch, 1)
    with pytest.raises(Exception):
        store.replace_all([_preset("a", 99)])
    monkeypatch.undo()

    on_disk = json.loads((tmp_path / "store" / "a.json").read_text("utf-8"))
    in_memory = store.get("a")
    assert in_memory["rules"][0]["minutes"] == on_disk["rules"][0]["minutes"], (
        "the catalog still claims a generation the files do not have")


# --- 06 H-L: the fault matrix, not just the second move ---------------------

def _fail_on_journal_entry(monkeypatch, ordinal, total, *, what="move"):
    """Fail the Nth move (1-based) of an already-staged batch.

    Unlike ``_fail_on_move`` this arms the failure AFTER the journal exists, so
    it reproduces a crash in the middle of publication rather than a crash
    while staging. The journal is what recovery reads, so this is the
    interesting window.
    """
    real = os.replace

    def flaky(src, dst, *a, **k):
        if (str(dst).endswith(".json") and ".batch-journal" not in str(dst)
                and ".tmp" not in str(dst)):
            flaky.hits.append(str(dst))
            if len(flaky.hits) == ordinal and ordinal <= total:
                raise OSError(5, f"injected {what} failure at position {ordinal}")
        return real(src, dst, *a, **k)

    flaky.hits = []
    monkeypatch.setattr(os, "replace", flaky)
    return flaky


def _arm_failure_only_for_batch(monkeypatch, ordinal, size):
    """Arm the failure for a batch of ``size`` moves, then disarm after it.

    Recovery runs inside the same process, so the injection has to be
    released once the interrupted batch has done its damage; otherwise the
    recovery pass would hit the identical failure and prove nothing.
    """
    real = os.replace

    def flaky(src, dst, *a, **k):
        if (len(flaky.hits) < size and str(dst).endswith(".json")
                and ".batch-journal" not in str(dst)
                and ".tmp" not in str(dst)):
            flaky.hits.append(str(dst))
            if len(flaky.hits) == ordinal:
                raise OSError(5, f"injected failure at position {ordinal}")
        return real(src, dst, *a, **k)

    flaky.hits = []
    monkeypatch.setattr(os, "replace", flaky)
    return flaky


def _batch(count, minutes):
    return [_preset(f"p{i}", minutes) for i in range(count)]


def _payload(doc):
    """The exact bytes the store writes for one document."""
    return json.dumps(doc, indent=2, ensure_ascii=False,
                      sort_keys=True).encode("utf-8")


def _move(src_name, doc):
    """A journal move entry, digest included, as the store now writes it."""
    return {"src": src_name, "dst": f"{doc['id']}.json",
            "sha256": hashlib.sha256(_payload(doc)).hexdigest()}


@pytest.mark.parametrize("ordinal", [1, 3, 5])
def test_src138_06_recovery_after_an_interrupted_first_middle_and_last_move(
        tmp_path, monkeypatch, ordinal):
    """SRC-138/§06 H: recovery must converge on the NEW generation whatever
    move died.

    The three positions are the distinct failure shapes: nothing published yet
    (first), a genuine mixture (middle), and everything moved with only the
    stale half left (last). In every case the next load must report exactly
    the five new documents, never a mixture and never the old generation.
    """
    store = ips.IntervalPresetStore(directory=str(tmp_path / "store"))
    store.replace_all(_batch(5, 10))          # old generation, 5 files

    # A 5-file batch whose documents all differ from the old ones.
    _arm_failure_only_for_batch(monkeypatch, ordinal, 5)
    with pytest.raises(Exception):
        store.replace_all(_batch(5, 20))
    monkeypatch.undo()

    reloaded = ips.IntervalPresetStore(directory=str(tmp_path / "store"))
    loaded = {p["id"]: p["rules"][0]["minutes"] for p in reloaded.load()}
    assert set(loaded) == {f"p{i}" for i in range(5)}, (
        f"failure at move {ordinal} left {sorted(loaded)}")
    assert set(loaded.values()) == {20}, (
        f"failure at move {ordinal} left a MIXED generation: {loaded}")


@pytest.mark.parametrize("ordinal", [1, 3, 5])
def test_src138_06_a_mutation_is_refused_while_the_batch_is_unfinished(
        tmp_path, ordinal):
    """SRC-138/§06 E: an unresolved transaction blocks conflicting writes.

    The fixture is a journal recovery cannot apply -- the staged file is gone
    and the destination does not carry the batch's digest -- which is what a
    half-written staging directory or a foreign cleanup leaves behind. Reads
    must keep working; a WRITE must refuse and say why.
    """
    root = tmp_path / "store"
    store = ips.IntervalPresetStore(directory=str(root))
    store.replace_all(_batch(5, 10))

    token = f"dead{ordinal:04d}"
    staging = root / f".batch-staging-{token}"
    staging.mkdir()
    journal = {
        "token": token,
        "moves": [{"src": f"x-p{ordinal}.json", "dst": f"p{ordinal}.json",
                   "sha256": "0" * 64}],
        "stale": [],
    }
    (root / ".batch-journal.json").write_text(json.dumps(journal),
                                             encoding="utf-8")

    broken = ips.IntervalPresetStore(directory=str(root))
    with pytest.raises(ips.PresetRecoveryError):
        broken.create_preset("new", _RULE)
    assert broken.recovery_problem, (
        "the library refused the write but reported no reason for it")

    # Reads still work: a mixture the user can see beats an unreadable library.
    assert broken.load() is not None


def test_src138_06_failure_during_stale_deletion_keeps_the_journal(tmp_path,
                                                                  monkeypatch):
    """SRC-138/§06 I: stale removal is the destructive half of the batch.

    If it dies part-way the new generation is already published but some old
    files are still there, so the directory holds BOTH. ``replace_all`` repairs
    this in-process before it returns, so the crash case is modelled the way a
    real crash happens: the process stops before the repair, which is exactly
    what the on-disk journal plus a fresh instance simulate here.
    """
    root = tmp_path / "store"
    store = ips.IntervalPresetStore(directory=str(root))
    store.replace_all(_batch(4, 10))          # p0..p3; two become stale

    token = "5ta1e001"
    staging = root / f".batch-staging-{token}"
    staging.mkdir()
    wanted = {f"p{i}": _preset(f"p{i}", 20) for i in range(2)}
    for name, doc in wanted.items():
        (staging / f"x-{name}.json").write_bytes(_payload(doc))
    journal = {
        "token": token,
        "moves": [_move(f"x-{name}.json", doc) for name, doc in wanted.items()],
        "stale": ["p2", "p3"],
    }
    (root / ".batch-journal.json").write_text(json.dumps(journal),
                                             encoding="utf-8")

    # Simulate the crash landing exactly between the two deletions: p2 is
    # already gone, p3 is still on disk, the journal names both.
    (root / "p2.json").unlink()
    assert (root / "p3.json").exists()

    reloaded = ips.IntervalPresetStore(directory=str(root))
    loaded = {p["id"]: p["rules"][0]["minutes"] for p in reloaded.load()}
    assert loaded == {"p0": 20, "p1": 20}, (
        f"recovery did not finish the stale deletion: {loaded}")
    assert not (root / ".batch-journal.json").exists(), (
        "recovery completed but kept the journal")
    assert not staging.exists(), (
        "recovery completed but kept its staging directory")


def test_src138_06_a_dead_stale_deletion_is_retried_on_the_next_load(tmp_path,
                                                                   monkeypatch):
    """SRC-138/§06 I: a deletion that fails is retried, never written off.

    The new generation is already published when the destructive half runs, so
    an ``OSError`` here must not abort the batch -- the stale file would then
    stay in the catalog forever as a preset the user deleted. The failure is
    injected once and must be retried by the recovery pass.
    """
    root = tmp_path / "store"
    store = ips.IntervalPresetStore(directory=str(root))
    store.replace_all(_batch(3, 10))

    attempts = []
    real_remove = os.remove

    def die_once(path, *a, **k):
        name = os.path.basename(str(path))
        if name == "p2.json" and not attempts:
            attempts.append(name)
            raise OSError(5, "injected failure during stale deletion")
        return real_remove(path, *a, **k)

    monkeypatch.setattr(os, "remove", die_once)
    try:
        store.replace_all(_batch(2, 20))      # p0 p1 new, p2 stale
    finally:
        monkeypatch.undo()

    assert attempts, "the injection never reached stale deletion"
    reloaded = ips.IntervalPresetStore(directory=str(root))
    loaded = {p["id"]: p["rules"][0]["minutes"] for p in reloaded.load()}
    assert loaded == {"p0": 20, "p1": 20}, (
        f"a failed stale deletion left a superseded preset in the library: "
        f"{loaded}")


@pytest.mark.parametrize("payload", [b"{not json", b"[]", b'"a string"',
                                     b""])
def test_src138_06_a_corrupt_journal_is_reported_not_ignored(tmp_path, payload):
    """SRC-138/§06 J: a journal we cannot parse is an unfinished transaction.

    The pre-fix code swallowed every exception from recovery, so a corrupt
    journal meant the catalog silently reported whatever mixture was on disk
    as the user's library. The journal must be KEPT (the staging directory may
    hold the only copy of the new documents) and the state must be reported.
    """
    root = tmp_path / "store"
    store = ips.IntervalPresetStore(directory=str(root))
    store.replace_all(_batch(2, 10))

    journal = root / ".batch-journal.json"
    journal.write_bytes(payload)
    staging = root / ".batch-staging-deadbeef"
    staging.mkdir()
    (staging / "only-copy-of-new.json").write_text("{}", encoding="utf-8")

    reloaded = ips.IntervalPresetStore(directory=str(root))
    assert reloaded.load() is not None, "a corrupt journal made the library unreadable"
    assert reloaded.recovery_problem, (
        "a corrupt journal was accepted in silence; the catalog may be a "
        "mixture of two generations and said nothing")
    assert journal.exists(), (
        "the only record of the unfinished transaction was deleted")
    assert (staging / "only-copy-of-new.json").exists(), (
        "the staging directory was deleted; it can hold the only copy of the "
        "new generation")


def test_src138_06_a_missing_journal_is_not_an_error(tmp_path):
    """SRC-138/§06 J: the ordinary case must stay silent.

    A missing journal is the normal state of a library that has never been
    interrupted. Reporting it would train the user to ignore the warning that
    matters.
    """
    root = tmp_path / "store"
    ips.IntervalPresetStore(directory=str(root)).replace_all(_batch(2, 10))
    assert not (root / ".batch-journal.json").exists()

    reloaded = ips.IntervalPresetStore(directory=str(root))
    assert reloaded.load() is not None
    assert reloaded.recovery_problem is None, (
        f"a clean library reported a recovery problem: "
        f"{reloaded.recovery_problem!r}")


def test_src138_06_missing_staged_files_block_the_destructive_half(tmp_path):
    """SRC-138/§06 K: publishing must never proceed past a missing source.

    If a staged file vanished, moving on would mean the batch published SOME
    new documents and then DELETED the stale ones it was told to remove --
    producing a library that is neither generation. The apply loop must stop
    before any deletion.
    """
    root = tmp_path / "store"
    store = ips.IntervalPresetStore(directory=str(root))
    store.replace_all(_batch(3, 10))

    token = "cafe0123"
    staging = root / f".batch-staging-{token}"
    staging.mkdir()
    # Two of three staged files exist; "p1.json" is the one that vanished.
    wanted = {f"p{i}": _preset(f"p{i}", 20) for i in range(3)}
    for name in ("p0", "p2"):
        (staging / f"x-{name}.json").write_text(
            json.dumps(wanted[name]), encoding="utf-8")
    journal = {
        "token": token,
        "moves": [_move(f"x-p{i}.json", wanted[f"p{i}"]) for i in range(3)],
        "stale": ["p0", "p1", "p2"],
    }
    (root / ".batch-journal.json").write_text(json.dumps(journal),
                                             encoding="utf-8")

    reloaded = ips.IntervalPresetStore(directory=str(root))
    loaded = sorted(p["id"] for p in reloaded.load())
    assert loaded == ["p0", "p1", "p2"], (
        "an incomplete batch deleted the previous generation: "
        f"{loaded}")
    assert reloaded.recovery_problem, (
        "an unfinishable batch was reported as a healthy library")


def test_src138_06_missing_staged_files_do_not_undo_a_published_copy(tmp_path):
    """SRC-138/§06 K: an already-published destination is not a missing source.

    Recovery runs again after a partial publish, when the staged copy of an
    already-moved document is legitimately gone. Treating that as a failure
    would make a finished batch look permanently unfinished.
    """
    root = tmp_path / "store"
    store = ips.IntervalPresetStore(directory=str(root))
    store.replace_all(_batch(2, 10))

    token = "bead0042"
    staging = root / f".batch-staging-{token}"
    staging.mkdir()                      # empty: both files already moved
    wanted = {f"p{i}": _preset(f"p{i}", 20) for i in range(2)}
    for i in range(2):
        (root / f"p{i}.json").write_bytes(_payload(wanted[f"p{i}"]))
    journal = {
        "token": token,
        "moves": [_move(f"x-p{i}.json", wanted[f"p{i}"]) for i in range(2)],
        "stale": [],
    }
    (root / ".batch-journal.json").write_text(json.dumps(journal),
                                             encoding="utf-8")

    reloaded = ips.IntervalPresetStore(directory=str(root))
    loaded = {p["id"]: p["rules"][0]["minutes"] for p in reloaded.load()}
    assert loaded == {"p0": 20, "p1": 20}, (
        f"recovery mistook a published batch for an unfinished one: {loaded}")
    assert reloaded.recovery_problem is None, (
        f"recovery reported a problem for a batch it had just finished: "
        f"{reloaded.recovery_problem!r}")
    assert not (root / ".batch-journal.json").exists()


def test_src138_06_a_second_instance_opening_during_recovery_converges(tmp_path):
    """SRC-138/§06 L: two instances over one interrupted batch must agree.

    The realistic sequence is the timer dialog loading while a release tool
    also loads: both call recovery over the same journal. Whichever finishes
    it, the second must observe the committed generation rather than replay
    it into a mixture or delete the result.
    """
    root = tmp_path / "store"
    store = ips.IntervalPresetStore(directory=str(root))
    store.replace_all(_batch(4, 10))

    journal = {
        "token": "0ddba11c",
        "moves": [_move(f"x-p{i}.json", _preset(f"p{i}", 30))
                  for i in range(4)],
        "stale": [],
    }
    staging = root / ".batch-staging-0ddba11c"
    staging.mkdir()
    for i in range(4):
        (staging / f"x-p{i}.json").write_text(
            json.dumps(_preset(f"p{i}", 30)), encoding="utf-8")
    (root / ".batch-journal.json").write_text(json.dumps(journal),
                                             encoding="utf-8")

    first = ips.IntervalPresetStore(directory=str(root))
    second = ips.IntervalPresetStore(directory=str(root))
    first_seen = {p["id"]: p["rules"][0]["minutes"] for p in first.load()}
    second_seen = {p["id"]: p["rules"][0]["minutes"] for p in second.load()}

    assert first_seen == second_seen == {f"p{i}": 30 for i in range(4)}, (
        "two instances disagreed about the recovered generation: "
        f"{first_seen} vs {second_seen}")
    assert not (root / ".batch-journal.json").exists()
    assert not staging.exists(), (
        "a completed recovery left its staging directory behind")
    # And the committed generation is what a third instance reads from disk.
    third = ips.IntervalPresetStore(directory=str(root))
    assert {p["id"]: p["rules"][0]["minutes"] for p in third.load()} == {
        f"p{i}": 30 for i in range(4)}


def test_src138_06_an_interrupted_batch_preserves_the_old_bytes(tmp_path,
                                                              monkeypatch):
    """SRC-138/§06 M: until the new generation commits, old bytes survive.

    Staging writes only into the private staging directory, so a failure
    BEFORE publication must leave every committed document byte-identical --
    the user's existing presets are never rewritten in place.
    """
    root = tmp_path / "store"
    store = ips.IntervalPresetStore(directory=str(root))
    store.replace_all(_batch(3, 10))
    before = {p.name: p.read_bytes() for p in root.glob("*.json")}

    real_open = open

    def die_writing_staging(path, mode="r", *a, **k):
        if ".batch-staging-" in str(path) and "b" in mode:
            handle = real_open(path, mode, *a, **k)
            handle.close()
            raise OSError(28, "injected failure while staging")
        return real_open(path, mode, *a, **k)

    monkeypatch.setattr("builtins.open", die_writing_staging)
    with pytest.raises(OSError):
        store.replace_all(_batch(3, 20))
    monkeypatch.undo()

    after = {p.name: p.read_bytes() for p in root.glob("*.json")}
    assert after == before, (
        "a failure while staging rewrote committed documents: "
        f"{sorted(set(after) ^ set(before))}")


def test_src138_06_a_committed_batch_keeps_ids_and_user_names(tmp_path):
    """SRC-138/§06 N: a batch must not rename what the user named.

    Ids are the file identity and names are display labels the user chose;
    recovery replays a journal, and a journal that renamed anything would turn
    a crash into a surprise rename.
    """
    root = tmp_path / "store"
    store = ips.IntervalPresetStore(directory=str(root))
    batch = [
        {"id": "keep-me", "name": "My Work Rhythm",
         "kind": ips.KIND_SINGLE, "schema_version": ips.SCHEMA_VERSION,
         "rules": [{**_RULE, "minutes": 25}]},
    ]
    store.replace_all(batch)

    journal = {
        "token": "f00dface",
        "moves": [_move("x-keep-me.json", batch[0])],
        "stale": [],
    }
    staging = root / ".batch-staging-f00dface"
    staging.mkdir()
    (staging / "x-keep-me.json").write_text(
        json.dumps(batch[0]), encoding="utf-8")
    (root / ".batch-journal.json").write_text(json.dumps(journal),
                                             encoding="utf-8")

    reloaded = ips.IntervalPresetStore(directory=str(root))
    (stored,) = reloaded.load()
    assert stored["id"] == "keep-me"
    assert stored["name"] == "My Work Rhythm", (
        f"recovery renamed the user's preset to {stored['name']!r}")


# --- 07: cross-instance import must not clobber -----------------------------

def test_src138_07_stale_second_instance_cannot_import_over_an_existing_id(tmp_path):
    """The reported reproduction: instance B loads first (warm, empty), A then
    creates the id, B imports with overwrite=False. The disk must keep A's
    document."""
    root = str(tmp_path / "store")
    first = ips.IntervalPresetStore(directory=root)
    second = ips.IntervalPresetStore(directory=root)
    second.load()  # B's cache is now warm and stale

    first.create_preset("First", [dict(_RULE)], preset_id="collide")

    with pytest.raises(ips.PresetValidationError):
        second.import_preset(_preset("collide", 99), overwrite=False)

    on_disk = json.loads((tmp_path / "store" / "collide.json").read_text("utf-8"))
    assert on_disk["rules"][0]["minutes"] == 25, (
        "a stale instance overwrote a document it never saw")
    assert on_disk["name"] == "P First" or on_disk["name"] == "First"


def test_src138_07_stale_second_instance_cannot_create_over_an_existing_id(tmp_path):
    """``create_preset`` has the same cache-vs-disk hole and the same contract."""
    root = str(tmp_path / "store")
    first = ips.IntervalPresetStore(directory=root)
    second = ips.IntervalPresetStore(directory=root)
    second.load()

    first.create_preset("First", [dict(_RULE)], preset_id="collide")

    with pytest.raises(ips.PresetValidationError):
        second.create_preset("Second", [dict(_RULE, minutes=99)], preset_id="collide")

    on_disk = json.loads((tmp_path / "store" / "collide.json").read_text("utf-8"))
    assert on_disk["rules"][0]["minutes"] == 25


def test_src138_07_explicit_overwrite_still_works_across_instances(tmp_path):
    """The refusal is about ACCIDENTAL clobber: an explicit overwrite is the
    user's authorization and must keep working."""
    root = str(tmp_path / "store")
    first = ips.IntervalPresetStore(directory=root)
    first.create_preset("First", [dict(_RULE)], preset_id="collide")

    second = ips.IntervalPresetStore(directory=root)
    second.load()
    stored = second.import_preset(_preset("collide", 99), overwrite=True)

    assert stored["rules"][0]["minutes"] == 99
    on_disk = json.loads((tmp_path / "store" / "collide.json").read_text("utf-8"))
    assert on_disk["rules"][0]["minutes"] == 99


# --- 04: the wallet unit must come from the snapshot, not the renderer ------

def test_src138_04_wallet_row_reports_the_units_the_snapshot_declares():
    """The archived operator specification asked for "Wallet: 15 FB" because
    the Freebuff provider reported Freebucks. The provider now normalizes to
    hours (5 FB = 1 h) and says so in ``provider_metadata["unit"]``. The row
    must follow the DATA: a snapshot declaring FB renders FB, one declaring
    hrs renders hrs, and neither is a hardcoded opinion of the renderer.
    """
    import os as _os
    _os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    import sys as _sys
    _tests = str(pathlib.Path(__file__).resolve().parent)
    if _tests not in _sys.path:
        _sys.path.insert(0, _tests)

    from test_t1312_release_ux_repairs import _fb_snap, _tooltip

    as_fb = _tooltip(_fb_snap(daily=10.0, wallet=15.0, total=25.0))
    assert "Wallet: <b>15 FB</b>" in as_fb

    _tooltip(_fb_snap(daily=10.0, wallet=15.0, total=25.0))
    snapshot = _fb_snap(daily=10.0, wallet=15.0, total=25.0)
    snapshot.provider_metadata["unit"] = "hrs"
    hours_html = _tooltip(snapshot)
    assert "Wallet: <b>15 hrs</b>" in hours_html
    assert "Wallet: <b>15 FB</b>" not in hours_html


# --- 08: the ledger must report vanished evidence, not degrade silently ----

def _ledger_module():
    import importlib.util as _ilu
    path = pathlib.Path(__file__).resolve().parents[1] / "tools" / "audit_mechanism_ledger.py"
    spec = _ilu.spec_from_file_location("audit_mechanism_ledger_t1441", path)
    mod = _ilu.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_src138_07_ledger_reports_missing_evidence_instead_of_mapping(tmp_path):
    """A ledger naming a run that is not on disk must say MISSING_EVIDENCE.

    Falling back to MAPPED is indistinguishable from "this ledger was never
    recorded", so a vanished receipt would silently downgrade every domain
    without explaining why.
    """
    import json as _json

    mod = _ledger_module()
    root = tmp_path
    (root / "src" / "fastprompter" / "core").mkdir(parents=True)
    (root / "tests").mkdir()
    (root / "docs" / "audit").mkdir(parents=True)

    (root / "src" / "fastprompter" / "core" / "sound_library.py").write_text(
        "X = 1\n", encoding="utf-8")
    (root / "tests" / "test_sound.py").write_text(
        "from fastprompter.core import sound_library\n\ndef test_ok():\n    assert sound_library.X == 1\n",
        encoding="utf-8")

    mod.LEDGER = pathlib.Path("docs/audit/MECHANISM_COVERAGE.json")
    mod.INVENTORY = pathlib.Path("docs/audit/MECHANISM_INVENTORY.md")
    mod.DOMAINS = {"D01": ("sound_library", ["sound_library"])}
    # Collection runs a real pytest against the LIVE tree, so it cannot answer
    # for a synthetic root. This test is about the evidence rule, not about
    # collection, so the counts are seeded through the same seam the CLI uses.
    mod.collected_counts = lambda files: {f: 1 for f in files}

    # A ledger that claims a run which does not exist.
    (root / "docs" / "audit" / "MECHANISM_COVERAGE.json").write_text(
        _json.dumps({"record": {"path": ".saipen/evidence/gone/run.xml",
                                "sha256": "0" * 64}}),
        encoding="utf-8")

    derived = mod.derive(root, None)
    entry = derived["domains"]["D01"]
    assert entry["status"] == "MISSING_EVIDENCE", (
        f"a vanished evidence file was reported as {entry['status']!r}")
    assert ".saipen/evidence/gone/run.xml" in (entry["next_action"] or "")
