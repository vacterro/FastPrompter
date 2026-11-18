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


def test_readme_source_badge_matches_canonical(canonical):
    """T-1454: the badge is hand-written, so it sat at 0.8.72 while VERSION
    said 0.8.73 and nothing in the tree noticed."""
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    line = (
        f'<a href="VERSION"><img src="https://img.shields.io/badge/'
        f'source-{canonical}-D4B86A?style=flat-square" '
        f'alt="source version {canonical}"></a>'
    )
    assert text.count(line) == 1, (
        f"README.md must carry exactly one source badge line naming {canonical}"
    )


def test_every_release_surface_carries_exactly_one_pinned_badge(canonical):
    """The ship parity gate proves a release surface by finding exactly one
    literal ``**vX.Y.Z**`` in it (saipen_engine.release_contract.version_badges).

    That set is VERSION, README.md, the three root README mirrors, CHANGELOG.md
    and every non-ignored locale README under the translation kitchen. The
    pinned literal is easy to lose: commit 88b420c6 replaced README.md's with a
    shields badge alone, which left ``version_badges(README.md) == []`` and made
    `saipen ship` unsatisfiable until 64661de put it back. These five files are
    the badge-bearing half of that surface, so the same loss cannot recur here.
    """
    surfaces = ("README.md",) + sync_release_version._README_TRANSLATED_FILES
    for name in surfaces:
        text = (ROOT / name).read_text(encoding="utf-8")
        found = sync_release_version._README_TRANSLATED_RE.findall(text)
        assert found == [f"**v{canonical}**"], (
            f"{name} must carry exactly one pinned **v{canonical}** badge, got {found}"
        )


def test_changelog_head_is_the_canonical_version(canonical):
    """A release ships one version, so the newest changelog entry names it."""
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    head = re.search(r"^## (\d+\.\d+\.\d+)", text, re.MULTILINE)
    assert head is not None, "CHANGELOG.md carries no version heading"
    assert head.group(1) == canonical, (
        f"CHANGELOG.md starts at {head.group(1)} while VERSION says {canonical}"
    )
