"""T-1274 — Codex/Luna multi-pool ``rateLimitsByLimitId`` support.

Upstream shape, observed live on the operator's own Codex homes
(``codex app-server --stdio`` -> ``account/rateLimits/read``):

* ``~/.codex`` (Plus):      ``rateLimitsByLimitId == {"codex": ...}``
* ``~/.codex-account2``:    ``{"codex": ..., "base_model_inference": ...}``
  where the second pool carries ``limitName = "gpt-reserve"`` and
  ``normalModelSlug = "gpt-5.6-luna"``.
* ``~/.codex-account3free`` (Free): ``{"codex": ...}`` with a single 43200m
  window.

So a real account can hold TWO pools with the SAME duration (both weekly
10080). Window key is an IDENTITY: it keys the alert rule, its suppression
state, the reset queue and ``UsageSnapshot.window()``. An unqualified key
collapses them.
"""

from __future__ import annotations

import time

from fastprompter.core.usage_limits.model import (
    FIVE_HOUR,
    OK,
    WEEKLY,
    UsageSnapshot,
    UsageWindow,
    account_usable_for,
    display_windows,
    gate_windows,
    qualified_key,
    reserve_advice,
    reset_candidates,
)
from fastprompter.core.usage_limits.model import AccountRef as AR
from fastprompter.core.usage_limits.notifications import (
    evaluate_limit_notifications,
    notification_key,
)
from fastprompter.core.usage_limits.providers._codex_probe import (
    _iso_from_epoch,
    parse_windows,
)
from fastprompter.core.usage_limits.providers.codex import (
    CodexProvider,
    _as_window,
    _epoch,
    _windows_from,
)

LUNA_SLUG = "gpt-5.6-luna"
LUNA_POOL = "base_model_inference"


def _u(epoch_offset=3600):
    return int(time.time()) + epoch_offset


def _by_id_payload(*, codex_weekly_used=100, luna_weekly_used=0,
                   codex_five_used=0, luna_five_used=0,
                   luna_slug=LUNA_SLUG, luna_name="gpt-reserve",
                   luna_pool=LUNA_POOL):
    """Two pools, SAME weekly duration — the collision fixture."""
    return {
        "rateLimits": {
            "primary": {"windowDurationMins": 300, "usedPercent": codex_five_used,
                        "resetsAt": _u()},
            "secondary": {"windowDurationMins": 10080, "usedPercent": codex_weekly_used,
                          "resetsAt": _u(86400)},
            "planType": "plus",
            "limitId": "codex",
        },
        "rateLimitsByLimitId": {
            "codex": {
                "limitId": "codex", "planType": "plus",
                "primary": {"windowDurationMins": 300, "usedPercent": codex_five_used,
                            "resetsAt": _u()},
                "secondary": {"windowDurationMins": 10080, "usedPercent": codex_weekly_used,
                              "resetsAt": _u(86400)},
            },
            luna_pool: {
                "limitId": luna_pool, "planType": "plus",
                "limitName": luna_name, "normalModelSlug": luna_slug,
                "primary": {"windowDurationMins": 10080, "usedPercent": luna_weekly_used,
                            "resetsAt": _u(172800)},
            },
        },
    }


def _legacy_parse(rate_limits):
    """PRE-FIX parser, reconstructed: one unqualified key per duration.

    This is the RED control. It is the actual defect shape (``out[label]``
    keyed by duration alone, "first match wins"), kept here so the collision
    it causes is asserted rather than described.
    """
    out = {}
    snap = rate_limits.get("rateLimits") or {}
    for w in (snap.get("primary"), snap.get("secondary")):
        if not isinstance(w, dict):
            continue
        dur = w.get("windowDurationMins")
        label = {300: "five_hour", 10080: "weekly", 43200: "monthly"}.get(dur)
        if not label:
            continue
        out[label] = {"available": True, "used_percent": w.get("usedPercent")}
    by_id = rate_limits.get("rateLimitsByLimitId")
    if isinstance(by_id, dict):
        for _gid, sub in by_id.items():
            if not isinstance(sub, dict):
                continue
            for w in (sub.get("primary"), sub.get("secondary")):
                if not isinstance(w, dict):
                    continue
                dur = w.get("windowDurationMins")
                label = {300: "five_hour", 10080: "weekly", 43200: "monthly"}.get(dur)
                if not label:
                    continue
                out[label] = {"available": True, "used_percent": w.get("usedPercent")}
    return out


