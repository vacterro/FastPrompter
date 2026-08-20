"""Per-silo prompt queues.

One queue per silo, each in its own strict order. The store is shaped like
the other slot-keyed maps in main.py ({slot: value}, aliased into a
per-category `_all` dict), so reordering or deleting silos remaps it
through the existing `str_dict` machinery instead of needing its own.

A queued item is a REFERENCE to a line, not a copy of it: editing the line
edits what will be sent. `text` here is the last known value, used while
the silo is unloaded and kept as the fallback if the line is ever deleted.

Qt-free, so the ordering rules can be tested without a window.
"""

from __future__ import annotations

import datetime
import uuid

PENDING = "pending"
SENT = "sent"
FAILED = "failed"
SKIPPED = "skipped"
DETACHED = "detached"          # the source line is gone; text is the last we saw
STATES = (PENDING, SENT, FAILED, SKIPPED, DETACHED)

# States that still want to go out. Anything else has had its turn.
_LIVE = (PENDING,)


def _now():
    return datetime.datetime.now().isoformat(timespec="seconds")


class QueueItem:
    """One queued prompt: the line it came from, and the skill to prepend."""

    __slots__ = ("id", "text", "skill", "line", "state", "reason",
                 "created", "sent_at")

    def __init__(self, text, skill="", line=0, id=None, state=PENDING,
                 reason="", created=None, sent_at=None):
        self.id = id or uuid.uuid4().hex[:12]
        self.text = text if isinstance(text, str) else ""
        self.skill = (skill or "").lstrip("/").strip()
        try:
            # 1-based to match the gutter; 0 means "no line known"
            self.line = max(0, int(line))
        except (TypeError, ValueError):
            self.line = 0
        self.state = state if state in STATES else PENDING
        self.reason = reason or ""
        self.created = created or _now()
        self.sent_at = sent_at or None

    # ---- composing ----------------------------------------------------
    def compose(self, skill_format="/{skill} {text}"):
        """The string that would be sent, or None if it cannot be composed.

        Returns None when the item carries a skill the target cannot invoke
        (`skill_format` is None). Sending it without the skill would be a
        different request than the one that was queued, so the caller is
        expected to skip the item and say why rather than strip it.
        """
        text = (self.text or "").strip()
        if not self.skill:
            return text
        if not skill_format:
            return None
        return skill_format.format(skill=self.skill, text=text).strip()

    # ---- state --------------------------------------------------------
    def mark_sent(self):
        self.state = SENT
        self.reason = ""
        self.sent_at = _now()

    def mark_failed(self, reason=""):
        self.state = FAILED
        self.reason = reason or "send failed"

    def mark_skipped(self, reason=""):
        self.state = SKIPPED
        self.reason = reason or "skipped"

    def mark_detached(self, reason=""):
        self.state = DETACHED
        self.reason = reason or "source line was deleted"

    def reset(self):
        """Put a finished item back in line — the retry path."""
        self.state = PENDING
        self.reason = ""
        self.sent_at = None

    # ---- serialisation ------------------------------------------------
    def to_dict(self):
        return {
            "id": self.id,
            "text": self.text,
            "skill": self.skill,
            "line": self.line,
            "state": self.state,
            "reason": self.reason,
            "created": self.created,
            "sent_at": self.sent_at,
        }

    @classmethod
    def from_dict(cls, d, seen=None):
        """None for anything malformed — one corrupt entry must not take the
        whole queue (or the app) down with it.

        ``seen`` is a shared id set across the whole load: a duplicate,
        numeric, empty or whitespace id is replaced with a fresh globally
        unique one, and any id already consumed (even in another slot) yields a
        new one — so two items never end up sharing an identity and becoming
        indistinguishable to find/move/remove.
        """
        if not isinstance(d, dict):
            return None
        text = d.get("text")
        if not isinstance(text, str):
            return None

        # skill is a str in storage; a stray int (e.g. ``skill=123``) must be
        # coerced, not passed to str.lstrip, which would crash the loader.
        skill = d.get("skill", "")
        skill = "" if skill is None else str(skill)

        state = d.get("state", PENDING)
        if state not in STATES:
            state = PENDING

        raw_id = d.get("id")
        if isinstance(raw_id, str) and raw_id.strip():
            item_id = raw_id.strip()
        else:
            item_id = uuid.uuid4().hex[:12]
        if seen is not None:
            if item_id in seen:
                item_id = uuid.uuid4().hex[:12]
            seen.add(item_id)

        reason = d.get("reason", "")
        reason = "" if reason is None else str(reason)

        line = d.get("line", 0)
        try:
            line = max(0, int(line))
        except (TypeError, ValueError):
            line = 0

        return cls(
            text=text,
            skill=skill,
            line=line,
            id=item_id,
            state=state,
            reason=reason,
            created=d.get("created"),
            sent_at=d.get("sent_at"),
        )


