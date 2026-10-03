"""Low-level Codex app-server probe with a true hard deadline.

This is the engine half of the Codex provider, refactored from
``core/codex_limits.py`` (LIMISAW port) to obey an absolute deadline
across spawn/handshake/read/close, and to drain stderr so a noisy child
can never block the pipe.
"""

from __future__ import annotations

import functools
import json
import os
import subprocess
import threading
import time

from fastprompter.core.usage_limits.cli_tools import (
    silent_creationflags,
    silent_startupinfo,
)
from fastprompter.core.usage_limits.model import qualified_key

# Tunables
READ_STEP_S = 0.02
CHILD_KILL_GRACE_S = 2.0
# Grace granted to a child that shutdown asked to stop. Short on purpose: the
# app is already leaving and the pipes are about to be closed underneath it.
CANCEL_GRACE_S = 0.5
# Per-call ceiling for one JSON-RPC round trip. Measured on a live account
# (8 sequential probes): initialize ~0.13s, account/rateLimits/read median
# 0.87s but with 3.6s outliers, and a first probe after the machine had been
# idle took 14s all by itself. 12s was tight enough to turn that first slow
# answer into "timed out waiting for account/rateLimits/read" and then a full
# ERROR snapshot, which shows up as a phantom dead account in the header.
RESPONSE_WINDOW_S = 25.0

# Windows. Codex varies the window set by plan: Plus reports 300 (5h) plus
# 10080 (weekly); Free reports a single 43200 (30-day) primary. Durations
# outside this map are NOT dropped — they get a generic ``window_<n>m`` key,
# so a real quota is never silently discarded as "unavailable".
DURATION_LABELS = {300: "five_hour", 10080: "weekly", 43200: "monthly"}


class JsonRpcError(Exception):
    pass


# -- live child registry ---------------------------------------------------
# A probe owns a real ``codex app-server`` child plus the reader thread that
# drains its stdout. Shutdown has to reach both: cancelling a future only
# stops probes that never started, while a running one sits in ``call()``
# polling for a response and its worker thread cannot unwind until the child
# is gone. Every live child is therefore registered the moment it is spawned
# so ``terminate_probe_processes`` can close the whole set from outside.
_procs_lock = threading.Lock()
_probe_procs: dict[subprocess.Popen, threading.Thread | None] = {}


def register_probe_process(proc: subprocess.Popen) -> None:
    """Record a freshly spawned probe child. Called before any I/O on it."""
    with _procs_lock:
        _probe_procs.setdefault(proc, None)


def attach_probe_reader(proc: subprocess.Popen,
                        reader: threading.Thread) -> None:
    """Bind the stdout reader thread to its child, registering if needed.

    Registration is unconditional: a session owns its child no matter who
    spawned it, so no caller can forget to register and leak a live process.
    """
    with _procs_lock:
        _probe_procs[proc] = reader


def unregister_probe_process(proc: subprocess.Popen) -> None:
    """Drop a child that finished normally. Safe to call more than once."""
    with _procs_lock:
        _probe_procs.pop(proc, None)


def live_probe_processes() -> list[subprocess.Popen]:
    """Snapshot of currently registered probe children."""
    with _procs_lock:
        return list(_probe_procs)


def _close_pipes(proc: subprocess.Popen) -> None:
    for stream in (proc.stdin, proc.stdout, proc.stderr):
        if stream is None:
            continue
        try:
            stream.close()
        except Exception:
            pass


def _stop_process(proc: subprocess.Popen, grace_s: float) -> bool:
    """terminate -> grace -> kill -> reap -> close pipes.

    W2-006 (audit/10): returns the POST-condition, not the pre-state. ``True``
    only when ``proc.poll()`` proves the child is no longer running after the
    terminate/kill/reap attempts. A stubborn child whose kill/wait all fail
    returns ``False`` and MUST stay registered so a later bounded pass can
    retry it (previously the pre-attempt ``was_alive`` was returned, so a
    provably live process was reported stopped and erased from the registry).
    """
    was_alive = proc.poll() is None
    if was_alive:
        try:
            proc.terminate()
        except Exception:
            pass
        try:
            proc.wait(timeout=grace_s)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
            try:
                proc.wait(timeout=grace_s)
            except Exception:
                pass
    else:
        try:
            proc.wait(timeout=0)
        except Exception:
            pass
    _close_pipes(proc)
    # Confirmed exit is the source of truth; the child must be genuinely gone.
    return proc.poll() is not None


