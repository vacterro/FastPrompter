"""Assert-based self-check for debt._receipt_binds_current_tree (T-1362).

The T-1362 fix must do two things at once:
  1. accept a receipt whose HEAD is an ANCESTOR of live HEAD (a protocol-only
     commit moves HEAD but not the source_tree_fingerprint, so the old
     HEAD-equality test rejected evidence the fingerprint still vouches for);
  2. still reject the cases that make evidence unsafe -- a moved source tree,
     a divergent/unrelated HEAD, a missing HEAD.

Each case below builds a real throwaway git repo so the ancestry check runs
against git itself rather than a mock.
"""

import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, r"C:\Users\vac34\.agents\skills\saipen\tools")
from saipen_engine import debt  # noqa: E402


def git(root, *args):
    return subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def commit(root, text):
    (root / "f.txt").write_text(text, encoding="utf-8")
    git(root, "add", "-A")
    git(root, "commit", "-m", text)
    return git(root, "rev-parse", "HEAD")


def main():
    checks = []
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        git(root, "init", "-q", "-b", "main")
        git(root, "config", "user.email", "t@t.t")
        git(root, "config", "user.name", "t")
        head_a = commit(root, "a")
        head_b = commit(root, "b")
        # a divergent commit: same base, unrelated line of history
        git(root, "checkout", "-q", "-b", "side", head_a)
        head_side = commit(root, "side")
        git(root, "checkout", "-q", "main")
        git(root, "branch", "-q", "keep-a", head_a)

        def binds(receipt, identity, at=None):
            return debt._receipt_binds_current_tree(receipt, identity, at or root)

        live = {"source_head": head_b, "source_tree_fingerprint": "FP"}

        # 1. exact HEAD + exact fingerprint -> accept
        checks.append((
            "exact head, exact fingerprint -> accept",
            binds({"source_head": head_b, "source_tree_fingerprint": "FP"}, live),
            True,
        ))
        # 2. ANCESTOR head + exact fingerprint -> accept (the fix)
        checks.append((
            "ancestor head, exact fingerprint -> accept",
            binds({"source_head": head_a, "source_tree_fingerprint": "FP"}, live),
            True,
        ))
        # 3. ancestor head + MOVED source tree -> reject (load-bearing half)
        checks.append((
            "ancestor head, changed fingerprint -> reject",
            binds({"source_head": head_a, "source_tree_fingerprint": "OLD"}, live),
            False,
        ))
        # 4. divergent head (sibling branch) + exact fingerprint -> reject
        checks.append((
            "divergent head, exact fingerprint -> reject",
            binds({"source_head": head_side, "source_tree_fingerprint": "FP"}, live),
            False,
        ))
        # 5. unknown/garbage head -> reject, no crash
        checks.append((
            "unknown head -> reject",
            binds(
                {"source_head": "0" * 40, "source_tree_fingerprint": "FP"}, live
            ),
            False,
        ))
        # 6. missing head -> reject, no crash
        checks.append((
            "missing head -> reject",
            binds({"source_tree_fingerprint": "FP"}, live),
            False,
        ))
        # 7. ancestor head, but HEAD that does not exist in the repo at all
        #    (a receipt from an unrelated clone) -> reject
        checks.append((
            "foreign-repo head -> reject",
            binds(
                {"source_head": "9" * 40, "source_tree_fingerprint": "FP"}, live
            ),
            False,
        ))

    failures = [(n, got, want) for n, got, want in checks if got != want]
    for name, got, want in checks:
        print(f"{'ok  ' if got == want else 'FAIL'}  {name}  (got {got}, want {want})")
    if failures:
        print(f"\n{len(failures)} FAILED")
        return 1
    print(f"\nall {len(checks)} binding cases pass")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
