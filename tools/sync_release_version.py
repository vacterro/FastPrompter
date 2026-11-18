"""Sync every release-version surface to the canonical VERSION file.

P2 of the audit baseline: FastPrompter.pyw (the Nuitka EXE's
--product-version, shown in Windows Explorer) and pyproject.toml (the
dist/uv package version) both drifted from the canonical VERSION file that
`tools/release.py` reads. The executable's ProductVersion must equal the
package version — Explorer properties, the About dialog and the pip
metadata must agree.

T-1454: the four READMEs carried a hand-written source-version badge, so they
lagged one release behind VERSION with nothing to notice. They are synced here
for the same reason as the other surfaces: one writer, no hand edits.

Usage:  python tools/sync_release_version.py [VERSION]
        (no argument reads the canonical VERSION file)
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VERSION_FILE = ROOT / "VERSION"
PYPROJECT = ROOT / "pyproject.toml"
PYW = ROOT / "FastPrompter.pyw"

_PYW_RE = re.compile(r"^# nuitka-project: --product-version=\S+", re.MULTILINE)
_PYPROJECT_RE = re.compile(r'^version = "\S+"', re.MULTILINE)
# T-1454: the release-version badge line. `tools/saipen_engine/release_contract`
# proves a release surface by finding exactly one literal `**vX.Y.Z**` in it
# (`version_badges`), so README.md needs BOTH the shields badge and the pinned
# literal beside it -- the pinned form alone was replaced by a shields badge in
# 88b420c6, which left `version_badges(README.md)` empty and the ship parity
# gate unsatisfiable.
_README_BADGE_LINE_RE = re.compile(
    r'(<a href="VERSION">'
    r'<img src="https://img.shields.io/badge/source-)\d+\.\d+\.\d+'
    r'(-D4B86A\?style=flat-square" alt="source version )\d+\.\d+\.\d+'
    r'("></a>)(?: \*\*v\d+\.\d+\.\d+\*\*)?'
)
# The plain `**vX.Y.Z**` heading in the three translated root READMEs and the
# two saitranslate kitchen indices; both are enumerated release surfaces.
_README_TRANSLATED_RE = re.compile(r"\*\*v\d+\.\d+\.\d+\*\*")
_README_TRANSLATED_FILES = (
    "README.ded.md",
    "README.ee.md",
    "README.ja.md",
    ".saipen/saitranslate/kitchen/docs/README_DOCS.md",
    ".saipen/saitranslate/kitchen/guides/README_GUIDES.md",
)


def read_canonical() -> str:
    return VERSION_FILE.read_text(encoding="utf-8").strip()


def sync_pyw(version: str) -> bool:
    text = PYW.read_text(encoding="utf-8")
    new, n = _PYW_RE.subn(f"# nuitka-project: --product-version={version}", text)
    if n != 1:
        raise RuntimeError(f"FastPrompter.pyw has {n} product-version lines")
    if new != text:
        PYW.write_text(new, encoding="utf-8")
        return True
    return False


def sync_pyproject(version: str) -> bool:
    text = PYPROJECT.read_text(encoding="utf-8")
    new, n = _PYPROJECT_RE.subn(f'version = "{version}"', text)
    if n != 1:
        raise RuntimeError(f"pyproject.toml has {n} version lines")
    if new != text:
        PYPROJECT.write_text(new, encoding="utf-8")
        return True
    return False


def sync_readme_main(version: str) -> bool:
    path = ROOT / "README.md"
    text = path.read_text(encoding="utf-8")
    # One replacement that writes the shields badge and, right after it, the
    # pinned literal the ship parity gate reads.
    repl = (
        f'\\g<1>{version}\\g<2>{version}\\g<3> **v{version}**'
    )
    new, n = _README_BADGE_LINE_RE.subn(repl, text)
    if n != 1:
        raise RuntimeError(f"README.md has {n} source-version badge lines")
    if new != text:
        path.write_text(new, encoding="utf-8")
        return True
    return False


def sync_readme_translated(version: str) -> list[str]:
    changed = []
    for fname in _README_TRANSLATED_FILES:
        path = ROOT / fname
        text = path.read_text(encoding="utf-8")
        new, n = _README_TRANSLATED_RE.subn(f"**v{version}**", text)
        if n != 1:
            raise RuntimeError(f"{fname} has {n} version badges")
        if new != text:
            path.write_text(new, encoding="utf-8")
            changed.append(fname)
    return changed


def main() -> int:
    version = sys.argv[1].strip() if len(sys.argv) > 1 else read_canonical()
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        print(f"invalid version {version!r}; expected X.Y.Z")
        return 2
    changed = []
    if sync_pyproject(version):
        changed.append("pyproject.toml")
    if sync_pyw(version):
        changed.append("FastPrompter.pyw")
    if sync_readme_main(version):
        changed.append("README.md")
    changed.extend(sync_readme_translated(version))
    if changed:
        print(f"updated {', '.join(changed)} to {version}")
        print("regenerating uv.lock ...")
        subprocess.run(["uv", "lock"], cwd=ROOT, check=True)
    else:
        print(f"already at {version} everywhere")
    return 0


if __name__ == "__main__":
    sys.exit(main())
