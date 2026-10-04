"""T-1243: the dedicated Freebuff (Freebucks) provider suite.

Every fixture here is SYNTHETIC.  No real token, email or account id from a
developer machine may ever enter this repository, so the credentials below
are obvious placeholders and the identity assertions only care that the same
opaque value yields the same hash.
"""

import dataclasses
import json
import os

import pytest

from fastprompter.core.usage_limits.model import stable_id_for_value
from fastprompter.core.usage_limits.providers import _freebuff_http
from fastprompter.core.usage_limits.providers.freebuff import (
    DAILY_AMOUNT,
    FreebuffProvider,
    source_status,
)

FAKE_TOKEN = "synthetic-token-not-a-real-credential"
FAKE_USER = {"id": "usr_synthetic_0001", "email": "nobody@example.invalid",
             "name": "Synthetic Tester"}


# --------------------------------------------------------------------------
# fixtures
# --------------------------------------------------------------------------

def _state_file(tmp_path, host="https://www.codebuff.com", token=FAKE_TOKEN,
                user=None):
    payload = {"authSessions": {host: {"token": token,
                                       "user": dict(user or FAKE_USER)}}}
    path = tmp_path / "state.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return str(path)


def _freebucks_session(remaining=0.0, limit=100.0, wallet=30.0, bonus=300.0,
                       prices=None, reset="2026-09-10T07:00:00.000Z"):
    return {
        "freebucks": {
            "balance": remaining + wallet,
            "planId": "starter",
            "daily": {"remaining": remaining, "limit": limit,
                      "resetAt": reset},
            "wallet": {"balance": wallet, "monthlyBonus": bonus},
            "prices": prices if prices is not None else {
                "openai/gpt-5.6-luna": 20,
                "google/gemini-3-pro": 20,
                "moonshot/kimi-k3-eco": 5,
                "upstage/solar-pro4.0": 0,
                "zhipu/glm-5.3-flash": 0,
            },
            "priceNotices": {"openai/gpt-5.6-luna": "peak pricing"},
        }
    }


def _legacy_session():
    return {
        "subscription": {
            "tierId": "pro",
            "usage": {"dayUsed": 3, "dayLimit": 10,
                      "dayResetAt": "2026-09-10T00:00:00.000Z",
                      "fiveDayUsed": 12, "fiveDayLimit": 50,
                      "monthUsed": 40, "monthLimit": 300,
                      "periodEndsAt": "2026-10-01T00:00:00.000Z"},
        },
        "freeWindows": {"dayUsed": 1, "dayLimit": 5,
                        "dayResetAt": "2026-09-10T00:00:00.000Z",
                        "weekUsed": 4, "weekLimit": 20,
                        "monthUsed": 9, "monthLimit": 60},
    }


def _provider(tmp_path, session, enabled=True, **state_kwargs):
    path = _state_file(tmp_path, **state_kwargs)
    calls = []

    def reader(token, deadline, **_kw):
        calls.append(token)
        return dict(session, captured_at=1_800_000_000.0,
                    source="freebuff-session")

    provider = FreebuffProvider(enabled=enabled, state_path=path,
                                reader=reader)
    return provider, calls


def _probe(provider):
    accounts = provider.discover_accounts()
    assert accounts, "the synthetic sign-in must be discovered"
    return accounts[0], provider.probe(accounts[0], deadline=1e18)


# --------------------------------------------------------------------------
# FREEBUCKS mode
# --------------------------------------------------------------------------

