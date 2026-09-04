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
only lines that mention the field, and cached per (path, mtime, size) so a
3-minute sweep re-reads nothing that did not change.
"""

from __future__ import annotations

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
    """Seconds since the epoch, or None. Accepts ms (Claude has used both)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
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
    # sessions; stale paths are dropped when the directory listing changes.
    if len(_cache) > 64:
        _cache.clear()
    _cache[path] = (stat.st_mtime, stat.st_size, events)
    return events


def _iso_epoch(value):
    if not isinstance(value, str) or not value:
        return None
    try:
        import datetime
        text = value.strip().replace("Z", "+00:00")
        parsed = datetime.datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=datetime.UTC)
        return parsed.timestamp()
    except (ValueError, OverflowError):
        return None


def _recent_transcripts(root: str, now: float, max_files: int,
                        max_age_s: float) -> list[str]:
    try:
        slugs = os.listdir(root)
    except OSError:
        return []
    found: list[tuple[float, str]] = []
    for slug in slugs:
        directory = os.path.join(root, slug)
        try:
            names = os.listdir(directory)
        except OSError:
            continue
        for name in names:
            if not name.endswith(".jsonl"):
                continue
            path = os.path.join(directory, name)
            try:
                mtime = os.path.getmtime(path)
            except OSError:
                continue
            if now - mtime > max_age_s:
                continue
            found.append((mtime, path))
    found.sort(reverse=True)
    return [path for _mtime, path in found[:max_files]]


def active_quota_blocks(claude_dir: str | os.PathLike, *, now: float | None = None,
                        max_files: int = MAX_FILES,
                        max_age_s: float = MAX_AGE_S) -> dict:
    """Windows Claude itself refused, keyed by provider-neutral window key.

    Only refusals whose reset time is still in the future are returned: once
    ``resetsAt`` passes, the window is no longer blocked and reporting it
    would be a lie the moment the clock ticks past it.
    """
    now = time.time() if now is None else now
    root = transcript_root(claude_dir)
    blocks: dict[str, dict] = {}
    for path in _recent_transcripts(root, now, max_files, max_age_s):
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
                             now: float | None = None) -> float | None:
    """Newest transcript mtime — proof Claude Code ran, whatever it reported."""
    now = time.time() if now is None else now
    paths = _recent_transcripts(transcript_root(claude_dir), now, 1, MAX_AGE_S)
    if not paths:
        return None
    try:
        return os.path.getmtime(paths[0])
    except OSError:
        return None
