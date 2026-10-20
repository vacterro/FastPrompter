"""Authoritative Claude quota facts recovered from Claude Code transcripts.

The status-line bridge is the only source of *percentages*, and it only fires
when Claude Code actually renders a status line — a Desktop-entrypoint session
never calls it, so a user can have the bridge connected and still see nothing.

Claude Code does, however, journal a structured ``quotaLimits`` block into its
own transcript (``~/.claude/projects/<slug>/<session>.jsonl``) every time the
API refuses a request for quota reasons:

    "quotaLimits": {"status": "rejected", "resetsAt": 1788303000,
                    "rateLimitType": "five_hour", ...}

That is the provider's own verdict: the window is spent until ``resetsAt``.
Nothing here estimates or interpolates a percentage — a refusal means zero
remaining, and an unknown percentage stays unknown.

Reading is bounded on purpose: only the newest transcripts, only their tail,
only lines that mention the field, and the parsed events are cached per
(path, mtime, size) so a 3-minute sweep re-reads nothing that did not change.
"""

from __future__ import annotations

import heapq
import json
import os
import time

# Bounded scan budget. A transcript grows to tens of MB; the quota block we
# need is always among the newest records, so a tail read is both sufficient
# and the only affordable option on a 3-minute timer.
TAIL_BYTES = 256 * 1024
MAX_FILES = 8
MAX_AGE_S = 7 * 24 * 3600
FIELD = "quotaLimits"

# Claude's own window names -> the provider-neutral keys in model.py.
WINDOW_KEYS = {
    "five_hour": "five_hour",
    "fivehour": "five_hour",
    "5h": "five_hour",
    "seven_day": "weekly",
    "sevenday": "weekly",
    "weekly": "weekly",
    "week": "weekly",
    "monthly": "monthly",
    "month": "monthly",
    "thirty_day": "monthly",
    "spend_limit": "spend_limit",
}

WINDOW_MINUTES = {
    "five_hour": 300,
    "weekly": 10080,
    "monthly": 43200,
}

_cache: dict[str, tuple[float, int, list]] = {}


def transcript_root(claude_dir: str | os.PathLike) -> str:
    return os.path.join(str(claude_dir), "projects")


def _epoch(value):
    """Seconds since the epoch from Claude's numeric or ISO reset shapes."""
    if isinstance(value, bool):
        return None
    if isinstance(value, str):
        return _iso_epoch(value)
    if not isinstance(value, (int, float)):
        return None
    value = float(value)
    if value != value or value <= 0:
        return None
    if value > 1e11:          # milliseconds
        value /= 1000.0
    return value if 1e9 < value < 1e11 else None


def _window_key(raw) -> str | None:
    if not isinstance(raw, str):
        return None
    key = raw.strip().lower()
    if not key:
        return None
    return WINDOW_KEYS.get(key, key)


def _tail_lines(path: str, tail_bytes: int = TAIL_BYTES) -> list[str]:
    """The last complete lines of ``path``. Never raises, never loads it all."""
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as handle:
            if size > tail_bytes:
                handle.seek(size - tail_bytes)
            raw = handle.read(tail_bytes + 1)
    except OSError:
        return []
    text = raw.decode("utf-8", errors="replace")
    lines = text.splitlines()
    if size > tail_bytes and lines:
        # The first line is the tail of a record whose head was not read.
        lines = lines[1:]
    return lines


def _events_from_file(path: str) -> list[dict]:
    """Quota events in one transcript's tail, oldest first. Cached by stat."""
    try:
        stat = os.stat(path)
    except OSError:
        return []
    cached = _cache.get(path)
    if cached is not None and cached[0] == stat.st_mtime and cached[1] == stat.st_size:
        return cached[2]
    events: list[dict] = []
    for line in _tail_lines(path):
        if FIELD not in line:
            continue
        try:
            record = json.loads(line)
        except (ValueError, TypeError):
            continue
        if not isinstance(record, dict):
            continue
        quota = record.get(FIELD)
        if not isinstance(quota, dict):
            continue
        key = _window_key(quota.get("rateLimitType"))
        resets_at = _epoch(quota.get("resetsAt"))
        if key is None and resets_at is None:
            continue
        events.append({
            "window": key,
            "status": str(quota.get("status") or "").strip().lower(),
            "resets_at": resets_at,
            "observed_at": _iso_epoch(record.get("timestamp")) or stat.st_mtime,
            "session": str(record.get("sessionId") or "")[:64],
        })
    # A cache entry per transcript is bounded by MAX_FILES worth of live
    # sessions per slug; paths outside every live selection stay until the
    # whole cache is trimmed past its cap.
    if len(_cache) > 64:
        _cache.clear()
    _cache[path] = (stat.st_mtime, stat.st_size, events)
    return events


def _iso_epoch(value):
    if not isinstance(value, str) or not value:
        return None
    try:
        import datetime
        text = value.strip()
        parsed = datetime.datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=datetime.UTC)
        return parsed.timestamp()
    except (ValueError, OverflowError):
        return None


def _top_k(items, limit: int) -> list[tuple[float, str]]:
    """The ``limit`` newest (mtime, path) pairs, newest first.

    A bounded min-heap of the K best, so neither the heap nor the final
    ``sorted`` ever holds the tree: 250 transcripts in one project produce a
    ``limit``-item result and a ``limit``-item sort, never a 250-item one.
    ``items`` is consumed as a stream -- a caller that materialised the pool
    first would defeat the bound, so the caller passes a generator.
    """
    heap: list[tuple[float, str]] = []
    for item in items:
        if len(heap) < limit:
            heapq.heappush(heap, item)
        elif item > heap[0]:
            heapq.heappushpop(heap, item)
    return sorted(heap, reverse=True)


