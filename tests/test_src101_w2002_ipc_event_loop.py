"""SRC-101 / W2-002: the IPC receive path must not block the GUI thread.

The audited server assembled its frame inside a synchronous loop with a
3-second deadline, driven straight from the ``newConnection`` signal — so an
unauthenticated local client froze the owner's event loop for 200 ms…3 s merely
by connecting and withholding, or slowly dripping, an incomplete frame. Token
authentication could not bound that, because it ran only AFTER the loop.

These tests run the REAL thing: a real ``QLocalServer``, real ``QLocalSocket``
clients and a real Qt event loop.

The witnesses are CALL-LEVEL and STRUCTURAL, never durations.  On a loaded
machine this process can be descheduled for many seconds, so a wall-clock bound
cannot tell a server that blocks from a host that is merely busy — an earlier
revision of this module asserted a timer-throughput bound and reddened
deterministically at one point in the suite for that reason alone.  Instead
every test that must fail for a reintroduced blocking call shadows
``waitForReadyRead``/``waitForBytesWritten``/``waitForConnected`` on each
accepted socket (and ``waitForNewConnection`` on the server), so the CALL is
what fails the test, and the waits for state transitions use a budget that is
generous enough to outlast any scheduler stall rather than tight.
"""

import os
import sys
import uuid

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

import pytest
from PyQt6.QtCore import QEventLoop, QTimer
from PyQt6.QtNetwork import QLocalSocket

from fastprompter.core import ipc_server

#: Long enough to outlast the worst stall this host has shown (seconds), and
#: deliberately never tight: it only has to be reachable by a correct path.
#: A path that never reaches the terminal state does not reach it with any
#: budget, so a generous value costs no discrimination.
BUDGET_MS = 20000

#: The blocking calls the audit found in the receive/connect path.  Every one
#: of them must be absent from ``IpcServer``'s own source, and every one of them
#: is shadowed on a live accepted socket by :class:`_NoWait`.
WAIT_NAMES = (
    "waitForReadyRead", "waitForBytesWritten", "waitForConnected",
    "waitForNewConnection",
)


class _NoWait:
    """Record any socket wait the GUI thread performs, instead of timing one.

    On a Windows named pipe a wait against an empty socket can return at once,
    so a duration proves nothing; making the call itself observable does.
    """

    def __init__(self, server):
        self.server = server
        self.waits = []

    def install(self, monkeypatch):
        srv = self.server._server
        real_next = srv.nextPendingConnection

        def _next():
            sock = real_next()
            if sock is not None:
                self._arm(sock)
            return sock

        monkeypatch.setattr(srv, "nextPendingConnection", _next)
        for name in ("waitForNewConnection", "waitForReadyRead"):
            real = getattr(srv, name, None)
            if real is None:
                continue

            def _spy(ms=0, *args, _name=name, _real=real):
                self.waits.append((_name, ms))
                return False

            monkeypatch.setattr(srv, name, _spy)
        return self

    def _arm(self, sock):
        for name in WAIT_NAMES:
            if not hasattr(sock, name):
                continue

            def _spy(ms=0, *args, _name=name):
                self.waits.append((_name, ms))
                return False

            setattr(sock, name, _spy)

    def reason(self):
        return "the GUI thread waited on the socket: " + ", ".join(
            f"{name}({ms})" for name, ms in self.waits[:6])


def _pump(ms):
    """Run the real event loop (nested) for a bounded time."""
    loop = QEventLoop()
    QTimer.singleShot(int(ms), loop.quit)
    loop.exec()


@pytest.fixture
def ipc(qapp, monkeypatch):
    """A listening IpcServer on a private pipe name.

    The default per-socket deadline is LONG (30 s of event-loop time): a test
    that expects a frame to be delivered must not lose the race to a 200 ms
    deadline that fires in the same dispatch batch as its own pump timers the
    moment the host stalls.  Tests that expect the deadline to fire call
    :func:`_short_deadline` first, which is the case the starvation works for.
    """
    name = f"FastPrompter_Test_{uuid.uuid4().hex}"
    monkeypatch.setattr(ipc_server, "SERVER_NAME", name)
    calls = []

    def _show():
        calls.append(1)

    server = ipc_server.IpcServer(_show, frame_deadline_ms=30000)
    server.setup()
    assert server._server.isListening(), "test server failed to listen"
    server._test_name = name
    server._test_calls = calls
    yield server
    server.close()
    _pump(20)


def _short_deadline(server, ms=200):
    """Ask this server to retire incomplete frames after ``ms`` of loop time.

    Read at registration time, so it must be set BEFORE the client connects.
    """
    server._frame_deadline_ms = int(ms)
    return server


