"""ZCode provider tests — the only usage source that leaves the machine.

ZCode ships no ``/usage`` command and keeps its cached quota in a LevelDB the
running app holds open, so the sole readable source is the monitor endpoint its
own client calls. That makes these tests unusual in two ways:

* **no test ever performs a request.** The provider takes a ``reader`` seam and
  every test here supplies one, so the suite can never assert on this machine's
  live quota — or spend a credential proving a parser works;
* **the security posture is under test, not just the mapping.** Opted-out
  discovery, the host allow-list, and the absence of the API key from every
  outward-facing surface are asserted the same way the percentages are.

The payloads below are verbatim shapes captured from ZCode 3.4.0: a Coding Plan
credit meter (``CREDIT_LIMIT``, ``unit`` 3/5 and 6) and the older Start Plan
token buckets (``ent_2_*``), whose ``percentage`` field carries the OPPOSITE
meaning — which is exactly why neither is trusted.
"""

from __future__ import annotations

import json
import time

from fastprompter.core.usage_limits.model import (
    FIVE_HOUR,
    OK,
    UNAVAILABLE,
    WEEKLY,
    UsageWindow,
    provider_reset_color,
    resolved_windows,
)
from fastprompter.core.usage_limits.providers import _zcode_http
from fastprompter.core.usage_limits.providers.zcode import (
    ZCodeProvider,
    source_status,
)

# Live shape, 04.09.2026: 5h pool 2000 credits with 252 spent, weekly 10000.
_LIVE_LIMITS = [
    {"type": "CREDIT_LIMIT", "unit": 3, "number": 5, "usage": 2000,
     "currentValue": 252, "remaining": 1747, "percentage": 12,
     "nextResetTime": 1788498595214, "usageDetails": []},
    {"type": "CREDIT_LIMIT", "unit": 6, "number": 1, "usage": 10000,
     "currentValue": 252, "remaining": 9747, "percentage": 2,
     "nextResetTime": 1789085298997, "usageDetails": []},
]


def _config(tmp_path, entries=None, name="config.json"):
    """A ZCode config.json holding the plan entries under test."""
    if entries is None:
        entries = {
            "builtin:zai-coding-plan": {
                "name": "Z.ai - Coding Plan",
                "options": {"apiKey": "secret-key-do-not-leak",
                            "baseURL": "https://api.z.ai/api/anthropic"},
                "enabled": True,
            },
        }
    path = tmp_path / name
    path.write_text(json.dumps({"provider": entries}), encoding="utf-8")
    return str(path)


def _reader(payload):
    """A reader seam that answers with one fixed payload and records calls."""
    calls = []

    def read(entry, deadline, now=None):
        calls.append(dict(entry))
        return payload

    read.calls = calls
    return read


def _ok_reading(windows=None, level="lite"):
    return {
        "windows": windows if windows is not None
        else _zcode_http.parse_limits({"limits": _LIVE_LIMITS}),
        "level": level,
        "captured_at": time.time(),
        "source": "zcode-monitor-quota",
    }


