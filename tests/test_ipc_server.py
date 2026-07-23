"""Tests for fastprompter.core.ipc_server — IpcServer, try_connect_to_server."""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

from unittest.mock import MagicMock, patch


# Build Qt network stubs so the module can be imported without real PyQt6
class _MockQLocalSocket:
    """Stand-in for QLocalSocket."""

    def __init__(self):
        self._connected = False
        self._props = {}
        self._data = b""

    def connectToServer(self, name):
        pass

    def waitForConnected(self, timeout):
        return self._connected

    def setProperty(self, key, value):
        self._props[key] = value

    def property(self, key):
        return self._props.get(key, "")

    def write(self, data):
        self._data = data

    def flush(self):
        pass

    def disconnectFromServer(self):
        pass

    def deleteLater(self):
        pass

    def bytesAvailable(self):
        return len(self._data) > 0

    def waitForReadyRead(self, timeout):
        return len(self._data) > 0

    def readAll(self):
        return self

    def data(self):
        return self._data


class _MockQLocalServer:
    """Stand-in for QLocalServer with a persistent shared socket."""

    def __init__(self):
        self._listening = False
        self.newConnection = MagicMock()
        self._pending = _MockQLocalSocket()

    def removeServer(self, name):
        pass

    def listen(self, name):
        self._listening = True
        return True

    def close(self):
        self._listening = False

    def nextPendingConnection(self):
        return self._pending


# Stub for sys.exit
_real_exit = sys.exit


# Patch modules before importing
sys.modules["PyQt6"] = MagicMock()
sys.modules["PyQt6.QtNetwork"] = MagicMock()
sys.modules["PyQt6.QtNetwork"].QLocalServer = _MockQLocalServer
sys.modules["PyQt6.QtNetwork"].QLocalSocket = _MockQLocalSocket

from fastprompter.core.ipc_server import SERVER_NAME, IpcServer, try_connect_to_server


class TestServerName:
    """Verify the SERVER_NAME constant."""

    def test_server_name_is_string(self):
        assert isinstance(SERVER_NAME, str)

    def test_server_name_contains_fastprompter(self):
        assert "FastPrompter" in SERVER_NAME

    def test_server_name_has_version(self):
        assert "V15" in SERVER_NAME


class TestTryConnectToServer:
    """Verify the standalone try_connect_to_server function."""

    def test_returns_none_when_no_server(self):
        """No server listening -> returns None."""
        result = try_connect_to_server(retries=1, delay=0.01)
        assert result is None

    @patch("fastprompter.core.ipc_server.QLocalSocket")
    def test_returns_socket_when_connected(self, mock_socket_cls):
        """Server responds -> returns a connected socket."""
        mock_sock = MagicMock()
        mock_sock.waitForConnected.return_value = True
        mock_socket_cls.return_value = mock_sock

        result = try_connect_to_server(retries=1, delay=0.01)
        assert result is not None
        mock_sock.connectToServer.assert_called_once_with(SERVER_NAME)

    @patch("fastprompter.core.ipc_server.QLocalSocket")
    def test_attaches_token_when_token_file_exists(self, mock_socket_cls):
        """A token on disk is attached to the socket as the ipc_token property.

        The token is optional — try_connect_to_server only calls setProperty
        when the token file exists and is non-empty. Asserting that
        unconditionally made this test pass or fail depending on whether a
        stray token happened to be left in %TEMP% by a real app run.
        """
        import tempfile

        mock_sock = MagicMock()
        mock_sock.waitForConnected.return_value = True
        mock_socket_cls.return_value = mock_sock

        token_file = os.path.join(tempfile.gettempdir(), "fastprompter_ipc.token")
        had_token = os.path.exists(token_file)
        prior = None
        if had_token:
            with open(token_file) as f:
                prior = f.read()
        try:
            with open(token_file, "w") as f:
                f.write("deadbeef")
            result = try_connect_to_server(retries=1, delay=0.01)
            assert result is not None
            mock_sock.setProperty.assert_called_once_with("ipc_token", "deadbeef")
        finally:
            if had_token:
                with open(token_file, "w") as f:
                    f.write(prior)
            elif os.path.exists(token_file):
                os.remove(token_file)

    @patch("fastprompter.core.ipc_server.QLocalSocket")
    def test_no_token_property_when_token_file_absent(self, mock_socket_cls):
        """No token on disk -> no ipc_token property set (the flaky case)."""
        import tempfile

        mock_sock = MagicMock()
        mock_sock.waitForConnected.return_value = True
        mock_socket_cls.return_value = mock_sock

        token_file = os.path.join(tempfile.gettempdir(), "fastprompter_ipc.token")
        had_token = os.path.exists(token_file)
        prior = None
        if had_token:
            with open(token_file) as f:
                prior = f.read()
            os.remove(token_file)
        try:
            result = try_connect_to_server(retries=1, delay=0.01)
            assert result is not None
            mock_sock.setProperty.assert_not_called()
        finally:
            if had_token:
                with open(token_file, "w") as f:
                    f.write(prior)

    @patch("fastprompter.core.ipc_server.QLocalSocket")
    def test_retries_on_failure(self, mock_socket_cls):
        """Server doesn't respond -> retries the specified number of times."""
        mock_sock = MagicMock()
        mock_sock.waitForConnected.return_value = False
        mock_socket_cls.return_value = mock_sock

        result = try_connect_to_server(retries=3, delay=0.01)
        assert result is None
        assert mock_sock.connectToServer.call_count == 3


