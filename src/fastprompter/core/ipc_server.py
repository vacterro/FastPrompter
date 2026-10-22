"""Single-instance IPC server for FastPrompter.

Uses ``QLocalServer`` to ensure only one instance runs at a time.
When a second instance starts, ``try_connect_to_server`` sends a
TOKEN-authenticated SHOW command to the existing instance and then exits.

Protocol contract (one way, and only one):

* Valid: ``TOKEN:<correct-token>|SHOW``  -> window shown, ``ACK`` returned.
* Invalid: bare ``SHOW``, wrong/empty token, malformed input, unknown
  command -> nothing shown, NO ``ACK``.

There is deliberately no unauthenticated command path: a client that cannot
prove it knows this session's token is not answered, so "authenticated" is
never a label on an open door.
"""

import os
import tempfile
import time
import uuid
from collections.abc import Callable

from PyQt6.QtCore import QTimer
from PyQt6.QtNetwork import QLocalServer, QLocalSocket

from fastprompter.core.logging import logger

SERVER_NAME = "FastPrompter_Server_V15"

_ACK_TIMEOUT_MS = 1500

#: Hard ceiling on one assembled frame. A valid authentication frame is a UUID
#: token plus the fixed grammar, so a few hundred bytes already carries huge
#: headroom; anything larger is refused before it can grow.
MAX_FRAME_BYTES = 4096

#: Default per-socket deadline, in Qt event-loop time. One stalled client must
#: not retire another one's frame, so the bound is per socket and generous.
DEFAULT_FRAME_DEADLINE_MS = 30000

# Set by request_show after its grace window closes: True when a live owner's
# IPC server was CONNECTED to at least once (the owner exists and is alive,
# just busy/slow), False when no server ever appeared (owner still starting or
# genuinely frozen). main_entry uses this to decide whether the "not
# responding" diagnostic is honest — a deliberate second launch that reached a
# live owner should not scare the user with a frozen-instance box.
_LAST_SAW_SERVER = False


def try_connect_to_server(retries: int = 3, delay: float = 0.05) -> QLocalSocket | None:
    """Try to connect to a running FastPrompter instance.

    Returns a connected ``QLocalSocket`` if another instance is already
    listening, or ``None`` if no instance is found (caller should start a new one).
    """
    token_file = os.path.join(tempfile.gettempdir(), "fastprompter_ipc.token")
    token = ""
    if os.path.exists(token_file):
        try:
            with open(token_file) as f:
                token = f.read().strip()
        except Exception:
            logger.debug("Failed to read IPC token file %s", token_file)

    for _ in range(retries):
        sock = QLocalSocket()
        sock.connectToServer(SERVER_NAME)
        if sock.waitForConnected(100):
            if token:
                sock.setProperty("ipc_token", token)
            return sock
        time.sleep(delay)
    return None