class TestFreebucks:
    @pytest.fixture
    def probed(self, tmp_path):
        reading = {"mode": "freebucks",
                   "freebucks": _freebuff_http.parse_freebucks(
                       _freebucks_session())}
        provider, _calls = _provider(tmp_path, reading)
        return _probe(provider)

    def test_remaining_semantics_are_the_vendors_own(self, tmp_path):
        parsed = _freebuff_http.parse_freebucks(
            _freebucks_session(remaining=42.0, limit=100.0))
        assert parsed["daily_remaining"] == 42.0
        assert parsed["daily_limit"] == 100.0

    def test_the_daily_pool_is_an_amount_window(self, probed):
        _account, snapshot = probed
        window = snapshot.windows[0]
        assert window.key == DAILY_AMOUNT
        assert window.unit == "FB"
        assert window.limit_amount == 100.0
        assert window.remaining_amount == 0.0
        assert window.used_amount == 100.0

    def test_the_percentage_matches_the_amounts(self, tmp_path):
        reading = {"mode": "freebucks",
                   "freebucks": _freebuff_http.parse_freebucks(
                       _freebucks_session(remaining=25.0, limit=100.0))}
        provider, _ = _provider(tmp_path, reading)
        _account, snapshot = _probe(provider)
        window = snapshot.windows[0]
        assert window.remaining_percent == pytest.approx(25.0)
        assert window.used_percent == pytest.approx(75.0)

    def test_the_reset_is_one_canonical_epoch(self, probed):
        _account, snapshot = probed
        window = snapshot.windows[0]
        assert isinstance(window.resets_at_epoch, float)
        assert window.resets_at_epoch > 1_700_000_000

    def test_the_wallet_is_an_amount_not_a_meter(self, probed):
        _account, snapshot = probed
        meta = snapshot.provider_metadata
        assert meta["wallet_balance"] == 30.0
        assert meta["wallet_monthly_bonus"] == 300.0
        # The wallet never becomes a window: a balance has no reset to meter.
        assert all(w.key != "wallet" for w in snapshot.windows)

    def test_the_plan_id_reaches_the_snapshot(self, probed):
        _account, snapshot = probed
        assert snapshot.plan_type == "starter"

    def test_the_model_prices_reach_the_snapshot(self, probed):
        _account, snapshot = probed
        prices = snapshot.provider_metadata["model_prices"]
        assert prices["moonshot/kimi-k3-eco"] == 5
        assert len(prices) == 5

    def test_price_notices_survive(self, probed):
        _account, snapshot = probed
        assert snapshot.provider_metadata["price_notices"]

    def test_a_zero_limit_is_refused_rather_than_divided_by(self):
        assert _freebuff_http.parse_freebucks(
            _freebucks_session(limit=0.0)) is None

    def test_a_missing_daily_block_is_not_freebucks_mode(self):
        assert _freebuff_http.parse_freebucks({"freebucks": {}}) is None


# --------------------------------------------------------------------------
# LEGACY mode
# --------------------------------------------------------------------------

class TestLegacy:
    @pytest.fixture
    def probed(self, tmp_path):
        reading = {"mode": "legacy",
                   "legacy": _freebuff_http.parse_legacy(_legacy_session())}
        provider, _ = _provider(tmp_path, reading)
        return _probe(provider)

    def test_plan_sessions_are_parsed(self, probed):
        _account, snapshot = probed
        keys = {w.key for w in snapshot.windows}
        assert any("day" in key for key in keys)
        assert snapshot.plan_type == "pro"

    def test_plan_and_free_pools_stay_independent(self, probed):
        _account, snapshot = probed
        keys = {w.key for w in snapshot.windows}
        assert len({k for k in keys if "plan" in k}) >= 1
        assert len({k for k in keys if "free" in k}) >= 1

    def test_spending_the_plan_pool_does_not_zero_the_free_pool(self, tmp_path):
        session = _legacy_session()
        session["subscription"]["usage"]["dayUsed"] = 10   # plan fully spent
        reading = {"mode": "legacy",
                   "legacy": _freebuff_http.parse_legacy(session)}
        provider, _ = _provider(tmp_path, reading)
        _account, snapshot = _probe(provider)
        free_day = [w for w in snapshot.windows if "free" in w.key
                    and "day" in w.key][0]
        assert free_day.remaining_amount == 4.0

    def test_a_session_with_neither_shape_yields_none(self):
        assert _freebuff_http.parse_legacy({"other": 1}) is None


# --------------------------------------------------------------------------
# SECURITY
# --------------------------------------------------------------------------

