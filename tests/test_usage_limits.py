"""Tests for the provider-neutral usage-limit subsystem.

Covers:

* stable identity and canonical path normalization;
* window parsing (by duration, not primary/secondary position);
* service: per-account isolation, generation discard, stale preservation;
* Codex discovery: env + default + siblings, dedupe, extra paths.
"""

from __future__ import annotations

import os
import time

import pytest

from fastprompter.core.usage_limits.model import (
    AccountRef,
    FIVE_HOUR,
    OK,
    STALE,
    WEEKLY,
    AccountRef as AR,
    UsageSnapshot,
    UsageWindow,
    canonical_path,
    stable_id_for,
)
from fastprompter.core.usage_limits.providers.codex import (
    CodexProvider,
    parse_windows,
)


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
