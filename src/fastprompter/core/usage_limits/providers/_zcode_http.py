"""ZCode quota straight from the vendor's own monitor endpoint.

ZCode ships no ``/usage`` slash command — its CLI surface (``zcode.cjs``) knows
``login``, ``model``, ``effort``, ``workflow`` and sixteen more, and none of them
report quota. Only the Electron app reads it, over one authenticated GET::

    GET https://api.z.ai/api/monitor/usage/quota/limit
    Authorization: <the plan's own API key>

    {"code": 200, "data": {"level": "lite", "limits": [
      {"type": "CREDIT_LIMIT", "unit": 3, "number": 5,
       "usage": 2000, "currentValue": 252, "remaining": 1747,
       "percentage": 12, "nextResetTime": 1788498595214},
      {"type": "CREDIT_LIMIT", "unit": 6, "number": 1,
       "usage": 10000, "currentValue": 252, "remaining": 9747,
       "percentage": 2, "nextResetTime": 1789085298997}]}}

Reading a quota costs no tokens: the endpoint is a billing monitor, not an
inference route.

Three properties of that payload drive the mapping, and each one is a trap the
vendor's own renderer sidesteps:

* **``unit`` is a window selector, not a size.** The app picks the 5-hour bar
  with ``unit=3, number=5`` and the weekly one with ``unit=6``, across BOTH
  ``TOKENS_LIMIT`` and ``CREDIT_LIMIT`` (it treats those two type names as
  interchangeable). Reading ``unit`` as an amount would report a 3-credit cap.
* **``percentage`` means two different things.** On a Coding Plan credit bucket
  it is the truncated USED percent (12 for 12.6% spent); on the older
  ``ent_2_*`` token buckets it is the REMAINING fraction (0.0107 for 1.07%
  left). Believing it would invert the gauge on one of the two.
* **``currentValue + remaining`` is the honest total on both shapes** — verified
  against live payloads of each: 252+1747=1999 of a 2000 cap, and
  2967863+32137=3000000. That sum is the only derivation used here; a bucket
  that cannot state both halves is DROPPED rather than guessed at.

Every window belongs to ONE pool: both bars count the same ``currentValue``
credit meter, so a spent weekly really does zero the 5-hour window and the
model's ordinary gating (no ``group``) is correct.

Security posture, since this is the only usage source that leaves the machine:

* opt-in — the provider refuses to read anything until the user enables it;
* the host must be one of the vendor's own (``_ALLOWED_HOSTS``), scheme HTTPS,
  certificate verified; a relocated or env-injected endpoint is refused rather
  than trusted;
* the API key is read from ZCode's own config, sent in one header, and never
  logged, echoed, cached or placed in an error summary.
"""

from __future__ import annotations

import json
import os
import ssl
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

# ZCode's own plan entries. A plain API-key provider (``builtin:zai``) can hit
# the same endpoint but has no plan behind it, so it would only ever answer
# "no_plan" — offering it as an account would be noise with a permanent error.
PLAN_PROVIDER_IDS = (
    "builtin:zai-coding-plan",
    "builtin:zai-start-plan",
    "builtin:bigmodel-coding-plan",
    "builtin:bigmodel-start-plan",
)

# Where the quota lives on each vendor host, verified in ZCode 3.4.0.
QUOTA_PATH = "/api/monitor/usage/quota/limit"

# The only hosts this module will talk to. ZCode itself honours
# ``ZCODE_BIGMODEL_USAGE_QUOTA_URL`` and rewrites its endpoint from a runtime
# env var; that is a fine feature for the vendor's own client and a redirection
# primitive for anything holding a credential, so it is deliberately NOT
# supported here. An unknown host is refused, never followed.
_ALLOWED_HOSTS = frozenset({
    "api.z.ai",
    "api.chatglm.site",
    "open.bigmodel.cn",
    "bigmodel.cn",
})

# Which (type, unit) pair is which window. ``number`` disambiguates the 5-hour
# bucket from the monthly tool one, both of which report unit 3/5.
_TOKEN_TYPES = frozenset({"TOKENS_LIMIT", "CREDIT_LIMIT"})
_TIME_TYPES = frozenset({"TIME_LIMIT"})
_WINDOW_MINUTES = {"five_hour": 300, "weekly": 10080, "monthly": 43200}

