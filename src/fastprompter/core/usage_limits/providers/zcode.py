"""ZCode (GLM Coding Plan) provider — one authenticated HTTPS read, opt-in.

Every other provider here reads a file the vendor's own client already wrote,
or asks a locally installed CLI. ZCode offers neither: its CLI has no ``/usage``
command and its cached quota lives inside the Electron app's LevelDB, which is
locked while ZCode runs. What it does have is the endpoint the app itself calls
(see :mod:`._zcode_http`), so this provider asks that — and because that is the
only usage source in FastPrompter which leaves the machine, it is the only one
that stays OFF until the user turns it on.

The consequences of that choice, spelled out because a silent network read on a
credential would be exactly the wrong default:

* ``enabled=False`` discovers nothing at all — no account, no row, no request;
* the API key comes from ZCode's own ``config.json`` and is handed to one
  ``Authorization`` header. It never enters a log, a tooltip, an error summary
  or a snapshot; the settings UI is told only *whether* a key exists;
* the destination host must be one of the vendor's own, over HTTPS with the
  certificate verified. ZCode's own env-var endpoint override is deliberately
  not honoured — for a process holding a credential that is a redirection
  primitive, not a feature.

Both windows the plan reports (5-hour prompt pool and weekly quota) count the
same credit meter, so they share one pool: no ``group``, and the model's
ordinary gating correctly zeroes the 5-hour window once the weekly one is spent.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

from fastprompter.core.usage_limits.model import (
    FIVE_HOUR,
    OK,
    UNAVAILABLE,
    WEEKLY,
    AccountRef,
    UsageSnapshot,
    UsageWindow,
    canonical_path,
    stable_id_for,
)
from fastprompter.core.usage_limits.providers import UsageProvider, _zcode_http

# Which plan entry is which, for the account label. ZCode calls both of its
# Z.ai entries "Z.ai - Coding Plan", so the id is what distinguishes them.
_PLAN_LABELS = {
    "builtin:zai-coding-plan": "ZCode",
    "builtin:zai-start-plan": "ZCode Start",
    "builtin:bigmodel-coding-plan": "ZCode BigModel",
    "builtin:bigmodel-start-plan": "ZCode BigModel Start",
}


class ZCodeProvider(UsageProvider):
    """Quota for each configured ZCode Coding Plan. Off unless enabled."""

    provider_id = "zcode"

    def __init__(self, enabled: bool = False, config_path: str = "",
                 reader=None):
        self._enabled = bool(enabled)
        self._config_path = config_path or ""
        # Injection seam for tests: a real HTTPS call in the suite would assert
        # on this machine's live quota (and spend a credential doing it).
        self._reader = reader or _zcode_http.read_quota

    # -- discovery ---------------------------------------------------------
    def config_path(self) -> str:
        return self._config_path or _zcode_http.default_config_path()

    def discover_accounts(self) -> list[AccountRef]:
        """One account per usable plan entry, or nothing while opted out.

        Identity is the config path plus the plan id, so the two Z.ai plans on
        one machine stay two accounts and neither inherits the other's history.
        """
        if not self._enabled:
            return []
        path = self.config_path()
        entries = _zcode_http.read_plan_entries(path)
        if not entries:
            return []
        root = canonical_path(path)
        out: list[AccountRef] = []
        for entry in entries:
            identity = f"{root}|{entry['id']}"
            out.append(AccountRef(
                provider_id=self.provider_id,
                stable_id=stable_id_for(self.provider_id, identity),
                display_name=_PLAN_LABELS.get(entry["id"], "ZCode"),
                source_kind="configured" if self._config_path else "auto_default",
                source_path=root,
                # The plan id and its host are safe to carry; the key is not,
                # and is re-read from disk at probe time instead of being held
                # in a structure the UI can render.
                metadata={"plan_id": entry["id"],
                          "plan_name": entry["name"],
                          "base_url": entry["base_url"]},
            ))
        return out

    # -- probe -------------------------------------------------------------
    def probe(self, account: AccountRef, deadline: float) -> UsageSnapshot:
        if not self._enabled:
            return _unavailable(account, "disabled",
                                "ZCode limits are off — enable them in AI "
                                "limit settings (they need one HTTPS call to "
                                "Z.ai)")
        if time.monotonic() >= deadline:
            return _unavailable(account, "deadline_exceeded",
                                "no time left in this sweep to read ZCode's "
                                "quota")
        plan_id = str(account.metadata.get("plan_id") or "")
        entry = self._entry_for(plan_id)
        if entry is None:
            return _unavailable(account, "plan_not_configured",
                                "this ZCode plan is no longer in ZCode's "
                                "config, or its API key was removed")
        reading = self._reader(entry, deadline)
        if "error" in reading:
            code, summary = reading["error"]
            # A plan the account simply does not hold is not a fault: ZCode
            # itself renders "no active Coding Plan" and there is nothing to
            # fix, so it must not light the header's error marker.
            return _unavailable(account, code, summary)
        windows = [
            UsageWindow(
                key=row["key"],
                duration_minutes=row["duration_minutes"],
                available=True,
                used_percent=100.0 - row["remaining"],
                remaining_percent=row["remaining"],
                resets_at_epoch=row["resets_at"],
                source=reading["source"],
            )
            for row in reading["windows"]
        ]
        return UsageSnapshot(
            account=account, status=OK, windows=windows,
            plan_type=reading.get("level") or None,
            fetched_at=reading.get("captured_at"),
            provider_metadata={
                "capability": "zcode-monitor-quota",
                "strategy": "https-monitor-usage-quota-limit",
                "plan_id": plan_id,
                "plan_name": str(account.metadata.get("plan_name") or ""),
            },
        )

    def _entry_for(self, plan_id: str) -> dict | None:
        """Re-read the key from disk for exactly this plan, or None."""
        if not plan_id:
            return None
        for entry in _zcode_http.read_plan_entries(self.config_path()):
            if entry["id"] == plan_id:
                return entry
        return None


def _unavailable(account: AccountRef, code: str, summary: str) -> UsageSnapshot:
    return UsageSnapshot(
        account=account,
        status=UNAVAILABLE,
        windows=[UsageWindow.unavailable(FIVE_HOUR),
                 UsageWindow.unavailable(WEEKLY)],
        error_code=code,
        error_summary=summary,
        provider_metadata={"capability": "zcode-monitor-quota",
                           "strategy": "https-monitor-usage-quota-limit"},
    )


def candidate_config_paths() -> list[str]:
    """Candidate locations where ZCode's config might exist."""
    home = os.environ.get("HOME") or os.environ.get("USERPROFILE")
    appdata = os.environ.get("APPDATA")
    localappdata = os.environ.get("LOCALAPPDATA")
    candidates = []
    if home:
        candidates.append(str(Path(home) / ".zcode" / "v2" / "config.json"))
        candidates.append(str(Path(home) / ".zcode" / "config.json"))
    if appdata:
        candidates.append(str(Path(appdata) / "zcode" / "v2" / "config.json"))
        candidates.append(str(Path(appdata) / "zcode" / "config.json"))
    if localappdata:
        candidates.append(str(Path(localappdata) / "zcode" / "config.json"))
    return [c for c in candidates if os.path.isfile(c)]


def source_status(config_path: str | os.PathLike | None = None, *,
                  enabled: bool | None = None) -> dict:
    """What ZCode can currently prove — for the settings UI.

    Reports whether a key EXISTS per plan, never the key. Read-only: a
    malformed config is reported as "no plans", not raised at the dialog.
    """
    path = (str(config_path) if config_path is not None
            else _zcode_http.default_config_path())
    out = {
        "config_path": path,
        "config_found": bool(path) and os.path.isfile(path),
        "candidate_configs": [],
        "enabled": bool(enabled) if enabled is not None else None,
        "plans": [],
    }
    if not out["config_found"]:
        out["candidate_configs"] = candidate_config_paths()
        return out
    try:
        entries = _zcode_http.read_plan_entries(path)
    except Exception:
        return out
    out["plans"] = [
        {
            "id": entry["id"],
            "name": entry["name"],
            "label": _PLAN_LABELS.get(entry["id"], "ZCode"),
            "has_key": bool(entry["has_key"]),
            # An empty endpoint here means the configured host is not one of
            # the vendor's own, so the probe would refuse to send anything.
            "endpoint": _zcode_http.quota_url(entry["base_url"]),
        }
        for entry in entries
    ]
    return out
