"""Tests for picking up agent installs/updates while FastPrompter is running.

Accounts used to be discovered exactly once, at construction. That was fine
while the only sources were files that had always been there — and wrong the
moment the settings dialog grew a button that installs a CLI, because the app
would keep reporting "not installed" until a restart.
"""

from __future__ import annotations

import time

from fastprompter.core.usage_limits.model import AccountRef as AR
from fastprompter.core.usage_limits.service import (
    REDISCOVER_EVERY_S,
    UsageLimitService,
)


class _Provider:
    """A provider whose account list the test can change mid-run."""

    provider_id = "codex"

    def __init__(self, accounts):
        self.accounts = list(accounts)
        self.discoveries = 0

    def discover_accounts(self):
        self.discoveries += 1
        return list(self.accounts)

    def probe(self, account, deadline):
        return None

    def shutdown(self):
        pass


def _account(stable_id):
    return AR(provider_id="codex", stable_id=stable_id,
              display_name=stable_id, source_kind="test")


def _service_with(provider):
    service = UsageLimitService()
    service._providers = {"codex": provider}
    provider.discoveries = 0
    service._discover()
    return service


class TestPeriodicRediscovery:
    def test_a_new_account_appears_without_a_restart(self):
        provider = _Provider([_account("a")])
        service = _service_with(provider)
        try:
            assert [a.stable_id for a in service.accounts] == ["a"]
            provider.accounts.append(_account("b"))
            # Pretend the interval elapsed rather than sleeping through it.
            with service._lock:
                service._state.last_discovery = (
                    time.monotonic() - REDISCOVER_EVERY_S - 1)
            service._rediscover_if_due()
            assert sorted(a.stable_id for a in service.accounts) == ["a", "b"]
        finally:
            service.shutdown()

    def test_it_does_not_rescan_on_every_sweep(self):
        provider = _Provider([_account("a")])
        service = _service_with(provider)
        try:
            before = provider.discoveries
            for _ in range(5):
                service._rediscover_if_due()
            assert provider.discoveries == before
        finally:
            service.shutdown()

    def test_rediscovery_keeps_known_readings(self):
        """Unlike reconfigure: the provider set did not change.

        Dropping snapshots here would blink every gauge back to "not probed
        yet" every five minutes for no reason.
        """
        from fastprompter.core.usage_limits.model import OK, UsageSnapshot
        provider = _Provider([_account("a")])
        service = _service_with(provider)
        try:
            key = _account("a").key
            with service._lock:
                service._state.snapshots[key] = UsageSnapshot(
                    account=_account("a"), status=OK, windows=[],
                    fetched_at=time.time())
                service._state.last_discovery = (
                    time.monotonic() - REDISCOVER_EVERY_S - 1)
            service._rediscover_if_due()
            assert key in service.snapshots
        finally:
            service.shutdown()

    def test_a_closed_service_never_rescans(self):
        provider = _Provider([_account("a")])
        service = _service_with(provider)
        service.shutdown()
        before = provider.discoveries
        service._rediscover_if_due()
        assert provider.discoveries == before

    def test_it_notifies_only_when_the_roster_actually_changed(self):
        provider = _Provider([_account("a")])
        service = _service_with(provider)
        fired = []
        service.add_callback(lambda: fired.append(1))
        try:
            with service._lock:
                service._state.last_discovery = (
                    time.monotonic() - REDISCOVER_EVERY_S - 1)
            service._rediscover_if_due()
            assert fired == []           # same accounts, no repaint needed
            provider.accounts.append(_account("b"))
            with service._lock:
                service._state.last_discovery = (
                    time.monotonic() - REDISCOVER_EVERY_S - 1)
            service._rediscover_if_due()
            assert fired == [1]
        finally:
            service.shutdown()


class TestBridgeStaleness:
    """A bridge command records absolute paths; those go stale silently."""

    def _settings(self, directory, command):
        import json
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "settings.json").write_text(
            json.dumps({"statusLine": {"type": "command",
                                       "command": command}}),
            encoding="utf-8")

    def test_a_command_from_another_install_is_flagged_stale(self, tmp_path):
        from fastprompter.core.usage_limits.claude_statusline import (
            BRIDGE_ARG,
            bridge_status,
        )
        directory = tmp_path / ".claude"
        self._settings(directory,
                       f"D:\\gone\\python.exe D:\\gone\\FastPrompter.pyw {BRIDGE_ARG}")
        status = bridge_status(directory)
        assert status["connected"] is True
        assert status["stale"] is True
        assert status["expected_command"]

    def test_the_current_command_is_not_stale(self, tmp_path):
        from fastprompter.core.usage_limits.claude_statusline import (
            bridge_status,
            current_bridge_command,
        )
        directory = tmp_path / ".claude"
        self._settings(directory, current_bridge_command())
        status = bridge_status(directory)
        assert status["connected"] is True
        assert status["stale"] is False

    def test_case_alone_is_not_staleness(self, tmp_path):
        """Windows hands paths back in whatever case the caller used."""
        from fastprompter.core.usage_limits.claude_statusline import (
            bridge_status,
            current_bridge_command,
        )
        directory = tmp_path / ".claude"
        self._settings(directory, current_bridge_command().upper())
        assert bridge_status(directory)["stale"] is False

    def test_an_unconnected_bridge_is_not_stale(self, tmp_path):
        from fastprompter.core.usage_limits.claude_statusline import bridge_status
        directory = tmp_path / ".claude"
        self._settings(directory, "my-own-statusline --json")
        status = bridge_status(directory)
        assert status["connected"] is False
        assert status["stale"] is False

    def test_reinstalling_over_a_stale_bridge_keeps_the_users_backup(
            self, tmp_path):
        """Repair must not cost the user their original status line."""
        import json

        from fastprompter.core.usage_limits.claude_statusline import (
            BRIDGE_ARG,
            BRIDGE_CONFIG_NAME,
            bridge_status,
            install_bridge,
            uninstall_bridge,
        )
        directory = tmp_path / ".claude"
        directory.mkdir()
        original = {"type": "command", "command": "my-old-line --json"}
        (directory / "settings.json").write_text(
            json.dumps({"statusLine": original}), encoding="utf-8")
        install_bridge(directory, command=f"D:\\old\\python.exe x {BRIDGE_ARG}")
        assert bridge_status(directory)["stale"] is True
        # Repair: same call, current paths.
        install_bridge(directory)
        assert bridge_status(directory)["stale"] is False
        sidecar = json.loads(
            (directory / BRIDGE_CONFIG_NAME).read_text(encoding="utf-8"))
        assert sidecar["original_status_line"] == original
        uninstall_bridge(directory)
        restored = json.loads(
            (directory / "settings.json").read_text(encoding="utf-8"))
        assert restored == {"statusLine": original}
