"""Provider-neutral usage-limit domain model.

FastPrompter may DISPLAY authoritative limit facts, but must never invent
quota percentages, silently mutate auth, log credentials, or block the GUI
while probing. This module is the shared vocabulary every provider speaks;
the UI consumes only these records.

Stable identity rules:

* An account is identified by ``provider_id + stable_id``, never by its
  ordinal position or display name.
* ``stable_id`` is derived from a canonical (case-normalized, separator-
  normalized, resolved) source path, not from auth data.
* Two accounts are never merged merely because their display names match.
"""

from __future__ import annotations

import dataclasses
import hashlib
import os


@dataclasses.dataclass(frozen=True)
class AccountRef:
    """One discovered/configured account, provider-agnostic."""

    provider_id: str          # "codex" / "claude" / future
    stable_id: str            # provider + canonical identity, NOT ordinal
    display_name: str
    source_kind: str          # auto_default / auto_sibling / env / configured / runtime
    source_path: str = ""     # never a secret
    enabled: bool = True
    metadata: dict = dataclasses.field(default_factory=dict)

    @property
    def key(self) -> str:
        return f"{self.provider_id}:{self.stable_id}"


def canonical_path(path: str) -> str:
    """Normalize a filesystem path for stable identity + dedupe.

    On Windows, case and separators are folded before any comparison so
    ``C:\\Users\\x\\.codex`` and ``c:/users/x/.codex`` are the same account.
    """
    if not path:
        return ""
    try:
        p = os.path.abspath(os.path.expanduser(path))
        if os.name == "nt":
            p = os.path.normcase(p).replace("/", "\\")
        return p
    except Exception:
        return path


def stable_id_for(provider_id: str, source_path: str) -> str:
    """Deterministic stable account id from canonical identity, not ordinal."""
    base = canonical_path(source_path) or provider_id
    if os.name == "nt":
        base = base.lower()
    return hashlib.sha1(f"{provider_id}:{base}".encode()).hexdigest()[:16]


@dataclasses.dataclass(frozen=True)
class UsageWindow:
    """One quota window (5h, weekly, provider-specific)."""

    key: str                  # five_hour / weekly / provider-specific
    duration_minutes: int | None
    available: bool
    used_percent: float | None
    remaining_percent: float | None
    resets_at_epoch: float | None = None
    source: str = ""
    gated_by: str | None = None  # key of the longer window that makes this one unusable
    assumed_full: bool = False   # the window's own reset time passed; refill assumed
    # Independent quota pool this window belongs to. One account can hold
    # several pools that do NOT constrain each other: Antigravity bills Gemini
    # models and Claude/GPT models against separate weekly+5h pairs, so a spent
    # Claude weekly must not zero the Gemini 5h window. Empty = the account's
    # single pool (Codex, Claude), which keeps the historical behaviour.
    group: str = ""
    # Human label of that pool, for tooltips/overview ("Gemini models").
    group_label: str = ""

    @classmethod
    def unavailable(cls, key: str) -> UsageWindow:
        return cls(key=key, duration_minutes=None, available=False,
                   used_percent=None, remaining_percent=None)


@dataclasses.dataclass(frozen=True)
class UsageSnapshot:
    """One account's answer at one point in time. Never partial truth."""

    account: AccountRef
    status: str               # OK / STALE / UNAVAILABLE / AUTH_REQUIRED / ERROR
    windows: list  # list[UsageWindow]
    plan_type: str | None = None
    fetched_at: float | None = None
    stale_since: float | None = None
    error_code: str = ""
    error_summary: str = ""   # sanitized, no secrets
    provider_metadata: dict = dataclasses.field(default_factory=dict)

    def window(self, key: str) -> UsageWindow | None:
        for w in self.windows:
            if w.key == key:
                return w
        return None


# Status constants
OK = "OK"
STALE = "STALE"
UNAVAILABLE = "UNAVAILABLE"
AUTH_REQUIRED = "AUTH_REQUIRED"
ERROR = "ERROR"

