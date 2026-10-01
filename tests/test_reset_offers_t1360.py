"""T-1360: cross-provider redeemable/manual reset offers.

Codex + Claude + ZCode Coding Plans can each hold MANUAL reset offers that
are conceptually separate from automatic window resets, quota capacity and
wallet credit. These tests pin the whole contract:

* a generic ``ResetOffer`` model carried on ``UsageSnapshot``;
* the Codex visibility bug: an exhausted account hidden by the ordinary
  hide-zero / hide-unusable filters STILL shows its reset offer in the
  topbar (aggregate badge + hover "Resets" section + context menu);
* owning a reset never makes an account "usable now" and never enters the
  automatic soonest-reset queue;
* the Claude parser is defensive: campaign-shaped metadata must carry
  EXPLICIT availability, null is not "available", and no secret ever
  reaches an offer, snapshot or error;
* the ZCode Coding-Plan reset-card read path is a distinct, hardened HTTPS
  route that reports "unavailable" truthfully instead of claiming zero;
* one shared manual-offer expiry formatter ("expires in ...", never
  "resets in ...").
"""

from __future__ import annotations

import os
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

import pytest  # noqa: E402

from fastprompter.core.usage_limits.model import (  # noqa: E402
    OK,
    STALE,
    AccountRef,
    ResetOffer,
    UsageSnapshot,
    UsageWindow,
    format_offer_expiry,
    manual_reset_count,
    reset_offer_rows,
)
from fastprompter.core.usage_limits.providers import _zcode_http  # noqa: E402
from fastprompter.core.usage_limits.providers import codex as codex_mod  # noqa: E402
from fastprompter.core.usage_limits.providers import zcode as zcode_mod  # noqa: E402
from fastprompter.core.usage_limits.providers.claude import (  # noqa: E402
    _campaign_offers,
)

pytest.importorskip("PyQt6.QtWidgets")

from test_usage_limits_gauge_layout import (  # noqa: E402
    _account,
    _build,
)
from test_usage_limits_gauge_layout import (
    qapp as qapp,  # noqa: F401
)

NOW = 1_800_000_000.0


def _offer(provider="codex", target="weekly", title="", expires=None,
           status="available", offer_id="o1", account_key="",
           redeemable_in_fastprompter=True, **extra):
    fields = dict(
        offer_id=offer_id, provider_id=provider,
        account_key=account_key or f"{provider}:a1",
        target_kind=target, status=status, title=title,
        granted_at_epoch=None, expires_at_epoch=expires,
        redeemable=True, redeemable_in_fastprompter=redeemable_in_fastprompter,
        source="test")
    fields.update(extra)
    return ResetOffer(**fields)


def _snap(provider, account, offers=(), *, status=OK, five=0.0, weekly=0.0,
          banked=None, windows=None, now=NOW):
    if windows is None:
        windows = [
            UsageWindow("five_hour", 300, True, 100 - five, five, now + 3600),
            UsageWindow("weekly", 10080, True, 100 - weekly, weekly,
                        now + 4 * 86400)]
    return UsageSnapshot(
        account=account, status=status, windows=windows,
        fetched_at=now, banked_resets=banked,
        reset_offers=tuple(offers))


# ---------------------------------------------------------------------------
# 1. model: currency of an offer
# ---------------------------------------------------------------------------

def test_offer_current_excludes_expired_and_consumed():
    live = _offer(expires=NOW + 7200)
    expired = _offer(offer_id="o2", expires=NOW - 60)
    consumed = _offer(offer_id="o3", status="consumed", expires=NOW + 7200)
    pending = _offer(offer_id="o4", status="unknown", expires=None)
    snap = _snap("codex", _account("codex", "a1"),
                 [live, expired, consumed, pending])
    from fastprompter.core.usage_limits.model import current_reset_offers
    got = [o.offer_id for o in current_reset_offers(snap, now=NOW)]
    assert got == ["o1"]


def test_offers_ignored_for_invalid_snapshot():
    from fastprompter.core.usage_limits.model import current_reset_offers
    snap = _snap("codex", _account("codex", "a1"), [_offer()],
                 status="AUTH_REQUIRED")
    assert current_reset_offers(snap, now=NOW) == []
    stale = _snap("codex", _account("codex", "a1"), [_offer()], status=STALE)
    assert current_reset_offers(stale, now=NOW)  # last-known still shown


