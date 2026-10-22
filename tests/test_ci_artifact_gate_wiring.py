"""The artifact gate must actually RUN in CI, not just fail closed there.

`tools/audit_release_artifact.py` reads the Nuitka onefile payload through
`zstandard`, which ships only in the `build` extra.  CI installed
`uv sync --group dev`, so in a CI-like environment the gate raised
`UnreadableArtifact` on every build.  That is the safe direction -- the gate
never passed a bad artifact -- but it meant the gate was dead weight: a
regression in the gate itself and a gate that cannot start produce the same
green tick, because the job never invoked it at all.

These tests pin the two halves of the wiring:

* the CI job installs the extra that contains `zstandard`, and
* the CI job invokes the gate.

They read the workflow and `pyproject.toml` as data.  A future edit that
drops either line fails here instead of shipping a blind CI.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CI = ROOT / ".github" / "workflows" / "ci.yml"
PYPROJECT = ROOT / "pyproject.toml"


def _ci_text() -> str:
    assert CI.is_file(), f"CI workflow is missing: {CI}"
    return CI.read_text(encoding="utf-8")


def _build_extra() -> list[str]:
    data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    return data["project"]["optional-dependencies"]["build"]


class TestCiInstallsTheGateDependencies:
    def test_zstandard_lives_in_the_build_extra(self):
        """The gate's reader is optional at the project level, by design."""
        assert any(
            requirement.split(">")[0].split("=")[0].strip() == "zstandard"
            for requirement in _build_extra()
        ), f"zstandard must be declared in the build extra, got {_build_extra()}"

    def test_ci_syncs_the_build_extra(self):
        """A CI venv without it cannot run the artifact gate at all."""
        text = _ci_text()
        install_lines = [
            line for line in text.splitlines()
            if "uv sync" in line
        ]
        assert install_lines, "CI must install dependencies with uv sync"
        assert any("--extra build" in line for line in install_lines), (
            "the CI dependency install must include --extra build so that "
            f"zstandard is present; got {install_lines}"
        )


class TestCiActuallyRunsTheGate:
    def test_the_artifact_gate_is_invoked(self):
        """Installing the dependency is pointless if nothing calls the gate."""
        assert "audit_release_artifact" in _ci_text() or "build.py" in _ci_text(), (
            "CI must run the artifact gate (tools/audit_release_artifact.py) "
            "or the build that wraps it"
        )

    def test_the_source_allowlist_is_invoked(self):
        """The two-sided gate has a source half that must run before the build."""
        assert "verify_sound_allowlist" in _ci_text(), (
            "CI must run tools/verify_sound_allowlist.py: it answers what a "
            "push would publish, which a build artifact cannot answer"
        )


class TestTheGateFailsClosedWithoutTheDependency:
    def test_missing_zstandard_is_an_error_not_a_pass(self, monkeypatch, tmp_path):
        """Negative control for the whole premise: absence must never read PASS."""
        import sys

        from tools import audit_release_artifact as gate

        fake_exe = tmp_path / "FastPrompter.exe"
        fake_exe.write_bytes(b"not a real exe")

        real_import = __builtins__["__import__"] if isinstance(__builtins__, dict) \
            else __builtins__.__import__

        def refuse(name, *args, **kwargs):
            if name == "zstandard":
                raise ImportError("no zstandard")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr("builtins.__import__", refuse)
        monkeypatch.delitem(sys.modules, "zstandard", raising=False)

        with pytest.raises(gate.UnreadableArtifact):
            gate.payload_from_exe(fake_exe)