def _account(sid="acc"):
    return AR(provider_id="codex", stable_id=sid, display_name=sid,
              source_kind="test")


def _snapshot(windows, sid="acc"):
    return UsageSnapshot(account=_account(sid), status=OK, windows=list(windows),
                         fetched_at=time.time())


def _pool_windows(codex_weekly=0.0, luna_weekly=100.0, codex_five=100.0,
                  luna_five=100.0, luna_slug=LUNA_SLUG):
    """Resolved-shape windows: default pool spent, named reserve intact."""
    now = time.time()
    return [
        UsageWindow(qualified_key(WEEKLY, "codex"), 10080, True,
                    100.0 - codex_weekly, codex_weekly, now + 86400,
                    group="codex", group_label="Codex"),
        UsageWindow(qualified_key(WEEKLY, LUNA_POOL), 10080, True,
                    100.0 - luna_weekly, luna_weekly, now + 172800,
                    group=LUNA_POOL, group_label="GPT Reserve",
                    model_slug=luna_slug),
        UsageWindow(qualified_key(FIVE_HOUR, "codex"), 300, True,
                    100.0 - codex_five, codex_five, now + 3600,
                    group="codex", group_label="Codex"),
        UsageWindow(qualified_key(FIVE_HOUR, LUNA_POOL), 300, True,
                    100.0 - luna_five, luna_five, now + 3600,
                    group=LUNA_POOL, group_label="GPT Reserve",
                    model_slug=luna_slug),
    ]


# -- parsing ---------------------------------------------------------------

class TestParseMonotonic:
    def test_red_control_two_same_duration_pools_collide_without_identity(self):
        payload = _by_id_payload(codex_weekly_used=100, luna_weekly_used=0)
        legacy = _legacy_parse(payload)
        # One "weekly" for two real pools: the reserve's 0%-used reading is
        # lost (and with the opposite ordering the DEFAULT pool vanishes).
        assert list(k for k in legacy if k == "weekly") == ["weekly"]
        assert legacy["weekly"]["used_percent"] == 0

    def test_both_same_duration_pools_survive_the_parser(self):
        out = parse_windows(_by_id_payload())
        assert qualified_key(WEEKLY, "codex") in out
        assert qualified_key(WEEKLY, LUNA_POOL) in out
        assert out[qualified_key(WEEKLY, "codex")]["used_percent"] == 100
        assert out[qualified_key(WEEKLY, LUNA_POOL)]["used_percent"] == 0

    def test_group_and_label_and_slug_are_carried(self):
        out = parse_windows(_by_id_payload())
        codex = out[qualified_key(WEEKLY, "codex")]
        luna = out[qualified_key(WEEKLY, LUNA_POOL)]
        assert codex["group"] == "codex"
        assert codex["group_label"] == "Codex"
        assert codex["model_slug"] == ""
        assert luna["group"] == LUNA_POOL
        assert luna["group_label"] == "GPT Reserve"
        assert luna["model_slug"] == LUNA_SLUG

    def test_unknown_pool_label_is_humanized_not_guessed(self):
        out = parse_windows(_by_id_payload(luna_name=None, luna_slug=None))
        bucket = out[qualified_key(WEEKLY, LUNA_POOL)]
        assert bucket["group_label"] == "Base Model Inference"
        assert bucket["model_slug"] == ""

    def test_malformed_pool_fails_safely(self):
        out = parse_windows({
            "rateLimits": {},
            "rateLimitsByLimitId": {
                "codex": {"primary": {"windowDurationMins": 10080,
                                      "usedPercent": 50}},
                "broken": "not a dict",
                "empty": {},
                "no_duration": {"primary": {"usedPercent": 10}},
                "zero_duration": {"primary": {"windowDurationMins": 0,
                                              "usedPercent": 10}},
            },
        })
        assert qualified_key(WEEKLY, "codex") in out
        assert not any(k.startswith("window_") for k in out)
        for bad in ("broken", "empty", "no_duration", "zero_duration"):
            assert not any(k.endswith("@" + bad) for k in out)


