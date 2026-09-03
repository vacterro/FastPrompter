"""Low-level Codex app-server probe with a true hard deadline.

This is the engine half of the Codex provider, refactored from
``core/codex_limits.py`` (LIMISAW port) to obey an absolute deadline
across spawn/handshake/read/close, and to drain stderr so a noisy child
can never block the pipe.
"""

from __future__ import annotations

import json
import os
import subprocess
import threading
import time

# Tunables
READ_STEP_S = 0.02
CHILD_KILL_GRACE_S = 2.0
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
            try:
                self.proc.kill()
            except Exception:
                pass


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
    creationflags = 0x08000000 if os.name == "nt" else 0  # CREATE_NO_WINDOW
    cmd = codex_cmd or _resolve_codex_cmd()
    proc = subprocess.Popen(
        [cmd, "app-server", "--stdio"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL, env=env,
        creationflags=creationflags, bufsize=-1, text=False,
    )
    return AppServerSession(proc, label)


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


def _blank_bucket() -> dict:
    return {"available": False, "remaining_percent": None,
            "resets_at": None, "used_percent": None,
            "window_duration_mins": None}


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
    """Map windows by duration; missing buckets stay unavailable.

    Returns a flat ``{window_key: bucket}`` dict plus ``plan_type``. Callers
    iterate the dict and skip ``plan_type`` — that way a plan reporting an
    unexpected window count (Free: one 30-day window) is preserved verbatim
    instead of being filtered down to a hardcoded pair.
    """
    out = {"five_hour": _blank_bucket(), "weekly": _blank_bucket()}
    snap = rate_limits.get("rateLimits") or {}

    candidates: list[tuple[int | None, dict]] = []
    primary, secondary = snap.get("primary"), snap.get("secondary")
    if isinstance(primary, dict):
        candidates.append((primary.get("windowDurationMins"), primary))
    if isinstance(secondary, dict):
        candidates.append((secondary.get("windowDurationMins"), secondary))
    by_id = rate_limits.get("rateLimitsByLimitId")
    if isinstance(by_id, dict):
        for sub in by_id.values():
            if not isinstance(sub, dict):
                continue
            for key in ("primary", "secondary"):
                w = sub.get(key)
                if isinstance(w, dict):
                    candidates.append((w.get("windowDurationMins"), w))

    for dur, w in candidates:
        label = _duration_label(dur)
        if not label:
            continue
        if out.get(label, {}).get("available"):
            continue   # first match wins
        used = w.get("usedPercent")
        rem = None
        if isinstance(used, (int, float)):
            rem = max(0, min(100, 100 - used))
        out[label] = {
            "available": True,
            "remaining_percent": rem,
            "resets_at": _iso_from_epoch(w.get("resetsAt")),
            "used_percent": used if isinstance(used, (int, float)) else None,
            "window_duration_mins": dur,
        }
    out["plan_type"] = snap.get("planType")
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
        return _dt.datetime.fromtimestamp(f).strftime("%Y-%m-%dT%H:%M:%S")
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
        rl = session.call(
            "account/rateLimits/read",
            timeout=min(RESPONSE_WINDOW_S, max(0.1, remaining)),
        )
        if time.monotonic() > deadline:
            return None
        if "error" in rl:
            raise JsonRpcError(f"rateLimits error: {rl['error']}")
        result = rl.get("result") or {}
        parsed = parse_windows(result)
        # Every detected window ships through verbatim — the provider decides
        # how many to render, the probe must not pre-filter the set.
        payload = {"ok": True}
        for key, bucket in parsed.items():
            if key == "plan_type":
                continue
            payload[key] = bucket
        payload["plan_type"] = parsed.get("plan_type")
        payload["fetched_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        return payload
    except JsonRpcError as exc:
        return {"ok": False, "error": str(exc)[:160],
                "five_hour": {"available": False}, "weekly": {"available": False}}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"[:120],
                "five_hour": {"available": False}, "weekly": {"available": False}}
    finally:
        if session is not None:
            session.close()
