"""Tests for fastprompter.core.watcher.limit_scan.

Every test drives a fake socket, so the sweep is exercised with no agent
running and nothing is ever typed into a real window.
"""

import datetime
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

from fastprompter.core.watcher.limit_scan import (  # noqa: E402
    AgentLimit,
    limited,
    scan_agent,
    scan_all,
)

NOW = datetime.datetime(2026, 7, 22, 14, 30)


class FakeWs:
    def __init__(self, text="", fail=None):
        self.text = text
        self.fail = fail
        self.closed = False

    def call(self, method, params=None, max_messages=60):
        if self.fail:
            raise RuntimeError(self.fail)
        if method == "Runtime.evaluate":
            return {"result": {"value": self.text}}
        return {}

    def close(self):
        self.closed = True


class FakeTarget:
    ws_url = "ws://127.0.0.1:1/devtools/page/P1"


class FakeAdapter:
    def __init__(self, name="agent", transport="cdp", port=9333, enabled=True):
        self.name = name
        self.transport = transport
        self.cdp_port = port
        self.cdp_title = ""
        self.enabled = enabled

    def live_cdp_port(self):
        return self.cdp_port


def scan(text, **kw):
    ws = FakeWs(text)
    result = scan_agent(FakeAdapter(), connect=lambda url: ws,
                        target_fn=lambda port, title: FakeTarget(), now=NOW,
                        **kw)
    return result, ws


# ------------------------------------------------------------------ reading

def test_a_limited_agent_is_reported_with_its_reset_time():
    result, _ws = scan("chat...\n5-hour limit reached ∙ resets 6pm")
    assert result.reachable is True
    assert result.state.reached is True
    assert result.state.resets_at == NOW.replace(hour=18, minute=0)


def test_a_working_agent_reads_clear():
    result, _ws = scan("Agent: build\nDONE\nready for the next task")
    assert result.reachable is True
    assert result.state.reached is False


def test_the_socket_is_always_closed():
    _result, ws = scan("anything")
    assert ws.closed is True


def test_a_socket_that_refuses_is_an_answer_not_a_crash():
    ws = FakeWs(fail="connection reset")
    result = scan_agent(FakeAdapter(), connect=lambda url: ws,
                        target_fn=lambda port, title: FakeTarget(), now=NOW)
    assert result.reachable is False
    assert "connection reset" in result.error


def test_an_agent_that_is_not_listening_says_so():
    """With no store to fall back to, a shut agent is 'no answer' - and the
    reason names it, so the UI never has to show a blank."""
    result = scan_agent(FakeAdapter(), connect=lambda url: FakeWs(),
                        target_fn=lambda port, title: None, now=NOW)
    assert result.reachable is False
    assert "not running" in result.error


def test_a_non_cdp_agent_is_skipped_with_a_reason():
    """post-transport agents have no page to read; saying why beats a blank."""
    result = scan_agent(FakeAdapter(transport="post"), now=NOW)
    assert result.reachable is False
    assert "debugger" in result.error


def test_an_agent_with_no_port_is_not_probed():
    result = scan_agent(FakeAdapter(port=0), now=NOW)
    assert result.reachable is False
    assert "no debug port" in result.error


def test_empty_page_text_is_reported_rather_than_read_as_clear():
    """A blank read means the probe failed, not that the agent is fine -
    reporting it as clear would let a queue fire into a limited agent."""
    result, _ws = scan("")
    assert result.reachable is False
    assert "no readable text" in result.error


# -------------------------------------------------------------- the sweep

def test_the_sweep_covers_every_enabled_adapter():
    adapters = [FakeAdapter("a"), FakeAdapter("b"), FakeAdapter("c")]
    results = scan_all(adapters, connect=lambda url: FakeWs("all good"),
                       target_fn=lambda port, title: FakeTarget(), now=NOW)
    assert [r.name for r in results] == ["a", "b", "c"]


def test_disabled_adapters_are_left_out():
    adapters = [FakeAdapter("on"), FakeAdapter("off", enabled=False)]
    results = scan_all(adapters, connect=lambda url: FakeWs("fine"),
                       target_fn=lambda port, title: FakeTarget(), now=NOW)
    assert [r.name for r in results] == ["on"]


def test_one_broken_agent_does_not_stop_the_sweep():
    calls = {"n": 0}

    def flaky(url):
        calls["n"] += 1
        if calls["n"] == 2:
            raise OSError("that one is down")
        return FakeWs("limit reached, resets at 20:00")

    results = scan_all([FakeAdapter("a"), FakeAdapter("b"), FakeAdapter("c")],
                       connect=flaky,
                       target_fn=lambda port, title: FakeTarget(), now=NOW)
    assert len(results) == 3
    assert results[1].reachable is False
    assert results[0].state.reached and results[2].state.reached


