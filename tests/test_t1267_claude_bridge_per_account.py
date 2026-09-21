"""T-1267: the Claude status-line bridge is controlled PER ACCOUNT/HOME.

The low-level bridge API (``bridge_status`` / ``install_bridge`` /
``uninstall_bridge``) and the provider (per-home discovery, per-home
``cache_path_for_dir(home)/fastprompter-rate-limits.json``) were already
per-account; the Settings dialog was not -- its one Connect/Disconnect
button called the bridge API with no directory, so every action landed on
the default ``~/.claude`` home no matter which account the user meant.

The contract proven here (handoff matrix A-J): every discovered Claude
account gets its own bridge row, every action carries that account's
EXACT home, a sibling home's settings.json / statusLine / sidecar backup
/ rate-limit cache is never touched by another account's action, a
malformed home reports its own configuration error, and every state
survives a restart through its own home on disk.
"""

from __future__ import annotations

import json
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from fastprompter.core.usage_limits.claude_statusline import (  # noqa: E402
    BRIDGE_CONFIG_NAME,
    cache_path_for_dir,
    install_bridge,
)
from fastprompter.core.usage_limits.providers.claude import (  # noqa: E402
    ClaudeProvider,
)
from fastprompter.core.usage_limits.service import (  # noqa: E402
    apply_display_names,
)

pytest.importorskip("PyQt6.QtWidgets")

from PyQt6.QtWidgets import QApplication, QWidget  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture()
def fake_home(tmp_path, monkeypatch):
    """A HOME carrying the default Claude account and nothing else."""
    default = tmp_path / ".claude"
    default.mkdir()
    (default / "settings.json").write_text("{}", encoding="utf-8")
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setenv("HOME", str(tmp_path))
    return tmp_path


def _home(root, name, *, status_line=None):
    path = root / name
    path.mkdir(exist_ok=True)
    settings = {}
    if status_line is not None:
        settings["statusLine"] = status_line
    (path / "settings.json").write_text(
        json.dumps(settings, indent=2), encoding="utf-8")
    return path


def _settings(home):
    with open(os.path.join(str(home), "settings.json"),
              encoding="utf-8") as handle:
        return json.load(handle)


def _write_settings(home, value):
    with open(os.path.join(str(home), "settings.json"), "w",
              encoding="utf-8") as handle:
        json.dump(value, handle, indent=2)


def _accounts(fake_home, sibling_name=".claude-work"):
    """The real discovery result for a default home plus one sibling."""
    _home(fake_home, sibling_name)
    accounts = apply_display_names(
        ClaudeProvider(use_cli=False).discover_accounts())
    assert len(accounts) == 2
    return accounts


class _State:
    def __init__(self, accounts, snapshots=None):
        self.accounts = list(accounts)
        self.snapshots = dict(snapshots or {})
        self.status = "IDLE"


class _Service:
    def __init__(self, state):
        self._state = state

    @property
    def state_copy(self):
        return self._state

    def reconfigure_async(self, data):
        pass


class _MainWin(QWidget):
    def __init__(self, service, data=None):
        super().__init__()
        from unittest.mock import MagicMock

        self.data = dict(data or {})
        self.limit_service = service
        self._theme_cache = {"raw_colors": {}}
        self.limit_gauges = MagicMock()
        self.limit_gauges.get_available_sounds.return_value = []
        self.sound_manager = MagicMock()
        self.sound_manager.get_available_sounds.return_value = []

    def mark_dirty(self, domain=None):
        pass

    def _toggle_claude_limit_bridge(self, directory=None):
        pass

    def _check_limit_notifications(self):
        pass


def _dialog(qapp, accounts):
    from fastprompter.ui.limit_settings_dialog import LimitSettingsDialog

    service = _Service(_State(accounts))
    main_win = _MainWin(service)
    dlg = LimitSettingsDialog(main_win)
    dlg._suppress_dialogs_for_tests = True
    dlg._refresh_claude_status()
    return dlg, main_win


def _row(dlg, home):
    return dlg._claude_bridge_rows[str(home)]


# ---------------------------------------------------------------------------
# A -- the single-account machine keeps the historical behaviour
# ---------------------------------------------------------------------------