def _drain(service, timeout=5.0):
    """Let a shut-down service's sweep threads retire.

    ``shutdown()`` is non-blocking by contract, so a coordinator thread that was
    already past its closed-check can still reach the retired executor and raise
    into pytest's thread-exception hook. Waiting here keeps that a test-harness
    concern instead of a fake product defect.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with service._lock:
            if service._sweep_threads_count == 0:
                return
        time.sleep(0.01)


class TestWindowMapping:
    def test_unit_selects_the_window_it_is_not_a_size(self):
        """unit=3/number=5 is the 5h pool; unit=6 is weekly. Not 3 credits."""
        rows = _zcode_http.parse_limits({"limits": _LIVE_LIMITS})
        assert [row["key"] for row in rows] == [FIVE_HOUR, WEEKLY]
        assert rows[0]["duration_minutes"] == 300
        assert rows[1]["duration_minutes"] == 10080

    def test_remaining_is_derived_from_the_meter_not_the_percentage_field(self):
        """percentage=12 means 12% USED; the gauge needs 87.4% remaining."""
        five_hour, weekly = _zcode_http.parse_limits({"limits": _LIVE_LIMITS})
        assert abs(five_hour["remaining"] - 1747 / 1999 * 100) < 0.01
        assert five_hour["remaining"] > 80          # not 12
        assert abs(weekly["remaining"] - 9747 / 9999 * 100) < 0.01

    def test_the_start_plan_shape_is_read_the_same_way(self):
        """``ent_2_*`` percentage is a REMAINING fraction — also ignored."""
        rows = _zcode_http.parse_limits({"limits": [
            {"type": "TOKENS_LIMIT", "unit": 3, "number": 5,
             "usage": 3000000, "currentValue": 2967863, "remaining": 32137,
             "percentage": 0.0107, "nextResetTime": 1787500799000},
        ]})
        assert len(rows) == 1
        assert rows[0]["key"] == FIVE_HOUR
        assert abs(rows[0]["remaining"] - 32137 / 3000000 * 100) < 0.01

    def test_reset_milliseconds_become_epoch_seconds(self):
        rows = _zcode_http.parse_limits({"limits": _LIVE_LIMITS})
        assert abs(rows[0]["resets_at"] - 1788498595.214) < 0.01

    def test_the_monthly_tool_bucket_is_its_own_window(self):
        rows = _zcode_http.parse_limits({"limits": [
            {"type": "TIME_LIMIT", "unit": 5, "number": 1, "usage": 1000,
             "currentValue": 40, "remaining": 960,
             "nextResetTime": 1788537600000},
        ]})
        assert [row["key"] for row in rows] == ["monthly"]

    def test_an_unknown_bucket_is_dropped_not_guessed(self):
        rows = _zcode_http.parse_limits({"limits": [
            {"type": "MYSTERY_LIMIT", "unit": 9, "number": 9,
             "currentValue": 1, "remaining": 1},
            {"type": "CREDIT_LIMIT", "unit": 99, "currentValue": 1,
             "remaining": 1},
        ]})
        assert rows == []

    def test_a_bucket_that_cannot_state_both_halves_is_dropped(self):
        """Without currentValue+remaining no truthful percentage exists."""
        rows = _zcode_http.parse_limits({"limits": [
            {"type": "CREDIT_LIMIT", "unit": 3, "number": 5, "usage": 2000,
             "percentage": 12},
            {"type": "CREDIT_LIMIT", "unit": 6, "currentValue": 0,
             "remaining": 0},
        ]})
        assert rows == []

    def test_garbage_payloads_are_silent(self):
        assert _zcode_http.parse_limits(None) == []
        assert _zcode_http.parse_limits({"limits": "nope"}) == []
        assert _zcode_http.parse_limits({"limits": [None, 7, "x"]}) == []


class TestEndpointAllowList:
    def test_a_vendor_host_resolves_to_the_monitor_path(self):
        assert (_zcode_http.quota_url("https://api.z.ai/api/anthropic")
                == "https://api.z.ai/api/monitor/usage/quota/limit")
        assert (_zcode_http.quota_url("https://open.bigmodel.cn/api/anthropic")
                == "https://open.bigmodel.cn/api/monitor/usage/quota/limit")

    def test_a_missing_base_url_falls_back_to_the_vendor_default(self):
        assert _zcode_http.quota_url("") == \
            "https://api.z.ai/api/monitor/usage/quota/limit"

    def test_a_foreign_host_is_refused(self):
        """A rewritten config must not redirect the credential."""
        for base in ("https://evil.example/api/anthropic",
                     "http://api.z.ai.attacker.test/x",
                     "https://api-z.ai/api", "ftp://api.z.ai/x",
                     "https://api.z.ai@evil.example/x", "not a url at all"):
            assert _zcode_http.quota_url(base) == "", base

    def test_the_probe_refuses_a_foreign_host_before_requesting(self):
        """No socket is opened at all when the host is not the vendor's."""
        opened = []
        original = _zcode_http._request

        def spy(url, api_key, timeout):
            opened.append(url)
            return original(url, api_key, timeout)

        _zcode_http._request = spy
        try:
            reading = _zcode_http.read_quota(
                {"base_url": "https://evil.example", "api_key": "k"},
                deadline=time.monotonic() + 5)
        finally:
            _zcode_http._request = original
        assert reading["error"][0] == "endpoint_not_allowed"
        assert opened == []

    def test_no_env_var_can_move_the_endpoint(self, monkeypatch):
        """ZCode honours an env override; a credential holder must not."""
        monkeypatch.setenv("ZCODE_BIGMODEL_USAGE_QUOTA_URL",
                           "https://evil.example/quota")
        monkeypatch.setenv("BIGMODEL_USAGE_QUOTA_URL",
                           "https://evil.example/quota")
        assert "evil" not in _zcode_http.quota_url(
            "https://api.z.ai/api/anthropic")