def terminate_probe_processes(grace_s: float = CANCEL_GRACE_S,
                              passes: int = 3) -> int:
    """Stop every registered probe child and join its reader thread.

    Repeated passes cover the narrow race where a coordinator was already
    inside ``Popen`` when cancellation began: the caller has already refused
    new work, so the set drains within a couple of rounds. Bounded by
    construction — never blocks longer than ``passes * 2 * grace_s`` per
    child. Returns how many children were still running.

    W2-006: a child is unregistered ONLY once confirmed dead (or its reader
    has retired). An unresolved child stays registered for the next pass, so
    it cannot be silently lost while still alive.
    """
    stopped = 0
    for _ in range(max(1, passes)):
        with _procs_lock:
            batch = list(_probe_procs.items())
        if not batch:
            break
        for proc, reader in batch:
            confirmed_dead = _stop_process(proc, grace_s)
            if confirmed_dead:
                stopped += 1
            # Closing the child's stdout ends ``readline``, so the reader
            # returns on its own; the join only confirms it.
            reader_alive = reader is not None and reader.is_alive()
            if reader_alive:
                reader.join(timeout=grace_s)
                reader_alive = reader.is_alive()
            if confirmed_dead and not reader_alive:
                with _procs_lock:
                    _probe_procs.pop(proc, None)
            # else: keep it registered; a later pass retries it.
    return stopped


class AppServerSession:
    """Minimal JSON-RPC 2.0 client over stdio for ``codex app-server``."""

    def __init__(self, proc: subprocess.Popen, label: str):
        self.proc = proc
        self.label = label
        self._next_id = 1
        self._lock = threading.Lock()
        self._responses: dict[int, dict] = {}
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()
        attach_probe_reader(proc, self._reader)

    def _read_loop(self) -> None:
        if self.proc.stdout is None:
            return
        try:
            for line in iter(self.proc.stdout.readline, b""):
                if not line:
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line.decode("utf-8", errors="replace"))
                except Exception:
                    continue
                if isinstance(msg, dict) and "id" in msg:
                    with self._lock:
                        self._responses[msg["id"]] = msg
        except Exception:
            pass

    def call(self, method: str, params=None, timeout: float = RESPONSE_WINDOW_S) -> dict:
        with self._lock:
            rid = self._next_id
            self._next_id += 1
        req = {"jsonrpc": "2.0", "id": rid, "method": method}
        if params is not None:
            req["params"] = params
        data = (json.dumps(req) + "\n").encode("utf-8")
        if self.proc.stdin is None:
            raise JsonRpcError(f"{self.label}: no stdin")
        self.proc.stdin.write(data)
        self.proc.stdin.flush()
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self._lock:
                if rid in self._responses:
                    return self._responses.pop(rid)
            time.sleep(READ_STEP_S)
        raise JsonRpcError(f"{self.label}: timed out waiting for {method}")

    def notify(self, method: str, params=None) -> None:
        req = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            req["params"] = params
        data = (json.dumps(req) + "\n").encode("utf-8")
        if self.proc.stdin is not None:
            self.proc.stdin.write(data)
            self.proc.stdin.flush()

    def close(self) -> None:
        try:
            if self.proc.stdin:
                self.proc.stdin.close()
        except Exception:
            pass
        try:
            self.proc.wait(timeout=CHILD_KILL_GRACE_S)
        except Exception:
            _stop_process(self.proc, CHILD_KILL_GRACE_S)
        else:
            _close_pipes(self.proc)
        reader_alive = self._reader.is_alive()
        if reader_alive:
            self._reader.join(timeout=CHILD_KILL_GRACE_S)
            reader_alive = self._reader.is_alive()
        # W2-006 (audit/10): unregister only on CONFIRMED retirement -- a child
        # still alive or a reader still active must stay registered so a later
        # bounded pass can retry it.
        if self.proc.poll() is not None and not reader_alive:
            unregister_probe_process(self.proc)


