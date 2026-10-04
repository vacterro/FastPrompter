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
import re

from fastprompter.core.translations import tr


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
    return hashlib.sha1(f"{provider_id}:{base}".encode(), usedforsecurity=False).hexdigest()[:16]


def stable_id_for_value(provider_id: str, value: str) -> str:
    """Deterministic stable id from an OPAQUE vendor identity value.

    ``stable_id_for`` runs its input through :func:`canonical_path`, which is
    right for a config file and wrong for an account id: ``abspath()`` makes
    the answer depend on the current working directory and drive letter, so
    the same vendor account produced different ids from different launch
    directories (T-1243).  A vendor account id is a value, not a path, so it
    is hashed verbatim with an unambiguous separator.
    """
    identity = (value or "").strip()
    if not identity:
        return ""
    payload = f"{provider_id}\0{identity}".encode()
    return hashlib.sha256(payload).hexdigest()[:16]


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
    # Upstream model identity the pool serves, verbatim from the vendor
    # (Codex ``normalModelSlug``, e.g. ``gpt-5.6-luna``). This is EVIDENCE:
    # it is what lets :func:`account_usable_for` decide whether a pool is a
    # named model's reserve without guessing from a label like "Reserve".
    model_slug: str = ""
    reset_pending: bool = False  # reset elapsed; awaiting provider confirmation
    # AMOUNT quotas (Freebuff Freebucks): a window whose truth is "42 of 100
    # FB left", not a percent of an abstract budget. Percent fields stay
    # exact so every existing percent consumer keeps working; the amount
    # fields carry the vendor's own numbers beside them and ``unit`` names
    # the currency. None everywhere else — percent-only windows are untouched.
    used_amount: float | None = None
    remaining_amount: float | None = None
    limit_amount: float | None = None
    unit: str = ""

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
    banked_resets: int | None = None
    # Manual/redeemable reset offers (T-1360). Conceptually separate from
    # automatic window resets (UsageWindow.resets_at_epoch), from quota
    # capacity and from wallet credit: owning a reset card never makes an
    # exhausted account usable and never enters the soonest-reset queue.
    reset_offers: tuple = ()

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
    """Invalidate percentages after reset until the provider confirms new usage.

    A clock proves that an old quota period ended, not how much the user has
    spent since. Keep an explicit pending state rather than inventing 100%.
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
            remaining_percent=None,
            used_percent=None,
            available=False,
            resets_at_epoch=None,
            gated_by=None,
            assumed_full=False,
            reset_pending=True,
        )
    return out


def resolved_windows(windows, now: float | None = None) -> list:
    """Expire old readings, then gate short windows by confirmed longer limits."""
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
    "zcode": "#4FB6A8",        # teal
    "freebuff": "#50ecb3",     # Freebuff's own brand accent (from its UI assets)
}


def provider_reset_color(provider_id: str) -> str | None:
    """Colour of the reset-timer label for one vendor, or None (theme default)."""
    return PROVIDER_RESET_COLORS.get(provider_id)


@dataclasses.dataclass(frozen=True)
class ResetCandidate:
    """One upcoming quota reset, with everything a renderer needs to name it.

    The soonest-reset topbar label and its hover queue MUST both derive from
    ``reset_candidates`` so the "↻ 42m" winner and the list it opens can never
    disagree about who resets next (they used to be two hand-rolled selection
    algorithms, and the hover list drifted).
    """

    account_key: str          # "provider:stable_id" map key
    provider_id: str
    account: AccountRef
    window: UsageWindow
    resets_at_epoch: float


def reset_candidates(snapshots, hidden_keys=frozenset()) -> list[ResetCandidate]:
    """EVERY upcoming usable quota reset, soonest first.

    The single canonical source for the topbar soonest-reset countdown and
    its hover queue. Walks all snapshots through ``resolved_windows`` and
    keeps a window when it is available, not gated by a longer sibling, and
    carries a valid positive ``resets_at_epoch``. Manually hidden accounts
    are excluded; the AUTOMATIC display filters (hide 0%-usage, hide
    unusable-5h) are deliberately NOT applied here — an exhausted account is
    exactly the one whose reset the user is waiting for.
    """
    candidates: list[ResetCandidate] = []
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
                candidates.append(ResetCandidate(
                    account_key=key, provider_id=provider,
                    account=snap.account, window=window,
                    resets_at_epoch=float(epoch)))
    candidates.sort(key=lambda c: c.resets_at_epoch)
    return candidates


def soonest_reset(snapshots, hidden_keys=frozenset()):
    """(provider_id, epoch) of the soonest usable quota reset, or (None, None).

    Derived from ``reset_candidates`` — the SAME list the hover queue
    renders — so the topbar winner and the queue can never drift apart.
    """
    candidates = reset_candidates(snapshots, hidden_keys)
    if not candidates:
        return None, None
    first = candidates[0]
    return first.provider_id, first.resets_at_epoch


# -- manual / redeemable reset offers (T-1360) ------------------------------
# A MANUAL reset offer is a redeemable card the vendor granted (Codex reset
# credits, ZCode Coding Plan reset cards, a future Claude campaign). It is
# NOT the automatic window refill (``UsageWindow.resets_at_epoch``): the two
# must never share a queue, a label or a formatter, and owning an offer says
# NOTHING about whether the account can do work right now.

@dataclasses.dataclass(frozen=True)
class ResetOffer:
    """One manual reset the vendor says this account owns.

    Fields stay optional where the provider does not prove them: an
    aggregate count (Codex ``availableCount`` without individual credits)
    yields ONE offer with an empty ``offer_id`` and a count title — never a
    fabricated per-card identity.
    """

    offer_id: str = ""               # vendor card id, "" when only a count
    provider_id: str = ""
    account_key: str = ""            # "provider:stable_id"
    target_kind: str = ""            # five_hour / weekly / vendor word
    status: str = "available"        # available / expired / consumed / unknown
    title: str = ""                  # human name, adapter-provided
    granted_at_epoch: float | None = None
    expires_at_epoch: float | None = None
    redeemable: bool = True          # the offer can be redeemed at the vendor
    # Whether FASTPROMPTER can redeem it directly (Codex: yes; Claude and
    # ZCode: not until an official route is proven — their UI action opens
    # the vendor's own usage page instead).
    redeemable_in_fastprompter: bool = False
    # How many credits this one offer stands for. 1 for an identified card;
    # N only for an honest vendor-side aggregate count (Codex
    # ``availableCount`` with no per-credit list), where one offer object
    # legitimately represents several identical credits.
    quantity: int = 1
    source: str = ""                 # provenance tag, never a secret


def offer_is_current(offer, now: float | None = None) -> bool:
    """True when this offer can be redeemed right now.

    Requires the vendor to have marked it available AND, when an expiry is
    known, the expiry to still be in the future. An unknown status is not
    availability: ``null != available reset``.
    """
    if offer is None or offer.status != "available":
        return False
    if not getattr(offer, "redeemable", True):
        return False
    expires = offer.expires_at_epoch
    if expires is None:
        return True
    if now is None:
        import time as _time
        now = _time.time()
    return isinstance(expires, (int, float)) and expires > now


def current_reset_offers(snapshot, now: float | None = None) -> list:
    """This snapshot's redeemable-now offers.

    Only an OK/STALE snapshot may state offers: an ERROR / AUTH_REQUIRED /
    UNAVAILABLE answer proves nothing about what the account still owns
    (a STALE answer keeps showing the last known offers, as with windows).
    """
    if snapshot is None or getattr(snapshot, "status", None) not in (OK, STALE):
        return []
    return [o for o in (getattr(snapshot, "reset_offers", ()) or ())
            if offer_is_current(o, now=now)]


def banked_reset_count(snapshot, now: float | None = None) -> int:
    """Redeemable-now offer count, falling back to the legacy Codex count.

    The legacy ``banked_resets`` integer stays for compatibility with
    snapshots built before offers existed; where offers ARE present they are
    the truth (they know about expiry and consumption).
    """
    offers = list(getattr(snapshot, "reset_offers", ()) or ())
    if offers:
        return sum(max(1, int(getattr(o, "quantity", 1) or 1))
                   for o in current_reset_offers(snapshot, now=now))
    value = getattr(snapshot, "banked_resets", None)
    if isinstance(value, bool) or not isinstance(value, int):
        return 0
    return max(0, value)


@dataclasses.dataclass(frozen=True)
class ResetOfferRow:
    """One account's current offers, bundled for presentation."""

    account: AccountRef
    snapshot: UsageSnapshot
    offers: list


