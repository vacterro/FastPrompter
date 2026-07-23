"""Asking every configured agent whether it is rate-limited right now.

Reads each agent's visible chat text over the debugger socket and runs it
through core.limits. No typing, no clicking — this only looks, so it is safe
to run on a timer while the user works.

The socket layer is injected, so the whole sweep is testable without an
agent running.
"""

from __future__ import annotations

import datetime

from fastprompter.core.limits import LimitState, scan_text

# innerText, not textContent: it skips hidden nodes, so an old limit banner
# the app has already collapsed does not read as current.
_TEXT_JS = "document.body ? document.body.innerText : ''"


class AgentLimit:
    """One agent's answer, plus how it was reached."""

    __slots__ = ("name", "state", "error", "port")

    def __init__(self, name, state=None, error="", port=0):
        self.name = name
        self.state = state or LimitState(False)
        self.error = error or ""
        self.port = port

    @property
    def reachable(self):
        return not self.error

    def __repr__(self):
        if self.error:
            return f"AgentLimit({self.name!r}, unreachable: {self.error})"
        return f"AgentLimit({self.name!r}, {self.state!r})"


def read_agent_text(target, connect=None, timeout=3.0):
    """The visible chat text of one debuggable page, or '' if unreachable."""
    from fastprompter.core.watcher.cdp import WebSocket

    if target is None or not getattr(target, "ws_url", ""):
        return ""
    connect = connect or (lambda url: WebSocket(url, timeout))
    ws = None
    try:
        ws = connect(target.ws_url)
        ws.call("Runtime.enable")
        result = ws.call("Runtime.evaluate",
                         {"expression": _TEXT_JS, "returnByValue": True})
        return result.get("result", {}).get("value") or ""
    finally:
        if ws is not None:
            try:
                ws.close()
            except Exception:
                pass


def scan_agent(adapter, connect=None, target_fn=None, now=None):
    """One adapter -> AgentLimit. Never raises; unreachable is an answer."""
    from fastprompter.core.watcher.cdp import CdpTarget

    name = getattr(adapter, "name", "agent")
    if getattr(adapter, "transport", "post") != "cdp":
        return AgentLimit(name, error="not driven over the debugger")

    port = 0
    try:
        port = adapter.live_cdp_port()
    except Exception:
        port = getattr(adapter, "cdp_port", 0)
    if not port:
        return AgentLimit(name, error="no debug port")

    try:
        build = target_fn or CdpTarget.from_port
        target = build(port, getattr(adapter, "cdp_title", ""))
        if target is None:
            return AgentLimit(name, error="not listening", port=port)
        text = read_agent_text(target, connect=connect)
    except Exception as exc:
        return AgentLimit(name, error=str(exc)[:80], port=port)

    if not text:
        return AgentLimit(name, error="no readable text", port=port)
    return AgentLimit(name, scan_text(text, now), port=port)


def scan_all(adapters, connect=None, target_fn=None, now=None):
    """Sweep every enabled adapter. Order follows the config."""
    now = now or datetime.datetime.now()
    out = []
    for adapter in adapters or ():
        if not getattr(adapter, "enabled", True):
            continue
        out.append(scan_agent(adapter, connect=connect,
                              target_fn=target_fn, now=now))
    return out


def limited(results):
    """Only the agents that actually reported a limit."""
    return [r for r in results if r.reachable and r.state.reached]
