"""SRC-101 / CORE-003: runtime dependency authority and launcher admission.

The audit found THREE divergent dependency descriptions with three different
completeness levels: pyproject.toml declared tzdata, requirements.txt did not,
and the .pyw admission probe did not even look for the payload. The concrete
degraded behaviour already in production code is loss of named-zone reset
parsing: Claude's /usage answer names its IANA zone and
providers/_claude_cli.py resolves it through ZoneInfo(), which on Windows
(no system timezone database) needs the tzdata package.

These tests pin the authorities together:

* the canonical manifest and the plain-pip source manifest stay at exact parity;
* launcher admission refuses to certify an interpreter whose timezone payload is
  unusable, even though PyQt6 and markdown import;
* the provider path that needs the payload still parses a named zone;
* the standalone build still ships the payload.
"""

import builtins
import datetime
import importlib.util
import os
import sys
import tomllib
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
_PYW = _REPO_ROOT / "FastPrompter.pyw"


def _load_pyw():
    """Load FastPrompter.pyw as a module; the __main__ guard stays off."""
    spec = importlib.util.spec_from_file_location("FastPrompter", str(_PYW))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _canonical_dependencies():
    with open(_REPO_ROOT / "pyproject.toml", "rb") as fh:
        return list(tomllib.load(fh)["project"]["dependencies"])


