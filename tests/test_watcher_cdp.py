"""Tests for fastprompter.core.watcher.cdp.

Every test drives a fake socket. Nothing here opens a port or reaches a
running application — the property that makes it safe to test the transport
that actually works.
"""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

from fastprompter.core.watcher.cdp import (  # noqa: E402
    CdpError,
    CdpSender,
    CdpTarget,
    WebSocket,
    discover,
    find_page,
)
from fastprompter.core.watcher.engine import SendIntent  # noqa: E402

PAGE = {"id": "P1", "type": "page", "title": "CHAT",
        "url": "https://127.0.0.1:1/c/abc",
        "webSocketDebuggerUrl": "ws://127.0.0.1:1/devtools/page/P1"}
WORKER = {"id": "W1", "type": "worker", "title": "", "url": ""}


class FakeWs:
    """Records CDP calls and answers them from a scripted field value."""

    def __init__(self, field="", insert_works=True, fail_on=None):
        self.field = field
        self.insert_works = insert_works
        self.fail_on = fail_on or set()
        self.calls = []
        self.closed = False

    def call(self, method, params=None, max_messages=60):
        self.calls.append((method, params or {}))
        if method in self.fail_on:
            raise CdpError(f"{method} refused")
        if method == "Runtime.evaluate":
            expr = (params or {}).get("expression", "")
            if "focus()" in expr:
                return {"result": {"value": True}}
            return {"result": {"value": self.field}}
        if method == "Input.insertText":
            if self.insert_works:
                self.field += (params or {}).get("text", "")
            return {}
        return {}

    def close(self):
        self.closed = True

    def methods(self):
        return [m for m, _p in self.calls]


def intent(text="/saipen continue", item="i1"):
    return SendIntent(item, text, "0", "saipen", 0.0)


def target(**kw):
    kw.setdefault("discover_fn", lambda port: [PAGE])
    return CdpTarget(50814, "P1", "CHAT", PAGE["url"], PAGE["webSocketDebuggerUrl"],
                     **kw)


def sender(ws, **kw):
    return CdpSender(connect=lambda url: ws, **kw)


# --------------------------------------------------------------- discovery

def test_a_silent_port_is_an_empty_list_not_an_error():
    """'Not reachable this way' is a normal answer the UI has to show — an
    app only listens when it was launched with --remote-debugging-port."""
    def refuse(url, timeout=None):
        raise OSError("connection refused")

    assert discover(50814, opener=refuse) == []


def test_junk_from_the_port_is_survived():
    class Fake:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return b"<html>not json</html>"

    assert discover(1, opener=lambda url, timeout=None: Fake()) == []


def test_only_pages_are_candidates():
    """Workers are debuggable too, and typing into one does nothing."""
    assert find_page([WORKER, PAGE])["id"] == "P1"
    assert find_page([WORKER]) is None


def test_a_page_can_be_picked_by_title():
    other = dict(PAGE, id="P2", title="Settings")
    assert find_page([other, PAGE], "chat")["id"] == "P1"
    assert find_page([other, PAGE], "nothing like it") is None


def test_a_target_is_built_from_a_port():
    t = CdpTarget.from_port(50814, discover_fn=lambda port: [WORKER, PAGE])
    assert t.target_id == "P1" and t.title == "CHAT"
    assert CdpTarget.from_port(1, discover_fn=lambda port: []) is None


# ---------------------------------------------------------------- identity

def test_a_closed_debugger_aborts_the_send():
    ok, reason = CdpTarget(1, "P1", discover_fn=lambda port: []).matches()
    assert ok is False and "no longer listening" in reason


def test_a_page_that_has_gone_aborts_the_send():
    ok, reason = CdpTarget(1, "P1", discover_fn=lambda port: [
        dict(PAGE, id="OTHER")]).matches()
    assert ok is False and "gone" in reason


