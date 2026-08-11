"""Phase-10 (second pass): IPC startup handover grace.

A second process must never mistake a STARTING owner (mutex held, IPC socket
not yet listening) for a FROZEN one, and must never become a second writer.
request_show retries connection + token reads for a bounded grace window.
"""

import os
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

from unittest.mock import MagicMock

from _qt_stub import import_with_stubs


class _MockQLocalSocket:
    def __init__(self, ack=True, data=b"ACK"):
        self._props = {}
        self._ack = ack
        self._data = data

    def connectToServer(self, name):
        pass

    def waitForConnected(self, timeout):
        return True

    def setProperty(self, key, value):
        self._props[key] = value

    def property(self, key):
        return self._props.get(key, "")

    def write(self, data):
        pass

    def flush(self):
        pass

    def waitForBytesWritten(self, timeout):
        return True

    def waitForReadyRead(self, timeout):
        return self._ack

    def readAll(self):
        return self

    def data(self):
        return self._data

    def disconnectFromServer(self):
        pass

    def deleteLater(self):
        pass

    def bytesAvailable(self):
        return len(self._data) > 0


_ipc = import_with_stubs(
    "fastprompter.core.ipc_server",
    {"PyQt6": MagicMock(), "PyQt6.QtNetwork": MagicMock(
        QLocalServer=MagicMock(), QLocalSocket=_MockQLocalSocket)},
)
request_show = _ipc.request_show


class TestStartupGrace:
    def test_slow_startup_eventually_handoffs(self, monkeypatch):
        """No server for the first attempts, then it appears and ACKs."""
        calls = {"n": 0}

        def fake_try(retries=3, delay=0.05):
            calls["n"] += 1
            if calls["n"] < 3:
                return None
            return _MockQLocalSocket(ack=True, data=b"ACK")

        monkeypatch.setattr(_ipc, "try_connect_to_server", fake_try)
        assert request_show(grace_ms=800) is True

    def test_no_server_within_grace_returns_false(self, monkeypatch):
        monkeypatch.setattr(_ipc, "try_connect_to_server", lambda **k: None)
        assert request_show(grace_ms=150) is False

    def test_frozen_owner_no_ack_returns_false(self, monkeypatch):
        """A socket that never ACKs is a frozen owner, not a starting one."""
        monkeypatch.setattr(
            _ipc, "try_connect_to_server",
            lambda **k: _MockQLocalSocket(ack=False, data=b""))
        assert request_show(grace_ms=300) is False

    def test_token_replaced_during_retry_eventually_acks(self, monkeypatch):
        """First attempt carries a stale token (no ACK); the re-read token on
        the retry succeeds."""
        calls = {"n": 0}

        def fake_try(retries=3, delay=0.05):
            calls["n"] += 1
            sock = _MockQLocalSocket(ack=calls["n"] >= 2, data=b"ACK")
            sock.setProperty("ipc_token", f"token-{calls['n']}")
            return sock

        monkeypatch.setattr(_ipc, "try_connect_to_server", fake_try)
        assert request_show(grace_ms=800) is True

    def test_grace_is_bounded(self, monkeypatch):
        """The retry loop must terminate quickly even when nothing answers."""
        monkeypatch.setattr(_ipc, "try_connect_to_server",
                            lambda **k: _MockQLocalSocket(ack=False, data=b""))
        t0 = time.monotonic()
        request_show(grace_ms=200)
        assert time.monotonic() - t0 < 5.0
