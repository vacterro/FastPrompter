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

import dataclasses
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
    ResetOffer,
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
from fastprompter.core.usage_limits.providers._claude_desktop import (
    normalize_organization_id,
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


# Markers that tell a real ``CLAUDE_CONFIG_DIR`` from a stray ``.claude-backup``
# folder. Claude Code writes all of these into whatever home it is pointed at;
# a directory carrying none of them has never been an account.
_HOME_MARKERS = (".credentials.json", ".claude.json", "settings.json",
                 "projects")


def _looks_like_claude_home(path: Path) -> bool:
    """Does this directory carry Claude Code's own fingerprints?"""
    try:
        return any((path / marker).exists() for marker in _HOME_MARKERS)
    except OSError:
        return False


def sibling_config_dirs() -> list[str]:
    """``~/.claude-<name>`` homes — one per extra logged-in account.

    This is the Codex convention applied to Claude: a second account is a
    second ``CLAUDE_CONFIG_DIR``, because the CLI keeps credentials, settings
    and transcripts together under one root. ``~/.claude`` itself is excluded —
    it is the default account, found by :func:`_discover_config_dirs`.
    """
    try:
        root = _home_dir()
    except RuntimeError:
        return []
    try:
        candidates = sorted(p for p in root.glob(".claude-*") if p.is_dir())
    except OSError:
        return []
    return [str(p) for p in candidates if _looks_like_claude_home(p)]


def _account_organization_id(account: AccountRef) -> str | None:
    """Read one account home's non-secret Claude organization identity."""
    try:
        home = Path(account.source_path)
        config_path = (home.parent / ".claude.json"
                       if account.metadata.get("is_default")
                       else home / ".claude.json")
        payload = json.loads(config_path.read_text(encoding="utf-8"))
        oauth = payload.get("oauthAccount") if isinstance(payload, dict) else None
        organization = (oauth.get("organizationUuid")
                        if isinstance(oauth, dict) else None)
        return normalize_organization_id(organization)
    except (OSError, UnicodeError, ValueError, TypeError):
        return None


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
        """The default account, plus one per extra ``CLAUDE_CONFIG_DIR``.

        The default home and the extra ones are NOT symmetrical, and the
        difference is why this is not a plain loop:

        * ``~/.claude`` and ``~/.claude.json`` are two faces of ONE
          installation, collapsed into a single account (returning both used to
          render a phantom second cluster);
         * Claude Desktop's usage sampler is a single process reading a single
           signed-in account; its sample organization id is matched to the
           account home's own organization identity;
        * every non-default account carries ``config_dir``, which the CLI probe
          exports as ``CLAUDE_CONFIG_DIR`` so ``/usage`` answers for THAT
          account instead of the ambient one.
        """
        found = _discover_config_dirs()
        accounts: list[AccountRef] = []
        seen: set[str] = set()

        def add(path: str, kind: str, *, default: bool = False,
                others: list[str] | None = None) -> None:
            key = canonical_path(path)
            if not key or key in seen:
                return
            seen.add(key)
            metadata = {
                "other_paths": list(others or ()),
                "cache_path": str(cache_path_for_dir(key)),
                # Empty for the default account: it is read with the ambient
                # environment, exactly as before this became multi-account.
                "config_dir": "" if default else key,
                "is_default": default,
            }
            if default:
                metadata["desktop_history"] = (self._desktop_history
                                               or desktop_history_path())
            accounts.append(AccountRef(
                provider_id=self.provider_id,
                stable_id=stable_id_for(self.provider_id, key),
                display_name="Claude",
                source_kind=kind,
                source_path=key,
                metadata=metadata,
            ))

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
            others = [canonical_path(p) for p, _k in found[1:]]
            add(str(identity), kind, default=True, others=others)
            seen.update(others)
        # Explicit homes the user typed in settings win over auto-detection,
        # so a relocated account keeps the ordinal it was given.
        for path in self._extra_paths:
            add(path, "configured")
        for path in sibling_config_dirs():
            add(path, "auto_sibling")
        # _desktop_reading needs to distinguish the unambiguous legacy
        # single-account case from a multi-account roster. Keep that context
        # provider-local; no global account registry and no service query.
        account_count = len(accounts)
        accounts = [dataclasses.replace(
            account,
            metadata={**account.metadata,
                      "claude_account_count": account_count},
        ) for account in accounts]
        return accounts

    # -- source 0: Claude Code CLI (best: percentages AND reset times) -----
    @staticmethod
    def _config_dir_for(account: AccountRef) -> str:
        """``CLAUDE_CONFIG_DIR`` for this account's CLI probe.

        Discovery always sets an explicit ``config_dir`` (empty for the
        default account, which is deliberately read with the ambient
        environment). An account built OUTSIDE discovery — a test fixture, or
        a portable install — carries no such key, and falling back to "" there
        made the CLI answer for whatever account the machine happens to be
        signed into, so a caller asking about one home silently received
        another home's percentages. Such an account is asked about its OWN
        home, which is what every other source in this provider already reads
        (:meth:`_bridge_reading` uses ``source_path`).

        The empty (default-account) value gets the same treatment when the
        AMBIENT environment names a different home: "read with the ambient
        environment" is only correct while that environment points at this
        account. A FastPrompter process launched with a foreign
        ``CLAUDE_CONFIG_DIR`` would otherwise report the other account's
        percentages under the default account's name — two gauges showing
        one account.
        """
        metadata = getattr(account, "metadata", None) or {}
        if "config_dir" in metadata:
            config_dir = str(metadata.get("config_dir") or "")
            if config_dir:
                return config_dir
            source = str(getattr(account, "source_path", "") or "")
            ambient = str(os.environ.get("CLAUDE_CONFIG_DIR") or "").strip()
            if (source and ambient
                    and canonical_path(ambient) != canonical_path(source)):
                return source
            return ""
        return str(getattr(account, "source_path", "") or "")

    def _cli_reading(self, deadline: float, now: float,
                     config_dir: str = "") -> dict:
        """``{window: {...}}`` from ``claude -p "/usage"``, or ``{}``.

        ``config_dir`` names the account to ask; empty is the default one.
        """
        if not self._use_cli:
            return {}
        reading = _claude_cli.read_usage(deadline, binary=self._cli_binary,
                                         now=now, config_dir=config_dir)
        if "error" in reading:
            return {}
        return {
            "windows": reading["windows"],
            "captured_at": reading["captured_at"],
            "cache": reading["source"],
            "raw": reading.get("raw"),
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
            # Full cache payload for the defensive campaign scan (T-1360).
            "raw": payload,
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
        sample_org = normalize_organization_id(usage.get("org"))
        account_org = _account_organization_id(account)
        try:
            account_count = int(account.metadata.get("claude_account_count", 1))
        except (TypeError, ValueError):
            account_count = 1
        if sample_org is None:
            # Legacy Desktop history has no owner. It is safe only when this
            # provider has exactly one discovered Claude account.
            if account_count != 1:
                return {}
        elif account_org != sample_org:
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
        bridge = self._bridge_reading(account)
        desktop = {} if self._structured_source else self._desktop_reading(account)

        # Fast path: if the statusline bridge or desktop sampler already holds
        # a fresh reading (< 5 min), skip spawning the 7-second CLI process.
        need_cli = True
        if bridge.get("windows"):
            captured = bridge.get("captured_at")
            if captured and (now - captured) < 300:
                need_cli = False
        elif desktop.get("windows") and desktop.get("fresh"):
            captured = desktop.get("captured_at")
            if captured and (now - captured) < 300:
                need_cli = False

        # An explicit refusal in Claude Code's own transcript beats any
        # percentage: the window is spent until it resets. This is the only
        # directory-walking read here, so it is also the only one that can
        # meaningfully overrun a deadline — skip it rather than blow the sweep.
        #
        # Read BEFORE the CLI probe, not after. ``_cli_reading`` may spend the
        # WHOLE deadline waiting on ``claude -p "/usage"``; running it first
        # left this guard permanently false, so the provider's own refusal
        # verdict was discarded and a refused window was reported as "connect
        # Claude Code" — unavailable instead of spent. Refusals are also the
        # only source of a window with no percentage at all, so they must never
        # depend on another source's leftovers.
        blocks = {}
        if not self._structured_source and time.monotonic() < deadline:
            try:
                blocks = active_quota_blocks(account.source_path, now=now)
            except Exception:
                blocks = {}

        cli = (self._cli_reading(deadline, now, self._config_dir_for(account))
               if need_cli else {})

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
        # Defensive campaign scan (T-1360): run over the FIRST-PARTY payloads
        # this probe actually read. Today's CLI/statusline payloads carry no
        # campaign metadata, so this is normally empty — the point is that a
        # future payload that does carry offers needs no schema change here
        # and can never be misread (availability must be explicit).
        campaign_offers: list[ResetOffer] = []
        seen_campaigns: set[tuple] = set()
        for reading in (cli, bridge, desktop):
            raw = reading.get("raw") if isinstance(reading, dict) else None
            for offer in _campaign_offers(raw, account, now):
                signature = (offer.source, offer.title,
                             offer.target_kind, offer.expires_at_epoch)
                if signature in seen_campaigns:
                    continue
                seen_campaigns.add(signature)
                campaign_offers.append(offer)
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
            reset_offers=tuple(campaign_offers),
        )


# -- manual reset offers: defensive campaign parsing (T-1360) ----------------
# No first-party Claude payload FastPrompter reads today carries reset-offer
# metadata (evidence .saipen/evidence/t1360/claude_reset_source_discovery.json),
# and the CLI is not logged in on this machine to fetch one that might. So
# NOTHING is hard-coded about a vendor campaign schema: this parser recognises
# a generic campaign SHAPE wherever it appears in the payloads the provider
# already reads (the CLI /usage JSON envelope, the status-line cache), and
# only when the vendor states availability EXPLICITLY. null/absent metadata
# is never "available". Redemption is not proven anywhere, so Claude offers
# are never directly activatable — the UI opens Claude's usage page instead.

# Explicit vendor statements that a campaign entry is available. Anything
# else — including null, false, or a missing key — is NOT availability.
_AVAILABLE_STATUSES = frozenset({"available", "active", "granted"})
# Keys whose value may carry the explicit availability marker.
_AVAILABILITY_KEYS = ("available", "redeemable")
# Known non-campaign containers of the two first-party payloads: their
# contents are quota windows and envelopes, never offers.
_KNOWN_NON_CAMPAIGN_KEYS = frozenset({
    "rate_limits", "captured_at", "schema_version", "source", "result",
    "windows", "is_error", "subtype", "type", "session_id", "usage",
    "duration_ms", "duration_api_ms", "total_cost_usd", "num_turns",
    "modelUsage", "permission_denials", "fast_mode_state", "uuid",
})


def _campaign_target_kind(raw) -> str:
    text = str(raw or "").strip().lower()
    if "week" in text:
        return WEEKLY
    if "session" in text or "five" in text or text in ("5h", "5_hour"):
        return FIVE_HOUR
    return text


def _campaign_expiry(raw) -> float | None:
    if isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)):
        value = float(raw)
        if value <= 0:
            return None
        if value > 1e11:
            value /= 1000.0
        return value if 1e9 < value < 1e11 else None
    if isinstance(raw, str):
        return _parse_reset(raw)
    return None