def _client(server, timeout_ms=5000):
    sock = QLocalSocket()
    sock.connectToServer(server._test_name)
    assert sock.waitForConnected(timeout_ms), "client could not connect"
    return sock


def _wait_for(predicate, timeout_ms=BUDGET_MS, step_ms=20):
    """Pump the event loop until predicate() or the budget runs out."""
    waited = 0
    while not predicate() and waited < timeout_ms:
        _pump(step_ms)
        waited += step_ms
    return predicate()


def _read_all(sock):
    _pump(20)
    return bytes(sock.readAll().data())


# --------------------------------------------------------------------------
# responsiveness
# --------------------------------------------------------------------------

def test_a_silent_client_cannot_block_the_gui_thread(ipc, monkeypatch):
    _short_deadline(ipc)
    """Connect and send nothing: the GUI thread must never wait on the peer.

    The audited handler called ``waitForReadyRead(200)`` ON THE GUI THREAD and
    looped until its 3-second deadline, so one silent peer froze the owner for
    seconds.  The witness is the call, not the freeze: the socket waits are
    shadowed, and the silent socket must instead be retired by its own
    per-socket deadline without any command ever running.
    """
    spy = _NoWait(ipc).install(monkeypatch)

    sock = _client(ipc)                      # connects, then says nothing
    assert _wait_for(lambda: len(ipc._pending) == 0), \
        f"the silent client was never retired: {ipc._pending}"

    assert spy.waits == [], spy.reason()
    assert ipc._test_calls == []
    assert _read_all(sock) != b"ACK"


def test_a_slow_drip_expires_without_blocking(ipc, monkeypatch):
    _short_deadline(ipc)
    """One byte every 40 ms for longer than the frame deadline."""
    spy = _NoWait(ipc).install(monkeypatch)

    sock = _client(ipc)
    drip = QTimer()
    drip.setInterval(40)
    drip.timeout.connect(lambda: sock.write(b"T"))
    drip.start()
    _pump(500)
    drip.stop()

    # the per-socket deadline discarded the stalled client
    assert _wait_for(lambda: len(ipc._pending) == 0), \
        f"the dripping client was never retired: {ipc._pending}"
    assert spy.waits == [], spy.reason()
    assert ipc._test_calls == []
    assert _read_all(sock) != b"ACK"


def test_the_gui_path_never_calls_a_socket_wait(ipc, monkeypatch):
    """Deterministic discriminator, independent of whether a wait really blocks.

    Structural half: ``IpcServer``'s own source must name none of the audited
    waits.  Live half: a valid frame is served while every socket wait is
    shadowed, and none may be called.
    """
    import ast
    import inspect

    # Names, not text: the class docstring names the removed calls on purpose.
    tree = ast.parse(inspect.getsource(ipc_server.IpcServer))
    used = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    used |= {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    for name in WAIT_NAMES:
        assert name not in used, f"server still blocks on {name}"

    spy = _NoWait(ipc).install(monkeypatch)
    sock = _client(ipc)
    sock.write(f"TOKEN:{ipc.token}|SHOW".encode())
    sock.flush()
    assert _wait_for(lambda: len(ipc._test_calls) == 1), "the valid frame was not served"

    assert spy.waits == [], spy.reason()
    assert _read_all(sock) == b"ACK"


def test_a_stalled_client_does_not_delay_a_valid_sibling(ipc, monkeypatch):
    """Independent per-socket state is the point: one stalled client, one served."""
    spy = _NoWait(ipc).install(monkeypatch)

    stalled = _client(ipc)                       # says nothing, ever
    stalled.write(b"TOKEN:")                     # partial, never completed
    _pump(30)

    good = _client(ipc)
    good.write(f"TOKEN:{ipc.token}|SHOW".encode())
    good.flush()
    served = _wait_for(lambda: len(ipc._test_calls) == 1)

    assert served, "a stalled sibling delayed a valid command"
    assert spy.waits == [], spy.reason()
    assert _read_all(good) == b"ACK"
    assert ipc._test_calls == [1]


# --------------------------------------------------------------------------
# fragmented / authenticated handover
# --------------------------------------------------------------------------

def test_fragmented_valid_frame_is_accepted_exactly_once(ipc):
    """A local-socket write may legitimately arrive split."""
    sock = _client(ipc)
    token = ipc.token
    sock.write(b"TOKEN:")          # three separate deliveries
    sock.flush()
    _pump(30)
    sock.write(token[:12].encode())
    sock.flush()
    _pump(30)
    sock.write((token[12:] + "|SHOW").encode())
    sock.flush()

    assert _wait_for(lambda: len(ipc._test_calls) == 1), "the fragmented frame was not served"
    assert ipc._test_calls == [1], "the frame was resolved more than once"
    assert _read_all(sock) == b"ACK"


def test_the_ack_is_written_without_a_blocking_write_wait(ipc, monkeypatch):
    """The ACK must arrive while the server performs no blocking flush wait."""
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(ipc_server.IpcServer))
    used = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    assert "waitForBytesWritten" not in used, "server still blocks writing"

    spy = _NoWait(ipc).install(monkeypatch)
    sock = _client(ipc)
    sock.write(f"TOKEN:{ipc.token}|SHOW".encode())
    sock.flush()
    assert _wait_for(lambda: len(ipc._test_calls) == 1), "the valid frame was not served"
    assert _read_all(sock) == b"ACK"
    assert spy.waits == [], spy.reason()


