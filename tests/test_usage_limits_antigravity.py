"""Antigravity provider tests — CLI first, refusal journal as the fallback.

The provider has two very unequal sources, and each has its own risk:

* the CLI states exact percentages per quota POOL, and Antigravity bills Gemini
  models and Claude/GPT models against independent pools — so the tests here
  guard that the pools never gate or overwrite each other;
* the refusal journal proves a block but never a percentage, so a number may
  appear only while Antigravity itself refused work.

Every provider test pins its source explicitly (``use_cli``) or stubs the CLI
reader. A test that let the real ``agy`` answer would assert on this machine's
live quota, which changes every five hours.
"""

from __future__ import annotations

import json
import os
import time

from fastprompter.core.usage_limits.model import (
    OK,
    UNAVAILABLE,
    WEEKLY,
    UsageWindow,
    base_key,
    gate_windows,
    provider_reset_color,
    qualified_key,
    resolved_windows,
)
from fastprompter.core.usage_limits.model import AccountRef as AR
from fastprompter.core.usage_limits.providers import _antigravity_cli
from fastprompter.core.usage_limits.providers._antigravity_brain import (
    latest_refusal,
)
from fastprompter.core.usage_limits.providers.antigravity import (
    QUOTA,
    RESET_GRACE_S,
    AntigravityProvider,
    source_status,
)


def _message(directory, conversation, name, content, timestamp=None,
             mtime=None):
    folder = (directory / "brain" / conversation / ".system_generated"
              / "messages")
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{name}.json"
    record = {"id": name, "sender": "system", "content": content}
    if timestamp is not None:
        record["timestamp"] = timestamp
    path.write_text(json.dumps(record), encoding="utf-8")
    if mtime is not None:
        os.utime(path, (mtime, mtime))
        os.utime(folder, (mtime, mtime))
    return path


_REFUSAL = ('The subagent X encountered an error: RESOURCE_EXHAUSTED '
            '(code 429): Individual quota reached. Please upgrade your '
            'subscription to increase your limits. Resets in {delay}.')


def _clear_cache():
    from fastprompter.core.usage_limits.providers import _antigravity_brain
    _antigravity_brain._cache.clear()


def _journal_provider(directory):
    """The provider with the CLI switched off — journal behaviour only."""
    return AntigravityProvider(data_dir=str(directory), use_cli=False)


