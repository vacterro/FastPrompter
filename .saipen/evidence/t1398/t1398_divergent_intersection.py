"""T-1398 at the intersection: a CONFLICT that is BOTH a partial apply AND divergent.

Two separate measurements already exist, and neither covers their intersection:

  t1398/deterministic_reproduction.json -- a partial apply (STATE.md unapplied,
    live bytes still == expected_before). Both advertised resolution classes
    answered NEEDS_REPAIR. Bare recover answered RECOVERED.

  t1400/t1400_divergent_conflict.json -- a partial apply whose ALREADY-APPLIED
    target .saipen/LOG.md was then written by a third party, so its live bytes
    match neither expected_before nor planned_after. Bare recover REFUSED with
    RECOVERY_CONFLICT and preserved the third party's bytes. The two advertised
    resolution classes were never tried in that state.

The intersection is where a real deadlock would live: the divergent case is the
one bare recover will not touch, and the partial-apply case is the one both
advertised classes reject. If the classes also reject here, the project holds a
conflict that no advertised route settles and the bare route refuses by design.

This builds that state and tries ALL THREE routes in a fixed order, recording
each answer, then checks what survived on disk:

  step 1  init, ticket, claim                (soundness precondition)
  step 2  transition, no lock               (negative control: ok)
  step 3  transition with STATE.md held      -> CONFLICT, partial apply
  step 4  append a third-party line to LOG.md -> divergence on an applied target
  step 5  bare recover, then accept_live, then replan -- each recorded
  step 6  inspect again; report op status and whether the bytes survived

Order matters: bare recover runs FIRST so that a bare recover which SETTLES the
op cannot retroactively make the resolution classes look broken, and so the
refusal case is observed against the untouched state.

The engine is never written to; every step is the public CLI in a subprocess
with --project-root pointed at a scratch tree.
"""

from __future__ import annotations

import json
import pathlib
import shutil
import subprocess
import sys

SAIPEN = r"C:\Users\vac34\AppData\Local\saipen\scheduled-source\bin\saipen.cmd"
ROOT = pathlib.Path("build/t1398_intersection/scratch")

# The third-party write must be a GRAMMAR-LEGAL log event. An earlier attempt
# appended a bare marker string, and the two resolution classes then refused
# partly because "LOG.md:6 not a legal event line" -- an artefact of the
# harness, not the defect under test. Making the injected line legal removes
# that excuse: if accept_live and replan still refuse, the only remaining
# reason is the partial-apply mismatch the ticket is about.
MARKER = (
    "- 02.10.26 06:25 [E-5] [parent: E-4] [T-1] [agent: saipen] "
    "RUN: third-party write -- DO NOT OVERWRITE\n"
)


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


def route(name, answer, op):
    """Classify one settle attempt the way the ticket's claim is stated."""
    return {
        "route": name,
        "ok": answer.get("ok"),
        "code": answer.get("code"),
        "names_the_op": op in json.dumps(answer),
        "detail": (answer.get("detail") or answer.get("message") or "")[:400],
        "settled": bool(answer.get("ok")),
    }


def main():
    if ROOT.exists():
        shutil.rmtree(ROOT)
    ROOT.parent.mkdir(parents=True, exist_ok=True)

    out = {"scratch_root": str(ROOT)}

    out["init"] = cli("init")
    out["ticket"] = cli(
        "ticket",
        "add",
        "P1",
        "scratch ticket for the T-1398 divergent-intersection reproduction",
        "--verify",
        "all three settle routes are recorded",
    )
    out["claim"] = cli("claim", "T-1", "--explicit")

    # step 2 -- negative control
    out["control_transition"] = cli("transition", "BUILD", "T-1", "control arm, no lock")
    out["control_ok"] = bool(out["control_transition"].get("ok"))

    # step 3 -- partial apply
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

    out["op_id"] = op

    # step 4 -- divergence on an ALREADY-APPLIED target
    with log.open("a", encoding="utf-8") as fh:
        fh.write(MARKER)
    out["inspect_before"] = cli("recover", "inspect", op)
    out["conflicting_locations"] = out["inspect_before"].get("conflicting_locations")
    out["unapplied_targets"] = [
        t["path"] for t in out["inspect_before"].get("targets", []) if not t.get("applied")
    ]
    out["state_is_both_partial_and_divergent"] = bool(
        out["conflicting_locations"] and out["unapplied_targets"]
    )

    # step 5 -- all three routes, bare first
    out["routes"] = [
        route("bare_recover", cli("recover"), op),
        route(
            "accept_live",
            cli("recover", "resolve", op, "--resolution", "accept_live"),
            op,
        ),
        route("replan", cli("recover", "resolve", op, "--resolution", "replan"), op),
    ]

    # step 6 -- what is left
    out["inspect_after"] = cli("recover", "inspect", op)
    out["status_after"] = out["inspect_after"].get("status")
    out["third_party_line_survived"] = MARKER in log.read_text(encoding="utf-8")
    out["further_write_blocked"] = cli(
        "checkpoint", "RUN", "T-1", "probe after all three routes"
    ).get("code")

    settled = [r["route"] for r in out["routes"] if r["settled"]]
    refused = [r["route"] for r in out["routes"] if not r["settled"]]
    out["settled_routes"] = settled
    out["refused_routes"] = refused
    out["op_still_conflict"] = out["status_after"] == "CONFLICT"

    if settled:
        out["conclusion"] = "SETTLED_BY " + ",".join(settled)
    elif out["op_still_conflict"]:
        out["conclusion"] = "DEADLOCK_NO_ROUTE_SETTLES"
    else:
        out["conclusion"] = "SETTLED_BY_SOMETHING_ELSE"

    out["verdict_against_the_ticket"] = (
        "the advertised classes dead-end and no other route settles either"
        if out["conclusion"] == "DEADLOCK_NO_ROUTE_SETTLES"
        else "the ticket's claim does not hold in this state"
    )

    (ROOT.parent / "t1398_divergent_intersection.json").write_text(
        json.dumps(out, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
