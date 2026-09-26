"""Antigravity quota straight from ``agy -p "/usage"`` — structured and exact.

The Antigravity CLI answers ``/usage`` in print mode without starting an agent
turn (its own changelog: "without starting an agent turn, spending quota, or
leaving a conversation behind"), and ``--output-format json`` returns the
server's own numbers rather than prose::

    {"command": {"name": "usage", "data": {"groups": [
      {"name": "Gemini Models", "buckets": [
        {"id": "gemini-weekly", "window": "weekly",
         "remaining_fraction": 0.681, "reset_time": "2026-09-08T20:06:36Z"},
        {"id": "gemini-5h", "window": "5h",
         "remaining_fraction": 0.096, "reset_time": "2026-09-03T12:41:31Z"}]},
      {"name": "Claude and GPT models", "buckets": [
        {"id": "3p-weekly", "window": "weekly", "remaining_fraction": 0,
         "reset_time": "2026-09-04T16:16:03Z"},
        {"id": "3p-5h", "window": "5h", "disabled": true,
         "remaining_fraction": 1}]}]}}}

Two properties of that payload drive the mapping:

* the groups are INDEPENDENT quota pools ("Within each group, models share a
  weekly limit and a 5-hour limit"), so each window carries its group and
  cross-group gating is refused (see ``UsageWindow.group``);
* a ``disabled`` bucket is not free quota. Antigravity marks the 5h window
  disabled while the pool's weekly one is spent and describes it itself: "You
  have hit your weekly limit, the 5-hour limit does not currently apply." Its
  ``remaining_fraction: 1`` would render as "100% free" on a pool that refuses
  every request, so the window is kept at ZERO remaining instead — the model's
  gating pass then labels it ``blocked by weekly``, which is what the vendor
  says. Dropping it would be the other mistake: the 5-hour limit exists, and
  hiding it makes the pool look like it only has a weekly one.

Nothing is estimated: no bucket, no window.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import math
import os
import re
import time

from fastprompter.core.usage_limits.cli_tools import resolve_binary, run_cli

# A refresh token can remain in Windows Credential Manager after the server has
# revoked it.  Presence alone therefore is not proof of authentication.  Once
# the CLI reports its OAuth prompt, suppress that exact credential blob until
# an explicit login replaces it.  Keeping only a digest avoids retaining token
# material in process memory beyond the credential read itself.
_rejected_auth_signature: str | None = None


def _credential_signature() -> str | None:
    """Digest of a usable Antigravity credential, or ``None``.

    The digest changes when an explicit login refreshes/replaces the token, so
    a previously rejected credential becomes eligible automatically without a
    FastPrompter restart.
    """
    if os.name != "nt":
        return None
    try:
        import ctypes
        from ctypes import wintypes
        advapi32 = ctypes.windll.advapi32

        class _CREDENTIAL(ctypes.Structure):
            _fields_ = [
                ("Flags", wintypes.DWORD),
                ("Type", wintypes.DWORD),
                ("TargetName", wintypes.LPWSTR),
                ("Comment", wintypes.LPWSTR),
                ("LastWritten", wintypes.FILETIME),
                ("CredentialBlobSize", wintypes.DWORD),
                ("CredentialBlob", ctypes.POINTER(ctypes.c_byte)),
                ("Persist", wintypes.DWORD),
                ("AttributeCount", wintypes.DWORD),
                ("Attributes", ctypes.c_void_p),
                ("TargetAlias", wintypes.LPWSTR),
                ("UserName", wintypes.LPWSTR),
            ]

        pcred = ctypes.POINTER(_CREDENTIAL)()
        if not advapi32.CredReadW(
                "gemini:antigravity", 1, 0, ctypes.byref(pcred)) or not pcred:
            return None
        try:
            cred = pcred.contents
            if not cred.CredentialBlob or cred.CredentialBlobSize <= 0:
                return None
            raw = ctypes.string_at(cred.CredentialBlob, cred.CredentialBlobSize)
            data = json.loads(raw.decode("utf-8", errors="replace"))
            token_info = data.get("token") or {}
            if not (token_info.get("access_token") or
                    token_info.get("refresh_token")):
                return None
            return hashlib.sha256(raw).hexdigest()
        finally:
            advapi32.CredFree(pcred)
    except Exception:
        return None


def is_authenticated() -> bool:
    """Whether Antigravity CLI has stored credentials.

    On Windows, agy stores Google OAuth tokens in Windows Credential Manager under
    the target ``gemini:antigravity``. When that target is absent or has no tokens,
    invoking ``agy -p "/usage"`` triggers an interactive browser OAuth flow via
    rundll32. Probing must NEVER run when unauthenticated to avoid surprise browser
    popups.
    """
    signature = _credential_signature()
    return bool(signature and signature != _rejected_auth_signature)


def _mark_auth_rejected() -> None:
    """Suppress the credential that just produced an OAuth login prompt."""
    global _rejected_auth_signature
    _rejected_auth_signature = _credential_signature()


def clear_rejected_auth() -> None:
    """Allow an explicit login attempt to validate the current credential."""
    global _rejected_auth_signature
    _rejected_auth_signature = None

# Antigravity's window names -> provider-neutral keys (model.py).
_WINDOWS = {"5h": "five_hour", "five_hour": "five_hour",
            "weekly": "weekly", "7d": "weekly",
            "monthly": "monthly", "30d": "monthly"}
_WINDOW_MINUTES = {"five_hour": 300, "weekly": 10080, "monthly": 43200}


def _epoch(value) -> float | None:
    """ISO-8601 (``2026-09-08T20:06:36Z``) or epoch number -> epoch seconds."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        value = float(value)
        if value > 1e11:          # milliseconds
            value /= 1000.0
        return value if 1e9 < value < 1e11 else None
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    text = re.sub(r"(\.\d{6})\d+", r"\1", text)
    try:
        parsed = datetime.datetime.fromisoformat(text)
    except (ValueError, OverflowError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=datetime.UTC)
    return parsed.timestamp()


