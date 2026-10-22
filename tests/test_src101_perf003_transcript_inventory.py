"""SRC-101 / PERF-003 — one bounded transcript inventory per quota refresh.

The audit measured a 40 project × 250 transcript local tree: the old
``_recent_transcripts`` listed every slug, ``getmtime``d all 10,000
transcripts, appended them all to one list and sorted that list before
slicing ``[:max_files]`` — and ``probe()``/``source_status()`` did the whole
thing twice back to back (once for ``active_quota_blocks`` with K=8, once for
``last_transcript_activity`` with K=1).

These tests hold the replacement to the audit's own clauses:

* the filesystem is instrumented, so the claims are operation counts, not
  wall time on one machine;
* one selection pass covers both questions (refusal blocks + activity);
* the tree's size never becomes the temporary's size (bounded top-K);
* every refresh re-stats every transcript -- a directory stamp is never
  evidence that a child file is unchanged, so freshness is proven per file,
  and the scan stays one metadata pass with bounded heap selection;
* the selected files are exactly what a full descending ordering picks.
"""

from __future__ import annotations

import json
import os
import time

import pytest

from fastprompter.core.usage_limits.providers import _claude_transcripts as transcripts

FIVE_HOUR = "five_hour"
_MAX_AGE_S = transcripts.MAX_AGE_S


# --------------------------------------------------------------------------
# filesystem instrumentation
# --------------------------------------------------------------------------

class _PathProbe:
    """``os.path`` the transcript module can be handed, with counters."""

    def __init__(self, base, probe):
        self._base = base
        self._probe = probe

    def __getattr__(self, name):
        return getattr(self._base, name)

    def getmtime(self, path):
        self._probe.getmtimes.append(os.fspath(path))
        return self._base.getmtime(path)

    def getsize(self, path):
        self._probe.getsizes.append(os.fspath(path))
        return self._base.getsize(path)


class _FsProbe:
    """A recording stand-in for the transcript module's ``os``.

    Only the transcript module sees it (installed in that module's namespace),
    so counting here cannot disturb the rest of the suite. ``listdir`` and
    ``os.path.getmtime`` are counted as well as ``scandir``/``stat``: they are
    exactly the calls the audit measured on the old implementation, and a
    regression back to them has to show up as a count.
    """

    def __init__(self, base=os):
        self._base = base
        self._path = _PathProbe(base.path, self)
        self.scandirs: list[str] = []
        self.stats: list[str] = []
        self.listdirs: list[str] = []
        self.getmtimes: list[str] = []
        self.getsizes: list[str] = []
        self.entry_stats: list[str] = []

    def __getattr__(self, name):
        if name == "path":
            return self._path
        return getattr(self._base, name)

    def scandir(self, path="."):
        self.scandirs.append(os.fspath(path))
        real = self._base.scandir(path)
        entries = list(real)
        real.close()
        probe = self

        class _CountingEntry:
            def __init__(self, entry):
                self._entry = entry

            def __getattr__(self, name):
                return getattr(self._entry, name)

            def stat(self, follow_symlinks=True):
                probe.entry_stats.append(os.fspath(self._entry.path))
                return self._entry.stat(follow_symlinks=follow_symlinks)

        class _Ctx:
            def __enter__(self):
                return iter(_CountingEntry(entry) for entry in entries)

            def __exit__(self, *exc):
                return False

        return _Ctx()

    def stat(self, path, **kwargs):
        self.stats.append(os.fspath(path))
        return self._base.stat(path, **kwargs)

    def listdir(self, path="."):
        self.listdirs.append(os.fspath(path))
        return self._base.listdir(path)

    def reset(self):
        for bucket in ("scandirs", "stats", "listdirs", "getmtimes", "getsizes",
                       "entry_stats"):
            getattr(self, bucket).clear()

    @property
    def transcript_stats(self) -> list[str]:
        return [path for path in self.stats if path.endswith(".jsonl")]


@pytest.fixture
def probe(monkeypatch):
    fs = _FsProbe()
    monkeypatch.setattr(transcripts, "os", fs)
    return fs


