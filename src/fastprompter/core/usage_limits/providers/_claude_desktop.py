"""Claude Desktop's own quota sampler — the reliable percentage source.

Claude Code's status line only runs when Claude Code renders one. A session
started from Claude Desktop never calls it, so the bridge cache can stay empty
for hours while the account is being spent. Claude Desktop, meanwhile, samples
the same account's usage into ``%APPDATA%/Claude/plan-usage-history.json`` on
its own schedule (measured: every ~5 minutes while the app runs):

    {"version": 2, "samples": [
        {"t": 1788330590568, "org": "<uuid>", "u": {"fh": 39, "sd": 20}}, ...]}

``fh`` is the five-hour window's USED percentage, ``sd`` the seven-day one, both
authored by Anthropic's own client. This module reads only the newest sample —
no interpolation, no derived percentage, no history mining.

The file grows without bound (1423 samples / 111 KB after a month), so the read
is size-capped and cached by ``(mtime, size)``: a 3-minute sweep re-reads
nothing that did not change.
"""

from __future__ import annotations

import json
import os
import time

MAX_BYTES = 8 * 1024 * 1024
# Beyond this the sampler is not running (Desktop closed) and the numbers
# describe a window that has probably already rolled over.
FRESH_WINDOW_S = 45 * 60

# Claude Desktop's short keys -> provider-neutral window keys (model.py).
SAMPLE_KEYS = {
    "fh": "five_hour",
    "five_hour": "five_hour",
    "sd": "weekly",
    "seven_day": "weekly",
    "sl": "spend_limit",
    "spend_limit": "spend_limit",
}

_cache: dict[str, tuple[float, int, dict]] = {}


def history_path(appdata: str | os.PathLike | None = None) -> str:
    """Location of Claude Desktop's usage history."""
    if appdata is None:
        appdata = os.environ.get("APPDATA") or ""
        if not appdata:
            home = os.environ.get("HOME") or os.environ.get("USERPROFILE") or ""
            # macOS/Linux Electron layout; harmless when it does not exist.
            appdata = os.path.join(home, "Library", "Application Support")
    return os.path.join(str(appdata), "Claude", "plan-usage-history.json")


def _percentage(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    value = float(value)
    if value != value or value in (float("inf"), float("-inf")):
        return None
    return max(0.0, min(100.0, value))


def _sample_epoch(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    value = float(value)
    if value <= 0:
        return None
    if value > 1e11:          # Desktop writes milliseconds
        value /= 1000.0
    return value if 1e9 < value < 1e11 else None


def _load(path: str) -> dict:
    """Newest sample as ``{"sampled_at": epoch, "windows": {key: used_pct}}``.

    Returns an empty dict when the file is missing, oversized, malformed, or
    carries no readable percentage. Never raises.
    """
    try:
        stat = os.stat(path)
    except OSError:
        return {}
    if stat.st_size > MAX_BYTES:
        return {}
    cached = _cache.get(path)
    if cached is not None and cached[0] == stat.st_mtime and cached[1] == stat.st_size:
        return cached[2]
    try:
        with open(path, encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, ValueError):
        payload = None
    result: dict = {}
    samples = payload.get("samples") if isinstance(payload, dict) else None
    if isinstance(samples, list):
        best_at = None
        best: dict = {}
        # Newest-first: the tail is chronological in practice, but a max scan
        # costs nothing here and does not trust the file's ordering.
        for sample in reversed(samples[-512:]):
            if not isinstance(sample, dict):
                continue
            sampled_at = _sample_epoch(sample.get("t"))
            if sampled_at is None:
                continue
            raw = sample.get("u")
            if not isinstance(raw, dict):
                continue
            windows = {}
            for short, value in raw.items():
                key = SAMPLE_KEYS.get(str(short).strip().lower())
                used = _percentage(value)
                if key and used is not None:
                    windows[key] = used
            if not windows:
                continue
            if best_at is None or sampled_at > best_at:
                best_at, best = sampled_at, windows
        if best_at is not None:
            result = {"sampled_at": best_at, "windows": best,
                      "source": "claude-desktop-usage-history"}
    if len(_cache) > 16:
        _cache.clear()
    _cache[path] = (stat.st_mtime, stat.st_size, result)
    return result


def latest_usage(appdata: str | os.PathLike | None = None, *,
                 path: str | os.PathLike | None = None,
                 now: float | None = None,
                 fresh_window_s: float = FRESH_WINDOW_S) -> dict:
    """Newest Desktop sample plus its age, or ``{}`` when unusable.

    ``fresh`` says whether the sampler is still running. A stale sample is
    still returned (the caller may show it as STALE) but never presented as
    current truth.
    """
    target = str(path) if path is not None else history_path(appdata)
    data = _load(target)
    if not data:
        return {}
    now = time.time() if now is None else now
    age = max(0.0, now - data["sampled_at"])
    return {
        "sampled_at": data["sampled_at"],
        "age_s": age,
        "fresh": age <= fresh_window_s,
        "windows": dict(data["windows"]),
        "source": data["source"],
        "path": target,
    }