class TestBrainRefusalParsing:
    def test_a_refusal_becomes_a_reset_epoch(self, tmp_path):
        _clear_cache()
        now = time.time()
        _message(tmp_path, "conv-a", "m1",
                 _REFUSAL.format(delay="2h53m44s"),
                 timestamp="2026-08-15T16:23:30.918980800Z",
                 mtime=now - 60)
        found = latest_refusal(tmp_path, now=now)
        observed = found["observed_at"]
        assert abs(found["resets_at"] - (observed + 2 * 3600 + 53 * 60 + 44)) < 1
        assert found["source"] == "antigravity-brain-message"

    def test_nine_digit_fractional_timestamp_is_read(self, tmp_path):
        """Antigravity writes 9 fractional digits; fromisoformat takes 6."""
        import datetime
        _clear_cache()
        now = time.time()
        _message(tmp_path, "conv-a", "m1", _REFUSAL.format(delay="1h"),
                 timestamp="2026-08-22T10:48:59.737723300Z", mtime=now - 60)
        found = latest_refusal(tmp_path, now=now)
        expected = datetime.datetime(2026, 8, 22, 10, 48, 59, 737723,
                                     tzinfo=datetime.UTC).timestamp()
        # the message's own timestamp, not the file mtime we set a minute ago
        assert abs(found["observed_at"] - expected) < 1

    def test_a_per_model_hiccup_is_not_a_quota_window(self, tmp_path):
        """``Resets in 0s`` / no reset clause = one model, not the account."""
        _clear_cache()
        now = time.time()
        _message(tmp_path, "conv-a", "m1",
                 "RESOURCE_EXHAUSTED (code 429): You have exhausted your "
                 "capacity on this model. Resets in 0s.", mtime=now - 60)
        _message(tmp_path, "conv-a", "m2",
                 "RESOURCE_EXHAUSTED (code 429): You have exhausted your "
                 "capacity on this model.", mtime=now - 60)
        assert latest_refusal(tmp_path, now=now) == {}

    def test_a_live_block_beats_a_newer_expired_one(self, tmp_path):
        _clear_cache()
        now = time.time()
        _message(tmp_path, "conv-a", "old", _REFUSAL.format(delay="80h"),
                 timestamp=_iso(now - 3600), mtime=now - 3600)
        _message(tmp_path, "conv-b", "new", _REFUSAL.format(delay="1m"),
                 timestamp=_iso(now - 600), mtime=now - 600)
        found = latest_refusal(tmp_path, now=now)
        assert found["resets_at"] > now          # the 80h block, still live
        assert found["resets_at"] - now > 3600

    def test_a_conversation_older_than_a_week_is_ignored(self, tmp_path):
        _clear_cache()
        now = time.time()
        _message(tmp_path, "conv-a", "m1", _REFUSAL.format(delay="80h"),
                 timestamp=_iso(now - 30 * 86400), mtime=now - 30 * 86400)
        assert latest_refusal(tmp_path, now=now) == {}

    def test_unreadable_and_missing_paths_are_silent(self, tmp_path):
        _clear_cache()
        now = time.time()
        assert latest_refusal(tmp_path / "nope", now=now) == {}
        folder = (tmp_path / "brain" / "conv" / ".system_generated"
                  / "messages")
        folder.mkdir(parents=True)
        (folder / "broken.json").write_text(
            "{not json RESOURCE_EXHAUSTED Resets in 1h", encoding="utf-8")
        assert latest_refusal(tmp_path, now=now) == {}

    def test_the_scan_is_cached_by_directory_stat(self, tmp_path, monkeypatch):
        _clear_cache()
        now = time.time()
        _message(tmp_path, "conv-a", "m1", _REFUSAL.format(delay="1h"),
                 timestamp=_iso(now - 60), mtime=now - 60)
        first = latest_refusal(tmp_path, now=now)
        assert first
        # A second sweep must not re-read the message files. Poisoning open()
        # proves it: a cache miss would raise instead of quietly costing IO
        # every 3 minutes for the life of the app.
        import builtins
        real_open = builtins.open

        def _poisoned(path, *args, **kwargs):
            if str(path).endswith(".json"):
                raise AssertionError(f"re-read a cached message: {path}")
            return real_open(path, *args, **kwargs)

        monkeypatch.setattr(builtins, "open", _poisoned)
        assert latest_refusal(tmp_path, now=now) == first


class TestAntigravityCliPayload:
    """The live payload shape, captured from agy 1.1.25."""

    _PAYLOAD = {
        "status": "SUCCESS",
        "command": {"name": "usage", "data": {"groups": [
            {"name": "Gemini Models", "buckets": [
                {"id": "gemini-weekly", "window": "weekly",
                 "remaining_fraction": 0.6814926862716675,
                 "reset_time": "2026-09-08T20:06:36Z"},
                {"id": "gemini-5h", "window": "5h",
                 "remaining_fraction": 0.09602990001440048,
                 "reset_time": "2026-09-03T12:41:31Z"}]},
            {"name": "Claude and GPT models", "buckets": [
                {"id": "3p-weekly", "window": "weekly",
                 "remaining_fraction": 0,
                 "reset_time": "2026-09-04T16:16:03Z"},
                {"id": "3p-5h", "window": "5h", "disabled": True,
                 "remaining_fraction": 1}]}]}},
    }

    def test_every_pool_and_window_survives(self):
        rows = _antigravity_cli.parse_usage_payload(self._PAYLOAD)
        assert [(r["group"], r["key"]) for r in rows] == [
            ("gemini_models", "weekly"),
            ("gemini_models", "five_hour"),
            ("claude_and_gpt_models", "weekly"),
            ("claude_and_gpt_models", "five_hour"),
        ]
        assert rows[0]["group_label"] == "Gemini Models"
        assert rows[2]["group_label"] == "Claude and GPT models"

    def test_a_disabled_bucket_is_kept_at_zero_not_dropped(self):
        """The 5h limit EXISTS while its weekly sibling is spent.

        Antigravity says so itself ("the 5-hour limit does not currently
        apply"), and ships ``remaining_fraction: 1`` with it. Believing that
        would advertise free quota on a pool that refuses everything; dropping
        the bucket would hide a limit the user has. Zero remaining is the only
        honest reading, and the model then labels it "blocked by weekly".
        """
        rows = _antigravity_cli.parse_usage_payload(self._PAYLOAD)
        blocked = next(r for r in rows
                       if r["group"] == "claude_and_gpt_models"
                       and r["key"] == "five_hour")
        assert blocked["remaining"] == 0.0
        assert blocked["disabled"] is True

    def test_fractions_become_percentages(self):
        rows = _antigravity_cli.parse_usage_payload(self._PAYLOAD)
        gemini_5h = next(r for r in rows if r["key"] == "five_hour")
        assert abs(gemini_5h["remaining"] - 9.602990) < 0.001

    def test_iso_reset_becomes_an_epoch(self):
        import datetime
        rows = _antigravity_cli.parse_usage_payload(self._PAYLOAD)
        expected = datetime.datetime(2026, 9, 3, 12, 41, 31,
                                     tzinfo=datetime.UTC).timestamp()
        gemini_5h = next(r for r in rows if r["key"] == "five_hour")
        assert gemini_5h["resets_at"] == expected

    def test_garbage_yields_no_window(self):
        assert _antigravity_cli.parse_usage_payload({}) == []
        assert _antigravity_cli.parse_usage_payload(
            {"command": {"data": {"groups": "nope"}}}) == []
        assert _antigravity_cli.parse_usage_payload(
            {"command": {"data": {"groups": [
                {"name": "X", "buckets": [
                    {"window": "weekly", "remaining_fraction": "nope"},
                    {"window": "century", "remaining_fraction": 0.5}]}]}}}) == []


