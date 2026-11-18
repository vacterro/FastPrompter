"""CommandCode / OpenCode Go via the SHARED LIMISAW snapshot.

These vendors have no CLI to ask and no local session cache to read, so the
only truthful source is the same measurement LIMISAW already performs for the
whole machine (``%LOCALAPPDATA%\\SAI\\Limits\\snapshot.json``, schema
``sai.limits/snapshot/1``).

This provider performs NO network requests and holds NO credential. It reads
the published document, which is LIMISAW's job to keep fresh, and translates it
into FastPrompter's provider-neutral records. If LIMISAW is not installed the
file is absent, discovery returns nothing, and FastPrompter behaves exactly as
it did standalone — no error, no retry storm.

Identity is ``source_id`` from the snapshot (a vendor account id or a digest of
the configured key), never the display name: two subscriptions can both be
called "vacuum34" and they are still two accounts.
"""

from __future__ import annotations

import json
import os
import time

from fastprompter.core.usage_limits.model import (
    AUTH_REQUIRED,
    ERROR,
    OK,
    STALE,
    UNAVAILABLE,
    AccountRef,
    UsageSnapshot,
    UsageWindow,
    stable_id_for_value,
)
from fastprompter.core.usage_limits.providers import UsageProvider

SNAPSHOT_SCHEMA = "sai.limits/snapshot/1"
# The snapshot is a small JSON document. Refusing a pathological file is the
# same bounded-read rule LIMISAW applies to every external payload.
MAX_SNAPSHOT_BYTES = 8 * 1024 * 1024

# Local override for tests and for users who relocate the producer output.
SNAPSHOT_ENV = "SAI_LIMITS_SNAPSHOT"


def snapshot_path() -> str:
    override = os.environ.get(SNAPSHOT_ENV, "").strip()
    if override:
        return override
    base = os.environ.get("LOCALAPPDATA", "").strip()
    if not base:
        base = os.path.join(os.path.expanduser("~"), "AppData", "Local")
    return os.path.join(base, "SAI", "Limits", "snapshot.json")


def _number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    value = float(value)
    if value != value or value in (float("inf"), float("-inf")):
        return None
    return value


def _text(value) -> str:
    return value.strip() if isinstance(value, str) else ""


def load_snapshot(path: str | None = None) -> dict | None:
    """Read the shared document, or None when it is absent/unreadable.

    None is deliberately quiet: an uninstalled LIMISAW is the standalone
    configuration, not a failure FastPrompter should surface.
    """
    target = path or snapshot_path()
    try:
        with open(target, "rb") as handle:
            raw = handle.read(MAX_SNAPSHOT_BYTES + 1)
    except OSError:
        return None
    if len(raw) > MAX_SNAPSHOT_BYTES:
        return None
    try:
        doc = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None
    if not isinstance(doc, dict) or doc.get("schema") != SNAPSHOT_SCHEMA:
        return None
    return doc


def _window(raw: dict) -> UsageWindow:
    key = _text(raw.get("key"))
    remaining = _number(raw.get("remaining"))
    available = bool(raw.get("available")) and remaining is not None
    if available:
        remaining = max(0.0, min(100.0, remaining))
    duration = raw.get("duration_minutes")
    duration = int(duration) if isinstance(duration, (int, float)) and not isinstance(duration, bool) else None
    reset = _number(raw.get("reset_epoch"))
    if reset is not None and reset <= 0:
        reset = None
    gated = _text(raw.get("gated_by"))
    return UsageWindow(
        key=key,
        duration_minutes=duration,
        available=available,
        used_percent=None if not available else max(0.0, min(100.0, 100.0 - remaining)),
        remaining_percent=remaining if available else None,
        resets_at_epoch=reset,
        source="limisaw-shared-snapshot",
        gated_by=gated or None,
        assumed_full=bool(raw.get("assumed_full")),
        group=_text(raw.get("group")),
        group_label=_text(raw.get("group_label")),
    )