def request_show(ack_timeout_ms=_ACK_TIMEOUT_MS, grace_ms=3000) -> bool:
    """Ask the live owner to show its window. True only on a real ACK.

    The caller has already failed to acquire writer ownership, so a live
    process exists — the mutex is authoritative, never this function. This
    handover is authentication-gated: the token must match or the owner will
    not answer.

    Startup grace: a freshly started owner holds the mutex before its IPC
    server is listening, so the FIRST few attempts may find no socket at all.
    Connection attempts and the token are re-read for a bounded window, so a
    slow STARTING owner is not mistaken for a FROZEN one. No ACK within the
    grace (frozen event loop, replaced token that never catches up) returns
    False — the caller must exit, never become a second writer.

    Sets the module-level ``_LAST_SAW_SERVER`` so the caller can distinguish
    "owner alive but busy" (server reached, no ACK) from "owner genuinely
    frozen or absent" (server never seen). A deliberate second launch that
    reached a live server should not scare the user with a frozen-instance box.
    """
    global _LAST_SAW_SERVER
    _LAST_SAW_SERVER = False
    deadline = time.monotonic() + max(0, int(grace_ms)) / 1000.0
    attempt = 0
    saw_server = False
    while True:
        attempt += 1
        # the first attempt may afford a long ACK wait; retries are bounded
        # so the whole handover stays inside the grace window
        timeout = ack_timeout_ms if attempt == 1 else min(ack_timeout_ms, 500)
        sock = try_connect_to_server()          # re-reads the token each call
        if sock is not None:
            saw_server = True
            try:
                token = sock.property("ipc_token") or ""
                sock.write(f"TOKEN:{token}|SHOW".encode())
                sock.flush()
                sock.waitForBytesWritten(500)
                acked = sock.waitForReadyRead(max(0, int(timeout))) and \
                    b"ACK" in sock.readAll().data()
                if acked:
                    _LAST_SAW_SERVER = True
                    return True
                # a live socket that does not ACK: the owner's event loop is
                # not pumping, or a stale token is in play — retry until the
                # grace window closes, then give up (never become a writer)
            finally:
                sock.disconnectFromServer()
        if time.monotonic() >= deadline:
            break
        time.sleep(0.05)
    _LAST_SAW_SERVER = saw_server
    # distinguish the two failure shapes in the log: the owner was never seen
    # (still starting / crashed before its server) vs was seen but never
    # acknowledged (frozen event loop or stale token)
    if saw_server:
        logger.warning("IPC handover: the owner's socket was seen but never "
                       "ACKed within the startup grace; treating it as "
                       "unresponsive")
    else:
        logger.warning("IPC handover: no server appeared within the startup "
                       "grace; the owner is starting very slowly or is not "
                       "serving IPC")
    return False


def _get_token() -> str:
    """Read or generate an IPC authentication token."""
    token_file = os.path.join(tempfile.gettempdir(), "fastprompter_ipc.token")
    token = str(uuid.uuid4())
    try:
        with open(token_file, "w") as f:
            f.write(token)
    except Exception as e:
        logger.warning("Could not write IPC token: %s", e)
    return token


class _PendingSocket:
    """Per-socket half-frame state: accumulate, bound, retire on a deadline.

    One plain object per accepted connection, owned by the server. Nothing in
    it ever waits on the socket: the ready-read, disconnect and deadline paths
    all drive ordinary slots on the GUI thread.

    A bound method keeps its owner alive through the connection, so the class
    deliberately carries no ``__slots__`` -- a slot-only object cannot be
    weak-referenced and Qt's connect needs that reference to tear the
    connection down when the owner goes away.
    """

    def __init__(self, server, sock):
        self.server = server
        self.sock = sock
        self.buf = b""
        self.done = False
        self.timer = QTimer()
        self.timer.setSingleShot(True)
        self.timer.setInterval(max(0, int(server._frame_deadline_ms)))
        self.timer.timeout.connect(self._expire)

    def arm(self):
        sock = self.sock
        sock.readyRead.connect(self._on_ready_read)
        sock.disconnected.connect(self._on_disconnected)
        self.timer.start()

    # ---- slots ---------------------------------------------------------
    def _on_ready_read(self):
        if self.done:
            return
        sock = self.sock
        if sock.bytesAvailable() > 0:
            self.buf += sock.readAll().data()
            if len(self.buf) > MAX_FRAME_BYTES:
                self._abort()
                return
        if not self.buf:
            return
        if self._resolve_frame(self.buf):
            return
        if len(self.buf) > MAX_FRAME_BYTES:
            self._abort()

    def _on_disconnected(self):
        self._abort()

    def _expire(self):
        if not self.done and self.buf:
            logger.info("IPC: discarded an incomplete frame after the "
                        "per-socket deadline")
        self._abort()

    # ---- resolution ----------------------------------------------------
    def _resolve_frame(self, buf: bytes) -> bool:
        """Resolve one complete authenticated frame. True when it terminal."""

        try:
            data_str = buf.decode("utf-8")
        except UnicodeDecodeError:
            self._abort()
            return True
        if b"|SHOW" not in buf or not buf.startswith(b"TOKEN:"):
            return False
        parts = data_str.split("|", 1)
        if len(parts) != 2:
            self._abort()
            return True
        recv_token, cmd = parts[0][6:], parts[1]
        if recv_token != self.server._token or cmd.strip() != "SHOW":
            self._abort()
            return True
        self._retire()
        self.server._show_window()
        self._ack(b"ACK")
        return True

    def _ack(self, payload: bytes):
        try:
            self.sock.write(payload)
            self.sock.flush()
        except Exception:
            logger.debug("IPC: could not answer a frame")

    def _retire(self):
        """Drop this half-frame from the registry BEFORE destroying the socket.

        ``_pending`` is per-connection state and an entry is removed exactly
        once, whichever path retires it first.
        """
        if self.done:
            return
        self.done = True
        pending = self.server._pending
        if pending.get(self.sock) is self:
            del pending[self.sock]
        timer, self.timer = self.timer, None
        if timer is not None:
            timer.stop()
            timer.deleteLater()

    def _abort(self):
        """Retire without answering: silent, or an unexplainable frame."""
        self._retire()
        sock = self.sock
        sock.disconnectFromServer()
        sock.deleteLater()