def test_reset_rows_ignore_ordinary_filters_and_manual_hidden_is_excluded():
    codex = _account("codex", "c1")
    claude = _account("claude", "cl1")
    snaps = {
        codex.key: _snap("codex", codex, [_offer(provider="codex")]),
        claude.key: _snap("claude", claude, [_offer(
            provider="claude", target="weekly",
            title="Weekly reset", redeemable_in_fastprompter=False)]),
    }
    rows = reset_offer_rows(snaps, hidden_keys=frozenset(), now=NOW)
    assert [r.account.provider_id for r in rows] == ["codex", "claude"]
    # manually hidden account is excluded from presentation
    rows_hidden = reset_offer_rows(
        snaps, hidden_keys=frozenset({claude.key}), now=NOW)
    assert [r.account.provider_id for r in rows_hidden] == ["codex"]
    assert manual_reset_count(snaps, now=NOW) == 2


# ---------------------------------------------------------------------------
# 2. shared expiry formatter
# ---------------------------------------------------------------------------

def test_format_offer_expiry_words():
    assert format_offer_expiry(NOW + 11 * 60, now=NOW) == "expires in 11m"
    assert format_offer_expiry(NOW + 4 * 3600 + 44 * 60, now=NOW) == \
        "expires in 4h 44m"
    future_day = NOW + 2 * 86400
    assert format_offer_expiry(future_day, now=NOW).startswith("expires ")
    assert "resets" not in format_offer_expiry(future_day, now=NOW)
    assert format_offer_expiry(NOW - 5, now=NOW) == "expired"
    assert format_offer_expiry(None, now=NOW) == ""


# ---------------------------------------------------------------------------
# 3. Codex adapter: rateLimitResetCredits -> ResetOffer
# ---------------------------------------------------------------------------

def _codex_result(count=None, credits=None):
    result = {
        "ok": True, "plan_type": "plus", "fetched_at": NOW,
        "five_hour": {"available": True, "remaining_percent": 0.0,
                      "used_percent": 100.0, "resets_at": None,
                      "window_duration_mins": 300, "group": "",
                      "group_label": "", "model_slug": ""},
        "weekly": {"available": True, "remaining_percent": 0.0,
                   "used_percent": 100.0, "resets_at": None,
                   "window_duration_mins": 10080, "group": "",
                   "group_label": "", "model_slug": ""},
    }
    if count is not None:
        result["banked_resets"] = count
    if credits is not None:
        result["reset_credits"] = credits
    return result


class _FixedProbe:
    def __init__(self, result):
        self._result = result

    def probe_codex_home(self, home, deadline=None):
        return self._result


def _probe_offers(monkeypatch, result):
    provider = codex_mod.CodexProvider()
    monkeypatch.setattr(
        "fastprompter.core.usage_limits.providers._codex_probe.probe_codex_home",
        _FixedProbe(result).probe_codex_home)
    account = AccountRef(provider_id="codex", stable_id="s1",
                         display_name="Codex", source_kind="test",
                         source_path="C:/x")
    return provider.probe(account, deadline=time.monotonic() + 5)


def test_codex_count_only_becomes_one_honest_aggregate_offer(monkeypatch):
    snap = _probe_offers(monkeypatch, _codex_result(count=1))
    assert snap.banked_resets == 1
    assert len(snap.reset_offers) == 1
    offer = snap.reset_offers[0]
    assert offer.provider_id == "codex"
    assert offer.redeemable_in_fastprompter is True
    assert offer.offer_id == ""              # no fabricated vendor id
    assert "1" in offer.title and "reset" in offer.title


def test_codex_individual_credit_fields_preserved(monkeypatch):
    credits = [{
        "id": "credit-7", "status": "available", "title": "Full reset",
        "description": "Resets all limits",
        "reset_type": "FULL",
        "granted_at": NOW - 3600, "expires_at": NOW + 2 * 86400,
    }]
    snap = _probe_offers(monkeypatch, _codex_result(count=1, credits=credits))
    assert len(snap.reset_offers) == 1
    offer = snap.reset_offers[0]
    assert offer.offer_id == "credit-7"
    assert offer.title == "Full reset"
    assert offer.expires_at_epoch == NOW + 2 * 86400
    assert offer.granted_at_epoch == NOW - 3600
    assert offer.redeemable_in_fastprompter is True


