"""Per-account/per-window quota alert evaluation with durable anti-spam."""

from __future__ import annotations

import dataclasses

from fastprompter.core.usage_limits.model import OK, AccountRef, UsageWindow

DEFAULT_RULE = {
    "enabled": "False",
    "threshold": 20.0,
    "sound_enabled": "True",
    "sound": "file:newday.wav",
    "volume": 0.5,
    "show_notification": "True",
    "reset_enabled": "False",
    "reset_sound_enabled": "True",
    "reset_sound": "file:success_levelup.wav",
    "reset_volume": 0.5,
    "reset_show_notification": "True",
}


def notification_key(account_key: str, window_key: str) -> str:
    return f"{account_key}|{window_key}"


def normalized_rule(raw) -> dict:
    rule = dict(DEFAULT_RULE)
    if isinstance(raw, dict):
        rule.update(raw)
    rule["enabled"] = "True" if rule.get("enabled") in (True, "True") else "False"
    rule["sound_enabled"] = (
        "True" if rule.get("sound_enabled") in (True, "True") else "False")
    rule["show_notification"] = (
        "True" if rule.get("show_notification") in (True, "True") else "False")
    rule["reset_enabled"] = (
        "True" if rule.get("reset_enabled") in (True, "True") else "False")
    rule["reset_sound_enabled"] = (
        "True" if rule.get("reset_sound_enabled") in (True, "True") else "False")
    rule["reset_show_notification"] = (
        "True" if rule.get("reset_show_notification") in (True, "True")
        else "False")
    try:
        rule["threshold"] = max(0.0, min(100.0, float(rule["threshold"])))
    except (TypeError, ValueError):
        rule["threshold"] = 20.0
    try:
        rule["volume"] = max(0.0, min(1.0, float(rule["volume"])))
    except (TypeError, ValueError):
        rule["volume"] = 0.5
    try:
        rule["reset_volume"] = max(
            0.0, min(1.0, float(rule["reset_volume"])))
    except (TypeError, ValueError):
        rule["reset_volume"] = 0.5
    sound = str(rule.get("sound") or DEFAULT_RULE["sound"])
    rule["sound"] = sound[:512]
    reset_sound = str(
        rule.get("reset_sound") or DEFAULT_RULE["reset_sound"])
    rule["reset_sound"] = reset_sound[:512]
    return rule


@dataclasses.dataclass(frozen=True)
class LimitAlert:
    kind: str  # "low" | "reset"
    key: str
    account: AccountRef
    window: UsageWindow
    rule: dict


def _cycle_token(window: UsageWindow) -> str:
    reset = window.resets_at_epoch
    if isinstance(reset, (int, float)) and reset > 0:
        return f"reset:{int(reset)}"
    return "no-reset"


# A genuine Weekly reset restores the allowance to approximately full
# capacity (observed real-world behavior: effectively ~100% in nearly every
# reset). ``recovered`` — any upward jump > 1.0 — proves only that capacity
# INCREASED, never that a quota boundary was crossed: a 20% -> 60% climb can
# be a server-side correction, a banked/spent recompute, or a fresh sample
# from a different source. So a recovery episode is a CONFIRMED reset only
# when the allowance lands near full; smaller climbs stay silent. Partial
# evidence is deliberately preferred over a confident announcement of a
# reset that did not happen.
CONFIRMED_REFILL_FRACTION = 0.9


def _classify_recovery(prior_remaining, window: UsageWindow) -> str:
    """Semantic class of a quota recovery episode.

    ``recovered`` (the caller's upward jump) is a REPLENISHMENT signal; this
    function decides whether it deserves to be called a RESET. Classes:

    * "reset"      — near-full refill; a genuine allowance boundary was
                     almost certainly crossed. The only class that notifies.
    * "partial"    — capacity increased but the window is nowhere near
                     full: correction/refill/recompute, not a reset.
    * "reconciliation" — data came from a source refresh with no percentage
                     evidence (window unavailable/unknown); never notifies.

    A hard "must be exactly 100%" rule is deliberately avoided: a reset is
    often first observed after some capacity was already consumed.
    """
    remaining = getattr(window, "remaining_percent", None)
    if not isinstance(remaining, (int, float)):
        return "reconciliation"
    if remaining >= 100.0 * CONFIRMED_REFILL_FRACTION:
        return "reset"
    return "partial"


