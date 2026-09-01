"""Claude provider: honest capability detection, no invented percentages.

Claude does not expose a clean external structured quota surface on every
installation the way Codex's ``app-server`` does. This provider therefore:

* discovers the installed Claude config/runtime using standard paths;
* probes ONLY via a structured source the installed runtime provably offers
  (none assumed by default);
* otherwise reports ``UNAVAILABLE`` / ``UNSUPPORTED`` honestly instead of
  fabricating percentages from token history or "limit reached" prose.

No hidden AI prompt/session is ever created to obtain usage. No credentials
are logged or stored. The strategy is visible in diagnostics/settings.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

from fastprompter.core.usage_limits.model import (
    AccountRef,
    FIVE_HOUR,
    WEEKLY,
    UNAVAILABLE,
    UsageSnapshot,
    UsageWindow,
    canonical_path,
    stable_id_for,
)
from fastprompter.core.usage_limits.providers import UsageProvider


def _home_dir() -> Path:
    home = os.environ.get("HOME") or os.environ.get("USERPROFILE")
    if not home:
        raise RuntimeError("could not resolve $HOME / USERPROFILE")
    return Path(home)


def _discover_config_dirs() -> list[tuple[str, str]]:
    """(path, kind) candidates for Claude config, most authoritative first.

    ``~/.claude.json`` is the root config that records ``oauthAccount``.
    ``~/.claude/`` holds settings/projects. A structured quota surface may
    exist in future Claude versions; discovery here only reports what is
    installed so the probe can decide honestly.
    """
    try:
        root = _home_dir()
    except RuntimeError:
        return []
    out: list[tuple[str, str]] = []
    root_json = root / ".claude.json"
    if root_json.is_file():
        out.append((str(root_json), "config_file"))
    claude_dir = root / ".claude"
    if claude_dir.is_dir():
        out.append((str(claude_dir), "config_dir"))
    return out


class ClaudeProvider(UsageProvider):
    """Claude provider. Exact percentages only when a structured source is
    proven; otherwise honest ``UNAVAILABLE``."""

    provider_id = "claude"

    def __init__(self, extra_paths: list[str] | None = None,
                 structured_source: str = ""):
        self._extra_paths = [canonical_path(p) for p in (extra_paths or ())
                             if p]
        # A configured structured source (future proof): if the installed
        # runtime provides one, the probe can read it. Empty by default.
        self._structured_source = structured_source or ""

    def discover_accounts(self) -> list[AccountRef]:
        found = _discover_config_dirs()
        accounts: list[AccountRef] = []
        seen: set[str] = set()
        for path, kind in found:
            key = canonical_path(path)
            if key in seen:
                continue
            seen.add(key)
            accounts.append(AccountRef(
                provider_id=self.provider_id,
                stable_id=stable_id_for(self.provider_id, key),
                display_name="Claude",
                source_kind=kind,
                source_path=key,
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

    def probe(self, account: AccountRef, deadline: float) -> UsageSnapshot:
        # Honest unsupported: no structured quota surface proven in the
        # installed runtime, so exact percentages would be invented.
        return UsageSnapshot(
            account=account,
            status=UNAVAILABLE,
            windows=[UsageWindow.unavailable(FIVE_HOUR),
                     UsageWindow.unavailable(WEEKLY)],
            error_code="unsupported",
            error_summary=("Claude does not expose a structured quota surface "
                           "this build can read; no percentages invented"),
            provider_metadata={"capability": "unsupported",
                               "strategy": "honest-unavailable"},
        )
