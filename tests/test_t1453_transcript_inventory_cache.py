"""T-1453 — the Claude transcript inventory cache must not hide changes.

The slug cache keyed on ``(directory generation, entry names)`` could not see
a transcript whose mtime moved without its directory stamp moving: an older
transcript edited outside the previous top-K stayed invisible, so a fresh
quota refusal never reached the provider. The same cache retained every JSONL
entry of every slug, so retained memory grew with the tree, not with the
selection.

These tests hold the corrected contract:

* a directory stamp is never evidence about a child file's content -- every
  refresh re-stats the tree and selects with a bounded heap, so an excluded
  transcript that is modified becomes eligible at the very next refresh;
* the selection never retains per-slug inventory state, and the transient
  candidate containers are bounded by the selection, never by the tree;
* the unchanged-file parse cache still prevents re-reading file contents;
* one account root can never inherit another root's answer.

The filesystem is instrumented with a frozen-directory fixture: directory
entries report a stable ``st_mtime_ns``, which is what ext4/NFS do (and what
Windows NTFS only does with a delay), so the stale-key branch is exercised
deterministically instead of depending on host timestamp semantics.
"""

from __future__ import annotations

import json
import os

import pytest

from fastprompter.core.usage_limits.providers import _claude_transcripts as transcripts

FIVE_HOUR = "five_hour"


# --------------------------------------------------------------------------
# frozen-directory fixture
# --------------------------------------------------------------------------

class _FrozenEntry:
    """A DirEntry whose DIRECTORY stat never moves."""

    def __init__(self, entry, stamp_ns):
        self._entry = entry
        self._stamp_ns = stamp_ns

    def __getattr__(self, name):
        return getattr(self._entry, name)

    def is_dir(self, follow_symlinks=True):
        return self._entry.is_dir(follow_symlinks=follow_symlinks)

    def stat(self, follow_symlinks=True):
        stat = self._entry.stat(follow_symlinks=follow_symlinks)
        if not self._entry.is_dir(follow_symlinks=follow_symlinks):
            return stat
        seconds = self._stamp_ns / 1e9
        return os.stat_result((stat.st_mode, stat.st_ino, stat.st_dev,
                               stat.st_nlink, stat.st_uid, stat.st_gid,
                               stat.st_size, seconds, seconds, seconds))


@pytest.fixture
def frozen_dirs(monkeypatch):
    """Directory generations are frozen at first sight; files stay truthful."""
    frozen: dict[str, int] = {}

    class FrozenOs:
        def __getattr__(self, name):
            return getattr(os, name)

        def scandir(self, path="."):
            real = os.scandir(path)

            class _Ctx:
                def __enter__(self):
                    entries = real.__enter__()
                    wrapped = []
                    for entry in entries:
                        if entry.is_dir() and entry.path not in frozen:
                            frozen[entry.path] = entry.stat().st_mtime_ns
                        wrapped.append(_FrozenEntry(entry, frozen.get(entry.path, 0))
                                       if entry.is_dir() else entry)
                    return iter(wrapped)

                def __exit__(self, *exc):
                    real.__exit__(*exc)
                    return False

            return _Ctx()

    monkeypatch.setattr(transcripts, "os", FrozenOs())
    return frozen


@pytest.fixture(autouse=True)
def _fresh_caches():
    transcripts._cache.clear()
    yield
    transcripts._cache.clear()


# --------------------------------------------------------------------------
# fixtures
# --------------------------------------------------------------------------

def _transcript(directory, slug, name="session.jsonl", records=None,
                mtime=None, text=None):
    project = os.path.join(directory, "projects", slug)
    os.makedirs(project, exist_ok=True)
    path = os.path.join(project, name)
    if text is None:
        text = "\n".join(json.dumps(r) for r in (records or [])) + "\n"
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)
    if mtime is not None:
        os.utime(path, (mtime, mtime))
    return path


def _refusal(resets_at, window="five_hour"):
    return {"type": "assistant",
            "quotaLimits": {"status": "rejected", "resetsAt": resets_at,
                            "rateLimitType": window}}


