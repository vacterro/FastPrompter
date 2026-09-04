"""Tests for AI Limits multi-level troubleshooting and auto-healing."""

import os
import unittest
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication, QWidget

from fastprompter.core.usage_limits import cli_tools, troubleshooter
from fastprompter.core.usage_limits.model import (
    FIVE_HOUR,
    OK,
    AccountRef,
    UsageSnapshot,
    UsageWindow,
)
from fastprompter.core.usage_limits.providers import (
    antigravity as agy_prov,
)
from fastprompter.core.usage_limits.providers import (
    claude as claude_prov,
)
from fastprompter.core.usage_limits.providers import (
    codex as codex_prov,
)
from fastprompter.core.usage_limits.providers import (
    zcode as zcode_prov,
)


class TestCliToolsLogin(unittest.TestCase):
    def test_login_subcommands_defined(self):
        self.assertEqual(cli_tools.LOGIN_SUBCOMMANDS.get("codex"), "login")
        self.assertEqual(cli_tools.LOGIN_SUBCOMMANDS.get("claude"), "login")
        self.assertEqual(cli_tools.LOGIN_SUBCOMMANDS.get("antigravity"), "auth login")

    def test_launch_login_missing_binary_raises(self):
        with patch.object(cli_tools, "resolve_binary", return_value=""):
            with self.assertRaises(ValueError):
                cli_tools.launch_login("codex")

    def test_launch_login_spawns_console(self):
        with patch.object(cli_tools, "resolve_binary", return_value=r"C:\bin\codex.exe"):
            with patch.object(cli_tools.os, "name", "nt"):
                with patch("subprocess.Popen") as mock_popen:
                    cli_tools.launch_login("codex")
                    self.assertTrue(mock_popen.called)
                    args = mock_popen.call_args[0][0]
                    self.assertIn("-NoExit", args)
                    self.assertTrue(any("C:\\bin\\codex.exe" in a for a in args))
                    self.assertTrue(any("login" in a for a in args))


class TestCodexSourceStatus(unittest.TestCase):
    def test_codex_source_status_no_auth(self, tmp_path=None):
        with patch.object(codex_prov, "_home_dir", return_value=None):
            with patch("fastprompter.core.usage_limits.cli_tools.resolve_binary", return_value=""):
                status = codex_prov.source_status()
                self.assertFalse(status["auth_found"])
                self.assertFalse(status["cli_installed"])

    def test_codex_source_status_with_auth(self, tmp_path=None):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as td:
            home = Path(td)
            codex_dir = home / ".codex"
            codex_dir.mkdir()
            (codex_dir / "auth.json").write_text('{"token": "test"}', encoding="utf-8")

            with patch.object(codex_prov, "_home_dir", return_value=home):
                with patch("fastprompter.core.usage_limits.cli_tools.resolve_binary", return_value="/bin/codex"):
                    status = codex_prov.source_status()
                    self.assertTrue(status["auth_found"])
                    self.assertTrue(status["logged_in"])
                    self.assertTrue(status["cli_installed"])
                    self.assertEqual(len(status["homes"]), 1)


