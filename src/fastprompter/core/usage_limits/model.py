"""Provider-neutral usage-limit domain model.

FastPrompter may DISPLAY authoritative limit facts, but must never invent
quota percentages, silently mutate auth, log credentials, or block the GUI
while probing. This module is the shared vocabulary every provider speaks;
the UI consumes only these records.

Stable identity rules:

* An account is identified by ``provider_id + stable_id``, never by its
  ordinal position or display name.
* ``stable_id`` is derived from a canonical (case-normalized, separator-
  normalized, resolved) source path, not from auth data.
* Two accounts are never merged merely because their display names match.
"""

from __future__ import annotations

import dataclasses
import hashlib
import os


@dataclasses.dataclass(frozen=True)
class AccountRef:
    """One discovered/configured account, provider-agnostic."""

    provider_id: str          # "codex" / "claude" / future
    stable_id: str            # provider + canonical identity, NOT ordinal
    display_name: str
    source_kind: str          # auto_default / auto_sibling / env / configured / runtime
    source_path: str = ""     # never a secret
    enabled: bool = True
    metadata: dict = dataclasses.field(default_factory=dict)

    @property
    def key(self) -> str:
        return f"{self.provider_id}:{self.stable_id}"


def canonical_path(path: str) -> str:
    """Normalize a filesystem path for stable identity + dedupe.

    On Windows, case and separators are folded before any comparison so
    ``C:\\Users\\x\\.codex`` and ``c:/users/x/.codex`` are the same account.
    """
    if not path:
        return ""
    try:
        p = os.path.abspath(os.path.expanduser(path))
        if os.name == "nt":
            p = os.path.normcase(p).replace("/", "\\")
        return p
    except Exception:
        return path


def stable_id_for(provider_id: str, source_path: str) -> str:
    """Deterministic stable account id from canonical identity, not ordinal."""
    base = canonical_path(source_path) or provider_id
    if os.name == "nt":
        base = base.lower()
    return hashlib.sha1(f"{provider_id}:{base}".encode("utf-8")).hexdigest()[:16]


@dataclasses.dataclass(frozen=True)
class UsageWindow:
    """One quota window (5h, weekly, provider-specific)."""

    key: str                  # five_hour / weekly / provider-specific
    duration_minutes: int | None
    available: bool
    used_percent: float | None
    remaining_percent: float | None
    resets_at_epoch: float | None = None
    source: str = ""

    @classmethod
    def unavailable(cls, key: str) -> "UsageWindow":
        return cls(key=key, duration_minutes=None, available=False,
                   used_percent=None, remaining_percent=None)


@dataclasses.dataclass(frozen=True)
class UsageSnapshot:
    """One account's answer at one point in time. Never partial truth."""

    account: AccountRef
    status: str               # OK / STALE / UNAVAILABLE / AUTH_REQUIRED / ERROR
    windows: list  # list[UsageWindow]
    plan_type: str | None = None
    fetched_at: float | None = None
    stale_since: float | None = None
    error_code: str = ""
    error_summary: str = ""   # sanitized, no secrets
    provider_metadata: dict = dataclasses.field(default_factory=dict)

    def window(self, key: str) -> UsageWindow | None:
        for w in self.windows:
            if w.key == key:
                return w
        return None


# Status constants
OK = "OK"
STALE = "STALE"
UNAVAILABLE = "UNAVAILABLE"
AUTH_REQUIRED = "AUTH_REQUIRED"
ERROR = "ERROR"

# Window keys
FIVE_HOUR = "five_hour"
WEEKLY = "weekly"