class IpcServer:
    """Wraps a ``QLocalServer`` for single-instance IPC communication.

    Usage::

        ipc = IpcServer(show_window_callback)
        ipc.setup()
        # … later, when a second instance sends SHOW:
        # show_window_callback() is called automatically

    Every socket path is event-driven: the frame is accumulated in ready-read
    slots, bounded per socket, and retired by that socket's own deadline. The
    GUI thread never waits on a peer, so a silent or slowly-dripping client
    cannot starve the owner's event loop, one stalled client cannot delay a
    valid sibling, and an unauthenticated frame is answered by nothing.
    """

    def __init__(self, show_window: Callable[[], None],
                 frame_deadline_ms: int = DEFAULT_FRAME_DEADLINE_MS) -> None:
        self._show_window: Callable[[], None] = show_window
        self._token: str = _get_token()
        self._server: QLocalServer = QLocalServer()
        self._frame_deadline_ms = int(frame_deadline_ms)
        self._pending: dict[QLocalSocket, _PendingSocket] = {}

    @property
    def token(self) -> str:
        """The IPC authentication token shared via a temp file."""
        return self._token

    def setup(self) -> None:
        """Start listening for IPC connections from sibling instances.

        Never exits the process. It used to `sys.exit(0)` when listen()
        failed, which is how a stuck instance turned every later launch into
        a silent no-op: the user double-clicked, nothing appeared, and there
        was nothing in the log to say why. Being unable to own the socket
        costs single-instance behaviour, not the application - so it is
        reported and the window still opens.
        """
        # removeServer clears a name left behind by a process that died
        # without closing it, which is what lets a launch recover from a
        # corpse rather than inheriting its silence.
        self._server.removeServer(SERVER_NAME)
        if not self._server.listen(SERVER_NAME):
            logger.warning(
                "IPC: could not own %s (%s); running without single-instance "
                "handover", SERVER_NAME, self._server.errorString())
            return
        self._server.newConnection.connect(self._on_new_connection)

    def close(self) -> None:
        """Close the IPC server and retire every half-assembled frame."""
        for pending in list(self._pending.values()):
            pending._abort()
        self._pending.clear()
        self._server.close()

    # ---- event paths ---------------------------------------------------
    def _on_new_connection(self):
        """Accept every pending connection into its own bounded state."""
        while True:
            sock = self._server.nextPendingConnection()
            if sock is None:
                return
            pending = _PendingSocket(self, sock)
            self._pending[sock] = pending
            pending.arm()

    def _handle_command(self) -> None:
        """Accept ONE connection and resolve the bytes already available.

        The event-driven path is ``_on_new_connection``; this stays as the
        direct entry point so a caller (or a test) that drives the server
        without pumping the loop still exercises the SAME per-socket frame
        resolution. A frame that is still incomplete is left registered for
        its own ready-read slots -- never for a waiting loop.
        """
        sock = self._server.nextPendingConnection()
        if sock is None:
            return
        pending = self._pending.get(sock)
        if pending is None or pending.done:
            pending = _PendingSocket(self, sock)
            self._pending[sock] = pending
        try:
            pending.arm()
        except Exception:
            pass
        pending._on_ready_read()