def test_codex_multiple_expired_and_consumed_credits(monkeypatch):
    credits = [
        {"id": "a", "status": "available", "reset_type": "FULL"},
        {"id": "b", "status": "available", "reset_type": "WEEK"},
        {"id": "c", "status": "expired", "reset_type": "FULL",
         "expires_at": NOW - 10},
        {"id": "d", "status": "consumed", "reset_type": "FULL"},
    ]
    snap = _probe_offers(monkeypatch, _codex_result(count=2, credits=credits))
    statuses = {o.offer_id: o.status for o in snap.reset_offers}
    assert statuses == {"a": "available", "b": "available",
                        "c": "expired", "d": "consumed"}
    from fastprompter.core.usage_limits.model import current_reset_offers
    assert len(current_reset_offers(snap, now=NOW)) == 2


def test_codex_malformed_credit_entries_never_crash(monkeypatch):
    credits = [42, None, {"id": "", "status": ""}, {"id": "ok",
                                                    "status": "available"}]
    snap = _probe_offers(monkeypatch, _codex_result(count=1, credits=credits))
    assert [o.offer_id for o in snap.reset_offers if o.status == "available"] \
        == ["ok"]


def test_codex_no_credits_key_means_no_offers(monkeypatch):
    snap = _probe_offers(monkeypatch, _codex_result())
    assert snap.reset_offers == ()
    assert snap.banked_resets is None


# ---------------------------------------------------------------------------
# 4. THE Codex visibility bug (RED first) + topbar presentation
# ---------------------------------------------------------------------------

def test_exhausted_filtered_codex_keeps_reset_in_topbar(qapp, monkeypatch):
    """Handoff case: five_hour=0, weekly=0, reset credit available=1,
    hide_zero=True, hide_unusable=True. The usage account may vanish from
    the bars, but the reset must stay visible."""
    codex = _account("codex", "c1")
    snap = _snap("codex", codex, [_offer(
        provider="codex", title="1 reset available",
        expires=time.time() + 19 * 3600)],
        five=0.0, weekly=0.0, banked=1)
    gauges = _build(qapp, [codex], {codex.key: snap},
                    limit_gauges_hide_zero_usage="True",
                    limit_gauges_hide_unusable_5h="True")
    try:
        html_text = gauges._build_tooltip()
        assert gauges._visible_accounts() == []   # account filtered, by design
        assert "Resets" in html_text              # distinct section exists
        assert "1 reset available" in html_text   # the offer itself
        import re
        assert re.search(r"expires in 1[89]h", html_text)
        # aggregate badge is painted in the header
        assert gauges._reset_badge_text() == "★ 1"
    finally:
        gauges.main_win.close()


def test_resets_section_not_duplicated_under_shift(qapp):
    codex = _account("codex", "c1")
    snap = _snap("codex", codex, [_offer(title="1 reset available")], banked=1)
    gauges = _build(qapp, [codex], {codex.key: snap})
    try:
        for shift in (False, True):
            html_text = gauges._build_tooltip(ignore_filters=shift)
            assert html_text.count("Resets") == 1, shift
    finally:
        gauges.main_win.close()


def test_context_menu_includes_filtered_reset_account(qapp):
    codex = _account("codex", "c1")
    snap = _snap("codex", codex, [_offer(title="1 reset available")], banked=1)
    gauges = _build(qapp, [codex], {codex.key: snap},
                    limit_gauges_hide_zero_usage="True",
                    limit_gauges_hide_unusable_5h="True")
    try:
        actions = gauges._reset_menu_actions()
        assert len(actions) == 1
        assert actions[0].account is codex
        assert actions[0].activate is True
    finally:
        gauges.main_win.close()


# ---------------------------------------------------------------------------
# 5. REQUIRED cross-provider oracle
# ---------------------------------------------------------------------------

