"""Tests for the CLI-backed quota sources — the most reliable ones we have.

Three things must hold, and each has burned a real defect into the design:

* a CLI answer is parsed, never guessed: a line or bucket that does not parse
  produces no window rather than a plausible number;
* reading quota must not COST quota, must not block the GUI, and must not
  litter the vendor's own store with probe artefacts;
* a CLI that appears while FastPrompter is already running has to be picked up,
  because installing one is now a button in the settings dialog.

Nothing here executes a vendor CLI. The parsers are fed payloads captured from
the live tools (``claude`` 2.1.259, ``agy`` 1.1.25) and the runner is exercised
against a stub script, so the suite asserts on fixed facts instead of this
machine's quota, which rolls over every five hours.
"""

from __future__ import annotations

import datetime
import json
import os
import subprocess
import sys
import time

from fastprompter.core.usage_limits import cli_tools
from fastprompter.core.usage_limits.providers import _antigravity_cli, _claude_cli

# Captured verbatim from `claude -p "/usage"` on 2.1.259.
CLAUDE_USAGE_TEXT = """You are currently using your subscription to power your Claude Code usage

Current session: 65% used \u00b7 resets Sep 3, 4:49pm (Europe/Tallinn)
Current week (all models): 64% used \u00b7 resets Sep 8, 4:59pm (Europe/Tallinn)

What's contributing to your limits usage?
Approximate, based on local sessions on this machine \u2014 does not include other devices or claude.ai.

Last 24h \u00b7 1314 requests \u00b7 3 sessions
  97% of your usage was at >150k context
  Top skills: /anthropic-skills:caveman 1%
"""


class TestResolveBinary:
    def test_path_wins(self, tmp_path, monkeypatch):
        binary = tmp_path / "agy.exe"
        binary.write_text("", encoding="utf-8")
        monkeypatch.setattr(cli_tools.shutil, "which",
                            lambda name: str(binary))
        assert cli_tools.resolve_binary("antigravity") == str(binary)

    def test_the_installers_own_directory_is_the_fallback(self, tmp_path,
                                                          monkeypatch):
        """A CLI installed while FastPrompter runs is NOT on our PATH.

        Windows hands each process a PATH snapshot at launch, so the installer's
        PATH edit is invisible until a restart. Checking where the official
        installer puts the binary is what makes the settings-dialog install
        button work without one.
        """
        monkeypatch.setattr(cli_tools.shutil, "which", lambda name: None)
        home = tmp_path / "home"
        (home / "AppData" / "Local" / "agy" / "bin").mkdir(parents=True)
        landed = home / "AppData" / "Local" / "agy" / "bin" / "agy.exe"
        landed.write_text("", encoding="utf-8")
        monkeypatch.setenv("USERPROFILE", str(home))
        monkeypatch.setenv("HOME", str(home))
        assert cli_tools.resolve_binary("antigravity") == str(landed)

    def test_absent_everywhere_is_empty(self, tmp_path, monkeypatch):
        monkeypatch.setattr(cli_tools.shutil, "which", lambda name: None)
        monkeypatch.setenv("USERPROFILE", str(tmp_path))
        monkeypatch.setenv("HOME", str(tmp_path))
        assert cli_tools.resolve_binary("claude") == ""

    def test_every_installer_entry_is_complete(self):
        for tool in cli_tools.INSTALLERS:
            assert tool.install_command, tool.key
            assert tool.install_source, tool.key
            assert tool.install_target, tool.key
            # The published one-liners are all HTTPS; a plain-HTTP installer
            # command would be a downgrade nobody asked for.
            assert "http://" not in tool.install_command, tool.key