def _recovered(prior_remaining, remaining) -> bool:
    """True when quota genuinely recovered — the ONLY real reset signal.

    The server's ``resets_at`` rolls forward while a window is simply idle,
    so an epoch change alone does not mean a reset happened (it fired "reset"
    every 3-minute sweep for an untouched 5h window). Recovery shows up as
    ``remaining`` climbing; that cannot happen through usage, only through a
    window actually refilling. A small tolerance kills float noise.
    """
    if not isinstance(prior_remaining, (int, float)):
        return False
    if not isinstance(remaining, (int, float)):
        return False
    return remaining - prior_remaining > 1.0


def evaluate_limit_notifications(accounts, snapshots, rules, state,
                                 is_initial_poll: bool = False,
                                 now: float | None = None):
    """Return ``(alerts, new_state)``.

    A rule fires once while its remaining percentage is at/below threshold.
    It re-arms only after the quota RECOVERS above the threshold (or a real
    reset lifts remaining), so a drifting ``resets_at`` on an idle window can
    never replay the same alert on every sweep. State is persisted, so an app
    restart cannot replay the same low-limit alert endlessly either.
    """
    import time as _time
    if now is None:
        now = _time.time()
    from fastprompter.core.usage_limits.model import resolved_windows
    raw_rules = rules if isinstance(rules, dict) else {}
    old_state = state if isinstance(state, dict) else {}
    new_state = {str(k): dict(v) for k, v in old_state.items()
                 if isinstance(v, dict)}
    alerts = []
    enabled_rule_keys = {
        str(key) for key, raw in raw_rules.items()
        if (normalized_rule(raw)["enabled"] == "True"
            or normalized_rule(raw)["reset_enabled"] == "True")
    }
    # CORE-001: Canonicalize accounts by verified provider identity into quota pools.
    # Group accounts sharing a verified fingerprint so only ONE alert and ONE suppression
    # episode fires per physical provider quota pool, while preserving per-account rules.
    from fastprompter.core.usage_limits import identity as _identity

    entries = [
        (a.key, snapshots.get(a.key).provider_metadata if snapshots.get(a.key) else {})
        for a in accounts
    ]
    groups = _identity.group_by_identity(entries)

    pool_members: list[list[AccountRef]] = []
    assigned_keys = set()
    for a in accounts:
        if a.key in assigned_keys:
            continue
        meta = snapshots.get(a.key).provider_metadata if snapshots.get(a.key) else {}
        fp = _identity.fingerprint_of(meta)
        if fp and fp in groups:
            members = [acc for acc in accounts if acc.key in groups[fp]]
            pool_members.append(members)
            for m in members:
                assigned_keys.add(m.key)
        else:
            pool_members.append([a])
            assigned_keys.add(a.key)

    for members in pool_members:
        canonical_account = members[0]
        snap = snapshots.get(canonical_account.key)
        if snap is None or snap.status != OK:
            continue
        for window in resolved_windows(snap.windows, now=now):
            if not isinstance(window, UsageWindow) or not window.available:
                continue
            if not isinstance(window.remaining_percent, (int, float)):
                continue
            # A window gated by an exhausted longer one (weekly 0% with 5h
            # reporting 100) is not an independent quota: alerting on it only
            # duplicates the longer window's own alert. Keep its suppression
            # state so it re-arms once the gate lifts.
            if window.gated_by:
                continue

            # Deterministic group rule semantics across pool members (CORE-001)
            effective_rule = dict(DEFAULT_RULE)
            any_low_enabled = False
            any_reset_enabled = False
            max_threshold = 20.0
            first_sound_rule = None

            for m in members:
                m_key = notification_key(m.key, window.key)
                m_rule = normalized_rule(raw_rules.get(m_key))
                if m_rule["enabled"] == "True":
                    any_low_enabled = True
                    max_threshold = max(max_threshold, m_rule["threshold"])
                    if first_sound_rule is None:
                        first_sound_rule = m_rule
                if m_rule["reset_enabled"] == "True":
                    any_reset_enabled = True
                    if first_sound_rule is None:
                        first_sound_rule = m_rule

            if first_sound_rule is not None:
                effective_rule.update(first_sound_rule)
            effective_rule["enabled"] = "True" if any_low_enabled else "False"
            effective_rule["reset_enabled"] = "True" if any_reset_enabled else "False"
            effective_rule["threshold"] = max_threshold

            key = notification_key(canonical_account.key, window.key)
            if not any_low_enabled and not any_reset_enabled:
                new_state.pop(key, None)
                for m in members[1:]:
                    new_state.pop(notification_key(m.key, window.key), None)
                continue

            prior = dict(new_state.get(key, {}))
            cycle = _cycle_token(window)
            remaining = max(0.0, min(100.0, float(window.remaining_percent)))
            threshold = effective_rule["threshold"]
            prior_remaining = prior.get("remaining")
            recovered = _recovered(prior_remaining, remaining)

            # Re-arm low alert only on genuine recovery above the threshold
            if remaining > threshold:
                prior.pop("low_alerted", None)

            # CORE-002: reset alert fires ONCE per recovery episode.
            # Latch `reset_alerted` on the confirmed recovery, and re-arm
            # only when quota falls back OUT of confirmed-reset territory
            # (a 1%-jitter dip near full must not re-arm the announcement;
            # genuine consumption crosses the confirmed boundary).
            confirmed_full = 100.0 * CONFIRMED_REFILL_FRACTION
            dropped = (isinstance(prior_remaining, (int, float))
                       and prior_remaining >= confirmed_full
                       and remaining < confirmed_full)
            if dropped:
                prior.pop("reset_alerted", None)

            if recovered and any_reset_enabled and not prior.get("reset_alerted"):
                # A recovery episode is a SEMANTIC event, not merely an
                # upward movement: only a CONFIRMED reset (near-full refill,
                # see _classify_recovery) may notify. A 20% -> 60% climb
                # stays silent — partial refill/correction is exactly the
                # false-positive this guard exists for. A partial episode
                # stays UNLATCHED so a later near-full confirmation within
                # the same climb can still notify (exactly once — the latch
                # arms on confirmation, not on the first step).
                if _classify_recovery(prior_remaining, window) == "reset":
                    # Suppress false reset alerts between sessions/launches:
                    # If this is the initial poll of a session, or if the reset
                    # occurred in the distant past (>300s ago), do not fire a
                    # spurious alert.
                    stale_reset = False
                    reset_epoch = getattr(window, "resets_at_epoch", None)
                    if isinstance(reset_epoch, (int, float)) and reset_epoch > 0:
                        if now - reset_epoch > 300:
                            stale_reset = True
                    if not is_initial_poll and not stale_reset:
                        alerts.append(LimitAlert(
                            "reset", key, canonical_account, window, effective_rule))
                    prior["reset_alerted"] = True

            prior["remaining"] = remaining
            if any_low_enabled and remaining <= threshold:
                if prior.get("low_alerted") != threshold:
                    alerts.append(LimitAlert(
                        "low", key, canonical_account, window, effective_rule))
                    prior["low_alerted"] = threshold
            prior["last_cycle"] = cycle
            new_state[key] = prior

            # Ensure duplicate member contexts share this suppression and don't linger
            for m in members[1:]:
                new_state.pop(notification_key(m.key, window.key), None)

    # Disabled/deleted rules cannot leave an unbounded graveyard behind.
    for key in list(new_state):
        if key not in enabled_rule_keys:
            # Also keep if key is the canonical key for a member with an enabled rule
            k_win = key.split("|")[-1] if "|" in key else ""
            keep_canon = False
            for members in pool_members:
                if notification_key(members[0].key, k_win) == key:
                    if any(notification_key(m.key, k_win) in enabled_rule_keys for m in members):
                        keep_canon = True
                        break
            if not keep_canon:
                new_state.pop(key, None)
    return alerts, new_state
