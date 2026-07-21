"""Tests for fastprompter.core.watcher.engine — when may a prompt go out?

Everything real is an argument: the clock, the probes, whether the target is
alive. So every rule below is exercised without a window or an agent.
"""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

from fastprompter.core.watcher.engine import (  # noqa: E402
    ARMED,
    DISARMED,
    SENDING,
    WATCHING,
    Engine,
)
from fastprompter.core.watcher.probes import BUSY, IDLE, Probe  # noqa: E402
from fastprompter.core.watcher.queue import QueueItem, SiloQueue  # noqa: E402


class FakeProbe(Probe):
    """A probe the test drives directly."""

    kind = "fake"

    def __init__(self, idle=False):
        super().__init__(quiet_ms=0)
        self.state = IDLE if idle else BUSY

    def set(self, idle):
        self.state = IDLE if idle else BUSY

    def poll(self, now):
        return self.state, f"fake: {self.state}"


def make(items=("first", "second"), **kw):
    engine = Engine(settle_ms=1000, min_gap_ms=0, **kw)
    probe = FakeProbe(idle=False)
    queue = SiloQueue([QueueItem(t) for t in items])
    engine.arm("hwnd-1", "0", [probe])
    return engine, probe, queue


def run_to_intent(engine, probe, queue, start=0.0):
    """Baseline, then busy, then idle long enough to settle.

    TWO busy ticks, not one. The first tick after arming only establishes a
    baseline - a probe's first read always reports busy because a new token
    cannot match a previous one - so it is not evidence that the agent is
    working, and the engine will not release a prompt on the strength of it.

    Returns the FIRST intent produced: with settle_ms=0 it arrives on the
    tick right after the agent goes quiet, and a helper that only looked at
    the last tick would throw it away and report None.
    """
    probe.set(False)
    engine.tick(start, queue)          # baseline
    engine.tick(start + 0.1, queue)    # the agent is genuinely working
    probe.set(True)
    for offset in (1.0, 3.0):
        intent = engine.tick(start + offset, queue)
        if intent is not None:
            return intent
    return None


# ------------------------------------------------------------------ arming

def test_a_fresh_engine_is_disarmed_and_sends_nothing():
    engine = Engine()
    assert engine.state == DISARMED
    assert engine.tick(0.0, SiloQueue([QueueItem("x")])) is None


def test_arming_without_a_target_refuses():
    engine = Engine()
    assert engine.arm("", "0", []) == DISARMED
    assert "no target" in engine.reason


def test_the_queue_is_pinned_at_arm():
    """If the draining queue followed the open silo, switching silos while
    armed would start feeding a different backlog into a live agent."""
    engine, _p, _q = make()
    assert engine.queue_key == "0"
    engine.arm("hwnd-1", "3", [FakeProbe()])
    assert engine.queue_key == "3"


# ------------------------------------------------------- seeing it work

def test_idle_from_the_start_does_not_fire():
    """A freshly armed watcher looking at an idle agent has not seen it work
    - firing there would send into whatever is already on screen."""
    engine, probe, queue = make()
    probe.set(True)
    assert engine.tick(0.0, queue) is None
    assert engine.tick(99.0, queue) is None
    assert engine.state == ARMED
    assert "not been seen working" in engine.reason


def test_busy_then_idle_fires_after_the_settle_window():
    engine, probe, queue = make()
    probe.set(False)
    assert engine.tick(0.0, queue) is None, "tick one is only a baseline"
    assert engine.tick(0.1, queue) is None, "now it has been seen working"
    assert engine.state == WATCHING

    probe.set(True)
    assert engine.tick(1.0, queue) is None, "the window has not passed"
    intent = engine.tick(2.0, queue)
    assert intent is not None
    assert intent.text == "first"
    assert engine.state == SENDING


def test_a_flicker_back_to_busy_restarts_the_window():
    """A pause mid-turn must not accumulate into idleness."""
    engine, probe, queue = make()
    probe.set(False)
    engine.tick(0.0, queue)
    probe.set(True)
    engine.tick(0.5, queue)
    probe.set(False)
    engine.tick(0.9, queue)
    probe.set(True)
    assert engine.tick(1.5, queue) is None, "the clock restarted at the flicker"
    assert engine.tick(2.6, queue) is not None, "a full window after the flicker"


def test_a_blocker_overrides_idle_probes():
    """A permission prompt is silent, which is exactly when a send does the
    most damage."""
    engine, probe, queue = make()
    probe.set(False)
    engine.tick(0.0, queue)
    probe.set(True)
    assert engine.tick(5.0, queue, blocked=True) is None
    assert "blocked" in engine.reason
    assert engine.tick(6.0, queue, blocked=True) is None


def test_a_vanished_target_disarms():
    engine, probe, queue = make()
    probe.set(False)
    engine.tick(0.0, queue)
    assert engine.tick(1.0, queue, target_ok=False) is None
    assert engine.state == DISARMED
    assert "gone" in engine.reason


# ------------------------------------------------------------- one at a time