# -- historical payloads stay unchanged ------------------------------------

class TestHistoricalPayloadsUnchanged:
    def test_ordinary_plus_payload_keys_unchanged(self):
        out = parse_windows({
            "rateLimits": {
                "primary": {"windowDurationMins": 10080, "usedPercent": 71,
                            "resetsAt": 1800000000},
                "secondary": {"windowDurationMins": 300, "usedPercent": 100,
                              "resetsAt": 1800000100},
            }})
        assert out["five_hour"]["remaining_percent"] == 0
        assert out["five_hour"]["window_duration_mins"] == 300
        assert out["weekly"]["remaining_percent"] == 29
        assert out["five_hour"]["group"] == ""
        assert out["weekly"]["group_label"] == ""
        assert out["weekly"]["model_slug"] == ""

    def test_free_plan_monthly_unchanged(self):
        out = parse_windows({"rateLimits": {
            "primary": {"windowDurationMins": 43200, "usedPercent": 100,
                        "resetsAt": 1790116837},
            "secondary": None,
            "planType": "free",
        }})
        assert out["monthly"]["available"] is True
        assert out["monthly"]["remaining_percent"] == 0
        assert out["plan_type"] == "free"


class TestResetEpochContract:
    def test_reset_epoch_roundtrip_stays_utc_across_dst(self):
        target = 1_767_607_200  # 2026-01-05T10:00:00Z, Tallinn winter UTC+2
        assert _iso_from_epoch(target) == "2026-01-05T10:00:00+00:00"
        parsed = parse_windows({"rateLimits": {"primary": {
            "windowDurationMins": 10080, "usedPercent": 71,
            "resetsAt": target,
        }}})
        assert _epoch(parsed["weekly"]["resets_at"]) == target


# -- probe payload -> UsageWindow ------------------------------------------