class TestRunCli:
    def _script(self, tmp_path, body):
        path = tmp_path / "stub.py"
        path.write_text(body, encoding="utf-8")
        return [sys.executable, str(path)]

    def test_captures_stdout(self, tmp_path):
        argv = self._script(tmp_path, "print('hello')")
        result = cli_tools.run_cli(argv, time.monotonic() + 20)
        assert result["ok"] is True
        assert result["stdout"].strip() == "hello"

    def test_a_nonzero_exit_reports_the_first_stderr_line(self, tmp_path):
        argv = self._script(
            tmp_path,
            "import sys; print('Not logged in', file=sys.stderr); sys.exit(3)")
        result = cli_tools.run_cli(argv, time.monotonic() + 20)
        assert result["ok"] is False
        assert "Not logged in" in result["error"]

    def test_an_expired_deadline_never_spawns(self, tmp_path):
        argv = self._script(tmp_path, "raise SystemExit('should not run')")
        result = cli_tools.run_cli(argv, time.monotonic() - 1)
        assert result == {"ok": False, "stdout": "", "error": "deadline_exceeded"}

    def test_a_hung_child_is_killed_at_the_deadline(self, tmp_path):
        argv = self._script(tmp_path, "import time; time.sleep(30)")
        started = time.perf_counter()
        result = cli_tools.run_cli(argv, time.monotonic() + 1.0)
        elapsed = time.perf_counter() - started
        assert result["error"] == "timeout"
        assert elapsed < 10, f"waited {elapsed:.1f}s past a 1s deadline"

    def test_a_missing_executable_is_reported_not_raised(self, tmp_path):
        result = cli_tools.run_cli(
            [str(tmp_path / "nope.exe")], time.monotonic() + 5)
        assert result["ok"] is False
        assert result["stdout"] == ""

    def test_no_shell_is_used(self, tmp_path):
        """An argument must never be reinterpreted by a shell."""
        argv = self._script(tmp_path, "import sys; print(sys.argv[1])")
        result = cli_tools.run_cli(argv + ["a & b | c"], time.monotonic() + 20)
        assert result["ok"] is True
        assert result["stdout"].strip() == "a & b | c"


class TestClaudeUsageParser:
    def test_reads_both_windows_with_their_resets(self):
        windows = _claude_cli.parse_usage_text(CLAUDE_USAGE_TEXT)
        assert set(windows) == {"five_hour", "weekly"}
        assert windows["five_hour"]["used"] == 65.0
        assert windows["weekly"]["used"] == 64.0
        assert windows["five_hour"]["resets_at"] is not None
        assert windows["weekly"]["resets_at"] > windows["five_hour"]["resets_at"]

    def test_the_reset_is_parsed_as_local_time(self):
        """The CLI renders local time and names the zone for the reader.

        Parsing it as UTC would shift every countdown by the offset, and the
        bundled build ships no tzdata to interpret the zone name with.
        """
        epoch = _claude_cli.parse_reset("Sep 3, 4:49pm",
                                        now=datetime.datetime(
                                            2026, 9, 3, 12, 0).timestamp())
        local = datetime.datetime.fromtimestamp(epoch)
        assert (local.month, local.day, local.hour, local.minute) == (9, 3, 16, 49)

    def test_a_bare_hour_has_no_minutes(self):
        epoch = _claude_cli.parse_reset("Sep 8, 5pm")
        assert datetime.datetime.fromtimestamp(epoch).minute == 0

    def test_an_explicit_year_is_honoured(self):
        epoch = _claude_cli.parse_reset("Jan 2, 2028, 9am")
        assert datetime.datetime.fromtimestamp(epoch).year == 2028

    def test_a_per_model_weekly_keeps_its_own_identity(self):
        """"Current week (Sonnet)" is a separate limit, not the weekly again."""
        windows = _claude_cli.parse_usage_text(
            "Current week (all models): 10% used \u00b7 resets Sep 8, 5pm\n"
            "Current week (Sonnet): 40% used \u00b7 resets Sep 8, 5pm\n")
        assert set(windows) == {"weekly", "weekly_sonnet"}
        assert windows["weekly_sonnet"]["used"] == 40.0

    def test_a_spend_limit_is_recognised(self):
        windows = _claude_cli.parse_usage_text(
            "Spend limit: 3% used \u00b7 resets Oct 1, 12am\n")
        assert set(windows) == {"spend_limit"}

    def test_prose_and_percentages_that_are_not_limits_are_ignored(self):
        assert _claude_cli.parse_usage_text(
            "Total cost:            $0.0000\n"
            "  97% of your usage was at >150k context\n"
            "Last 24h \u00b7 1314 requests \u00b7 3 sessions\n") == {}

    def test_garbage_never_becomes_a_reset(self):
        assert _claude_cli.parse_reset("") is None
        assert _claude_cli.parse_reset("whenever") is None
        assert _claude_cli.parse_reset("Feb 30, 1pm") is None
        assert _claude_cli.parse_reset("Xyz 3, 4pm") is None

    def test_a_window_without_a_reset_still_reports_its_percentage(self):
        windows = _claude_cli.parse_usage_text("Current session: 12% used")
        assert windows["five_hour"] == {"used": 12.0, "resets_at": None}


