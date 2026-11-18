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


def _explicit_sign_out(state_path: str) -> bool:
    """True when the PRIMARY state is readable and positively says "signed out".

    CORE-002: ``state.json`` carrying a present ``authSessions`` mapping with no
    allowed host is the desktop app's own signed-out evidence. The ``.bak``
    fallback exists to survive a CORRUPT or partial primary, so it must not fire
    when the primary is intact and certain — resurrecting the backup there left
    a signed-out account discoverable, associated limits with an old identity
    and aimed an enabled provider at an obsolete token.

    A primary that cannot be parsed, is not an object, or has no usable
    ``authSessions`` mapping is *not* certain evidence, so documented recovery
    from its backup still applies.
    """
    try:
        with open(state_path, encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, ValueError):
        return False
    if not isinstance(payload, dict):
        return False
    sessions = payload.get("authSessions")
    if not isinstance(sessions, dict):
        return False
    return _allowed_session_entry(sessions) is None



def default_state_path() -> str:
    """Where Freebuff Desktop keeps its own auth state."""
    return str(Path.home() / ".config" / "freebuff-desktop" / "state.json")


def candidate_state_paths() -> list[str]:
    """Candidate Freebuff Desktop state.json locations on this machine."""
    candidates: list[str] = []
    default_p = default_state_path()
    if os.path.isfile(default_p):
        candidates.append(default_p)
    if os.name == "nt":
        for env_k in ("USERPROFILE", "HOME"):
            val = os.environ.get(env_k)
            if val:
                p = str(Path(val) / ".config" / "freebuff-desktop" / "state.json")
                if os.path.isfile(p) and p not in candidates:
                    candidates.append(p)
        sys_drive = os.environ.get("SystemDrive") or "C:"
        users_dir = Path(sys_drive + "\\Users")
        if users_dir.is_dir():
            try:
                for u in users_dir.iterdir():
                    try:
                        if u.is_dir() and u.name.lower() not in (
                            "public", "all users", "default", "default user"
                        ):
                            sp = str(u / ".config" / "freebuff-desktop" / "state.json")
                            if os.path.isfile(sp) and sp not in candidates:
                                candidates.append(sp)
                    except (PermissionError, OSError):
                        pass
            except (PermissionError, OSError):
                pass
    return candidates


def _find_local_state(state_path: str) -> str:
    candidates = []
    appdata = os.environ.get("APPDATA")
    if appdata:
        candidates.append(os.path.join(appdata, "Freebuff", "Local State"))
    if state_path:
        try:
            p = Path(state_path).resolve()
            for parent in p.parents:
                if parent.name.lower() == ".config":
                    user_home = parent.parent
                    candidates.append(
                        str(user_home / "AppData" / "Roaming" / "Freebuff" / "Local State")
                    )
        except Exception:
            pass
    for c in candidates:
        if os.path.isfile(c):
            return c
    return ""


def _decrypt_dpapi(blob: bytes) -> bytes:
    if os.name != "nt" or not blob:
        return b""
    try:
        import ctypes
        from ctypes import wintypes

        class _DATA_BLOB(ctypes.Structure):
            _fields_ = [
                ("cbData", wintypes.DWORD),
                ("pbData", ctypes.POINTER(ctypes.c_byte)),
            ]

        crypt32 = ctypes.windll.crypt32
        in_blob = _DATA_BLOB(len(blob), ctypes.cast(blob, ctypes.POINTER(ctypes.c_byte)))
        out_blob = _DATA_BLOB()
        if crypt32.CryptUnprotectData(
            ctypes.byref(in_blob), None, None, None, None, 0, ctypes.byref(out_blob)
        ):
            res = ctypes.string_at(out_blob.pbData, out_blob.cbData)
            kernel32 = ctypes.windll.kernel32
            kernel32.LocalFree(out_blob.pbData)
            return res
    except Exception:
        pass
    return b""


