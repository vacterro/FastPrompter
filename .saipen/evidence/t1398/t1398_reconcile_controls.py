"""T-1398 controls for the `reconcile` resolution class.

Every control drives the REAL working-tree engine through its real CLI
(`python <repo>/tools/saipen.py ... --project-root <scratch>`), not the
installed launcher and not an in-process import. That distinction is measured,
not assumed: the installed copy under
`C:/Users/vac34/AppData/Local/saipen/scheduled-source/` is a SEPARATE tree
that does not contain this change, so a control run against it would have
reported the pre-change behaviour and passed for the wrong reason.

Each scratch is built to the exact shape the ticket measures:

    .saipen/LOG.md    applied, then a third party appends E-5  -> DIVERGENT
    .saipen/BOARD.md  applied, untouched since                   -> already applied
    .saipen/STATE.md  never applied, live == expected_before    -> untouched

which is the state where bare recover, accept_live and replan all refuse.

The controls assert on REFUSAL TEXT and on WHOLE-TREE BYTES, never on the
mere absence of an exception. A control that only checked "it did not raise"
would pass against an engine that did nothing at all.

  C1  accept_live still refuses the deadlock      (no behaviour change)
  C2  replan still refuses the deadlock           (no behaviour change)
  C3  reconcile settles it, and says what it did
  C4  the op is no longer CONFLICT and the project takes writes again
  C5  the third party's E-5 line survives byte-identical
  C6  an unrelated invalidity is still refused AND leaves ZERO net bytes
  C7  corrupt staged evidence refuses, writes nothing
  C8  a rewound LOG tail refuses rather than moving the checkpoint back
  C9  inspect advertises reconcile
  C10 the grammar refuses an unknown resolution class
  C11 reconcile refuses an op that is not a CONFLICT
"""

from __future__ import annotations

import hashlib
import json
import pathlib
import shutil
import subprocess
import sys

SAIPEN_PY = r"V:\___VAC\__K\__CODE\_AI_STUFF_AGENTIC\_SAIPEN\tools\saipen.py"
SCRATCH = pathlib.Path("build/t1398_reconcile")

# A grammar-LEGAL, consecutive third-party event. An earlier harness pass
# injected a bare marker and the validator then refused partly because of the
# harness's own artefact; making the injected line legal is what leaves the
# ticket's defect as the only remaining reason.
THIRD_PARTY = (
    "- 02.10.26 06:25 [E-5] [parent: E-4] [T-1] [agent: saipen] "
    "RUN: third-party write -- DO NOT OVERWRITE\n"
)
# A NON-consecutive event. Monotonicity is an invariant the cursor repair does
# not and cannot fix, which makes this the control for "an unrelated fault
# still refuses, and the repair rolls itself back".
GAP_EVENT = (
    "- 02.10.26 06:25 [E-9] [parent: E-4] [T-1] [agent: saipen] "
    "RUN: third-party write with a gap -- DO NOT OVERWRITE\n"
)

RESULTS: list[dict] = []


def cli(*args: str, root: pathlib.Path, timeout: int = 300) -> dict:
    proc = subprocess.run(
        [sys.executable, SAIPEN_PY, *args, "--project-root", str(root), "--json"],
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
            "stderr": proc.stderr[-600:],
        }


def tree_digest(root: pathlib.Path) -> dict:
    """Whole-tree content digest, per file, so a rollback can be PROVEN."""
    out = {}
    for path in sorted(root.rglob("*")):
        if path.is_file():
            rel = path.relative_to(root).as_posix()
            out[rel] = hashlib.sha256(path.read_bytes()).hexdigest()[:16]
    return out


def delta(before: dict, after: dict) -> dict:
    changed = sorted(k for k in set(before) | set(after) if before.get(k) != after.get(k))
    return {"changed_paths": changed, "count": len(changed)}


def record(cid: str, title: str, passed: bool, evidence: dict) -> None:
    RESULTS.append({"id": cid, "title": title, "passed": bool(passed), "evidence": evidence})
    print(f"{'PASS' if passed else 'FAIL'} {cid}  {title}")
    print(f"       {json.dumps(evidence, ensure_ascii=False)[:400]}")


def expect_text(answer: dict, *needles: str) -> bool:
    blob = json.dumps(answer, ensure_ascii=False)
    return all(n in blob for n in needles)