def test_cross_provider_oracle(qapp):
    codex = _account("codex", "cx")
    claude = _account("claude", "cl")
    zcode = _account("zcode", "zc")
    snaps = {
        codex.key: _snap("codex", codex, [_offer(
            provider="codex", title="Full reset",
            expires=NOW + 2 * 86400)], five=0, weekly=0, banked=1),
        claude.key: _snap("claude", claude, [_offer(
            provider="claude", target="weekly", title="Weekly reset",
            expires=NOW + 19 * 3600, redeemable_in_fastprompter=False)],
            five=0, weekly=0),
        zcode.key: _snap("zcode", zcode, [_offer(
            provider="zcode", target="five_hour", title="5h reset",
            expires=NOW + 4 * 3600 + 44 * 60, redeemable_in_fastprompter=False)],
            five=0, weekly=0),
    }
    gauges = _build(qapp, [codex, claude, zcode], snaps,
                    limit_gauges_hide_zero_usage="True",
                    limit_gauges_hide_unusable_5h="True")
    try:
        # quota accounts may be filtered away entirely
        assert gauges._visible_accounts() == []
        html_text = gauges._build_tooltip()
        # ... but the reset section shows all three
        for fragment in ("Resets", "Full reset", "Weekly reset", "5h reset"):
            assert fragment in html_text, fragment
        assert manual_reset_count(snaps, now=NOW) == 3
        assert gauges._reset_badge_text() == "★ 3"
        # no provider becomes usable merely by owning a reset
        from fastprompter.core.usage_limits.model import account_usable_now
        for snap in snaps.values():
            assert account_usable_now(snap, now=NOW) is False
        # the automatic reset queue is UNCHANGED by reset offers
        from fastprompter.core.usage_limits.model import reset_candidates
        without = dict(snaps)
        for key, snap in list(without.items()):
            without[key] = UsageSnapshot(
                account=snap.account, status=snap.status,
                windows=list(snap.windows), fetched_at=snap.fetched_at)
        assert (reset_candidates(snaps) == reset_candidates(without))
    finally:
        gauges.main_win.close()


# ---------------------------------------------------------------------------
# 6. Claude: defensive campaign parsing (no vendor schema invented)
# ---------------------------------------------------------------------------

def test_claude_no_offer_metadata_yields_nothing():
    assert _campaign_offers({"rate_limits": {"five_hour": {"used_percentage": 10}}}) == ()
    assert _campaign_offers({}) == ()
    assert _campaign_offers({"campaigns": None}) == ()      # null is not data
    assert _campaign_offers({"campaigns": []}) == ()


def test_claude_null_availability_is_not_an_offer():
    payload = {"campaigns": [{"title": "Weekly reset", "available": None}]}
    assert _campaign_offers(payload) == ()
    payload2 = {"campaigns": [{"title": "Weekly reset"}]}
    assert _campaign_offers(payload2) == ()


def test_claude_session_and_weekly_offers_parsed():
    payload = {"campaigns": [
        {"title": "Session reset", "available": True,
         "target": "session", "expires_at": NOW + 3600},
        {"title": "Weekly reset", "status": "available",
         "reset_type": "WEEK", "expires_at": NOW + 19 * 3600},
    ]}
    offers = _campaign_offers(payload, now=NOW)
    assert [o.target_kind for o in offers] == ["five_hour", "weekly"]
    assert all(o.redeemable_in_fastprompter is False for o in offers)
    assert offers[0].expires_at_epoch == NOW + 3600


def test_claude_expired_offer_carried_but_not_current():
    payload = {"campaigns": [{"title": "Weekly reset", "available": True,
                              "reset_type": "WEEK",
                              "expires_at": NOW - 60}]}
    offers = _campaign_offers(payload, now=NOW)
    assert len(offers) == 1
    from fastprompter.core.usage_limits.model import current_reset_offers
    assert current_reset_offers(
        _snap("claude", _account("claude", "a"), offers), now=NOW) == []


def test_claude_malformed_campaign_entries_dropped():
    payload = {"campaigns": ["junk", 3, None,
                             {"available": True, "reset_type": "WEEK"}]}
    offers = _campaign_offers(payload, now=NOW)
    assert len(offers) == 1
    assert offers[0].target_kind == "weekly"


SECRET = "sk-ant-secret-token-DO-NOT-LEAK"


def test_claude_offers_and_errors_never_carry_secrets():
    payload = {"campaigns": [{"title": "Weekly reset", "available": True,
                              "reset_type": "WEEK", "api_key": SECRET,
                              "access_token": SECRET}]}
    for offer in _campaign_offers(payload, now=NOW):
        blob = repr(offer)
        assert SECRET not in blob
        assert "api_key" not in blob and "token" not in blob.lower()


# ---------------------------------------------------------------------------
# 7. ZCode Coding Plan reset cards (hardened read path)
# ---------------------------------------------------------------------------

