"""Authoritative Antigravity quota facts recovered from its own brain messages.

Antigravity (Google's agent IDE, data under ``~/.gemini/antigravity``) publishes
no usage API and no percentage sampler. Its conversation stores are protobuf
blobs, ``app_storage.json`` carries only UI state, and nothing on disk says how
much quota is left.

What it DOES write, verbatim, is the server's own refusal. Every time the model
backend rejects work for quota reasons, Antigravity journals a system message
into ``~/.gemini/antigravity/brain/<conversation>/.system_generated/messages/
<id>.json``::

    {"timestamp": "2026-08-22T10:48:59Z", "sender": "system",
     "content": "... RESOURCE_EXHAUSTED (code 429): Individual quota reached.
                 Please upgrade your subscription to increase your limits.
                 Resets in 81h17m43s."}

That is the provider's own verdict: quota is spent until ``timestamp + 81h17m``.
Nothing here estimates a percentage — a refusal means zero remaining, and an
absent refusal means unknown, never "free".

Reading is bounded on purpose: only recent conversations, only their message
directory, only files that mention the marker, and cached per (directory mtime,
entry count) so a 3-minute sweep re-reads nothing that did not change.
"""

from __future__ import annotations

import json
import os
import re
import time

# Bounded scan budget. A machine accumulates hundreds of conversations (393
# here); a refusal that still matters is always in a recently touched one.
MAX_AGE_S = 7 * 24 * 3600
MAX_DIRS = 16
MAX_FILES_PER_DIR = 200
MARKER = "RESOURCE_EXHAUSTED"

_RESET_RE = re.compile(
    r"Resets? in\s+(?:(\d+)\s*h)?\s*(?:(\d+)\s*m)?\s*(?:(\d+)\s*s)?", re.I)

_cache: dict[str, tuple[float, int, list]] = {}


def brain_root(antigravity_dir: str | os.PathLike) -> str:
    return os.path.join(str(antigravity_dir), "brain")


def _messages_dir(conversation: str) -> str:
    return os.path.join(conversation, ".system_generated", "messages")


def _reset_delay(text: str) -> float | None:
    """Seconds until the reset the message quotes, or None when it quotes none.

    ``Resets in 0s`` and messages with no reset clause at all ("You have
    exhausted your capacity on this model.") are per-model hiccups, not account
    quota windows — they carry no window to render, so they are not events.
    """
    match = _RESET_RE.search(text or "")
    if match is None:
        return None
    hours, minutes, seconds = (int(part) if part else 0
                               for part in match.groups())
    total = hours * 3600.0 + minutes * 60.0 + seconds
    return total or None


def _iso_epoch(value):
    if not isinstance(value, str) or not value:
        return None
    try:
        import datetime
        text = value.strip().replace("Z", "+00:00")
        # Antigravity writes 9 fractional digits; fromisoformat takes 6.
        text = re.sub(r"(\.\d{6})\d+", r"\1", text)
        parsed = datetime.datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=datetime.UTC)
        return parsed.timestamp()
    except (ValueError, OverflowError):
        return None


def _events_from_dir(directory: str, now: float, budget: int) -> list[dict]:
    """Refusal events in one conversation's message directory, cached by stat.

    ``budget`` caps how many message files this directory may open, so a single
    conversation with thousands of them cannot eat the sweep. Newest names are
    tried first only as a heuristic — the names are UUIDs, so the real ordering
    comes from the timestamps inside.
    """
    try:
        stat = os.stat(directory)
        names = os.listdir(directory)
    except OSError:
        return []
    cached = _cache.get(directory)
    if (cached is not None and cached[0] == stat.st_mtime
            and cached[1] == len(names)):
        return cached[2]
    events: list[dict] = []
    opened = 0
    for name in names:
        if opened >= budget:
            break
        if not name.endswith(".json"):
            continue
        path = os.path.join(directory, name)
        try:
            file_stat = os.stat(path)
            if now - file_stat.st_mtime > MAX_AGE_S:
                continue
            with open(path, encoding="utf-8") as handle:
                text = handle.read(64 * 1024)
        except OSError:
            continue
        opened += 1
        if MARKER not in text:
            continue
        try:
            record = json.loads(text)
        except (ValueError, TypeError):
            continue
        if not isinstance(record, dict):
            continue
        content = record.get("content")
        if not isinstance(content, str) or MARKER not in content:
            continue
        delay = _reset_delay(content)
        if delay is None:
            continue
        observed_at = _iso_epoch(record.get("timestamp")) or file_stat.st_mtime
        events.append({
            "observed_at": observed_at,
            "resets_at": observed_at + delay,
            "source": "antigravity-brain-message",
        })
    if len(_cache) > 64:
        _cache.clear()
    _cache[directory] = (stat.st_mtime, len(names), events)
    return events


def _recent_conversations(root: str, now: float, max_dirs: int) -> list[str]:
    try:
        names = os.listdir(root)
    except OSError:
        return []
    found: list[tuple[float, str]] = []
    for name in names:
        directory = _messages_dir(os.path.join(root, name))
        try:
            mtime = os.path.getmtime(directory)
        except OSError:
            continue
        if now - mtime > MAX_AGE_S:
            continue
        found.append((mtime, directory))
    found.sort(reverse=True)
    return [path for _mtime, path in found[:max_dirs]]


def latest_refusal(antigravity_dir: str | os.PathLike, *,
                   now: float | None = None,
                   max_dirs: int = MAX_DIRS,
                   max_files: int = MAX_FILES_PER_DIR) -> dict:
    """The refusal that describes the current quota state, or ``{}``.

    An ACTIVE block (its reset is still in the future) always wins over an
    elapsed one, however recent the latter is: an old expired block must never
    mask a live one. Among equals the newest observation wins.
    """
    now = time.time() if now is None else now
    events: list[dict] = []
    for directory in _recent_conversations(brain_root(antigravity_dir), now,
                                           max_dirs):
        events.extend(_events_from_dir(directory, now, max_files))
    if not events:
        return {}
    active = [event for event in events if event["resets_at"] > now]
    return max(active or events, key=lambda event: event["observed_at"])