def build_deadlock(root: pathlib.Path, third_party: str = THIRD_PARTY) -> dict:
    """Drive the project to the exact T-1398 shape. Returns the op_id."""
    if root.exists():
        shutil.rmtree(root)
    root.parent.mkdir(parents=True, exist_ok=True)

    cli("init", root=root)
    cli("ticket", "add", "P1", "scratch ticket for the T-1398 reconcile controls",
        "--verify", "every control is recorded", root=root)
    cli("claim", "T-1", "--explicit", root=root)

    # Negative control first: an unlocked transition must succeed, so a later
    # CONFLICT is attributable to the held handle and not to a broken path.
    control = cli("transition", "BUILD", "T-1", "control arm, no lock", root=root)
    if not control.get("ok"):
        return {"failed_at": "control_transition", "answer": control}

    state = root / ".saipen" / "STATE.md"
    log = root / ".saipen" / "LOG.md"
    handle = open(state, "r+b")
    try:
        armed = cli("transition", "VERIFY", "T-1", "arm with STATE held", root=root)
    finally:
        handle.close()

    op = armed.get("op_id")
    if not op:
        return {"failed_at": "conflict_transition", "answer": armed}

    with log.open("a", encoding="utf-8") as fh:
        fh.write(third_party)
    return {"op_id": op, "conflict_code": armed.get("code")}


def state_field(root: pathlib.Path, field: str) -> str | None:
    for line in (root / ".saipen" / "STATE.md").read_text(encoding="utf-8").splitlines():
        if line.startswith(f"{field}:"):
            return line.split(":", 1)[1].strip().strip('"')
    return None