class SharedSnapshotProvider(UsageProvider):
    """One vendor's accounts, as published by the shared LIMISAW producer."""

    def __init__(self, provider_id: str, path: str | None = None):
        self._provider_id = provider_id
        self._path = path

    @property
    def provider_id(self) -> str:
        return self._provider_id

    # -- discovery ---------------------------------------------------------
    def _accounts(self, doc: dict) -> list[dict]:
        rows = doc.get("accounts")
        if not isinstance(rows, list):
            return []
        found = []
        for row in rows:
            if isinstance(row, dict) and _text(row.get("provider")) == self._provider_id:
                found.append(row)
        return found

    @staticmethod
    def _stable_id(row: dict) -> str:
        source_id = _text(row.get("source_id"))
        if source_id:
            return source_id
        # No vendor id: the snapshot's own key is still stable and opaque.
        return stable_id_for_value(
            _text(row.get("provider")),
            _text(row.get("key")) or _text(row.get("name")),
        )

    def discover_accounts(self) -> list[AccountRef]:
        doc = load_snapshot(self._path)
        if doc is None:
            return []
        seen: set[str] = set()
        refs: list[AccountRef] = []
        for row in self._accounts(doc):
            stable = self._stable_id(row)
            if not stable or stable in seen:
                continue
            seen.add(stable)
            label = (_text(row.get("name")) or _text(row.get("provider_label"))
                     or self._provider_id)
            refs.append(AccountRef(
                provider_id=self._provider_id,
                stable_id=stable,
                display_name=label,
                source_kind="runtime",
                metadata={"plan": _text(row.get("plan"))},
            ))
        return refs

    # -- probing -----------------------------------------------------------
    def probe(self, account: AccountRef, deadline: float) -> UsageSnapshot:
        if time.monotonic() > deadline:
            return self._missing(account, ERROR, "deadline_exceeded")
        doc = load_snapshot(self._path)
        if doc is None:
            return self._missing(account, UNAVAILABLE, "shared_snapshot_unavailable")
        row = None
        for candidate in self._accounts(doc):
            if self._stable_id(candidate) == account.stable_id:
                row = candidate
                break
        if row is None:
            return self._missing(account, UNAVAILABLE, "account_not_in_snapshot")

        raw_status = _text(row.get("status"))
        carried = bool(row.get("carried"))
        auth_failed = bool(row.get("auth_failed")) or raw_status == AUTH_REQUIRED
        if bool(row.get("ok")) and raw_status == OK and not carried:
            status = OK
        elif auth_failed:
            status = AUTH_REQUIRED
        elif carried or raw_status == STALE:
            status = STALE
        else:
            status = UNAVAILABLE

        windows = []
        for raw in row.get("windows") or []:
            if isinstance(raw, dict) and _text(raw.get("key")):
                windows.append(_window(raw))

        error = _text(row.get("error")) or _text(row.get("auth_failure_reason"))
        # The shared producer already redacts vendor echoes; the length cap is
        # the consumer's own guarantee that a hostile payload cannot fill a
        # tooltip.
        error = error[:240]

        balances = [b for b in (row.get("balances") or []) if isinstance(b, dict)]
        statistics = [s for s in (row.get("statistics") or []) if isinstance(s, dict)]
        checked = _number(doc.get("checked_at_epoch"))
        metadata = {
            "shared_source": "LIMISAW",
            "shared_schema": SNAPSHOT_SCHEMA,
            "plan": _text(row.get("plan")),
            "provider_status": raw_status,
            "verified_identity": bool(row.get("verified_identity")),
            "balances": balances,
            "statistics": statistics,
        }
        return UsageSnapshot(
            account=account,
            status=status,
            windows=windows,
            plan_type=_text(row.get("plan")) or None,
            fetched_at=checked if checked and checked > 0 else None,
            stale_since=(checked if carried and checked and checked > 0 else None),
            error_code=raw_status or status,
            error_summary=error,
            provider_metadata=metadata,
        )

    @staticmethod
    def _missing(account: AccountRef, status: str, code: str) -> UsageSnapshot:
        return UsageSnapshot(
            account=account,
            status=status,
            windows=[],
            error_code=code,
            error_summary="" if code == "shared_snapshot_unavailable" else code,
            provider_metadata={"shared_source": "LIMISAW"},
        )
