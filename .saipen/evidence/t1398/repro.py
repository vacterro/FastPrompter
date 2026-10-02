"""T-1398 deterministic reproduction: a partial apply that cannot be settled.

The 2026-10-02T05:49Z incident in the real project was one sample. This drives
the same code path on purpose, twice, in a scratch project:

  arm A  no lock held      -- the multi-target write completes; the negative
                              control that the harness itself is sound
  arm B  STATE.md held     -- os.replace on that one target fails with
                              WinError 5, exactly the transient the ticket names

Both arms then run the two resolution classes the engine advertises and record
what each one answers, so "cannot be settled" is a measurement and not a
reading of the source.

Nothing here touches the engine; it only calls the public CLI as a subprocess
with --project-root pointed at the scratch tree.
"""
import json
import os
import pathlib
import subprocess
import sys

SAIPEN = r"C:\Users\vac34\AppData\Local\saipen\scheduled-source\bin\saipen.cmd"
ROOT = pathlib.Path(__file__).resolve().parent / "scratch2"


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
        return {"ok": False, "code": "UNPARSEABLE", "stdout": proc.stdout[-800:]}


def phase():
    for line in (ROOT / ".saipen" / "STATE.md").read_text(encoding="utf-8").splitlines():
        if line.startswith("phase:"):
            return line.split(":", 1)[1].strip()
    return None


def hold(path):
    """A handle that denies delete sharing, so os.replace on it fails.

    Win32 opens without FILE_SHARE_DELETE by default, so an open handle is
    enough to make the atomic rename fail -- the same failure an antivirus
    scanner or a second writer produces.
    """
    return open(path, "r+b")


def run_arm(name, hold_state):
    record = {"arm": name, "holds_STATE": hold_state}
    record["phase_before"] = phase()
    handle = None
    if hold_state:
        state = ROOT / ".saipen" / "STATE.md"
        handle = hold(state)
        record["lock_confirmed"] = {
            "opened": str(state),
            "size": os.fstat(handle.fileno()).st_size,
        }
    try:
        record["transition"] = cli("transition", "BUILD", "T-1", f"{name} arm")
    finally:
        if handle is not None:
            handle.close()
    record["phase_after"] = phase()
    return record


def settle(conflict_id):
    """Both advertised classes, then the route that is not advertised."""
    out = {
        "accept_live": cli("recover", "resolve", conflict_id, "--resolution", "accept_live"),
        "replan": cli("recover", "resolve", conflict_id, "--resolution", "replan"),
    }
    out["bare_recover"] = cli("recover")
    return out


def main():
    out = {"scratch_root": str(ROOT), "arms": []}

    arm_a = run_arm("control (no lock)", hold_state=False)
    out["arms"].append(arm_a)
    out["control_ok"] = bool(arm_a["transition"].get("ok"))
    out["control_phase_moved"] = arm_a["phase_before"] != arm_a["phase_after"]

    arm_b = run_arm("partial apply (STATE held)", hold_state=True)
    out["arms"].append(arm_b)
    out["partial_applied"] = arm_b["transition"].get("code")

    op = arm_b["transition"].get("op_id")
    if op:
        out["conflict_op"] = op
        out["inspect"] = cli("recover", "inspect", op)
        out["new_write_blocked"] = cli("checkpoint", "RUN", "T-1", "probe while blocked")
        out["settle"] = settle(op)
        out["phase_after_settle"] = phase()
        out["validate"] = cli("validate")

    (ROOT.parent / "repro_result.json").write_text(
        json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