def _oracle_newest(directory, now, max_files):
    """The literal full-ordering selection: every entry, sorted descending."""
    root = transcripts.transcript_root(directory)
    found: list[tuple[float, str]] = []
    for slug in os.listdir(root):
        project = os.path.join(root, slug)
        try:
            names = os.listdir(project)
        except OSError:
            continue
        for name in names:
            if not name.endswith(".jsonl"):
                continue
            path = os.path.join(project, name)
            try:
                mtime = os.path.getmtime(path)
            except OSError:
                continue
            found.append((mtime, path))
    found.sort(reverse=True)
    return [path for _mtime, path in found[:max_files]]


# --------------------------------------------------------------------------
# 1 + 2 -- the false negative: an excluded transcript that is modified
# --------------------------------------------------------------------------

def test_an_excluded_transcript_modified_outside_the_top_k_becomes_newest(
        tmp_path, frozen_dirs):
    now = 1_800_000_000.0
    directory = str(tmp_path / ".claude")
    paths = []
    for index in range(12):
        paths.append(_transcript(directory, "slug", name=f"s{index:02d}.jsonl",
                                 text='{"type":"assistant"}\n',
                                 mtime=now - 1000 + 100 * index))
    first = transcripts.transcript_inventory(directory, now=now, max_files=8)
    assert first["paths"] == paths[::-1][:8]  # the eight newest, newest first

    excluded = paths[0]  # oldest, never selected by the first sweep
    with open(excluded, "w", encoding="utf-8") as handle:
        handle.write('{"type":"assistant"}\n')
    os.utime(excluded, (now + 500, now + 500))

    second = transcripts.transcript_inventory(directory, now=now, max_files=8)
    assert second["paths"][0] == excluded
    assert second["newest_mtime"] == pytest.approx(now + 500)
    assert second["paths"] == _oracle_newest(directory, now, 8)


def test_the_modified_excluded_transcripts_new_refusal_is_reported(
        tmp_path, frozen_dirs):
    now = 1_800_000_000.0
    directory = str(tmp_path / ".claude")
    paths = []
    for index in range(12):
        paths.append(_transcript(directory, "slug", name=f"s{index:02d}.jsonl",
                                 text='{"type":"assistant"}\n',
                                 mtime=now - 1000 + 100 * index))
    assert transcripts.transcript_inventory(directory, now=now, max_files=8)

    excluded = paths[0]
    with open(excluded, "w", encoding="utf-8") as handle:
        handle.write(json.dumps(_refusal(now + 900)) + "\n")
    os.utime(excluded, (now + 500, now + 500))

    inventory = transcripts.transcript_inventory(directory, now=now, max_files=8)
    blocks = transcripts.active_quota_blocks(directory, now=now,
                                             inventory=inventory)
    assert blocks[FIVE_HOUR]["resets_at"] == now + 900
    assert blocks[FIVE_HOUR]["source"] == "claude-code-transcript"


# --------------------------------------------------------------------------
# 2b -- a NEWLY APPENDED transcript's refusal is visible on the next refresh
# --------------------------------------------------------------------------

def test_a_newly_appended_refusal_is_visible(tmp_path, frozen_dirs):
    now = 1_800_000_000.0
    directory = str(tmp_path / ".claude")
    for index in range(10):
        _transcript(directory, "slug", name=f"s{index:02d}.jsonl",
                    text='{"type":"assistant"}\n',
                    mtime=now - 1000 + 10 * index)
    assert transcripts.active_quota_blocks(directory, now=now) == {}

    fresh = _transcript(directory, "slug", name="refused.jsonl",
                        records=[_refusal(now + 900)], mtime=now - 1)
    inventory = transcripts.transcript_inventory(directory, now=now)
    assert inventory["paths"][0] == fresh
    blocks = transcripts.active_quota_blocks(directory, now=now,
                                             inventory=inventory)
    assert blocks[FIVE_HOUR]["resets_at"] == now + 900


# --------------------------------------------------------------------------
# 3 -- unchanged top-K candidates stay reusable (parse level)
# --------------------------------------------------------------------------

