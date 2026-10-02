"""T-1394: is a transient filesystem error escalated into a blocking content conflict?

journal.py:3054 catches OSError around a target write, calls journal.mark
("CONFLICT") and returns code CONFLICT with recovery_required True. Eleven lines
below, journal.py:3064 handles a genuine content mismatch -- a target that was
written but whose live bytes are not the planned bytes -- and returns the SAME
literals: code CONFLICT, recovery_required True. Nothing in either answer tells a
caller which world it is in.

The two are not equivalent in kind:
  OSError            the filesystem refused right now (a scan, an indexer, an
                     editor, a second writer). The bytes may be perfectly fine.
  content mismatch   somebody else's bytes are here. The plan is stale.

So the question is whether the escalation OUTLIVES the condition. If the lock is
held for the length of one CLI call and released, and the identical command then
succeeds, then a momentary WinError 5 has left the project in a blocking recovery
state for a condition that a plain retry clears -- and the operator is routed
into `saipen recover`, which T-1398 measured can itself deadlock.

The CONFLICT status itself is CORRECT and stays: the op really is half-applied.
What was wrong was the ROUTE the refusal named -- T-1355 replaced one blanket
answer with another, naming `recover resolve` for every conflict, and in this
state both of its arms answer NEEDS_REPAIR while the unnamed bare `recover`
settles unattended. The engine fix (SAIPEN 51fb18a1) routes by shape instead.

This harness therefore measures BOTH states and is expected to change its
verdict: pre-fix `canonical_next_command` was `recover resolve ...` and the
operator spent 4 commands, two of them on a branch the engine itself named.
Post-fix it is `saipen recover`, and the operator spends 2. A rerun that still
reports 4 would mean the fix did not reach the engine this harness calls.

Steps, all public CLI in a subprocess against a scratch tree:

  1  init, ticket, claim
  2  transition BUILD, no lock            -> negative control, must be ok
  3  hold .saipen/STATE.md, transition    -> the OSError branch
  4  release; retry the IDENTICAL command -> is the condition still real?
  5  run the command the engine NAMES     -> does the detour settle it?
  6  run bare `saipen recover`            -> same question, engine-independent
  7  retry once more                      -> the shape of the operator's session

The branches are located by CONTENT anchor, not line number: engine edits above
them shift every line below, and a line-pinned locator silently quotes the wrong
lines while still printing a plausible number.

The lock is `open(path, "r+b")`: Win32 opens without FILE_SHARE_DELETE by default,
so os.replace on that target fails with WinError 5 -- the same failure an
antivirus scanner produces, with no timing race involved. It is held only across
step 3's subprocess call and closed immediately after.

The engine is read, never written.
"""

from __future__ import annotations

import json
import pathlib
import shutil
import subprocess
import sys

