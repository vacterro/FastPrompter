"""P2: every release-version surface must agree with the canonical VERSION.

FastPrompter.pyw's Nuitka ``--product-version`` (the EXE's ProductVersion in
Explorer) and pyproject.toml's ``version`` (the pip/uv package version)
drifted from the canonical VERSION file that tools/release.py reads. The About
dialog, the file properties and the package metadata must describe the same
release. `tools/sync_release_version.py` is the single tool that re-syncs all
of them; this test is the gate that stops the drift.

The provenance tests below pin the hardened release contract: local AND remote
tags are checked, an already-published release is immutable, and publication
is refused without a valid receipt.
"""

import importlib.util
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
VERSION_FILE = ROOT / "VERSION"
PYPROJECT = ROOT / "pyproject.toml"
PYW = ROOT / "FastPrompter.pyw"


def _load_release_tool():
    tools_dir = str(ROOT / "tools")
    if tools_dir not in sys.path:
        sys.path.insert(0, tools_dir)
    spec = importlib.util.spec_from_file_location(
        "fastprompter_release_tool", ROOT / "tools" / "release.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_canonical_version_is_well_formed():
    v = VERSION_FILE.read_text(encoding="utf-8").strip()
    assert re.fullmatch(r"\d+\.\d+\.\d+", v), f"bad VERSION {v!r}"


def test_version_agrees_everywhere():
    canonical = VERSION_FILE.read_text(encoding="utf-8").strip()
    pyproject = re.search(r'^version = "(\S+)"',
                          PYPROJECT.read_text(encoding="utf-8"),
                          re.MULTILINE)
    assert pyproject, "pyproject.toml has no version line"
    pyw = re.search(r"^# nuitka-project: --product-version=(\S+)$",
                    PYW.read_text(encoding="utf-8"),
                    re.MULTILINE)
    assert pyw, "FastPrompter.pyw has no product-version line"
    assert pyproject.group(1) == canonical, (
        "pyproject.toml drifted from VERSION - run "
        "tools/sync_release_version.py")
    assert pyw.group(1) == canonical, (
        "FastPrompter.pyw drifted from VERSION - run "
        "tools/sync_release_version.py")


def test_sync_tool_reports_already_synced():
    """The sync tool on an already-consistent tree is a no-op that exits 0 —
    running it must never mutate a synced tree (a release would otherwise
    dirty the worktree for nothing)."""
    if not sys.executable:
        return
    result = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "sync_release_version.py")],
        capture_output=True, text=True, cwd=ROOT, timeout=60)
    assert result.returncode == 0, result.stderr
    assert "already at" in result.stdout


def test_release_tool_aborts_on_local_tag_provenance_mismatch(monkeypatch):
    """T-1011 + hardening: a local tag pointing elsewhere aborts the release."""
    release = _load_release_tool()

    def fake_git(*args, **kwargs):
        if args[:2] == ("rev-parse", "HEAD"):
            return "commit-HEAD"
        if args[0] == "rev-parse" and args[1].startswith("v"):
            return "commit-OTHER"
        raise AssertionError(f"unexpected git call: {args}")

    monkeypatch.setattr(release.rp, "git", fake_git)
    with pytest.raises(SystemExit) as excinfo:
        release.check_tag_provenance("0.8.40")
    assert "version already tagged at different commit" in str(excinfo.value)


def test_release_tool_aborts_on_remote_tag_provenance_mismatch(monkeypatch):
    release = _load_release_tool()

    def fake_git(*args, **kwargs):
        if args[:2] == ("rev-parse", "HEAD"):
            return "commit-HEAD"
        if args[0] == "rev-parse" and args[1].startswith("v"):
            return "commit-HEAD"
        raise AssertionError(f"unexpected git call: {args}")

    monkeypatch.setattr(release.rp, "git", fake_git)
    monkeypatch.setattr(release.rp, "git_remote_tag_commit", lambda tag: "commit-REMOTE")
    with pytest.raises(SystemExit) as excinfo:
        release.check_tag_provenance("0.8.40")
    assert "remote tag" in str(excinfo.value)


def test_release_tool_proceeds_on_provenance_match(monkeypatch):
    release = _load_release_tool()

    def fake_git(*args, **kwargs):
        if args[:2] == ("rev-parse", "HEAD"):
            return "commit-MATCH"
        if args[0] == "rev-parse" and args[1].startswith("v"):
            return "commit-MATCH"
        raise AssertionError(f"unexpected git call: {args}")

    monkeypatch.setattr(release.rp, "git", fake_git)
    monkeypatch.setattr(release.rp, "git_remote_tag_commit", lambda tag: "commit-MATCH")
    release.check_tag_provenance("0.8.40")


def test_release_tool_refuses_published_release(monkeypatch):
    """A published release is immutable; completing a draft stays allowed."""
    release = _load_release_tool()
    monkeypatch.setattr(
        release, "api", lambda path, tok, **kwargs: {"draft": False, "id": 1}
    )
    with pytest.raises(SystemExit) as excinfo:
        release.ensure_draft("tok", "v0.8.68", "head", "notes")
    assert "immutable" in str(excinfo.value)


def test_release_tool_requires_a_receipt(monkeypatch, tmp_path):
    release = _load_release_tool()
    monkeypatch.setattr(release.rp, "RECEIPT_PATH", tmp_path / "missing_receipt.json")
    with pytest.raises(SystemExit) as excinfo:
        release.check_receipt("0.8.68", str(tmp_path / "FastPrompter.exe"))
    assert "receipt missing" in str(excinfo.value)
