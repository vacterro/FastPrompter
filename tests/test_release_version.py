"""P2: every release-version surface must agree with the canonical VERSION.

FastPrompter.pyw's Nuitka ``--product-version`` (the EXE's ProductVersion in
Explorer) and pyproject.toml's ``version`` (the pip/uv package version)
drifted from the canonical VERSION file that tools/release.py reads. The
About dialog, the file properties and the package metadata must describe
the same release. `tools/sync_release_version.py` is the single tool that
re-syncs all of them; this test is the gate that stops the drift.
"""

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VERSION_FILE = ROOT / "VERSION"
PYPROJECT = ROOT / "pyproject.toml"
PYW = ROOT / "FastPrompter.pyw"


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
                    PYW.read_text(encoding="utf-8"), re.MULTILINE)
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