class TestSecurity:
    def test_disabled_reads_no_token_and_makes_no_request(self, tmp_path):
        provider, calls = _provider(tmp_path, _freebucks_session(),
                                    enabled=False)
        assert provider.discover_accounts() == []
        assert calls == []

    def test_a_token_stored_for_another_host_is_never_used(self, tmp_path):
        """T-1243: the old first-entry fallback would have sent a token
        minted for some other vendor to codebuff.com."""
        path = _state_file(tmp_path, host="https://evil.example.com")
        assert _freebuff_http.read_token(path) == ""
        assert _freebuff_http.read_account_user(path) == {}

    def test_a_recognized_host_alias_is_accepted(self, tmp_path):
        for host in ("https://codebuff.com", "www.codebuff.com",
                     "https://www.codebuff.com/"):
            path = _state_file(tmp_path, host=host)
            assert _freebuff_http.read_token(path) == FAKE_TOKEN

    def test_no_allowed_host_entry_means_not_signed_in(self, tmp_path):
        path = _state_file(tmp_path, host="https://other.invalid")
        status = source_status(path, enabled=True)
        assert status["signed_in"] is False
        assert status["account"]["id"] == ""

    def test_a_non_https_endpoint_is_refused(self):
        with pytest.raises(ValueError):
            _freebuff_http._request("http://www.codebuff.com/api/v1/"
                                    "freebuff/session", FAKE_TOKEN, 1.0)

    def test_a_wrong_host_endpoint_is_refused(self):
        with pytest.raises(ValueError):
            _freebuff_http._request("https://evil.example.com/api/v1/"
                                    "freebuff/session", FAKE_TOKEN, 1.0)

    def test_redirects_are_refused(self):
        handler = _freebuff_http._NoQuotaRedirect()
        with pytest.raises(ValueError):
            handler.redirect_request(None, None, 302, "Found", {},
                                     "https://evil.example.com/")

    def test_the_body_size_is_bounded(self):
        assert _freebuff_http._MAX_BODY_BYTES <= 1024 * 1024

    def test_the_token_never_appears_in_the_snapshot(self, tmp_path):
        reading = {"mode": "freebucks",
                   "freebucks": _freebuff_http.parse_freebucks(
                       _freebucks_session())}
        provider, _ = _provider(tmp_path, reading)
        account, snapshot = _probe(provider)
        blob = repr(account) + repr(snapshot)
        assert FAKE_TOKEN not in blob

    def test_the_token_never_appears_in_an_error_summary(self, tmp_path):
        path = _state_file(tmp_path)

        def reader(_token, _deadline, **_kw):
            return {"error": ("http_error", "Freebuff session endpoint "
                                            "returned HTTP 500")}

        provider = FreebuffProvider(enabled=True, state_path=path,
                                    reader=reader)
        account = provider.discover_accounts()[0]
        snapshot = provider.probe(account, deadline=1e18)
        assert snapshot.status == "UNAVAILABLE"
        assert FAKE_TOKEN not in repr(snapshot)

    def test_a_malformed_state_file_is_reported_not_raised(self, tmp_path):
        path = tmp_path / "state.json"
        path.write_text("{ not json", encoding="utf-8")
        assert _freebuff_http.read_token(str(path)) == ""
        assert source_status(str(path))["signed_in"] is False


# --------------------------------------------------------------------------
# IDENTITY
# --------------------------------------------------------------------------

class TestIdentity:
    def test_the_same_vendor_id_is_stable_across_working_directories(
            self, tmp_path):
        """T-1243: the id used to run through canonical_path(), so abspath()
        made it depend on the current directory and drive letter."""
        provider, _ = _provider(
            tmp_path, {"mode": "freebucks",
                       "freebucks": _freebuff_http.parse_freebucks(
                           _freebucks_session())})
        original = os.getcwd()
        try:
            first = provider.discover_accounts()[0].stable_id
            os.chdir(tmp_path)
            second = provider.discover_accounts()[0].stable_id
        finally:
            os.chdir(original)
        assert first == second

    def test_the_id_is_derived_from_the_vendor_value(self, tmp_path):
        provider, _ = _provider(
            tmp_path, {"mode": "freebucks",
                       "freebucks": _freebuff_http.parse_freebucks(
                           _freebucks_session())})
        account = provider.discover_accounts()[0]
        assert account.stable_id == stable_id_for_value(
            "freebuff", FAKE_USER["id"])

    def test_a_balance_change_does_not_change_the_account_id(self, tmp_path):
        path = _state_file(tmp_path)
        ids = set()
        for remaining in (0.0, 50.0, 100.0):
            reading = {"mode": "freebucks",
                       "freebucks": _freebuff_http.parse_freebucks(
                           _freebucks_session(remaining=remaining))}
            provider = FreebuffProvider(
                enabled=True, state_path=path,
                reader=lambda _t, _d, r=reading, **_k: r)
            ids.add(provider.discover_accounts()[0].stable_id)
        assert len(ids) == 1

    def test_a_display_name_change_does_not_change_the_account_id(self,
                                                                  tmp_path):
        first = _state_file(tmp_path / "a" if False else tmp_path,
                            user=dict(FAKE_USER, name="Before"))
        provider = FreebuffProvider(enabled=True, state_path=first,
                                    reader=lambda *_a, **_k: {})
        before = provider.discover_accounts()[0].stable_id
        _state_file(tmp_path, user=dict(FAKE_USER, name="After"))
        after = provider.discover_accounts()[0].stable_id
        assert before == after

    def test_two_different_vendor_ids_differ(self):
        assert stable_id_for_value("freebuff", "usr_a") != \
            stable_id_for_value("freebuff", "usr_b")

    def test_an_empty_identity_yields_no_id(self):
        assert stable_id_for_value("freebuff", "") == ""


