"""Claude provider with four independent authoritative sources.

Percentages are never invented here. Every number comes from Anthropic's own
client, and the provider only decides which of them is freshest and how a
refusal overrides a percentage:

0. **Claude Code CLI** (``claude -p "/usage"``) — the best source there is: it
   asks Anthropic's ``/api/oauth/usage`` endpoint and reports every window with
   BOTH its percentage and its reset time. Measured on 2.1.259 it answers
   locally with ``num_turns: 0`` / ``total_cost_usd: 0``, so reading the quota
   spends none of it. Requires the CLI to be installed and logged in.
1. **Claude Code status line** (``~/.claude/fastprompter-rate-limits.json``) —
   the documented ``rate_limits`` block, complete with ``resets_at``. Only
   written while Claude Code actually renders a status line.
2. **Claude Desktop usage sampler**
   (``%APPDATA%/Claude/plan-usage-history.json``) — Desktop records the same
   account's five-hour/seven-day used percentages every ~5 minutes on its own.
   This is what keeps the gauges alive when Claude Code is not running, which
   used to be an indefinite "waiting for first API response". It carries NO
   reset time, which is why the CLI outranks it.
3. **Claude Code transcripts** (``~/.claude/projects/**.jsonl``) — the
   ``quotaLimits`` block Claude Code journals when the API REFUSES a request.
   A refusal is the provider's own verdict: that window is spent until
   ``resetsAt``, so remaining is 0 no matter what a stale percentage says.

There is no prompt scraping, no token estimation, no credential access, and no
interpolation between samples. When every source is silent the provider says
so instead of guessing.
"""

from __future__ import annotations

import datetime
import json
import os
import time
from pathlib import Path

from fastprompter.core.usage_limits.claude_statusline import (
    bridge_status,
    cache_path_for_dir,
)
from fastprompter.core.usage_limits.model import (
    FIVE_HOUR,
    OK,
    STALE,
    UNAVAILABLE,
    WEEKLY,
    AccountRef,
    UsageSnapshot,
    UsageWindow,
    canonical_path,
    stable_id_for,
)
from fastprompter.core.usage_limits.providers import UsageProvider, _claude_cli
from fastprompter.core.usage_limits.providers._claude_desktop import (
    history_path as desktop_history_path,
)
from fastprompter.core.usage_limits.providers._claude_desktop import (
    latest_usage as desktop_latest_usage,
)
from fastprompter.core.usage_limits.providers._claude_transcripts import (
    active_quota_blocks,
    last_transcript_activity,
)

STALE_AFTER_SEC = 15 * 60
# Desktop samples every ~5 minutes while it runs; past this the sampler is
# stopped and the numbers describe a window that may already have rolled.
DESKTOP_STALE_AFTER_SEC = 45 * 60

_WINDOW_MINUTES = {FIVE_HOUR: 300, WEEKLY: 10080, "monthly": 43200}
# Status-line JSON names -> provider-neutral window keys.
_BRIDGE_WINDOWS = (("five_hour", FIVE_HOUR), ("seven_day", WEEKLY),
                   ("spend_limit", "spend_limit"))


def _home_dir() -> Path:
    home = os.environ.get("HOME") or os.environ.get("USERPROFILE")
    if not home:
        raise RuntimeError("could not resolve $HOME / USERPROFILE")
    return Path(home)


def _discover_config_dirs() -> list[tuple[str, str]]:
    """(path, kind) candidates for the Claude installation.

    ``~/.claude.json`` is the root config that records ``oauthAccount``;
    ``~/.claude/`` holds settings and projects. They are two faces of ONE
    installation, not two accounts — returning both used to make the gauges
    render a phantom second cluster. The list is ordered most-authoritative
    first and callers collapse it to a single account.
    """
    try:
        root = _home_dir()
    except RuntimeError:
        return []
    out: list[tuple[str, str]] = []
    claude_dir = root / ".claude"
    if claude_dir.is_dir():
        out.append((str(claude_dir), "config_dir"))
    root_json = root / ".claude.json"
    if root_json.is_file():
        out.append((str(root_json), "config_file"))
    if not out and os.path.isfile(desktop_history_path()):
        # Claude Desktop only: no CLI config on disk, but the account is real
        # and its usage sampler is running. Identity still points at the
        # canonical ~/.claude path so connecting the CLI later keeps the ID.
        out.append((str(claude_dir), "desktop_only"))
    return out


