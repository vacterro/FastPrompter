"""Abstract base for agent adapters.

Each adapter wraps one agent CLI (Claude Code, Freebuff CLI, etc.)
Standardises launch, input, completion detection, and abort.

Implementations live in sibling modules: claude.py, freebuff_cli.py, …
"""

from abc import ABC, abstractmethod

from PyQt6.QtCore import QProcess


class AgentAdapter(ABC):
    """Interface every agent adapter must implement."""

    # Human-readable label shown in the queue panel dropdown
    label = "Generic Agent"

    # Unique key used in config storage
    key = "generic"

    @abstractmethod
    def launch(self) -> QProcess:
        """Start the agent CLI process.

        Returns a started QProcess that the watcher will read from
        and write to.
        """

    @abstractmethod
    def send_prompt(self, process: QProcess, text: str) -> None:
        """Write a prompt string to the agent's stdin."""

    @abstractmethod
    def detect_completion(self, process: QProcess, stdout_buffer: str) -> bool:
        """Examine buffered stdout for the agent's "ready for next input"
        signal.

        Return True when the agent is waiting for the next prompt.
        The watcher calls this after every chunk of stdout arrives.
        """

    @abstractmethod
    def abort(self, process: QProcess) -> None:
        """Stop the agent process gracefully, then force-kill if needed."""

    def config_defaults(self) -> dict:
        """Return a dict of default user-configurable settings for this
        adapter.  Keys are merged into ``prompt_queue_config``."""
        return {
            "command": self.key,
            "completion_pattern": "",
            "timeout_seconds": 120,
        }

    # ---- convenience helpers for subclasses ----

    @staticmethod
    def _write_stdin(process: QProcess, text: str) -> None:
        """Write text + newline to the process stdin."""
        if process.state() == QProcess.ProcessState.Running:
            payload = (text + "\n").encode("utf-8")
            process.write(payload)

    @staticmethod
    def _prompt_detected(buffer: str, pattern: str) -> bool:
        """True when the buffer ends with a line matching *pattern*."""
        if not buffer.strip():
            return False
        import re
        lines = buffer.splitlines()
        return bool(re.search(pattern, lines[-1]))

    @staticmethod
    def _terminate(process: QProcess, grace_ms: int = 2000) -> None:
        """SIGTERM then SIGKILL after grace period."""
        if process.state() == QProcess.ProcessState.NotRunning:
            return
        from PyQt6.QtCore import QTimer

        process.terminate()
        if not process.waitForFinished(grace_ms):
            process.kill()
            process.waitForFinished(1000)