def _eligible_entries(slug_dir, now: float, max_age_s: float):
    """Stream a project slug's eligible (mtime, path) pairs.

    A generator on purpose: the directory's entry list is never materialised,
    each JSONL child costs at most one ``stat``, and an aged-out or vanished
    entry simply never yields, so the caller's heap stays bounded by its limit
    instead of by the slug. An unreadable slug yields nothing rather than
    costing the sweep its answer.
    """
    try:
        with os.scandir(slug_dir) as entries:
            for child in entries:
                if not child.name.endswith(".jsonl"):
                    continue
                try:
                    mtime = child.stat().st_mtime
                except OSError:
                    continue
                if now - mtime > max_age_s:
                    continue
                yield mtime, child.path
    except OSError:
        return


def transcript_inventory(directory: str | os.PathLike, *, now: float | None = None,
                         max_files: int = MAX_FILES,
                         max_age_s: float = MAX_AGE_S) -> dict:
    """The newest ``max_files`` transcripts plus the tree's newest mtime.

    One selection pass answers BOTH questions the provider asks -- which files
    hold refusals, and whether Claude Code ran at all -- because the old code
    walked the whole tree twice per refresh (K=8 for the blocks, K=1 for the
    activity) and sorted every entry it found before slicing ``[:max_files]``.

    Selection is streamed end to end: each slug's eligible entries are yielded
    one at a time into a bounded per-slug top-K heap, and every slug's bounded
    selection is merged into ONE bounded heap for the whole sweep, so the
    transient candidate state never exceeds K items per slug and K items
    overall -- never the tree, never the slugs x K product. Every refresh
    performs exactly one metadata scan (one stat per JSONL entry) and no sort
    ever sees more than the final K items. No transcript is retained between
    refreshes: correctness comes from re-stat'ing on every sweep, not from a
    directory-keyed memo that a moved mtime would defeat.

    Correctness: a transcript's mtime can move while its directory's stamp
    and entry names stay put, so unchanged directory metadata is NOT evidence
    that the transcripts are unchanged -- the previous cache keyed on exactly
    that pair and silently hid an edited transcript that sat outside the
    previous top-K. Each refresh therefore re-stats every transcript and
    selects from the live mtimes; a file that was excluded and then modified
    becomes eligible at the very next refresh, and a removal, aging-out or
    permission loss disappears from the selection at the same refresh.
    """
    now = time.time() if now is None else now
    limit = max(1, int(max_files))
    root = transcript_root(directory)
    try:
        with os.scandir(root) as slug_entries:
            slugs = list(slug_entries)
    except OSError:
        return {"paths": [], "newest_mtime": None}

    merged: list[tuple[float, str]] = []
    newest: float | None = None
    for slug in slugs:
        try:
            if not slug.is_dir():
                continue
        except OSError:
            continue
        selected = _top_k(_eligible_entries(slug.path, now, max_age_s), limit)
        if not selected:
            continue
        newest = selected[0][0] if newest is None else max(newest, selected[0][0])
        for item in selected:
            # one bounded heap for the whole sweep: the merge never grows past
            # the K the answer needs, never slugs x K
            if len(merged) < limit:
                heapq.heappush(merged, item)
            elif item > merged[0]:
                heapq.heappushpop(merged, item)
    selected = sorted(merged, reverse=True)
    paths = [path for _mtime, path in selected]
    return {"paths": paths, "newest_mtime": newest}


def active_quota_blocks(claude_dir: str | os.PathLike, *, now: float | None = None,
                        max_files: int = MAX_FILES,
                        max_age_s: float = MAX_AGE_S,
                        inventory: dict | None = None) -> dict:
    """Windows Claude itself refused, keyed by provider-neutral window key.

    Only refusals whose reset time is still in the future are returned: once
    ``resetsAt`` passes, the window is no longer blocked and reporting it
    would be a lie the moment the clock ticks past it.

    ``inventory`` is the sweep's already-built selection, so a provider that
    also asks about Claude Code activity walks the tree once, not twice.
    """
    now = time.time() if now is None else now
    if inventory is None:
        inventory = transcript_inventory(claude_dir, now=now,
                                         max_files=max_files,
                                         max_age_s=max_age_s)
    blocks: dict[str, dict] = {}
    for path in inventory["paths"]:
        for event in _events_from_file(path):
            if event["status"] != "rejected":
                continue
            resets_at = event["resets_at"]
            if resets_at is None or resets_at <= now:
                continue
            key = event["window"] or "five_hour"
            previous = blocks.get(key)
            if previous is None or event["observed_at"] > previous["observed_at"]:
                blocks[key] = {
                    "window": key,
                    "resets_at": resets_at,
                    "observed_at": event["observed_at"],
                    "duration_minutes": WINDOW_MINUTES.get(key),
                    "source": "claude-code-transcript",
                }
    return blocks


def last_transcript_activity(claude_dir: str | os.PathLike, *,
                             now: float | None = None,
                             max_files: int = MAX_FILES,
                             max_age_s: float = MAX_AGE_S,
                             inventory: dict | None = None) -> float | None:
    """Newest transcript mtime — proof Claude Code ran, whatever it reported.

    ``max_files`` is irrelevant to the answer (the newest file is always the
    newest) but kept so a caller can share one inventory with
    ``active_quota_blocks``.
    """
    if inventory is None:
        inventory = transcript_inventory(claude_dir, now=now,
                                         max_files=max_files,
                                         max_age_s=max_age_s)
    return inventory["newest_mtime"]