class ClaudeProvider(UsageProvider):
    """Claude provider. Exact percentages only from a client-written file;
    otherwise honest ``UNAVAILABLE``."""

    provider_id = "claude"

    def __init__(self, extra_paths: list[str] | None = None,
                 structured_source: str = "",
                 desktop_history: str = "",
                 use_cli: bool = True,
                 cli_binary: str = ""):
        self._extra_paths = [canonical_path(p) for p in (extra_paths or ())
                             if p]
        # Explicit paths remain useful for portable/test installations.
        self._structured_source = structured_source or ""
        self._desktop_history = desktop_history or ""
        # ``structured_source`` pins the provider to ONE file for tests, so the
        # CLI (which reads the live account) must stay out of those runs.
        self._use_cli = bool(use_cli) and not self._structured_source
        self._cli_binary = cli_binary or ""

    def discover_accounts(self) -> list[AccountRef]:
        found = _discover_config_dirs()
        accounts: list[AccountRef] = []
        seen: set[str] = set()

        # One installation = one account. The most authoritative path becomes
        # the account's identity; the rest ride along as metadata so the
        # tooltip can still show what was found without inflating the count.
        if found:
            primary, kind = found[0]
            # Identity is always ~/.claude, even on a fresh install where
            # only ~/.claude.json exists. Connecting the bridge creates the
            # directory and must not turn the same account into a new ID.
            primary_path = Path(primary)
            identity = (primary_path if primary_path.is_dir()
                        else primary_path.parent / ".claude")
            key = canonical_path(str(identity))
            others = [canonical_path(p) for p, _k in found[1:]]
            seen.add(key)
            seen.update(others)
            accounts.append(AccountRef(
                provider_id=self.provider_id,
                stable_id=stable_id_for(self.provider_id, key),
                display_name="Claude",
                source_kind=kind,
                source_path=key,
                metadata={"other_paths": others,
                          "cache_path": str(cache_path_for_dir(key)),
                          "desktop_history": self._desktop_history
                                             or desktop_history_path()},
            ))
        for p in self._extra_paths:
            if p and p not in seen:
                seen.add(p)
                accounts.append(AccountRef(
                    provider_id=self.provider_id,
                    stable_id=stable_id_for(self.provider_id, p),
                    display_name="Claude",
                    source_kind="configured",
                    source_path=p,
                ))
        return accounts

    # -- source 0: Claude Code CLI (best: percentages AND reset times) -----
    def _cli_reading(self, deadline: float, now: float) -> dict:
        """``{window: {...}}`` from ``claude -p "/usage"``, or ``{}``."""
        if not self._use_cli:
            return {}
        reading = _claude_cli.read_usage(deadline, binary=self._cli_binary,
                                         now=now)
        if "error" in reading:
            return {}
        return {
            "windows": reading["windows"],
            "captured_at": reading["captured_at"],
            "cache": reading["source"],
        }

    # -- source 1: Claude Code status-line cache --------------------------
    def _bridge_reading(self, account: AccountRef) -> dict:
        """``{window: {...}}`` + ``captured_at`` from the status-line cache."""
        if self._structured_source:
            cache_path = Path(self._structured_source)
        else:
            try:
                if not bridge_status(account.source_path)["connected"]:
                    return {"error": ("bridge_not_connected",
                                      "connect Claude Code in Clock settings")}
            except Exception:
                return {"error": ("invalid_claude_settings",
                                  "Claude settings are unreadable")}
            cache_path = Path(account.metadata.get("cache_path")
                              or cache_path_for_dir(account.source_path))
        try:
            payload = json.loads(cache_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {"error": ("waiting_for_statusline",
                              "connect Claude Code, then send one prompt")}
        except (OSError, json.JSONDecodeError):
            return {"error": ("invalid_statusline_cache",
                              "Claude limit cache is unreadable")}
        if not isinstance(payload, dict) or payload.get("schema_version") != 1:
            return {"error": ("invalid_statusline_cache",
                              "Claude limit cache has an unknown format")}
        rate_limits = payload.get("rate_limits")
        if not isinstance(rate_limits, dict):
            return {"error": ("missing_rate_limits",
                              "Claude has not supplied rate limits yet")}
        windows = {}
        for source_key, window_key in _BRIDGE_WINDOWS:
            bucket = rate_limits.get(source_key)
            if not isinstance(bucket, dict):
                continue
            used = bucket.get("used_percentage")
            if isinstance(used, bool) or not isinstance(used, (int, float)):
                continue
            used = max(0.0, min(100.0, float(used)))
            windows[window_key] = {
                "used": used,
                "resets_at": _parse_reset(bucket.get("resets_at")),
            }
        if not windows:
            return {"error": ("missing_rate_limits",
                              "Claude has not supplied readable limits yet")}
        captured_at = payload.get("captured_at")
        return {
            "windows": windows,
            "captured_at": (float(captured_at)
                            if isinstance(captured_at, (int, float)) else None),
            "cache": str(cache_path),
        }

    # -- source 2: Claude Desktop usage sampler ---------------------------
    def _desktop_reading(self, account: AccountRef) -> dict:
        path = (self._desktop_history
                or account.metadata.get("desktop_history")
                or desktop_history_path())
        usage = desktop_latest_usage(path=path,
                                     fresh_window_s=DESKTOP_STALE_AFTER_SEC)
        if not usage:
            return {}
        return {
            "windows": {key: {"used": used, "resets_at": None}
                        for key, used in usage["windows"].items()},
            "captured_at": usage["sampled_at"],
            "cache": usage["path"],
            "fresh": usage["fresh"],
        }

    def probe(self, account: AccountRef, deadline: float) -> UsageSnapshot:
        now = time.time()
        cli = self._cli_reading(deadline, now)
        bridge = self._bridge_reading(account)
        desktop = {} if self._structured_source else self._desktop_reading(account)
        # An explicit refusal in Claude Code's own transcript beats any
        # percentage: the window is spent until it resets. This is the only
        # directory-walking read here, so it is also the only one that can
        # meaningfully overrun a deadline — skip it rather than blow the sweep.
        blocks = {}
        if not self._structured_source and time.monotonic() < deadline:
            try:
                blocks = active_quota_blocks(account.source_path, now=now)
            except Exception:
                blocks = {}

        readings = [r for r in (cli, bridge, desktop) if r.get("windows")]
        if not readings and not blocks:
            code, summary = bridge.get(
                "error", ("missing_rate_limits",
                          "Claude has not supplied rate limits yet"))
            if not self._structured_source and _claude_ran_recently(account, now):
                summary = (f"{summary} — Claude Code ran recently but reported "
                           "no quota data")
            return _unavailable(account, code, summary)

        # Freshest percentage source wins; the others only fill gaps, so a
        # 6-hour-old bridge cache can never overwrite a 5-minute-old sample.
        # The CLI is asked first and stamped with the current time, so when it
        # answers it also wins — as it should: it is the only source that
        # carries the reset time together with the percentage.
        readings.sort(key=lambda r: r.get("captured_at") or 0.0, reverse=True)
        merged: dict[str, dict] = {}
        for reading in readings:
            source = reading["cache"]
            captured_at = reading.get("captured_at")
            for key, value in reading["windows"].items():
                slot = merged.setdefault(key, {})
                if "used" not in slot:
                    slot["used"] = value["used"]
                    slot["captured_at"] = captured_at
                    slot["source"] = source
                if slot.get("resets_at") is None and value.get("resets_at"):
                    slot["resets_at"] = value["resets_at"]

        # A refusal contributes its window even when no percentage exists for
        # it: "blocked until 01:50" is real, actionable state.
        for key, block in blocks.items():
            slot = merged.setdefault(key, {})
            slot["blocked"] = True
            slot["resets_at"] = block["resets_at"]
            slot.setdefault("captured_at", block["observed_at"])
            slot["source"] = block["source"]

        windows = []
        for key in sorted(merged, key=lambda k: (_WINDOW_MINUTES.get(k) or 10**9, k)):
            slot = merged[key]
            blocked = bool(slot.get("blocked"))
            used = slot.get("used")
            if blocked:
                used, remaining = 100.0, 0.0
            elif isinstance(used, (int, float)):
                remaining = 100.0 - float(used)
            else:
                windows.append(UsageWindow.unavailable(key))
                continue
            windows.append(UsageWindow(
                key=key,
                duration_minutes=_WINDOW_MINUTES.get(key),
                available=True,
                used_percent=float(used),
                remaining_percent=remaining,
                resets_at_epoch=slot.get("resets_at"),
                source=str(slot.get("source") or "claude"),
            ))
        if not any(window.available for window in windows):
            return _unavailable(account, "missing_rate_limits",
                                "Claude has not supplied readable limits yet")

        # Freshness is the NEWEST fact behind any rendered window: a live
        # refusal keeps the snapshot current even when both caches are old.
        newest = max((slot.get("captured_at") or 0.0)
                     for slot in merged.values())
        fetched_at = newest or None
        age = max(0.0, now - newest) if newest else None
        status = OK if (age is not None and age <= STALE_AFTER_SEC) else STALE
        if blocks:
            status = OK
        sources = sorted({str(slot.get("source") or "") for slot in merged.values()
                          if slot.get("source")})
        return UsageSnapshot(
            account=account, status=status, windows=windows,
            fetched_at=fetched_at,
            stale_since=fetched_at if status == STALE else None,
            provider_metadata={
                "capability": "claude-multi-source",
                "strategy": "cli+statusline+desktop-sampler"
                            "+transcript-refusals",
                "sources": sources,
                "blocked_windows": sorted(blocks),
            },
        )


def _claude_ran_recently(account: AccountRef, now: float,
                         window_s: float = 6 * 3600) -> bool:
    """Did Claude Code write a transcript lately? (better error wording)"""
    try:
        seen = last_transcript_activity(account.source_path, now=now)
    except Exception:
        return False
    return seen is not None and (now - seen) <= window_s


def source_status(directory: str | os.PathLike | None = None, *,
                 now: float | None = None) -> dict:
    """What each Claude source can currently prove — for the settings UI.

    Read-only and defensive: a source that raises is reported as unavailable
    rather than breaking the dialog that asks about it.
    """
    now = time.time() if now is None else now
    if directory is None:
        try:
            directory = str(_home_dir() / ".claude")
        except RuntimeError:
            directory = ""
    out = {
        "cli_installed": False,
        "cli_path": "",
        "bridge_connected": False,
        "bridge_has_cache": False,
        "desktop_windows": {},
        "desktop_age_s": None,
        "desktop_fresh": False,
        "blocked_windows": {},
        "claude_code_seen_at": None,
    }
    try:
        from fastprompter.core.usage_limits.cli_tools import resolve_binary
        out["cli_path"] = resolve_binary("claude")
        out["cli_installed"] = bool(out["cli_path"])
    except Exception:
        pass
    try:
        status = bridge_status(directory) if directory else {}
        out["bridge_connected"] = bool(status.get("connected"))
        out["bridge_has_cache"] = bool(status.get("has_cache"))
    except Exception:
        pass
    try:
        usage = desktop_latest_usage(fresh_window_s=DESKTOP_STALE_AFTER_SEC)
        if usage:
            out["desktop_windows"] = dict(usage["windows"])
            out["desktop_age_s"] = usage["age_s"]
            out["desktop_fresh"] = bool(usage["fresh"])
    except Exception:
        pass
    if directory:
        try:
            out["blocked_windows"] = active_quota_blocks(directory, now=now)
        except Exception:
            pass
        try:
            out["claude_code_seen_at"] = last_transcript_activity(directory, now=now)
        except Exception:
            pass
    return out


def _parse_reset(value) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        value = float(value)
        if value <= 0:
            return None
        if value > 1e11:          # milliseconds
            value /= 1000.0
        return value if 1e9 < value < 1e11 else None
    if isinstance(value, str):
        try:
            parsed = datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed.timestamp()
        except (ValueError, OverflowError):
            return None
    return None


def _unavailable(account, code: str, summary: str) -> UsageSnapshot:
    return UsageSnapshot(
        account=account,
        status=UNAVAILABLE,
        windows=[UsageWindow.unavailable(FIVE_HOUR),
                 UsageWindow.unavailable(WEEKLY)],
        error_code=code,
        error_summary=summary,
        provider_metadata={"capability": "claude-multi-source",
                           "strategy": "cli+statusline+desktop-sampler"
                                       "+transcript-refusals"},
    )
