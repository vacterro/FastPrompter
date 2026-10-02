"""T-1400, second arm: a bare `saipen recover` against a CONFLICT whose live
bytes have actually DIVERGED.

T-1398's scratch run already recorded a bare recover on a partial apply
(.saipen/evidence/t1398/repro_run3.json, settle.bare_recover = RECOVERED). That
run's op carried `conflicting_locations: []` -- every target's live bytes matched
either expected_before or planned_after, so settling it lost nothing. It is the
benign case.

The load-bearing case is a CONFLICT where a third party wrote the target: live
bytes match neither expected_before nor planned_after. That is exactly the
situation the documented refusal exists to protect, because roll-forward would
overwrite somebody else's work and destroy the evidence of the overwrite.

This forces that state in a scratch project -- no lock trickery, no timing:
  1. init, transition BUILD                       -> op committed
  2. hold STATE.md, transition BUILD              -> CONFLICT, partial apply
  3. append a third-party line to LOG.md, an applied target
                                              -> live bytes now diverge
  4. inspect, bare recover, inspect again
  5. read LOG.md back: did the third-party line survive?

The engine is never touched; every step is the public CLI in a subprocess with
--project-root pointed at the scratch tree.
"""

from __future__ import annotations

import json
import pathlib
import shutil
import subprocess
import sys

SAIPEN = r"C:\Users\vac34\AppData\Local\saipen\scheduled-source\bin\saipen.cmd"
ROOT = pathlib.Path("build/t1400/scratch")
MARKER = "THIRD-PARTY-LINE-DO-NOT-OVERWRITE\n"


def cli(*args, timeout=180):
    proc = subprocess.run(
        [SAIPEN, *args, "--project-root", str(ROOT), "--json"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError:
        return {
            "ok": False,
            "code": "UNPARSEABLE",
            "stdout": proc.stdout[-800:],
            "stderr": proc.stderr[-400:],
        }


def main():
    if ROOT.exists():
        shutil.rmtree(ROOT)
    ROOT.parent.mkdir(parents=True, exist_ok=True)

    out = {"scratch_root": str(ROOT), "steps": []}

    out["init"] = cli("init")
    out["ticket"] = cli(
        "ticket",
        "add",
        "P1",
        "scratch ticket for the T-1400 divergent-conflict reproduction",
        "--verify",
        "the bare recover answer is recorded",
    )
    out["claim"] = cli("claim", "T-1", "--explicit")
    out["control_transition"] = cli("transition", "BUILD", "T-1", "control arm, no lock")
    out["control_ok"] = bool(out["control_transition"].get("ok"))

    state = ROOT / ".saipen" / "STATE.md"
    log = ROOT / ".saipen" / "LOG.md"

    handle = open(state, "r+b")
    try:
        out["conflicting_transition"] = cli("transition", "VERIFY", "T-1", "arm with STATE held")
    finally:
        handle.close()
    op = out["conflicting_transition"].get("op_id")
    out["conflict_code"] = out["conflicting_transition"].get("code")

    if not op:
        out["conclusion"] = "NO_CONFLICT_PRODUCED"
        print(json.dumps(out, indent=2))
        return 1

    before = log.read_text(encoding="utf-8")
    with log.open("a", encoding="utf-8") as fh:
        fh.write(MARKER)
    out["divergence_injected"] = {
        "file": ".saipen/LOG.md",
        "marker": MARKER.strip(),
        "bytes_before": len(before),
        "bytes_after": len(log.read_text(encoding="utf-8")),
    }

    out["inspect_before"] = cli("recover", "inspect", op)
    out["bare_recover"] = cli("recover")
    out["inspect_after"] = cli("recover", "inspect", op)

    after = log.read_text(encoding="utf-8")
    out["third_party_line_survived"] = MARKER in after
    out["log_bytes_after_recover"] = len(after)

    out["documented_refusal_shape"] = {
        "expected_per_OPS_md_109": "ok=false naming the op with evidence preserved",
        "observed_ok": out["bare_recover"].get("ok"),
        "observed_code": out["bare_recover"].get("code"),
        "names_the_op": op in json.dumps(out["bare_recover"]),
        "evidence_preserved": out["third_party_line_survived"],
    }
    out["status_before"] = out["inspect_before"].get("status")
    out["status_after"] = out["inspect_after"].get("status")
    out["conflicting_locations_before"] = out["inspect_before"].get("conflicting_locations")
    out["conclusion"] = (
        "SETTLED_AND_OVERWROTE"
        if out["third_party_line_survived"] is False
        else "SETTLED_EVIDENCE_PRESERVED"
        if out["bare_recover"].get("ok")
        else "REFUSED"
    )

    (ROOT.parent / "t1400_divergent_conflict.json").write_text(
        json.dumps(out, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
