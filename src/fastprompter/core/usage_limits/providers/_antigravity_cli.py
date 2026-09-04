"""Antigravity quota straight from ``agy -p "/usage"`` — structured and exact.

The Antigravity CLI answers ``/usage`` in print mode without starting an agent
turn (its own changelog: "without starting an agent turn, spending quota, or
leaving a conversation behind"), and ``--output-format json`` returns the
server's own numbers rather than prose::

    {"command": {"name": "usage", "data": {"groups": [
      {"name": "Gemini Models", "buckets": [
        {"id": "gemini-weekly", "window": "weekly",
         "remaining_fraction": 0.681, "reset_time": "2026-09-08T20:06:36Z"},
        {"id": "gemini-5h", "window": "5h",
         "remaining_fraction": 0.096, "reset_time": "2026-09-03T12:41:31Z"}]},
      {"name": "Claude and GPT models", "buckets": [
        {"id": "3p-weekly", "window": "weekly", "remaining_fraction": 0,
         "reset_time": "2026-09-04T16:16:03Z"},
        {"id": "3p-5h", "window": "5h", "disabled": true,
         "remaining_fraction": 1}]}]}}}

Two properties of that payload drive the mapping:

* the groups are INDEPENDENT quota pools ("Within each group, models share a
  weekly limit and a 5-hour limit"), so each window carries its group and
  cross-group gating is refused (see ``UsageWindow.group``);
* a ``disabled`` bucket is not free quota. Antigravity marks the 5h window
  disabled while the pool's weekly one is spent and describes it itself: "You
  have hit your weekly limit, the 5-hour limit does not currently apply." Its
  ``remaining_fraction: 1`` would render as "100% free" on a pool that refuses
  every request, so the window is kept at ZERO remaining instead — the model's
  gating pass then labels it ``blocked by weekly``, which is what the vendor
  says. Dropping it would be the other mistake: the 5-hour limit exists, and
  hiding it makes the pool look like it only has a weekly one.

Nothing is estimated: no bucket, no window.
"""

from __future__ import annotations

import datetime
import json
import re
import time

from fastprompter.core.usage_limits.cli_tools import resolve_binary, run_cli

# Antigravity's window names -> provider-neutral keys (model.py).
_WINDOWS = {"5h": "five_hour", "five_hour": "five_hour",
            "weekly": "weekly", "7d": "weekly",
            "monthly": "monthly", "30d": "monthly"}
_WINDOW_MINUTES = {"five_hour": 300, "weekly": 10080, "monthly": 43200}


def _epoch(value) -> float | None:
    """ISO-8601 (``2026-09-08T20:06:36Z``) or epoch number -> epoch seconds."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        value = float(value)
        if value > 1e11:          # milliseconds
            value /= 1000.0
        return value if 1e9 < value < 1e11 else None
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip().replace("Z", "+00:00")
    text = re.sub(r"(\.\d{6})\d+", r"\1", text)
    try:
        parsed = datetime.datetime.fromisoformat(text)
    except (ValueError, OverflowError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=datetime.UTC)
    return parsed.timestamp()


def _remaining(value) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    value = float(value)
    if value != value:            # NaN
        return None
    return max(0.0, min(100.0, value * 100.0))


def parse_usage_payload(payload) -> list[dict]:
    """Flatten the ``/usage`` JSON into one record per quota window.

    Each record is ``{key, group, group_label, remaining, resets_at,
    duration_minutes, disabled}``. A window the vendor marked ``disabled`` is
    reported with ZERO remaining rather than dropped or believed: it exists, it
    is simply superseded by the longer limit in its own pool right now.

    An unknown window name, or a bucket with no readable fraction, IS dropped —
    a pool that cannot state a number must not be rendered as free.
    """
    if not isinstance(payload, dict):
        return []
    data = (payload.get("command") or {}).get("data")
    groups = data.get("groups") if isinstance(data, dict) else None
    if not isinstance(groups, list):
        return []
    out: list[dict] = []
    for index, group in enumerate(groups):
        if not isinstance(group, dict):
            continue
        label = str(group.get("name") or f"group {index + 1}").strip()
        group_id = re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_") \
            or f"group{index + 1}"
        for bucket in group.get("buckets") or ():
            if not isinstance(bucket, dict):
                continue
            key = _WINDOWS.get(str(bucket.get("window") or "").strip().lower())
            if key is None:
                continue
            disabled = bool(bucket.get("disabled"))
            remaining = _remaining(bucket.get("remaining_fraction"))
            if remaining is None and not disabled:
                continue
            out.append({
                "key": key,
                "group": group_id,
                "group_label": label,
                "remaining": 0.0 if disabled else remaining,
                "resets_at": _epoch(bucket.get("reset_time")),
                "duration_minutes": _WINDOW_MINUTES.get(key),
                "disabled": disabled,
            })
    return out


def read_usage(deadline: float, *, binary: str = "",
               now: float | None = None) -> dict:
    """Run ``agy -p "/usage"`` and return the parsed windows.

    Returns ``{"windows": [...], "captured_at": epoch, "source": str}`` or
    ``{"error": (code, summary)}``. Never raises.
    """
    executable = binary or resolve_binary("antigravity")
    if not executable:
        return {"error": ("cli_not_installed",
                          "Antigravity CLI (agy) not found on PATH")}
    result = run_cli(
        [executable, "-p", "/usage", "--output-format", "json"], deadline)
    if not result["ok"]:
        return {"error": ("cli_failed", f"agy /usage: {result['error']}")}
    try:
        payload = json.loads(result["stdout"])
    except (ValueError, TypeError):
        return {"error": ("cli_bad_output", "agy /usage did not return JSON")}
    if isinstance(payload, dict) and payload.get("status") not in (
            None, "SUCCESS"):
        return {"error": ("cli_failed",
                          f"agy /usage: {str(payload.get('status'))[:60]}")}
    windows = parse_usage_payload(payload)
    if not windows:
        return {"error": ("cli_no_limits",
                          "agy /usage reported no readable quota window")}
    return {
        "windows": windows,
        "captured_at": time.time() if now is None else now,
        "source": "antigravity-cli-usage",
    }