def _requirements_txt():
    lines = []
    for raw in (_REPO_ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if line:
            lines.append(line)
    return lines


def _outside_venv(monkeypatch, mod, tmp_path):
    """Point the launcher at a project dir whose .venv is a synthetic tmp tree.

    Returns (venv_python_path, exec_calls). os.execv is stubbed to raise
    SystemExit so a successful re-exec is observable instead of fatal.
    """
    venv_py = os.path.join(str(tmp_path), "project", ".venv", "Scripts", "python.exe")
    monkeypatch.setattr(mod, "__file__", os.path.join(str(tmp_path), "project", "FastPrompter.pyw"))
    monkeypatch.setattr(sys, "executable", os.path.join(str(tmp_path), "system", "python.exe"))
    calls = []

    def _fake_execv(path, argv):
        calls.append((path, argv))
        raise SystemExit(0)

    real_exists = os.path.exists
    monkeypatch.setattr(os, "execv", _fake_execv)
    monkeypatch.setattr(
        os.path, "exists",
        lambda p: True if p == venv_py else real_exists(p))
    return venv_py, calls


# --------------------------------------------------------------------------
# manifest parity
# --------------------------------------------------------------------------

def test_requirements_txt_is_at_exact_parity_with_pyproject():
    canonical = sorted(_canonical_dependencies())
    declared = sorted(_requirements_txt())
    assert declared == canonical, (
        "requirements.txt drifted from pyproject.toml [project.dependencies], "
        "the single runtime dependency authority")


def test_every_authority_declares_the_timezone_payload():
    pyproject = " ".join(_canonical_dependencies())
    requirements = " ".join(_requirements_txt())
    assert "tzdata" in pyproject
    assert "tzdata" in requirements, (
        "the plain-pip source-install path would produce an environment that "
        "cannot resolve the IANA zones Claude's /usage answer names")


# --------------------------------------------------------------------------
# launcher admission
# --------------------------------------------------------------------------

def test_admission_certifies_the_canonical_environment():
    """The project venv is complete, so nothing may be reported missing."""
    mod = _load_pyw()
    assert mod._missing_startup_requirements() == []


def test_admission_does_not_certify_an_interpreter_without_timezone_data(
        monkeypatch, tmp_path):
    """PyQt6 + markdown import, tzdata does not: admission must fail over.

    This is the exact shape the audit describes -- the old import-only probe
    saw nothing missing and blessed the interpreter, so a named-zone reset
    silently degraded to "no reset time".
    """
    import zoneinfo

    def _no_zone_database(name):
        raise ZoneInfoNotFoundError(name)

    monkeypatch.setattr(zoneinfo, "ZoneInfo", _no_zone_database)
    mod = _load_pyw()
    venv_py, calls = _outside_venv(monkeypatch, mod, tmp_path)

    with pytest.raises(SystemExit) as exc_info:
        mod._ensure_venv_python()

    assert exc_info.value.code == 0
    assert len(calls) == 1, f"expected one re-exec into the project venv, got {calls}"
    assert calls[0][0] == venv_py


def test_admission_probe_names_the_missing_payload(monkeypatch):
    import zoneinfo

    def _no_zone_database(name):
        raise ZoneInfoNotFoundError(name)

    monkeypatch.setattr(zoneinfo, "ZoneInfo", _no_zone_database)
    mod = _load_pyw()
    assert mod._missing_startup_requirements() == ["tzdata"]


def test_admission_refuses_an_incomplete_interpreter_when_venv_is_absent(
        monkeypatch, tmp_path):
    import zoneinfo

    def _no_zone_database(name):
        raise ZoneInfoNotFoundError(name)

    monkeypatch.setattr(zoneinfo, "ZoneInfo", _no_zone_database)
    mod = _load_pyw()
    venv_py, calls = _outside_venv(monkeypatch, mod, tmp_path)
    real_exists = os.path.exists
    monkeypatch.setattr(os.path, "exists",
                        lambda p: False if p == venv_py else real_exists(p))

    with pytest.raises(RuntimeError) as exc_info:
        mod._ensure_venv_python()

    assert "tzdata" in str(exc_info.value)
    assert venv_py in str(exc_info.value)
    assert calls == []


def test_admission_still_reexecs_on_a_missing_startup_module(monkeypatch, tmp_path):
    """Regression guard: the capability probe must ADD to, never replace, the
    module check that already worked."""
    real_import = builtins.__import__

    def _guarded(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "markdown":
            raise ImportError("markdown missing")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", _guarded)
    mod = _load_pyw()
    venv_py, calls = _outside_venv(monkeypatch, mod, tmp_path)

    with pytest.raises(SystemExit):
        mod._ensure_venv_python()
    assert len(calls) == 1
    assert calls[0][0] == venv_py


# --------------------------------------------------------------------------
# the consumer that actually needs the payload
# --------------------------------------------------------------------------

def test_named_zone_reset_still_parses_through_the_provider():
    from fastprompter.core.usage_limits.providers import _claude_cli

    expected = int(datetime.datetime(
        2027, 9, 3, 16, 49, tzinfo=ZoneInfo("Europe/Tallinn")).timestamp())
    assert _claude_cli.parse_reset(
        "Sep 3, 2027, 4:49pm", tz_name="Europe/Tallinn") == expected


def test_usage_text_keeps_a_named_zone_reset_window():
    from fastprompter.core.usage_limits.providers import _claude_cli

    text = (
        "You are currently using your subscription to power your Claude Code usage\n"
        "\n"
        "Current session: 65% used \u00b7 resets Sep 3, 2027, 4:49pm (Europe/Tallinn)\n"
        "Current week (all models): 64% used \u00b7 resets Sep 8, 2027, 4:59pm (Europe/Tallinn)\n"
    )
    windows = _claude_cli.parse_usage_text(text)
    assert windows["five_hour"]["resets_at"] is not None
    assert windows["weekly"]["resets_at"] is not None


def test_an_unresolvable_zone_is_the_degradation_the_dependency_prevents():
    """Documents WHY tzdata is a runtime dependency: without the payload the
    provider cannot tell a bad zone name from a missing database and drops the
    window's reset time entirely."""
    from fastprompter.core.usage_limits.providers import _claude_cli

    assert _claude_cli.parse_reset(
        "Sep 3, 2027, 4:49pm", tz_name="Not/AZone") is None


# --------------------------------------------------------------------------
# packaged artifact
# --------------------------------------------------------------------------

def test_standalone_build_still_ships_the_timezone_payload():
    build = (_REPO_ROOT / "tools" / "build.py").read_text(encoding="utf-8")
    assert "--include-package-data=tzdata" in build, (
        "the Nuitka standalone build must keep including the tzdata payload "
        "that the runtime now requires")