def _campaign_entry_is_available(entry: dict) -> bool:
    for key in _AVAILABILITY_KEYS:
        if entry.get(key) is True:
            return True
    status = entry.get("status")
    return (isinstance(status, str)
            and status.strip().lower() in _AVAILABLE_STATUSES)


def _campaign_offers(payload, account: AccountRef | None = None,
                     now: float | None = None) -> tuple:
    """Campaign-shaped reset offers in a first-party payload, or ``()``.

    Deliberately conservative: a payload names an offer only through an
    explicit availability statement; titles/targets/expiries are read from
    well-known key spellings and DROPPED when malformed. Only the four
    vendor-visible fields ever reach the ResetOffer — no payload passthrough,
    so no credential can ride along even if a future payload embeds one.
    """
    if not isinstance(payload, dict):
        return ()
    offers = []
    for key, value in payload.items():
        if key in _KNOWN_NON_CAMPAIGN_KEYS:
            continue
        entries = value if isinstance(value, list) else [value]
        if not isinstance(value, (list, dict)):
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            if not _campaign_entry_is_available(entry):
                continue
            target_raw = (entry.get("target") or entry.get("reset_type")
                          or entry.get("resetType") or entry.get("window"))
            expires = _campaign_expiry(
                entry.get("expires_at") or entry.get("expiresAt")
                or entry.get("expire_at") or entry.get("expireAt")
                or entry.get("valid_until"))
            title = str(entry.get("title") or entry.get("name")
                        or entry.get("description") or "").strip()
            offers.append(ResetOffer(
                provider_id="claude",
                account_key=account.key if account is not None else "",
                target_kind=_campaign_target_kind(target_raw),
                status="available",
                title=title or "reset",
                expires_at_epoch=expires,
                redeemable=True,
                redeemable_in_fastprompter=False,
                source=f"claude-campaign:{key}"))
    return tuple(offers)


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


