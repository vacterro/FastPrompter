"""The watcher state machine: when may the next prompt go out?

Decides, and only decides. `tick()` returns an INTENT — a composed string
and the item it came from — and something else does the typing. Keeping the
decision separate from the act is what makes every rule here testable
without a window, an agent, or a keyboard.

Reality arrives as arguments (the clock, the probes, whether the target is
still there, whether something is blocking), so a test can describe any
situation without faking an operating system.
"""

from __future__ import annotations

from fastprompter.core.watcher.probes import combine

DISARMED = "disarmed"
ARMED = "armed"          # watching, but the agent has not been seen busy yet
WATCHING = "watching"    # the agent is working; waiting for it to stop
SENDING = "sending"      # an intent is out; waiting to hear how it went
STATES = (DISARMED, ARMED, WATCHING, SENDING)


class SendIntent:
    """What the sender is being asked to do. Not a promise that it worked."""

    __slots__ = ("item_id", "text", "queue_key", "skill", "at")

    def __init__(self, item_id, text, queue_key, skill="", at=0.0):
        self.item_id = item_id
        self.text = text
        self.queue_key = queue_key
        self.skill = skill
        self.at = at

    def __repr__(self):
        return f"SendIntent({self.item_id!r}, {self.text!r})"


class Engine:
    """One armed target, one queue, one decision at a time."""

    def __init__(self, settle_ms=2500, min_gap_ms=4000, max_sends=25,
                 max_failures=3):
        self.settle_ms = max(0, int(settle_ms))
        self.min_gap_ms = max(0, int(min_gap_ms))
        self.max_sends = max(1, int(max_sends))
        self.max_failures = max(1, int(max_failures))

        self.state = DISARMED
        self.target = None
        self.queue_key = None       # pinned at arm; see arm()
        self.skill_format = "/{skill} {text}"
        self.probes = []
        self.reason = ""
        self.sent_count = 0
        self.consecutive_failures = 0
        self.pending = None         # the intent currently out

        self._idle_since = None
        self._last_sent_at = None
        self._seen_busy = False
        self._ticks = 0

    # ---- arming -------------------------------------------------------
    def arm(self, target, queue_key, probes, skill_format="/{skill} {text}",
            now=0.0):
        """Bind to one target and ONE queue.

        The queue key is pinned here on purpose. If the draining queue
        followed whatever silo happened to be open, switching silos while
        armed would start feeding a different backlog into a live agent.
        """
        if not target:
            return self._disarm("no target to arm")
        self.target = target
        self.queue_key = queue_key
        self.probes = list(probes or [])
        self.skill_format = skill_format
        self.state = ARMED
        self.reason = "armed"
        self.sent_count = 0
        self.consecutive_failures = 0
        self.pending = None
        self._idle_since = None
        self._last_sent_at = None
        self._seen_busy = False
        self._ticks = 0
        for probe in self.probes:
            probe.reset()
        return self.state

    def disarm(self, reason="disarmed"):
        return self._disarm(reason)

    def panic(self):
        """Stop now, and refuse whatever was in flight.

        A panic during SENDING must not later be counted as a send: the
        report that comes back belongs to a run the user has already ended.
        """
        was = self.pending
        self._disarm("panic")
        self.pending = None
        return was

    def _disarm(self, reason):
        self.state = DISARMED
        self.reason = reason
        self._idle_since = None
        self._seen_busy = False
        return self.state

    @property
    def armed(self):
        return self.state != DISARMED

    # ---- the tick -----------------------------------------------------
    def tick(self, now, queue, blocked=False, target_ok=True):
        """Advance, and return a SendIntent when one is due.

        `blocked` is the adapter's blocker_pattern having matched - a
        permission prompt, say. It forces busy no matter what the probes
        think, because that silence is the worst moment to interrupt.
        """
        if self.state == DISARMED:
            return None

        if not target_ok:
            self._disarm("the target window is gone")
            return None

        if self.state == SENDING:
            self.reason = "waiting for the send to be reported"
            return None

        # The first tick after arming is a BASELINE, not evidence of work.
        # A probe's first read always reports busy - a new token cannot match
        # a previous one - so without this the seen-busy guard below is
        # vacuous, satisfied on tick one every single time, and arming beside
        # an already-idle agent would fire into whatever is on screen.
        #
        # Counted here rather than asked of the probes: a subclass that
        # overrides poll() never runs the base class's bookkeeping, so
        # trusting a probe to report its own priming makes the guard depend
        # on which probe happens to be configured.
        baseline = self._ticks == 0
        self._ticks += 1

        idle, reasons = combine(self.probes, now)
        if blocked:
            idle = False
            reasons = list(reasons) + ["blocked by the adapter"]

        if not idle:
            self._idle_since = None
            if not baseline:
                self._seen_busy = True
            self.state = WATCHING
            self.reason = "; ".join(reasons)
            return None

        # Idle from the very first tick means the agent was never seen
        # working. That is the state a freshly armed watcher is in, and
        # firing there would send into whatever is already on screen.
        if not self._seen_busy:
            self.state = ARMED
            self.reason = "idle, but the agent has not been seen working yet"
            return None

        if self._idle_since is None:
            self._idle_since = now
        if (now - self._idle_since) * 1000.0 < self.settle_ms:
            self.state = WATCHING
            self.reason = f"settling ({now - self._idle_since:.1f}s)"
            return None

        if self.sent_count >= self.max_sends:
            self._disarm(f"reached the {self.max_sends}-send limit")
            return None

        if (self._last_sent_at is not None
                and (now - self._last_sent_at) * 1000.0 < self.min_gap_ms):
            self.state = WATCHING
            self.reason = "rate limited"
            return None

        item = queue.next_pending() if queue is not None else None
        if item is None:
            self.state = ARMED
            self.reason = "nothing left to send"
            return None

        text = item.compose(self.skill_format)
        if text is None:
            # the item carries a skill this target cannot invoke; sending it
            # stripped would be a different request than the one queued
            item.mark_skipped(
                f"this target cannot invoke /{item.skill}")
            self.reason = f"skipped /{item.skill}: the target has no skills"
            return None
        if not text.strip():
            item.mark_skipped("the line is empty now")
            self.reason = "skipped an empty prompt"
            return None

        self.pending = SendIntent(item.id, text, self.queue_key,
                                  item.skill, now)
        self.state = SENDING
        self.reason = "sending"
        return self.pending

    # ---- reporting ----------------------------------------------------
    def report_sent(self, item=None, now=None):
        """The sender managed it."""
        if self.state != SENDING:
            return False          # a panic already ended this run
        if item is not None:
            item.mark_sent()
        self.sent_count += 1
        self.consecutive_failures = 0
        self._last_sent_at = now if now is not None else self._last_sent_at
        self.pending = None
        self._idle_since = None
        self._seen_busy = False   # wait to see it work before sending again
        self._ticks = 0           # and re-baseline, for the same reason
        self.state = ARMED
        self.reason = "sent"
        return True

    def report_failed(self, item=None, reason="", now=None):
        """It did not go. The queue carries on - up to a point.

        One failure is a hiccup; a run of them means the target is gone or
        broken, and continuing would burn the whole backlog into nothing one
        prompt at a time, leaving a queue that looks finished.
        """
        if self.state != SENDING:
            return False
        if item is not None:
            item.mark_failed(reason)
        self.consecutive_failures += 1
        self._last_sent_at = now if now is not None else self._last_sent_at
        self.pending = None
        self._idle_since = None
        self._seen_busy = False
        self._ticks = 0
        if self.consecutive_failures >= self.max_failures:
            self._disarm(
                f"{self.consecutive_failures} failures in a row: {reason}")
            return True
        self.state = ARMED
        self.reason = f"failed: {reason}"
        return True

    # ---- for the UI ---------------------------------------------------
    def status(self):
        return {
            "state": self.state,
            "reason": self.reason,
            "target": self.target,
            "queue": self.queue_key,
            "sent": self.sent_count,
            "failures": self.consecutive_failures,
        }