# Window keys
FIVE_HOUR = "five_hour"
WEEKLY = "weekly"
MONTHLY = "monthly"

# An account can hold several independent quota pools, each with its OWN
# weekly/5h pair (Antigravity: "Gemini Models" and "Claude and GPT models").
# Two pools therefore produce two windows that would both be called "weekly" —
# and a window key is an identity: it keys the alert rule, its suppression
# state, and ``UsageSnapshot.window()``. Colliding them would give one alert
# rule authority over two unrelated limits. So a pooled window carries a
# qualified key, ``weekly@gemini_models``, while ``base_key`` recovers the
# vendor-neutral half for display and duration lookups.
_GROUP_SEP = "@"


def qualified_key(key: str, group: str = "") -> str:
    """Window identity, unique per quota pool."""
    return f"{key}{_GROUP_SEP}{group}" if group else key


def base_key(key: str) -> str:
    """The window kind behind a possibly pool-qualified key."""
    return str(key or "").split(_GROUP_SEP, 1)[0]


# An UNAVAILABLE snapshot carrying one of these codes is NOT a fault: the
# provider works exactly as designed and simply has nothing to state right now.
# Antigravity, for instance, can only quote quota when its backend refuses
# work — "no refusal recorded" is its healthy resting state, and flagging it
# would leave the header's ``!`` marker permanently lit with nothing to fix.
EXPECTED_QUIET_CODES = frozenset({"no_refusal_recorded", "quota_unknown"})

# The server can report a short window (5h) at 100% while the longer window
# that actually governs work (weekly) is already exhausted. Spending quota in
# the short window would still count against the dead longer one, so such a
# short window is effectively 0 — showing the raw number would tell the user
# "free quota" while the provider refuses every request. This is display and
# notification policy derived from the authoritative windows, never a
# provider-side invention.
_KNOWN_DURATION_MIN = {FIVE_HOUR: 300, WEEKLY: 10080, MONTHLY: 43200}
_ZERO_REMAINING = 0.5  # an exhausted window is 0%, not 0.0001%


def _duration_minutes(window: UsageWindow) -> int | None:
    if isinstance(window.duration_minutes, (int, float)) and window.duration_minutes > 0:
        return int(window.duration_minutes)
    return _KNOWN_DURATION_MIN.get(base_key(window.key))


def exhausted_key(window: UsageWindow) -> bool:
    """True when this window has no usable quota left."""
    return (window.available
            and isinstance(window.remaining_percent, (int, float))
            and window.remaining_percent <= _ZERO_REMAINING)


def gate_windows(windows) -> list:
    """Clamp short windows to 0 when a longer one in the SAME pool is exhausted.

    A longer window fully spent (weekly 0%) makes every shorter window
    (5h) effectively unusable regardless of what the server reports for it.
    The blocked window keeps its identity but is marked ``gated_by`` and
    reports 0 remaining — gauges, tooltips and notifications all read the
    gated truth instead of the raw misleading number.

    Gating is per ``group``: an account can hold several independent quota
    pools (Antigravity bills Gemini models and Claude/GPT models separately),
    and a pool being spent says nothing about the other. Comparing across them
    would zero a window the user can still spend.
    """
    out = list(windows)
    blocks: dict[str, list] = {}
    for w in out:
        if not isinstance(w, UsageWindow) or not exhausted_key(w):
            continue
        dur = _duration_minutes(w)
        if dur is None:
            continue
        blocks.setdefault(w.group, []).append((dur, w.key))
    if not blocks:
        return out
    for group in blocks:
        blocks[group].sort()
    for i, w in enumerate(out):
        if not isinstance(w, UsageWindow) or not w.available:
            continue
        mine = _duration_minutes(w)
        if mine is None:
            continue
        for bdur, bkey in blocks.get(w.group, ()):
            if bkey == w.key:
                continue
            if bdur <= mine:
                continue
            w = dataclasses.replace(
                w,
                remaining_percent=0.0,
                used_percent=100.0,
                gated_by=bkey,
            )
            out[i] = w
            break
    return out