class TestAntigravityDisabledWindowIsBlockedNotFree:
    """The pool's own weekly gates its 5h window, end to end."""

    def _reading(self, now):
        return {"windows": [
            {"key": "weekly", "group": "third_party",
             "group_label": "Claude and GPT models", "remaining": 0.0,
             "resets_at": now + 29 * 3600, "duration_minutes": 10080,
             "disabled": False},
            {"key": "five_hour", "group": "third_party",
             "group_label": "Claude and GPT models", "remaining": 0.0,
             "resets_at": None, "duration_minutes": 300, "disabled": True},
        ], "captured_at": now, "source": "antigravity-cli-usage"}

    def test_the_five_hour_window_renders_and_says_what_blocks_it(
            self, tmp_path, monkeypatch):
        (tmp_path / "brain").mkdir()
        now = time.time()
        monkeypatch.setattr(_antigravity_cli, "read_usage",
                            lambda *a, **k: self._reading(now))
        snap = AntigravityProvider(data_dir=str(tmp_path)).probe(
            _account(tmp_path), time.monotonic() + 5)
        windows = resolved_windows(snap.windows)
        five = next(w for w in windows if base_key(w.key) == "five_hour")
        assert five.available is True          # the limit exists
        assert five.remaining_percent == 0.0   # but nothing can be spent
        assert five.gated_by == qualified_key(WEEKLY, "third_party")

    def test_it_never_alerts_on_its_own(self, tmp_path, monkeypatch):
        """Only the governing weekly alerts; the gated 5h would double it."""
        from fastprompter.core.usage_limits.notifications import (
            evaluate_limit_notifications,
            notification_key,
        )
        (tmp_path / "brain").mkdir()
        now = time.time()
        monkeypatch.setattr(_antigravity_cli, "read_usage",
                            lambda *a, **k: self._reading(now))
        account = _account(tmp_path)
        snap = AntigravityProvider(data_dir=str(tmp_path)).probe(
            account, time.monotonic() + 5)
        weekly_key = notification_key(
            account.key, qualified_key(WEEKLY, "third_party"))
        five_key = notification_key(
            account.key, qualified_key("five_hour", "third_party"))
        rules = {weekly_key: {"enabled": "True", "threshold": 20},
                 five_key: {"enabled": "True", "threshold": 20}}
        alerts, _state = evaluate_limit_notifications(
            [account], {account.key: snap}, rules, {})
        assert [a.key for a in alerts] == [weekly_key]


