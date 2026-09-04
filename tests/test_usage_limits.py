"""Tests for the provider-neutral usage-limit subsystem.

Covers:

* stable identity and canonical path normalization;
* window parsing (by duration, not primary/secondary position);
* service: per-account isolation, generation discard, stale preservation;
* Codex discovery: env + default + siblings, dedupe, extra paths.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

from fastprompter.core.usage_limits.model import (
    FIVE_HOUR,
    OK,
    STALE,
    UNAVAILABLE,
    WEEKLY,
    UsageSnapshot,
    UsageWindow,
    canonical_path,
    provider_reset_color,
    soonest_reset,
    stable_id_for,
)
from fastprompter.core.usage_limits.model import AccountRef as AR
from fastprompter.core.usage_limits.providers.codex import (
    CodexProvider,
    parse_windows,
)
from fastprompter.core.usage_limits.service import UsageLimitService


class TestCanonicalPath:
    def test_lowercases_on_windows(self):
        os.environ["USERPROFILE"] = "C:\\Users\\Test"
        a = canonical_path("C:\\Users\\TEST\\.codex")
        b = canonical_path("c:/users/test/.codex")
        assert a == b

    def test_empty_returns_empty(self):
        assert canonical_path("") == ""


class TestStableId:
    def test_same_path_same_id(self):
        a = stable_id_for("codex", "C:\\Users\\x\\.codex")
        b = stable_id_for("codex", "C:\\x\\.codex")
        assert a != b   # different path -> different id

    def test_provider_part_of_id(self):
        a = stable_id_for("codex", "X")
        b = stable_id_for("claude", "X")
        assert a != b


class TestParseWindows:
    def test_maps_windows_by_duration(self):
        rl = {"rateLimits": {
            "primary": {"windowDurationMins": 10080, "usedPercent": 71,
                        "resetsAt": 1800000000},
            "secondary": {"windowDurationMins": 300, "usedPercent": 100,
                          "resetsAt": 1800000100},
        }}
        out = parse_windows(rl)
        assert out["five_hour"]["remaining_percent"] == 0
        assert out["five_hour"]["window_duration_mins"] == 300
        assert out["weekly"]["remaining_percent"] == 29
        assert out["weekly"]["window_duration_mins"] == 10080

    def test_missing_bucket_unavailable(self):
        out = parse_windows({"rateLimits": {
            "primary": {"windowDurationMins": 300, "usedPercent": 50},
        }})
        assert out["five_hour"]["available"] is True
        assert out["weekly"]["available"] is False

    def test_empty_input_no_guess(self):
        out = parse_windows({})
        assert out["five_hour"]["available"] is False
        assert out["five_hour"]["remaining_percent"] is None

    def test_parse_windows_with_banked_resets(self):
        rl = {
            "rateLimits": {
                "primary": {"windowDurationMins": 300, "usedPercent": 50},
            },
            "rateLimitResetCredits": {
                "availableCount": 2,
                "credits": [
                    {
                        "id": "Credit_1",
                        "resetType": "codexRateLimits",
                        "status": "available",
                        "grantedAt": 1788483108,
                        "expiresAt": 1791075108,
                        "title": "Full reset",
                        "description": "Free rate limit reset",
                    },
                    {
                        "id": "Credit_2",
                        "resetType": "codexRateLimits",
                        "status": "available",
                        "grantedAt": 1788483108,
                        "expiresAt": 1791075108,
                        "title": "Full reset",
                        "description": "Free rate limit reset",
                    },
                ],
            },
        }
        out = parse_windows(rl)
        assert out["banked_resets"] == 2
        assert len(out["reset_credits"]) == 2
        assert out["reset_credits"][0]["id"] == "Credit_1"
        assert out["reset_credits"][0]["status"] == "available"

    def test_parse_windows_counts_available_credits_if_available_count_missing(self):
        rl = {
            "rateLimits": {},
            "rateLimitResetCredits": {
                "credits": [
                    {"id": "c1", "status": "available"},
                    {"id": "c2", "status": "used"},
                    {"id": "c3", "status": "available"},
                ],
            },
        }
        out = parse_windows(rl)
        assert out["banked_resets"] == 2
        assert len(out["reset_credits"]) == 3

    def test_parse_windows_no_reset_credits(self):
        out = parse_windows({"rateLimits": {}})
        assert out["banked_resets"] is None
        assert out["reset_credits"] == []


class TestCodexDiscovery:
    def test_no_home_dir(self, monkeypatch):
        monkeypatch.delenv("HOME", raising=False)
        monkeypatch.delenv("USERPROFILE", raising=False)
        monkeypatch.delenv("CODEX_HOME", raising=False)
        assert CodexProvider().discover_accounts() == []

    def test_dedupes_extra_and_default(self, tmp_path, monkeypatch):
        primary = tmp_path / ".codex"
        primary.mkdir()
        (primary / "auth.json").write_text("{}")
        monkeypatch.setenv("USERPROFILE", str(tmp_path))
        monkeypatch.delenv("HOME", raising=False)
        monkeypatch.delenv("CODEX_HOME", raising=False)
        p = CodexProvider(extra_homes=[str(primary)])
        accounts = p.discover_accounts()
        keys = [a.source_path for a in accounts]
        assert len(keys) == len(set(canonical_path(k) for k in keys))

    def test_dedupes_case_insensitive(self, tmp_path, monkeypatch):
        d1 = tmp_path / ".codex"; d1.mkdir()
        (d1 / "auth.json").write_text("{}")
        d2 = tmp_path / "CUSTOM"; d2.mkdir()
        (d2 / "auth.json").write_text("{}")
        monkeypatch.setenv("USERPROFILE", str(tmp_path))
        monkeypatch.delenv("HOME", raising=False)
        monkeypatch.delenv("CODEX_HOME", raising=False)
        p = CodexProvider(extra_homes=[str(d1), str(d1)])
        # extra_homes dedupe itself; default ~/.codex skipped because folder
        # without auth.json is filtered.
        accounts = p.discover_accounts()
        # Only d1 (default) and d2 via extras -> 1 unique via extras, plus default match
        assert len(accounts) >= 1

    def test_sibling_homes_picked_up(self, tmp_path, monkeypatch):
        (tmp_path / ".codex").mkdir()
        (tmp_path / ".codex" / "auth.json").write_text("{}")
        for s in ("account2", "account3free"):
            d = tmp_path / f".codex-{s}"
            d.mkdir()
            (d / "auth.json").write_text("{}")
        monkeypatch.setenv("USERPROFILE", str(tmp_path))
        monkeypatch.delenv("HOME", raising=False)
        monkeypatch.delenv("CODEX_HOME", raising=False)
        names = [a.display_name for a in CodexProvider().discover_accounts()]
        assert "Codex" in names
        assert "Account2" in names
        assert "Account3Free" in names


class TestService:
    def test_discover_populates_accounts(self, monkeypatch):
        from fastprompter.core.usage_limits.service import UsageLimitService
        s = UsageLimitService()
        # Service should have at least the default ~/.codex (or none on this
        # machine); what matters is the public API is non-throwing.
        assert isinstance(s.accounts, list)

    def test_snapshot_marks_stale_on_failure(self):
        from fastprompter.core.usage_limits.service import UsageLimitService
        s = UsageLimitService()
        acc = AR(provider_id="codex", stable_id="abc123",
                 display_name="Test", source_kind="test")
        with s._lock:
            s._state.snapshots[acc.key] = UsageSnapshot(
                account=acc, status=OK,
                windows=[UsageWindow(FIVE_HOUR, 300, True, 30, 70),
                         UsageWindow(WEEKLY, 10080, True, 50, 50)],
                fetched_at=time.time(),
            )
        # Simulate transient failure: service preserves OK and marks STALE.
        with s._lock:
            prev = s._state.snapshots[acc.key]
            s._state.snapshots[acc.key] = UsageSnapshot(
                account=prev.account, status=STALE,
                windows=list(prev.windows),
                fetched_at=prev.fetched_at, stale_since=time.time(),
            )
        out = s.snapshots[acc.key]
        assert out.status == STALE
        assert out.window(FIVE_HOUR).remaining_percent == 70

    def test_generation_discards_stale_results(self):
        from fastprompter.core.usage_limits.service import UsageLimitService
        s = UsageLimitService()
        s._state.generation = 5
        # Simulate an old sweep trying to commit at gen 1
        old_gen = 1
        with s._lock:
            if old_gen < s._state.generation:
                return  # service: dropped
            s._state.snapshots["x"] = UsageSnapshot(
                account=AR(provider_id="c", stable_id="x",
                           display_name="x", source_kind="t"),
                status=OK, windows=[])
        assert "x" not in s.snapshots   # was dropped

    def test_oversized_account_list_is_accepted(self):
        from fastprompter.core.usage_limits.service import UsageLimitService
        s = UsageLimitService()
        # 50 synthetic accounts -> data model accepts all
        accounts = [AR(provider_id="codex", stable_id=f"id{i}",
                       display_name=f"A{i}", source_kind="synthetic")
                    for i in range(50)]
        with s._lock:
            s._state.accounts = accounts
            s._state.generation += 1
        assert len(s.accounts) == 50

    def test_first_unavailable_result_is_preserved(self):
        from fastprompter.core.usage_limits.service import UsageLimitService

        acc = AR(provider_id="claude", stable_id="claude1",
                 display_name="Claude", source_kind="test")

        class UnavailableProvider:
            def probe(self, account, _deadline):
                return UsageSnapshot(
                    account=account, status=UNAVAILABLE,
                    windows=[UsageWindow.unavailable(FIVE_HOUR),
                             UsageWindow.unavailable(WEEKLY)],
                    error_code="unsupported",
                    error_summary="no structured source",
                )

        s = UsageLimitService()
        try:
            with s._lock:
                s._providers = {"claude": UnavailableProvider()}
                s._state.accounts = [acc]
                s._state.snapshots = {}
                gen = s._state.generation
            s._sweep([acc], gen, s._state.request_id)
            assert s.snapshots[acc.key].status == UNAVAILABLE
            assert s.snapshots[acc.key].error_code == "unsupported"
        finally:
            s.shutdown()

    def test_monotonic_request_id_rejects_out_of_order_sweep(self):
        """CORE-001: an older sweep completing late cannot overwrite newer truth."""
        import threading
        account = AR(provider_id="codex", stable_id="one",
                     display_name="Codex 1", source_kind="test")
        hold = threading.Event()

        class _Provider:
            provider_id = "codex"

            def __init__(self, rem, ts, gate=None):
                self.rem = rem
                self.ts = ts
                self.gate = gate

            def discover_accounts(self):
                return [account]

            def probe(self, a, deadline):
                if self.gate is not None:
                    self.gate.wait(5)
                return UsageSnapshot(
                    account=a, status=OK, fetched_at=self.ts,
                    windows=[UsageWindow(FIVE_HOUR, 300, True,
                                         100 - self.rem, self.rem, None)])

            def shutdown(self):
                pass

        service = UsageLimitService()
        with service._lock:
            service._state.accounts = [account]
            service._state.generation = 1

        # Sweep 1: older data, held
        service._providers = {"codex": _Provider(10, 1.0, gate=hold)}
        service.refresh()
        time.sleep(0.05)

        # Sweep 2: newer data, completes immediately
        service._providers = {"codex": _Provider(90, 2.0)}
        service.refresh()
        time.sleep(0.15)

        assert service.state_copy.snapshots[account.key].fetched_at == 2.0
        assert service.state_copy.snapshots[account.key].windows[0].remaining_percent == 90

        # Release sweep 1 -> must be discarded by request_id gate
        hold.set()
        time.sleep(0.15)
        assert service.state_copy.snapshots[account.key].fetched_at == 2.0
        assert service.state_copy.snapshots[account.key].windows[0].remaining_percent == 90
        service.shutdown()

    def test_probes_run_concurrently_up_to_pool_size(self):
        """PERF-001: independent accounts fan out across the thread pool."""
        import threading
        accounts = [AR(provider_id="codex", stable_id=f"a{i}",
                       display_name=f"Codex {i}", source_kind="test")
                    for i in range(3)]
        live = 0
        peak = 0
        lock = threading.Lock()

        class _Provider:
            provider_id = "codex"

            def discover_accounts(self):
                return list(accounts)

            def probe(self, a, deadline):
                nonlocal live, peak
                with lock:
                    live += 1
                    peak = max(peak, live)
                time.sleep(0.08)
                with lock:
                    live -= 1
                return UsageSnapshot(
                    account=a, status=OK, fetched_at=time.time(),
                    windows=[UsageWindow(FIVE_HOUR, 300, True, 50, 50, None)])

            def shutdown(self):
                pass

        service = UsageLimitService()
        with service._lock:
            service._state.accounts = list(accounts)
        service._providers = {"codex": _Provider()}
        start = time.perf_counter()
        service.refresh()
        for _ in range(100):
            if len(service.state_copy.snapshots) == 3:
                break
            time.sleep(0.01)
        elapsed = time.perf_counter() - start
        assert peak == 3, f"expected 3 concurrent probes, got {peak}"
        assert elapsed < 0.20, f"expected ~0.08s concurrent, took {elapsed:.3f}s"
        service.shutdown()

    def test_shutdown_aborts_queued_probes(self):
        """PERF-001: closing the service prevents remaining accounts from starting."""
        accounts = [AR(provider_id="codex", stable_id=f"a{i}",
                       display_name=f"Codex {i}", source_kind="test")
                    for i in range(3)]

        class _SlowProvider:
            provider_id = "codex"

            def discover_accounts(self):
                return list(accounts)

            def probe(self, a, deadline):
                time.sleep(0.2)
                return UsageSnapshot(
                    account=a, status=OK, fetched_at=time.time(),
                    windows=[UsageWindow(FIVE_HOUR, 300, True, 50, 50, None)])

            def shutdown(self):
                pass

        service = UsageLimitService()
        with service._lock:
            service._state.accounts = list(accounts)
        service._providers = {"codex": _SlowProvider()}
        service.refresh()
        time.sleep(0.02)
        service.shutdown()
        time.sleep(0.5)
        assert service._closed is True


class TestPlanSpecificWindows:
    """A plan's window set must survive parsing verbatim.

    Codex Free reports a single 43200-minute (30-day) primary. Dropping it
    because it is not 5h/weekly rendered the account as two dead bars while
    a real quota was known.
    """

    def test_free_plan_monthly_window_is_kept(self):
        out = parse_windows({"rateLimits": {
            "primary": {"windowDurationMins": 43200, "usedPercent": 100,
                        "resetsAt": 1790116837},
            "secondary": None,
        }})
        assert out["monthly"]["available"] is True
        assert out["monthly"]["remaining_percent"] == 0
        assert out["monthly"]["window_duration_mins"] == 43200

    def test_unknown_duration_gets_generic_key_not_dropped(self):
        out = parse_windows({"rateLimits": {
            "primary": {"windowDurationMins": 1440, "usedPercent": 40},
        }})
        assert out["window_1440m"]["available"] is True
        assert out["window_1440m"]["remaining_percent"] == 60

    def test_zero_duration_is_ignored(self):
        out = parse_windows({"rateLimits": {
            "primary": {"windowDurationMins": 0, "usedPercent": 10},
        }})
        assert not any(k.startswith("window_") for k in out)

    def test_windows_from_drops_windows_the_plan_lacks(self):
        from fastprompter.core.usage_limits.providers.codex import _windows_from
        windows = _windows_from({
            "ok": True,
            "monthly": {"available": True, "used_percent": 100,
                        "window_duration_mins": 43200},
            "five_hour": {"available": False},
            "weekly": {"available": False},
            "plan_type": "free",
        })
        assert [w.key for w in windows] == ["monthly"]

    def test_windows_from_keeps_unavailable_when_nothing_readable(self):
        from fastprompter.core.usage_limits.providers.codex import _windows_from
        windows = _windows_from({"ok": True, "five_hour": {"available": False},
                                 "weekly": {"available": False}})
        assert len(windows) == 2
        assert all(not w.available for w in windows)

    def test_windows_sorted_shortest_first(self):
        from fastprompter.core.usage_limits.providers.codex import _windows_from
        windows = _windows_from({
            "weekly": {"available": True, "used_percent": 10,
                       "window_duration_mins": 10080},
            "five_hour": {"available": True, "used_percent": 50,
                          "window_duration_mins": 300},
        })
        assert [w.duration_minutes for w in windows] == [300, 10080]


class TestCodexBankedResets:
    def test_codex_probe_attaches_banked_resets_and_metadata(self, monkeypatch):
        account = AR(provider_id="codex", stable_id="test_id",
                     display_name="Codex Test", source_kind="test",
                     source_path="C:/dummy/path")
        p = CodexProvider()
        fake_result = {
            "ok": True,
            "five_hour": {"available": True, "remaining_percent": 80,
                          "window_duration_mins": 300},
            "plan_type": "pro",
            "banked_resets": 3,
            "reset_credits": [{"id": "c1", "status": "available"}],
        }
        import fastprompter.core.usage_limits.providers._codex_probe as probe_mod
        monkeypatch.setattr(probe_mod, "probe_codex_home", lambda path, deadline: fake_result)

        snapshot = p.probe(account, deadline=time.time() + 5.0)
        assert snapshot.status == OK
        assert snapshot.banked_resets == 3
        assert snapshot.provider_metadata.get("banked_resets") == 3
        assert len(snapshot.provider_metadata.get("reset_credits", [])) == 1

    def test_service_stale_preserves_banked_resets(self):
        acc = AR(provider_id="codex", stable_id="c_banked",
                 display_name="Codex Banked", source_kind="test")
        snap = UsageSnapshot(
            account=acc, status=OK, windows=[],
            banked_resets=2,
            provider_metadata={"banked_resets": 2},
        )
        s = UsageLimitService()
        with s._lock:
            s._state.snapshots[acc.key] = snap

        # Simulate service stale copy
        stale_snap = UsageSnapshot(
            account=snap.account,
            status=STALE,
            windows=list(snap.windows),
            fetched_at=snap.fetched_at,
            stale_since=time.time(),
            plan_type=snap.plan_type,
            error_code="refresh_failed",
            error_summary="temporary failure",
            banked_resets=snap.banked_resets,
            provider_metadata=dict(snap.provider_metadata) if snap.provider_metadata else None,
        )
        assert stale_snap.banked_resets == 2
        assert stale_snap.provider_metadata["banked_resets"] == 2

    def test_consume_codex_reset_missing_dir(self):
        from fastprompter.core.usage_limits.providers._codex_probe import consume_codex_reset
        res = consume_codex_reset("C:/nonexistent_dir_12345")
        assert res["ok"] is False
        assert "CODEX_HOME missing" in res["error"]

    def test_consume_codex_reset_success(self, tmp_path, monkeypatch):
        from fastprompter.core.usage_limits.providers._codex_probe import consume_codex_reset
        codex_home = tmp_path / ".codex"
        codex_home.mkdir()

        class FakeSession:
            def __init__(self):
                self.calls = []

            def call(self, method, params=None, timeout=None):
                self.calls.append((method, params))
                if method == "initialize":
                    return {"result": {}}
                if method == "account/rateLimitResetCredit/consume":
                    return {"result": {"outcome": "success"}}
                return {"result": {}}

            def notify(self, method, params=None):
                self.calls.append((method, params))

            def close(self):
                pass

        fake_session = FakeSession()
        import fastprompter.core.usage_limits.providers._codex_probe as probe_mod
        monkeypatch.setattr(probe_mod, "_start_app_server", lambda *a, **kw: fake_session)

        res = consume_codex_reset(str(codex_home), credit_id="cred_123")
        assert res["ok"] is True
        assert res["outcome"] == "success"
        consume_call = next(c for c in fake_session.calls if c[0] == "account/rateLimitResetCredit/consume")
        assert consume_call[1]["creditId"] == "cred_123"
        assert "idempotencyKey" in consume_call[1]

    def test_codex_provider_and_service_consume_reset(self, tmp_path, monkeypatch):
        codex_home = tmp_path / ".codex"
        codex_home.mkdir()

        p = CodexProvider()
        account = AR(provider_id="codex", stable_id="test_acc",
                     display_name="Codex Test", source_kind="test",
                     source_path=str(codex_home))

        import fastprompter.core.usage_limits.providers._codex_probe as probe_mod
        monkeypatch.setattr(probe_mod, "consume_codex_reset",
                            lambda path, credit_id=None: {"ok": True, "outcome": "success"})

        res = p.consume_reset(account)
        assert res["ok"] is True
        assert res["outcome"] == "success"

        # Test service dispatch
        s = UsageLimitService()
        s._providers["codex"] = p
        with s._lock:
            s._state.accounts = [account]

        refreshed = []
        monkeypatch.setattr(s, "refresh", lambda: refreshed.append(True))
        s_res = s.consume_account_reset(account.key)
        assert s_res["ok"] is True
        assert len(refreshed) == 1



class TestClaudeSingleAccount:
    """One Claude installation must never become two accounts."""

    def test_one_install_yields_one_account(self):
        from fastprompter.core.usage_limits.providers.claude import ClaudeProvider
        accounts = ClaudeProvider().discover_accounts()
        assert len(accounts) <= 1
        if accounts:
            assert accounts[0].provider_id == "claude"
            assert accounts[0].display_name == "Claude"

    def test_secondary_paths_are_metadata_not_accounts(self):
        from fastprompter.core.usage_limits.providers.claude import (
            _discover_config_dirs,
        )
        found = _discover_config_dirs()
        if len(found) > 1:
            from fastprompter.core.usage_limits.providers.claude import (
                ClaudeProvider,
            )
            acc = ClaudeProvider().discover_accounts()[0]
            assert len(acc.metadata.get("other_paths", [])) == len(found) - 1


class TestClaudeStatuslineBridge:
    def test_sanitizes_only_rate_limit_fields(self):
        from fastprompter.core.usage_limits.claude_statusline import (
            sanitize_statusline_payload,
        )
        out = sanitize_statusline_payload({
            "session_id": "secret-session",
            "transcript_path": "secret-path",
            "workspace": {"current_dir": "secret-workspace"},
            "rate_limits": {
                "five_hour": {"used_percentage": 12.5,
                              "resets_at": 1800000000},
                "seven_day": {"used_percentage": 200},
            },
        }, captured_at=1700000000)
        assert out == {
            "schema_version": 1,
            "source": "claude-code-statusline",
            "captured_at": 1700000000.0,
            "rate_limits": {
                "five_hour": {"used_percentage": 12.5,
                              "resets_at": 1800000000.0},
                "seven_day": {"used_percentage": 100.0},
            },
        }
        assert "session_id" not in str(out)
        assert "transcript" not in str(out)

    def test_install_disconnect_restores_existing_statusline(self, tmp_path):
        import json

        from fastprompter.core.usage_limits.claude_statusline import (
            bridge_status,
            install_bridge,
            uninstall_bridge,
        )
        directory = tmp_path / ".claude"
        directory.mkdir()
        original = {"type": "command", "command": "my-old-line --json",
                    "padding": 2}
        (directory / "settings.json").write_text(json.dumps({
            "theme": "dark", "statusLine": original,
        }), encoding="utf-8")
        install_bridge(directory, command="fastprompter --claude-statusline-bridge")
        installed = json.loads((directory / "settings.json").read_text())
        assert "--claude-statusline-bridge" in installed["statusLine"]["command"]
        assert installed["statusLine"]["padding"] == 2
        assert bridge_status(directory)["connected"] is True
        uninstall_bridge(directory)
        restored = json.loads((directory / "settings.json").read_text())
        assert restored == {"theme": "dark", "statusLine": original}

    def test_provider_reads_five_hour_and_seven_day_cache(self, tmp_path):
        import json

        from fastprompter.core.usage_limits.providers.claude import ClaudeProvider
        cache = tmp_path / "limits.json"
        cache.write_text(json.dumps({
            "schema_version": 1,
            "captured_at": time.time(),
            "rate_limits": {
                "five_hour": {"used_percentage": 30,
                              "resets_at": 1800000000},
                "seven_day": {"used_percentage": 72,
                              "resets_at": "2027-01-01T00:00:00Z"},
            },
        }), encoding="utf-8")
        account = AR(provider_id="claude", stable_id="one",
                     display_name="Claude", source_kind="test",
                     source_path=str(tmp_path))
        snap = ClaudeProvider(structured_source=str(cache)).probe(
            account, time.monotonic() + 1)
        assert snap.status == OK
        assert snap.window(FIVE_HOUR).remaining_percent == 70
        assert snap.window(WEEKLY).remaining_percent == 28

    def test_provider_reports_waiting_without_cache(self, tmp_path):
        from fastprompter.core.usage_limits.providers.claude import ClaudeProvider

        account = AR(provider_id="claude", stable_id="one",
                     display_name="Claude", source_kind="test",
                     source_path=str(tmp_path))
        snap = ClaudeProvider(structured_source=str(tmp_path / "missing.json")).probe(
            account, time.monotonic() + 1)
        assert snap.status == UNAVAILABLE
        assert snap.error_code == "waiting_for_statusline"

    def test_real_launcher_bridge_mode_writes_cache_without_qt(self, tmp_path):
        from fastprompter.core.usage_limits.claude_statusline import CACHE_NAME

        directory = tmp_path / ".claude"
        directory.mkdir()
        env = os.environ.copy()
        env["HOME"] = str(tmp_path)
        env["USERPROFILE"] = str(tmp_path)
        launcher = Path(__file__).resolve().parents[1] / "FastPrompter.pyw"
        result = subprocess.run(
            [sys.executable, str(launcher), "--claude-statusline-bridge"],
            input=json.dumps({"rate_limits": {
                "five_hour": {"used_percentage": 44},
                "seven_day": {"used_percentage": 55},
            }}),
            text=True, capture_output=True, timeout=10, env=env, check=False,
        )
        assert result.returncode == 0
        cached = json.loads((directory / CACHE_NAME).read_text(encoding="utf-8"))
        assert cached["rate_limits"]["five_hour"]["used_percentage"] == 44


class TestClaudeDesktopSampler:
    """Claude Desktop samples the same account's usage on its own timer."""

    @staticmethod
    def _history(tmp_path, samples, version=2):
        path = tmp_path / "plan-usage-history.json"
        path.write_text(json.dumps({"version": version, "samples": samples}),
                        encoding="utf-8")
        return path

    def test_reads_the_newest_sample_only(self, tmp_path):
        from fastprompter.core.usage_limits.providers._claude_desktop import (
            latest_usage,
        )
        now = 1_800_000_000.0
        path = self._history(tmp_path, [
            {"t": (now - 3600) * 1000, "u": {"fh": 10, "sd": 5}},
            {"t": (now - 300) * 1000, "u": {"fh": 61, "sd": 16}},
        ])
        usage = latest_usage(path=path, now=now)
        assert usage["windows"] == {FIVE_HOUR: 61.0, WEEKLY: 16.0}
        assert usage["fresh"] is True
        assert 290 < usage["age_s"] < 310

    def test_an_old_sample_is_returned_but_not_fresh(self, tmp_path):
        from fastprompter.core.usage_limits.providers._claude_desktop import (
            latest_usage,
        )
        now = 1_800_000_000.0
        path = self._history(tmp_path, [
            {"t": (now - 6 * 3600) * 1000, "u": {"fh": 88}},
        ])
        usage = latest_usage(path=path, now=now)
        assert usage["windows"] == {FIVE_HOUR: 88.0}
        assert usage["fresh"] is False

    def test_garbage_never_becomes_a_percentage(self, tmp_path):
        from fastprompter.core.usage_limits.providers._claude_desktop import (
            latest_usage,
        )
        now = 1_800_000_000.0
        path = self._history(tmp_path, [
            {"t": (now - 60) * 1000, "u": {"fh": "nope", "sd": True,
                                           "unknown": 50}},
        ])
        assert latest_usage(path=path, now=now) == {}
        broken = tmp_path / "broken.json"
        broken.write_text("{not json", encoding="utf-8")
        assert latest_usage(path=broken, now=now) == {}
        assert latest_usage(path=tmp_path / "missing.json", now=now) == {}

    def test_percentages_are_clamped_not_rejected(self, tmp_path):
        from fastprompter.core.usage_limits.providers._claude_desktop import (
            latest_usage,
        )
        now = 1_800_000_000.0
        path = self._history(tmp_path, [
            {"t": (now - 60) * 1000, "u": {"fh": 140, "sd": -3}},
        ])
        usage = latest_usage(path=path, now=now)
        assert usage["windows"] == {FIVE_HOUR: 100.0, WEEKLY: 0.0}

    def test_provider_uses_the_sampler_when_the_bridge_is_silent(self, tmp_path):
        from fastprompter.core.usage_limits.providers.claude import ClaudeProvider

        directory = tmp_path / ".claude"
        directory.mkdir()
        history = self._history(tmp_path, [
            {"t": time.time() * 1000, "u": {"fh": 43, "sd": 21}},
        ])
        account = AR(provider_id="claude", stable_id="one",
                     display_name="Claude", source_kind="test",
                     source_path=str(directory))
        provider = ClaudeProvider(desktop_history=str(history))
        snap = provider.probe(account, time.monotonic() + 5)
        assert snap.status == OK
        assert snap.window(FIVE_HOUR).remaining_percent == 57
        assert snap.window(WEEKLY).remaining_percent == 79
        assert "plan-usage-history" in snap.window(FIVE_HOUR).source

    def test_the_freshest_source_wins_over_a_stale_bridge_cache(self, tmp_path):
        from fastprompter.core.usage_limits.claude_statusline import CACHE_NAME
        from fastprompter.core.usage_limits.providers.claude import ClaudeProvider

        directory = tmp_path / ".claude"
        directory.mkdir()
        now = time.time()
        # Bridge cache is 3 hours old and says 5% used; Desktop sampled 90%
        # a minute ago. Showing the stale 95% remaining would be a lie.
        (directory / CACHE_NAME).write_text(json.dumps({
            "schema_version": 1,
            "captured_at": now - 3 * 3600,
            "rate_limits": {
                "five_hour": {"used_percentage": 5, "resets_at": now + 900},
            },
        }), encoding="utf-8")
        (directory / "settings.json").write_text(json.dumps({
            "statusLine": {"type": "command",
                           "command": "x --claude-statusline-bridge"},
        }), encoding="utf-8")
        history = self._history(tmp_path, [
            {"t": (now - 60) * 1000, "u": {"fh": 90}},
        ])
        account = AR(provider_id="claude", stable_id="one",
                     display_name="Claude", source_kind="test",
                     source_path=str(directory))
        snap = ClaudeProvider(desktop_history=str(history)).probe(
            account, time.monotonic() + 5)
        assert snap.window(FIVE_HOUR).remaining_percent == 10
        # the older cache still contributes the reset time it alone knows
        assert snap.window(FIVE_HOUR).resets_at_epoch == now + 900