class TestClaudeCliReader:
    def _fake_claude(self, tmp_path, result_text, *, is_error=False):
        """A stub `claude` that writes a transcript exactly like the real one."""
        script = tmp_path / "fake_claude.py"
        script.write_text(
            "import json, os, sys\n"
            "argv = sys.argv[1:]\n"
            "sid = argv[argv.index('--session-id') + 1]\n"
            "home = os.environ['USERPROFILE']\n"
            "import re\n"
            "slug = re.sub(r'[^A-Za-z0-9]', '-', os.path.abspath(os.getcwd()))\n"
            "d = os.path.join(home, '.claude', 'projects', slug)\n"
            "os.makedirs(d, exist_ok=True)\n"
            "open(os.path.join(d, sid + '.jsonl'), 'w').write('{}\\n')\n"
            f"print(json.dumps({{'is_error': {bool(is_error)!r},"
            f" 'result': {result_text!r}, 'num_turns': 0,"
            " 'total_cost_usd': 0}))\n",
            encoding="utf-8")
        return script

    def _binary(self, script):
        # run_cli takes argv, so the "binary" is the interpreter plus script.
        return script

    def test_reads_the_live_answer_and_cleans_up_after_itself(
            self, tmp_path, monkeypatch):
        """A quota read must not file a transcript on every 3-minute sweep.

        The refusal scanner reads that same directory, so probe litter would
        both grow without bound and slow the other source down.
        """
        home = tmp_path / "home"
        home.mkdir()
        monkeypatch.setenv("USERPROFILE", str(home))
        monkeypatch.setenv("HOME", str(home))
        probe = tmp_path / "probe"
        probe.mkdir()
        monkeypatch.setattr(_claude_cli, "_probe_dir", lambda: str(probe))
        script = self._fake_claude(tmp_path, CLAUDE_USAGE_TEXT)
        monkeypatch.setattr(
            _claude_cli, "run_cli",
            lambda argv, deadline, **kw: cli_tools.run_cli(
                [sys.executable, str(script)] + argv[1:], deadline, **kw))
        monkeypatch.setattr(_claude_cli, "resolve_binary",
                            lambda key: "claude")
        reading = _claude_cli.read_usage(time.monotonic() + 30)
        assert reading["source"] == "claude-cli-usage"
        assert set(reading["windows"]) == {"five_hour", "weekly"}
        slug = _claude_cli._project_slug(str(probe))
        left = list((home / ".claude" / "projects" / slug).glob("*.jsonl"))
        assert left == [], f"probe left a transcript behind: {left}"

    def test_a_missing_cli_is_reported_not_raised(self, monkeypatch):
        monkeypatch.setattr(_claude_cli, "resolve_binary", lambda key: "")
        reading = _claude_cli.read_usage(time.monotonic() + 5)
        assert reading["error"][0] == "cli_not_installed"

    def test_non_json_output_is_refused(self, monkeypatch):
        monkeypatch.setattr(_claude_cli, "resolve_binary", lambda key: "claude")
        monkeypatch.setattr(_claude_cli, "run_cli",
                            lambda *a, **k: {"ok": True, "stdout": "not json",
                                             "error": ""})
        monkeypatch.setattr(_claude_cli, "_drop_transcript",
                            lambda *a, **k: None)
        assert _claude_cli.read_usage(
            time.monotonic() + 5)["error"][0] == "cli_bad_output"

    def test_an_api_key_account_without_plan_limits_is_not_an_error_state(
            self, monkeypatch):
        """`/usage` answers with a cost summary when there is no subscription."""
        monkeypatch.setattr(_claude_cli, "resolve_binary", lambda key: "claude")
        monkeypatch.setattr(
            _claude_cli, "run_cli",
            lambda *a, **k: {"ok": True, "error": "", "stdout": json.dumps(
                {"is_error": False, "result": "Total cost: $0.0000"})})
        monkeypatch.setattr(_claude_cli, "_drop_transcript",
                            lambda *a, **k: None)
        assert _claude_cli.read_usage(
            time.monotonic() + 5)["error"][0] == "cli_no_limits"

    def test_the_probe_directory_is_one_fixed_place(self):
        """Not the app's cwd: that would file one project entry per launch dir."""
        first = _claude_cli._probe_dir()
        assert first == _claude_cli._probe_dir()
        assert "fastprompter" in first.lower()