class TestCandidatePaths(unittest.TestCase):
    def test_antigravity_candidate_dirs(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as td:
            mock_home = Path(td)
            cand = mock_home / ".gemini" / "antigravity"
            cand.mkdir(parents=True)
            with patch.dict(os.environ, {"USERPROFILE": str(mock_home), "HOME": str(mock_home)}):
                candidates = agy_prov.candidate_data_dirs()
                self.assertIn(str(cand), candidates)

    def test_zcode_candidate_configs(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as td:
            mock_home = Path(td)
            cand = mock_home / ".zcode" / "v2" / "config.json"
            cand.parent.mkdir(parents=True)
            cand.write_text("{}", encoding="utf-8")
            with patch.dict(os.environ, {"USERPROFILE": str(mock_home), "HOME": str(mock_home)}):
                candidates = zcode_prov.candidate_config_paths()
                self.assertIn(str(cand), candidates)


class TestTroubleshooterDiagnosis(unittest.TestCase):
    def test_diagnose_codex_needs_install(self):
        with patch.object(codex_prov, "source_status", return_value={"cli_installed": False, "auth_found": False}):
            diag = troubleshooter.diagnose_vendor("codex")
            self.assertEqual(diag["status_code"], "needs_install")
            self.assertFalse(diag["ready"])
            self.assertEqual(len(diag["manual_actions"]), 1)
            self.assertEqual(diag["manual_actions"][0]["action"], "install")

    def test_diagnose_codex_needs_login(self):
        with patch.object(codex_prov, "source_status", return_value={"cli_installed": True, "auth_found": False, "homes": []}):
            diag = troubleshooter.diagnose_vendor("codex")
            self.assertEqual(diag["status_code"], "needs_login")
            self.assertFalse(diag["ready"])
            self.assertEqual(len(diag["manual_actions"]), 1)
            self.assertEqual(diag["manual_actions"][0]["action"], "login")

    def test_diagnose_claude_stale_bridge(self):
        with patch("fastprompter.core.usage_limits.claude_statusline.bridge_status", return_value={"stale": True, "connected": True}):
            with patch.object(claude_prov, "source_status", return_value={"cli_installed": True}):
                diag = troubleshooter.diagnose_vendor("claude")
                self.assertEqual(diag["status_code"], "stale_bridge")
                self.assertIn("repair_bridge", diag["auto_heals_available"])

    def test_diagnose_zcode_disabled_with_plans(self):
        with patch.object(zcode_prov, "source_status", return_value={
            "config_found": True,
            "plans": [{"id": "p1", "label": "Coding Plan", "has_key": True, "endpoint": "https://api.z.ai"}]
        }):
            diag = troubleshooter.diagnose_vendor("zcode", {"limit_zcode_enabled": "False"})
            self.assertEqual(diag["status_code"], "disabled_with_plans")
            self.assertIn("enable_zcode", diag["auto_heals_available"])

    def test_diagnose_all(self):
        res = troubleshooter.diagnose_all()
        for k in ("codex", "claude", "antigravity", "zcode"):
            self.assertIn(k, res)
            self.assertIn("ready", res[k])


class TestTroubleshooterAutoHeal(unittest.TestCase):
    def test_auto_heal_enables_zcode_and_gauges(self):
        data = {"limit_zcode_enabled": "False", "limit_gauges": "False"}
        with patch.object(zcode_prov, "source_status", return_value={
            "config_found": True,
            "plans": [{"id": "p1", "label": "GLM Plan", "has_key": True, "endpoint": "https://api.z.ai"}]
        }):
            res = troubleshooter.auto_heal_all(data)
            self.assertEqual(data["limit_zcode_enabled"], "True")
            self.assertEqual(data["limit_gauges"], "True")
            self.assertTrue(any("ZCode" in h for h in res["healed"]))
            self.assertTrue(any("header" in h for h in res["healed"]))

    def test_auto_heal_repairs_stale_claude_bridge(self):
        data = {}
        with patch("fastprompter.core.usage_limits.claude_statusline.bridge_status", return_value={"stale": True, "connected": True}):
            with patch("fastprompter.core.usage_limits.claude_statusline.install_bridge") as mock_install:
                res = troubleshooter.auto_heal_all(data)
                self.assertTrue(mock_install.called)
                self.assertTrue(any("Claude" in h for h in res["healed"]))


class _MockService:
    def __init__(self, accounts=(), snapshots=None):
        self._state = MagicMock()
        self._state.accounts = list(accounts)
        self._state.snapshots = dict(snapshots or {})
        self._state.status = "IDLE"
        self.reconfigured = False
        self.discovered = False
        self.refreshed = False

    @property
    def state_copy(self):
        return self._state

    def reconfigure(self, data):
        self.reconfigured = True

    def discover(self):
        self.discovered = True

    def refresh(self):
        self.refreshed = True

    def add_callback(self, cb):
        pass


class _MockMainWin(QWidget):
    def __init__(self, data=None, service=None):
        super().__init__()
        self.data = data if data is not None else {}
        self.limit_service = service
        self._theme_cache = {}
        self.limit_gauges = MagicMock()
        self.sound_manager = MagicMock()
        self.sound_manager.get_available_sounds.return_value = []

    def mark_dirty(self, domain=None):
        pass

    def _toggle_claude_limit_bridge(self):
        pass

    def _check_limit_notifications(self):
        pass


class TestLimitSettingsDialogTroubleshootingUI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def test_onboarding_card_shown_when_no_accounts(self):
        from fastprompter.ui.limit_settings_dialog import LimitSettingsDialog
        data = {}
        service = _MockService(accounts=[])
        main_win = _MockMainWin(data, service)
        dlg = LimitSettingsDialog(main_win)
        dlg._suppress_dialogs_for_tests = True

        self.assertFalse(dlg.card_onboarding.isHidden())
        self.assertTrue(dlg.overview_scroll.isHidden())
        self.assertIn("Auto-Detect", dlg.lbl_overview_status.text())

    def test_onboarding_card_hidden_when_accounts_exist(self):
        from fastprompter.ui.limit_settings_dialog import LimitSettingsDialog
        account = AccountRef("codex", "c1", "Codex 1", "test", "path")
        snap = UsageSnapshot(account, OK, [UsageWindow(FIVE_HOUR, 300, True, 10, 90, None)])
        service = _MockService(accounts=[account], snapshots={account.key: snap})
        main_win = _MockMainWin({}, service)
        dlg = LimitSettingsDialog(main_win)

        self.assertTrue(dlg.card_onboarding.isHidden())
        self.assertFalse(dlg.overview_scroll.isHidden())

    def test_sources_tab_has_troubleshoot_and_login_buttons(self):
        from fastprompter.ui.limit_settings_dialog import LimitSettingsDialog
        service = _MockService(accounts=[])
        main_win = _MockMainWin({}, service)
        dlg = LimitSettingsDialog(main_win)
        dlg._suppress_dialogs_for_tests = True

        self.assertTrue(hasattr(dlg, "btn_auto_troubleshoot"))
        self.assertTrue(hasattr(dlg, "btn_codex_login"))
        self.assertTrue(hasattr(dlg, "btn_claude_login"))
        self.assertTrue(hasattr(dlg, "btn_antigravity_login"))
        self.assertTrue(hasattr(dlg, "btn_zcode_quick_enable"))

    def test_run_auto_troubleshoot_triggers_healing(self):
        from fastprompter.ui.limit_settings_dialog import LimitSettingsDialog
        service = _MockService(accounts=[])
        main_win = _MockMainWin({}, service)
        dlg = LimitSettingsDialog(main_win)
        dlg._suppress_dialogs_for_tests = True

        with patch("fastprompter.core.usage_limits.troubleshooter.auto_heal_all", return_value={
            "healed": ["Repaired bridge"],
            "remaining_issues": [],
            "accounts_count": 2,
            "diagnostics": {},
        }) as mock_heal:
            dlg._run_auto_troubleshoot()
            self.assertTrue(mock_heal.called)
            self.assertIn("Auto-heal: 1 fix(es)", dlg.lbl_troubleshoot_status.text())