def test_every_concurrent_client_gets_its_own_ack(ipc):
    socks = [_client(ipc) for _ in range(3)]
    for sock in socks:
        sock.write(f"TOKEN:{ipc.token}|SHOW".encode())
        sock.flush()

    assert _wait_for(lambda: len(ipc._test_calls) == 3), "not every client was served"
    assert ipc._test_calls == [1, 1, 1]
    for sock in socks:
        assert _read_all(sock) == b"ACK"


# --------------------------------------------------------------------------
# rejection paths: no window, no ACK
# --------------------------------------------------------------------------

@pytest.mark.parametrize("payload", [
    b"SHOW",                                # bare command
    b"UNKNOWN",                             # unknown command
    b"TOKEN:|SHOW",                         # empty token
    b"TOKEN:wrong-token|SHOW",              # wrong token
    b"TOKEN:abc",                           # incomplete
    b"\xff\xfe\x00\x01",                    # malformed, no token
])
def test_unauthenticated_shapes_show_nothing_and_ack_nothing(ipc, payload):
    _short_deadline(ipc)
    sock = _client(ipc)
    sock.write(payload)
    sock.flush()
    _pump(400)                              # past the 200 ms frame deadline

    assert ipc._test_calls == []
    assert _read_all(sock) != b"ACK"
    assert _wait_for(lambda: len(ipc._pending) == 0), \
        f"the rejected frame was never retired: {ipc._pending}"


def test_wrong_token_with_valid_command_shape_is_rejected(ipc):
    _short_deadline(ipc)
    sock = _client(ipc)
    sock.write(f"TOKEN:{ipc.token}|QUIT".encode())
    sock.flush()
    _pump(400)

    assert ipc._test_calls == []
    assert _read_all(sock) != b"ACK"


def test_malformed_utf8_inside_a_complete_frame_is_rejected(ipc):
    _short_deadline(ipc)
    """A complete frame is resolved promptly and rejected without an ACK."""
    sock = _client(ipc)
    sock.write(b"TOKEN:\xff\xfe|SHOW")
    sock.flush()
    _pump(200)

    assert ipc._test_calls == []
    assert _read_all(sock) != b"ACK"
    assert _wait_for(lambda: len(ipc._pending) == 0), \
        f"the rejected frame was never retired: {ipc._pending}"


def test_oversized_frame_is_rejected_before_it_can_grow(ipc):
    _short_deadline(ipc)
    """A 47-byte authenticated frame has no honest reason to be 405 bytes."""
    sock = _client(ipc)
    sock.write(b"TOKEN:" + b"A" * 400)
    sock.flush()
    _pump(200)

    assert ipc._test_calls == []
    assert _read_all(sock) != b"ACK"
    assert _wait_for(lambda: len(ipc._pending) == 0), \
        f"the rejected frame was never retired: {ipc._pending}"


# --------------------------------------------------------------------------
# cleanup
# --------------------------------------------------------------------------

def test_close_discards_every_half_assembled_frame(ipc):
    sock = _client(ipc)
    sock.write(b"TOKEN:")               # left incomplete on purpose
    _pump(30)

    ipc.close()

    assert ipc._pending == {}
    assert ipc._test_calls == []
    sock.disconnectFromServer()


def test_a_disconnected_client_leaves_no_state_behind(ipc):
    sock = _client(ipc)
    sock.write(b"TOKEN:")               # incomplete, then the client leaves
    _pump(30)
    sock.disconnectFromServer()

    assert _wait_for(lambda: len(ipc._pending) == 0), \
        f"the departed client left state behind: {ipc._pending}"
    assert ipc._test_calls == []
