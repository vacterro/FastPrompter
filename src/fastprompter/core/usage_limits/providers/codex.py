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
    ERROR,
    FIVE_HOUR,
    OK,
    WEEKLY,
    AccountRef,
    ResetOffer,
    UsageSnapshot,
    UsageWindow,
    canonical_path,
    stable_id_for,
)
from fastprompter.core.usage_limits.providers import UsageProvider
from fastprompter.core.usage_limits.providers._codex_probe import (  # noqa: F401
    parse_windows,
)

# Duration -> window key lives in _codex_probe.DURATION_LABELS (single source
# of truth). Kept out of this module on purpose: a second copy would drift
# and start dropping plan-specific windows again.


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
            st = result.get("status") or ERROR
            code = "identity_mismatch" if st == "IDENTITY_MISMATCH" else (
                "auth_required" if st == "AUTH_REQUIRED" else "probe_failed"
            )
            return UsageSnapshot(
                account=account, status=st,
                windows=[UsageWindow.unavailable(FIVE_HOUR),
                         UsageWindow.unavailable(WEEKLY)],
                error_code=code,
                error_summary=str(result.get("error") or "probe failed")[:120],
            )

        # Window set comes from the probe verbatim — a Free plan reports one
        # 30-day window, Plus reports 5h + weekly. Never hardcode the pair.
        windows = _windows_from(result)
        if not windows:
            windows = [UsageWindow.unavailable(FIVE_HOUR),
                       UsageWindow.unavailable(WEEKLY)]
        banked = result.get("banked_resets")
        meta = {
            "source": "codex app-server account/rateLimits/read",
            "codex_home": result.get("codex_home") or account.source_path,
            "codex_account_id": result.get("codex_account_id"),
            "codex_email": result.get("codex_email"),
        }
        if banked is not None:
            meta["banked_resets"] = banked
        if result.get("reset_credits"):
            meta["reset_credits"] = result["reset_credits"]
        return UsageSnapshot(
            account=account, status=OK, windows=windows,
            plan_type=result.get("plan_type"),
            fetched_at=result.get("fetched_at"),
            provider_metadata=meta,
            banked_resets=banked,
            reset_offers=_reset_offers_from(account, banked,
                                            result.get("reset_credits")),
        )

    def consume_reset(self, account: AccountRef, credit_id: str | None = None) -> dict:
        from fastprompter.core.usage_limits.providers._codex_probe import (
            consume_codex_reset,
        )

        return consume_codex_reset(account.source_path, credit_id=credit_id)



# Keys in a probe payload that are NOT quota windows.
_NON_WINDOW_KEYS = frozenset({"ok", "error", "plan_type", "fetched_at",
                             "banked_resets", "reset_credits"})


# Codex ``resetType`` values -> provider-neutral target kinds. Anything
# else is kept verbatim: an unknown vendor target is still real, it is just
# not one of the two windows FastPrompter already names.
_RESET_TARGETS = {"FULL": "", "WEEK": WEEKLY, "WEEKLY": WEEKLY,
                  "FIVE_HOUR": FIVE_HOUR, "5H": FIVE_HOUR}


