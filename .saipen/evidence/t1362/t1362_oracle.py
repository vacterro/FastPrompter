"""RED/GREEN oracle for T-1362 (VERIFY-ORACLE-01).

A gate that cannot fail is not a gate. This runs the identical binding cases
from _t1362_binding_check.py against BOTH engines:

  RED   -- build/_debt.py.backup-E3717 (pre-fix, HEAD equality):
           the ancestor case must be REJECTED, because that rejection is the
           exact defect T-1362 exists to remove.
  GREEN -- the live engine: every case must behave as specified.

The RED half is the true pre-fix subject recovered from the recorded backup,
not a simulated failure.
"""

import importlib.machinery
import importlib.util
import subprocess
import sys
import tempfile
from pathlib import Path

TOOLS = r"C:\Users\vac34\.agents\skills\saipen\tools"
# The pre-fix subject is the recorded backup of debt.py taken before the
# T-1362 edit. It lives in the repo's gitignored build/ (the live engine path
# is not under version control), so look there first and beside this script
# second -- a committed copy of this oracle must still find it.
_BACKUP_NAMES = ("_debt.py.backup-E3717",)
_HERE = Path(__file__).resolve().parent
_REPO_BUILD = _HERE.parents[2] / "build"
BACKUP = next(
    (c for n in _BACKUP_NAMES for c in (_REPO_BUILD / n, _HERE / n) if c.exists()),
    _REPO_BUILD / _BACKUP_NAMES[0],
)
LIVE = Path(TOOLS) / "saipen_engine" / "debt.py"

sys.path.insert(0, TOOLS)
sys.path.insert(0, str(Path(TOOLS) / "saipen_engine"))


def load(name, path):
    # debt.py does "from . import findings", so the module must be loaded under
    # the saipen_engine package name for that relative import to resolve. The
    # backup's ".py" is only mid-name, so the loader is supplied explicitly.
    import saipen_engine  # noqa: F401  (make the parent package importable)

    qualname = f"saipen_engine.{name}"
    spec = importlib.util.spec_from_file_location(
        qualname,
        path,
        loader=importlib.machinery.SourceFileLoader(qualname, str(path)),
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[qualname] = mod
    spec.loader.exec_module(mod)
    return mod


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


def cases(root, head_a, head_b, head_side):
    live = {"source_head": head_b, "source_tree_fingerprint": "FP"}
    return [
        ("exact head -> accept", {"source_head": head_b,
                                  "source_tree_fingerprint": "FP"}, live, True),
        ("ancestor head -> accept", {"source_head": head_a,
                                     "source_tree_fingerprint": "FP"}, live, True),
        ("ancestor head, changed tree -> reject", {"source_head": head_a,
                                                    "source_tree_fingerprint": "OLD"},
         live, False),
        ("divergent head -> reject", {"source_head": head_side,
                                      "source_tree_fingerprint": "FP"}, live, False),
        ("missing head -> reject", {"source_tree_fingerprint": "FP"}, live, False),
    ]


def run(mod, spec):
    """Apply the module's own binding rule (pre-fix: inline equality; post: helper)."""
    out = []
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        git(root, "init", "-q", "-b", "main")
        git(root, "config", "user.email", "t@t.t")
        git(root, "config", "user.name", "t")
        head_a = commit(root, "a")
        head_b = commit(root, "b")
        git(root, "checkout", "-q", "-b", "side", head_a)
        head_side = commit(root, "side")
        git(root, "checkout", "-q", "main")

        for name, receipt, identity, want in spec(root, head_a, head_b, head_side):
            helper = getattr(mod, "_receipt_binds_current_tree", None)
            if helper is not None:
                got = helper(receipt, identity, root)
            else:  # pre-fix rule, transcribed from the backup's source
                got = (
                    receipt.get("source_head") == identity["source_head"]
                    and receipt.get("source_tree_fingerprint")
                    == identity["source_tree_fingerprint"]
                )
            out.append((name, got, want))
    return out


def main():
    if not BACKUP.exists():
        print(f"FAIL  pre-fix backup missing: {BACKUP}")
        return 1

    pre = run(load("debt_pre", BACKUP), cases)
    post = run(load("debt_post", LIVE), cases)

    red_ancestor = [g for n, g, _ in pre if n.startswith("ancestor head ->")]
    green_ok = all(g == w for _, g, w in post)

    print("PRE-FIX  (HEAD equality, backup %s)" % BACKUP.name)
    for n, g, w in pre:
        print(f"  {'ok  ' if g == w else 'DIFF'}  {n}  (got {g}, want {w})")
    print("POST-FIX (ancestor-tolerant, live debt.py)")
    for n, g, w in post:
        print(f"  {'ok  ' if g == w else 'FAIL'}  {n}  (got {g}, want {w})")

    red = red_ancestor == [False]
    print(f"\nRED half   ancestor rejected by pre-fix engine: {red}")
    print(f"GREEN half all post-fix cases as specified:     {green_ok}")
    if red and green_ok:
        print("PAIR ADMISSIBLE: the oracle fails on the pre-fix subject and passes after.")
        return 0
    print("PAIR INADMISSIBLE")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