def test_limited_filters_to_the_ones_actually_capped():
    results = [
        AgentLimit("clear"),
        AgentLimit("down", error="unreachable"),
    ]
    hit, _ws = scan("daily free limit reached. come back after the daily reset")
    results.append(hit)
    assert [r.name for r in limited(results)] == [hit.name]


# ------------------------------------------------- reading the store on disk


def _store(tmp_path, rows):
    """A sqlite store shaped like freebuff's: text plus a unix timestamp."""
    import sqlite3

    db = tmp_path / "agent.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE messages(seq INTEGER, role TEXT, "
                 "text TEXT, ts INTEGER)")
    for i, (text, stamp) in enumerate(rows):
        conn.execute("INSERT INTO messages VALUES (?,?,?,?)",
                     (i, "assistant", text, int(stamp)))
    conn.commit()
    conn.close()
    return str(db)


def _disk_adapter(db):
    from fastprompter.core.watcher.adapter import Adapter
    from fastprompter.core.watcher.probes import SqliteProbe

    return Adapter("shutdown-agent", probes=[SqliteProbe(db)], transport="post")


LIMIT = ("⚠️ Daily free limit reached for deepseek/deepseek-v4-flash. "
         "Come back after the daily reset.")


def test_a_fresh_limit_in_the_store_is_found_with_the_app_shut(tmp_path):
    """The point of reading the store: waiting for a reset is exactly when
    the agent is NOT running."""
    import time

    now = time.time()
    rows = [(f"msg {i} working fine", now - 3600 + i) for i in range(200)]
    rows.append((LIMIT, now - 60))
    result = scan_agent(_disk_adapter(_store(tmp_path, rows)))

    assert result.reachable is True
    assert result.state.reached is True
    assert "store on disk" in result.state.source


def test_a_stale_limit_is_not_reported_as_current(tmp_path):
    """freebuff's real one was 28 hours old and its daily window had already
    reset - announcing it would name a limit that no longer exists."""
    import time

    now = time.time()
    rows = [(LIMIT, now - 28 * 3600), ("back to normal", now - 27 * 3600)]
    result = scan_agent(_disk_adapter(_store(tmp_path, rows)))

    assert result.state.reached is False


def test_rows_with_no_readable_time_are_dropped(tmp_path):
    """An unknown age is not evidence of being recent."""
    import sqlite3

    db = tmp_path / "notime.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE messages(text TEXT)")
    conn.execute("INSERT INTO messages VALUES (?)", (LIMIT,))
    conn.commit()
    conn.close()

    result = scan_agent(_disk_adapter(str(db)))
    assert result.state.reached is False
    assert result.reachable is False, "nothing recent to read is 'no answer'"


def test_milliseconds_timestamps_are_understood(tmp_path):
    """Some stores write ms, some seconds; the value says which."""
    import time

    now = time.time()
    rows = [(LIMIT, int(now * 1000) - 60_000)]
    result = scan_agent(_disk_adapter(_store(tmp_path, rows)))
    assert result.state.reached is True


def test_the_live_page_is_preferred_over_the_store(tmp_path):
    """What the user is looking at wins; the store is the fallback."""
    import time

    now = time.time()
    db = _store(tmp_path, [(LIMIT, now - 60)])

    from fastprompter.core.watcher.adapter import Adapter
    from fastprompter.core.watcher.probes import SqliteProbe

    adapter = Adapter("live-one", probes=[SqliteProbe(db)], transport="cdp",
                      cdp_port=9333)
    result = scan_agent(adapter, connect=lambda url: FakeWs("all good here"),
                        target_fn=lambda port, title: FakeTarget(), now=NOW)

    assert result.state.reached is False, "the live page said it was fine"
    assert "store on disk" not in (result.state.source or "")


def test_a_shut_agent_falls_back_to_its_store(tmp_path):
    import time

    now = time.time()
    db = _store(tmp_path, [(LIMIT, now - 60)])

    from fastprompter.core.watcher.adapter import Adapter
    from fastprompter.core.watcher.probes import SqliteProbe

    adapter = Adapter("shut-one", probes=[SqliteProbe(db)], transport="cdp",
                      cdp_port=9333)
    result = scan_agent(adapter, connect=lambda url: FakeWs(""),
                        target_fn=lambda port, title: None)

    assert result.state.reached is True
    assert "store on disk" in result.state.source