_TIMEOUT_CAP_S = 15.0
_MAX_BODY_BYTES = 512 * 1024   # a quota envelope is ~1 KB; refuse a firehose

# Vendor messages that mean "this account simply has no plan", not "broken".
_NO_PLAN_MARKERS = ("\u4e0d\u5b58\u5728coding plan", "\u6ca1\u6709\u8d44\u683c",
                    "no coding plan")


def default_config_path() -> str:
    """ZCode's own config file, where the plan API keys live."""
    home = os.environ.get("HOME") or os.environ.get("USERPROFILE")
    if not home:
        return ""
    return str(Path(home) / ".zcode" / "v2" / "config.json")


def read_plan_entries(config_path: str) -> list[dict]:
    """The usable plan providers in ZCode's config, newest schema only.

    Returns one record per entry as ``{"id", "name", "base_url", "has_key"}``
    plus a private ``"api_key"``. Callers that build UI or log lines must read
    ``has_key`` and never the key itself.

    An entry the user switched off, or one ZCode itself marked unusable
    (``systemDisabledReason``: not entitled, not authenticated), is skipped: it
    could only ever answer with the vendor's own refusal.
    """
    if not config_path or not os.path.isfile(config_path):
        return []
    try:
        with open(config_path, encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, ValueError):
        return []
    providers = payload.get("provider") if isinstance(payload, dict) else None
    if not isinstance(providers, dict):
        return []
    out: list[dict] = []
    for entry_id in PLAN_PROVIDER_IDS:
        entry = providers.get(entry_id)
        if not isinstance(entry, dict):
            continue
        if entry.get("enabled") is False or entry.get("systemDisabledReason"):
            continue
        options = entry.get("options")
        options = options if isinstance(options, dict) else {}
        api_key = str(options.get("apiKey") or "").strip()
        if not api_key:
            continue
        out.append({
            "id": entry_id,
            "name": str(entry.get("name") or entry_id),
            "base_url": str(options.get("baseURL") or ""),
            "has_key": True,
            "api_key": api_key,
        })
    return out


def quota_url(base_url: str) -> str:
    """The monitor URL for one plan's host, or ``""`` when it is not allowed.

    ZCode derives this the same way (``inferQuotaUrl``): the quota endpoint
    lives on the vendor's API host, which the plan's own ``baseURL`` names. A
    host outside the vendor set is refused, so a rewritten config cannot point
    a credential somewhere else.

    An ABSENT ``baseURL`` falls back to the vendor's own default host, matching
    ZCode. A PRESENT but unusable one (foreign host, non-HTTPS scheme,
    unparseable) is refused rather than defaulted: a config that says something
    other than the vendor is a reason to stop, not to substitute a guess and
    send the key anyway.
    """
    text = (base_url or "").strip()
    if not text:
        # ZCode's own default for a plan whose baseURL is missing.
        return f"https://api.z.ai{QUOTA_PATH}"
    try:
        parts = urlsplit(text)
    except ValueError:
        return ""
    if parts.scheme not in ("http", "https"):
        return ""
    host = (parts.hostname or "").lower()
    if host not in _ALLOWED_HOSTS:
        return ""
    return f"https://{host}{QUOTA_PATH}"


def _is_success(envelope: dict) -> bool:
    """The vendor's own success rule (``isSuccessfulBigModelEnvelope``)."""
    if envelope.get("success") is False:
        return False
    code = envelope.get("code")
    return code is None or code in (0, 200)


def _envelope_message(envelope: dict) -> str:
    for key in ("msg", "message"):
        value = envelope.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    value = float(value)
    return None if value != value else value      # drop NaN


def _epoch(value) -> float | None:
    """``nextResetTime`` is epoch MILLISECONDS; seconds are accepted too."""
    value = _number(value)
    if value is None or value <= 0:
        return None
    if value > 1e11:
        value /= 1000.0
    return value if 1e9 < value < 1e11 else None


def _window_key(entry: dict) -> str | None:
    """Which quota window a limit row describes, by the vendor's own selector."""
    kind = str(entry.get("type") or "").strip().upper()
    unit = _number(entry.get("unit"))
    number = _number(entry.get("number"))
    if kind in _TOKEN_TYPES:
        if unit == 3 and number == 5:
            return "five_hour"
        if unit == 6:
            return "weekly"
        return None
    if kind in _TIME_TYPES and unit == 5 and number == 1:
        return "monthly"
    return None


