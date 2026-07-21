"""Driving a Chromium app through its DevTools socket. The transport that works.

Posting Win32 messages at an Electron window does nothing — Chromium takes
input through its own IPC, not the window message queue, and every agent
worth driving here is Electron. This is the channel that does reach them,
and it is not a trick: it is how DevTools itself drives a page.

Three rules, two of them learned the hard way:

* **Verify by reading back, never by a return value.** `PostMessageW`
  returned success for every character of a string that never arrived. So
  this inserts the text, reads the field again, and only presses the submit
  key once the text is actually there. A send that cannot be confirmed is
  not reported as sent.
* **Everything is injected.** The socket layer is a parameter, so a test
  drives a recorder and no test can reach a real application.
* **Short timeouts.** The sender runs inside the Qt tick; a socket that
  blocks for ten seconds freezes the window for ten seconds.
"""

from __future__ import annotations

import base64
import json
import os
import socket
import struct
import urllib.request

DEFAULT_TIMEOUT = 3.0


class CdpError(Exception):
    pass


# --------------------------------------------------------------- discovery

def discover(port, opener=None, timeout=DEFAULT_TIMEOUT):
    """The debuggable targets on a port, or [] if nothing answers.

    An app only listens when it was launched with --remote-debugging-port.
    Returning empty rather than raising is deliberate: "this agent is not
    reachable this way" is a normal answer the UI has to show.
    """
    opener = opener or urllib.request.urlopen
    try:
        with opener(f"http://127.0.0.1:{int(port)}/json/list",
                    timeout=timeout) as response:
            raw = response.read().decode("utf-8", "replace")
    except Exception:
        return []
    try:
        data = json.loads(raw)
    except ValueError:
        return []
    return [t for t in data if isinstance(t, dict)]


def find_page(targets, title_match=""):
    """The page a prompt should go to.

    Workers and iframes are debuggable too and typing into one does nothing
    visible, so pages only.
    """
    pages = [t for t in targets if t.get("type") == "page"]
    if title_match:
        needle = title_match.lower()
        pages = [t for t in pages if needle in str(t.get("title", "")).lower()]
    return pages[0] if pages else None


def port_from_file(path):
    """Read a Chromium DevToolsActivePort file.

    The port is assigned per launch, so hard-coding the one seen today would
    work exactly until the app restarts. Chromium writes the live port on
    the first line of this file in its user-data directory, which is the
    only stable way to find it.
    """
    if not path:
        return 0
    try:
        with open(os.path.expanduser(os.path.expandvars(path)),
                  encoding="utf-8") as fh:
            return int((fh.readline() or "").strip() or 0)
    except (OSError, ValueError):
        return 0


# ------------------------------------------------------------- the socket

class WebSocket:
    """Just enough of the protocol to speak CDP: masked text frames.

    Written out rather than taken as a dependency — the project ships no
    third-party runtime deps, and CDP needs exactly one frame type.
    """

    def __init__(self, url, timeout=DEFAULT_TIMEOUT, sock=None):
        self.timeout = timeout
        if sock is not None:
            self.sock = sock                      # injected, for tests
            self.buf = b""
            self._id = 0
            return
        host, port, path = self._split(url)
        self.sock = socket.create_connection((host, port), timeout=timeout)
        self.sock.settimeout(timeout)
        key = base64.b64encode(os.urandom(16)).decode()
        self.sock.sendall(
            f"GET {path} HTTP/1.1\r\nHost: {host}:{port}\r\n"
            f"Upgrade: websocket\r\nConnection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n"
            .encode())
        buf = b""
        while b"\r\n\r\n" not in buf:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise CdpError("the debugger closed during the handshake")
            buf += chunk
        head, _, rest = buf.partition(b"\r\n\r\n")
        if b" 101" not in head.split(b"\r\n")[0]:
            raise CdpError(f"the debugger refused the upgrade: {head[:80]!r}")
        self.buf = rest
        self._id = 0

    @staticmethod
    def _split(url):
        rest = url.split("://", 1)[-1]
        hostport, _, path = rest.partition("/")
        host, _, port = hostport.partition(":")
        return host, int(port or 80), "/" + path

    # ---- framing -------------------------------------------------------
    def _read(self, n):
        while len(self.buf) < n:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise CdpError("the debugger closed the connection")
            self.buf += chunk
        out, self.buf = self.buf[:n], self.buf[n:]
        return out

    def send(self, method, params=None):
        self._id += 1
        payload = json.dumps({"id": self._id, "method": method,
                              "params": params or {}}).encode()
        mask = os.urandom(4)
        size = len(payload)
        header = b"\x81"
        if size < 126:
            header += bytes([0x80 | size])
        elif size < 65536:
            header += bytes([0x80 | 126]) + struct.pack(">H", size)
        else:
            header += bytes([0x80 | 127]) + struct.pack(">Q", size)
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        self.sock.sendall(header + mask + masked)
        return self._id

    def recv(self):
        _b0, b1 = self._read(2)
        size = b1 & 0x7F
        if size == 126:
            size = struct.unpack(">H", self._read(2))[0]
        elif size == 127:
            size = struct.unpack(">Q", self._read(8))[0]
        return json.loads(self._read(size).decode("utf-8", "replace"))

    def call(self, method, params=None, max_messages=60):
        """Send and wait for THIS id.

        CDP interleaves events with replies, so a client that took the next
        message would read someone else's notification as its answer.
        """
        want = self.send(method, params)
        for _ in range(max_messages):
            message = self.recv()
            if message.get("id") == want:
                if "error" in message:
                    raise CdpError(str(message["error"])[:160])
                return message.get("result", {})
        raise CdpError(f"no reply to {method}")

    def close(self):
        try:
            self.sock.close()
        except Exception:
            pass


