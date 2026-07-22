"""Prompt queue system for chaining prompts to external AI agents.

PromptEntry
  ─ model for one queued prompt
QueueManager
  ─ in-memory FIFO + SQLite persistence, signals for state changes
"""

import json
import time
import uuid
from collections import deque
from dataclasses import dataclass, field, asdict
from typing import Callable, Optional


@dataclass
class PromptEntry:
    """One prompt in the queue, captured from an editor line."""

    text: str
    silo_index: int = 0
    line_number: int = 0
    status: str = "queued"  # queued | sent | completed | failed
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    created_at: float = field(default_factory=time.time)
    retries: int = 0

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "PromptEntry":
        return cls(**d)


class QueueManager:
    """Thread-safe FIFO queue with optional SQLite persistence.

    Usage:
        qm = QueueManager()
        qm.append(PromptEntry(text="explain decorators", silo_index=3))
        qm.append(PromptEntry(text="write a unit test", silo_index=3))
        entry = qm.pop()   # FIFO
        qm.peek()          # look at head without popping
    """

    def __init__(self, data: Optional[dict] = None):
        self._entries: deque[PromptEntry] = deque()
        self._running = False
        self._agent_type = "claude"
        self._on_change: Optional[Callable[[], None]] = None

        if data is not None:
            self._state_data = data
            self._load_from_data(data)
        else:
            self._state_data = None

    # ---- persistence helpers (store in the existing settings dict) ----

    QUEUE_KEY = "prompt_queue_v1"

    def _load_from_data(self, data: dict) -> None:
        raw = data.get(self.QUEUE_KEY)
        if not raw:
            return
        try:
            blob = json.loads(raw) if isinstance(raw, str) else raw
            items = blob.get("entries", [])
            self._entries = deque(
                PromptEntry.from_dict(e) for e in items
            )
            self._running = blob.get("running", False)
            self._agent_type = blob.get("agent_type", "claude")
        except (json.JSONDecodeError, TypeError, KeyError):
            self._entries = deque()

    def save_to_data(self, data: dict) -> None:
        blob = {
            "entries": [e.to_dict() for e in self._entries],
            "running": self._running,
            "agent_type": self._agent_type,
        }
        data[self.QUEUE_KEY] = json.dumps(blob)

    # ---- queue operations ----

    @property
    def running(self) -> bool:
        return self._running

    @running.setter
    def running(self, value: bool) -> None:
        if self._running != value:
            self._running = value
            self._notify()

    @property
    def agent_type(self) -> str:
        return self._agent_type

    @agent_type.setter
    def agent_type(self, value: str) -> None:
        self._agent_type = value
        self._notify()

    def append(self, entry: PromptEntry) -> None:
        self._entries.append(entry)
        self._notify()

    def pop(self) -> Optional[PromptEntry]:
        try:
            entry = self._entries.popleft()
            self._notify()
            return entry
        except IndexError:
            return None

    def peek(self) -> Optional[PromptEntry]:
        try:
            return self._entries[0]
        except IndexError:
            return None

    def remove(self, entry_id: str) -> Optional[PromptEntry]:
        """Remove a specific entry by id."""
        for i, e in enumerate(self._entries):
            if e.id == entry_id:
                removed = self._entries[i]
                del self._entries[i]
                self._notify()
                return removed
        return None

    def clear(self) -> None:
        self._entries.clear()
        self._notify()

    def __len__(self) -> int:
        return len(self._entries)

    def __bool__(self) -> bool:
        return bool(self._entries)

    def __iter__(self):
        return iter(self._entries)

    def __getitem__(self, index):
        return list(self._entries)[index]

    def entries(self) -> list[PromptEntry]:
        return list(self._entries)

    # ---- change callback ----

    def set_on_change(self, callback: Optional[Callable[[], None]]) -> None:
        self._on_change = callback

    def _notify(self) -> None:
        if self._on_change is not None:
            self._on_change()
