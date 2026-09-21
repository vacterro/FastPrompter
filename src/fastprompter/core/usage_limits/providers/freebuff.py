"""Freebuff (Freebucks) provider — one authenticated read-only HTTPS read, opt-in.

Freebuff Desktop keeps its quota in memory only and offers no local cache, so
the only truthful source is the same endpoint the app itself calls — and the
GET variant it uses to refresh its own header, which admits no session and
spends no quota (see :mod:`._freebuff_http`).

Two account modes exist and are never merged:

* FREEBUCKS — the current currency model: a daily pool with an exact ceiling,
  a wallet balance that never resets, and per-model prices. The daily pool is
  an AMOUNT quota (``daily.remaining`` of ``daily.limit`` Freebucks), not a
  percent of an abstract window, so its window carries the amount fields and
  the wallet lives beside it as a balance badge — never as a fake percentage
  of anything.
* LEGACY — session-count plans: ``subscription.usage`` premium sessions plus
  the separate ``freeWindows`` free-session pool. Parsed to its own windows
  with its own pool tag; a spent plan pool must not zero the free one.

Daily numerator semantics: ``daily.remaining`` is REMAINING — proven from the
vendor's own renderer ("X of today's Y left", wallet spent only after the
daily pool). Nothing here is guessed from a screenshot; all constants come
from the vendor's own implementation.

Security posture mirrors :mod:`.zcode`: constructed opted-OUT, discovers
nothing until enabled, token read only from Freebuff's own state at probe
time, never stored in a snapshot, log or tooltip.
"""

from __future__ import annotations

import time

from fastprompter.core.usage_limits.model import (
    AccountRef,
    UsageSnapshot,
    UsageWindow,
    canonical_path,
    qualified_key,
    stable_id_for,
    stable_id_for_value,
)
from fastprompter.core.usage_limits.providers import UsageProvider, _freebuff_http

# Daily-window key. Amount quotas are their own window kind — NOT five_hour —
# so percent-window alert rules and the "5h" label can never misread them.
DAILY_AMOUNT = "daily_amount"
# Legacy windows, one pool-qualified key each (plan sessions vs free sessions).
_LEGACY_WINDOWS = {
    ("plan", "day"): ("plan_day", 1440),
    ("plan", "five_day"): ("plan_five_day", 5 * 1440),
    ("plan", "month"): ("plan_month", 43200),
    ("free", "day"): ("free_day", 1440),
    ("free", "week"): ("free_week", 10080),
    ("free", "month"): ("free_month", 43200),
}

# Freebuff's brand accent, measured from its own UI assets — the header
# countdown colour when Freebuff refills next.
BRAND_ACCENT = "#50ecb3"


def _amount_window(fb: dict) -> UsageWindow:
    """The daily Freebucks pool as an amount window.

    ``used_percent``/``remaining_percent`` are the honest percent of the daily
    pool (the vendor states remaining and limit, so the percent is exact);
    ``used_amount``/``remaining_amount``/``limit_amount`` keep the Freebucks
    truth beside it so the UI can render "42 / 100 FB" instead of a naked
    percentage. Reset feeds the ordinary reset machinery.
    """
    remaining = float(fb["daily_remaining"])
    limit = float(fb["daily_limit"])
    used = max(0.0, limit - remaining)
    return UsageWindow(
        key=DAILY_AMOUNT,
        duration_minutes=1440,
        available=True,
        used_percent=min(100.0, used / limit * 100.0),
        remaining_percent=max(0.0, min(100.0, remaining / limit * 100.0)),
        used_amount=used,
        remaining_amount=remaining,
        limit_amount=limit,
        unit="FB",
        resets_at_epoch=fb.get("resets_at"),
        source="freebuff-session",
    )


def _legacy_window(pool: str, key: str, used: float, remaining: float,
                   limit: float, resets_at: float | None,
                   minutes: int) -> UsageWindow:
    used_n = max(0.0, min(used, limit))
    remaining_n = max(0.0, limit - used_n)
    return UsageWindow(
        key=qualified_key(key, pool),
        duration_minutes=minutes,
        available=True,
        used_percent=used_n / limit * 100.0,
        remaining_percent=remaining_n / limit * 100.0,
        used_amount=used_n,
        remaining_amount=remaining_n,
        limit_amount=limit,
        unit="sessions",
        resets_at_epoch=resets_at,
        source="freebuff-session",
    )


