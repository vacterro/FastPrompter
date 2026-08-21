"""T-811 regression: the watcher quiesce must be two-phase so an in-flight
send is never lost or silently disarmed.

These run against the REAL WatcherMixin methods with a minimal QObject (no
full FastPrompter window), so they exercise the actual quiesce/send-result
logic without the heavy UI boot that the shared `win` fixture requires.
"""

import os
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QObject

from fastprompter.core.watcher.engine import SendIntent
from fastprompter.core.watcher.queue import QueueItem, SiloQueue
from fastprompter.core.watcher.sender import SendResult
from fastprompter.ui.watcher_mixin import WatcherMixin


class _MinimalWatcher(WatcherMixin, QObject):
    """A bare QObject carrying only what the quiesce/send-result paths touch."""

    def __init__(self):
        QObject.__init__(self)
        self.prompt_queues = {}
        self._saved = 0

    def save_prompt_queues(self):
        self._saved += 1

    @property
    def text_area(self):
        class _TA:
            def mark_queue_sent(self, *a, **k):
                pass
        return _TA()

    def _queue_slot_key(self):
        return "0"


def _setup_inflight(q, text="hello"):
    q._watcher_init()
    q._watcher_target = object()
    eng = q._watcher_engine
    eng.state = "sending"
    eng.queue_key = "0"
    item = QueueItem(text=text)
    q.prompt_queues["0"] = SiloQueue([item])
    intent = SendIntent(item.id, text, "0", "", time.monotonic())
    eng.pending = intent
    q._watcher_send_gen = 1
    q._watcher_send_active = True
    # CORE-003: a real dispatch registers a PHYSICAL token; the quiesce
    # barrier waits on outstanding physical tokens, so the simulated
    # in-flight send must register one too.
    q._watcher_send_token_seq += 1
    token = q._watcher_send_token_seq
    q._watcher_send_physical_tokens.add(token)
    q._watcher_start_timer()
    return item, intent, token


def test_quiesce_timeout_keeps_watcher_armed_and_late_send_succeeds():
    q = _MinimalWatcher()
    try:
        item, intent, token = _setup_inflight(q)
        refused = q._watcher_begin_quiesce(timeout_s=0.05)
        # refused: watcher runtime rolled back, still armed, send still active
        assert refused is False
        assert q._watcher_engine.armed is True
        assert q._watcher_timer.isActive() is True
        assert q._watcher_send_active is True
        assert item.state == "pending"
        # the late success arrives now (engine still armed) -> applied once
        q._watcher_on_send_result(intent, 1, SendResult(True, "ok", "hello"), token)
        assert item.state == "sent"
        assert q._watcher_send_active is False
        assert q._watcher_engine.sent_count == 1
    finally:
        q._watcher_stop_timer()
        q.watcher_disarm()


def test_quiesce_success_disarms_after_send_resolves():
    q = _MinimalWatcher()
    try:
        item, intent, token = _setup_inflight(q)
        # resolve the send immediately, before quiescing
        q._watcher_on_send_result(intent, 1, SendResult(True, "ok", "hello"), token)
        assert item.state == "sent"
        ok = q._watcher_begin_quiesce(timeout_s=0.2)
        assert ok is True
        assert q._watcher_engine.armed is False
        assert q._watcher_engine.sent_count == 1
    finally:
        q._watcher_stop_timer()
        q.watcher_disarm()


def test_quiesce_success_blocks_new_sends():
    q = _MinimalWatcher()
    try:
        q._watcher_init()
        # arm a believable engine (no real target needed for the armed flag)
        eng = q._watcher_engine
        eng.state = "armed"
        eng.queue_key = "0"
        ok = q._watcher_begin_quiesce(timeout_s=0.2)
        assert ok is True
        assert q._watcher_engine.armed is False
        before = q._watcher_send_active
        # a tick on a disarmed engine must not dispatch a new send
        q._watcher_tick_inner()
        assert q._watcher_send_active == before
    finally:
        q._watcher_stop_timer()
        q.watcher_disarm()