class TestWindowPropagation:
    def test_windows_group_by_pool_so_each_heading_is_drawn_once(self):
        windows = _windows_from(_probe_payload())
        groups = [w.group for w in windows]
        # The ordinary pool leads, then the reserve — contiguous, never
        # interleaved, and stable regardless of the server's own pool order.
        assert groups == ["codex", "codex", LUNA_POOL]
        assert len(set(groups)) == 2

    def test_ordinary_pool_leads_even_when_server_lists_reserve_first(self):
        payload = {
            "ok": True,
            qualified_key(WEEKLY, LUNA_POOL): {
                "available": True, "used_percent": 10,
                "window_duration_mins": 10080,
                "group": LUNA_POOL, "group_label": "GPT Reserve",
                "model_slug": LUNA_SLUG},
            qualified_key(WEEKLY, "codex"): {
                "available": True, "used_percent": 90,
                "window_duration_mins": 10080,
                "group": "codex", "group_label": "Codex"},
        }
        keys = [w.key for w in _windows_from(payload)]
        assert keys[0] == qualified_key(WEEKLY, "codex")
        assert keys[1] == qualified_key(WEEKLY, LUNA_POOL)

    def test_single_pool_order_is_unchanged_shortest_first(self):
        windows = _windows_from({
            "weekly": {"available": True, "used_percent": 10,
                       "window_duration_mins": 10080},
            "five_hour": {"available": True, "used_percent": 50,
                          "window_duration_mins": 300},
        })
        assert [w.duration_minutes for w in windows] == [300, 10080]

    def test_group_survives_into_usagewindow(self):
        windows = _windows_from(_probe_payload())
        by_key = {w.key: w for w in windows}
        codex = by_key[qualified_key(WEEKLY, "codex")]
        luna = by_key[qualified_key(WEEKLY, LUNA_POOL)]
        assert codex.group == "codex"
        assert codex.group_label == "Codex"
        assert luna.group == LUNA_POOL
        assert luna.group_label == "GPT Reserve"
        assert luna.model_slug == LUNA_SLUG

    def test_as_window_propagates_group_metadata(self):
        w = _as_window("weekly@x", {
            "available": True, "used_percent": 25, "remaining_percent": 75,
            "window_duration_mins": 10080, "group": "x",
            "group_label": "X Pool", "model_slug": "gpt-5.6-luna"})
        assert (w.group, w.group_label, w.model_slug) == ("x", "X Pool",
                                                          "gpt-5.6-luna")

    def test_red_control_dropping_group_merges_pools(self):
        """Same windows, group metadata stripped -> cross-pool gating."""
        stripped = [dataclasses_replace_group(w) for w in _pool_windows()]
        gated = {w.key: w for w in gate_windows(stripped)}
        # The untouched reserve 5h window is now eaten by the DEFAULT pool's
        # spent weekly, because 0% weekly and 100% 5h belong to "one pool".
        assert gated[qualified_key(FIVE_HOUR, LUNA_POOL)].gated_by is not None

    def test_red_control_pre_fix_as_window_drops_group(self):
        """The real pre-fix ``_as_window`` shape, reconstructed verbatim.

        It built the record from ``key/duration/used/remaining/resets/source``
        only, so the pool identity the parser had just preserved was thrown
        away one layer later.
        """
        def legacy_as_window(key, bucket):
            return UsageWindow(
                key=key,
                duration_minutes=bucket.get("window_duration_mins"),
                available=True,
                used_percent=bucket.get("used_percent"),
                remaining_percent=bucket.get("remaining_percent"),
                resets_at_epoch=None,
                source="app-server",
            )

        out = parse_windows(_by_id_payload())
        legacy = [legacy_as_window(k, v) for k, v in out.items()
                  if isinstance(v, dict) and v.get("available")]
        assert len(legacy) == 3          # both pools parsed...
        assert {w.group for w in legacy} == {""}   # ...and merged right after
        fixed = _windows_from(_probe_payload())
        assert {w.group for w in fixed} == {"codex", LUNA_POOL}

    def test_two_pools_stay_independent_through_snapshot(self):
        gated = {w.key: w for w in gate_windows(_pool_windows())}
        assert gated[qualified_key(FIVE_HOUR, "codex")].gated_by == \
            qualified_key(WEEKLY, "codex")
        assert gated[qualified_key(FIVE_HOUR, LUNA_POOL)].gated_by is None
        assert gated[qualified_key(WEEKLY, LUNA_POOL)].remaining_percent == 100

    def test_provider_probe_keeps_both_pools_in_snapshot(self, monkeypatch):
        import fastprompter.core.usage_limits.providers._codex_probe as probe_mod
        monkeypatch.setattr(probe_mod, "probe_codex_home",
                            lambda path, deadline: _probe_payload())
        snap = CodexProvider().probe(_account(), deadline=time.time() + 5.0)
        assert snap.status == OK
        assert snap.window(qualified_key(WEEKLY, "codex")) is not None
        assert snap.window(qualified_key(WEEKLY, LUNA_POOL)) is not None

    def test_reparse_updates_instead_of_duplicating(self):
        first = parse_windows(_by_id_payload(codex_weekly_used=10))
        second = parse_windows(_by_id_payload(codex_weekly_used=90))
        assert set(second) == set(first) - {"ok"}
        snap = UsageSnapshot(account=_account(), status=OK,
                             windows=_windows_from(_probe_payload()))
        again = _windows_from(_probe_payload(codex_weekly_used=10))
        keys = [w.key for w in again]
        assert len(keys) == len(set(keys))
        assert snap.window(qualified_key(WEEKLY, "codex")).used_percent == 100

    def test_service_refresh_replaces_the_pool_set(self, monkeypatch):
        """A second sweep updates the SAME account key; pools never accumulate."""
        from fastprompter.core.usage_limits.service import UsageLimitService
        calls = {"n": 0}

        def fake_probe(path, deadline=None):
            calls["n"] += 1
            return _probe_payload(codex_weekly_used=10 if calls["n"] == 1 else 90)

        import fastprompter.core.usage_limits.providers._codex_probe as probe_mod
        monkeypatch.setattr(probe_mod, "probe_codex_home", fake_probe)
        account = _account("svc")
        svc = UsageLimitService(discover=False)
        try:
            with svc._lock:
                svc._state.accounts = [account]
            svc.refresh()
            _wait_until(lambda: calls["n"] >= 1 and "svc" in "".join(
                svc.snapshots.keys()))
            first = svc.snapshots[account.key]
            assert len(first.windows) == 3
            svc.refresh()
            _wait_until(lambda: calls["n"] >= 2 and
                        svc.snapshots[account.key].window(
                            qualified_key(WEEKLY, "codex")).used_percent == 90)
            second = svc.snapshots[account.key]
            assert len(second.windows) == 3
            keys = [w.key for w in second.windows]
            assert len(keys) == len(set(keys))
            assert list(svc.snapshots) == [account.key]
        finally:
            svc.shutdown()


