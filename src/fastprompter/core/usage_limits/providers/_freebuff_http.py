"""Freebuff quota straight from the endpoint Freebuff Desktop itself calls.

Freebuff ships no local quota cache: the desktop app keeps its session state in
memory only (its persisted ``state.json`` holds auth + UI prefs, its Local
Storage holds theme/intro flags — both verified). The authoritative source is
therefore the same authenticated call the app itself makes::

    GET https://www.codebuff.com/api/v1/freebuff/session
    Authorization: Bearer <token from Freebuff's own state.json>
    x-freebuff-multi-session: 1

The desktop app issues this GET in ``refreshTier()`` — the same call it makes
to refresh its own header — and crucially it is the READ variant: creating a
billable session is a POST with an ``x-freebuff-model`` header, releasing one
is a DELETE. A plain GET admits nothing, spends nothing, and returns the same
body the app renders its Freebucks header from. Reading it costs no quota.

Account modes seen in the wild, each parsed to its own model (never merged):

FREEBUCKS  — ``freebucks`` present::

    freebucks: { balance, planId,
                 daily:  { remaining, limit, resetAt },
                 wallet: { balance, monthlyBonus },
                 prices: { "<model id>": <Freebucks per hour> },
                 priceNotices, priceChanges }
    balance = daily.remaining + wallet.balance (the vendor's own spend order:
    today's pool first, then wallet). ``daily.remaining`` is REMAINING, not
    used — proven from the vendor's own renderer ("X of today's Y left").

LEGACY     — no ``freebucks``, but ``subscription``/``freeWindows``::

    subscription.usage: { dayUsed, dayLimit, dayResetAt,
                          fiveDayUsed, fiveDayLimit,
                          monthUsed, monthLimit, periodEndsAt }
    freeWindows: { dayUsed, dayLimit, dayResetAt, weekUsed, weekLimit,
                   monthUsed, monthLimit }   (free premium session counts)

Security posture (mirrors :mod:`._zcode_http`): opt-in at the provider layer,
HTTPS only, host allowlisted to the vendor's own, certificate verified,
redirects refused, bounded timeout, bounded body. The token is read from
Freebuff's own state, sent in one header, and never logged, echoed, cached or
placed in an error summary — summaries carry HTTP status, exception TYPE names
or vendor strings only.
"""

from __future__ import annotations

import json
import os
import ssl
import time
import urllib.error
import urllib.request
from datetime import UTC
from pathlib import Path
from urllib.parse import urlsplit

# The endpoint the desktop app itself uses (orchestrator sessionEndpoint()).
# The host is Freebuff's own API host; env overrides are deliberately NOT
# honoured — for a process holding a credential that is a redirection
# primitive, not a feature.
SESSION_URL = "https://www.codebuff.com/api/v1/freebuff/session"

_ALLOWED_HOSTS = frozenset({"www.codebuff.com", "codebuff.com"})

_TIMEOUT_CAP_S = 15.0
_MAX_BODY_BYTES = 512 * 1024   # a session envelope is a few KB; refuse a firehose

# Freebuff's own state file (verified schema: authSessions.{host}.{token,user}).
_STATE_FILE = Path.home() / ".config" / "freebuff-desktop" / "state.json"
_SESSION_HOST = "https://www.codebuff.com"

#: The ONLY ``authSessions`` keys whose credential may be sent to
#: codebuff.com.  T-1243: the old code fell back to the FIRST entry in the
#: file when the expected key was absent, which would send a token minted
#: for some other host to the vendor's API.  A credential is scoped to the
#: host that issued it; there is no safe "close enough" match.
_ALLOWED_SESSION_KEYS = frozenset({
    "https://www.codebuff.com",
    "https://codebuff.com",
    "http://www.codebuff.com",
    "http://codebuff.com",
    "www.codebuff.com",
    "codebuff.com",
})


def _allowed_session_entry(sessions) -> dict | None:
    """The session entry for a PROVEN Freebuff/Codebuff host, or None.

    No first-entry fallback: an unrecognized host means "not signed in".
    """
    if not isinstance(sessions, dict):
        return None
    for key, value in sessions.items():
        if not isinstance(key, str) or not isinstance(value, dict):
            continue
        candidate = key.strip().rstrip("/").lower()
        if candidate in _ALLOWED_SESSION_KEYS:
            return value
    return None


def default_state_path() -> str:
    """Where Freebuff Desktop keeps its own auth state."""
    return str(_STATE_FILE)


def read_token(state_path: str | None = None) -> str:
    """The auth token from Freebuff's own state file, or ``""``.

    The value never survives this function except as the return value the
    caller puts straight into one request header. Callers must not log it.
    """
    path = state_path or default_state_path()
    if not path or not os.path.isfile(path):
        return ""
    try:
        with open(path, encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, ValueError):
        return ""
    sessions = payload.get("authSessions") if isinstance(payload, dict) else None
    entry = _allowed_session_entry(sessions)
    if entry is None:
        return ""            # no proven Freebuff host entry: AUTH_REQUIRED
    token = entry.get("token")
    return token.strip() if isinstance(token, str) else ""