@pytest.fixture(autouse=True)
def _fresh_caches():
    """The per-file event cache is a module global, like the old one was.

    The per-slug inventory memo is gone: the selection is streamed straight
    through bounded heaps each refresh, so there is no retained inventory
    state to clear -- and nothing for a stale directory key to hide behind.
    """
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


def _bulk_tree(directory, slugs=40, per_slug=250):
    """The audit's 10,000-transcript reproduction, minus the content."""
    root = transcripts.transcript_root(directory)
    for slug in range(slugs):
        project = os.path.join(root, f"project-{slug:03d}")
        os.makedirs(project, exist_ok=True)
        for index in range(per_slug):
            with open(os.path.join(project, f"session-{index:03d}.jsonl"), "wb"):
                pass
    return root


def _reference_newest(root, now, max_files, max_age_s=_MAX_AGE_S):
    """The literal pre-PERF-003 selection, kept as the equivalence oracle."""
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
            if now - mtime > max_age_s:
                continue
            found.append((mtime, path))
    found.sort(reverse=True)
    return [path for _mtime, path in found[:max_files]]


# --------------------------------------------------------------------------
# one inventory per refresh
# --------------------------------------------------------------------------

def test_a_provider_sweep_builds_one_inventory_not_two(tmp_path, probe):
    """The audited shape: probe() enumerated the same tree twice."""
    from fastprompter.core.usage_limits.providers.claude import ClaudeProvider

    directory = str(tmp_path / ".claude")
    # No refusal anywhere: the sweep falls through to the "Claude Code ran
    # recently but reported no quota data" wording, which is the branch that
    # used to call last_transcript_activity() a second time.
    for slug in ("one", "two"):
        _transcript(directory, slug, text='{"type":"assistant"}\n')

    account = _account(directory)
    snap = ClaudeProvider(use_cli=False,
                          desktop_history=str(tmp_path / "none.json")).probe(
        account, time.monotonic() + 5)

    assert snap.error_summary.endswith("reported no quota data")
    # One root listing plus exactly one listing per project slug -- not two
    # walks of the same two slugs.
    assert len(probe.scandirs) == 3, probe.scandirs
    assert probe.listdirs == []
    assert probe.getmtimes == []


def test_source_status_builds_one_inventory(tmp_path, probe):
    from fastprompter.core.usage_limits.providers.claude import source_status

    now = 1_800_000_000.0
    directory = str(tmp_path / ".claude")
    for slug in ("one", "two", "three"):
        _transcript(directory, slug, records=[_refusal(now + 600)],
                    mtime=now - 60)

    status = source_status(directory, now=now)

    assert status["blocked_windows"][FIVE_HOUR]["resets_at"] == now + 600
    assert status["claude_code_seen_at"] == pytest.approx(now - 60, abs=1)
    assert len(probe.scandirs) == 4, probe.scandirs
    assert probe.listdirs == []
    assert probe.getmtimes == []


def _account(directory):
    from fastprompter.core.usage_limits.model import AccountRef

    return AccountRef(provider_id="claude", stable_id="one",
                      display_name="Claude", source_kind="test",
                      source_path=str(directory))


# --------------------------------------------------------------------------
# the 10,000-transcript scale regression
# --------------------------------------------------------------------------