@functools.lru_cache(maxsize=1)
def _resolve_codex_cmd() -> str:
    if os.name != "nt":
        return "codex"
    for name in ("codex.cmd", "codex.exe", "codex.bat"):
        for base in os.environ.get("PATH", "").split(os.pathsep):
            if not base:
                continue
            cand = os.path.join(base, name)
            if os.path.isfile(cand):
                return cand
    return "codex.cmd"


def _start_app_server(codex_home: str, label: str,
                      codex_cmd: str | None = None) -> AppServerSession:
    env = os.environ.copy()
    env["CODEX_HOME"] = codex_home
    for k in ("OPENAI_API_KEY", "CODEX_API_KEY", "CODEX_ACCESS_TOKEN"):
        env.pop(k, None)
    creationflags = silent_creationflags()
    cmd = codex_cmd or _resolve_codex_cmd()
    proc = subprocess.Popen(
        [cmd, "app-server", "--stdio"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL, env=env,
        creationflags=creationflags, startupinfo=silent_startupinfo(),
        bufsize=-1, text=False,
    )
    # Registered before the session exists: if the wrapper itself raises, the
    # child is still reachable for termination instead of leaking.
    register_probe_process(proc)
    try:
        return AppServerSession(proc, label)
    except BaseException:
        _stop_process(proc, CANCEL_GRACE_S)
        unregister_probe_process(proc)
        raise


def _handshake_and_read_rates(session: AppServerSession) -> dict:
    init = session.call("initialize", {
        "clientInfo": {"name": "fastprompter", "version": "1.0.0"},
        "capabilities": None,
    }, timeout=RESPONSE_WINDOW_S)
    if "error" in init:
        raise JsonRpcError(f"initialize error: {init['error']}")
    session.notify("initialized")
    rl = session.call("account/rateLimits/read", timeout=RESPONSE_WINDOW_S)
    if "error" in rl:
        raise JsonRpcError(f"rateLimits error: {rl['error']}")
    return rl.get("result") or {}


KNOWN_POOL_LABELS = {
    "codex": "Codex",
    "luna": "Luna",
    "reserve": "Reserve",
}


def _humanize(raw) -> str:
    """Vendor identifier -> readable label, deterministically.

    ``gpt-reserve`` -> ``GPT Reserve``, ``base_model_inference`` ->
    ``Base Model Inference``. Words the vendor already capitalised are kept
    verbatim so a real product name is never title-cased into nonsense.
    """
    import re as _re
    text = str(raw or "").strip()
    if not text:
        return ""
    words = [w for w in _re.split(r"[_\-.\s]+", text) if w]
    return " ".join(_capitalize_word(w) for w in words)


# Words that are proper acronyms, not names to capitalise: title-casing them
# produced "Gpt Reserve" and "Api Quota".
_ACRONYMS = frozenset({"gpt", "ai", "llm", "api", "ui", "db", "cpu", "gpu"})


def _capitalize_word(word: str) -> str:
    if word.lower() in _ACRONYMS:
        return word.upper()
    if any(c.isupper() for c in word):
        return word
    return word.capitalize()


def _pool_label(limit_id: str, limit_name) -> str:
    """Sanitized human label for one quota pool.

    The vendor's own ``limitName`` wins when present; ``KNOWN_POOL_LABELS`` is
    only a display fallback for the canonical pool names and is never evidence
    of what a pool actually serves (the model slug is).
    """
    named = _humanize(limit_name)
    if named:
        return named
    return KNOWN_POOL_LABELS.get(str(limit_id).lower()) or _humanize(limit_id)


def _blank_bucket() -> dict:
    return {
        "available": False,
        "remaining_percent": None,
        "resets_at": None,
        "used_percent": None,
        "window_duration_mins": None,
        "group": "",
        "group_label": "",
        "model_slug": "",
    }


def _duration_label(dur) -> str:
    """Known duration -> stable key; unknown -> generic ``window_<n>m``.

    An unrecognised duration is still a real quota the server told us about,
    so it must survive parsing instead of vanishing as "unavailable".
    """
    try:
        n = int(dur)
    except (TypeError, ValueError):
        return ""
    if n <= 0:
        return ""
    return DURATION_LABELS.get(n) or f"window_{n}m"


def parse_windows(rate_limits: dict) -> dict:
    """Map windows by duration and pool; missing buckets stay unavailable.

    Returns a flat ``{window_key: bucket}`` dict plus ``plan_type``.
    Supports multi-pool quotas via ``rateLimitsByLimitId`` (e.g. Codex,
    Luna, Reserve) while preserving the default top-level ``rateLimits``
    when by_id is absent or unpopulated.
    """
    out = {}
    snap = rate_limits.get("rateLimits") or {}
    by_id = rate_limits.get("rateLimitsByLimitId")
    has_by_id = isinstance(by_id, dict) and bool(by_id)
    codex_in_by_id = has_by_id and any(str(k).lower() == "codex" for k in by_id)

    # Top-level rateLimits is parsed when by_id is absent or when by_id does not contain codex
    if not has_by_id or not codex_in_by_id:
        if not has_by_id:
            out["five_hour"] = _blank_bucket()
            out["weekly"] = _blank_bucket()
        candidates: list[tuple[int | None, dict]] = []
        primary, secondary = snap.get("primary"), snap.get("secondary")
        if isinstance(primary, dict):
            candidates.append((primary.get("windowDurationMins"), primary))
        if isinstance(secondary, dict):
            candidates.append((secondary.get("windowDurationMins"), secondary))
        for dur, w in candidates:
            label = _duration_label(dur)
            if not label:
                continue
            if out.get(label, {}).get("available"):
                continue   # first match wins
            used = w.get("usedPercent")
            rem = None
            has_used = isinstance(used, (int, float))
            if has_used:
                rem = max(0.0, min(100.0, 100.0 - float(used)))
            out[label] = {
                "available": has_used,
                "remaining_percent": rem,
                "resets_at": _iso_from_epoch(w.get("resetsAt")),
                "used_percent": float(used) if has_used else None,
                "window_duration_mins": dur,
                "group": "",
                "group_label": "",
                "model_slug": "",
            }

    if has_by_id:
        for limit_id, sub in by_id.items():
            if not isinstance(sub, dict):
                continue
            group = str(limit_id)
            group_label = _pool_label(group, sub.get("limitName"))
            slug = str(sub.get("normalModelSlug") or "")
            for wkey in ("primary", "secondary"):
                w = sub.get(wkey)
                if not isinstance(w, dict):
                    continue
                dur = w.get("windowDurationMins")
                base_label = _duration_label(dur)
                if not base_label:
                    continue
                qkey = qualified_key(base_label, group)
                if out.get(qkey, {}).get("available"):
                    continue   # first match wins within pool
                used = w.get("usedPercent")
                rem = None
                has_used = isinstance(used, (int, float))
                if has_used:
                    rem = max(0.0, min(100.0, 100.0 - float(used)))
                out[qkey] = {
                    "available": has_used,
                    "remaining_percent": rem,
                    "resets_at": _iso_from_epoch(w.get("resetsAt")),
                    "used_percent": float(used) if has_used else None,
                    "window_duration_mins": dur,
                    "group": group,
                    "group_label": group_label,
                    "model_slug": slug,
                }

    if not out:
        out = {"five_hour": _blank_bucket(), "weekly": _blank_bucket()}

    plan_type = snap.get("planType")
    if not plan_type and has_by_id:
        for sub in by_id.values():
            if isinstance(sub, dict) and sub.get("planType"):
                plan_type = sub.get("planType")
                break
    out["plan_type"] = plan_type
    reset_credits = rate_limits.get("rateLimitResetCredits")
    if isinstance(reset_credits, dict):
        cnt = reset_credits.get("availableCount")
        credits_raw = reset_credits.get("credits")
        credits_list = []
        if isinstance(credits_raw, list):
            for c in credits_raw:
                if not isinstance(c, dict):
                    continue
                credits_list.append({
                    "id": str(c.get("id") or ""),
                    "status": str(c.get("status") or ""),
                    "title": str(c.get("title") or ""),
                    "description": str(c.get("description") or ""),
                    "reset_type": str(c.get("resetType") or ""),
                    "granted_at": c.get("grantedAt"),
                    "expires_at": c.get("expiresAt"),
                })
        if cnt is None and credits_list:
            cnt = sum(1 for c in credits_list if c.get("status") == "available")
        try:
            out["banked_resets"] = int(cnt) if cnt is not None else None
        except (TypeError, ValueError):
            out["banked_resets"] = None
        if credits_list:
            out["reset_credits"] = credits_list
    else:
        out["banked_resets"] = None
        out["reset_credits"] = []
    return out


def _iso_from_epoch(val) -> str | None:
    if val is None:
        return None
    try:
        f = float(val)
    except Exception:
        return None
    import datetime as _dt
    try:
        return _dt.datetime.fromtimestamp(f, _dt.UTC).isoformat()
    except Exception:
        return None


def probe_codex_home(codex_home: str, deadline: float | None = None,
                     codex_cmd: str | None = None) -> dict | None:
    """Probe one Codex account home. Returns a parsed snapshot dict,
    ``None`` when the absolute period has expired, or ``{"ok": False, ...}``
    on any normal failure.

    ``deadline`` is a monotic epoch.  The function MUST return before it
    expires; a hung child is reported as `{"ok": False, "error": ...}`.
    """
    if deadline is None:
        deadline = time.monotonic() + 15.0
    codex_home = str(codex_home)
    if not os.path.isdir(codex_home):
        return {"ok": False, "error": f"CODEX_HOME missing: {codex_home}",
                "five_hour": {"available": False}, "weekly": {"available": False}}

    session = None
    expected_account_id = None
    auth_path = os.path.join(codex_home, "auth.json")
    if os.path.isfile(auth_path):
        try:
            with open(auth_path, encoding="utf-8") as f:
                auth_doc = json.load(f)
                if isinstance(auth_doc, dict):
                    tokens = auth_doc.get("tokens") or {}
                    if isinstance(tokens, dict):
                        expected_account_id = tokens.get("account_id")
        except Exception:
            pass

    try:
        if time.monotonic() >= deadline:
            return None
        session = _start_app_server(codex_home, codex_home, codex_cmd=codex_cmd)
        remaining = deadline - time.monotonic()
        init = session.call(
            "initialize",
            {
                "clientInfo": {"name": "fastprompter", "version": "1.0.0"},
                "capabilities": None,
            },
            timeout=min(RESPONSE_WINDOW_S, max(0.1, remaining)),
        )
        if "error" in init:
            raise JsonRpcError(f"initialize error: {init['error']}")
        session.notify("initialized")
        remaining = deadline - time.monotonic()
        acct_res = {}
        try:
            acct_call = session.call(
                "account/read",
                {},
                timeout=min(RESPONSE_WINDOW_S, max(0.1, remaining)),
            )
            if isinstance(acct_call, dict) and "result" in acct_call:
                acct_res = acct_call.get("result") or {}
        except Exception:
            pass

        remaining = deadline - time.monotonic()
        rl = session.call(
            "account/rateLimits/read",
            {},
            timeout=min(RESPONSE_WINDOW_S, max(0.1, remaining)),
        )
        if time.monotonic() > deadline:
            return None
        if "error" in rl:
            raise JsonRpcError(f"rateLimits error: {rl['error']}")
        result = rl.get("result") or {}

        # Identity verification
        probed_account_id = result.get("accountId")
        if not probed_account_id and isinstance(acct_res.get("workspaceRouting"), dict):
            probed_account_id = acct_res["workspaceRouting"].get("chatgptAccountId")

        email = ""
        if isinstance(acct_res.get("account"), dict):
            email = str(acct_res["account"].get("email") or "")

        if expected_account_id and probed_account_id:
            if str(expected_account_id).strip().lower() != str(probed_account_id).strip().lower():
                return {
                    "ok": False,
                    "status": "IDENTITY_MISMATCH",
                    "error": f"Identity mismatch: expected {expected_account_id}, got {probed_account_id}",
                    "expected_account_id": expected_account_id,
                    "probed_account_id": probed_account_id,
                    "five_hour": {"available": False},
                    "weekly": {"available": False},
                }

        parsed = parse_windows(result)
        # Every detected window ships through verbatim — the provider decides
        # how many to render, the probe must not pre-filter the set.
        payload = {"ok": True}
        for key, bucket in parsed.items():
            if key in ("plan_type", "banked_resets", "reset_credits"):
                continue
            payload[key] = bucket
        payload["plan_type"] = parsed.get("plan_type") or (
            acct_res.get("account", {}).get("planType") if isinstance(acct_res.get("account"), dict) else None
        )
        payload["banked_resets"] = parsed.get("banked_resets")
        payload["reset_credits"] = parsed.get("reset_credits", [])
        payload["codex_home"] = codex_home
        payload["codex_account_id"] = probed_account_id or expected_account_id
        payload["codex_email"] = email
        payload["fetched_at"] = time.time()
        return payload
    except JsonRpcError as exc:
        err_str = str(exc)[:160]
        status = "AUTH_REQUIRED" if any(w in err_str.lower() for w in ("unauthorized", "401", "authentication", "auth required")) else "ERROR"
        return {"ok": False, "status": status, "error": err_str,
                "five_hour": {"available": False}, "weekly": {"available": False}}
    except Exception as exc:
        return {"ok": False, "status": "ERROR", "error": f"{type(exc).__name__}: {exc}"[:120],
                "five_hour": {"available": False}, "weekly": {"available": False}}
    finally:
        if session is not None:
            session.close()


def consume_codex_reset(codex_home: str, credit_id: str | None = None,
                        deadline: float | None = None,
                        codex_cmd: str | None = None) -> dict:
    """Consume one banked rate limit reset credit via Codex app-server.

    Sends account/rateLimitResetCredit/consume with an idempotencyKey and optional creditId.
    Returns {"ok": True, "outcome": outcome} on success, or {"ok": False, "error": msg}.
    """
    if deadline is None:
        deadline = time.monotonic() + 15.0
    codex_home = str(codex_home)
    if not os.path.isdir(codex_home):
        return {"ok": False, "error": f"CODEX_HOME missing: {codex_home}"}

    import uuid
    idempotency_key = str(uuid.uuid4())
    params: dict[str, str] = {"idempotencyKey": idempotency_key}
    if credit_id:
        params["creditId"] = str(credit_id)

    session = None
    try:
        if time.monotonic() >= deadline:
            return {"ok": False, "error": "deadline exceeded before starting"}
        session = _start_app_server(codex_home, f"{codex_home}:consume", codex_cmd=codex_cmd)
        remaining = deadline - time.monotonic()
        init = session.call(
            "initialize",
            {
                "clientInfo": {"name": "fastprompter", "version": "1.0.0"},
                "capabilities": None,
            },
            timeout=min(RESPONSE_WINDOW_S, max(0.1, remaining)),
        )
        if "error" in init:
            raise JsonRpcError(f"initialize error: {init['error']}")
        session.notify("initialized")
        remaining = deadline - time.monotonic()
        res = session.call(
            "account/rateLimitResetCredit/consume",
            params,
            timeout=min(RESPONSE_WINDOW_S, max(0.1, remaining)),
        )
        if "error" in res:
            err_msg = res["error"].get("message") if isinstance(res["error"], dict) else str(res["error"])
            return {"ok": False, "error": f"consume error: {err_msg}"}
        result = res.get("result") or {}
        outcome = result.get("outcome") or "success"
        if outcome in ("noCredit", "alreadyRedeemed", "nothingToReset", "unauthorized"):
            return {"ok": False, "error": f"outcome: {outcome}", "outcome": outcome}
        return {"ok": True, "outcome": outcome}
    except JsonRpcError as exc:
        return {"ok": False, "error": str(exc)[:160]}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {str(exc)[:160]}"}
    finally:
        if session is not None:
            session.close()