def parse_limits(data) -> list[dict]:
    """Flatten ``data.limits`` into one record per recognised quota window.

    Each record is ``{key, remaining, resets_at, duration_minutes, total,
    spent}``. Two rows are dropped rather than approximated: a window this
    module does not recognise (its meaning would be a guess) and one that
    cannot state both ``currentValue`` and ``remaining`` (the only pair from
    which a truthful percentage follows on both payload shapes).
    """
    if not isinstance(data, dict):
        return []
    limits = data.get("limits")
    if not isinstance(limits, list):
        return []
    out: list[dict] = []
    seen: set[str] = set()
    for entry in limits:
        if not isinstance(entry, dict):
            continue
        key = _window_key(entry)
        if key is None or key in seen:
            continue
        spent = _number(entry.get("currentValue"))
        remaining = _number(entry.get("remaining"))
        if spent is None or remaining is None:
            continue
        total = spent + remaining
        if total <= 0:
            continue
        seen.add(key)
        out.append({
            "key": key,
            "remaining": max(0.0, min(100.0, remaining / total * 100.0)),
            "resets_at": _epoch(entry.get("nextResetTime")),
            "duration_minutes": _WINDOW_MINUTES.get(key),
            "total": total,
            "spent": spent,
        })
    out.sort(key=lambda row: row["duration_minutes"] or 10 ** 9)
    return out


class _NoQuotaRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("quota redirects are not accepted")


# -- Coding Plan reset cards (T-1360) ----------------------------------------
# A SECOND, deliberately separate read path. The quota endpoint above takes
# the PLAN API key; the reset-card inventory is account-scoped and is proven
# from the installed ZCode client (evidence
# .saipen/evidence/t1360/zcode_reset_route_discovery.json):
#
#   GET https://zcode.z.ai/api/v1/coding-plan/reset/status
#   Authorization: Bearer <zcodejwttoken>          (from credentials.json)
#   X-Bigmodel-Authorization: <oauth:zai/bigmodel access_token>
#   Bigmodel-Target-Type: PERSONAL
#   -> {"code": 0, "data": {
#        "available_five_hour_resets": [{"expire_at": <epoch ms>}],
#        "available_week_resets": [{"expire_at": <epoch ms>}],
#        "latest_five_hour_reset_history": {"used_at": ms} | null,
#        "latest_week_reset_history": {"used_at": ms} | null,
#        "has_unread_history": bool}}
#
# The client's own rule for availability is expire_at strictly in the
# future; history used_at times are NOT availability. Consumption
# (POST .../use) is a paid-entitlement mutation and is NOT wired here.

_RESET_STATUS_PATH = "/api/v1/coding-plan/reset/status"
_RESET_ALLOWED_HOSTS = frozenset({"zcode.z.ai"})
_RESET_TIMEOUT_CAP_S = 15.0
_RESET_MAX_BODY_BYTES = 512 * 1024
# Keys of the vendor payload that are NOT card arrays.
_RESET_META_KEYS = frozenset({"has_unread_history"})


def default_credentials_path() -> str:
    """ZCode's own credential store, where the signed-in account tokens live."""
    home = os.environ.get("HOME") or os.environ.get("USERPROFILE")
    if not home:
        return ""
    return str(Path(home) / ".zcode" / "v2" / "credentials.json")


def _maas_token_key(plan_id: str) -> str:
    """The vendor OAuth token key for one plan family (from the client)."""
    return ("oauth:bigmodel:access_token"
            if "bigmodel" in str(plan_id or "") else "oauth:zai:access_token")


def reset_cards_url() -> str:
    """The reset-status URL. FIXED host and path, env overrides refused.

    ``ZCODE_BASE_URL`` is the vendor client's own redirection primitive; for
    a process holding account tokens it is exactly what must NOT move this
    endpoint, so the URL is derived from nothing but the vendor constants.
    """
    return f"https://zcode.z.ai{_RESET_STATUS_PATH}"


def _reset_request(request, timeout: float):
    """One authenticated GET of the reset inventory. Seams: tests replace it."""
    endpoint = urlsplit(request.full_url)
    if endpoint.scheme != "https" or endpoint.hostname not in _RESET_ALLOWED_HOSTS:
        raise ValueError("unrecognized reset endpoint")
    context = ssl.create_default_context()
    opener = urllib.request.build_opener(
        urllib.request.HTTPSHandler(context=context), _NoQuotaRedirect())
    return opener.open(request, timeout=timeout)  # nosec B310 - fixed vendor host


