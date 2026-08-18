"""Sync every release-version surface to the canonical VERSION file.

P2 of the audit baseline: FastPrompter.pyw (the Nuitka EXE's
--product-version, shown in Windows Explorer) and pyproject.toml (the
dist/uv package version) both drifted from the canonical VERSION file that
`tools/release.py` reads. The executable's ProductVersion must equal the
package version — Explorer properties, the About dialog and the pip
metadata must agree.

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
    if changed:
        print(f"updated {', '.join(changed)} to {version}")
        print("regenerating uv.lock ...")
        subprocess.run(["uv", "lock"], cwd=ROOT, check=True)
    else:
        print(f"already at {version} everywhere")
    return 0


if __name__ == "__main__":
    sys.exit(main())