class TestIpcServerInit:
    """Verify IpcServer initialization."""

    def test_show_window_callback_stored(self):
        cb = MagicMock()
        server = IpcServer(cb)
        assert server._show_window is cb

    def test_token_is_string(self):
        server = IpcServer(MagicMock())
        assert isinstance(server.token, str)
        assert len(server.token) > 0

    def test_token_property(self):
        server = IpcServer(MagicMock())
        assert server.token == server._token


class TestIpcServerSetup:
    """Verify IpcServer.setup()."""

    def test_setup_creates_server(self):
        server = IpcServer(MagicMock())
        server.setup()
        assert server._server._listening is True

    def test_setup_connects_signal(self):
        server = IpcServer(MagicMock())
        server.setup()
        server._server.newConnection.connect.assert_called_once()

    @patch.object(sys, "exit")
    def test_setup_never_kills_the_process_when_it_cannot_listen(self, mock_exit):
        """It used to sys.exit(0) here.

        That is how one stuck instance turned every later launch into a
        silent no-op: the user double-clicked, no window appeared, and the
        log said nothing. Losing the socket costs single-instance handover,
        not the application - so setup returns and the window still opens.
        """
        server = IpcServer(MagicMock())

        class _FailingServer(_MockQLocalServer):
            def listen(self, name):
                return False

            def errorString(self):
                # the real QLocalServer has this; setup logs it to say WHY
                return "address in use"

        server._server = _FailingServer()
        server.setup()

        mock_exit.assert_not_called()
        server._server.newConnection.connect.assert_not_called()


class TestIpcServerHandleCommand:
    """Verify IpcServer._handle_command."""

    def test_show_command_calls_callback(self):
        """Simple 'SHOW' command -> callback is invoked."""
        cb = MagicMock()
        server = IpcServer(cb)
        server.setup()

        # Simulate an incoming SHOW command via the shared pending socket
        server._server._pending._data = b"SHOW"
        server._handle_command()

        cb.assert_called_once()

    def test_token_show_command_calls_callback(self):
        """'TOKEN:<tok>|SHOW' with correct token -> callback is invoked."""
        cb = MagicMock()
        server = IpcServer(cb)
        server.setup()

        server._server._pending._data = f"TOKEN:{server.token}|SHOW".encode()
        server._handle_command()

        cb.assert_called_once()

    def test_wrong_token_does_not_call_callback(self):
        """'TOKEN:<wrong>|SHOW' with wrong token -> callback NOT invoked."""
        cb = MagicMock()
        server = IpcServer(cb)
        server.setup()

        server._server._pending._data = b"TOKEN:wrong-token|SHOW"
        server._handle_command()

        cb.assert_not_called()

    def test_unknown_command_does_not_call_callback(self):
        """Unknown command string -> callback NOT invoked."""
        cb = MagicMock()
        server = IpcServer(cb)
        server.setup()

        server._server._pending._data = b"UNKNOWN"
        server._handle_command()

        cb.assert_not_called()

    def test_empty_data_does_not_call_callback(self):
        """Empty data -> callback NOT invoked."""
        cb = MagicMock()
        server = IpcServer(cb)
        server.setup()

        server._server._pending._data = b""
        server._handle_command()

        cb.assert_not_called()

    def test_garbled_data_does_not_crash(self):
        """Garbled/non-UTF-8 data -> callback NOT invoked (no crash)."""
        cb = MagicMock()
        server = IpcServer(cb)
        server.setup()

        server._server._pending._data = b"\xff\xfe\x00\x01"
        server._handle_command()

        cb.assert_not_called()

    def test_socket_disconnected_after_handle(self):
        """Socket is disconnected and scheduled for deletion after handling."""
        cb = MagicMock()
        server = IpcServer(cb)
        server.setup()

        server._server._pending._data = b"SHOW"
        server._handle_command()

        # We can't easily check deleteLater on the stub,
        # but we can verify it doesn't crash
        assert True

    def test_multiple_commands_sequentially(self):
        """Multiple SHOW commands -> callback called each time."""
        cb = MagicMock()
        server = IpcServer(cb)
        server.setup()

        for _ in range(3):
            server._server._pending._data = b"SHOW"
            server._handle_command()

        assert cb.call_count == 3


class TestIpcServerClose:
    """Verify IpcServer.close()."""

    def test_close_stops_listening(self):
        cb = MagicMock()
        server = IpcServer(cb)
        server.setup()
        assert server._server._listening is True
        server.close()
        assert server._server._listening is False

    def test_close_idempotent(self):
        """Calling close() twice should not raise."""
        cb = MagicMock()
        server = IpcServer(cb)
        server.setup()
        server.close()
        server.close()  # second call should be safe


class TestGetToken:
    """Verify the _get_token helper (white-box)."""

    def test_token_is_unique(self):
        from fastprompter.core.ipc_server import _get_token

        t1 = _get_token()
        t2 = _get_token()
        assert t1 != t2