def _decrypt_aes_gcm(key_bytes: bytes, nonce: bytes, ciphertext: bytes, tag: bytes) -> bytes:
    if os.name != "nt" or not key_bytes:
        return b""
    try:
        import ctypes
        from ctypes import wintypes

        class _BCRYPT_AUTHENTICATED_CIPHER_MODE_INFO(ctypes.Structure):
            _fields_ = [
                ("cbSize", wintypes.ULONG),
                ("dwInfoVersion", wintypes.ULONG),
                ("pbNonce", ctypes.c_void_p),
                ("cbNonce", wintypes.ULONG),
                ("pbAuthData", ctypes.c_void_p),
                ("cbAuthData", wintypes.ULONG),
                ("pbTag", ctypes.c_void_p),
                ("cbTag", wintypes.ULONG),
                ("pbMacContext", ctypes.c_void_p),
                ("cbMacContext", wintypes.ULONG),
                ("cbAAD", wintypes.ULONG),
                ("cbData", wintypes.LARGE_INTEGER),
                ("dwFlags", wintypes.ULONG),
            ]

        bcrypt = ctypes.windll.bcrypt
        hAlg = wintypes.HANDLE()
        if bcrypt.BCryptOpenAlgorithmProvider(ctypes.byref(hAlg), ctypes.c_wchar_p("AES"), None, 0) != 0:
            return b""
        try:
            mode_buf = ctypes.create_unicode_buffer("ChainingModeGCM")
            if bcrypt.BCryptSetProperty(
                hAlg, ctypes.c_wchar_p("ChainingMode"), mode_buf, ctypes.sizeof(mode_buf), 0
            ) != 0:
                return b""
            hKey = wintypes.HANDLE()
            if bcrypt.BCryptGenerateSymmetricKey(hAlg, ctypes.byref(hKey), None, 0, key_bytes, len(key_bytes), 0) != 0:
                return b""
            try:
                auth_info = _BCRYPT_AUTHENTICATED_CIPHER_MODE_INFO()
                auth_info.cbSize = ctypes.sizeof(auth_info)
                auth_info.dwInfoVersion = 1
                auth_info.pbNonce = ctypes.cast(nonce, ctypes.c_void_p)
                auth_info.cbNonce = len(nonce)
                auth_info.pbTag = ctypes.cast(tag, ctypes.c_void_p)
                auth_info.cbTag = len(tag)

                cbResult = wintypes.ULONG(0)
                if bcrypt.BCryptDecrypt(
                    hKey, ciphertext, len(ciphertext), ctypes.byref(auth_info), None, 0, None, 0, ctypes.byref(cbResult), 0
                ) != 0:
                    return b""
                out_buf = ctypes.create_string_buffer(cbResult.value)
                if bcrypt.BCryptDecrypt(
                    hKey, ciphertext, len(ciphertext), ctypes.byref(auth_info), None, 0, out_buf, cbResult.value, ctypes.byref(cbResult), 0
                ) != 0:
                    return b""
                return out_buf.raw[: cbResult.value]
            finally:
                bcrypt.BCryptDestroyKey(hKey)
        finally:
            bcrypt.BCryptCloseAlgorithmProvider(hAlg, 0)
    except Exception:
        pass
    return b""


def _decrypt_safe_storage(b64_val: str, state_path: str) -> str:
    try:
        import base64

        raw = base64.b64decode(b64_val)
        if len(raw) < 31 or not (raw.startswith(b"v10") or raw.startswith(b"v11")):
            return ""
        nonce = raw[3:15]
        ciphertext = raw[15:-16]
        tag = raw[-16:]
        local_state = _find_local_state(state_path)
        if not local_state or not os.path.isfile(local_state):
            return ""
        with open(local_state, encoding="utf-8") as f:
            data = json.load(f)
        b64_key = data.get("os_crypt", {}).get("encrypted_key")
        if not b64_key:
            return ""
        raw_key = base64.b64decode(b64_key)
        if not raw_key.startswith(b"DPAPI"):
            return ""
        aes_key = _decrypt_dpapi(raw_key[5:])
        if not aes_key:
            return ""
        plain = _decrypt_aes_gcm(aes_key, nonce, ciphertext, tag)
        if plain:
            return plain.decode("utf-8", errors="replace")
    except Exception:
        pass
    return ""


def read_token(state_path: str | None = None) -> str:
    """The auth token from Freebuff's own state file, or ``""``.

    Supports:
    1. Direct plaintext authSessions in state.json (legacy / portable)
    2. Electron safeStorage encrypted secrets in state.json.auth-secrets.json
    3. state.json.bak fallback -- only for recoverable primary states, never
       after an explicit sign-out (CORE-002)
    """
    path = state_path or default_state_path()
    if (not path or not os.path.isfile(path)) and not state_path:
        cands = candidate_state_paths()
        if cands:
            path = cands[0]
    if not path or not os.path.isfile(path):
        return ""
    # 1. Direct state.json
    try:
        with open(path, encoding="utf-8") as handle:
            payload = json.load(handle)
        sessions = payload.get("authSessions") if isinstance(payload, dict) else None
        entry = _allowed_session_entry(sessions)
        if entry is not None:
            token = entry.get("token")
            if isinstance(token, str) and token.strip():
                return token.strip()
    except (OSError, ValueError):
        pass

    # 2. state.json.auth-secrets.json (Electron safeStorage encrypted).
    # CORE-002: every fallback source is gated by the same primary precedence,
    # not just the .bak one -- an encrypted secret left behind by an older
    # session resurrects the same account the .bak path did.
    secrets_path = path + ".auth-secrets.json"
    if not os.path.isfile(secrets_path):
        secrets_path = os.path.join(os.path.dirname(path), "state.json.auth-secrets.json")
    if os.path.isfile(secrets_path) and not _explicit_sign_out(path):
        try:
            with open(secrets_path, encoding="utf-8") as handle:
                secrets = json.load(handle)
            if isinstance(secrets, dict):
                import hashlib

                for host in _ALLOWED_SESSION_KEYS:
                    h = hashlib.sha256(host.encode("utf-8")).hexdigest()
                    enc_val = secrets.get(f"auth/{h}")
                    if isinstance(enc_val, str) and enc_val.strip():
                        dec = _decrypt_safe_storage(enc_val.strip(), path)
                        if dec:
                            try:
                                dec_obj = json.loads(dec)
                                if isinstance(dec_obj, dict) and "token" in dec_obj:
                                    tok = dec_obj.get("token")
                                    if isinstance(tok, str) and tok.strip():
                                        return tok.strip()
                            except Exception:
                                return dec.strip()
        except (OSError, ValueError):
            pass

    # 3. state.json.bak fallback -- only when the primary did not explicitly
    # sign out (CORE-002). See _explicit_sign_out.
    if _explicit_sign_out(path):
        return ""
    bak_path = path + ".bak"
    if not os.path.isfile(bak_path):
        bak_path = os.path.join(os.path.dirname(path), "state.json.bak")
    if os.path.isfile(bak_path):
        try:
            with open(bak_path, encoding="utf-8") as handle:
                payload = json.load(handle)
            sessions = payload.get("authSessions") if isinstance(payload, dict) else None
            entry = _allowed_session_entry(sessions)
            if entry is not None:
                token = entry.get("token")
                if isinstance(token, str) and token.strip():
                    return token.strip()
        except (OSError, ValueError):
            pass

    return ""