class TestTheRequestItself:
    """``read_quota`` with the socket layer stubbed — never a real call."""

    def _read(self, response, base_url="https://api.z.ai/api/anthropic",
              api_key="secret-key-do-not-leak"):
        seen = {}
        original = _zcode_http._request

        def stub(url, key, timeout):
            seen.update(url=url, key=key, timeout=timeout)
            if isinstance(response, Exception):
                raise response
            return response

        _zcode_http._request = stub
        try:
            reading = _zcode_http.read_quota(
                {"base_url": base_url, "api_key": api_key},
                deadline=time.monotonic() + 5, now=1788000000.0)
        finally:
            _zcode_http._request = original
        return reading, seen

    def test_a_success_envelope_becomes_windows(self):
        reading, seen = self._read(
            {"code": 200, "data": {"level": "lite", "limits": _LIVE_LIMITS}})
        assert seen["url"] == "https://api.z.ai/api/monitor/usage/quota/limit"
        assert seen["key"] == "secret-key-do-not-leak"
        assert reading["level"] == "lite"
        assert [row["key"] for row in reading["windows"]] == [FIVE_HOUR, WEEKLY]
        assert reading["captured_at"] == 1788000000.0

    def test_a_missing_key_is_refused_before_requesting(self):
        reading, seen = self._read({"code": 200}, api_key="")
        assert reading["error"][0] == "no_api_key"
        assert seen == {}

    def test_an_expired_deadline_is_refused_before_requesting(self):
        seen = {}
        original = _zcode_http._request
        _zcode_http._request = lambda *a, **k: seen.setdefault("hit", True)
        try:
            reading = _zcode_http.read_quota(
                {"base_url": "https://api.z.ai", "api_key": "k"},
                deadline=time.monotonic() - 1)
        finally:
            _zcode_http._request = original
        assert reading["error"][0] == "deadline_exceeded"
        assert seen == {}

    def test_http_401_is_an_auth_failure_and_carries_no_key(self):
        import urllib.error
        reading, _ = self._read(urllib.error.HTTPError(
            "https://api.z.ai/x", 401, "Unauthorized", {}, None))
        assert reading["error"][0] == "auth_failed"
        assert "secret-key" not in reading["error"][1]

    def test_http_500_is_a_transport_error_not_an_auth_one(self):
        import urllib.error
        reading, _ = self._read(urllib.error.HTTPError(
            "https://api.z.ai/x", 500, "Server Error", {}, None))
        assert reading["error"][0] == "http_error"

    def test_an_unreachable_host_is_reported_by_type_only(self):
        import urllib.error
        reading, _ = self._read(urllib.error.URLError(OSError("no route")))
        assert reading["error"][0] == "network_error"
        assert "no route" not in reading["error"][1]

    def test_a_vendor_refusal_keeps_the_vendor_message(self):
        reading, _ = self._read({"code": 1210, "msg": "quota service busy"})
        assert reading["error"][0] == "vendor_error"
        assert "quota service busy" in reading["error"][1]

    def test_the_vendors_no_plan_message_is_classified(self):
        reading, _ = self._read(
            {"code": 1211, "msg": "\u4e0d\u5b58\u5728coding plan"})
        assert reading["error"][0] == "no_plan"

    def test_an_empty_limit_list_is_no_limits(self):
        reading, _ = self._read({"code": 200, "data": {"limits": []}})
        assert reading["error"][0] == "no_limits"

    def test_a_non_object_body_is_a_bad_response(self):
        reading, _ = self._read(["not", "an", "object"])
        assert reading["error"][0] == "bad_response"