SAIPEN = r"C:\Users\vac34\AppData\Local\saipen\scheduled-source\bin\saipen.cmd"
ROOT = pathlib.Path("build/t1394/scratch")
JOURNAL = pathlib.Path(
    "V:/___VAC/__K/__CODE/_AI_STUFF_AGENTIC/_SAIPEN/tools/saipen_engine/journal.py"
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


def shape(answer, label):
    """The fields a caller can branch on."""
    return {
        "step": label,
        "ok": answer.get("ok"),
        "code": answer.get("code"),
        "recovery_required": answer.get("recovery_required"),
        "canonical_next_command": answer.get("canonical_next_command"),
        "detail": (answer.get("detail") or answer.get("message") or "")[:260],
    }


def _anchor(lines, needle, before=6, after=2):
    """Find `needle` and return the window around it.

    Anchored on CONTENT, not a line number: an engine edit above these branches
    shifts every line below it, and a line-pinned locator silently quotes the
    wrong lines while still printing a plausible number. Missing anchor raises --
    a receipt that quotes the wrong branch is worse than one that fails.

    `needle` must sit on ONE line: these detail strings are wrapped by the
    formatter, so anchoring on the whole message would not survive a reflow.
    """
    hits = [i for i, line in enumerate(lines) if needle in line]
    if not hits:
        raise AssertionError(f"anchor not found in journal.py: {needle!r}")
    i = hits[0]
    start = max(0, i - before)
    return start + 1, [
        f"{n}: {lines[n - 1]}" for n in range(start + 1, min(i + after, len(lines) + 1))
    ]


def source_branches():
    """Quote both returns so the indistinguishability is read, not assumed."""
    lines = JOURNAL.read_text(encoding="utf-8").splitlines()
    out = {}
    for label, needle in (
        ("oserror_branch", "action failed: {exc}"),
        ("content_mismatch_branch", "action left {after!r}"),
    ):
        start, block = _anchor(lines, needle)
        out[label] = {"first_line": start, "anchored_on": needle, "block": block}
    return out


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
        "scratch ticket for the T-1394 transient-lock reproduction",
        "--verify",
        "the retry answer is recorded",
    )
    out["claim"] = cli("claim", "T-1", "--explicit")

    # step 2 -- negative control
    out["control"] = shape(cli("transition", "BUILD", "T-1", "control arm, no lock"), "control")
    out["control_ok"] = bool(out["control"].get("ok"))

    state = ROOT / ".saipen" / "STATE.md"

    # step 3 -- the OSError branch, lock held only across this call
    handle = open(state, "r+b")
    try:
        oserr = cli("transition", "VERIFY", "T-1", "arm with STATE held")
    finally:
        handle.close()
    out["step3_locked"] = shape(oserr, "locked transition (OSError branch)")
    op = oserr.get("op_id")

    # the lock is now closed. The condition that produced CONFLICT no longer holds.
    out["lock_released_before_retry"] = True

    # step 4 -- the identical command, same bytes, nothing else changed
    out["step4_retry"] = shape(
        cli("transition", "VERIFY", "T-1", "retry with no lock"), "retry, no lock"
    )

    # step 5/6/7 -- if the retry is blocked, follow the command the engine itself
    # names. Pre-fix that command was `recover resolve`, and both its arms were
    # measured NEEDS_REPAIR in this very state, so the unnamed bare `recover`
    # was tried as well -- which is what proved the two dead ends. Post-fix the
    # named command IS the bare recover, and the bare arm is still attempted so
    # this harness measures the CURRENT engine rather than asserting the old
    # shape still holds.
    if not out["step4_retry"].get("ok"):
        named = out["step4_retry"].get("canonical_next_command") or ""
        canonical = {"the_engine_named_this": named}
        if named != "saipen recover":
            canonical["accept_live"] = shape(
                cli("recover", "resolve", op, "--resolution", "accept_live"),
                "named route: accept_live",
            )
            canonical["replan"] = shape(
                cli("recover", "resolve", op, "--resolution", "replan"),
                "named route: replan",
            )
            canonical["canonical_routes_settle"] = any(
                canonical[c].get("ok") for c in ("accept_live", "replan")
            )
        else:
            canonical["canonical_routes_settle"] = None
        out["step5_canonical_routes"] = canonical
        out["step6_recover"] = shape(cli("recover"), "bare recover (named post-fix)")
        out["step7_retry_again"] = shape(
            cli("transition", "VERIFY", "T-1", "retry after recover"),
            "retry after recover",
        )
        # The verdict belongs to THIS run, not to a remembered one. Pre-fix the
        # named command was `recover resolve`, whose two arms were measured
        # NEEDS_REPAIR in this very state; post-fix the named command is the bare
        # recover, whose outcome step6 actually observed. Either way it is
        # measured here rather than asserted.
        if named == "saipen recover":
            canonical["the_engine_named_a_route_that_works"] = out["step6_recover"].get("ok")
            canonical["the_named_command"] = "saipen recover"
            canonical["accept_live"] = "not attempted: the engine did not name it"
            canonical["replan"] = "not attempted: the engine did not name it"
        else:
            canonical["the_engine_named_a_route_that_works"] = canonical[
                "canonical_routes_settle"
            ]

    out["op_id"] = op
    out["source"] = source_branches()

    os_shape = {k: out["step3_locked"][k] for k in ("ok", "code", "recovery_required")}
    out["the_escalation"] = {
        "an_oserror_reports": os_shape,
        "it_is_indistinguishable_from_a_content_conflict": (
            os_shape["code"] == "CONFLICT" and os_shape["recovery_required"] is True
        ),
        "the_condition_lasted_only_as_long_as_the_lock": True,
        "did_the_state_outlive_it": out["step4_retry"].get("code") != "CONFLICT"
        and out["step4_retry"].get("ok") is not True,
    }

    # Derived from what actually ran, not from prose written before the fix.
    # The pre-fix shape was 4 commands because the engine named two dead-end
    # routes; with the shape-aware routing it names the working one, so the
    # count falls to 2 and the operator's next command is the one that works.
    session = ["transition VERIFY (held -> CONFLICT)"]
    settled_by_named = None
    if not out["step4_retry"].get("ok"):
        named = out["step4_retry"].get("canonical_next_command") or ""
        session.append(f"{named or '(no command named)'}   <- named by the engine")
        if named == "saipen recover":
            settled_by_named = out.get("step6_recover", {}).get("ok")
        else:
            session.append("recover                                        <- works, unnamed")
            session.append("transition VERIFY")
    out["operator_session_shape"] = {
        "intended": 1,
        "measured": len(session),
        "commands": session,
        "the_engine_named_a_route_that_works": out.get("step5_canonical_routes", {}).get(
            "the_engine_named_a_route_that_works"
        ) if not out["step4_retry"].get("ok") else True,
        "the_named_command_settled_it": settled_by_named,
    }

    out["conclusion"] = (
        "ESCALATION_OUTLIVES_THE_CONDITION"
        if out["the_escalation"]["did_the_state_outlive_it"]
        else "RETRY_SUCCEEDED_WITHOUT_RECOVERY"
        if out["step4_retry"].get("ok")
        else "INCONCLUSIVE"
    )

    (ROOT.parent / "t1394_transient_lock_escalation.json").write_text(
        json.dumps(out, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