def read_reset_cards(entry: dict, deadline: float, *,
                     creds_path: str = "") -> dict:
    """Fetch one plan's Coding Plan reset cards. Never raises, never leaks.

    Returns ``{"cards": [{"kind", "expire_at"}], "history": {...}}`` (the
    provider maps these to provider-neutral offers) or ``{"error": (code,
    summary)}``. Error summaries are built from HTTP status, the vendor's
    own message or an exception TYPE name — never from the request, so the
    account tokens cannot reach a log, tooltip or snapshot.

    An auth failure or a missing signed-in session is reported as an ERROR,
    not as "zero cards": an inventory FastPrompter cannot read is
    unavailable, not empty.
    """
    creds = {}
    try:
        with open(creds_path or default_credentials_path(),
                  encoding="utf-8") as handle:
            creds = json.load(handle)
        if not isinstance(creds, dict):
            creds = {}
    except (OSError, ValueError):
        creds = {}
    jwt = str(creds.get("zcodejwttoken") or "").strip()
    maas = str(creds.get(_maas_token_key(str(entry.get("id") or ""))) or "").strip()
    if not jwt or not maas:
        return {"error": ("reset_auth_unavailable",
                          "signed-in Coding Plan session required — no ZCode "
                          "account credentials on disk (an API key alone "
                          "cannot read the reset inventory)")}
    remaining = deadline - time.monotonic()
    if remaining <= 0.1:
        return {"error": ("deadline_exceeded",
                          "no time left in this sweep to read ZCode reset "
                          "cards")}
    request = urllib.request.Request(reset_cards_url(), method="GET")
    request.add_header("Authorization", f"Bearer {jwt}")
    request.add_header("X-Bigmodel-Authorization", maas)
    request.add_header("Bigmodel-Target-Type", "PERSONAL")
    request.add_header("Accept", "application/json")
    try:
        response = _reset_request(request, min(remaining, _RESET_TIMEOUT_CAP_S))
        with response:
            raw = response.read(_RESET_MAX_BODY_BYTES + 1)
    except urllib.error.HTTPError as exc:
        code = "reset_auth_failed" if exc.code in (401, 403) else "http_error"
        return {"error": (code, f"ZCode reset endpoint returned HTTP {exc.code}")}
    except urllib.error.URLError as exc:
        return {"error": ("network_error",
                          f"could not reach the ZCode reset endpoint "
                          f"({type(exc.reason).__name__ if exc.reason else 'URLError'})")}
    except (ValueError, ssl.SSLError, OSError) as exc:
        return {"error": ("reset_bad_response",
                          f"ZCode reset endpoint: {type(exc).__name__}")}
    if len(raw) > _RESET_MAX_BODY_BYTES:
        return {"error": ("reset_bad_response",
                          "ZCode reset response too large")}
    try:
        envelope = json.loads(raw.decode("utf-8", "replace"))
    except (ValueError, TypeError):
        return {"error": ("reset_bad_response",
                          "ZCode reset endpoint did not return JSON")}
    if not isinstance(envelope, dict) or not _is_success(envelope):
        message = _envelope_message(envelope)
        lowered = message.lower()
        if "404" in lowered or "not_found" in lowered:
            return {"error": ("reset_route_unavailable",
                              "ZCode reset endpoint is not available for this "
                              "account/deployment")}
        return {"error": ("vendor_error",
                          f"ZCode reset endpoint refused: {message[:120]}"
                          if message else "ZCode reset endpoint refused")}
    data = envelope.get("data")
    if not isinstance(data, dict):
        return {"error": ("reset_bad_response",
                          "ZCode reset endpoint returned no data object")}
    cards: list[dict] = []
    for source_key, kind in (("available_five_hour_resets", "five_hour"),
                             ("available_week_resets", "weekly")):
        rows = data.get(source_key)
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            expire = _epoch(row.get("expire_at"))
            if expire is None:
                continue          # the client's own rule: no finite expiry, no card
            cards.append({"kind": kind, "expire_at": expire})
    cards.sort(key=lambda card: card["expire_at"])
    history = {key: data.get(key) for key in data if key not in _RESET_META_KEYS
               and key not in ("available_five_hour_resets",
                               "available_week_resets")}
    # Normalise the two known history rows to epoch seconds, so a consumer
    # never has to know which fields the vendor still sends in milliseconds.
    for key in ("latest_five_hour_reset_history",
                "latest_week_reset_history"):
        row = history.get(key)
        if isinstance(row, dict) and "used_at" in row:
            row = dict(row)
            used = _epoch(row.get("used_at"))
            if used is not None:
                row["used_at"] = used
            history[key] = row
    return {"cards": cards, "history": history}