class SiloQueue:
    """The ordered items of one silo. Order is explicit; nothing sorts it."""

    def __init__(self, items=None):
        self.items = list(items or [])

    def __len__(self):
        return len(self.items)

    def __iter__(self):
        return iter(self.items)

    # ---- editing ------------------------------------------------------
    def append(self, item):
        self.items.append(item)
        return item

    def insert(self, index, item):
        self.items.insert(max(0, min(index, len(self.items))), item)
        return item

    def find(self, item_id):
        return next((i for i in self.items if i.id == item_id), None)

    def remove(self, item_id):
        item = self.find(item_id)
        if item is not None:
            self.items.remove(item)
        return item

    def move(self, item_id, index):
        """Move an item to an absolute position, clamped."""
        item = self.find(item_id)
        if item is None:
            return False
        self.items.remove(item)
        self.items.insert(max(0, min(index, len(self.items))), item)
        return True

    def to_front(self, item_id):
        """What "send next" does: jump the queue WITHOUT sending now.

        Typing into a busy agent is the hazard this whole feature is built
        to avoid, so the fastest an item can go is "first in line".
        """
        return self.move(item_id, 0)

    # ---- reading ------------------------------------------------------
    def next_pending(self):
        return next((i for i in self.items if i.state in _LIVE), None)

    def pending(self):
        return [i for i in self.items if i.state in _LIVE]

    def to_list(self):
        return [i.to_dict() for i in self.items]


def load_queues(raw):
    """{slot key: SiloQueue} from stored data, skipping anything corrupt.

    The id-heal in ``QueueItem.from_dict`` is driven by ONE shared set across
    every slot, so a duplicate/numeric/whitespace id collides with nothing. A
    legacy numeric slot key (``1``) and its string alias (``"1"`` normalise to
    the same key: their items are MERGED, never silently discarded.
    """
    out = {}
    if not isinstance(raw, dict):
        return out
    seen = set()
    for slot, entries in raw.items():
        if not isinstance(entries, list):
            continue
        key = str(slot)
        items = []
        for entry in entries:
            item = QueueItem.from_dict(entry, seen)
            if item is not None:
                items.append(item)
        if not items:
            continue
        if key in out:
            # same logical slot reached via two raw keys (e.g. 1 / "1")
            out[key].items.extend(items)
        else:
            out[key] = SiloQueue(items)
    return out


def save_queues(queues):
    """Back to plain data. Empty queues are dropped rather than stored as
    noise — the same reason childless parents are pruned in silo_children."""
    out = {}
    for slot, queue in (queues or {}).items():
        if len(queue):
            out[str(slot)] = queue.to_list()
    return out


def queue_for(queues, slot, create=True):
    """The queue for a slot, created on demand."""
    key = str(slot)
    queue = queues.get(key)
    if queue is None and create:
        queue = queues[key] = SiloQueue()
    return queue


def all_items(queues, labels=None):
    """Every item across every silo, for the master view.

    Returns [(slot, label, item)] in slot order then queue order, so the
    master view shows the same order the silos themselves are in. `labels`
    maps a slot to its display name.
    """
    rows = []
    for slot in sorted(queues, key=_slot_sort_key):
        label = (labels or {}).get(slot, "") or (labels or {}).get(int_or(slot), "")
        for item in queues[slot]:
            rows.append((slot, label, item))
    return rows


def find_item(queues, item_id):
    """(slot, item) for an id anywhere in the store, or (None, None)."""
    for slot, queue in (queues or {}).items():
        item = queue.find(item_id)
        if item is not None:
            return slot, item
    return None, None


def move_between(queues, item_id, from_slot, to_slot, index=None):
    """Drag an item from one silo's queue into another's."""
    src = queues.get(str(from_slot))
    if src is None:
        return False
    item = src.find(item_id)
    if item is None:
        return False
    dst = queue_for(queues, to_slot)
    src.remove(item_id)
    if index is None:
        dst.append(item)
    else:
        dst.insert(index, item)
    return True


def int_or(value, default=-1):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _slot_sort_key(slot):
    """Numeric where possible so slot 10 sorts after slot 9, not after 1."""
    n = int_or(slot)
    return (0, n) if n >= 0 else (1, str(slot))