def test_no_second_intent_until_the_first_is_reported():
    engine, probe, queue = make()
    intent = run_to_intent(engine, probe, queue)
    assert intent is not None
    assert engine.tick(10.0, queue) is None
    assert engine.state == SENDING


def test_after_a_send_it_waits_to_see_work_again():
    """Otherwise the next prompt goes out the instant the first is reported,
    while the agent has not even started."""
    engine, probe, queue = make()
    intent = run_to_intent(engine, probe, queue)
    engine.report_sent(queue.find(intent.item_id), now=3.0)
    assert queue.items[0].state == "sent"

    probe.set(True)
    assert engine.tick(20.0, queue) is None
    assert "not been seen working" in engine.reason


def test_the_second_prompt_goes_after_the_agent_works_again():
    engine, probe, queue = make()
    first = run_to_intent(engine, probe, queue)
    engine.report_sent(queue.find(first.item_id), now=3.0)

    second = run_to_intent(engine, probe, queue, start=10.0)
    assert second is not None
    assert second.text == "second"


# ------------------------------------------------------------------ limits

def test_the_rate_limit_holds_a_prompt_back():
    engine = Engine(settle_ms=0, min_gap_ms=5000)
    probe = FakeProbe()
    queue = SiloQueue([QueueItem("a"), QueueItem("b")])
    engine.arm("hwnd", "0", [probe])

    first = run_to_intent(engine, probe, queue)
    engine.report_sent(queue.find(first.item_id), now=3.0)

    probe.set(False)
    engine.tick(4.0, queue)            # baseline again after the send
    engine.tick(4.1, queue)            # genuinely working
    probe.set(True)
    assert engine.tick(5.0, queue) is None, "only 2s since the last send"
    assert engine.reason == "rate limited"
    assert engine.tick(9.0, queue) is not None


def test_the_send_cap_disarms_rather_than_running_on():
    engine = Engine(settle_ms=0, min_gap_ms=0, max_sends=1)
    probe = FakeProbe()
    queue = SiloQueue([QueueItem("a"), QueueItem("b")])
    engine.arm("hwnd", "0", [probe])

    first = run_to_intent(engine, probe, queue)
    engine.report_sent(queue.find(first.item_id), now=3.0)

    assert run_to_intent(engine, probe, queue, start=10.0) is None
    assert engine.state == DISARMED
    assert "limit" in engine.reason


# ---------------------------------------------------------------- failures

def test_a_failure_does_not_stop_the_queue():
    engine, probe, queue = make()
    intent = run_to_intent(engine, probe, queue)
    engine.report_failed(queue.find(intent.item_id), "window busy", now=3.0)

    assert queue.items[0].state == "failed"
    assert queue.items[0].reason == "window busy"
    assert engine.state == ARMED, "the run continues"
    assert queue.next_pending().text == "second"


def test_a_run_of_failures_disarms():
    """A dead target would otherwise burn the whole backlog one prompt at a
    time and leave a queue that looks finished."""
    engine = Engine(settle_ms=0, min_gap_ms=0, max_failures=3)
    probe = FakeProbe()
    queue = SiloQueue([QueueItem(t) for t in "abcd"])
    engine.arm("hwnd", "0", [probe])

    for i in range(3):
        intent = run_to_intent(engine, probe, queue, start=i * 10.0)
        assert intent is not None, f"attempt {i + 1}"
        engine.report_failed(queue.find(intent.item_id), "nope",
                             now=i * 10.0 + 3)

    assert engine.state == DISARMED
    assert "3 failures in a row" in engine.reason


def test_one_success_clears_the_failure_run():
    engine = Engine(settle_ms=0, min_gap_ms=0, max_failures=2)
    probe = FakeProbe()
    queue = SiloQueue([QueueItem(t) for t in "abc"])
    engine.arm("hwnd", "0", [probe])

    first = run_to_intent(engine, probe, queue)
    engine.report_failed(queue.find(first.item_id), "hiccup", now=3.0)
    assert engine.consecutive_failures == 1

    second = run_to_intent(engine, probe, queue, start=10.0)
    engine.report_sent(queue.find(second.item_id), now=13.0)
    assert engine.consecutive_failures == 0
    assert engine.state == ARMED


# ------------------------------------------------------------------- panic

def test_panic_stops_everything_mid_send():
    engine, probe, queue = make()
    intent = run_to_intent(engine, probe, queue)
    assert engine.state == SENDING

    returned = engine.panic()
    assert returned is intent
    assert engine.state == DISARMED
    assert engine.tick(99.0, queue) is None


def test_a_report_after_a_panic_is_refused():
    """The report belongs to a run the user has already ended; counting it
    would let a panicked send land in the tally."""
    engine, probe, queue = make()
    intent = run_to_intent(engine, probe, queue)
    engine.panic()

    assert engine.report_sent(queue.find(intent.item_id)) is False
    assert engine.sent_count == 0
    assert queue.items[0].state == "pending"


# ------------------------------------------------------------------- skills

