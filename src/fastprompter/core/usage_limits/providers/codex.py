"""Codex provider: structured usage via ``codex app-server``.

Preserves the proven LIMISAW-derived engine properties:

- spawn ``codex app-server --stdio``;
- per-account child-only ``CODEX_HOME``;
- JSON-RPC ``account/rateLimits/read``;
- map 5h/week by ``windowDurationMins``, never primary/secondary position;
- missing bucket = unavailable, never fake zero;
- no auth token logging/storage;
- per-account failure isolation.

Discovery here only *lists* candidate homes (fast, no subprocess); the
probe itself runs off-thread via :meth:`probe`.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

from fastprompter.core.usage_limits.model import (
    AccountRef,
    FIVE_HOUR,
    OK,
    ERROR,
    WEEKLY,
    UsageSnapshot,
    UsageWindow,
    canonical_path,
    stable_id_for,
)
from fastprompter.core.usage_limits.providers._codex_probe import (  # noqa: F401
    parse_windows,
)
from fastprompter.core.usage_limits.providers import UsageProvider

DURATION_LABELS = {300: FIVE_HOUR, 10080: WEEKLY}


def _home_dir() -> Path:
    home = os.environ.get("HOME") or os.environ.get("USERPROFILE")
    if not home:
        raise RuntimeError("could not resolve $HOME / USERPROFILE")
    return Path(home)


class CodexProvider(UsageProvider):
    """Discovery + probe for Codex CLI accounts."""

    provider_id = "codex"

    def __init__(self, extra_homes: list[str] | None = None):
        self._extra_homes = [canonical_path(p) for p in (extra_homes or ())
                             if p]

    def discover_accounts(self) -> list[AccountRef]:
        try:
            root = _home_dir()
        except RuntimeError:
            return []
        seen: set[str] = set()
        out: list[AccountRef] = []

        def add(path: str, kind: str, name: str) -> None:
            key = canonical_path(path)
            if not key or key in seen:
                return
            if not os.path.isdir(key):
                return
            if not os.path.isfile(os.path.join(key, "auth.json")):
                return   # a dir without auth.json is not a Codex home
            seen.add(key)
            out.append(AccountRef(
                provider_id=self.provider_id,
                stable_id=stable_id_for(self.provider_id, key),
                display_name=name,
                source_kind=kind,
                source_path=key,
            ))

        # Explicit configured homes first.
        for p in self._extra_homes:
            add(p, "configured", os.path.basename(p.rstrip("\\/")) or "Codex")
        # Explicit env override.
        env_home = os.environ.get("CODEX_HOME")
        if env_home:
            add(env_home, "env", "Codex")
        # Default home.
        add(str(root / ".codex"), "auto_default", "Codex")
        # Sibling homes.
        try:
            siblings = sorted(p for p in root.glob(".codex-*") if p.is_dir())
        except Exception:
            siblings = []
        for d in siblings:
            add(str(d), "auto_sibling",
                d.name.replace(".codex-", "").replace("_", " ").title())
        return out

    def probe(self, account: AccountRef, deadline: float) -> UsageSnapshot:
        from fastprompter.core.usage_limits.providers._codex_probe import (
            probe_codex_home,
        )

        try:
            result = probe_codex_home(account.source_path, deadline=deadline)
        except Exception as exc:
            return UsageSnapshot(
                account=account, status=ERROR,
                windows=[UsageWindow.unavailable(FIVE_HOUR),
                         UsageWindow.unavailable(WEEKLY)],
                error_code="probe_exception",
                error_summary=f"{type(exc).__name__}: {str(exc)[:80]}",
            )

        if result is None:
            return UsageSnapshot(
                account=account, status=ERROR,
                windows=[UsageWindow.unavailable(FIVE_HOUR),
                         UsageWindow.unavailable(WEEKLY)],
                error_code="deadline_exceeded",
                error_summary="probe exceeded its hard deadline",
            )

        ok = result.get("ok", False)
        if not ok:
            return UsageSnapshot(
                account=account, status=ERROR,
                windows=[UsageWindow.unavailable(FIVE_HOUR),
                         UsageWindow.unavailable(WEEKLY)],
                error_code="probe_failed",
                error_summary=str(result.get("error") or "probe failed")[:120],
            )

        windows = [
            _as_window(FIVE_HOUR, result.get("five_hour")),
            _as_window(WEEKLY, result.get("weekly")),
        ]
        return UsageSnapshot(
            account=account, status=OK, windows=windows,
            plan_type=result.get("plan_type"),
            fetched_at=result.get("fetched_at"),
            provider_metadata={"source": "codex app-server account/rateLimits/read"},
        )


def _as_window(key: str, bucket) -> UsageWindow:
    if not isinstance(bucket, dict) or not bucket.get("available"):
        return UsageWindow.unavailable(key)
    used = bucket.get("used_percent")
    rem = bucket.get("remaining_percent")
    return UsageWindow(
        key=key,
        duration_minutes=bucket.get("window_duration_mins"),
        available=True,
        used_percent=used if isinstance(used, (int, float)) else None,
        remaining_percent=rem if isinstance(rem, (int, float)) else None,
        resets_at_epoch=_epoch(bucket.get("resets_at")),
        source="app-server",
    )


def _epoch(iso):
    if not iso:
        return None
    try:
        import datetime as _dt
        t = _dt.datetime.fromisoformat(str(iso))
        if t.tzinfo is None:
            t = t.replace(tzinfo=_dt.datetime.now().astimezone().tzinfo)
        return t.timestamp()
    except Exception:
        return None