# --------------------------------------------------------------- the target

class CdpTarget:
    """A debuggable page, and how to tell it is still the same one.

    Mirrors sender.Target: identity is rechecked at send time, because a
    window that has been replaced must abort rather than receive.
    """

    def __init__(self, port, target_id, title="", url="", ws_url="",
                 discover_fn=None):
        self.port = int(port)
        self.target_id = target_id
        self.title = title or ""
        self.url = url or ""
        self.ws_url = ws_url or ""
        self.hwnd = 0                      # for SendLog, which asks
        self._discover = discover_fn or discover

    @classmethod
    def from_port(cls, port, title_match="", discover_fn=None):
        found = (discover_fn or discover)(port)
        page = find_page(found, title_match)
        if page is None:
            return None
        return cls(port, page.get("id"), page.get("title", ""),
                   page.get("url", ""), page.get("webSocketDebuggerUrl", ""),
                   discover_fn=discover_fn)

    def matches(self):
        """(ok, reason) — is this still the page that was armed?"""
        if not self.target_id:
            return False, "no page was armed"
        live = self._discover(self.port)
        if not live:
            return False, "the debugger is no longer listening"
        for entry in live:
            if entry.get("id") == self.target_id:
                # The title moves as the conversation is renamed, so it is
                # not identity; the target id is.
                return True, "target confirmed"
        return False, "the page is gone"


# --------------------------------------------------------------- the sender

class CdpSender:
    """Insert the text, confirm it landed, then submit. Never the other way.

    The confirmation is the whole point. Its predecessor reported success on
    the strength of an API return value while nothing had arrived, so here a
    send that cannot be read back is a failure, and the submit key is never
    pressed on an empty or wrong field.
    """

    dry = False
    silent = True

    # Finds the composer. Ordered widest-first: a chat UI is usually one
    # contenteditable, but some use a plain textarea.
    FIELD_JS = (
        "(() => { const e = document.querySelector("
        "'[contenteditable=\"true\"], textarea, input[type=text]');"
        " return e ? String(e.value ?? e.textContent ?? '') : null; })()")

    FOCUS_JS = (
        "(() => { const e = document.querySelector("
        "'[contenteditable=\"true\"], textarea, input[type=text]');"
        " if (!e) return false; e.focus(); return true; })()")

    def __init__(self, connect=None, submit="enter", multiline="join",
                 timeout=DEFAULT_TIMEOUT):
        self._connect = connect or (lambda url: WebSocket(url, timeout))
        self.submit = submit or "enter"
        self.multiline = multiline or "join"
        self.timeout = timeout

    # ---- helpers -------------------------------------------------------
    def _read_field(self, ws):
        result = ws.call("Runtime.evaluate",
                         {"expression": self.FIELD_JS, "returnByValue": True})
        return result.get("result", {}).get("value")

    def _press(self, ws, key):
        spec = _KEYS.get((key or "enter").lower())
        if spec is None:
            raise CdpError(f"unknown submit key {key!r}")
        code, name, mods = spec
        for kind in ("keyDown", "keyUp"):
            ws.call("Input.dispatchKeyEvent", {
                "type": kind, "key": name, "code": name,
                "windowsVirtualKeyCode": code, "nativeVirtualKeyCode": code,
                "modifiers": mods,
            })

    # ---- the send ------------------------------------------------------
    def send(self, intent, target):
        from fastprompter.core.watcher.sender import SendResult, _flatten

        if target is None:
            return SendResult(False, "no target")
        ok, reason = target.matches()
        if not ok:
            return SendResult(False, reason, intent.text)

        text, why = _flatten(intent.text, self.multiline)
        if text is None:
            return SendResult(False, why, intent.text)

        ws = None
        try:
            ws = self._connect(target.ws_url)
            ws.call("Runtime.enable")

            before = self._read_field(ws)
            if before is None:
                return SendResult(
                    False, "no text field on that page", text)
            if before.strip():
                # Typing after what the user has half-written would send a
                # sentence neither of them wrote.
                return SendResult(
                    False, "the field already has text in it", text)

            ws.call("Runtime.evaluate",
                    {"expression": self.FOCUS_JS, "returnByValue": True})
            ws.call("Input.insertText", {"text": text})

            after = self._read_field(ws)
            if after is None or text not in after:
                return SendResult(
                    False,
                    "the text did not reach the field, so nothing was sent",
                    text)

            self._press(ws, self.submit)
            return SendResult(True, "sent silently over the debugger", text)
        except CdpError as exc:
            return SendResult(False, f"debugger refused: {exc}", text)
        except OSError as exc:
            return SendResult(False, f"could not reach the debugger: {exc}", text)
        finally:
            if ws is not None:
                ws.close()


# key -> (virtual key code, DOM key name, modifier bits)
_KEYS = {
    "enter": (13, "Enter", 0),
    "return": (13, "Enter", 0),
    "ctrl+enter": (13, "Enter", 2),
    "shift+enter": (13, "Enter", 8),
    "tab": (9, "Tab", 0),
}