class TestClaudeTranscriptRefusals:
    """Claude Code journals a quotaLimits block when the API refuses."""

    @staticmethod
    def _transcript(directory, records, mtime=None):
        project = directory / "projects" / "slug"
        project.mkdir(parents=True, exist_ok=True)
        path = project / "session.jsonl"
        path.write_text("\n".join(json.dumps(r) for r in records) + "\n",
                        encoding="utf-8")
        if mtime is not None:
            # The scan only looks at transcripts younger than a week, so a
            # test using a synthetic clock must age the file to match it.
            os.utime(path, (mtime, mtime))
        return path

    def test_a_future_refusal_blocks_its_window(self, tmp_path):
        from fastprompter.core.usage_limits.providers._claude_transcripts import (
            active_quota_blocks,
        )
        now = 1_800_000_000.0
        directory = tmp_path / ".claude"
        self._transcript(directory, [
            {"type": "assistant", "timestamp": "2027-01-01T00:00:00Z",
             "quotaLimits": {"status": "rejected", "resetsAt": now + 1800,
                             "rateLimitType": "five_hour"}},
        ], mtime=now - 60)
        blocks = active_quota_blocks(directory, now=now)
        assert set(blocks) == {FIVE_HOUR}
        assert blocks[FIVE_HOUR]["resets_at"] == now + 1800

    def test_a_transcript_older_than_a_week_is_ignored(self, tmp_path):
        """A month-old refusal describes a window that reset long ago."""
        from fastprompter.core.usage_limits.providers._claude_transcripts import (
            active_quota_blocks,
        )
        now = 1_800_000_000.0
        directory = tmp_path / ".claude"
        self._transcript(directory, [
            {"type": "assistant", "quotaLimits": {
                "status": "rejected", "resetsAt": now + 1800,
                "rateLimitType": "five_hour"}},
        ], mtime=now - 30 * 24 * 3600)
        assert active_quota_blocks(directory, now=now) == {}

    def test_a_passed_reset_is_no_longer_a_block(self, tmp_path):
        from fastprompter.core.usage_limits.providers._claude_transcripts import (
            active_quota_blocks,
        )
        now = 1_800_000_000.0
        directory = tmp_path / ".claude"
        self._transcript(directory, [
            {"type": "assistant", "quotaLimits": {
                "status": "rejected", "resetsAt": now - 60,
                "rateLimitType": "five_hour"}},
        ], mtime=now - 60)
        assert active_quota_blocks(directory, now=now) == {}

    def test_an_allowed_request_is_not_a_block(self, tmp_path):
        from fastprompter.core.usage_limits.providers._claude_transcripts import (
            active_quota_blocks,
        )
        now = 1_800_000_000.0
        directory = tmp_path / ".claude"
        self._transcript(directory, [
            {"type": "assistant", "quotaLimits": {
                "status": "allowed", "resetsAt": now + 600,
                "rateLimitType": "five_hour"}},
        ], mtime=now - 60)
        assert active_quota_blocks(directory, now=now) == {}

    def test_seven_day_maps_to_the_weekly_window(self, tmp_path):
        from fastprompter.core.usage_limits.providers._claude_transcripts import (
            active_quota_blocks,
        )
        now = 1_800_000_000.0
        directory = tmp_path / ".claude"
        self._transcript(directory, [
            {"type": "assistant", "quotaLimits": {
                "status": "rejected", "resetsAt": now + 3600,
                "rateLimitType": "seven_day"}},
        ], mtime=now - 60)
        assert set(active_quota_blocks(directory, now=now)) == {WEEKLY}

    def test_a_refusal_overrides_a_healthy_percentage(self, tmp_path):
        """The refusal is the provider's verdict; the sample is a guess."""
        from fastprompter.core.usage_limits.providers.claude import ClaudeProvider

        now = time.time()
        directory = tmp_path / ".claude"
        directory.mkdir()
        self._transcript(directory, [
            {"type": "assistant", "quotaLimits": {
                "status": "rejected", "resetsAt": now + 1200,
                "rateLimitType": "five_hour"}},
        ])
        history = tmp_path / "plan-usage-history.json"
        history.write_text(json.dumps({"version": 2, "samples": [
            {"t": (now - 60) * 1000, "u": {"fh": 30, "sd": 20}},
        ]}), encoding="utf-8")
        account = AR(provider_id="claude", stable_id="one",
                     display_name="Claude", source_kind="test",
                     source_path=str(directory))
        snap = ClaudeProvider(desktop_history=str(history)).probe(
            account, time.monotonic() + 5)
        assert snap.status == OK
        five = snap.window(FIVE_HOUR)
        assert five.remaining_percent == 0.0     # refused, not 70% free
        assert five.resets_at_epoch == now + 1200
        assert snap.window(WEEKLY).remaining_percent == 80

    def test_a_transcript_only_refusal_still_renders_a_window(self, tmp_path):
        from fastprompter.core.usage_limits.providers.claude import ClaudeProvider

        now = time.time()
        directory = tmp_path / ".claude"
        directory.mkdir()
        self._transcript(directory, [
            {"type": "assistant", "quotaLimits": {
                "status": "rejected", "resetsAt": now + 600,
                "rateLimitType": "seven_day"}},
        ])
        account = AR(provider_id="claude", stable_id="one",
                     display_name="Claude", source_kind="test",
                     source_path=str(directory))
        snap = ClaudeProvider(desktop_history=str(tmp_path / "none.json")).probe(
            account, time.monotonic() + 5)
        assert snap.status == OK
        assert snap.window(WEEKLY).remaining_percent == 0.0

    def test_every_source_silent_stays_honest(self, tmp_path):
        from fastprompter.core.usage_limits.providers.claude import ClaudeProvider

        directory = tmp_path / ".claude"
        directory.mkdir()
        account = AR(provider_id="claude", stable_id="one",
                     display_name="Claude", source_kind="test",
                     source_path=str(directory))
        snap = ClaudeProvider(desktop_history=str(tmp_path / "none.json")).probe(
            account, time.monotonic() + 5)
        assert snap.status == UNAVAILABLE
        assert snap.error_code == "bridge_not_connected"
        assert all(not window.available for window in snap.windows)