class TestConfigReading:
    def test_a_plan_with_a_key_is_offered(self, tmp_path):
        entries = _zcode_http.read_plan_entries(_config(tmp_path))
        assert [e["id"] for e in entries] == ["builtin:zai-coding-plan"]
        assert entries[0]["has_key"] is True

    def test_an_entry_zcode_itself_disabled_is_skipped(self, tmp_path):
        path = _config(tmp_path, {
            "builtin:zai-coding-plan": {
                "options": {"apiKey": "k", "baseURL": "https://api.z.ai"},
                "enabled": True,
                "systemDisabledReason": "coding_plan_not_entitled",
            },
            "builtin:zai-start-plan": {
                "options": {"apiKey": "k", "baseURL": "https://api.z.ai"},
                "enabled": False,
            },
        })
        assert _zcode_http.read_plan_entries(path) == []

    def test_a_keyless_entry_is_skipped(self, tmp_path):
        path = _config(tmp_path, {
            "builtin:zai-coding-plan": {
                "options": {"apiKey": "", "baseURL": "https://api.z.ai"},
                "enabled": True,
            },
        })
        assert _zcode_http.read_plan_entries(path) == []

    def test_a_plain_api_key_provider_is_not_a_plan(self, tmp_path):
        """``builtin:zai`` has no plan, so it could only answer no_plan."""
        path = _config(tmp_path, {
            "builtin:zai": {
                "options": {"apiKey": "k", "baseURL": "https://api.z.ai"},
                "enabled": True,
            },
        })
        assert _zcode_http.read_plan_entries(path) == []

    def test_a_missing_or_broken_config_is_silent(self, tmp_path):
        assert _zcode_http.read_plan_entries(str(tmp_path / "nope.json")) == []
        broken = tmp_path / "broken.json"
        broken.write_text("{not json", encoding="utf-8")
        assert _zcode_http.read_plan_entries(str(broken)) == []


class TestOptIn:
    def test_disabled_discovers_nothing(self, tmp_path):
        """Off means no account, no row, and therefore no request."""
        provider = ZCodeProvider(enabled=False, config_path=_config(tmp_path))
        assert provider.discover_accounts() == []

    def test_the_shipped_default_is_off(self):
        from fastprompter.core.default_profile import DEFAULT_PROFILE
        assert DEFAULT_PROFILE["limit_zcode_enabled"] == "False"

    def test_the_service_builds_the_provider_opted_out_by_default(self):
        from fastprompter.core.usage_limits.service import UsageLimitService
        service = UsageLimitService({})
        try:
            provider = service._providers["zcode"]
            assert provider._enabled is False
            assert [a for a in service.accounts
                    if a.provider_id == "zcode"] == []
        finally:
            service.shutdown()
            _drain(service)

    def test_a_disabled_probe_never_calls_the_reader(self, tmp_path):
        reader = _reader(_ok_reading())
        enabled = ZCodeProvider(enabled=True, config_path=_config(tmp_path),
                                reader=reader)
        account = enabled.discover_accounts()[0]
        disabled = ZCodeProvider(enabled=False, config_path=_config(tmp_path),
                                 reader=reader)
        shot = disabled.probe(account, time.monotonic() + 5)
        assert shot.status == UNAVAILABLE
        assert shot.error_code == "disabled"
        assert reader.calls == []