def read_account_user(state_path: str | None = None) -> dict:
    """``{"id", "email", "name"}`` of the signed-in user, or ``{}``.

    Identity metadata only; the token is never included.
    """
    path = state_path or default_state_path()
    if not path or not os.path.isfile(path):
        return {}
    try:
        with open(path, encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, ValueError):
        return {}
    sessions = payload.get("authSessions") if isinstance(payload, dict) else None
    entry = _allowed_session_entry(sessions)
    if entry is None:
        return {}            # same host policy as read_token
    user = entry.get("user")
    if not isinstance(user, dict):
        return {}
    out = {}
    for key in ("id", "email", "name"):
        value = user.get(key)
        if isinstance(value, str) and value:
            out[key] = value
    return out


class _NoQuotaRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("session redirects are not accepted")


def _request(url: str, token: str, timeout: float) -> dict:
    """One authenticated GET. Returns the decoded body or raises."""
    endpoint = urlsplit(url)
    if endpoint.scheme != "https" or endpoint.hostname not in _ALLOWED_HOSTS:
        raise ValueError("unrecognized session endpoint")
    request = urllib.request.Request(url, method="GET")
    request.add_header("Authorization", f"Bearer {token}")
    # Mirror the desktop app's own GET (refreshTier): multi-session marker,
    # no model header — a model header is the POST-only admission trigger.
    request.add_header("x-freebuff-multi-session", "1")
    request.add_header("Accept", "application/json")
    context = ssl.create_default_context()
    opener = urllib.request.build_opener(
        urllib.request.HTTPSHandler(context=context), _NoQuotaRedirect())
    with opener.open(request, timeout=timeout) as response:  # nosec B310 - HTTPS allowlist above, redirects refused
        raw = response.read(_MAX_BODY_BYTES + 1)
    if len(raw) > _MAX_BODY_BYTES:
        raise ValueError("session response too large")
    return json.loads(raw.decode("utf-8", "replace"))


# --------------------------------------------------------------------------
# payload parsing — freebucks mode
# --------------------------------------------------------------------------

def _number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    value = float(value)
    return None if value != value else value      # drop NaN


def _epoch_from_iso(value) -> float | None:
    """ISO timestamp (vendor sends e.g. ``2026-09-10T07:00:00.000Z``)."""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        from datetime import datetime
        text = value.strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        moment = datetime.fromisoformat(text)
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=UTC)
        return moment.timestamp()
    except (ValueError, OverflowError, OSError):
        return None


def parse_freebucks(session: dict) -> dict | None:
    """The freebucks payload into a plain record, or None when absent.

    Every field is taken at face value from the vendor; nothing is derived
    that the vendor did not state. ``daily.remaining`` stays REMAINING — the
    vendor's own UI sentence is "X of today's Y left".
    """
    fb = session.get("freebucks") if isinstance(session, dict) else None
    if not isinstance(fb, dict):
        return None
    daily = fb.get("daily")
    wallet = fb.get("wallet")
    if not isinstance(daily, dict):
        return None
    remaining = _number(daily.get("remaining"))
    limit = _number(daily.get("limit"))
    if remaining is None or limit is None or limit <= 0:
        return None
    prices = {}
    raw_prices = fb.get("prices")
    if isinstance(raw_prices, dict):
        for model_id, price in raw_prices.items():
            value = _number(price)
            if value is not None and isinstance(model_id, str) and model_id:
                prices[model_id] = value
    wallet_balance = None
    wallet_bonus = None
    if isinstance(wallet, dict):
        wallet_balance = _number(wallet.get("balance"))
        wallet_bonus = _number(wallet.get("monthlyBonus"))
    balance = _number(fb.get("balance"))
    if balance is None:
        pool = daily.get("balance")
        balance = _number(pool) if isinstance(pool, dict) else None
    notices = {}
    raw_notices = fb.get("priceNotices")
    if isinstance(raw_notices, dict):
        notices = {str(k): str(v) for k, v in raw_notices.items()
                   if isinstance(k, str) and v is not None}
    return {
        "balance": balance,
        "daily_remaining": remaining,
        "daily_limit": limit,
        "resets_at": _epoch_from_iso(daily.get("resetAt")),
        "wallet_balance": wallet_balance,
        "wallet_monthly_bonus": wallet_bonus,
        "prices": prices,
        "price_notices": notices,
        "plan_id": str(fb.get("planId") or "") or None,
    }


# --------------------------------------------------------------------------
# payload parsing — legacy session mode
# --------------------------------------------------------------------------

def _used_remaining(used, limit) -> tuple[float | None, float | None]:
    used_n = _number(used)
    limit_n = _number(limit)
    if used_n is None or limit_n is None or limit_n <= 0:
        return None, None
    used_n = max(0.0, min(used_n, limit_n))
    return used_n, limit_n - used_n


