"""T-1297: the release-version surfaces must not drift apart.

RC preparation requires version parity before anything is built: the canonical
VERSION file, the packaging metadata, the Nuitka --product-version that
Windows Explorer shows, and the resolved lock all have to name one version. A
drift means the shipped EXE reports a different version than the package, and
the release receipt binds a ProductVersion the tree does not contain.

This is a read-only parity check. It asserts, and never rewrites: the writer is
tools/sync_release_version.py, and a test that silently fixed the drift would
hide exactly the defect it exists to catch.
"""

import re
import tomllib
from pathlib import Path

import pytest

from tools import sync_release_version

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def canonical() -> str:
    return sync_release_version.read_canonical()


def test_canonical_version_is_three_numeric_parts(canonical):
    assert re.fullmatch(r"\d+\.\d+\.\d+", canonical), (
        f"VERSION must be X.Y.Z, got {canonical!r}"
    )


def test_pyproject_version_matches_canonical(canonical):
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert data["project"]["version"] == canonical


def test_nuitka_product_version_matches_canonical(canonical):
    text = (ROOT / "FastPrompter.pyw").read_text(encoding="utf-8")
    found = sync_release_version._PYW_RE.findall(text)
    assert len(found) == 1, f"expected exactly one product-version line, got {found}"
    assert found[0] == f"# nuitka-project: --product-version={canonical}"


def test_lock_resolves_the_canonical_version(canonical):
    text = (ROOT / "uv.lock").read_text(encoding="utf-8")
    match = re.search(
        r'\[\[package\]\]\nname = "fastprompter"\nversion = "([^"]+)"', text
    )
    assert match is not None, "uv.lock no longer carries a fastprompter package entry"
    assert match.group(1) == canonical


def test_sync_tool_reports_no_drift(canonical):
    """The tool's own regexes must each match exactly one line, or a sync
    would raise instead of writing and the RC would break on the build step."""
    pyw_text = (ROOT / "FastPrompter.pyw").read_text(encoding="utf-8")
    pyproject_text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert len(sync_release_version._PYW_RE.findall(pyw_text)) == 1
    assert len(sync_release_version._PYPROJECT_RE.findall(pyproject_text)) == 1
