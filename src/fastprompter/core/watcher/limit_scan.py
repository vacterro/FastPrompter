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
_TEXT_JS = """
(function() {
    function getAllText(node) {
        if (!node) return '';
        let text = '';
        if (node.nodeType === 3) {
            text += node.textContent + ' ';
        } else {
            if (node.shadowRoot) text += getAllText(node.shadowRoot) + ' ';
            if (node.childNodes) {
                for (let child of node.childNodes) text += getAllText(child);
            }
        }
        return text;
    }
    return (document.body ? document.body.innerText + ' ' : '') + getAllText(document.body);
})()
"""


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


def _row_epoch(row):
    """A plausible unix timestamp among a row's numbers, or None.

    Stores keep the time in a column whose name varies (ts, created_at,
    updated); the VALUE is recognisable where the name is not — seconds or
    milliseconds inside a sane range.
    """
    import time as _t

    now = _t.time()
    best = None
    for value in row:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        v = float(value)
        if v > 1e11:          # milliseconds
            v /= 1000.0
        if 1_500_000_000 < v <= now + 86_400:      # 2017..tomorrow
            best = v if best is None else max(best, v)
    return best


def read_agent_text_on_disk(adapter, tail=400, max_age_hours=6.0, now=None):
    """The agent's own words from its STORE, with the app shut.

    The probes an adapter already carries name where it writes. Freebuff, for
    one, keeps "Daily free limit reached ..." in its messages table, so the
    limit is answerable without launching anything.

    ONLY rows newer than `max_age_hours` are returned. A store keeps every
    limit message it ever wrote: freebuff's is a day old and its daily window
    has since reset, so reading it as current would announce a limit that no
    longer exists. Rows whose time cannot be read are dropped for the same
    reason — an unknown age is not evidence of being recent.

    Returns "" when nothing recent is readable; the caller treats that as
    "no answer", never as "clear".
    """
    import glob as _glob
    import os
    import sqlite3
    import time as _t

    cutoff = (now or _t.time()) - max_age_hours * 3600.0
    fresh = []

    for probe in getattr(adapter, "probes", ()) or ():
        kind = getattr(probe, "kind", "")
        if kind == "sqlite":
            path = os.path.expanduser(os.path.expandvars(
                getattr(probe, "path", "")))
            if not path or not os.path.isfile(path):
                continue
            try:
                conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True,
                                       timeout=1.0)
            except Exception:
                continue
            try:
                tables = [r[0] for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'")]
                for table in tables:
                    try:
                        rows = conn.execute(
                            f'SELECT * FROM "{table}" '
                            f"ORDER BY rowid DESC LIMIT {int(tail)}").fetchall()
                    except Exception:
                        continue
                    for row in rows:
                        stamp = _row_epoch(row)
                        if stamp is None or stamp < cutoff:
                            continue
                        text = " ".join(
                            str(v) for v in row if isinstance(v, str))
                        if text.strip():
                            fresh.append((stamp, text))
            finally:
                conn.close()
        elif kind == "file":
            pattern = os.path.expanduser(os.path.expandvars(
                getattr(probe, "pattern", "")))
            files = [f for f in _glob.glob(pattern) if os.path.isfile(f)]
            if not files:
                continue
            newest = max(files, key=os.path.getmtime)
            if os.path.getmtime(newest) < cutoff:
                continue          # the whole file is stale
            try:
                with open(newest, "rb") as fh:
                    fh.seek(0, os.SEEK_END)
                    size = fh.tell()
                    fh.seek(max(0, size - 60_000))
                    fresh.append((os.path.getmtime(newest),
                                  fh.read().decode("utf-8", "replace")))
            except OSError:
                continue

    # Oldest first, so scan_text's tail lands on the most recent words - and
    # only the last stretch of them. Six hours of a busy store is ~900k
    # characters; without this the newest rows are the only ones scan_text
    # would ever reach anyway, and a limit line would sit far outside its
    # window. Each row is clipped so one huge blob cannot crowd out the rest.
    fresh.sort(key=lambda pair: pair[0])
    recent = fresh[-120:]
    return "\n".join(text[:2000] for _stamp, text in recent)


def scan_agent(adapter, connect=None, target_fn=None, now=None,
               allow_disk=True):
    """One adapter -> AgentLimit. Never raises; unreachable is an answer.

    Tries the live page first, because that is what the user is looking at.
    Falls back to the agent's store on disk so a limit can still be found
    with the app shut - which is the normal case when you are waiting for a
    reset rather than working.
    """
    from fastprompter.core.watcher.cdp import CdpTarget

    name = getattr(adapter, "name", "agent")

    def from_disk(reason):
        if not allow_disk:
            return AgentLimit(name, error=reason)
        text = ""
        try:
            text = read_agent_text_on_disk(adapter)
        except Exception as exc:
            return AgentLimit(name, error=f"{reason}; store: {str(exc)[:40]}")
        if not text:
            return AgentLimit(name, error=reason)
        state = scan_text(text, now)
        state.source = (state.source or "") + " [from the store on disk]"
        return AgentLimit(name, state)

    if getattr(adapter, "transport", "post") != "cdp":
        return from_disk("not driven over the debugger")

    port = 0
    try:
        port = adapter.live_cdp_port()
    except Exception:
        port = getattr(adapter, "cdp_port", 0)
    if not port:
        return from_disk("no debug port")

    try:
        build = target_fn or CdpTarget.from_port
        target = build(port, getattr(adapter, "cdp_title", ""))
        if target is None:
            return from_disk("not running")
        text = read_agent_text(target, connect=connect)
    except Exception as exc:
        return from_disk(str(exc)[:60])

    if not text:
        return from_disk("no readable text")
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