class TestSingleAccountHistoricalBehaviour:
    def test_one_account_keeps_the_aggregate_row_and_acts_on_its_home(
            self, qapp, fake_home):
        accounts = apply_display_names(
            ClaudeProvider(use_cli=False).discover_accounts())
        assert len(accounts) == 1
        default_home = accounts[0].source_path
        dlg, main_win = _dialog(qapp, accounts)
        try:
            assert dlg.claude_bridge_rows_box.isHidden()
            assert not dlg._claude_bridge_rows
            assert not dlg.btn_claude.isHidden()
            assert dlg.btn_claude.text() == "Connect Claude Code"

            dlg._toggle_claude()

            settings = _settings(default_home)
            assert "--claude-statusline-bridge" in str(
                settings.get("statusLine", {}).get("command", ""))
            dlg._refresh_claude_status()
            assert dlg.btn_claude.text() == "Disconnect Claude Code"
        finally:
            dlg.deleteLater()
            main_win.deleteLater()


# ---------------------------------------------------------------------------
# B..E -- per-account rows and action isolation
# ---------------------------------------------------------------------------


class TestPerAccountRows:
    def test_two_homes_report_independent_statuses(self, qapp, fake_home):
        first, second = _accounts(fake_home)
        home_a, home_b = first.source_path, second.source_path
        install_bridge(home_a)                       # A connected, B not
        dlg, main_win = _dialog(qapp, [first, second])
        try:
            assert not dlg.claude_bridge_rows_box.isHidden()
            assert set(dlg._claude_bridge_rows) == {home_a, home_b}
            row_a, row_b = _row(dlg, home_a), _row(dlg, home_b)
            assert "Connected · waiting for first Claude API response" \
                in row_a["label"].text()
            assert "Not connected" in row_b["label"].text()
            assert row_a["button"].text() == "Disconnect Claude Code"
            assert row_b["button"].text() == "Connect Claude Code"
            # each row names its own account and its own home
            assert first.display_name in row_a["label"].text()
            assert home_a in row_a["label"].text()
            assert home_b in row_b["label"].text()
        finally:
            dlg.deleteLater()
            main_win.deleteLater()

    def test_connect_b_touches_only_b(self, qapp, fake_home):
        first, second = _accounts(fake_home)
        home_a, home_b = first.source_path, second.source_path
        install_bridge(home_a)
        before_a = _settings(home_a)
        dlg, main_win = _dialog(qapp, [first, second])
        try:
            dlg._toggle_claude_for_home(home_b)
            assert "--claude-statusline-bridge" in str(
                _settings(home_b)["statusLine"]["command"])
            assert _settings(home_a) == before_a, (
                "connecting account B must not rewrite account A's settings")
            assert _row(dlg, home_b)["button"].text() == \
                "Disconnect Claude Code"
            assert _row(dlg, home_a)["button"].text() == \
                "Disconnect Claude Code"
        finally:
            dlg.deleteLater()
            main_win.deleteLater()

    def test_disconnect_b_restores_only_b_original_statusline(
            self, qapp, fake_home):
        first, second = _accounts(fake_home, ".claude-work")
        home_a, home_b = first.source_path, second.source_path
        original_b = {"type": "command", "command": "my-own-line.sh"}
        _write_settings(home_b, {"statusLine": original_b})
        install_bridge(home_a)
        install_bridge(home_b)
        before_a = _settings(home_a)
        dlg, main_win = _dialog(qapp, [first, second])
        try:
            dlg._toggle_claude_for_home(home_b)      # connected -> disconnect
            settings_b = _settings(home_b)
            assert settings_b.get("statusLine") == original_b, (
                "B's original statusLine must come back EXACTLY")
            assert _settings(home_a) == before_a, (
                "disconnecting account B must not touch account A")
            # each home owns its own sidecar: B's is consumed, A's survives
            assert not os.path.isfile(
                os.path.join(home_b, BRIDGE_CONFIG_NAME))
            assert os.path.isfile(os.path.join(home_a, BRIDGE_CONFIG_NAME))
        finally:
            dlg.deleteLater()
            main_win.deleteLater()

    def test_disconnect_b_without_previous_statusline_removes_the_key(
            self, qapp, fake_home):
        first, second = _accounts(fake_home)
        home_b = second.source_path
        install_bridge(home_b)
        dlg, main_win = _dialog(qapp, [first, second])
        try:
            dlg._toggle_claude_for_home(home_b)
            assert "statusLine" not in _settings(home_b)
        finally:
            dlg.deleteLater()
            main_win.deleteLater()

    def test_stale_b_reconnect_repairs_b_only(self, qapp, fake_home):
        from fastprompter.core.usage_limits.claude_statusline import (
            bridge_status,
        )

        first, second = _accounts(fake_home)
        home_a, home_b = first.source_path, second.source_path
        install_bridge(home_a)
        install_bridge(home_b)
        command_a_at_install = _settings(home_a)["statusLine"]["command"]
        stale = dict(_settings(home_b))
        stale["statusLine"] = {
            "type": "command",
            "command": "python X:/gone/launcher.pyw --claude-statusline-bridge",
        }
        _write_settings(home_b, stale)

        dlg, main_win = _dialog(qapp, [first, second])
        try:
            assert bridge_status(home_b)["stale"] is True
            assert _row(dlg, home_b)["button"].text() == \
                "Reconnect Claude Code"

            dlg._toggle_claude_for_home(home_b)

            repaired = str(_settings(home_b)["statusLine"]["command"])
            expected = bridge_status(home_b)["expected_command"]
            assert repaired.casefold() == expected.casefold()
            assert _settings(home_a)["statusLine"]["command"] == \
                command_a_at_install, (
                    "repairing B must not rewrite A's working command")
        finally:
            dlg.deleteLater()
            main_win.deleteLater()