def parse_legacy(session: dict) -> dict | None:
    """Legacy account facts, or None when the session carries none.

    Two independent pools exist in legacy mode: the plan's own premium
    sessions (``subscription.usage``) and the free premium sessions
    (``freeWindows``). Both report day/week(/month) counts; each is returned
    as its own pool so one being spent never zeroes the other.
    """
    if not isinstance(session, dict):
        return None
    pools: list[dict] = []
    plan_label = ""
    sub = session.get("subscription")
    if isinstance(sub, dict):
        usage = sub.get("usage")
        if isinstance(usage, dict):
            plan_label = str(sub.get("tierId") or "") or "plan"
            rows = (
                ("day", usage.get("dayUsed"), usage.get("dayLimit"),
                 _epoch_from_iso(usage.get("dayResetAt")), 1440),
                ("five_day", usage.get("fiveDayUsed"), usage.get("fiveDayLimit"),
                 None, 5 * 1440),
                ("month", usage.get("monthUsed"), usage.get("monthLimit"),
                 _epoch_from_iso(usage.get("periodEndsAt")), 43200),
            )
            for key, used, limit, reset, minutes in rows:
                used_n, remaining_n = _used_remaining(used, limit)
                if used_n is None:
                    continue
                pools.append({"pool": "plan", "key": key,
                              "used": used_n, "remaining": remaining_n,
                              "resets_at": reset, "minutes": minutes})
    free = session.get("freeWindows")
    if isinstance(free, dict):
        rows = (
            ("day", free.get("dayUsed"), free.get("dayLimit"),
             _epoch_from_iso(free.get("dayResetAt")), 1440),
            ("week", free.get("weekUsed"), free.get("weekLimit"),
             None, 10080),
            ("month", free.get("monthUsed"), free.get("monthLimit"),
             None, 43200),
        )
        for key, used, limit, reset, minutes in rows:
            used_n, remaining_n = _used_remaining(used, limit)
            if used_n is None:
                continue
            pools.append({"pool": "free", "key": key,
                          "used": used_n, "remaining": remaining_n,
                          "resets_at": reset, "minutes": minutes})
    if not pools:
        return None
    return {"plan_label": plan_label, "pools": pools}


# --------------------------------------------------------------------------
# top-level read
# --------------------------------------------------------------------------

def read_session(token: str, deadline: float, *, now: float | None = None) -> dict:
    """Fetch and parse one session reading. Never raises, never leaks the token.

    Returns one of::

        {"mode": "freebucks", "freebucks": {...}, "captured_at": epoch, "source": str}
        {"mode": "legacy",    "legacy": {...},    "captured_at": epoch, "source": str}
        {"error": (code, summary)}

    Summaries are built from HTTP status, exception TYPE names or vendor
    strings — never from the request, so the credential cannot reach a log,
    tooltip or snapshot.
    """
    if not token:
        return {"error": ("no_token",
                          "no Freebuff sign-in found in Freebuff Desktop's "
                          "own state — sign in there first")}
    remaining = deadline - time.monotonic()
    if remaining <= 0.1:
        return {"error": ("deadline_exceeded",
                          "no time left in this sweep to read Freebuff's quota")}
    try:
        body = _request(SESSION_URL, token, min(remaining, _TIMEOUT_CAP_S))
    except urllib.error.HTTPError as exc:
        code = "auth_failed" if exc.code in (401, 403) else "http_error"
        return {"error": (code, f"Freebuff session endpoint returned "
                                f"HTTP {exc.code}")}
    except urllib.error.URLError as exc:
        return {"error": ("network_error",
                          f"could not reach the Freebuff session endpoint "
                          f"({type(exc.reason).__name__ if exc.reason else 'URLError'})")}
    except (ValueError, ssl.SSLError, OSError) as exc:
        return {"error": ("bad_response",
                          f"Freebuff session endpoint: {type(exc).__name__}")}
    if not isinstance(body, dict):
        return {"error": ("bad_response",
                          "Freebuff session endpoint did not return an object")}
    captured = time.time() if now is None else now
    freebucks = parse_freebucks(body)
    if freebucks is not None:
        return {"mode": "freebucks", "freebucks": freebucks,
                "captured_at": captured, "source": "freebuff-session"}
    legacy = parse_legacy(body)
    if legacy is not None:
        return {"mode": "legacy", "legacy": legacy,
                "captured_at": captured, "source": "freebuff-session"}
    return {"error": ("no_quota_data",
                      "Freebuff reported neither Freebucks nor legacy "
                      "session quota for this account")}


def source_status(state_path: str | None = None, *,
                  enabled: bool | None = None) -> dict:
    """What Freebuff can currently prove — for the settings UI.

    Reports whether a sign-in EXISTS, never the token. Read-only: a malformed
    state file is reported as "not signed in", not raised at the dialog.
    """
    path = state_path or default_state_path()
    token_present = bool(read_token(path))
    user = read_account_user(path) if token_present else {}
    return {
        "state_path": path,
        "state_found": bool(path) and os.path.isfile(path),
        "signed_in": token_present,
        "account": {"id": user.get("id", ""),
                    "name": user.get("name", ""),
                    "email": user.get("email", "")},
        "endpoint": SESSION_URL,
        "enabled": bool(enabled) if enabled is not None else None,
    }
