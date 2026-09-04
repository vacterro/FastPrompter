"""Antigravity provider — the CLI states the quota, the journal proves a block.

Antigravity exposes no usage file: its conversation stores are protobuf blobs
and its settings carry only UI state. Two sources exist, and they are very
unequal:

0. **Antigravity CLI** (``agy -p "/usage" --output-format json``) — the real
   answer. It returns every quota pool with an exact remaining fraction and
   reset timestamp, answered locally in print mode (its changelog: "without
   starting an agent turn, spending quota, or leaving a conversation behind";
   measured: the conversation count does not change). Requires ``agy``
   installed and logged in.

   Antigravity bills more than Google's own models: the payload carries one
   group per INDEPENDENT pool — ``Gemini Models`` (Gemini Flash/Pro) and
   ``Claude and GPT models`` (Claude Opus/Sonnet, GPT-OSS) — each with its own
   weekly + 5h pair. Those pools do not constrain each other, so every window
   keeps its ``group`` and gating never crosses pools: a spent Claude weekly
   must not zero a Gemini 5h window the user can still spend.

1. **Brain refusal journal** (``brain/<conv>/.system_generated/messages``) — the
   fallback when the CLI is absent. Antigravity records the backend's own 429
   with the exact reset delay (see :mod:`._antigravity_brain`), which proves a
   block but never a percentage.

So without the CLI this provider reports exactly two honest states: a refusal
whose reset is still ahead (the window is SPENT until that instant, the
provider's own verdict), or ``UNAVAILABLE`` — quota unknown, not free.
Inventing a percentage is precisely what the subsystem forbids.

Right after a block's reset elapses the window is reported once more, so the
model's elapsed-reset pass (``apply_elapsed_resets``) can render it refilled and
the "limit reset" alert can fire. That grace is deliberately short: the refill
is derived from the provider's clock, and once it has been announced FastPrompter
has no way to know what was spent since, so it goes back to saying so.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

from fastprompter.core.usage_limits.model import (
    OK,
    UNAVAILABLE,
    AccountRef,
    UsageSnapshot,
    UsageWindow,
    canonical_path,
    qualified_key,
    stable_id_for,
)
from fastprompter.core.usage_limits.providers import UsageProvider, _antigravity_cli
from fastprompter.core.usage_limits.providers._antigravity_brain import (
    latest_refusal,
)

# The window the refusal journal can speak about: the account-wide quota the
# 429 describes. Its duration is NOT known (the message quotes only the
# remaining delay), which also keeps it out of the cross-window gating logic.
QUOTA = "quota"

# How long after a block's reset the refilled window is still reported, so the
# reset alert has a chance to fire before the state honestly becomes unknown.
# ponytail: a fixed 1h grace, not a setting — nothing has asked for one yet.
RESET_GRACE_S = 3600.0


def _home_dir() -> Path:
    home = os.environ.get("HOME") or os.environ.get("USERPROFILE")
    if not home:
        raise RuntimeError("could not resolve $HOME / USERPROFILE")
    return Path(home)


def default_dir() -> str:
    """Where Antigravity keeps its data — under ``~/.gemini``, not ``~/.antigravity``.

    ``~/.antigravity`` holds only ``argv.json`` and extensions; the brain,
    conversations and settings live in ``~/.gemini/antigravity``.
    """
    try:
        return str(_home_dir() / ".gemini" / "antigravity")
    except RuntimeError:
        return ""


class AntigravityProvider(UsageProvider):
    """CLI-first quota for Antigravity, with the refusal journal as fallback."""

    provider_id = "antigravity"

    def __init__(self, extra_paths: list[str] | None = None,
                 data_dir: str = "", use_cli: bool = True,
                 cli_binary: str = ""):
        self._extra_paths = [canonical_path(p) for p in (extra_paths or ()) if p]
        self._data_dir = data_dir or ""
        self._use_cli = bool(use_cli)
        self._cli_binary = cli_binary or ""

    def _root(self) -> str:
        return canonical_path(self._data_dir or default_dir())

    def discover_accounts(self) -> list[AccountRef]:
        seen: set[str] = set()
        accounts: list[AccountRef] = []

        def add(path: str, kind: str) -> None:
            key = canonical_path(path)
            if not key or key in seen or not os.path.isdir(key):
                return
            seen.add(key)
            accounts.append(AccountRef(
                provider_id=self.provider_id,
                stable_id=stable_id_for(self.provider_id, key),
                display_name="Antigravity",
                source_kind=kind,
                source_path=key,
            ))

        for path in self._extra_paths:
            add(path, "configured")
        add(self._root(), "configured" if self._data_dir else "auto_default")
        return accounts

    def probe(self, account: AccountRef, deadline: float) -> UsageSnapshot:
        if time.monotonic() >= deadline:
            return _unavailable(account, "deadline_exceeded",
                                "no time left in this sweep to read "
                                "Antigravity's quota")
        if self._use_cli:
            snapshot = self._cli_snapshot(account, deadline)
            if snapshot is not None:
                return snapshot
        return self._journal_snapshot(account)

    # -- source 0: the CLI ------------------------------------------------
    def _cli_snapshot(self, account: AccountRef,
                      deadline: float) -> UsageSnapshot | None:
        """Every pool the CLI reported, or None when it could not answer."""
        reading = _antigravity_cli.read_usage(deadline, binary=self._cli_binary)
        if "error" in reading:
            return None
        windows = [
            UsageWindow(
                # Pool-qualified: two pools each report a "weekly", and a
                # window key owns an alert rule, so they must not collide.
                key=qualified_key(row["key"], row["group"]),
                duration_minutes=row["duration_minutes"],
                available=True,
                used_percent=100.0 - row["remaining"],
                remaining_percent=row["remaining"],
                resets_at_epoch=row["resets_at"],
                source=reading["source"],
                group=row["group"],
                group_label=row["group_label"],
            )
            for row in reading["windows"]
        ]
        # Shortest window first within a pool, pools in payload order (e.g. Gemini first,
        # then Claude & GPT), so the gauge draws predictably per the CLI's reporting.
        group_order: dict[str, int] = {}
        for row in reading["windows"]:
            grp = row.get("group")
            if grp and grp not in group_order:
                group_order[grp] = len(group_order)
        windows.sort(key=lambda w: (group_order.get(w.group, 99), w.duration_minutes or 10 ** 9))
        pools = sorted({w.group_label for w in windows if w.group_label})
        return UsageSnapshot(
            account=account, status=OK, windows=windows,
            fetched_at=reading["captured_at"],
            provider_metadata={
                "capability": "antigravity-cli",
                "strategy": "agy-usage",
                "pools": pools,
            },
        )

    # -- source 1: the refusal journal ------------------------------------
    def _journal_snapshot(self, account: AccountRef) -> UsageSnapshot:
        now = time.time()
        try:
            refusal = latest_refusal(account.source_path, now=now)
        except Exception:
            refusal = {}
        if not refusal:
            return _unavailable(
                account, "no_refusal_recorded",
                "install the Antigravity CLI for exact quota — without it "
                "Antigravity only reports a limit when it refuses work")
        resets_at = refusal["resets_at"]
        if resets_at <= now - RESET_GRACE_S:
            return _unavailable(
                account, "quota_unknown",
                "last Antigravity block already reset — install the "
                "Antigravity CLI for exact quota")
        # Spent until resets_at. Once that instant passes, model.resolved_windows
        # renders the same window as refilled (assumed_full) and the reset alert
        # fires; that is why an elapsed timestamp is passed through as-is.
        return UsageSnapshot(
            account=account, status=OK,
            windows=[UsageWindow(
                key=QUOTA,
                duration_minutes=None,
                available=True,
                used_percent=100.0,
                remaining_percent=0.0,
                resets_at_epoch=resets_at,
                source=refusal["source"],
            )],
            fetched_at=refusal["observed_at"],
            provider_metadata={
                "capability": "antigravity-refusals",
                "strategy": "brain-message-429",
                "observed_at": refusal["observed_at"],
            },
        )


def _unavailable(account: AccountRef, code: str, summary: str) -> UsageSnapshot:
    return UsageSnapshot(
        account=account,
        status=UNAVAILABLE,
        windows=[UsageWindow.unavailable(QUOTA)],
        error_code=code,
        error_summary=summary,
        provider_metadata={"capability": "antigravity-refusals",
                           "strategy": "brain-message-429"},
    )


def candidate_data_dirs() -> list[str]:
    """Candidate directories where Antigravity data might reside."""
    home = os.environ.get("HOME") or os.environ.get("USERPROFILE")
    localappdata = os.environ.get("LOCALAPPDATA")
    candidates = []
    if home:
        candidates.append(str(Path(home) / ".gemini" / "antigravity"))
        candidates.append(str(Path(home) / ".antigravity"))
    if localappdata:
        candidates.append(str(Path(localappdata) / "gemini" / "antigravity"))
        candidates.append(str(Path(localappdata) / "antigravity"))
    return [c for c in candidates if os.path.isdir(c)]


def source_status(directory: str | os.PathLike | None = None, *,
                 now: float | None = None) -> dict:
    """What each Antigravity source can currently prove — for the settings UI."""
    now = time.time() if now is None else now
    root = str(directory) if directory is not None else default_dir()
    out = {"data_dir": root, "installed": bool(root) and os.path.isdir(root),
           "candidate_dirs": [],
           "cli_installed": False, "cli_path": "",
           "blocked_until": None, "observed_at": None}
    try:
        from fastprompter.core.usage_limits.cli_tools import resolve_binary
        out["cli_path"] = resolve_binary("antigravity")
        out["cli_installed"] = bool(out["cli_path"])
    except Exception:
        pass
    if not out["installed"]:
        out["candidate_dirs"] = candidate_data_dirs()
        return out
    try:
        refusal = latest_refusal(root, now=now)
    except Exception:
        return out
    if refusal:
        out["observed_at"] = refusal["observed_at"]
        if refusal["resets_at"] > now:
            out["blocked_until"] = refusal["resets_at"]
    return out