def apply_elapsed_resets(windows, now: float) -> list:
    """Show a window as refilled the moment its OWN reset time passes.

    The provider told us exactly when the window resets. Once that timestamp
    is in the past the window is full — there is no other outcome — yet the
    gauge kept the pre-reset number until the next 3-minute sweep confirmed
    what the clock already proved. That is a stale reading the app had the
    facts to avoid.

    Only the window whose own ``resets_at_epoch`` elapsed is refilled, and the
    now-meaningless timestamp is dropped so nothing renders "resets in -4m".
    The result is marked ``assumed_full`` so the UI can say the refill is
    derived from the reset clock rather than freshly probed; the next sweep
    replaces it with the provider's own number either way.

    Runs BEFORE ``gate_windows`` (see ``resolved_windows``): gating overwrites
    the gated window's percentages, so a refill applied afterwards could not
    restore the number the gate had already destroyed.
    """
    out = list(windows)
    for i, w in enumerate(out):
        if not isinstance(w, UsageWindow) or not w.available:
            continue
        reset = w.resets_at_epoch
        if not isinstance(reset, (int, float)) or reset <= 0 or reset > now:
            continue
        out[i] = dataclasses.replace(
            w,
            remaining_percent=100.0,
            used_percent=0.0,
            resets_at_epoch=None,
            gated_by=None,
            assumed_full=True,
        )
    return out


def resolved_windows(windows, now: float | None = None) -> list:
    """The windows as every consumer must read them: reset-aware, then gated.

    ONE entry point (gauge, overview bars, tooltips, reset countdown,
    notifications) so a window can never be refilled in one view and gated in
    another. Two passes, and the order is load-bearing:

    1. ``apply_elapsed_resets`` — a window whose own reset time already passed
       is full; no probe needed to know that.
    2. ``gate_windows`` — a longer window that is STILL spent zeroes the
       shorter ones. Running this second means a weekly reset lifts its gate
       in the same pass, and the 5h window keeps its own real number instead
       of the zero the gate had written over it.
    """
    if now is None:
        import time as _time
        now = _time.time()
    return gate_windows(apply_elapsed_resets(windows, now))


# Reset-timer label colours, one per vendor, so the header countdown tells the
# user at a glance whose bucket refills next. None -> inherit the theme colour.
PROVIDER_RESET_COLORS = {
    "claude": "#D97757",       # terracotta orange
    "codex": "#6AA9FF",        # blue
    "antigravity": "#B58CE8",  # violet
}


def provider_reset_color(provider_id: str) -> str | None:
    """Colour of the reset-timer label for one vendor, or None (theme default)."""
    return PROVIDER_RESET_COLORS.get(provider_id)


def soonest_reset(snapshots, hidden_keys=frozenset()):
    """(provider_id, epoch) of the soonest usable quota reset, or (None, None).

    EVERY window of every visible account competes — 5h and weekly alike, all
    vendors together — because the question is "when does anything refill", and
    a Claude 5h window landing in 3h is the answer even while a Codex weekly is
    3 days out. Two things are skipped: a window with no reset time (nothing to
    compare) and a gated window, whose longer sibling owns the real wait
    (``_update_limit_timer_label`` mirrors this).

    ``snapshots`` is the ``{provider:stable_id: UsageSnapshot}`` map from the
    service state copy.
    """
    soonest_provider = None
    soonest_epoch = None
    for key, snap in list(snapshots.items()):
        if key in hidden_keys:
            continue
        provider = snap.account.provider_id
        for window in resolved_windows(getattr(snap, "windows", ()) or ()):
            if not getattr(window, "available", False):
                continue
            if getattr(window, "gated_by", None):
                continue
            epoch = getattr(window, "resets_at_epoch", None)
            if isinstance(epoch, (int, float)) and epoch > 0:
                if soonest_epoch is None or epoch < soonest_epoch:
                    soonest_epoch = epoch
                    soonest_provider = provider
    return soonest_provider, soonest_epoch