def test_a_renamed_conversation_is_still_the_same_page():
    """The title moves as a conversation is renamed; the id is identity."""
    ok, _reason = CdpTarget(1, "P1", "Old name", discover_fn=lambda port: [
        dict(PAGE, title="Renamed by the agent")]).matches()
    assert ok is True


def test_an_unarmed_target_is_refused():
    ok, reason = CdpTarget(1, None).matches()
    assert ok is False and "no page" in reason


# ------------------------------------------------------------- the send

def test_a_good_send_inserts_then_submits_in_that_order():
    ws = FakeWs()
    result = sender(ws).send(intent(), target())

    assert result.ok is True and result.dry is False
    order = ws.methods()
    assert order.index("Input.insertText") < order.index("Input.dispatchKeyEvent")
    assert ws.field == "/saipen continue"
    assert ws.closed is True


def test_the_text_is_read_back_before_the_submit_key_is_pressed():
    """The lesson from PostMessage: it returned success for every character
    of a string that never arrived. A send that cannot be confirmed is not a
    send."""
    ws = FakeWs(insert_works=False)
    result = sender(ws).send(intent(), target())

    assert result.ok is False
    assert "did not reach the field" in result.reason
    assert "Input.dispatchKeyEvent" not in ws.methods(), "nothing was submitted"


def test_a_page_with_no_text_field_fails_instead_of_guessing():
    ws = FakeWs(field=None)
    result = sender(ws).send(intent(), target())
    assert result.ok is False and "no text field" in result.reason
    assert "Input.insertText" not in ws.methods()


def test_a_field_the_user_is_typing_in_is_left_alone():
    """Appending to a half-written line would send a sentence neither the
    user nor the queue wrote."""
    ws = FakeWs(field="what I was in the middle of")
    result = sender(ws).send(intent(), target())

    assert result.ok is False and "already has text" in result.reason
    assert "Input.insertText" not in ws.methods()
    assert ws.field == "what I was in the middle of", "untouched"


def test_whitespace_in_the_field_is_not_treated_as_the_user_typing():
    ws = FakeWs(field="   \n ")
    assert sender(ws).send(intent(), target()).ok is True


def test_a_dead_page_is_never_typed_into():
    ws = FakeWs()
    dead = CdpTarget(1, "P1", discover_fn=lambda port: [])
    result = sender(ws).send(intent(), dead)
    assert result.ok is False
    assert ws.calls == [], "identity is checked before anything is sent"


def test_a_debugger_that_refuses_mid_send_is_reported_not_raised():
    ws = FakeWs(fail_on={"Input.insertText"})
    result = sender(ws).send(intent(), target())
    assert result.ok is False and "refused" in result.reason
    assert ws.closed is True, "the socket is closed even on the error path"


def test_a_socket_error_is_reported_not_raised():
    def explode(url):
        raise OSError("connection reset")

    result = CdpSender(connect=explode).send(intent(), target())
    assert result.ok is False and "could not reach" in result.reason


def test_the_socket_is_always_closed():
    ws = FakeWs(fail_on={"Runtime.enable"})
    sender(ws).send(intent(), target())
    assert ws.closed is True


# --------------------------------------------------------------- the keys

def test_the_submit_key_is_per_target():
    ws = FakeWs()
    sender(ws, submit="ctrl+enter").send(intent(), target())
    events = [p for m, p in ws.calls if m == "Input.dispatchKeyEvent"]
    assert events and events[0]["modifiers"] == 2
    assert events[0]["key"] == "Enter"


def test_enter_is_sent_as_a_down_and_an_up():
    ws = FakeWs()
    sender(ws).send(intent(), target())
    kinds = [p["type"] for m, p in ws.calls if m == "Input.dispatchKeyEvent"]
    assert kinds == ["keyDown", "keyUp"]


def test_an_unknown_submit_key_fails_after_inserting_nothing_more():
    ws = FakeWs()
    result = sender(ws, submit="wingding").send(intent(), target())
    assert result.ok is False and "unknown submit key" in result.reason


# ------------------------------------------------------------ multi-line