def read_account_user(state_path: str | None = None) -> dict:
    """``{"id", "email", "name"}`` of the signed-in user, or ``{}``.

    Identity metadata only; the token is never included.
    """
    path = state_path or default_state_path()
    if (not path or not os.path.isfile(path)) and not state_path:
        cands = candidate_state_paths()
        if cands:
            path = cands[0]
    if not path or not os.path.isfile(path):
        return {}
    # 1. state.json
    try:
        with open(path, encoding="utf-8") as handle:
            payload = json.load(handle)
        sessions = payload.get("authSessions") if isinstance(payload, dict) else None
        entry = _allowed_session_entry(sessions)
        if entry is not None:
            user = entry.get("user")
            if isinstance(user, dict):
                out = {}
                for key in ("id", "email", "name"):
                    value = user.get(key)
                    if isinstance(value, str) and value:
                        out[key] = value
                if out:
                    return out
    except (OSError, ValueError):
        pass

    # 2. state.json.bak -- only when the primary did not explicitly sign out
    # (CORE-002). Identity and token must come from the same source decision,
    # so this repeats the precedence rather than disagreeing with read_token().
    if not _explicit_sign_out(path):
        bak_path = path + ".bak"
        if not os.path.isfile(bak_path):
            bak_path = os.path.join(os.path.dirname(path), "state.json.bak")
        if os.path.isfile(bak_path):
            try:
                with open(bak_path, encoding="utf-8") as handle:
                    payload = json.load(handle)
                sessions = payload.get("authSessions") if isinstance(payload, dict) else None
                entry = _allowed_session_entry(sessions)
                if entry is not None:
                    user = entry.get("user")
                    if isinstance(user, dict):
                        out = {}
                        for key in ("id", "email", "name"):
                            value = user.get(key)
                            if isinstance(value, str) and value:
                                out[key] = value
                        if out:
                            return out
            except (OSError, ValueError):
                pass

    # 3. session-refunds or session-ends (recovers user id if available).
    # CORE-002: gated by the same precedence as steps 1-2 -- an id recovered
    # here under an explicit sign-out would name an identity the user left.
    if _explicit_sign_out(path):
        return {}
    for name in ("state.json.session-refunds.json", "state.json.session-ends.json"):
        extra = os.path.join(os.path.dirname(path), name)
        if os.path.isfile(extra):
            try:
                with open(extra, encoding="utf-8") as handle:
                    records = json.load(handle)
                if isinstance(records, list):
                    for rec in records:
                        adm = rec.get("admission") if isinstance(rec, dict) else None
                        owner_raw = adm.get("owner") if isinstance(adm, dict) else None
                        if isinstance(owner_raw, str):
                            owner = json.loads(owner_raw)
                            if isinstance(owner, list) and len(owner) >= 2 and owner[1]:
                                return {"id": str(owner[1])}
            except (OSError, ValueError):
                pass

    return {}


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
    candidates = candidate_state_paths()
    if not os.path.isfile(path) and candidates and not state_path:
        path = candidates[0]
    token_present = bool(read_token(path))
    user = read_account_user(path) if token_present else {}
    return {
        "state_path": path,
        "state_found": bool(path) and os.path.isfile(path),
        "signed_in": token_present,
        "candidate_states": candidates,
        "account": {"id": user.get("id", ""),
                    "name": user.get("name", ""),
                    "email": user.get("email", "")},
        "endpoint": SESSION_URL,
        "enabled": bool(enabled) if enabled is not None else None,
    }