def test_the_scale_sweep_is_bounded_and_proves_freshness_per_file(tmp_path, probe,
                                                                  monkeypatch):
    now = time.time()
    directory = str(tmp_path / ".claude")
    root = _bulk_tree(directory)

    sorted_lengths: list[int] = []
    real_sorted = sorted

    def recording_sorted(iterable, *args, **kwargs):
        items = list(iterable)
        sorted_lengths.append(len(items))
        return real_sorted(items, *args, **kwargs)

    monkeypatch.setattr(transcripts, "sorted", recording_sorted, raising=False)

    # (1) a fresh walk at K=1 and (2) a fresh walk at K=8 do the same bounded
    # amount of temporary work: the tree is 10,000 files, the lists are not.
    first = transcripts.transcript_inventory(directory, now=now, max_files=1)
    assert (len(probe.scandirs), len(probe.transcript_stats)) == (41, 0)
    assert first["paths"]     # entry metadata only: not one getmtime, not one
    assert probe.getmtimes == []          # separate stat for a known entry

    probe.reset()
    eighth = transcripts.transcript_inventory(directory, now=now, max_files=8)
    assert (len(probe.scandirs), len(probe.transcript_stats)) == (41, 0)
    assert len(eighth["paths"]) == 8

    # (3) the recurring sweep: a file's mtime can move without its directory's
    # stamp or entry names moving, so directory metadata is not evidence that
    # a transcript is unchanged. Every refresh therefore re-stats every
    # transcript exactly once -- 10,000 entry stats for the 10,000-transcript
    # tree -- and selects with bounded heaps. The retained per-slug state is
    # the selection alone (8 per slug), never the entry list.
    probe.reset()
    again = transcripts.transcript_inventory(directory, now=now, max_files=8)
    assert len(probe.scandirs) == 41, probe.scandirs
    assert len(probe.entry_stats) == 10000, len(probe.entry_stats)
    assert probe.transcript_stats == []
    assert probe.getmtimes == []
    assert probe.listdirs == []
    assert again["paths"] == eighth["paths"]
    # No per-slug inventory state is retained at all: the entry lists of 40
    # slugs never survive the refresh that selected from them.
    assert not hasattr(transcripts, "_slug_cache")
    # the only mutable dicts left in the module are the window-key constants
    # and the per-file event memo; no per-slug inventory state survives
    module_dicts = {name for name, value in vars(transcripts).items()
                    if not name.startswith("__")
                    and isinstance(value, dict)}
    assert module_dicts == {"WINDOW_KEYS", "WINDOW_MINUTES", "_cache"}

    # Neither walk ever materialised the tree: every sorted() in the module saw
    # at most K entries (per-slug top-K and the global merge).
    assert sorted_lengths and max(sorted_lengths) <= 8, sorted_lengths

    # And the answers still equal the full-ordering oracle.
    for inventory, count in ((first, 1), (eighth, 8), (again, 8)):
        assert inventory["paths"] == _reference_newest(root, now, count)
    assert first["newest_mtime"] == eighth["newest_mtime"] == again["newest_mtime"]


def test_one_and_eight_candidates_agree_on_activity(tmp_path):
    now = time.time()
    directory = str(tmp_path / ".claude")
    for slug in range(4):
        for index in range(3):
            _transcript(directory, f"p{slug}", name=f"s{index}.jsonl",
                        text='{"type":"assistant"}\n',
                        mtime=now - 10 * (slug * 3 + index))
    newest = now - 10

    assert transcripts.transcript_inventory(
        directory, now=now, max_files=1)["newest_mtime"] == pytest.approx(newest)
    assert transcripts.transcript_inventory(
        directory, now=now, max_files=8)["newest_mtime"] == pytest.approx(newest)
    assert transcripts.last_transcript_activity(
        directory, now=now) == pytest.approx(newest)


# --------------------------------------------------------------------------
# invalidation
# --------------------------------------------------------------------------

def test_a_new_transcript_in_a_known_slug_is_visible_next_refresh(tmp_path):
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


def test_a_modified_candidate_updates_activity_and_refusal(tmp_path, probe):
    """Appending to a file is invisible to every directory timestamp."""
    now = 1_800_000_000.0
    directory = str(tmp_path / ".claude")
    slug_dir = os.path.join(transcripts.transcript_root(directory), "slug")
    path = _transcript(directory, "slug", text='{"type":"assistant"}\n',
                       mtime=now - 600)
    generation = os.stat(slug_dir).st_mtime_ns
    assert transcripts.last_transcript_activity(directory, now=now) == \
        pytest.approx(now - 600)
    assert transcripts.active_quota_blocks(directory, now=now) == {}

    with open(path, "w", encoding="utf-8") as handle:
        handle.write(json.dumps(_refusal(now + 900)) + "\n")
    os.utime(path, (now - 5, now - 5))
    # The directory is untouched, so an implementation keyed on it alone would
    # keep serving the old answer here.
    assert os.stat(slug_dir).st_mtime_ns == generation

    inventory = transcripts.transcript_inventory(directory, now=now)
    assert inventory["newest_mtime"] == pytest.approx(now - 5)
    blocks = transcripts.active_quota_blocks(directory, now=now,
                                             inventory=inventory)
    assert blocks[FIVE_HOUR]["resets_at"] == now + 900