class TestProbe:
    def _provider(self, tmp_path, payload):
        reader = _reader(payload)
        provider = ZCodeProvider(enabled=True, config_path=_config(tmp_path),
                                 reader=reader)
        return provider, reader

    def test_two_windows_land_in_one_pool(self, tmp_path):
        """Both bars count the same credit meter, so gating must cross them."""
        provider, _ = self._provider(tmp_path, _ok_reading())
        account = provider.discover_accounts()[0]
        shot = provider.probe(account, time.monotonic() + 5)
        assert shot.status == OK
        assert [w.key for w in shot.windows] == [FIVE_HOUR, WEEKLY]
        assert all(w.group == "" for w in shot.windows)
        assert shot.plan_type == "lite"

    def test_a_spent_weekly_gates_the_five_hour_window(self, tmp_path):
        now = time.time()
        provider, _ = self._provider(tmp_path, _ok_reading(windows=[
            {"key": FIVE_HOUR, "remaining": 90.0, "resets_at": now + 3600,
             "duration_minutes": 300, "total": 2000, "spent": 200},
            {"key": WEEKLY, "remaining": 0.0, "resets_at": now + 4 * 86400,
             "duration_minutes": 10080, "total": 10000, "spent": 10000},
        ]))
        account = provider.discover_accounts()[0]
        shot = provider.probe(account, time.monotonic() + 5)
        windows = {w.key: w for w in resolved_windows(shot.windows, now)}
        assert windows[FIVE_HOUR].gated_by == WEEKLY
        assert windows[FIVE_HOUR].remaining_percent == 0.0

    def test_used_and_remaining_always_agree(self, tmp_path):
        provider, _ = self._provider(tmp_path, _ok_reading())
        account = provider.discover_accounts()[0]
        for window in provider.probe(account, time.monotonic() + 5).windows:
            assert abs(window.used_percent + window.remaining_percent
                       - 100.0) < 0.01

    def test_no_plan_is_quiet_not_an_error(self, tmp_path):
        """ZCode itself renders "no active Coding Plan"; nothing to fix."""
        from fastprompter.core.usage_limits.model import EXPECTED_QUIET_CODES
        provider, _ = self._provider(
            tmp_path, {"error": ("no_plan", "no active Coding Plan")})
        account = provider.discover_accounts()[0]
        shot = provider.probe(account, time.monotonic() + 5)
        assert shot.status == UNAVAILABLE
        assert shot.error_code == "no_plan"
        # not in the quiet set: a plan the user pays for and cannot read IS
        # worth the header marker, unlike Antigravity's resting state.
        assert "no_plan" not in EXPECTED_QUIET_CODES

    def test_a_network_failure_never_invents_a_number(self, tmp_path):
        provider, _ = self._provider(
            tmp_path, {"error": ("network_error", "could not reach")})
        account = provider.discover_accounts()[0]
        shot = provider.probe(account, time.monotonic() + 5)
        assert shot.status == UNAVAILABLE
        assert all(not w.available for w in shot.windows)

    def test_an_expired_deadline_is_refused_before_the_reader(self, tmp_path):
        provider, reader = self._provider(tmp_path, _ok_reading())
        account = provider.discover_accounts()[0]
        shot = provider.probe(account, time.monotonic() - 1)
        assert shot.error_code == "deadline_exceeded"
        assert reader.calls == []

    def test_a_plan_removed_from_the_config_stops_being_probed(self, tmp_path):
        provider, reader = self._provider(tmp_path, _ok_reading())
        account = provider.discover_accounts()[0]
        _config(tmp_path, {})          # user logged out of the plan
        shot = provider.probe(account, time.monotonic() + 5)
        assert shot.error_code == "plan_not_configured"
        assert reader.calls == []


class TestIdentity:
    def test_two_plans_are_two_accounts(self, tmp_path):
        path = _config(tmp_path, {
            "builtin:zai-coding-plan": {
                "name": "Z.ai - Coding Plan",
                "options": {"apiKey": "a", "baseURL": "https://api.z.ai"},
                "enabled": True,
            },
            "builtin:bigmodel-coding-plan": {
                "name": "BigModel - Coding Plan",
                "options": {"apiKey": "b",
                            "baseURL": "https://open.bigmodel.cn/api"},
                "enabled": True,
            },
        })
        accounts = ZCodeProvider(enabled=True,
                                 config_path=path).discover_accounts()
        assert len({a.stable_id for a in accounts}) == 2
        assert {a.display_name for a in accounts} == {"ZCode",
                                                     "ZCode BigModel"}

    def test_identity_survives_a_re_read(self, tmp_path):
        path = _config(tmp_path)
        first = ZCodeProvider(enabled=True, config_path=path).discover_accounts()
        second = ZCodeProvider(enabled=True, config_path=path).discover_accounts()
        assert [a.key for a in first] == [a.key for a in second]

    def test_the_header_badge_and_reset_colour_exist(self, tmp_path):
        from fastprompter.ui.limit_account_selector import default_account_label
        account = ZCodeProvider(
            enabled=True, config_path=_config(tmp_path)).discover_accounts()[0]
        assert default_account_label(account) == "ZC"
        assert provider_reset_color("zcode")

    def test_the_colour_role_matches_the_model_default(self):
        from fastprompter.ui.limit_colors import ROLES_BY_KEY
        assert (ROLES_BY_KEY["reset_zcode"].default
                == provider_reset_color("zcode"))


