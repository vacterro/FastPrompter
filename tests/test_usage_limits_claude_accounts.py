"""Tests for a SECOND Claude account.

Claude used to be hard-wired to exactly one account: ``discover_accounts``
collapsed ``~/.claude`` and ``~/.claude.json`` into one ref (correctly — they
are one installation) and there was no route to any other home, while the
authoritative source, ``claude -p "/usage"``, always answered for whatever
account the ambient environment pointed at.

A second Claude account is a second ``CLAUDE_CONFIG_DIR``: the CLI keeps
credentials, settings and transcripts together under one root. These tests pin
the three things that make that work and the two that must NOT leak between
accounts.
"""

from __future__ import annotations

import json
import time

import pytest

from fastprompter.core.usage_limits.providers import _claude_cli
from fastprompter.core.usage_limits.providers import claude as claude_mod
from fastprompter.core.usage_limits.providers.claude import ClaudeProvider
from fastprompter.core.usage_limits.service import apply_display_names


@pytest.fixture()
def fake_home(tmp_path, monkeypatch):
    """A HOME carrying the default account and nothing else."""
    default = tmp_path / ".claude"
    default.mkdir()
    (default / "settings.json").write_text("{}", encoding="utf-8")
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setenv("HOME", str(tmp_path))
    return tmp_path


def _home(root, name):
    path = root / name
    path.mkdir()
    (path / "settings.json").write_text("{}", encoding="utf-8")
    return path


class TestDiscovery:
    def test_one_account_when_there_is_one_home(self, fake_home):
        accounts = ClaudeProvider(use_cli=False).discover_accounts()
        assert len(accounts) == 1
        assert accounts[0].metadata["is_default"] is True
        # The default account is read with the ambient environment, exactly as
        # it was before Claude became multi-account.
        assert accounts[0].metadata["config_dir"] == ""

    def test_a_sibling_home_becomes_a_second_account(self, fake_home):
        _home(fake_home, ".claude-work")
        accounts = ClaudeProvider(use_cli=False).discover_accounts()
        assert len(accounts) == 2
        extra = [a for a in accounts if not a.metadata["is_default"]][0]
        assert extra.source_kind == "auto_sibling"
        assert extra.metadata["config_dir"] == extra.source_path

    def test_a_configured_home_becomes_a_second_account(self, fake_home,
                                                        tmp_path):
        elsewhere = _home(tmp_path, "claude-elsewhere")
        accounts = ClaudeProvider(extra_paths=[str(elsewhere)],
                                  use_cli=False).discover_accounts()
        assert len(accounts) == 2
        extra = [a for a in accounts if not a.metadata["is_default"]][0]
        assert extra.source_kind == "configured"

    def test_a_directory_without_claude_fingerprints_is_not_an_account(
            self, fake_home):
        (fake_home / ".claude-backup").mkdir()          # no marker files
        accounts = ClaudeProvider(use_cli=False).discover_accounts()
        assert len(accounts) == 1

    def test_the_same_home_is_never_two_accounts(self, fake_home):
        sibling = _home(fake_home, ".claude-work")
        accounts = ClaudeProvider(extra_paths=[str(sibling)],
                                  use_cli=False).discover_accounts()
        assert len(accounts) == 2

    def test_identity_does_not_move_when_a_second_account_appears(
            self, fake_home):
        before = ClaudeProvider(use_cli=False).discover_accounts()[0]
        _home(fake_home, ".claude-work")
        after = ClaudeProvider(use_cli=False).discover_accounts()
        default = [a for a in after if a.metadata["is_default"]][0]
        assert default.stable_id == before.stable_id

    def test_the_default_account_is_numbered_first(self, fake_home):
        _home(fake_home, ".claude-work")
        accounts = apply_display_names(
            ClaudeProvider(use_cli=False).discover_accounts())
        named = {a.display_name: a for a in accounts}
        assert sorted(named) == ["Claude 1", "Claude 2"]
        assert named["Claude 1"].metadata["is_default"] is True


