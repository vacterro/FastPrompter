from PyQt6.QtNetwork import QLocalServer, QLocalSocket
from PyQt6.QtCore import pyqtSignal, QObject
import time

class SingleInstanceSignals(QObject):
    show_requested = pyqtSignal()

class SingleInstanceManager:
    def __init__(self, server_name: str = "FastPrompter_SingleInstance"):
        self.server_name = server_name
        self.signals = SingleInstanceSignals()
        self.server = None

    def try_connect(self, retries=3, delay=0.05):
        for _ in range(retries):
            sock = QLocalSocket()
            sock.connectToServer(self.server_name)
            if sock.waitForConnected(100):
                return sock
            time.sleep(delay)
        return None

    def start_server(self) -> bool:
        """Returns True if this is the first instance and server started."""
        # Try to connect to existing instance
        sock = self.try_connect(retries=3, delay=0.05)
        if sock is not None:
            sock.write(b"SHOW")
            sock.waitForBytesWritten(500)
            sock.disconnectFromServer()
            return False

        # No instance running, start our own server
        QLocalServer.removeServer(self.server_name)
        self.server = QLocalServer()
        self.server.newConnection.connect(self._handle_connection)
        if not self.server.listen(self.server_name):
            print(f"Failed to start local server: {self.server.errorString()}")
            return False
        return True

    def _handle_connection(self):
        socket = self.server.nextPendingConnection()
        if socket.waitForReadyRead(500):
            msg = socket.readAll().data()
            if msg == b"SHOW":
                self.signals.show_requested.emit()
        socket.disconnectFromServer()