def test_a_deleted_candidate_is_forgotten(tmp_path):
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


def test_a_cached_candidate_that_ages_out_stops_counting(tmp_path):
    now = 1_800_000_000.0
    directory = str(tmp_path / ".claude")
    _transcript(directory, "slug", text='{"type":"assistant"}\n',
                mtime=now - 60)
    assert transcripts.last_transcript_activity(directory, now=now) is not None

    later = now + _MAX_AGE_S + 120
    inventory = transcripts.transcript_inventory(directory, now=later)
    assert inventory["paths"] == []
    assert inventory["newest_mtime"] is None
    assert transcripts.active_quota_blocks(directory, now=later) == {}


def test_a_slug_that_disappears_is_gone_from_the_answer(tmp_path):
    directory = str(tmp_path / ".claude")
    _transcript(directory, "keep", text='{"type":"assistant"}\n')
    gone = _transcript(directory, "gone", text='{"type":"assistant"}\n')
    assert set(transcripts.transcript_inventory(directory)["paths"]) == \
        {os.path.join(str(tmp_path / ".claude" / "projects" / "keep"),
                      "session.jsonl"), gone}

    os.remove(gone)
    os.rmdir(os.path.dirname(gone))
    after = transcripts.transcript_inventory(directory)
    assert len(after["paths"]) == 1
    assert "gone" not in after["paths"][0]
    # nothing is retained about the removed slug either
    # the only mutable dicts left in the module are the window-key constants
    # and the per-file event memo; no per-slug inventory state survives
    module_dicts = {name for name, value in vars(transcripts).items()
                    if not name.startswith("__")
                    and isinstance(value, dict)}
    assert module_dicts == {"WINDOW_KEYS", "WINDOW_MINUTES", "_cache"}


# --------------------------------------------------------------------------
# preserved semantics
# --------------------------------------------------------------------------

def test_selection_matches_a_full_ordering(tmp_path):
    """Ties included: the oracle is the old sort-everything implementation."""
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
    root = transcripts.transcript_root(directory)

    for count in (1, 2, 5, 6, 20):
        assert transcripts.transcript_inventory(
            directory, now=now, max_files=count)["paths"] == \
            _reference_newest(root, now, count)


def test_an_inaccessible_slug_is_isolated(tmp_path, probe, monkeypatch):
    now = 1_800_000_000.0
    directory = str(tmp_path / ".claude")
    good = _transcript(directory, "good", text='{"type":"assistant"}\n',
                       mtime=now - 60)
    locked = os.path.join(transcripts.transcript_root(directory), "locked")
    os.makedirs(locked, exist_ok=True)

    real_scandir = probe.scandir

    def guarded(path="."):
        if os.fspath(path) == locked:
            raise PermissionError(13, "denied")
        return real_scandir(path)

    monkeypatch.setattr(probe, "scandir", guarded)
    inventory = transcripts.transcript_inventory(directory, now=now)
    assert inventory["paths"] == [good]


def test_a_malformed_transcript_cannot_break_the_refusal_read(tmp_path):
    now = 1_800_000_000.0
    directory = str(tmp_path / ".claude")
    _transcript(directory, "slug", name="garbage.jsonl",
                text='{"quotaLimits": \nnot json at all\n', mtime=now - 5)
    _transcript(directory, "slug", name="ok.jsonl",
                records=[_refusal(now + 600)], mtime=now - 60)

    blocks = transcripts.active_quota_blocks(directory, now=now)
    assert set(blocks) == {FIVE_HOUR}
    assert blocks[FIVE_HOUR]["resets_at"] == now + 600
    assert transcripts.last_transcript_activity(directory, now=now) == \
        pytest.approx(now - 5)


def test_a_missing_projects_directory_is_an_empty_inventory(tmp_path, probe):
    directory = str(tmp_path / ".claude")
    os.makedirs(directory)
    assert transcripts.transcript_inventory(directory) == {
        "paths": [], "newest_mtime": None}
    assert transcripts.active_quota_blocks(directory) == {}
    assert transcripts.last_transcript_activity(directory) is None


def test_the_inventory_writes_nothing_into_the_claude_home(tmp_path):
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