def test_unchanged_candidates_are_not_re_read(tmp_path, frozen_dirs):
    now = 1_800_000_000.0
    directory = str(tmp_path / ".claude")
    path = _transcript(directory, "slug", records=[_refusal(now + 600)],
                       mtime=now - 60)
    transcripts.active_quota_blocks(directory, now=now)
    cached = transcripts._cache[path][2]
    assert cached  # a refusal was parsed once

    transcripts.transcript_inventory(directory, now=now)
    assert transcripts._cache[path][2] is cached  # same events, not re-parsed

    blocks = transcripts.active_quota_blocks(directory, now=now)
    assert blocks[FIVE_HOUR]["resets_at"] == now + 600


# --------------------------------------------------------------------------
# 4 -- a modified SELECTED candidate still updates
# --------------------------------------------------------------------------

def test_a_modified_selected_candidate_updates(tmp_path, frozen_dirs):
    now = 1_800_000_000.0
    directory = str(tmp_path / ".claude")
    path = _transcript(directory, "slug", text='{"type":"assistant"}\n',
                       mtime=now - 600)
    assert transcripts.last_transcript_activity(directory, now=now) == \
        pytest.approx(now - 600)
    assert transcripts.active_quota_blocks(directory, now=now) == {}

    with open(path, "w", encoding="utf-8") as handle:
        handle.write(json.dumps(_refusal(now + 900)) + "\n")
    os.utime(path, (now - 5, now - 5))

    inventory = transcripts.transcript_inventory(directory, now=now)
    assert inventory["newest_mtime"] == pytest.approx(now - 5)
    blocks = transcripts.active_quota_blocks(directory, now=now,
                                             inventory=inventory)
    assert blocks[FIVE_HOUR]["resets_at"] == now + 900


# --------------------------------------------------------------------------
# 5 + 6 + 7 -- created, deleted and aged-out files
# --------------------------------------------------------------------------

def test_a_new_file_in_a_known_slug_is_selected(tmp_path, frozen_dirs):
    now = 1_800_000_000.0
    directory = str(tmp_path / ".claude")
    _transcript(directory, "slug", records=[_refusal(now + 600)],
                mtime=now - 3600)
    assert transcripts.transcript_inventory(directory, now=now)["paths"]

    created = _transcript(directory, "slug", name="fresh.jsonl",
                          text='{"type":"assistant"}\n', mtime=now)
    inventory = transcripts.transcript_inventory(directory, now=now)
    assert inventory["paths"][0] == created
    assert inventory["newest_mtime"] == pytest.approx(now)


def test_a_deleted_file_disappears(tmp_path, frozen_dirs):
    now = 1_800_000_000.0
    directory = str(tmp_path / ".claude")
    newest = _transcript(directory, "slug", name="new.jsonl",
                         text='{"type":"assistant"}\n', mtime=now - 5)
    older = _transcript(directory, "slug", name="old.jsonl",
                        text='{"type":"assistant"}\n', mtime=now - 600)
    assert transcripts.transcript_inventory(directory, now=now)["paths"][0] == newest

    os.remove(newest)
    inventory = transcripts.transcript_inventory(directory, now=now)
    assert inventory["paths"] == [older]
    assert inventory["newest_mtime"] == pytest.approx(now - 600)


def test_an_aged_out_file_stops_counting(tmp_path, frozen_dirs):
    now = 1_800_000_000.0
    directory = str(tmp_path / ".claude")
    _transcript(directory, "slug", text='{"type":"assistant"}\n',
                mtime=now - 60)
    assert transcripts.last_transcript_activity(directory, now=now) is not None

    later = now + transcripts.MAX_AGE_S + 120
    inventory = transcripts.transcript_inventory(directory, now=later)
    assert inventory["paths"] == []
    assert inventory["newest_mtime"] is None
    assert transcripts.active_quota_blocks(directory, now=later) == {}


# --------------------------------------------------------------------------
# 8 -- an unreadable slug is isolated
# --------------------------------------------------------------------------

def test_an_inaccessible_slug_is_isolated(tmp_path, frozen_dirs, monkeypatch):
    now = 1_800_000_000.0
    directory = str(tmp_path / ".claude")
    good = _transcript(directory, "good", text='{"type":"assistant"}\n',
                       mtime=now - 60)
    locked = os.path.join(transcripts.transcript_root(directory), "locked")
    os.makedirs(locked, exist_ok=True)

    real_scandir = os.scandir

    def guarded(path="."):
        if os.fspath(path) == locked:
            raise PermissionError(13, "denied")
        return real_scandir(path)

    monkeypatch.setattr(os, "scandir", guarded)
    inventory = transcripts.transcript_inventory(directory, now=now)
    assert inventory["paths"] == [good]