def homes_status(extra_paths: list[str] | None = None) -> list[dict]:
    """Every Claude home FastPrompter would turn into an account.

    One dict per home: ``path``, ``kind``, ``is_default``, ``has_credentials``
    and ``bridge_connected``. Purely descriptive — the settings dialog uses it
    to explain a second account that is present but silent, and it must never
    be the thing that decides identity (:meth:`ClaudeProvider.discover_accounts`
    does that).
    """
    provider = ClaudeProvider(extra_paths=list(extra_paths or ()))
    out: list[dict] = []
    for account in provider.discover_accounts():
        path = account.source_path
        try:
            connected = bool(bridge_status(path).get("connected"))
        except Exception:
            connected = False
        out.append({
            "path": path,
            "kind": account.source_kind,
            "is_default": bool(account.metadata.get("is_default")),
            "has_credentials": os.path.isfile(
                os.path.join(path, ".credentials.json")),
            "bridge_connected": connected,
        })
    return out


def account_data_state(snapshot) -> str:
    """``fresh`` / ``stale`` / ``unavailable`` for ONE account's quota data.

    Derived from the service snapshot the gauges already draw, so the
    settings row and the header can never disagree about whether an account
    currently has numbers. A missing snapshot is "unavailable", not zero --
    this provider does not invent quota values.
    """
    if snapshot is None:
        return "unavailable"
    status = getattr(snapshot, "status", "")
    if status == OK:
        return "fresh"
    if status == STALE:
        return "stale"
    return "unavailable"


