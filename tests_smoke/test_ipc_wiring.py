import subprocess
import sys
import time
import uuid


def _wait_for(path, process, timeout=10.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists():
            return
        if process.poll() is not None:
            raise AssertionError(
                f"IPC server exited early ({process.returncode}): "
                f"{process.stdout.read()} {process.stderr.read()}"
            )
        time.sleep(0.02)
    raise AssertionError(f"timed out waiting for {path}")


def test_real_show_signal_reaches_callback_and_ack(tmp_path, monkeypatch):
    from fastprompter.core import ipc_server

    server_name = f"FastPrompter_Test_{uuid.uuid4().hex}"
    ready = tmp_path / "ready"
    shown = tmp_path / "shown"
    token_dir = tmp_path / "token"
    token_dir.mkdir()
    script = f"""
import pathlib
from PyQt6.QtCore import QCoreApplication, QTimer
from fastprompter.core import ipc_server

ipc_server.SERVER_NAME = {server_name!r}
ipc_server.tempfile.gettempdir = lambda: {str(token_dir)!r}
app = QCoreApplication([])
shown = pathlib.Path({str(shown)!r})
server = ipc_server.IpcServer(lambda: shown.write_text('shown', encoding='utf-8'))
server.setup()
pathlib.Path({str(ready)!r}).write_text('ready', encoding='utf-8')
QTimer.singleShot(10000, app.quit)
app.exec()
server.close()
"""
    process = subprocess.Popen(
        [sys.executable, "-c", script],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        _wait_for(ready, process)
        monkeypatch.setattr(ipc_server, "SERVER_NAME", server_name)
        monkeypatch.setattr(ipc_server.tempfile, "gettempdir", lambda: str(token_dir))

        assert ipc_server.request_show(ack_timeout_ms=2000, grace_ms=4000) is True
        _wait_for(shown, process)
    finally:
        process.terminate()
        process.wait(timeout=10)

    assert shown.read_text(encoding="utf-8") == "shown"