def test_an_item_whose_skill_the_target_cannot_invoke_is_skipped():
    """Sending it stripped would be a different request than the one queued."""
    engine = Engine(settle_ms=0, min_gap_ms=0)
    probe = FakeProbe()
    queue = SiloQueue([QueueItem("go", skill="saipen"), QueueItem("plain")])
    engine.arm("hwnd", "0", [probe], skill_format=None)

    intent = run_to_intent(engine, probe, queue)
    assert queue.items[0].state == "skipped"
    assert "saipen" in queue.items[0].reason
    # and skipping does not stall the run: the plain prompt still goes,
    # because a target without skills can carry it unchanged
    assert intent is not None
    assert intent.text == "plain"


def test_the_intent_carries_the_composed_text():
    engine = Engine(settle_ms=0, min_gap_ms=0)
    probe = FakeProbe()
    queue = SiloQueue([QueueItem("continue please", skill="saipen")])
    engine.arm("hwnd", "0", [probe])

    intent = run_to_intent(engine, probe, queue)
    assert intent.text == "/saipen continue please"
    assert intent.skill == "saipen"
    assert intent.queue_key == "0"


def test_an_item_emptied_since_queuing_is_skipped():
    engine = Engine(settle_ms=0, min_gap_ms=0)
    probe = FakeProbe()
    item = QueueItem("something")
    queue = SiloQueue([item, QueueItem("next")])
    engine.arm("hwnd", "0", [probe])

    item.text = "   "          # the line was blanked in the note
    run_to_intent(engine, probe, queue)
    assert item.state == "skipped"


# -------------------------------------------------------------- exhaustion

def test_an_empty_queue_yields_no_intent():
    engine, probe, queue = make(items=())
    assert run_to_intent(engine, probe, queue) is None
    assert engine.state == ARMED
    assert "nothing left" in engine.reason


def test_a_probe_that_raises_keeps_the_engine_alive():
    engine, probe, queue = make()

    def boom(now):
        raise RuntimeError("probe exploded")

    probe.poll = boom
    assert engine.tick(0.0, queue) is None
    assert engine.armed, "one bad probe must not disarm the run"


def test_status_reports_what_the_ui_needs():
    engine, probe, queue = make()
    probe.set(False)
    engine.tick(0.0, queue)
    status = engine.status()
    assert status["state"] == WATCHING
    assert status["target"] == "hwnd-1"
    assert status["queue"] == "0"
    assert status["sent"] == 0


# --------------------------------------------- the baseline, added in W-07

def test_a_first_reading_is_a_baseline_not_the_agent_working():
    """The seen-busy guard was vacuous until W-07.

    A probe's first read always reports busy - a new token cannot match a
    previous one - so `_seen_busy` flipped true on tick one every single
    time, and the rule that a watcher must observe real work before it may
    fire never actually blocked anything. Arm beside an agent that is
    already sitting idle and it would send into whatever was on screen.
    """
    engine = Engine(settle_ms=0, min_gap_ms=0)
    probe = FakeProbe(idle=True)
    queue = SiloQueue([QueueItem("only line")])
    engine.arm("hwnd", "0", [probe])

    for step in range(6):
        assert engine.tick(float(step), queue) is None
    assert engine._seen_busy is False, "a first reading is not evidence of work"
    assert "not been seen working" in engine.reason
    assert queue.next_pending() is not None, "the prompt is still waiting"


def test_a_probe_that_reports_busy_on_the_first_tick_is_not_believed_either():
    """The same hole from the other side: the very first poll of a REAL probe
    reports busy, so a watcher armed next to an idle agent must still refuse."""
    engine = Engine(settle_ms=0, min_gap_ms=0)
    probe = FakeProbe(idle=False)
    queue = SiloQueue([QueueItem("only line")])
    engine.arm("hwnd", "0", [probe])

    engine.tick(0.0, queue)            # the one busy reading it ever gets
    assert engine._seen_busy is False

    probe.set(True)
    for step in range(1, 6):
        assert engine.tick(float(step), queue) is None


def test_work_seen_after_the_baseline_does_release_the_queue():
    """The other half: a real transition still lets the prompt out."""
    engine = Engine(settle_ms=0, min_gap_ms=0)
    probe = FakeProbe(idle=False)
    queue = SiloQueue([QueueItem("only line")])
    engine.arm("hwnd", "0", [probe])

    engine.tick(0.0, queue)            # baseline
    engine.tick(1.0, queue)            # genuinely working
    assert engine._seen_busy is True

    probe.set(True)
    intent = None
    for step in range(2, 8):
        intent = intent or engine.tick(float(step), queue)
    assert intent is not None, "once it has been seen working, it may send"
    assert intent.text == "only line"


def test_every_send_re_baselines_so_the_next_one_waits_for_real_work_too():
    """Otherwise the whole backlog would empty into one idle moment."""
    engine, probe, queue = make()
    first = run_to_intent(engine, probe, queue)
    assert first is not None
    engine.report_sent(queue.find(first.item_id), now=4.0)

    assert engine._seen_busy is False, "it must see the agent work again"
    probe.set(True)
    for step in range(5, 11):
        assert engine.tick(float(step), queue) is None, (
            "the second prompt must not go out on the same idle stretch")