# ---------------------------------------------------------------------------
# F..G -- per-home caches stay per-home, with and without the CLI
# ---------------------------------------------------------------------------


def _write_cache(home, used):
    from fastprompter.core.usage_limits.claude_statusline import (
        capture_payload,
    )

    assert capture_payload(
        {"rate_limits": {
            "five_hour": {"used_percentage": used, "resets_at": 1_900_000_000},
            "seven_day": {"used_percentage": used + 10},
        }},
        str(home),
    ) is True


class TestPerHomeCaches:
    def test_a_cache_b_absent_reports_each_home_truthfully(
            self, qapp, fake_home):
        first, second = _accounts(fake_home)
        home_a, home_b = first.source_path, second.source_path
        install_bridge(home_a)
        install_bridge(home_b)
        _write_cache(home_a, 12.0)

        dlg, main_win = _dialog(qapp, [first, second])
        try:
            assert "structured limits received" in \
                _row(dlg, home_a)["label"].text()
            assert "waiting for first Claude API response" in \
                _row(dlg, home_b)["label"].text()
        finally:
            dlg.deleteLater()
            main_win.deleteLater()

    def test_the_provider_reads_each_account_through_its_own_cache(
            self, fake_home):
        first, second = _accounts(fake_home)
        home_a, home_b = first.source_path, second.source_path
        install_bridge(home_a)
        install_bridge(home_b)
        _write_cache(home_a, 12.0)

        provider = ClaudeProvider(use_cli=False)
        reading_a = provider._bridge_reading(first)
        reading_b = provider._bridge_reading(second)
        # A: real numbers from A's own cache file
        assert reading_a["windows"]["five_hour"]["used"] == 12.0
        assert reading_a["cache"] == str(cache_path_for_dir(home_a))
        # B: truthfully waiting -- nothing invented
        assert reading_b["error"][0] == "waiting_for_statusline"

    def test_cli_unavailable_keeps_both_accounts_readable(
            self, fake_home):
        first, second = _accounts(fake_home)
        home_a, home_b = first.source_path, second.source_path
        install_bridge(home_a)
        install_bridge(home_b)
        _write_cache(home_a, 12.0)
        _write_cache(home_b, 77.0)

        provider = ClaudeProvider(use_cli=False)
        reading_a = provider._bridge_reading(first)
        reading_b = provider._bridge_reading(second)
        assert reading_a["cache"] == str(cache_path_for_dir(home_a))
        assert reading_a["windows"]["five_hour"]["used"] == 12.0
        assert reading_b["cache"] == str(cache_path_for_dir(home_b))
        assert reading_b["windows"]["five_hour"]["used"] == 77.0