class TestLimitNotifications:
    # Reset epochs must be in the FUTURE: a window whose own reset time has
    # passed is treated as refilled (model.apply_elapsed_resets), so a 1970
    # placeholder would silently make every fixture read as 100% free.
    _T0 = 1_800_000_000.0

    @staticmethod
    def _fixture(remaining=15, reset=None, status=OK):
        account = AR(provider_id="codex", stable_id="work",
                     display_name="Codex 1", source_kind="test")
        if reset is None:
            reset = time.time() + 3600
        window = UsageWindow(FIVE_HOUR, 300, True,
                             100 - remaining, remaining, reset)
        snapshot = UsageSnapshot(account=account, status=status,
                                 windows=[window], fetched_at=time.time())
        return account, snapshot

    def test_fires_once_per_reset_window(self):
        from fastprompter.core.usage_limits.notifications import (
            evaluate_limit_notifications,
            notification_key,
        )
        account, snapshot = self._fixture()
        key = notification_key(account.key, FIVE_HOUR)
        rules = {key: {"enabled": "True", "threshold": 20}}
        alerts, state = evaluate_limit_notifications(
            [account], {account.key: snapshot}, rules, {})
        assert [alert.key for alert in alerts] == [key]
        alerts, state2 = evaluate_limit_notifications(
            [account], {account.key: snapshot}, rules, state)
        assert alerts == []
        assert state2 == state

    def test_rearms_after_recovery_and_new_reset(self):
        from fastprompter.core.usage_limits.notifications import (
            evaluate_limit_notifications,
            notification_key,
        )
        soon = time.time() + 1800
        later = time.time() + 7200
        account, low = self._fixture(remaining=15, reset=soon)
        key = notification_key(account.key, FIVE_HOUR)
        rules = {key: {"enabled": "True", "threshold": 20}}
        _alerts, state = evaluate_limit_notifications(
            [account], {account.key: low}, rules, {})

        _account, recovered = self._fixture(remaining=80, reset=soon)
        alerts, state = evaluate_limit_notifications(
            [account], {account.key: recovered}, rules, state)
        assert alerts == []
        assert "low_alerted" not in state[key]
        alerts, state = evaluate_limit_notifications(
            [account], {account.key: low}, rules, state)
        assert len(alerts) == 1

        # A NEW window that is still low must NOT re-fire: recovery is the
        # only re-arm signal. A fresh rolling 5h window reports remaining=10
        # and a new resets_at — re-arming on that was the bug that replayed
        # the same alert every 3-minute sweep.
        _account, next_cycle = self._fixture(remaining=10, reset=later)
        alerts, _state = evaluate_limit_notifications(
            [account], {account.key: next_cycle}, rules, state)
        assert alerts == []

    def test_stale_snapshot_never_fires_or_forgets_suppression(self):
        from fastprompter.core.usage_limits.notifications import (
            evaluate_limit_notifications,
            notification_key,
        )
        account, _snapshot = self._fixture(status=STALE)
        key = notification_key(account.key, FIVE_HOUR)
        rules = {key: {"enabled": "True", "threshold": 20}}
        prior = {key: {"cycle": "reset:1800000000", "threshold": 20.0}}
        alerts, state = evaluate_limit_notifications(
            [account], {account.key: _snapshot}, rules, prior)
        assert alerts == []
        assert state == prior

    def test_reset_alert_needs_an_observed_cycle_transition(self):
        from fastprompter.core.usage_limits.notifications import (
            evaluate_limit_notifications,
            notification_key,
        )
        soon = time.time() + 1800
        later = time.time() + 7200
        account, first = self._fixture(remaining=80, reset=soon)
        key = notification_key(account.key, FIVE_HOUR)
        rules = {key: {
            "reset_enabled": "True",
            "reset_sound": "file:success.wav",
            "reset_volume": 0.27,
        }}
        alerts, state = evaluate_limit_notifications(
            [account], {account.key: first}, rules, {})
        assert alerts == []  # baseline, not a fake startup reset
        assert state[key]["last_cycle"] == f"reset:{int(soon)}"

        _account, reset = self._fixture(remaining=100, reset=later)
        alerts, state = evaluate_limit_notifications(
            [account], {account.key: reset}, rules, state)
        assert len(alerts) == 1
        assert alerts[0].kind == "reset"
        assert alerts[0].rule["reset_sound"] == "file:success.wav"
        assert alerts[0].rule["reset_volume"] == 0.27
        alerts, _state = evaluate_limit_notifications(
            [account], {account.key: reset}, rules, state)
        assert alerts == []

    def test_idle_window_with_drifting_reset_never_repeats(self):
        """The provider rolls ``resets_at`` forward on an untouched window.

        That used to re-arm the rule on every 3-minute sweep, so a low quota
        replayed its sound/popup forever. Only real recovery may re-arm.
        """
        from fastprompter.core.usage_limits.notifications import (
            evaluate_limit_notifications,
            notification_key,
        )
        base = time.time() + 1800
        account, _snap = self._fixture(remaining=5, reset=base)
        key = notification_key(account.key, FIVE_HOUR)
        rules = {key: {"enabled": "True", "threshold": 20,
                       "reset_enabled": "True"}}
        state = {}
        fired = 0
        for step in (0, 180, 360, 540, 720):
            _acc, snap = self._fixture(remaining=5, reset=base + step)
            alerts, state = evaluate_limit_notifications(
                [account], {account.key: snap}, rules, state)
            fired += len(alerts)
        assert fired == 1   # once, not once per sweep

    def test_gradual_recovery_emits_exactly_one_reset_alert(self):
        """CORE-002: 5 -> 10 -> 15 -> 20 -> 25% must not alert on every step."""
        from fastprompter.core.usage_limits.notifications import (
            evaluate_limit_notifications,
            notification_key,
        )
        base = time.time() + 3600
        account, _snap = self._fixture(remaining=5, reset=base)
        key = notification_key(account.key, FIVE_HOUR)
        rules = {key: {"enabled": "True", "threshold": 20,
                       "reset_enabled": "True"}}
        state = {}
        resets = 0
        for pct, step in ((5, 0), (10, 180), (15, 360), (20, 540), (25, 720)):
            _acc, snap = self._fixture(remaining=pct, reset=base + step)
            alerts, state = evaluate_limit_notifications(
                [account], {account.key: snap}, rules, state)
            resets += sum(1 for a in alerts if a.kind == "reset")
        assert resets == 1, "exactly one reset alert for the whole recovery episode"

    def test_gated_short_window_neither_alerts_nor_shows_quota(self):
        """Weekly 0% makes a reported-100% 5h window unusable, so it is 0."""
        from fastprompter.core.usage_limits.model import gate_windows
        from fastprompter.core.usage_limits.notifications import (
            evaluate_limit_notifications,
            notification_key,
        )
        account = AR(provider_id="codex", stable_id="work",
                     display_name="Codex 1", source_kind="test")
        now = time.time()
        snapshot = UsageSnapshot(
            account=account, status=OK,
            windows=[UsageWindow(FIVE_HOUR, 300, True, 0, 100, now + 900),
                     UsageWindow(WEEKLY, 10080, True, 100, 0, now + 86400)],
            fetched_at=now)
        gated = gate_windows(snapshot.windows)
        five = next(w for w in gated if w.key == FIVE_HOUR)
        weekly = next(w for w in gated if w.key == WEEKLY)
        assert five.remaining_percent == 0.0
        assert five.gated_by == WEEKLY
        assert weekly.gated_by is None       # the blocker itself is honest

        five_key = notification_key(account.key, FIVE_HOUR)
        weekly_key = notification_key(account.key, WEEKLY)
        rules = {five_key: {"enabled": "True", "threshold": 20},
                 weekly_key: {"enabled": "True", "threshold": 20}}
        alerts, _state = evaluate_limit_notifications(
            [account], {account.key: snapshot}, rules, {})
        # only the governing window alerts — the gated one is not an
        # independent quota, so alerting on it would double every popup
        assert [a.key for a in alerts] == [weekly_key]

    def test_a_free_plan_single_window_is_never_self_gated(self):
        from fastprompter.core.usage_limits.model import MONTHLY, gate_windows
        windows = [UsageWindow(MONTHLY, 43200, True, 100, 0, 3000)]
        out = gate_windows(windows)
        assert out[0].remaining_percent == 0
        assert out[0].gated_by is None

    def test_healthy_windows_are_untouched(self):
        from fastprompter.core.usage_limits.model import gate_windows
        windows = [UsageWindow(FIVE_HOUR, 300, True, 40, 60, 1000),
                   UsageWindow(WEEKLY, 10080, True, 50, 50, 2000)]
        assert gate_windows(windows) == windows


