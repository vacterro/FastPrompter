"""T-1362 acceptance check: does this checkout bind its own closure evidence?

Self-contained on purpose. `t1362_oracle.py` needs the pre-fix debt.py backup
to prove the RED half, and that backup lives in the gitignored build/ tree, so
it cannot run in a clone. This check needs nothing outside the repository and
tests the thing T-1362 actually shipped:

    the ancestor-tolerant binding admits this checkout's own receipts

It reads the committed re-verification receipts, and asserts that every
current-cycle PASS receipt binds to the live tree -- the head may be an
ancestor, the fingerprint must match exactly. A regression to HEAD equality
makes this fail as soon as a protocol-only commit lands, which is precisely
the treadmill T-1362 removed.

Exits non-zero on any failure, so it can serve as a reverify command.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, r"C:\Users\vac34\.agents\skills\saipen\tools")
from saipen_engine import debt  # noqa: E402

ROOT = Path(__file__).resolve().parents[3]
REVERIFY = ROOT / ".saipen" / "recovery" / "conformance" / "reverify"


def main() -> int:
    identity = debt._source_identity(ROOT)
    head = (identity.get("source_head") or "")[:10]
    print(f"live head {head}")
    print(f"live fingerprint {identity.get('source_tree_fingerprint')}")

    receipts = sorted(REVERIFY.glob("RV-*.json"))
    if not receipts:
        print("FAIL no re-verification receipts found")
        return 1

    bound, rejected = [], []
    for path in receipts:
        try:
            receipt = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if "PASS" not in str(receipt.get("verdict")):
            continue
        if debt._receipt_binds_current_tree(receipt, identity, ROOT):
            bound.append((receipt.get("work"), path.name))
        else:
            rejected.append((receipt.get("work"), path.name, receipt.get("source_head"), receipt.get("source_tree_fingerprint")))

    print(f"committed PASS receipts: {len(bound) + len(rejected)}; bound: {len(bound)}")

    # A refused receipt is only a REGRESSION if the evidence still describes
    # the live code. An ancestor head whose fingerprint has moved is correctly
    # stale -- the code really did change since it was minted -- and saying so
    # is the fingerprint half working, not a defect.
    import subprocess

    regressions = []
    for work, name, src, fp in rejected:
        if fp != identity.get("source_tree_fingerprint"):
            continue  # stale evidence about older code; expected
        anc = subprocess.run(
            ["git", "-C", str(ROOT), "merge-base", "--is-ancestor",
             str(src), identity["source_head"]],
            capture_output=True,
        ).returncode == 0
        if anc:
            regressions.append((work, name, src))

    stale = len(rejected) - len(regressions)
    print(f"  refused: {len(rejected)} ({stale} fingerprint-stale, "
          f"{len(regressions)} regressions)")
    if regressions:
        for work, name, src in regressions:
            print(f"FAIL {name} ({work}) matches the live fingerprint and is an "
                  f"ancestor-stamped receipt that still refused to bind")
        return 1

    if not bound:
        print("FAIL no receipt binds this checkout -- the binding admits nothing")
        return 1

    print(f"PASS {len(bound)} current-cycle receipts bind this checkout")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())