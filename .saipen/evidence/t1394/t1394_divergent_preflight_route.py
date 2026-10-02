"""Does the shape-aware routing still protect the DIVERGENT conflict?

T-1394's fix made `recovery_preflight` branch on the conflict's shape: it names
the bare `saipen recover` when every unfinished target still matches the plan,
and `saipen recover resolve --resolution <accept_live|replan>` when a target's
live bytes match neither its before nor its after hash. The second branch is the
one that must NOT have been widened, because bare recover would overwrite a
third party's write.

T-1400's harness proves bare recover refuses on this shape, but it injects its
divergence into `.saipen/LOG.md` as a non-grammar line, so the immutable-ledger
validator rejects the tree with HISTORY_LEDGER_CORRUPT before recovery is ever
reached. That answers a different question. This harness puts the same divergent
bytes into `BOARD.md` -- a validated file -- as a LEGAL board line, so the tree
passes validation and the probe reaches `recovery_preflight`.

Steps, all public CLI in a subprocess against a scratch tree:

  1  init, ticket, claim
  2  transition BUILD, no lock            -> negative control, must be ok
  3  hold .saipen/STATE.md, transition    -> the OSError branch, op is half-applied
  4  release the lock, then rewrite BOARD.md with a third party's line
     -> the LOG target's planned bytes are now unreachable, i.e. DIVERGENT
  5  retry the identical command           -> what does preflight name now?

The assertion is on the ROUTE, and it is checked in the shape the fix must not
have changed: `canonical_next_command` must be the resolve form, must not be the
bare `saipen recover`, and the third party's line must still be in the file.

The engine is read, never written.
"""

from __future__ import annotations

import json
import pathlib
import shutil
import subprocess
import sys

SAIPEN = r"C:\Users\vac34\AppData\Local\saipen\scheduled-source\bin\saipen.cmd"
ROOT = pathlib.Path("build/t1394/divergent")
MARKER = "DO NOT OVERWRITE"


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
            "raw": (proc.stdout or proc.stderr or "")[:400],
            "exit": proc.returncode,
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
        "scratch ticket for the divergent-shape routing probe",
        "--verify",
        "the preflight route is recorded",
    )
    out["claim"] = cli("claim", "T-1", "--explicit")

    out["control"] = cli("transition", "BUILD", "T-1", "control arm, no lock")
    out["control_ok"] = bool(out["control"].get("ok"))

    state = ROOT / ".saipen" / "STATE.md"
    handle = open(state, "r+b")
    try:
        oserr = cli("transition", "VERIFY", "T-1", "arm with STATE held")
    finally:
        handle.close()
    out["half_applied"] = {
        "ok": oserr.get("ok"),
        "code": oserr.get("code"),
        "recovery_required": oserr.get("recovery_required"),
        "detail": (oserr.get("detail") or oserr.get("message") or "")[:200],
    }
    op = oserr.get("op_id")

    # The lock is gone. A third party now rewrites the target the plan still
    # needs to write, so its live bytes match NEITHER its before nor its after
    # hash -- the divergent shape, reached without touching the LOG ledger.
    board = ROOT / ".saipen" / "BOARD.md"
    # Diverge BOARD by rewriting the text of the line that is ALREADY allocated
    # (T-1), rather than adding a new ticket line. A fresh `T-9001` line fails
    # CORE-003 -- ticket identity comes from a canonical allocation event, not
    # from a line that merely looks like a ticket. Two earlier attempts failed
    # for reasons unrelated to routing: appending landed in BLOCKED (a ticket
    # line there needs a non-empty `blocker:`), and DOING is the active-ticket
    # slot (a foreign line there collides with STATE.task). Both are the same
    # lesson: an injection into a validated file must be a VALID change, or the
    # validator rejects the tree and the probe measures the validator instead.
    text = board.read_text(encoding="utf-8")
    line = next(
        (l for l in text.splitlines() if l.startswith("- [") and "] T-1 " in l),
        None,
    )
    if line is None:
        raise AssertionError("no allocated T-1 line on the scratch board to diverge")
    # Into the DESCRIPTION, before the first field pipe. Appending after the
    # fields lands inside `claim_time: <stamp>` and the validator reads the
    # stamp as invalid, which is a rejection about my edit's placement, not
    # about the routing. The description is free text; the fields are not.
    head, sep, tail = line.partition(" | ")
    board.write_text(
        text.replace(line, head + " -- DO NOT OVERWRITE" + sep + tail, 1), encoding="utf-8"
    )
    out["third_party_write"] = {
        "file": ".saipen/BOARD.md",
        "diverged_line": line[:80],
        "marker": "DO NOT OVERWRITE",
        "bytes": board.stat().st_size,
    }

    probe = cli("transition", "VERIFY", "T-1", "probe the divergent shape")
    out["preflight"] = {
        "ok": probe.get("ok"),
        "code": probe.get("code"),
        "conflict_diverged": probe.get("conflict_diverged"),
        "canonical_next_command": probe.get("canonical_next_command"),
        "inspect_command": probe.get("inspect_command"),
        "detail": (probe.get("detail") or "")[:320],
    }
    out["op_id"] = op

    board_text = board.read_text(encoding="utf-8")
    named = probe.get("canonical_next_command") or ""
    checks = {
        "the_divergent_shape_is_diverged": probe.get("conflict_diverged") is True,
        "it_names_the_resolve_route": "recover resolve" in named,
        "it_does_not_name_the_bare_recover": named.strip() != "saipen recover",
        "the_third_party_edit_survived": MARKER in board_text,
        "it_still_refuses": probe.get("ok") is False,
    }
    out["checks"] = checks
    out["all_checks_passed"] = all(checks.values())

    out["conclusion"] = (
        "DIVERGENT_SHAPE_STILL_PROTECTED"
        if out["all_checks_passed"]
        else "ROUTING_WIDENED_OR_BYTES_LOST"
    )

    (ROOT.parent / "t1394_divergent_preflight_route.json").write_text(
        json.dumps(out, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(out, indent=2))
    return 0 if out["all_checks_passed"] else 1


if __name__ == "__main__":
    sys.exit(main())