def _remaining(value) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    value = float(value)
    if not math.isfinite(value) or not 0.0 <= value <= 1.0:
        return None
    return max(0.0, min(100.0, value * 100.0))


def parse_usage_payload(payload) -> list[dict]:
    """Flatten the ``/usage`` JSON into one record per quota window.

    Each record is ``{key, group, group_label, remaining, resets_at,
    duration_minutes, disabled}``. A window the vendor marked ``disabled`` is
    reported with ZERO remaining rather than dropped or believed: it exists, it
    is simply superseded by the longer limit in its own pool right now.

    An unknown window name, or a bucket with no readable fraction, IS dropped —
    a pool that cannot state a number must not be rendered as free.
    """
    if not isinstance(payload, dict):
        return []
    command = payload.get("command")
    if not isinstance(command, dict):
        return []
    data = command.get("data")
    groups = data.get("groups") if isinstance(data, dict) else None
    if not isinstance(groups, list):
        return []
    out: list[dict] = []
    for index, group in enumerate(groups):
        if not isinstance(group, dict):
            continue
        label = str(group.get("name") or f"group {index + 1}").strip()
        group_id = re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_") \
            or f"group{index + 1}"
        buckets = group.get("buckets")
        if not isinstance(buckets, list):
            continue
        for bucket in buckets:
            if not isinstance(bucket, dict):
                continue
            key = _WINDOWS.get(str(bucket.get("window") or "").strip().lower())
            if key is None:
                continue
            disabled = bucket.get("disabled") is True
            remaining = _remaining(bucket.get("remaining_fraction"))
            if remaining is None and not disabled:
                continue
            out.append({
                "key": key,
                "group": group_id,
                "group_label": label,
                "remaining": 0.0 if disabled else remaining,
                "resets_at": _epoch(bucket.get("reset_time")),
                "duration_minutes": _WINDOW_MINUTES.get(key),
                "disabled": disabled,
            })
    return out


def read_usage(deadline: float, *, binary: str = "",
               now: float | None = None) -> dict:
    """Run ``agy -p "/usage"`` and return the parsed windows.

    Returns ``{"windows": [...], "captured_at": epoch, "source": str}`` or
    ``{"error": (code, summary)}``. Never raises.
    """
    executable = binary or resolve_binary("antigravity")
    if not executable:
        return {"error": ("cli_not_installed",
                          "Antigravity CLI (agy) not found on PATH")}
    if not is_authenticated():
        return {"error": ("cli_not_logged_in",
                          "Antigravity CLI is not logged in; login required")}
    # Preserve LOCAL keyring authentication.  Pretending to be an SSH session
    # prevents the browser, but it also makes agy ignore a valid Windows
    # Credential Manager session and demand a fresh remote OAuth code forever.
    # ``BROWSER`` blocks only the launcher fallback if a saved token expires
    # between our credential check and the CLI call.
    env = dict(os.environ)
    env.pop("SSH_CONNECTION", None)
    env.pop("SSH_TTY", None)
    env.pop("AGY_CLI_INTERACTIVE_HEADLESS", None)
    system_root = env.get("SystemRoot") or env.get("WINDIR") or r"C:\Windows"
    env["BROWSER"] = os.path.join(system_root, "System32", "where.exe")
    env["AGY_CLI_DISABLE_AUTO_UPDATE"] = "true"
    result = run_cli(
        [executable, "-p", "/usage", "--output-format", "json"], deadline,
        env=env, block_child_processes=True)
    if not result["ok"]:
        failure = f"{result.get('stdout', '')}\n{result.get('error', '')}".lower()
        if any(marker in failure for marker in (
                "authentication required",
                "waiting for authentication",
                "paste the authorization code",
                "not logged in",
                "please log in",
                # The Job Object refused agy's rundll32/browser spawn: agy only
                # opens a browser when its saved OAuth session is expired, so
                # this is the same needs-login state, reached silently.
                "unable to create process")):
            _mark_auth_rejected()
            return {"error": (
                "cli_not_logged_in",
                "Antigravity sign-in expired; explicit login required")}
        return {"error": ("cli_failed", f"agy /usage: {result['error']}")}
    try:
        payload = json.loads(result["stdout"])
    except (ValueError, TypeError):
        return {"error": ("cli_bad_output", "agy /usage did not return JSON")}
    if isinstance(payload, dict) and payload.get("status") not in (
            None, "SUCCESS"):
        return {"error": ("cli_failed",
                          f"agy /usage: {str(payload.get('status'))[:60]}")}
    windows = parse_usage_payload(payload)
    if not windows:
        return {"error": ("cli_no_limits",
                          "agy /usage reported no readable quota window")}
    return {
        "windows": windows,
        "captured_at": time.time() if now is None else now,
        "source": "antigravity-cli-usage",
    }