def _request(url: str, api_key: str, timeout: float) -> dict:
    """One authenticated GET. Returns the decoded envelope or raises."""
    endpoint = urlsplit(url)
    if endpoint.scheme != "https" or endpoint.hostname not in _ALLOWED_HOSTS:
        raise ValueError("unrecognized quota endpoint")
    request = urllib.request.Request(url, method="GET")
    # The vendor sends the raw key in this header, not a Bearer token.
    request.add_header("Authorization", api_key)
    request.add_header("Accept", "application/json")
    context = ssl.create_default_context()
    opener = urllib.request.build_opener(
        urllib.request.HTTPSHandler(context=context), _NoQuotaRedirect())
    with opener.open(request, timeout=timeout) as response:  # nosec B310 - HTTPS allowlist above, redirects refused
        raw = response.read(_MAX_BODY_BYTES + 1)
    if len(raw) > _MAX_BODY_BYTES:
        raise ValueError("quota response too large")
    return json.loads(raw.decode("utf-8", "replace"))


def read_quota(entry: dict, deadline: float, *,
               now: float | None = None) -> dict:
    """Fetch and parse one plan's quota. Never raises, never leaks the key.

    Returns ``{"windows": [...], "level": str, "captured_at": epoch,
    "source": str}`` or ``{"error": (code, summary)}``. Every summary is built
    from HTTP status, the vendor's own message, or an exception TYPE name —
    never from the request itself, so the credential cannot reach a log, a
    tooltip or a snapshot.
    """
    url = quota_url(entry.get("base_url", ""))
    if not url:
        return {"error": ("endpoint_not_allowed",
                          "ZCode's configured host is not a known Z.ai / "
                          "BigModel endpoint; refusing to send credentials "
                          "there")}
    api_key = str(entry.get("api_key") or "")
    if not api_key:
        return {"error": ("no_api_key",
                          "this ZCode plan has no API key in its config")}
    remaining = deadline - time.monotonic()
    if remaining <= 0.1:
        return {"error": ("deadline_exceeded",
                          "no time left in this sweep to read ZCode's quota")}
    try:
        envelope = _request(url, api_key, min(remaining, _TIMEOUT_CAP_S))
    except urllib.error.HTTPError as exc:
        code = "auth_failed" if exc.code in (401, 403) else "http_error"
        return {"error": (code, f"ZCode quota endpoint returned "
                                f"HTTP {exc.code}")}
    except urllib.error.URLError as exc:
        return {"error": ("network_error",
                          f"could not reach the ZCode quota endpoint "
                          f"({type(exc.reason).__name__ if exc.reason else 'URLError'})")}
    except (ValueError, ssl.SSLError, OSError) as exc:
        return {"error": ("bad_response",
                          f"ZCode quota endpoint: {type(exc).__name__}")}
    if not isinstance(envelope, dict):
        return {"error": ("bad_response",
                          "ZCode quota endpoint did not return an object")}
    if not _is_success(envelope):
        message = _envelope_message(envelope)
        lowered = message.lower()
        if any(marker in lowered for marker in _NO_PLAN_MARKERS):
            return {"error": ("no_plan",
                              "this ZCode account has no active Coding Plan")}
        return {"error": ("vendor_error",
                          f"ZCode quota endpoint refused: {message[:120]}"
                          if message else "ZCode quota endpoint refused")}
    data = envelope.get("data")
    windows = parse_limits(data)
    if not windows:
        return {"error": ("no_limits",
                          "ZCode reported no readable quota window")}
    level = ""
    if isinstance(data, dict):
        level = str(data.get("level") or "").strip()
    return {
        "windows": windows,
        "level": level,
        "captured_at": time.time() if now is None else now,
        "source": "zcode-monitor-quota",
    }