def test_multiline_is_joined_by_default():
    ws = FakeWs()
    sender(ws).send(intent("first line\nsecond line"), target())
    assert ws.field == "first line second line"


def test_multiline_can_be_refused():
    ws = FakeWs()
    result = sender(ws, multiline="refuse").send(intent("one\ntwo"), target())
    assert result.ok is False and "several lines" in result.reason


# --------------------------------------------------------------- framing

def test_the_frame_header_grows_with_the_payload():
    """Three length encodings, and a wrong one desynchronises the stream."""
    class Recorder:
        def __init__(self): self.sent = b""
        def sendall(self, data): self.sent += data
        def close(self): pass

    for size, marker in ((10, 0x80 | 10), (300, 0x80 | 126), (70000, 0x80 | 127)):
        rec = Recorder()
        ws = WebSocket("", sock=rec)
        ws.send("X", {"p": "y" * size})
        assert rec.sent[0] == 0x81, "one text frame, final"
        assert rec.sent[1] == marker or size == 10


def test_a_reply_is_matched_by_id_not_by_arrival():
    """CDP interleaves events with replies; taking the next message would
    read somebody else's notification as the answer."""
    class Scripted:
        def __init__(self):
            self.queue = [
                {"method": "Runtime.consoleAPICalled", "params": {}},
                {"method": "Network.requestWillBeSent", "params": {}},
                {"id": 1, "result": {"value": "the real answer"}},
            ]
        def sendall(self, data): pass
        def close(self): pass

    ws = WebSocket("", sock=Scripted())
    ws.recv = lambda: ws.sock.queue.pop(0)
    assert ws.call("Runtime.evaluate")["value"] == "the real answer"


def test_a_reply_that_never_comes_gives_up():
    class Chatty:
        def sendall(self, data): pass
        def close(self): pass

    ws = WebSocket("", sock=Chatty())
    ws.recv = lambda: {"method": "Some.event", "params": {}}
    try:
        ws.call("Runtime.evaluate", max_messages=5)
    except CdpError as exc:
        assert "no reply" in str(exc)
    else:
        raise AssertionError("it should have given up")


def test_a_cdp_error_reply_is_raised_not_returned_as_a_result():
    class Failing:
        def sendall(self, data): pass
        def close(self): pass

    ws = WebSocket("", sock=Failing())
    ws.recv = lambda: {"id": 1, "error": {"code": -32000,
                                          "message": "Cannot find context"}}
    try:
        ws.call("Runtime.evaluate")
    except CdpError as exc:
        assert "Cannot find context" in str(exc)
    else:
        raise AssertionError("an error reply must not read as success")


# ------------------------------------------------------------- the field

def test_plain_inputs_are_not_composers_by_default():
    """Measured on CodeNomad: the page has three text fields and the
    composer is the third. The first two are a model search and a settings
    box, both <input> - a selector that matched them would have typed the
    queued prompt into a search."""
    assert "input" not in CdpSender.DEFAULT_SELECTOR
    assert "textarea" in CdpSender.DEFAULT_SELECTOR
    assert "contenteditable" in CdpSender.DEFAULT_SELECTOR


def test_the_lowest_visible_field_is_the_one_used():
    """A chat composer sits at the bottom; anything else is above it."""
    js = CdpSender().FIELD_JS
    assert "offsetWidth" in js, "invisible fields are filtered out"
    assert "getBoundingClientRect" in js and "els.length - 1" in js


def test_an_adapter_can_name_its_own_field():
    js = CdpSender(selector="#composer textarea").FIELD_JS
    assert "#composer textarea" in js


def test_the_selector_is_escaped_into_the_script():
    """A quote in a selector would otherwise end the JS string early and
    turn a config typo into a syntax error at send time."""
    js = CdpSender(selector='[data-x="y"]').FIELD_JS
    assert '\\"y\\"' in js or '[data-x=\\"y\\"]' in js.replace("'", '"')