def reset_offer_rows(snapshots, hidden_keys=frozenset(),
                     now: float | None = None) -> list:
    """Per-account current manual reset offers, for EVERY discovered account.

    The presentation source behind the topbar aggregate, the hover "Resets"
    section, the context menu and the settings overview. Deliberately
    independent of the ordinary hide-zero / hide-unusable gauge filters: an
    exhausted account is exactly the one holding a reset the user could
    redeem. Accounts the user explicitly hid in settings are excluded — that
    is a statement about the account, not a transient filter.
    """
    rows: list[ResetOfferRow] = []
    for key, snap in dict(snapshots or {}).items():
        if key in (hidden_keys or frozenset()):
            continue
        account = getattr(snap, "account", None)
        if account is None:
            continue
        offers = current_reset_offers(snap, now=now)
        if offers:
            rows.append(ResetOfferRow(account=account, snapshot=snap,
                                      offers=offers))
    return rows


def manual_reset_count(snapshots, hidden_keys=frozenset(),
                       now: float | None = None) -> int:
    """How many manual reset offers are redeemable right now (the ★ number)."""
    return sum(max(1, int(getattr(o, "quantity", 1) or 1))
               for row in reset_offer_rows(snapshots, hidden_keys, now=now)
               for o in row.offers)


def format_offer_expiry(epoch, now: float | None = None) -> str:
    """One shared formatter for MANUAL offer expiry.

    ``expires in 12m`` / ``expires in 4h 44m`` / ``expires Tue 18:00`` /
    ``expired``. The wording is "expires", never "resets in": that phrase
    belongs to the automatic window refill, and mixing the two is exactly
    the confusion the split exists to prevent.
    """
    if not isinstance(epoch, (int, float)) or epoch <= 0:
        return ""
    if now is None:
        import time as _time
        now = _time.time()
    remaining = float(epoch) - float(now)
    if remaining <= 0:
        return tr("expired")
    if remaining < 3600:
        return tr("expires in {mins}m").format(mins=int(remaining // 60) or 1)
    if remaining < 86400:
        hours = int(remaining // 3600)
        minutes = int((remaining % 3600) // 60)
        if minutes:
            return tr("expires in {hours}h {mins}m").format(
                hours=hours, mins=minutes)
        return tr("expires in {hours}h").format(hours=hours)
    import datetime as _dt
    try:
        moment = _dt.datetime.fromtimestamp(float(epoch))
    except (OverflowError, OSError, ValueError):
        return ""
    return tr("expires {when}").format(when=moment.strftime('%a %H:%M'))


def window_usable(window) -> bool:
    """True when this window currently permits work: it is available, not
    gated by a spent longer window, and still has quota left.

    Reads the window as RESOLVED (see ``resolved_windows``): an elapsed reset
    has already refilled it, and a 5h window blocked by an exhausted weekly
    sibling reports 0 here even when the server claimed 100.
    """
    if not isinstance(window, UsageWindow) or not getattr(window, "available", False):
        return False
    if getattr(window, "gated_by", None):
        return False
    rem = getattr(window, "remaining_percent", None)
    return isinstance(rem, (int, float)) and rem > _ZERO_REMAINING


def spare_balance(snapshot) -> float:
    """Spendable balance that survives the metered windows (T-1243).

    Freebuff's wallet is spent AFTER the daily pool and never resets, so an
    account whose daily Freebucks are gone can still do work.  Judging such
    an account only by its metered window makes the "hide unusable / hide
    0%" filters hide a genuinely usable account.
    """
    meta = getattr(snapshot, "provider_metadata", None) or {}
    value = meta.get("wallet_balance")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0.0
    return max(0.0, float(value))


def account_usable_now(snapshot, now: float | None = None) -> bool:
    """True when the account can do work RIGHT NOW — the rule behind "show
    only 5h-available accounts".

    The 5h window is the short-term gate for Claude / Codex / Antigravity
    pools: a 0% 5h window means the provider refuses work even while the
    weekly pool sits full, so such an account is not usable now regardless of
    its weekly reserve. A plan that reports NO 5h window (Codex Free's single
    30-day pool, Antigravity's refusal journal with its one ``quota`` window)
    is judged by whatever window it does report — the same "does anything
    have quota left" question.
    """
    if snapshot is None or getattr(snapshot, "status", None) not in (OK, STALE):
        return False
    if spare_balance(snapshot) > 0.0:
        return True                 # a non-expiring wallet is still work
    windows = [w for w in resolved_windows(
        getattr(snapshot, "windows", ()) or (), now=now)
        if isinstance(w, UsageWindow)]
    if not windows:
        return False
    groups = {w.group for w in windows}
    return any(_pool_usable([w for w in windows if w.group == group])
               for group in groups)


def _pool_usable(windows) -> bool:
    if any(w.reset_pending or not w.available for w in windows):
        return False
    five = [w for w in windows if base_key(w.key) == FIVE_HOUR]
    return any(window_usable(w) for w in (five or windows))


# -- model-specific availability -------------------------------------------
# One account can hold a NAMED-MODEL reserve beside its ordinary capacity:
# Codex reports ``rateLimitsByLimitId`` entries such as ``base_model_inference``
# (``limitName`` "gpt-reserve", ``normalModelSlug`` "gpt-5.6-luna"). Whether a
# user can actually work on a model is therefore a PER-MODEL question, and
# ``account_usable_now`` only answers the general one. Answering the general
# question with "yes" merely because SOME model-scoped reserve has quota would
# claim every model works — the exact lie this API exists to prevent.

def _model_token(window: UsageWindow) -> str:
    """The vendor model identity of a pool, lowercased, or "" when unknown."""
    return str(getattr(window, "model_slug", "") or "").strip().lower()


# A pool whose OWN reported name says it is a reserve is treated as
# model-scoped even before a model slug proves which model it serves. That is
# deliberately the CONSERVATIVE direction: a hinted-but-unproven pool is never
# allowed to answer a named-family question (so nothing is fabricated), and it
# stops being counted as general capacity for family purposes while leaving
# the family-agnostic predicates untouched.
_RESERVE_HINT = re.compile(r"reserve", re.IGNORECASE)


def _has_reserve_hint(window) -> bool:
    for field in ("group_label", "group"):
        if _RESERVE_HINT.search(str(getattr(window, field, "") or "")):
            return True
    return False


def pool_is_model_scoped(window) -> bool:
    """True when this pool serves a SPECIFIC model, not general capacity."""
    return bool(_model_token(window)) or _has_reserve_hint(window)


def pool_serves_family(window, family: str) -> bool:
    """True when the vendor PROVED this pool serves ``family``.

    Evidence is the upstream model slug (or, failing that, the pool id). A
    pool with no model identity is never claimed for a named family: unknown
    stays unknown instead of being classified by a guessed label.
    """
    token = str(family or "").strip().lower()
    if not token:
        return False
    slug = _model_token(window)
    if slug and token in slug:
        return True
    return token in str(getattr(window, "group", "") or "").lower()


def model_family_label(window) -> str:
    """Human name of the family a model-scoped pool serves ("Luna").

    Derived deterministically from the vendor slug's last token, so no
    hard-coded vendor vocabulary is required to name a future reserve.
    """
    slug = _model_token(window)
    if not slug:
        return ""
    tail = slug.replace("_", "-").replace(".", "-").split("-")
    tail = [p for p in tail if p and not p.isdigit()]
    return tail[-1].capitalize() if tail else ""


def _resolved_by_group(snapshot, now: float | None = None) -> dict:
    windows = [w for w in resolved_windows(
        getattr(snapshot, "windows", ()) or (), now=now)
        if isinstance(w, UsageWindow)]
    groups: dict[str, list] = {}
    for w in windows:
        groups.setdefault(w.group, []).append(w)
    return groups


def _any_group_usable(groups: dict, windows) -> bool:
    return any(_pool_usable(groups[w.group]) for w in windows)


def account_usable_for(snapshot, model_family: str | None = None,
                       now: float | None = None) -> bool:
    """True when this account can do work on ``model_family`` right now.

    ``model_family=None`` is the general question and delegates to
    :func:`account_usable_now`. For a named family the rules are:

    * ordinary (non model-scoped) capacity with quota left -> usable: every
      compatible model works, including this one;
    * ordinary capacity exhausted but a pool PROVEN (by upstream slug/id) to
      serve the family still has quota -> usable through that reserve;
    * ordinary capacity exhausted and only an UNPROVEN reserve has quota ->
      **not** usable. An unknown pool is never claimed for a named model;
    * a proven family pool at 0% -> not usable through the reserve.

    A family-scoped reserve never lifts any OTHER model: the answer is scoped
    to the family that was asked about.
    """
    if model_family is None or not str(model_family).strip():
        return account_usable_now(snapshot, now=now)
    if snapshot is None or getattr(snapshot, "status", None) not in (OK, STALE):
        return False
    if spare_balance(snapshot) > 0.0:
        return True
    groups = _resolved_by_group(snapshot, now)
    if not groups:
        return False
    all_windows = [w for ws in groups.values() for w in ws]
    if _any_group_usable(groups, [w for w in all_windows
                                  if not pool_is_model_scoped(w)]):
        return True
    return _any_group_usable(groups, [w for w in all_windows
                                      if pool_serves_family(w, model_family)])


def pool_labels(windows) -> list[str]:
    """Distinct non-empty pool labels, in provider order."""
    out: list[str] = []
    for w in windows:
        label = str(getattr(w, "group_label", "") or "")
        if label and label not in out:
            out.append(label)
    return out


def reserve_advice(snapshot, now: float | None = None) -> list[str]:
    """Compact recommendations for reserves that outlive ordinary capacity.

    Returns entries such as ``"Luna available via reserve"`` — ONLY for a
    pool whose upstream identity proves which model it serves AND which still
    has quota while ordinary capacity is exhausted. This states what the
    provider reported; it never claims FastPrompter controls debit order.
    """
    if snapshot is None or getattr(snapshot, "status", None) not in (OK, STALE):
        return []
    groups = _resolved_by_group(snapshot, now)
    if not groups:
        return []
    all_windows = [w for ws in groups.values() for w in ws]
    if _any_group_usable(groups, [w for w in all_windows
                                  if not pool_is_model_scoped(w)]):
        return []
    out: list[str] = []
    for ws in groups.values():
        scoped = [w for w in ws if pool_is_model_scoped(w)]
        if not scoped or not _pool_usable(ws):
            continue
        label = next((model_family_label(w) for w in scoped
                      if model_family_label(w)), "")
        if label:
            out.append(tr("{label} available via reserve").format(label=label))
    return sorted(set(out))


def display_windows(windows, now: float | None = None) -> list:
    """Windows worth DRAWING: every window of a quota pool in which ALL
    windows are dead is dropped — that pool cannot do work right now.

    Quota pools are independent (Antigravity bills Gemini models and
    Claude/GPT models against separate pools), so one pool being spent says
    nothing about the other: a dead Gemini pool is hidden while the Claude
    pool's windows stay. A pool with a usable short window keeps every window,
    because the exhausted sibling is exactly what explains the pool's state.
    Windows that belong to no pool (``group == ""`` — Codex, Claude) are
    untouched; the account-level filter (``account_usable_now``) already
    decides those.
    """
    resolved = [w for w in resolved_windows(windows, now)
                if isinstance(w, UsageWindow)]
    if not resolved:
        return []
    groups: dict[str, list] = {}
    for w in resolved:
        groups.setdefault(w.group, []).append(w)
    out = []
    for group, ws in groups.items():
        if group and not _pool_usable(ws):
            continue
        out.extend(ws)
    return out


def account_has_usage(snapshot, now: float | None = None) -> bool:
    """Return True if the snapshot reports usable capacity for hide-zero filtering.

    A positive spendable wallet (:func:`spare_balance`) is independently
    sufficient usable capacity — it never resets, so it survives both a spent
    metered pool AND the elapsed-reset/reset_pending boundary where every
    resolved window reports ``available=False`` (T-1254). It is therefore
    evaluated BEFORE the resolved metered windows, keeping this predicate
    consistent with :func:`account_usable_now` about wallet independence.

    Returns False if:
    - snapshot is missing or not in OK/STALE status (invalid statuses fail
      closed — wallet metadata never bypasses ERROR / UNAVAILABLE /
      AUTH_REQUIRED);
    - there is no wallet and no available quota windows exist;
    - there is no wallet and all windows have 0% usage (used <= 0 or
      remaining >= 100, untouched);
    - there is no wallet and all windows have 0% remaining (remaining <= 0
      or used >= 100, 0% left / exhausted).
    """
    if snapshot is None or getattr(snapshot, "status", None) not in (OK, STALE):
        return False
    # 1. status validated.  2. wallet first: a positive spendable balance is
    # capacity on its own, even when every window is reset_pending/unavailable
    # while waiting for the provider's post-reset refresh.
    if spare_balance(snapshot) > 0.0:
        return True
    from fastprompter.core.usage_limits.freebuff_format import spendable_total
    fb_total = spendable_total(snapshot)
    if fb_total is not None:
        return fb_total > 0.0

    # 3. ordinary metered-window evaluation.
    windows = [w for w in resolved_windows(getattr(snapshot, "windows", ()) or (), now=now)
               if isinstance(w, UsageWindow) and getattr(w, "available", False)]
    if not windows:
        return False

    has_any_used = False
    has_any_remaining = False

    for w in windows:
        if getattr(w, "unit", "") == "FB" or getattr(w, "key", "") == "daily_amount":
            rem_amt = getattr(w, "remaining_amount", None)
            if rem_amt is not None:
                has_capacity = isinstance(rem_amt, (int, float)) and rem_amt > 0.0
            else:
                rem_pct = getattr(w, "remaining_percent", None)
                has_capacity = isinstance(rem_pct, (int, float)) and rem_pct > 0.0
            if has_capacity:
                return True
            continue

        used = getattr(w, "used_percent", None)
        rem = getattr(w, "remaining_percent", None)
        if used is None and rem is not None:
            used = 100.0 - float(rem)
        if rem is None and used is not None:
            rem = 100.0 - float(used)

        if isinstance(used, (int, float)) and used > 0.0:
            if not getattr(w, "assumed_full", False):
                has_any_used = True
        if isinstance(rem, (int, float)) and rem > 0.0:
            has_any_remaining = True

    return has_any_used and has_any_remaining