# --------------------------------------------------------------------------
# 9 -- account roots stay isolated
# --------------------------------------------------------------------------

def test_one_account_cannot_inherit_another_accounts_cache(tmp_path, frozen_dirs):
    now = 1_800_000_000.0
    first = str(tmp_path / "acct-one" / ".claude")
    second = str(tmp_path / "acct-two" / ".claude")
    _transcript(first, "slug", name="a.jsonl", text='{"type":"assistant"}\n',
                mtime=now - 10)
    _transcript(second, "slug", name="b.jsonl", text='{"type":"assistant"}\n',
                mtime=now - 20)

    inv_one = transcripts.transcript_inventory(first, now=now, max_files=8)
    inv_two = transcripts.transcript_inventory(second, now=now, max_files=8)
    assert all(path.startswith(str(tmp_path / "acct-one")) for path in inv_one["paths"])
    assert all(path.startswith(str(tmp_path / "acct-two")) for path in inv_two["paths"])
    assert set(inv_one["paths"]).isdisjoint(inv_two["paths"])

    # a later modification in one root cannot move the other root's answer
    refreshed = _transcript(first, "slug", name="c.jsonl",
                           text='{"type":"assistant"}\n', mtime=now)
    inv_one_again = transcripts.transcript_inventory(first, now=now, max_files=8)
    assert inv_one_again["paths"][0] == refreshed
    inv_two_again = transcripts.transcript_inventory(second, now=now, max_files=8)
    assert inv_two_again["paths"] == inv_two["paths"]


# --------------------------------------------------------------------------
# 10 -- transient candidate state is bounded, and nothing is retained
# --------------------------------------------------------------------------

class _HeapProbe:
    """``heapq`` as the transcript module sees it, with size counters.

    Direct instrumentation of the ONLY containers the selection can build:
    every push reports the heap it grew, so the peak recorded here is the
    peak number of candidate items that ever coexisted anywhere in the
    module -- a pool of the tree's entries could not hide from it.
    """

    def __init__(self, base):
        self._base = base
        self.sizes: list[int] = []

    def __getattr__(self, name):
        return getattr(self._base, name)

    def heappush(self, heap, item):
        self.sizes.append(len(heap) + 1)
        return self._base.heappush(heap, item)

    def heappushpop(self, heap, item):
        self.sizes.append(len(heap))
        return self._base.heappushpop(heap, item)


class _StreamProbe:
    """``_top_k`` that records what its caller actually hands it.

    If the caller built the per-slug pool first, the recorded input is a
    materialised list of every entry in the slug; the streaming contract
    requires a lazy stream instead, and the count proves nothing was dropped
    or double-counted on the way in.
    """

    def __init__(self, real):
        self._real = real
        self.materialised: list[str] = []
        self.streamed: list[int] = []

    def __call__(self, items, limit):
        if isinstance(items, (list, tuple, set)):
            self.materialised.append(type(items).__name__)
        seen = 0

        def counted(iterable):
            nonlocal seen
            for item in iterable:
                seen += 1
                yield item

        result = self._real(counted(items), limit)
        self.streamed.append(seen)
        return result


@pytest.fixture
def instrumented(monkeypatch):
    # A subject that selects without any heap is still probed: the wrapper
    # records an empty size list and any real heap call fails loudly, so a
    # pool-building implementation cannot pass by having no heaps at all.
    heap = _HeapProbe(getattr(transcripts, "heapq", None))
    stream = _StreamProbe(transcripts._top_k)
    monkeypatch.setattr(transcripts, "heapq", heap, raising=False)
    monkeypatch.setattr(transcripts, "_top_k", stream)
    return heap, stream


