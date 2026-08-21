"""Regression tests for the AUDIT CORE tickets (CORE-001..CORE-010).

These exercise the root-cause repairs at unit level so each defect is caught
if it ever regresses:
  CORE-001  watcher_arm builds the sender from the validated candidate adapter
  CORE-002  armed-run queue owner is pinned by (category, slot), not the slot key
  CORE-003  physical-send barrier is per-dispatch, not a single boolean
  CORE-007  ZIP export refuses symlink/junction escapes (realpath containment)
  CORE-008  malformed undo snapshots are quarantined by _snapshot_is_valid
"""

import os

import pytest

from fastprompter.core.watcher.engine import Engine, SendIntent
from fastprompter.core.watcher.queue import QueueItem, SiloQueue, load_queues, queue_for
from fastprompter.core.watcher.sender import SendResult
from fastprompter.ui.watcher_mixin import WatcherMixin


# --------------------------------------------------------------------- harness
class _WatcherStub(WatcherMixin):
    """Minimal WatcherMixin host. `is_gui_thread` returns True when no
    QApplication exists, so the send-result handler runs in tests."""

    def __init__(self):
        self.data = {}
        self.prompt_queues = {}
        self.save_prompt_queues = lambda: None
        self.mark_dirty = lambda *a, **k: None
        self._queue_slot_key = lambda: "0"
        self.text_area = _FakeText()

    def get_current_category(self):
        return getattr(self, "_cat", "A")

    def _watcher_mark_sent(self, slot, item):
        self._marked = (slot, getattr(item, "id", None))


class _FakeText:
    def mark_queue_sent(self, item_id):
        pass


# ----------------------------------------------------------------- CORE-001
def test_build_sender_uses_candidate_adapter():
    """The candidate adapter must be the source of truth, not the not-yet
    published `_watcher_adapter` (CORE-001)."""
    m = _WatcherStub()
    m._watcher_init()
    m._watcher_adapter = None  # candidate NOT yet published

    class FakeAdapter:
        transport = "post"
        submit = "enter"
        multiline = "join"

    fake = FakeAdapter()
    # dry sender: never reaches win32
    sender = m._build_sender(False, fake)
    assert sender is not None
    # live (post) sender: builds PostMessageSender when win32 is available,
    # falls back to DryRunSender otherwise — but crucially does NOT raise.
    assert m._build_sender(True, fake) is not None


def test_watcher_arm_uses_candidate_adapter():
    """watcher_arm must call _build_sender(live, adapter) without raising the
    historical TypeError (CORE-001)."""
    m = _WatcherStub()
    m._watcher_init()

    class FakeAdapter:
        transport = "post"
        submit = "enter"
        multiline = "join"
        settle_ms = 2500
        skill_format = ""
        probes = []
        supported = staticmethod(lambda: (True, "ok"))

    # The historical defect raised
    #   TypeError: _build_sender() takes 2 positional args but 3 were given
    # because it was only called with `live`. The fix passes `adapter`.
    try:
        m.watcher_arm(None, FakeAdapter(), live=False)
    except TypeError as e:
        if "_build_sender" in str(e):
            raise AssertionError("CORE-001 regression: _build_sender "
                                  "still called without the candidate adapter")
        raise


# ----------------------------------------------------------------- CORE-003
def test_physical_barrier_is_per_dispatch():
    """A stale completion must NOT clear the barrier while a newer dispatch
    is still physically in the air (CORE-003)."""
    m = _WatcherStub()
    m._watcher_init()
    m._watcher_engine = Engine()

    intent = SendIntent("i1", "t", "0", queue_category="A")
    result = SendResult(False, "held")

    # G1 dispatched (token 1), then re-armed -> G2 dispatched (token 2)
    m._watcher_send_gen = 2
    m._watcher_send_token_seq = 2
    m._watcher_send_physical_tokens = {1, 2}

    # stale G1 completion arrives first: token 1 removed, token 2 still in air
    m._watcher_on_send_result(intent, 1, result, 1)
    assert m._watcher_send_physical_active is True

    # newer G2 completion arrives: barrier clears only now
    m._watcher_engine.state = "armed"
    m._watcher_on_send_result(intent, 2, result, 2)
    assert m._watcher_send_physical_active is False


def test_quiesce_refuses_while_physical_token_outstanding():
    """Quiesce must refuse (return False) when a physical token is unresolved."""
    m = _WatcherStub()
    m._watcher_init()
    # engine NOT armed -> the refusal path will not try to restart the timer
    m._watcher_engine = Engine()

    # simulate a single in-flight physical dispatch (no logical active flag)
    m._watcher_send_gen = 1
    m._watcher_send_token_seq = 1
    m._watcher_send_physical_tokens = {1}

    # with no GUI event loop, the bounded wait expires immediately -> refuses
    assert m._watcher_begin_quiesce(timeout_s=0) is False
    # the unresolved token must still be present
    assert m._watcher_send_physical_active is True