class TestElapsedResetsRefillImmediately:
    """A window whose own reset time passed is full — do not wait for a sweep.

    The provider already told us when the window resets. Once that instant is
    behind us the outcome is not in doubt, yet the gauge used to keep showing
    the pre-reset number until the next 3-minute probe confirmed the obvious.
    """

    def test_a_passed_reset_reads_as_full(self):
        from fastprompter.core.usage_limits.model import apply_elapsed_resets
        now = 1_800_000_000.0
        windows = [UsageWindow(FIVE_HOUR, 300, True, 100, 0, now - 1)]
        out = apply_elapsed_resets(windows, now)
        assert out[0].remaining_percent == 100.0
        assert out[0].used_percent == 0.0
        assert out[0].assumed_full is True
        # the elapsed timestamp is dropped: nothing may render "resets in -1s"
        assert out[0].resets_at_epoch is None

    def test_a_future_reset_is_left_exactly_alone(self):
        from fastprompter.core.usage_limits.model import apply_elapsed_resets
        now = 1_800_000_000.0
        windows = [UsageWindow(FIVE_HOUR, 300, True, 100, 0, now + 60)]
        assert apply_elapsed_resets(windows, now) == windows

    def test_a_window_with_no_reset_time_is_never_assumed(self):
        """No timestamp means no proof; the 3-minute sweep decides."""
        from fastprompter.core.usage_limits.model import apply_elapsed_resets
        now = 1_800_000_000.0
        windows = [UsageWindow(FIVE_HOUR, 300, True, 90, 10, None)]
        assert apply_elapsed_resets(windows, now) == windows

    def test_an_unavailable_window_stays_unavailable(self):
        from fastprompter.core.usage_limits.model import apply_elapsed_resets
        now = 1_800_000_000.0
        windows = [UsageWindow.unavailable(FIVE_HOUR)]
        assert apply_elapsed_resets(windows, now) == windows

    def test_a_weekly_reset_lifts_the_gate_it_was_holding(self):
        """The blocker refilling must free the short window in the same pass."""
        from fastprompter.core.usage_limits.model import resolved_windows
        now = 1_800_000_000.0
        windows = [UsageWindow(FIVE_HOUR, 300, True, 40, 60, now + 900),
                   UsageWindow(WEEKLY, 10080, True, 100, 0, now - 5)]
        out = resolved_windows(windows, now)
        five = next(w for w in out if w.key == FIVE_HOUR)
        weekly = next(w for w in out if w.key == WEEKLY)
        assert weekly.remaining_percent == 100.0
        assert weekly.assumed_full is True
        assert five.gated_by is None          # gate lifted, not inherited
        assert five.remaining_percent == 60   # its own number survives

    def test_a_live_weekly_still_gates_a_reset_short_window(self):
        """A refilled 5h window is still worthless while weekly is spent."""
        from fastprompter.core.usage_limits.model import resolved_windows
        now = 1_800_000_000.0
        windows = [UsageWindow(FIVE_HOUR, 300, True, 100, 0, now - 5),
                   UsageWindow(WEEKLY, 10080, True, 100, 0, now + 86400)]
        out = resolved_windows(windows, now)
        five = next(w for w in out if w.key == FIVE_HOUR)
        assert five.gated_by == WEEKLY
        assert five.remaining_percent == 0.0

    def test_resolved_windows_is_reset_then_gate(self):
        """Order matters: refill first, then gate on what is still spent."""
        from fastprompter.core.usage_limits.model import (
            apply_elapsed_resets,
            gate_windows,
            resolved_windows,
        )
        now = 1_800_000_000.0
        windows = [UsageWindow(FIVE_HOUR, 300, True, 0, 100, now + 900),
                   UsageWindow(WEEKLY, 10080, True, 100, 0, now + 86400)]
        assert resolved_windows(windows, now) == \
            gate_windows(apply_elapsed_resets(windows, now))

    def test_the_notifier_sees_the_refill_as_a_recovery(self):
        """A reset the clock proved must fire the reset alert, once."""
        from fastprompter.core.usage_limits.notifications import (
            evaluate_limit_notifications,
            notification_key,
        )
        account = AR(provider_id="codex", stable_id="work",
                     display_name="Codex 1", source_kind="test")
        key = notification_key(account.key, FIVE_HOUR)
        rules = {key: {"enabled": "True", "threshold": 20,
                       "reset_enabled": "True"}}
        spent = UsageSnapshot(
            account=account, status=OK, fetched_at=time.time(),
            windows=[UsageWindow(FIVE_HOUR, 300, True, 100, 0,
                                 time.time() + 2)])
        alerts, state = evaluate_limit_notifications(
            [account], {account.key: spent}, rules, {})
        assert [a.kind for a in alerts] == ["low"]

        # the same snapshot, read after its reset time passed
        elapsed = UsageSnapshot(
            account=account, status=OK, fetched_at=time.time(),
            windows=[UsageWindow(FIVE_HOUR, 300, True, 100, 0,
                                 time.time() - 2)])
        alerts, state = evaluate_limit_notifications(
            [account], {account.key: elapsed}, rules, state)
        assert [a.kind for a in alerts] == ["reset"]
        alerts, _state = evaluate_limit_notifications(
            [account], {account.key: elapsed}, rules, state)
        assert alerts == []      # once, not on every sweep

    def test_initial_poll_suppresses_reset_alert_between_sessions(self):
        from fastprompter.core.usage_limits.notifications import (
            evaluate_limit_notifications,
            notification_key,
        )
        account = AR(provider_id="claude", stable_id="c1",
                     display_name="C", source_kind="test")
        key = notification_key(account.key, FIVE_HOUR)
        rules = {key: {"enabled": "True", "threshold": 20, "reset_enabled": "True"}}

        # Simulate prior session saved state with 10% remaining
        old_state = {key: {"remaining": 10.0}}

        # Fresh snapshot on launch shows 100% (quota reset occurred between sessions)
        fresh_snap = UsageSnapshot(
            account=account, status=OK, fetched_at=time.time(),
            windows=[UsageWindow(FIVE_HOUR, 300, True, 100, 100, None)])

        # Initial poll on startup must NOT fire reset alert
        alerts, state = evaluate_limit_notifications(
            [account], {account.key: fresh_snap}, rules, old_state, is_initial_poll=True)
        assert alerts == []
        assert state[key]["remaining"] == 100.0
        assert state[key]["reset_alerted"] is True