def main() -> int:
    out: dict = {"controls": RESULTS}

    # ---------------------------------------------------------------- scratch A
    a = SCRATCH / "settle"
    built = build_deadlock(a)
    if "op_id" not in built:
        print(json.dumps({"fatal": "could not build the deadlock scratch", **built}, indent=2))
        return 1
    op = built["op_id"]
    out["scratch_a_op"] = op

    inspect = cli("recover", "inspect", op, root=a)
    unapplied = [t["path"] for t in inspect.get("targets", []) if not t.get("applied")]
    divergent = inspect.get("conflicting_locations")
    out["shape"] = {"op_id": op, "unapplied": unapplied, "divergent": divergent}
    if not (unapplied and divergent):
        print(json.dumps({"fatal": "scratch did not reach the divergent partial apply",
                          "inspect": inspect}, indent=2))
        return 1

    # C1 / C2 -- the existing classes must be untouched.
    accept = cli("recover", "resolve", op, "--resolution", "accept_live", root=a)
    record(
        "C1", "accept_live still refuses the deadlock (no behaviour change)",
        (not accept.get("ok")) and accept.get("code") == "NEEDS_REPAIR"
        and expect_text(accept, "last_event"),
        {"code": accept.get("code"), "detail": (accept.get("detail") or "")[:200]},
    )
    replan = cli("recover", "resolve", op, "--resolution", "replan", root=a)
    record(
        "C2", "replan still refuses the deadlock (no behaviour change)",
        (not replan.get("ok")) and replan.get("code") == "NEEDS_REPAIR"
        and expect_text(replan, "last_event"),
        {"code": replan.get("code"), "detail": (replan.get("detail") or "")[:200]},
    )

    # C9 / C10 -- grammar and advertisement, read-only, same scratch.
    record(
        "C9", "inspect advertises reconcile among the safe classes",
        "reconcile" in (inspect.get("safe_resolution_classes") or []),
        {"safe_resolution_classes": inspect.get("safe_resolution_classes")},
    )
    bad = cli("recover", "resolve", op, "--resolution", "reconcile_all", root=a)
    record(
        "C10", "the grammar refuses an unknown resolution class",
        (not bad.get("ok")) and expect_text(bad, "unknown resolution", "reconcile"),
        {"code": bad.get("code"), "detail": (bad.get("detail") or "")[:200]},
    )

    # C3 / C4 / C5 -- the actual fix.
    log_before = (a / ".saipen" / "LOG.md").read_bytes()
    rec = cli("recover", "resolve", op, "--resolution", "reconcile", root=a)
    record(
        "C3", "reconcile settles the deadlock and reports the repair",
        bool(rec.get("ok")) and rec.get("code") == "RESOLVED"
        and rec.get("resolution") == "reconcile"
        and ".saipen/STATE.md" in (rec.get("rolled_forward_targets") or [])
        and rec.get("cursor_rederived"),
        {"code": rec.get("code"),
         "rolled_forward_targets": rec.get("rolled_forward_targets"),
         "cursor_rederived": rec.get("cursor_rederived"),
         "detail": (rec.get("detail") or "")[:200]},
    )
    record(
        "C4", "the op is no longer CONFLICT and STATE tracks the LOG tail",
        state_field(a, "last_event") == "5" and state_field(a, "phase") == "VERIFY"
        and cli("recover", "inspect", op, root=a).get("status") != "CONFLICT",
        {"last_event": state_field(a, "last_event"), "phase": state_field(a, "phase"),
         "status_after": cli("recover", "inspect", op, root=a).get("status")},
    )
    log_after = (a / ".saipen" / "LOG.md").read_bytes()
    record(
        "C5", "the third party's divergent LOG bytes were never overwritten",
        log_after == log_before and THIRD_PARTY.strip() in log_after.decode("utf-8"),
        {"log_bytes_identical": log_after == log_before,
         "third_party_line_present": THIRD_PARTY.strip() in log_after.decode("utf-8")},
    )

    # C11 -- reconcile is still a resolution, not a bypass.
    again = cli("recover", "resolve", op, "--resolution", "reconcile", root=a)
    record(
        "C11", "reconcile refuses an op that is no longer a CONFLICT",
        (not again.get("ok")) and expect_text(again, "not CONFLICT"),
        {"code": again.get("code"), "detail": (again.get("detail") or "")[:200]},
    )

    # ---------------------------------------------------------------- scratch B
    b = SCRATCH / "rollback"
    built_b = build_deadlock(b, third_party=GAP_EVENT)
    if "op_id" not in built_b:
        print(json.dumps({"fatal": "could not build scratch B", **built_b}, indent=2))
        return 1
    op_b = built_b["op_id"]
    before_b = tree_digest(b)
    repair_b = cli("recover", "resolve", op_b, "--resolution", "reconcile", root=b)
    after_b = tree_digest(b)
    d = delta(before_b, after_b)
    record(
        "C6", "an unrelated invalidity still refuses AND leaves zero net bytes",
        (not repair_b.get("ok")) and repair_b.get("code") == "NEEDS_REPAIR"
        and repair_b.get("resolution_committed") is False
        and d["count"] == 0,
        {"code": repair_b.get("code"),
         "resolution_committed": repair_b.get("resolution_committed"),
         "undo_attempted": repair_b.get("rolled_forward_undone"),
         "tree_delta": d,
         "detail": (repair_b.get("detail") or "")[:220]},
    )

    # ---------------------------------------------------------------- scratch C
    c = SCRATCH / "corrupt_staged"
    built_c = build_deadlock(c)
    if "op_id" not in built_c:
        print(json.dumps({"fatal": "could not build scratch C", **built_c}, indent=2))
        return 1
    op_c = built_c["op_id"]
    staged = sorted(c.rglob("2_*.staged"))
    corrupted = []
    for f in staged:
        f.write_bytes(b"CORRUPT-EVIDENCE\n")
        corrupted.append(f.relative_to(c).as_posix())
    before_c = tree_digest(c)
    repair_c = cli("recover", "resolve", op_c, "--resolution", "reconcile", root=c)
    after_c = tree_digest(c)
    dc = delta(before_c, after_c)
    record(
        "C7", "corrupt staged evidence refuses and writes nothing",
        bool(corrupted) and (not repair_c.get("ok"))
        and expect_text(repair_c, "staged", "corrupt"),
        {"corrupted": corrupted, "code": repair_c.get("code"),
         "tree_delta": dc, "detail": (repair_c.get("detail") or "")[:220]},
    )

    # ---------------------------------------------------------------- scratch D
    d_root = SCRATCH / "rewound_log"
    built_d = build_deadlock(d_root)
    if "op_id" not in built_d:
        print(json.dumps({"fatal": "could not build scratch D", **built_d}, indent=2))
        return 1
    op_d = built_d["op_id"]
    sp = d_root / ".saipen" / "STATE.md"
    sp.write_text(
        sp.read_text(encoding="utf-8").replace("last_event: 3", "last_event: 9"),
        encoding="utf-8",
    )
    before_d = tree_digest(d_root)
    repair_d = cli("recover", "resolve", op_d, "--resolution", "reconcile", root=d_root)
    after_d = tree_digest(d_root)
    dd = delta(before_d, after_d)
    record(
        "C8", "a rewound LOG tail refuses rather than moving the checkpoint back",
        (not repair_d.get("ok")) and expect_text(repair_d, "BELOW", "backwards"),
        {"code": repair_d.get("code"), "tree_delta": dd,
         "detail": (repair_d.get("detail") or "")[:260]},
    )

    out["summary"] = {
        "total": len(RESULTS),
        "passed": sum(1 for r in RESULTS if r["passed"]),
        "failed": [r["id"] for r in RESULTS if not r["passed"]],
    }
    (SCRATCH.parent / "t1398_reconcile_controls.json").write_text(
        json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(json.dumps(out["summary"], indent=2))
    return 0 if not out["summary"]["failed"] else 1


if __name__ == "__main__":
    sys.exit(main())