# ----------------------------------------------------------------- CORE-002
def test_armed_queue_owner_is_pinned_by_category():
    """After arming on category A/slot 0 and switching the live alias to B,
    the watcher still resolves the QUEUE of category A (CORE-002)."""
    m = _WatcherStub()
    m._watcher_init()

    # A's queue map has a pending item in slot 0
    a_queue = SiloQueue([QueueItem("hello from A")])
    m.prompt_queues = {"0": a_queue}
    m.data.setdefault("watcher_queues_all", {})["A"] = m.prompt_queues

    m._watcher_engine = Engine()
    m._watcher_engine.arm(None, "0", [], queue_category="A")

    # pin the owner exactly as watcher_arm does
    m._watcher_pinned_category = "A"
    m._watcher_pinned_queues = m.prompt_queues

    # now switch the LIVE alias to category B — the pinned map must persist
    m._cat = "B"
    m.prompt_queues = {"0": SiloQueue([QueueItem("hello from B")])}
    m.data["watcher_queues_all"]["B"] = m.prompt_queues

    armed = m._watcher_armed_queue_map()
    assert armed is m._watcher_pinned_queues  # still A's map, not B's


def test_stale_success_marks_original_owner_only():
    """A late success from an older run marks A's item SENT and never touches
    B's queue (CORE-002)."""
    m = _WatcherStub()
    m._watcher_init()
    m._watcher_engine = Engine()
    m._watcher_engine.state = "armed"

    a_item = QueueItem("a-pending", id="a-id")
    b_item = QueueItem("b-pending", id="b-id")
    a_queue = SiloQueue([a_item])
    b_queue = SiloQueue([b_item])
    # the persisted store is the SERIALIZED form (lists of dicts)
    m.data.setdefault("watcher_queues_all", {})
    m.data["watcher_queues_all"]["A"] = {"0": a_queue.to_list()}
    m.data["watcher_queues_all"]["B"] = {"0": b_queue.to_list()}

    # current run is now B (newer generation); the stale result is for A
    m._watcher_pinned_category = "B"
    m._watcher_pinned_queues = b_queue
    m._watcher_send_gen = 5
    stale_intent = SendIntent("a-id", "a-pending", "0", queue_category="A")
    # deliver a STALE success (gen 1, while current gen is 5)
    m._watcher_on_send_result(stale_intent, 1, SendResult(True, "ok"), 1)

    # reload A's queue from the persisted store to confirm it was persisted
    a_after = load_queues(m.data["watcher_queues_all"]["A"])["0"]
    assert a_after.find("a-id").state == "sent"
    assert b_queue.find("b-id").state == "pending"  # B item unchanged


# ----------------------------------------------------------------- CORE-007
def test_path_is_under_resolves_realpath(monkeypatch):
    """A symlinked descendant that is lexically under the root but physically
    OUTSIDE must be refused (CORE-007)."""
    from fastprompter.ui.file_container import _is_alias, _path_is_under

    orig = os.path.realpath

    def fake_realpath(p):
        # /root/link is a symlink pointing at /outside/secret
        if p.replace("\\", "/").endswith("/root/link"):
            return os.path.normpath("/outside/secret")
        return orig(p)

    monkeypatch.setattr(os.path, "realpath", fake_realpath)

    assert _path_is_under("/root", "/root/link") is False
    assert _path_is_under("/root", "/root/real.txt") is True
    assert _is_alias("/root/link") is True
    assert _is_alias("/root/real.txt") is False


# ----------------------------------------------------------------- CORE-008
from fastprompter.main import FastPrompter  # noqa: E402


class _SnapHost:
    _TRANSFER_STORE_KEYS = FastPrompter._TRANSFER_STORE_KEYS

    def _snapshot_is_valid(self, state):
        return FastPrompter._snapshot_is_valid(self, state)


def _valid_base():
    return {
        "categories": {"A": [{"name": "s", "text": "x"}]},
        "temp_presets": ["x"],
        "archive_temp_presets": [],
    }


def test_snapshot_rejects_negative_editing_index():
    h = _SnapHost()
    s = _valid_base()
    s["editing_snippet"] = ["A", -1]
    assert h._snapshot_is_valid(s) is False


def test_snapshot_rejects_editing_category_missing():
    h = _SnapHost()
    s = _valid_base()
    s["editing_snippet"] = ["ZZZ", 0]
    assert h._snapshot_is_valid(s) is False


def test_snapshot_rejects_negative_active_slot():
    h = _SnapHost()
    s = _valid_base()
    s["active_temp_slot"] = -3
    assert h._snapshot_is_valid(s) is False


def test_snapshot_rejects_foreign_transfer_key():
    h = _SnapHost()
    s = _valid_base()
    s["_transfer"] = True
    s["_transfer_dst_cat"] = "A"
    s["_transfer_dst_before"] = {"totally_unknown_store": {"A": {}}}
    assert h._snapshot_is_valid(s) is False


def test_snapshot_rejects_transfer_scalar_value():
    h = _SnapHost()
    s = _valid_base()
    s["_transfer"] = True
    s["_transfer_dst_cat"] = "A"
    s["_transfer_dst_before"] = {"silo_type_all": "not-a-dict"}
    assert h._snapshot_is_valid(s) is False


def test_snapshot_accepts_valid_transfer():
    h = _SnapHost()
    s = _valid_base()
    s["_transfer"] = True
    s["_transfer_dst_cat"] = "A"
    s["_transfer_dst_before"] = {"silo_type_all": {"A": {}}}
    assert h._snapshot_is_valid(s) is True