def accounts_report(accounts, snapshots=None) -> list[dict]:
    """One descriptive row per DISCOVERED Claude account (T-1266 C6).

    ``accounts`` is the service roster (already numbered "Claude 1" /
    "Claude 2"); non-Claude accounts are ignored. ``snapshots`` is the
    service's ``account.key -> UsageSnapshot`` map, so the reported data
    state is the SAME fact the gauges render.

    Purely descriptive and secret-free: the credential file is reported as
    present or absent, never read.
    """
    shots = dict(snapshots or {})
    out: list[dict] = []
    for account in accounts or ():
        if getattr(account, "provider_id", "") != "claude":
            continue
        path = account.source_path
        try:
            bridge = bridge_status(path) if path else {}
        except Exception:
            bridge = {}
        try:
            has_credentials = bool(path) and os.path.isfile(
                os.path.join(path, ".credentials.json"))
        except OSError:
            has_credentials = False
        out.append({
            "key": account.key,
            "name": account.display_name,
            "path": path,
            "kind": account.source_kind,
            "is_default": bool(account.metadata.get("is_default")),
            "config_dir": account.metadata.get("config_dir", ""),
            "has_credentials": has_credentials,
            "bridge_connected": bool(bridge.get("connected")),
            "bridge_has_cache": bool(bridge.get("has_cache")),
            "data_state": account_data_state(shots.get(account.key)),
        })
    return out


def detected_summary(count: int) -> str:
    """"1 Claude account detected" / "2 Claude accounts detected".

    Shown even when the count is one: "how many accounts does this thing
    think I have" is the question the detection UX exists to answer, and
    hiding the answer at one is what made a missing second account
    undiagnosable.
    """
    plural = "" if count == 1 else "s"
    return f"{count} Claude account{plural} detected"

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
            parsed = datetime.datetime.fromisoformat(value)
            # Naive provider output is DEFINED as UTC (quota-reset-time
            # contract). `timestamp()` on a naive value reads it as LOCAL,
            # which moved Claude's reset window by the host's UTC offset.
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=datetime.UTC)
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