# ---------------------------------------------------------------------------
# H..J -- malformed homes, stable bindings, restart
# ---------------------------------------------------------------------------


class TestRobustness:
    def test_malformed_b_settings_is_b_error_only(self, qapp, fake_home):
        first, second = _accounts(fake_home)
        home_a, home_b = first.source_path, second.source_path
        install_bridge(home_a)
        with open(os.path.join(home_b, "settings.json"), "w",
                  encoding="utf-8") as handle:
            handle.write("{not json")

        dlg, main_win = _dialog(qapp, [first, second])
        try:
            assert "Configuration error" in _row(dlg, home_b)["label"].text()
            assert "Configuration error" not in _row(dlg, home_a)["label"].text()
            assert "Connected" in _row(dlg, home_a)["label"].text()
        finally:
            dlg.deleteLater()
            main_win.deleteLater()

    def test_refresh_keeps_actions_bound_to_the_same_homes(
            self, qapp, fake_home):
        first, second = _accounts(fake_home)
        home_a, home_b = first.source_path, second.source_path
        install_bridge(home_a)
        settings_a_before = _settings(home_a)
        dlg, main_win = _dialog(qapp, [first, second])
        try:
            bound_before = set(dlg._claude_bridge_rows)
            # a plain status refresh (profile/settings refresh path) must
            # not rebind or drop any action
            dlg._refresh_claude_status()
            dlg._refresh_claude_status()
            assert set(dlg._claude_bridge_rows) == bound_before

            dlg._toggle_claude_for_home(home_b)
            assert "--claude-statusline-bridge" in str(
                _settings(home_b)["statusLine"]["command"])
            assert _settings(home_a) == settings_a_before, (
                "the still-bound A action must keep targeting A only")
        finally:
            dlg.deleteLater()
            main_win.deleteLater()

    def test_a_vanished_home_loses_its_row_without_touching_the_rest(
            self, qapp, fake_home, monkeypatch):
        first, second = _accounts(fake_home)
        home_a, home_b = first.source_path, second.source_path
        install_bridge(home_a)
        dlg, main_win = _dialog(qapp, [first, second])
        try:
            assert home_b in dlg._claude_bridge_rows
            # the roster drops B (discovery sees only A again)
            dlg._sync_claude_bridge_rows([first])
            assert set(dlg._claude_bridge_rows) == {home_a}
            # A's row still works and still targets A
            dlg._toggle_claude_for_home(home_a)     # connected -> disconnect
            assert "statusLine" not in _settings(home_a)
            assert os.path.isfile(os.path.join(home_b, "settings.json"))
        finally:
            dlg.deleteLater()
            main_win.deleteLater()

    def test_restart_redisCOVERS_each_homes_state(self, qapp, fake_home):
        first, second = _accounts(fake_home)
        home_a, home_b = first.source_path, second.source_path
        install_bridge(home_a)
        _write_cache(home_a, 5.0)
        dlg1, main1 = _dialog(qapp, [first, second])
        dlg1.deleteLater()
        main1.deleteLater()

        dlg2, main2 = _dialog(qapp, [first, second])
        try:
            assert "structured limits received" in \
                _row(dlg2, home_a)["label"].text()
            assert "Not connected" in _row(dlg2, home_b)["label"].text()
        finally:
            dlg2.deleteLater()
            main2.deleteLater()


# ---------------------------------------------------------------------------
# the main-window toggle carries the directory explicitly
# ---------------------------------------------------------------------------


class TestMainWindowToggleCarriesDirectory:
    def test_toggle_with_directory_never_falls_back_to_default(
            self, fake_home):
        from fastprompter.core.usage_limits.claude_statusline import (
            bridge_status,
        )

        default = fake_home / ".claude"
        other = _home(fake_home, ".claude-other")
        from fastprompter.main import FastPrompter

        FastPrompter._toggle_claude_limit_bridge(
            FastPrompter, str(other))
        assert bridge_status(str(other))["connected"] is True
        assert bridge_status(str(default))["connected"] is False

        FastPrompter._toggle_claude_limit_bridge(
            FastPrompter, str(other))
        assert bridge_status(str(other))["connected"] is False
        assert "statusLine" not in _settings(str(other))