class TestAntigravityCliReader:
    def test_a_failed_status_is_refused(self, monkeypatch):
        monkeypatch.setattr(_antigravity_cli, "resolve_binary",
                            lambda key: "agy")
        monkeypatch.setattr(
            _antigravity_cli, "run_cli",
            lambda *a, **k: {"ok": True, "error": "", "stdout": json.dumps(
                {"status": "ERROR", "response": ""})})
        assert _antigravity_cli.read_usage(
            time.monotonic() + 5)["error"][0] == "cli_failed"

    def test_a_missing_cli_is_reported_not_raised(self, monkeypatch):
        monkeypatch.setattr(_antigravity_cli, "resolve_binary", lambda key: "")
        assert _antigravity_cli.read_usage(
            time.monotonic() + 5)["error"][0] == "cli_not_installed"

    def test_non_json_output_is_refused(self, monkeypatch):
        monkeypatch.setattr(_antigravity_cli, "resolve_binary",
                            lambda key: "agy")
        monkeypatch.setattr(_antigravity_cli, "run_cli",
                            lambda *a, **k: {"ok": True, "stdout": "<html>",
                                             "error": ""})
        assert _antigravity_cli.read_usage(
            time.monotonic() + 5)["error"][0] == "cli_bad_output"


class TestQuotaReadsAreFree:
    """Reading the quota must never consume it — the whole feature depends on it."""

    def test_claude_is_asked_in_print_mode_with_no_prompt_of_our_own(
            self, monkeypatch):
        seen = {}

        def _capture(argv, deadline, **kw):
            seen["argv"] = argv
            return {"ok": False, "stdout": "", "error": "captured"}

        monkeypatch.setattr(_claude_cli, "resolve_binary", lambda key: "claude")
        monkeypatch.setattr(_claude_cli, "run_cli", _capture)
        monkeypatch.setattr(_claude_cli, "_drop_transcript", lambda *a, **k: None)
        _claude_cli.read_usage(time.monotonic() + 5)
        argv = seen["argv"]
        assert "-p" in argv and "/usage" in argv
        assert "--session-id" in argv       # so the transcript can be removed
        # Nothing that could start a turn: only the read-only slash command.
        assert not any(a.startswith("Write") or a == "--dangerously-skip-permissions"
                       for a in argv)

    def test_antigravity_is_asked_for_structured_output(self, monkeypatch):
        seen = {}

        def _capture(argv, deadline, **kw):
            seen["argv"] = argv
            return {"ok": False, "stdout": "", "error": "captured"}

        monkeypatch.setattr(_antigravity_cli, "resolve_binary", lambda key: "agy")
        monkeypatch.setattr(_antigravity_cli, "run_cli", _capture)
        _antigravity_cli.read_usage(time.monotonic() + 5)
        assert seen["argv"][1:] == ["-p", "/usage", "--output-format", "json"]


class TestInstallLaunching:
    def test_launch_refuses_an_unknown_tool(self):
        import pytest
        with pytest.raises(ValueError):
            cli_tools.launch_installer("nope")

    def test_launch_passes_the_published_command_verbatim(self, monkeypatch):
        if os.name != "nt":
            import pytest
            pytest.skip("one-click install is Windows-only")
        seen = {}
        monkeypatch.setattr(subprocess, "Popen",
                            lambda argv, **kw: seen.setdefault("argv", argv))
        cli_tools.launch_installer("claude")
        command = seen["argv"][seen["argv"].index("-Command") + 1]
        assert command == cli_tools.INSTALLERS_BY_KEY["claude"].install_command