class TestAntigravityCliSnapshot:
    def _stub(self, monkeypatch, reading):
        monkeypatch.setattr(_antigravity_cli, "read_usage",
                            lambda *a, **k: reading)

    def test_pools_become_distinctly_keyed_windows(self, tmp_path, monkeypatch):
        (tmp_path / "brain").mkdir()
        now = time.time()
        self._stub(monkeypatch, {"windows": [
            {"key": "weekly", "group": "gemini_models",
             "group_label": "Gemini Models", "remaining": 68.0,
             "resets_at": now + 129 * 3600, "duration_minutes": 10080},
            {"key": "five_hour", "group": "gemini_models",
             "group_label": "Gemini Models", "remaining": 9.6,
             "resets_at": now + 1.9 * 3600, "duration_minutes": 300},
            {"key": "weekly", "group": "claude_and_gpt_models",
             "group_label": "Claude and GPT models", "remaining": 0.0,
             "resets_at": now + 29 * 3600, "duration_minutes": 10080},
        ], "captured_at": now, "source": "antigravity-cli-usage"})
        snap = AntigravityProvider(data_dir=str(tmp_path)).probe(
            _account(tmp_path), time.monotonic() + 5)
        assert snap.status == OK
        keys = [w.key for w in snap.windows]
        # Two "weekly" limits exist; a shared key would give ONE alert rule
        # authority over both, so each pool owns its own identity.
        assert len(set(keys)) == 3
        assert qualified_key(WEEKLY, "gemini_models") in keys
        assert all(base_key(k) in ("weekly", "five_hour") for k in keys)
        assert snap.provider_metadata["pools"] == [
            "Claude and GPT models", "Gemini Models"]

    def test_a_spent_pool_never_gates_another_pool(self, tmp_path, monkeypatch):
        """Claude/GPT weekly at 0% must not zero the Gemini 5h window."""
        (tmp_path / "brain").mkdir()
        now = time.time()
        self._stub(monkeypatch, {"windows": [
            {"key": "five_hour", "group": "gemini_models",
             "group_label": "Gemini Models", "remaining": 9.6,
             "resets_at": now + 1800, "duration_minutes": 300},
            {"key": "weekly", "group": "claude_and_gpt_models",
             "group_label": "Claude and GPT models", "remaining": 0.0,
             "resets_at": now + 29 * 3600, "duration_minutes": 10080},
        ], "captured_at": now, "source": "antigravity-cli-usage"})
        snap = AntigravityProvider(data_dir=str(tmp_path)).probe(
            _account(tmp_path), time.monotonic() + 5)
        gemini = next(w for w in resolved_windows(snap.windows)
                      if w.group == "gemini_models")
        assert gemini.gated_by is None
        assert abs(gemini.remaining_percent - 9.6) < 0.001

    def test_a_spent_weekly_still_gates_its_own_pool(self):
        """Within ONE pool the old rule stands: weekly 0% zeroes the 5h."""
        now = time.time()
        windows = [
            UsageWindow(qualified_key("five_hour", "p"), 300, True, 0, 100,
                        now + 900, group="p"),
            UsageWindow(qualified_key("weekly", "p"), 10080, True, 100, 0,
                        now + 86400, group="p"),
        ]
        five = next(w for w in gate_windows(windows)
                    if base_key(w.key) == "five_hour")
        assert five.gated_by == qualified_key("weekly", "p")
        assert five.remaining_percent == 0.0

    def test_a_silent_cli_falls_back_to_the_journal(self, tmp_path, monkeypatch):
        _clear_cache()
        now = time.time()
        _message(tmp_path, "conv-a", "m1", _REFUSAL.format(delay="3h"),
                 timestamp=_iso(now - 60), mtime=now - 60)
        self._stub(monkeypatch, {"error": ("cli_not_installed", "no agy")})
        snap = AntigravityProvider(data_dir=str(tmp_path)).probe(
            _account(tmp_path), time.monotonic() + 5)
        assert snap.status == OK
        assert snap.window(QUOTA).remaining_percent == 0.0
        assert snap.provider_metadata["capability"] == "antigravity-refusals"