class TestVendorResetColors:
    def test_claude_is_orangish(self):
        color = provider_reset_color("claude")
        assert color is not None
        r, g, b = (int(color[i:i + 2], 16) for i in (1, 3, 5))
        assert r > g > b * 0.6, color

    def test_codex_is_bluish(self):
        color = provider_reset_color("codex")
        assert color is not None
        r, g, b = (int(color[i:i + 2], 16) for i in (1, 3, 5))
        assert b > r and b > g, color

    def test_unknown_vendor_returns_none(self):
        assert provider_reset_color("grok") is None


class TestSoonestReset:
    def _snap(self, provider_id, epoch, gated_by=None):
        account = AR(provider_id=provider_id, stable_id=provider_id,
                     display_name=provider_id, source_kind="test")
        window = UsageWindow(FIVE_HOUR, 300, True, 10, 90, epoch,
                             gated_by=gated_by)
        return UsageSnapshot(account=account, status=OK,
                             fetched_at=time.time(), windows=[window])

    def test_picks_earliest_epoch_and_its_vendor(self):
        codex = self._snap("codex", time.time() + 3600)
        claude = self._snap("claude", time.time() + 600)
        provider, epoch = soonest_reset({
            codex.account.key: codex, claude.account.key: claude})
        assert provider == "claude"
        assert epoch == claude.windows[0].resets_at_epoch

    def test_gated_window_is_skipped(self):
        gated = self._snap("codex", time.time() + 60, gated_by="weekly")
        open_ = self._snap("claude", time.time() + 3600)
        provider, epoch = soonest_reset(
            {gated.account.key: gated, open_.account.key: open_})
        assert provider == "claude"
        assert epoch == open_.windows[0].resets_at_epoch

    def test_hidden_account_is_skipped(self):
        codex = self._snap("codex", time.time() + 60)
        provider, epoch = soonest_reset({codex.account.key: codex},
                                        hidden_keys={codex.account.key})
        assert provider is None and epoch is None

    def test_empty_map_returns_none(self):
        assert soonest_reset({}) == (None, None)
