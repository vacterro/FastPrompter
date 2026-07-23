"""Single-instance IPC server for FastPrompter.

Uses ``QLocalServer`` to ensure only one instance runs at a time.
When a second instance starts, ``try_connect_to_server`` sends a
SHOW command to the existing instance and then exits.
"""

import os
import tempfile
import time
import uuid
from collections.abc import Callable

from PyQt6.QtNetwork import QLocalServer, QLocalSocket

from fastprompter.core.logging import logger

SERVER_NAME = "FastPrompter_Server_V15"


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


class IpcServer:
    """Wraps a ``QLocalServer`` for single-instance IPC communication.

    Usage::

        ipc = IpcServer(show_window_callback)
        ipc.setup()
        # … later, when a second instance sends SHOW:
        # show_window_callback() is called automatically
    """

    def __init__(self, show_window: Callable[[], None]) -> None:
        self._show_window: Callable[[], None] = show_window
        self._token: str = _get_token()
        self._server: QLocalServer = QLocalServer()

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
        self._server.newConnection.connect(self._handle_command)

    def close(self) -> None:
        """Close the IPC server socket."""
        self._server.close()

    def _handle_command(self) -> None:
        """Process an incoming IPC command from a sibling instance.

        Answers ACK once the window has actually been asked to show. The
        sibling waits for that byte: a process that holds the socket but no
        longer pumps its event loop never sends it, and the newcomer then
        takes the socket over instead of exiting into nothing.
        """
        sock = self._server.nextPendingConnection()
        handled = False
        if sock.bytesAvailable() > 0 or sock.waitForReadyRead(500):
            data = sock.readAll().data()
            try:
                data_str = data.decode("utf-8")
                if data_str.startswith("TOKEN:"):
                    parts = data_str.split("|", 1)
                    if len(parts) == 2:
                        recv_token = parts[0][6:]
                        cmd = parts[1]
                        if recv_token == self._token and cmd.strip() == "SHOW":
                            self._show_window()
                            handled = True
                elif data_str.strip() == "SHOW":
                    self._show_window()
                    handled = True
            except Exception:
                logger.exception("Failed to handle IPC command")
        if handled:
            try:
                sock.write(b"ACK")
                sock.flush()
                sock.waitForBytesWritten(300)
            except Exception:
                logger.debug("IPC: could not acknowledge SHOW")
        sock.disconnectFromServer()
        sock.deleteLater()