class TestAntigravityJournalFallback:
    def test_discovery_needs_a_real_directory(self, tmp_path):
        assert _journal_provider(tmp_path / "missing").discover_accounts() == []

    def test_one_install_yields_one_account(self, tmp_path):
        (tmp_path / "brain").mkdir()
        accounts = _journal_provider(tmp_path).discover_accounts()
        assert len(accounts) == 1
        assert accounts[0].provider_id == "antigravity"
        assert accounts[0].display_name == "Antigravity"

    def test_an_active_refusal_reads_as_a_spent_window(self, tmp_path):
        _clear_cache()
        now = time.time()
        _message(tmp_path, "conv-a", "m1", _REFUSAL.format(delay="3h"),
                 timestamp=_iso(now - 60), mtime=now - 60)
        snap = _journal_provider(tmp_path).probe(
            _account(tmp_path), time.monotonic() + 5)
        assert snap.status == OK
        window = snap.window(QUOTA)
        assert window.remaining_percent == 0.0
        assert window.used_percent == 100.0
        assert window.resets_at_epoch > now
        # No duration is claimed: the message quotes only the delay left.
        assert window.duration_minutes is None

    def test_no_refusal_is_unknown_not_free(self, tmp_path):
        _clear_cache()
        (tmp_path / "brain").mkdir()
        snap = _journal_provider(tmp_path).probe(
            _account(tmp_path), time.monotonic() + 5)
        assert snap.status == UNAVAILABLE
        assert snap.error_code == "no_refusal_recorded"
        assert "CLI" in snap.error_summary
        assert all(not window.available for window in snap.windows)

    def test_a_long_expired_block_stops_being_reported(self, tmp_path):
        _clear_cache()
        now = time.time()
        age = RESET_GRACE_S + 7200
        _message(tmp_path, "conv-a", "m1", _REFUSAL.format(delay="1h"),
                 timestamp=_iso(now - age), mtime=now - age)
        snap = _journal_provider(tmp_path).probe(
            _account(tmp_path), time.monotonic() + 5)
        assert snap.status == UNAVAILABLE
        assert snap.error_code == "quota_unknown"

    def test_a_just_elapsed_block_is_still_reported_so_the_reset_can_fire(
            self, tmp_path):
        """The refill must be announceable before the state goes unknown."""
        _clear_cache()
        now = time.time()
        _message(tmp_path, "conv-a", "m1", _REFUSAL.format(delay="1h"),
                 timestamp=_iso(now - 3660), mtime=now - 3660)
        snap = _journal_provider(tmp_path).probe(
            _account(tmp_path), time.monotonic() + 5)
        assert snap.status == OK
        window = resolved_windows(snap.windows, now)[0]
        assert window.remaining_percent == 100.0
        assert window.assumed_full is True

    def test_an_expired_deadline_never_touches_the_disk(self, tmp_path):
        snap = _journal_provider(tmp_path).probe(
            _account(tmp_path), time.monotonic() - 1)
        assert snap.status == UNAVAILABLE
        assert snap.error_code == "deadline_exceeded"


class TestAntigravityRegistration:
    def test_the_service_registers_the_provider(self):
        from fastprompter.core.usage_limits.service import UsageLimitService
        service = UsageLimitService()
        try:
            assert "antigravity" in service._providers
        finally:
            service.shutdown()

    def test_the_vendor_has_its_own_reset_colour(self):
        color = provider_reset_color("antigravity")
        assert color is not None
        r, g, b = (int(color[i:i + 2], 16) for i in (1, 3, 5))
        assert b > g and r > g, color      # violet: blue+red over green


class TestAntigravitySourceStatus:
    def test_reports_a_live_block(self, tmp_path):
        _clear_cache()
        now = time.time()
        _message(tmp_path, "conv-a", "m1", _REFUSAL.format(delay="5h"),
                 timestamp=_iso(now - 60), mtime=now - 60)
        state = source_status(str(tmp_path), now=now)
        assert state["installed"] is True
        assert state["blocked_until"] > now

    def test_reports_a_missing_install_without_raising(self, tmp_path):
        state = source_status(str(tmp_path / "missing"), now=time.time())
        assert state["installed"] is False
        assert state["blocked_until"] is None


class TestQuietProvidersAreNotFailures:
    """A provider with nothing to say must not light the header's ``!``."""

    def test_expected_quiet_codes_are_declared(self):
        from fastprompter.core.usage_limits.model import EXPECTED_QUIET_CODES
        assert "no_refusal_recorded" in EXPECTED_QUIET_CODES
        assert "quota_unknown" in EXPECTED_QUIET_CODES


def _account(directory):
    return AR(provider_id="antigravity", stable_id="one",
              display_name="Antigravity", source_kind="test",
              source_path=str(directory))


def _iso(epoch: float) -> str:
    import datetime
    return datetime.datetime.fromtimestamp(
        epoch, datetime.UTC).strftime("%Y-%m-%dT%H:%M:%S.%f000Z")