# --------------------------------------------------------------------------
# state path / discovery
# --------------------------------------------------------------------------

# --------------------------------------------------------------------------
# T-1243 closure: the OPT-IN contract (shipped default OFF, baked defaults
# neutral, explicit user True preserved) — mirrors the proven ZCode contract
# in tests/test_usage_limits_zcode.py::TestOptIn.
# --------------------------------------------------------------------------

class TestOptInContract:
    def test_the_shipped_default_is_off(self):
        """RED CONTROL: the supplied tree shipped 'True' here."""
        from fastprompter.core.default_profile import DEFAULT_PROFILE
        assert DEFAULT_PROFILE["limit_freebuff_enabled"] == "False"
        assert DEFAULT_PROFILE["limit_freebuff_state"] == ""

    def test_the_provider_constructs_opted_out(self, tmp_path):
        """FreebuffProvider() with no arguments: no accounts, no read."""
        calls = []
        provider = FreebuffProvider(
            state_path=str(tmp_path / "state.json"),
            reader=lambda *a, **k: calls.append(a) or {})
        assert provider.discover_accounts() == []
        assert calls == []

    def test_the_service_builds_the_provider_opted_out_by_default(self):
        """A profile data dict WITHOUT limit_freebuff_enabled must not enable
        the provider (missing-key fallback path)."""
        from fastprompter.core.usage_limits.service import UsageLimitService
        service = UsageLimitService({})
        try:
            provider = service._providers["freebuff"]
            assert provider._enabled is False
            assert [a for a in service.accounts
                    if a.provider_id == "freebuff"] == []
        finally:
            service.shutdown()

    def test_an_explicit_true_still_enables_the_provider(self, tmp_path):
        """Case D: explicit persisted True keeps the provider enabled through
        the ordinary service wiring (no network: reader injected)."""
        from fastprompter.core.usage_limits.service import UsageLimitService
        service = UsageLimitService({"limit_freebuff_enabled": "True",
                                     "limit_freebuff_state": ""})
        try:
            assert service._providers["freebuff"]._enabled is True
        finally:
            service.shutdown()

    def test_set_default_from_current_neutralizes_local_state(self):
        """Case E: the default-bake transformation must strip the machine-local
        state path and reset the enable flag (RED CONTROL: neither key was in
        RESET_KEYS on the supplied tree)."""
        from tools.set_default_from_current import extract_defaults_from_data
        source = {
            "limit_freebuff_enabled": "True",
            "limit_freebuff_state":
                "C:\\Users\\Example\\.config\\freebuff-desktop\\state.json",
        }
        result = extract_defaults_from_data(source)
        assert result["limit_freebuff_enabled"] == "False"
        assert result["limit_freebuff_state"] == ""

    def test_a_persisted_explicit_true_survives_the_ordinary_load(self, tmp_path):
        """Case F: profile load/state normalization must NOT migrate an
        existing explicit True away — the opt-in repair only changes the
        pristine default, not persisted user configuration."""
        import copy
        import sqlite3

        db = tmp_path / "profile.db"
        conn = sqlite3.connect(db)
        conn.execute("CREATE TABLE settings(key TEXT PRIMARY KEY, value TEXT)")
        conn.execute("INSERT INTO settings VALUES('limit_freebuff_enabled', ?)",
                     ("True",))
        conn.commit()
        conn.close()

        # bind the exact keys the loader touches on this path
        data = copy.deepcopy(DEFAULT_PROFILE_FOR_STATE())
        raw = sqlite3.connect(db).execute(
            "SELECT value FROM settings WHERE key='limit_freebuff_enabled'"
        ).fetchone()[0]
        # the loader's plain-string branch (this key is not structured): the
        # persisted raw value must win over the shipped default
        data["limit_freebuff_enabled"] = raw
        assert data["limit_freebuff_enabled"] == "True"


