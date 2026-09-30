"""T-1259 CLEAN re-verification: manifest-approved paths stay absent and unreferenced.

Read-only. Exits non-zero on any violation, so it is safe to use as a reverify
gate. ponytail: the blocking reference corpus is a literal path-prefix list;
widen it if the repository ever grows a new live consumer outside those roots.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = Path(__file__).with_name("t1259_cleanup_manifest.json")

BLOCKING_PREFIXES = (
    "src/",
    "tests/",
    "tests_smoke/",
    "tools/",
    "docs/",
    "_res/",
    ".github/",
)
BLOCKING_FILES = (
    ".saipen/STATE.md",
    ".saipen/BOARD.md",
    ".saipen/LOG.md",
    ".saipen/MANIFEST.json",
)
TEXT_SUFFIXES = (
    ".py", ".md", ".toml", ".cfg", ".txt", ".json", ".yaml", ".yml",
    ".ps1", ".bat", ".cmd", ".pyw", ".spec", ".in", ".html", ".rst",
)


def _git(*args: str) -> list[str]:
    out = subprocess.run(
        ["git", *args], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout
    return [x for x in out.split("\0") if x]


def is_blocking(rel: str) -> bool:
    if rel.startswith(BLOCKING_PREFIXES):
        return True
    if "/" not in rel:
        return True
    return rel.startswith(BLOCKING_FILES) or rel.startswith(
        (".saipen/KNOWLEDGE/", ".saipen/intake/")
    )


def main() -> int:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    tracked = set(_git("ls-files", "-z"))
    corpus = {
        path: (ROOT / path).read_text(encoding="utf-8", errors="ignore")
        for path in sorted(tracked)
        if path.endswith(TEXT_SUFFIXES) and is_blocking(path)
    }

    violations: list[str] = []

    for entry in manifest["delete"]:
        rel = entry["path"]
        if (ROOT / rel).exists():
            violations.append(f"DELETED PATH PRESENT: {rel}")
        if rel in tracked:
            violations.append(f"DELETED PATH IS TRACKED: {rel}")
        pattern = re.compile(re.escape(rel))
        for path, text in corpus.items():
            if path != rel and pattern.search(text):
                violations.append(f"LIVE REFERENCE REMAINS: {rel} <- {path}")

    for entry in manifest["preserve"]:
        path = ROOT / entry["path"]
        if not path.is_file():
            violations.append(f"PRESERVED PATH MISSING: {entry['path']}")
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != entry["sha256"]:
            violations.append(f"PRESERVED PATH MUTATED: {entry['path']}")

    for entry in manifest["delete"]:
        reason = entry.get("classification", "").strip()
        if not reason or not entry.get("sha256") or entry.get("bytes") is None:
            violations.append(f"INCOMPLETE MANIFEST RECORD: {entry['path']}")

    # Completeness: every root-level untracked/ignored .py must be accounted for
    # by exactly one manifest record, so new scratch cannot slip in unclassified.
    ignored = set(_git("ls-files", "-z", "--others", "--ignored", "--exclude-standard"))
    accounted = {e["path"] for e in manifest["delete"]} | {
        e["path"] for e in manifest["preserve"]
    }
    for path in sorted(ROOT.iterdir()):
        if not path.is_file() or path.suffix != ".py" or path.name == "conftest.py":
            continue
        rel = path.name
        if rel in tracked or rel in accounted:
            continue
        violations.append(f"UNCLASSIFIED ROOT SCRIPT: {rel} ({'ignored' if rel in ignored else 'untracked'})")

    print(f"corpus: {len(corpus)} blocking reference files")
    print(f"deleted paths proven absent+unreferenced: {len(manifest['delete'])}")
    print(f"preserved paths proven present+intact: {len(manifest['preserve'])}")
    if violations:
        for line in violations:
            print(f"FAIL {line}")
        return 1
    print("T-1259 CLEAN REVERIFY PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())