def _wait_until(predicate, timeout=10.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if predicate():
                return True
        except Exception:
            pass
        time.sleep(0.02)
    return False


def dataclasses_replace_group(window):
    import dataclasses
    return dataclasses.replace(window, group="", group_label="", model_slug="")


def _probe_payload(*, codex_weekly_used=100, luna_weekly_used=0):
    parsed = parse_windows(_by_id_payload(codex_weekly_used=codex_weekly_used,
                                          luna_weekly_used=luna_weekly_used))
    payload = {"ok": True}
    for key, bucket in parsed.items():
        if key in ("plan_type", "banked_resets", "reset_credits"):
            continue
        payload[key] = bucket
    payload["plan_type"] = parsed.get("plan_type")
    payload["banked_resets"] = parsed.get("banked_resets")
    payload["reset_credits"] = parsed.get("reset_credits", [])
    return payload


# -- model-specific availability -------------------------------------------

class TestModelSpecificAvailability:
    def test_default_quota_means_ordinary_models_usable(self):
        snap = _snapshot(_pool_windows(codex_weekly=50, codex_five=100))
        assert account_usable_for(snap) is True
        assert account_usable_for(snap, "luna") is True
        assert account_usable_for(snap, "sol") is True

    def test_default_spent_luna_reserve_keeps_luna_usable(self):
        snap = _snapshot(_pool_windows(codex_weekly=0, codex_five=0,
                                       luna_weekly=100, luna_five=100))
        assert account_usable_for(snap, "luna") is True

    def test_unknown_reserve_never_claims_luna(self):
        snap = _snapshot(_pool_windows(codex_weekly=0, codex_five=0,
                                       luna_slug=""))
        assert account_usable_for(snap, "luna") is False

    def test_luna_reserve_does_not_lift_other_models(self):
        snap = _snapshot(_pool_windows(codex_weekly=0, codex_five=0,
                                       luna_weekly=100))
        assert account_usable_for(snap, "sol") is False
        assert account_usable_for(snap) is True   # account still has quota

    def test_exhausted_luna_reserve_is_unavailable(self):
        snap = _snapshot(_pool_windows(codex_weekly=0, codex_five=0,
                                       luna_weekly=0, luna_five=0))
        assert account_usable_for(snap, "luna") is False

    def test_reserve_states_itself_only_when_ordinary_is_spent(self):
        spent = _snapshot(_pool_windows(codex_weekly=0, codex_five=0))
        assert reserve_advice(spent) == ["Luna available via reserve"]
        healthy = _snapshot(_pool_windows(codex_weekly=50, codex_five=100))
        assert reserve_advice(healthy) == []

    def test_unknown_reserve_produces_no_advice(self):
        assert reserve_advice(_snapshot(_pool_windows(
            codex_weekly=0, codex_five=0, luna_slug=""))) == []


# -- UI contract -----------------------------------------------------------

class TestDisplayContract:
    def test_generic_and_luna_reserve_show_separately(self):
        snap = _snapshot(_pool_windows(codex_weekly=40, codex_five=100,
                                       luna_weekly=100, luna_five=100))
        shown = display_windows(snap.windows)
        groups = {w.group for w in shown}
        assert groups == {"codex", LUNA_POOL}
        assert len([w for w in shown if w.group == LUNA_POOL]) == 2

    def test_account_with_only_luna_reserve_is_still_visible(self):
        snap = _snapshot(_pool_windows(codex_weekly=0, codex_five=0,
                                       luna_weekly=100, luna_five=100))
        assert display_windows(snap.windows)          # not hidden
        assert reserve_advice(snap)


# -- identity: alerts / reset queue ----------------------------------------

class TestPoolIdentity:
    def test_alert_keys_never_share_identity(self):
        a = _snapshot(_pool_windows())
        k_codex = notification_key(a.account.key, qualified_key(WEEKLY, "codex"))
        k_luna = notification_key(a.account.key, qualified_key(WEEKLY, LUNA_POOL))
        assert k_codex != k_luna

    def test_low_alert_on_one_pool_does_not_suppress_the_other(self):
        snap = _snapshot(_pool_windows(codex_weekly=0, luna_weekly=0))
        rules = {notification_key(snap.account.key, qualified_key(WEEKLY, LUNA_POOL)):
                 {"enabled": "True", "threshold": 10}}
        alerts, _state = evaluate_limit_notifications(
            [snap.account], {snap.account.key: snap}, rules, {})
        assert [al.window.key for al in alerts] == \
            [qualified_key(WEEKLY, LUNA_POOL)]
        assert all(al.window.group == LUNA_POOL for al in alerts)

    def test_reset_queue_keeps_distinct_pool_identities(self):
        snap = _snapshot(_pool_windows(codex_weekly=0, luna_weekly=50))
        cands = reset_candidates({snap.account.key: snap})
        keys = [c.window.key for c in cands]
        assert qualified_key(WEEKLY, "codex") in keys
        assert qualified_key(WEEKLY, LUNA_POOL) in keys
        assert len(keys) == len(set(keys))

    def test_two_accounts_stay_isolated(self):
        a = _snapshot(_pool_windows(codex_weekly=0, codex_five=0,
                                    luna_weekly=100), sid="a")
        b = _snapshot(_pool_windows(codex_weekly=90, codex_five=100,
                                    luna_weekly=0), sid="b")
        snaps = {a.account.key: a, b.account.key: b}
        # A lives on its reserve; B still has ordinary capacity and no reserve.
        assert account_usable_for(snaps[a.account.key], "luna") is True
        assert reserve_advice(snaps[a.account.key]) == \
            ["Luna available via reserve"]
        assert reserve_advice(snaps[b.account.key]) == []
        assert account_usable_for(snaps[b.account.key], "luna") is True
        assert reset_candidates(snaps)
        keys = {c.account_key for c in reset_candidates(snaps)}
        assert keys == {a.account.key, b.account.key}