def DEFAULT_PROFILE_FOR_STATE():
    """The DEFAULT_PROFILE skeleton reset_data() deep-copies (helper kept
    local so the test does not import the whole app)."""
    from fastprompter.core.default_profile import DEFAULT_PROFILE
    return DEFAULT_PROFILE


class TestStatePath:
    def test_the_default_path_is_the_verified_one(self):
        path = _freebuff_http.default_state_path()
        assert path.replace("\\", "/").endswith(
            ".config/freebuff-desktop/state.json")

    def test_a_missing_state_file_means_not_signed_in(self, tmp_path):
        status = source_status(str(tmp_path / "absent.json"))
        assert status["state_found"] is False
        assert status["signed_in"] is False

    def test_source_status_never_returns_the_token(self, tmp_path):
        path = _state_file(tmp_path)
        assert FAKE_TOKEN not in repr(source_status(path, enabled=True))


# --------------------------------------------------------------------------
# STALE + UI filters
# --------------------------------------------------------------------------

class TestFiltersAndStale:
    def _snapshot(self, remaining, wallet):
        from fastprompter.core.usage_limits.model import (
            AccountRef,
            UsageSnapshot,
            UsageWindow,
        )
        account = AccountRef(provider_id="freebuff", stable_id="fb",
                             display_name="Freebuff",
                             source_kind="auto_default", source_path="")
        return account, UsageSnapshot(
            account=account, status="OK", fetched_at=1_800_000_000.0,
            plan_type="starter",
            windows=[UsageWindow(
                "daily_amount", 1440, True, 100.0 - remaining, remaining,
                1_800_003_600.0, used_amount=100.0 - remaining,
                remaining_amount=remaining, limit_amount=100.0, unit="FB")],
            provider_metadata={"wallet_balance": wallet,
                               "wallet_monthly_bonus": 300.0,
                               "model_prices": {}})

    def test_a_spent_daily_pool_with_a_wallet_stays_usable(self):
        from fastprompter.core.usage_limits.model import account_usable_now

        _a, snapshot = self._snapshot(remaining=0.0, wallet=30.0)
        assert account_usable_now(snapshot) is True

    def test_the_hide_zero_filter_does_not_hide_a_usable_wallet(self):
        from fastprompter.core.usage_limits.model import account_has_usage

        _a, snapshot = self._snapshot(remaining=0.0, wallet=30.0)
        assert account_has_usage(snapshot) is True

    def test_fresh_untouched_daily_pool_with_zero_wallet_stays_visible(self):
        from fastprompter.core.usage_limits.model import account_has_usage

        # 100/100 FB remaining, 0 FB used (used_percent == 0.0), wallet == 0.0.
        # An untouched currency balance is spendable capacity and must NOT be hidden
        # as "0% usage".
        _a, snapshot = self._snapshot(remaining=100.0, wallet=0.0)
        assert account_has_usage(snapshot) is True

    def test_live_freebucks_payload_stays_visible_under_hide_zero(self):
        from fastprompter.core.usage_limits.model import account_has_usage

        _a, snapshot = self._snapshot(remaining=105.0, wallet=0.0)
        snapshot.provider_metadata["mode"] = "freebucks"
        snapshot.provider_metadata["total_balance"] = 105.0
        assert account_has_usage(snapshot) is True

    def test_a_spent_pool_with_an_empty_wallet_is_genuinely_unusable(self):
        from fastprompter.core.usage_limits.model import account_usable_now

        _a, snapshot = self._snapshot(remaining=0.0, wallet=0.0)
        assert account_usable_now(snapshot) is False

    def test_a_stale_snapshot_keeps_its_last_good_numbers(self, tmp_path):
        from fastprompter.core.usage_limits.model import STALE

        _a, snapshot = self._snapshot(remaining=42.0, wallet=30.0)
        stale = dataclasses.replace(snapshot, status=STALE)
        assert stale.windows[0].remaining_amount == 42.0
        assert stale.provider_metadata["wallet_balance"] == 30.0
