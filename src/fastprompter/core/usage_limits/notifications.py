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
    for account in accounts:
        snap = snapshots.get(account.key)
        if snap is None or snap.status != OK:
            continue
        for window in resolved_windows(snap.windows):
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
            key = notification_key(account.key, window.key)
            rule = normalized_rule(raw_rules.get(key))
            low_enabled = rule["enabled"] == "True"
            reset_enabled = rule["reset_enabled"] == "True"
            if not low_enabled and not reset_enabled:
                new_state.pop(key, None)
                continue
            prior = dict(new_state.get(key, {}))
            cycle = _cycle_token(window)
            remaining = max(0.0, min(100.0, float(window.remaining_percent)))
            threshold = rule["threshold"]
            prior_remaining = prior.get("remaining")
            recovered = _recovered(prior_remaining, remaining)

            # Re-arm low alert only on genuine recovery above the threshold
            if remaining > threshold:
                prior.pop("low_alerted", None)

            # CORE-002: reset alert fires ONCE per recovery episode.
            # Latch `reset_alerted` on the first recovery jump, and re-arm
            # only when quota DROPS back down (>1% decrease).
            dropped = (isinstance(prior_remaining, (int, float))
                       and prior_remaining - remaining > 1.0)
            if dropped:
                prior.pop("reset_alerted", None)

            if recovered and reset_enabled and not prior.get("reset_alerted"):
                # Suppress false reset alerts between sessions/launches:
                # If this is the initial poll of a session, or if the reset occurred
                # in the distant past (>300s ago), do not fire a spurious alert.
                stale_reset = False
                reset_epoch = getattr(window, "resets_at_epoch", None)
                if isinstance(reset_epoch, (int, float)) and reset_epoch > 0:
                    if now - reset_epoch > 300:
                        stale_reset = True
                if not is_initial_poll and not stale_reset:
                    alerts.append(LimitAlert(
                        "reset", key, account, window, rule))
                prior["reset_alerted"] = True

            prior["remaining"] = remaining
            if low_enabled and remaining <= threshold:
                if prior.get("low_alerted") != threshold:
                    alerts.append(LimitAlert(
                        "low", key, account, window, rule))
                    prior["low_alerted"] = threshold
            prior["last_cycle"] = cycle
            new_state[key] = prior

    # Disabled/deleted rules cannot leave an unbounded graveyard behind.
    for key in list(new_state):
        if key not in enabled_rule_keys:
            new_state.pop(key, None)
    return alerts, new_state