def test_retained_memory_is_bounded_by_the_selection(tmp_path, frozen_dirs,
                                                     instrumented):
    now = 1_800_000_000.0
    directory = str(tmp_path / ".claude")
    for index in range(200):
        _transcript(directory, "slug", name=f"s{index:03d}.jsonl",
                    text='{"type":"assistant"}\n',
                    mtime=now - 1000 + 5 * index)

    heap, stream = instrumented
    inventory = transcripts.transcript_inventory(directory, now=now, max_files=8)
    assert len(inventory["paths"]) == 8

    # No per-slug inventory state is retained at all: the memo that made the
    # retained set grow with the slug is gone, and nothing replaced it.
    assert not hasattr(transcripts, "_slug_cache")
    # the only mutable dicts left in the module are the window-key constants
    # and the per-file event memo; no per-slug inventory state survives
    module_dicts = {name for name, value in vars(transcripts).items()
                    if not name.startswith("__")
                    and isinstance(value, dict)}
    assert module_dicts == {"WINDOW_KEYS", "WINDOW_MINUTES", "_cache"}

    # The transient candidate containers are the heaps: 200 entries in one slug
    # still never produced more than the K the answer needs at once.
    assert heap.sizes and max(heap.sizes) <= 8, heap.sizes
    # And no caller handed _top_k a pool: the 200 entries arrived as a stream.
    assert stream.materialised == []
    assert stream.streamed == [200], stream.streamed


def test_one_slug_of_enormous_size_still_selects_bounded(tmp_path,
                                                         frozen_dirs,
                                                         instrumented):
    """A single project holding 10,000 transcripts is the worst shape for a
    pool: the answer is 8 files, so nothing in between may BE 10,000 items."""
    now = 1_800_000_000.0
    directory = str(tmp_path / ".claude")
    for index in range(10000):
        _transcript(directory, "solo", name=f"s{index:05d}.jsonl",
                    text='{"type":"assistant"}\n',
                    mtime=now - 100000 + 10 * index)

    heap, stream = instrumented
    inventory = transcripts.transcript_inventory(directory, now=now, max_files=8)
    assert len(inventory["paths"]) == 8
    assert inventory["paths"] == _oracle_newest(directory, now, 8)
    assert inventory["newest_mtime"] == pytest.approx(now - 100000 + 10 * 9999)

    # 10,000 entries streamed in; every heap stayed at or below K.
    assert stream.materialised == []
    assert stream.streamed == [10000], stream.streamed
    assert heap.sizes and max(heap.sizes) <= 8, heap.sizes
    assert not hasattr(transcripts, "_slug_cache")


# --------------------------------------------------------------------------
# 11 -- the selection equals a complete-ordering oracle, ties included
# --------------------------------------------------------------------------

def test_the_selection_matches_a_full_ordering(tmp_path, frozen_dirs):
    now = 1_800_000_000.0
    directory = str(tmp_path / ".claude")
    stamps = [now - 60, now - 60, now - 60, now - 30, now - 90, now - 30]
    index = 0
    for slug in ("alpha", "beta", "gamma"):
        for slot in range(2):
            _transcript(directory, slug, name=f"s{slot}.jsonl",
                        text='{"type":"assistant"}\n',
                        mtime=stamps[index % len(stamps)])
            index += 1

    for count in (1, 2, 5, 6, 20):
        assert transcripts.transcript_inventory(
            directory, now=now, max_files=count)["paths"] == \
            _oracle_newest(directory, now, count)


# --------------------------------------------------------------------------
# 12 -- the inventory still writes nothing into the Claude home
# --------------------------------------------------------------------------

def test_the_inventory_writes_nothing_into_the_claude_home(tmp_path, frozen_dirs):
    now = 1_800_000_000.0
    directory = str(tmp_path / ".claude")
    _transcript(directory, "slug", records=[_refusal(now + 600)],
                mtime=now - 60)

    def snapshot():
        seen = {}
        for parent, dirs, files in os.walk(directory):
            for name in sorted(dirs) + sorted(files):
                path = os.path.join(parent, name)
                stamp = os.stat(path)
                seen[path] = (stamp.st_mtime_ns, stamp.st_size)
        return seen

    before = snapshot()
    transcripts.transcript_inventory(directory, now=now)
    transcripts.active_quota_blocks(directory, now=now)
    transcripts.last_transcript_activity(directory, now=now)
    assert snapshot() == before