class TestTheKeyNeverLeaves:
    _SECRET = "secret-key-do-not-leak"

    def test_the_account_carries_no_key(self, tmp_path):
        account = ZCodeProvider(
            enabled=True, config_path=_config(tmp_path)).discover_accounts()[0]
        assert self._SECRET not in repr(account)
        assert self._SECRET not in json.dumps(account.metadata)

    def test_the_snapshot_carries_no_key(self, tmp_path):
        reader = _reader(_ok_reading())
        provider = ZCodeProvider(enabled=True, config_path=_config(tmp_path),
                                 reader=reader)
        account = provider.discover_accounts()[0]
        shot = provider.probe(account, time.monotonic() + 5)
        assert self._SECRET not in repr(shot)
        # ...but the probe really did receive it, so this is not a false pass
        assert reader.calls[0]["api_key"] == self._SECRET

    def test_an_error_summary_carries_no_key(self, tmp_path):
        provider = ZCodeProvider(
            enabled=True, config_path=_config(tmp_path),
            reader=_reader({"error": ("auth_failed",
                                      "endpoint returned HTTP 401")}))
        account = provider.discover_accounts()[0]
        shot = provider.probe(account, time.monotonic() + 5)
        assert self._SECRET not in shot.error_summary
        assert self._SECRET not in repr(shot)

    def test_the_settings_status_reports_presence_not_the_key(self, tmp_path):
        state = source_status(_config(tmp_path))
        assert state["config_found"] is True
        assert state["plans"][0]["has_key"] is True
        assert self._SECRET not in json.dumps(state)

    def test_the_settings_status_flags_a_refused_endpoint(self, tmp_path):
        path = _config(tmp_path, {
            "builtin:zai-coding-plan": {
                "options": {"apiKey": "k", "baseURL": "https://evil.example"},
                "enabled": True,
            },
        })
        state = source_status(path)
        assert state["plans"][0]["endpoint"] == ""

    def test_a_missing_config_is_reported_not_raised(self, tmp_path):
        state = source_status(str(tmp_path / "nope.json"))
        assert state["config_found"] is False
        assert state["plans"] == []


class TestServiceIntegration:
    def test_enabling_it_registers_accounts_through_the_service(self, tmp_path):
        from fastprompter.core.usage_limits.providers import zcode as zcode_mod
        from fastprompter.core.usage_limits.service import UsageLimitService

        data = {"limit_zcode_enabled": "True",
                "limit_zcode_config": _config(tmp_path)}
        service = UsageLimitService(data)
        try:
            accounts = [a for a in service.accounts
                        if a.provider_id == "zcode"]
            assert len(accounts) == 1
            assert accounts[0].display_name == "ZCode"
            assert isinstance(service._providers["zcode"],
                              zcode_mod.ZCodeProvider)
            assert service._providers["zcode"]._enabled is True
        finally:
            service.shutdown()
            _drain(service)

    def test_turning_it_off_drops_the_account_again(self, tmp_path):
        from fastprompter.core.usage_limits.service import UsageLimitService

        data = {"limit_zcode_enabled": "True",
                "limit_zcode_config": _config(tmp_path)}
        service = UsageLimitService(data)
        try:
            assert any(a.provider_id == "zcode" for a in service.accounts)
            data["limit_zcode_enabled"] = "False"
            service.reconfigure(data)
            assert not any(a.provider_id == "zcode" for a in service.accounts)
        finally:
            service.shutdown()
            _drain(service)

    def test_the_window_labels_render(self, tmp_path):
        from fastprompter.ui.limit_gauges import _win_label
        assert _win_label(UsageWindow(FIVE_HOUR, 300, True, 10, 90)) == "5h"
        assert _win_label(UsageWindow(WEEKLY, 10080, True, 10, 90)) == "weekly"