class TestProbeIsolation:
    def _capture(self, monkeypatch, tmp_path):
        seen = {}

        def fake_read_usage(deadline, *, binary="", now=None, config_dir=""):
            seen["config_dir"] = config_dir
            return {"windows": {"five_hour": {"used": 40.0,
                                              "resets_at": time.time() + 900}},
                    "captured_at": time.time(), "source": "fake-cli"}

        monkeypatch.setattr(_claude_cli, "read_usage", fake_read_usage)
        # The probe skips the CLI when a cache is under 5 minutes old, and the
        # Desktop sampler on the DEVELOPER's machine is such a cache. Point it
        # at nothing so this test measures the provider, not the workstation.
        monkeypatch.setattr(claude_mod, "desktop_history_path",
                            lambda: str(tmp_path / "no-desktop-history.json"))
        return seen

    def test_the_second_account_is_read_with_its_own_config_dir(
            self, fake_home, tmp_path, monkeypatch):
        seen = self._capture(monkeypatch, tmp_path)
        _home(fake_home, ".claude-work")
        provider = ClaudeProvider()
        extra = [a for a in provider.discover_accounts()
                 if not a.metadata["is_default"]][0]
        provider.probe(extra, deadline=time.monotonic() + 30)
        assert seen["config_dir"] == extra.source_path

    def test_the_default_account_keeps_the_ambient_environment(
            self, fake_home, tmp_path, monkeypatch):
        seen = self._capture(monkeypatch, tmp_path)
        provider = ClaudeProvider()
        default = provider.discover_accounts()[0]
        provider.probe(default, deadline=time.monotonic() + 30)
        assert seen["config_dir"] == ""

    def test_the_desktop_sampler_never_bleeds_into_a_second_account(
            self, fake_home, tmp_path, monkeypatch):
        """An org-less multi-account sample is unattributable, even to default."""
        history = tmp_path / "plan-usage-history.json"
        history.write_text(json.dumps({"samples": [
            {"t": int(time.time() * 1000), "u": {"fh": 77, "sd": 55}},
        ]}), encoding="utf-8")
        monkeypatch.setattr(claude_mod, "desktop_history_path",
                            lambda: str(history))
        _home(fake_home, ".claude-work")
        provider = ClaudeProvider(use_cli=False)
        accounts = provider.discover_accounts()
        default = [a for a in accounts if a.metadata["is_default"]][0]
        extra = [a for a in accounts if not a.metadata["is_default"]][0]
        assert provider._desktop_reading(default) == {}
        assert provider._desktop_reading(extra) == {}


class TestCliConfigDir:
    def test_read_usage_exports_claude_config_dir(self, monkeypatch, tmp_path):
        seen = {}

        def fake_run_cli(argv, deadline, *, cwd=None, env=None, **kw):
            seen["env"] = env
            return {"ok": True, "error": "", "stdout": json.dumps(
                {"result": "Current session: 12% used"})}

        monkeypatch.setattr(_claude_cli, "resolve_binary", lambda name: "claude")
        monkeypatch.setattr(_claude_cli, "run_cli", fake_run_cli)
        out = _claude_cli.read_usage(time.monotonic() + 30,
                                     config_dir=str(tmp_path))
        assert "error" not in out, out
        assert seen["env"]["CLAUDE_CONFIG_DIR"] == str(tmp_path)

    def test_no_config_dir_means_no_env_override(self, monkeypatch):
        seen = {}

        def fake_run_cli(argv, deadline, *, cwd=None, env=None, **kw):
            seen["env"] = env
            return {"ok": True, "error": "", "stdout": json.dumps(
                {"result": "Current session: 12% used"})}

        monkeypatch.setattr(_claude_cli, "resolve_binary", lambda name: "claude")
        monkeypatch.setattr(_claude_cli, "run_cli", fake_run_cli)
        _claude_cli.read_usage(time.monotonic() + 30)
        assert seen["env"] is None

    def test_probe_litter_is_dropped_from_the_accounts_own_home(
            self, tmp_path):
        """The transcript the probe files lands under THAT account's root."""
        directory = str(tmp_path / "cwd")
        slug = _claude_cli._project_slug(directory)
        transcript = tmp_path / "home" / "projects" / slug / "sid.jsonl"
        transcript.parent.mkdir(parents=True)
        transcript.write_text("{}", encoding="utf-8")
        _claude_cli._drop_transcript("sid", directory,
                                     str(tmp_path / "home"))
        assert not transcript.exists()