def _zcode_entry(tmp_path, base="https://api.z.ai/api/anthropic"):
    return {"id": "builtin:zai-coding-plan", "name": "Z.ai - Coding Plan",
            "base_url": base, "has_key": True, "api_key": "K" * 20}


def _creds_file(tmp_path, jwt="J" * 20, maas="M" * 20):
    import json
    path = tmp_path / "credentials.json"
    path.write_text(json.dumps({
        "zcodejwttoken": jwt,
        "oauth:zai:access_token": maas}), encoding="utf-8")
    return str(path)


class _ReaderSpy:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def __call__(self, entry, deadline, creds_path=""):
        self.calls.append((entry, creds_path))
        return self.response


def _zcode_snapshot(monkeypatch, tmp_path, reader, enabled=True):
    provider = zcode_mod.ZCodeProvider(
        enabled=enabled,
        config_path=str(tmp_path / "config.json"),
        reader=lambda entry, deadline: {
            "windows": [{
                "key": "five_hour", "remaining": 0.0, "resets_at": NOW + 3600,
                "duration_minutes": 300, "total": 100.0, "spent": 100.0}],
            "level": "lite", "captured_at": NOW,
            "source": "zcode-monitor-quota"},
        reset_reader=reader)
    monkeypatch.setattr(
        zcode_mod._zcode_http, "read_plan_entries",
        lambda path: [_zcode_entry(tmp_path)])
    account = AccountRef(provider_id="zcode", stable_id="s1",
                         display_name="ZCode", source_kind="test",
                         source_path=str(tmp_path),
                         metadata={"plan_id": "builtin:zai-coding-plan",
                                   "plan_name": "Z.ai - Coding Plan"})
    return provider.probe(account, deadline=time.monotonic() + 5)


def test_zcode_5h_and_weekly_cards(monkeypatch, tmp_path):
    spy = _ReaderSpy({"cards": [
        {"kind": "five_hour", "expire_at": NOW + 4 * 3600 + 44 * 60},
        {"kind": "weekly", "expire_at": None},
    ]})
    snap = _zcode_snapshot(monkeypatch, tmp_path, spy)
    assert snap.status == OK
    offers = snap.reset_offers
    assert [o.target_kind for o in offers] == ["five_hour", "weekly"]
    assert all(o.redeemable_in_fastprompter is False for o in offers)
    assert offers[0].source == "zcode-coding-plan-reset"
    assert snap.provider_metadata["reset_cards"]["state"] == "ok"
    # the automatic window survives beside the cards
    assert snap.window("five_hour").remaining_percent == 0.0


def test_zcode_expired_card_not_current(monkeypatch, tmp_path):
    spy = _ReaderSpy({"cards": [{"kind": "weekly",
                                 "expire_at": time.time() - 60}]})
    snap = _zcode_snapshot(monkeypatch, tmp_path, spy)
    from fastprompter.core.usage_limits.model import current_reset_offers
    assert current_reset_offers(snap, now=NOW) == []
    assert snap.reset_offers[0].status == "expired"


def test_zcode_history_is_not_availability(monkeypatch, tmp_path):
    # consumed history present, zero available arrays -> NO offers, and the
    # metadata must not pretend the inventory said "zero" — it did say zero
    # here, but the distinction is state=="ok" with empty cards.
    spy = _ReaderSpy({"cards": [],
                      "history": {"latest_week_reset_history": {"used_at": NOW - 900}}})
    snap = _zcode_snapshot(monkeypatch, tmp_path, spy)
    assert snap.reset_offers == ()
    assert snap.provider_metadata["reset_cards"]["state"] == "ok"


def test_zcode_auth_unavailable_is_not_zero(monkeypatch, tmp_path):
    spy = _ReaderSpy({"error": ("reset_auth_unavailable",
                                "signed-in Coding Plan session required "
                                "(no ZCode account credentials on disk)")})
    snap = _zcode_snapshot(monkeypatch, tmp_path, spy)
    assert snap.reset_offers == ()
    meta = snap.provider_metadata["reset_cards"]
    assert meta["state"] == "unavailable"
    assert "no credentials" in meta["summary"] or "credentials" in meta["summary"]