def _epoch_or_none(value):
    """Vendor epoch (seconds or milliseconds) -> epoch seconds or None."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    if number <= 0:
        return None
    if number > 1e11:            # milliseconds
        number /= 1000.0
    return number if 1e9 < number < 1e11 else None


def _reset_offers_from(account: AccountRef, banked, credits) -> tuple:
    """Codex reset credits as provider-neutral :class:`ResetOffer` entries.

    Rules (T-1360): individual credits are mapped verbatim when the vendor
    identifies them; a bare ``availableCount`` with no per-credit list yields
    ONE aggregate offer with an empty ``offer_id`` — an honest count, never
    a fabricated card identity. Malformed entries are dropped, not guessed
    at. Codex is the one provider whose redemption route FastPrompter has
    proven, so its offers are directly activatable.
    """
    offers: list[ResetOffer] = []
    if isinstance(credits, list):
        for credit in credits:
            if not isinstance(credit, dict):
                continue
            status_raw = str(credit.get("status") or "").strip().lower()
            if status_raw not in ("available", "expired", "consumed"):
                continue
            offer_id = str(credit.get("id") or "").strip()
            if status_raw == "available" and not offer_id:
                continue      # an unidentifiable credit is not a card
            reset_type = str(credit.get("reset_type") or "").strip().upper()
            title = str(credit.get("title") or "").strip()
            if not title:
                title = str(credit.get("description") or "").strip()
            offers.append(ResetOffer(
                offer_id=offer_id,
                provider_id=account.provider_id,
                account_key=account.key,
                target_kind=_RESET_TARGETS.get(reset_type, reset_type.lower()),
                status=status_raw,
                title=title,
                granted_at_epoch=_epoch_or_none(credit.get("granted_at")),
                expires_at_epoch=_epoch_or_none(credit.get("expires_at")),
                redeemable=status_raw == "available",
                redeemable_in_fastprompter=status_raw == "available",
                source="codex-rateLimitResetCredits"))
    if offers:
        return tuple(offers)
    if isinstance(banked, int) and not isinstance(banked, bool) and banked > 0:
        word = "reset" if banked == 1 else "resets"
        return (ResetOffer(
            provider_id=account.provider_id,
            account_key=account.key,
            status="available",
            title=f"{banked} {word} available",
            quantity=banked,
            redeemable=True,
            redeemable_in_fastprompter=True,
            source="codex-rateLimitResetCredits-count"),)
    return ()


def _windows_from(result: dict) -> list:
    """Every window the probe reported, shortest duration first.

    Windows this plan does not have (``available=False``) are dropped as soon
    as at least one real window exists — otherwise a Free plan, which reports
    only a 30-day window, would render two dead bars next to it. When nothing
    is available the unavailable ones survive so the UI still has something
    honest (dim) to draw.
    """
    out = []
    group_order: dict[str, int] = {}
    for key, bucket in (result or {}).items():
        if key in _NON_WINDOW_KEYS or not isinstance(bucket, dict):
            continue
        window = _as_window(key, bucket)
        if window.group not in group_order:
            group_order[window.group] = len(group_order)
        out.append(window)
    # Grouped by POOL first, then shortest window inside it. An account can
    # hold several pools (Codex + a named reserve) whose windows have the same
    # duration, and sorting by duration alone interleaved them, so a pool's
    # heading was drawn, then the other pool's, then the first pool's again.
    #
    # An account's ORDINARY pool leads, then the others in the probe's own
    # order: a reserve is an alternative to the default quota, not the main
    # subject, and it keeps the ordinary "Codex 5h / weekly" pair at the top
    # regardless of which pool the server happened to list first. A
    # single-pool account has group "" everywhere, which leaves the historical
    # "shortest first" order byte-identical.
    out.sort(key=lambda w: (not _is_ordinary_group(w.group),
                            group_order.get(w.group, 0),
                            w.duration_minutes is None,
                            w.duration_minutes or 0))
    available = [w for w in out if w.available]
    return available or out


def _is_ordinary_group(group: str) -> bool:
    """The account's default pool, versus a model-scoped reserve.

    Only the canonical default pool ids are recognised. Anything else is
    treated as a reserve for ORDERING purposes only — an unclassified pool
    sorts after the default rather than being claimed as ordinary capacity
    (classification itself never happens here; ``UsageWindow.model_slug``
    carries that evidence).
    """
    return str(group or "").strip().lower() in ("", "codex")


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
        # The pool identity MUST survive this boundary: every pool-aware
        # consumer (gate_windows / _pool_usable / display_windows /
        # account_usable_now / reset_candidates) groups by ``group``, so
        # dropping it here silently re-merges independent Codex pools into
        # one logical pool -- the exact defect this ticket repairs.
        group=str(bucket.get("group") or ""),
        group_label=str(bucket.get("group_label") or ""),
        model_slug=str(bucket.get("model_slug") or ""),
    )


def _epoch(iso):
    if not iso:
        return None
    try:
        import datetime as _dt
        t = _dt.datetime.fromisoformat(str(iso))
        if t.tzinfo is None:
            t = t.replace(tzinfo=_dt.UTC)
        return t.timestamp()
    except Exception:
        return None


def source_status(extra_homes: list[str] | None = None, *,
                  now: float | None = None) -> dict:
    """What each Codex source can currently prove — for the settings UI.

    Reports whether the CLI is on PATH/fallback, what homes exist, and
    whether an authenticated session (auth.json) was found.
    """
    now = time.time() if now is None else now
    try:
        root = _home_dir()
    except Exception:
        root = None
    from fastprompter.core.usage_limits.cli_tools import resolve_binary
    cli_path = resolve_binary("codex")
    cli_installed = bool(cli_path)

    homes: list[dict] = []
    seen: set[str] = set()

    def check_home(p_str: str, kind: str) -> None:
        if not p_str:
            return
        can = canonical_path(p_str)
        if not can or can in seen:
            return
        if not os.path.isdir(can):
            return
        seen.add(can)
        auth_file = os.path.join(can, "auth.json")
        has_auth = os.path.isfile(auth_file)
        homes.append({
            "path": can,
            "kind": kind,
            "has_auth": has_auth,
            "auth_path": auth_file if has_auth else "",
        })

    if root:
        check_home(str(root / ".codex"), "auto_default")
        try:
            for s in sorted(root.glob(".codex-*")):
                if s.is_dir():
                    check_home(str(s), "auto_sibling")
        except Exception:
            pass

    env_home = os.environ.get("CODEX_HOME")
    if env_home:
        check_home(env_home, "env")

    for p in (extra_homes or ()):
        check_home(p, "configured")

    auth_found = any(h["has_auth"] for h in homes)
    return {
        "cli_installed": cli_installed,
        "cli_path": cli_path,
        "homes": homes,
        "auth_found": auth_found,
        "logged_in": auth_found,
        "default_home_exists": bool(root and os.path.isdir(str(root / ".codex"))),
    }