class FreebuffProvider(UsageProvider):
    """Quota of the signed-in Freebuff Desktop account. Off unless enabled."""

    provider_id = "freebuff"

    def __init__(self, enabled: bool = False, state_path: str = "",
                 reader=None):
        self._enabled = bool(enabled)
        self._state_path = state_path or ""
        # Injection seam for tests: a real HTTPS call in the suite would
        # assert on this machine's live quota.
        self._reader = reader or _freebuff_http.read_session

    # -- discovery ---------------------------------------------------------
    def config_path(self) -> str:
        return self._state_path or _freebuff_http.default_state_path()

    def discover_accounts(self) -> list[AccountRef]:
        """The one signed-in account, or nothing while opted out.

        Identity derives from the account's own canonical id in Freebuff's
        state — a real, non-secret, stable source; never from a balance or
        display name. The token is NOT carried here (a structure the UI can
        render must not hold it); it is re-read from disk at probe time.
        """
        if not self._enabled:
            return []
        path = self.config_path()
        user = _freebuff_http.read_account_user(path)
        has_token = bool(_freebuff_http.read_token(path))
        if not has_token:
            return []
        # T-1243: a vendor account id is an OPAQUE VALUE.  Running it
        # through canonical_path() made the identity depend on the current
        # working directory and drive letter; only the state-file fallback
        # is genuinely a path.
        vendor_id = (user.get("id") or "").strip()
        if vendor_id:
            stable = stable_id_for_value(self.provider_id, vendor_id)
        else:
            stable = stable_id_for(self.provider_id, canonical_path(path))
        return [AccountRef(
            provider_id=self.provider_id,
            stable_id=stable,
            display_name="Freebuff",
            source_kind="configured" if self._state_path else "auto_default",
            source_path=canonical_path(path),
            metadata={
                "capability": "freebuff-freebucks",
                "strategy": "https-freebuff-session-get",
                "account_name": user.get("name", ""),
                "account_email": user.get("email", ""),
            },
        )]

    # -- probe -------------------------------------------------------------
    def probe(self, account: AccountRef, deadline: float) -> UsageSnapshot:
        if not self._enabled:
            return _unavailable(account, "disabled",
                                "Freebuff limits are off — enable them in AI "
                                "limit settings (they need one read-only HTTPS "
                                "call to Freebuff)")
        if time.monotonic() >= deadline:
            return _unavailable(account, "deadline_exceeded",
                                "no time left in this sweep to read Freebuff")
        token = _freebuff_http.read_token(self.config_path())
        reading = self._reader(token, deadline)
        if "error" in reading:
            code, summary = reading["error"]
            return _unavailable(account, code, summary)
        captured = reading.get("captured_at")
        if reading["mode"] == "freebucks":
            fb = reading["freebucks"]
            windows = [_amount_window(fb)]
            reset_color_note = ""
            return UsageSnapshot(
                account=account, status="OK", windows=windows,
                plan_type=fb.get("plan_id") or "Freebucks",
                fetched_at=captured,
                provider_metadata={
                    "capability": "freebuff-freebucks",
                    "strategy": "https-freebuff-session-get",
                    "mode": "freebucks",
                    # The wallet is a BALANCE: a number, no meter, no reset.
                    "wallet_balance": fb.get("wallet_balance"),
                    "wallet_monthly_bonus": fb.get("wallet_monthly_bonus"),
                    "total_balance": fb.get("balance"),
                    # Per-model prices (FB/hour) — tooltip/overview detail.
                    "model_prices": dict(fb.get("prices") or {}),
                    "price_notices": dict(fb.get("price_notices") or {}),
                    "unit": "FB",
                    "reset_color_note": reset_color_note,
                },
            )
        legacy = reading["legacy"]
        windows = []
        for row in legacy["pools"]:
            pool_key, minutes = _LEGACY_WINDOWS.get(
                (row["pool"], row["key"]), (None, None))
            if pool_key is None:
                continue
            limit = row["used"] + row["remaining"]
            windows.append(_legacy_window(
                row["pool"], pool_key.split("_", 1)[1], row["used"],
                row["remaining"], limit, row.get("resets_at"), minutes))
        if not windows:
            return _unavailable(account, "no_quota_data",
                                "Freebuff reported no readable legacy window")
        return UsageSnapshot(
            account=account, status="OK", windows=windows,
            plan_type=legacy.get("plan_label") or "Legacy sessions",
            fetched_at=captured,
            provider_metadata={
                "capability": "freebuff-freebucks",
                "strategy": "https-freebuff-session-get",
                "mode": "legacy",
                "unit": "sessions",
            },
        )


def _unavailable(account: AccountRef, code: str, summary: str) -> UsageSnapshot:
    return UsageSnapshot(
        account=account,
        status="UNAVAILABLE",
        windows=[UsageWindow.unavailable(DAILY_AMOUNT)],
        error_code=code,
        error_summary=summary,
        provider_metadata={
            "capability": "freebuff-freebucks",
            "strategy": "https-freebuff-session-get",
        },
    )


def source_status(state_path: str | None = None, *,
                  enabled: bool | None = None) -> dict:
    """What Freebuff can currently prove — for the settings UI."""
    return _freebuff_http.source_status(state_path, enabled=enabled)