def test_zcode_disabled_provider_never_reads_resets(monkeypatch, tmp_path):
    spy = _ReaderSpy({"cards": [{"kind": "weekly", "expire_at": NOW + 99}]})
    provider = zcode_mod.ZCodeProvider(enabled=False, reset_reader=spy)
    monkeypatch.setattr(
        zcode_mod._zcode_http, "read_plan_entries",
        lambda path: [_zcode_entry(tmp_path)])
    assert provider.discover_accounts() == []
    assert spy.calls == []


# -- _zcode_http.reset_cards_url + read_reset_cards hardening ---------------

def test_reset_url_is_fixed_vendor_host():
    url = _zcode_http.reset_cards_url()
    assert url == "https://zcode.z.ai/api/v1/coding-plan/reset/status"
    # env override must not move it
    os.environ["ZCODE_BASE_URL"] = "https://evil.example"
    try:
        assert _zcode_http.reset_cards_url() == url
    finally:
        del os.environ["ZCODE_BASE_URL"]


def test_read_reset_cards_requires_credentials(tmp_path):
    empty = tmp_path / "none.json"
    result = _zcode_http.read_reset_cards(
        _zcode_entry(tmp_path), time.monotonic() + 5, creds_path=str(empty))
    assert "error" in result
    code, summary = result["error"]
    assert code == "reset_auth_unavailable"
    assert "credential" in summary.lower()


def test_read_reset_cards_never_leaks_credentials(tmp_path, monkeypatch):
    creds = _creds_file(tmp_path)
    import urllib.error

    def _boom(request, timeout):
        raise urllib.error.HTTPError(
            request.full_url, 401, "Unauthorized", {}, None)

    monkeypatch.setattr(_zcode_http, "_reset_request", _boom)
    result = _zcode_http.read_reset_cards(
        _zcode_entry(tmp_path), time.monotonic() + 5, creds_path=creds)
    code, summary = result["error"]
    assert code == "reset_auth_failed"
    for secret in ("J" * 20, "M" * 20, "K" * 20):
        assert secret not in summary


def test_read_reset_cards_oversized_body_refused(tmp_path, monkeypatch):
    creds = _creds_file(tmp_path)

    class _Big:
        def read(self, n=-1):
            return b"x" * (512 * 1024 + 1)

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(_zcode_http, "_reset_request", lambda r, t: _Big())
    result = _zcode_http.read_reset_cards(
        _zcode_entry(tmp_path), time.monotonic() + 5, creds_path=creds)
    assert result["error"][0] == "reset_bad_response"


def test_read_reset_cards_vendor_not_found_is_unavailable(tmp_path, monkeypatch):
    import json as _json

    class _Envelope:
        def read(self, n=-1):
            return _json.dumps(
                {"code": 500, "msg": "404 NOT_FOUND",
                 "success": False}).encode()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(_zcode_http, "_reset_request",
                        lambda r, t: _Envelope())
    creds = _creds_file(tmp_path)
    result = _zcode_http.read_reset_cards(
        _zcode_entry(tmp_path), time.monotonic() + 5, creds_path=creds)
    assert result["error"][0] == "reset_route_unavailable"


def test_read_reset_cards_parses_proven_schema(tmp_path, monkeypatch):
    import json as _json

    payload = {"code": 0, "data": {
        "available_five_hour_resets": [{"expire_at": (NOW + 3600) * 1000}],
        "available_week_resets": [],
        "latest_five_hour_reset_history": None,
        "latest_week_reset_history": {"used_at": (NOW - 800) * 1000},
        "has_unread_history": True}}

    class _Envelope:
        def read(self, n=-1):
            return _json.dumps(payload).encode()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(_zcode_http, "_reset_request",
                        lambda r, t: _Envelope())
    creds = _creds_file(tmp_path)
    result = _zcode_http.read_reset_cards(
        _zcode_entry(tmp_path), time.monotonic() + 5, creds_path=creds)
    assert result["cards"] == [{"kind": "five_hour", "expire_at": NOW + 3600}]
    assert result["history"]["latest_week_reset_history"]["used_at"] == \
        NOW - 800


def test_read_reset_cards_malformed_envelope(tmp_path, monkeypatch):
    class _Envelope:
        def read(self, n=-1):
            return b"<html>not json</html>"

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(_zcode_http, "_reset_request",
                        lambda r, t: _Envelope())
    creds = _creds_file(tmp_path)
    result = _zcode_http.read_reset_cards(
        _zcode_entry(tmp_path), time.monotonic() + 5, creds_path=creds)
    assert result["error"][0] == "reset_bad_response"
