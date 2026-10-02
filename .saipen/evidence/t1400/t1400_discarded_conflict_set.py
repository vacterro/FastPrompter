"""T-1400: the bare `saipen recover` path binds the CONFLICT set and never reads it.

OPS.md:109 promises `saipen recover` "REFUSEs a conflict with the op named and
evidence preserved rather than hiding it", and `auto_recover_pending`'s own
docstring says "A conflict stops the run with the conflicting op named and its
evidence preserved". Both statements describe a refusal that no code performs:
the function that receives the conflict set does not read it back.

This measures the gap structurally -- an AST walk that finds every function
which binds a conflict-named variable and never loads it -- because the gap is
exactly "computed, then discarded", and a grep cannot tell a deliberate throwaway
from a computed value nobody remembered to use.

Negative control: inject one read of `_conflicts` into a scratch copy of
`auto_recover_pending` and assert the detector stops flagging it. A control that
still flagged would mean the detector reports a defect that is really its own.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

COPIES = {
    "saipen.py": "V:/___VAC/__K/__CODE/_AI_STUFF_AGENTIC/_SAIPEN/tools/saipen.py",
    "journal.py": ("V:/___VAC/__K/__CODE/_AI_STUFF_AGENTIC/_SAIPEN/tools/saipen_engine/journal.py"),
}


def discarded_conflict_binds(path: str) -> list[dict]:
    """Functions that STORE a conflict-named name and never LOAD it."""
    src = Path(path).read_text(encoding="utf-8")
    tree = ast.parse(src)
    out = []
    for fn in [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]:
        stores: dict[str, list[int]] = {}
        loads: dict[str, list[int]] = {}
        for node in ast.walk(fn):
            if isinstance(node, ast.Name):
                bucket = stores if isinstance(node.ctx, ast.Store) else loads
                bucket.setdefault(node.id, []).append(node.lineno)
        for name, at in sorted(stores.items()):
            if "conflict" in name.lower() and not loads.get(name):
                out.append(
                    {
                        "function": fn.name,
                        "function_lineno": fn.lineno,
                        "bound_name": name,
                        "bound_at_lines": at,
                        "read_back": False,
                    }
                )
    return out


report = {
    "harness": "t1400_discarded_conflict_set.py",
    "ticket": "T-1400",
    "claim_under_test": (
        "the bare `saipen recover` path computes the CONFLICT subset and "
        "discards it, so the refusal OPS.md:109 promises has no code behind it"
    ),
    "method": (
        "AST walk of both engine copies: for every function, collect Name "
        "nodes with Store and Load context; report any conflict-named name "
        "that is stored and never loaded."
    ),
    "copies": {label: discarded_conflict_binds(p) for label, p in COPIES.items()},
}
report["total_discarded_binds"] = sum(len(v) for v in report["copies"].values())

# ---- negative control: inject one read and require the detector to go quiet --
src = Path(COPIES["journal.py"]).read_text(encoding="utf-8")
anchor = "            pending, _conflicts = scan_pending(root)\n"
assert src.count(anchor) == 1, f"anchor not unique: {src.count(anchor)}"
injected = src.replace(anchor, anchor + "            _conflicts_seen = len(_conflicts)\n")
scratch = Path(__file__).resolve().parent / "control_journal_scratch.py"
scratch.write_text(injected, encoding="utf-8")
try:
    after = discarded_conflict_binds(str(scratch))
    # The control asks whether the NAME UNDER TEST is still discarded. Matching on
    # the function alone would be wrong: the injection itself stores
    # `_conflicts_seen`, which the detector is right to flag as a fresh discarded
    # bind -- reporting it as a failed control would be the harness grading itself.
    still = [
        r
        for r in after
        if r["function"] == "auto_recover_pending" and r["bound_name"] == "_conflicts"
    ]
finally:
    scratch.unlink(missing_ok=True)

report["negative_control"] = {
    "injection": "_conflicts_seen = len(_conflicts)",
    "injection_target": "journal.py auto_recover_pending",
    "scoped_to": "the bound name `_conflicts`, not the enclosing function",
    "_conflicts_still_discarded": bool(still),
    "other_binds_the_injection_introduced": [
        {"bound_name": r["bound_name"], "bound_at_lines": r["bound_at_lines"]}
        for r in after
        if r["function"] == "auto_recover_pending" and r["bound_name"] != "_conflicts"
    ],
    "flagged_before_injection": any(
        r["function"] == "auto_recover_pending" and r["bound_name"] == "_conflicts"
        for r in report["copies"]["journal.py"]
    ),
}
report["negative_control"]["auto_recover_pending_still_flagged"] = report["negative_control"].pop(
    "_conflicts_still_discarded"
)
report["negative_control"]["control_passed"] = (
    report["negative_control"]["flagged_before_injection"]
    and not report["negative_control"]["auto_recover_pending_still_flagged"]
)

report["verdict"] = (
    "CONFIRMED"
    if report["total_discarded_binds"] >= 2 and report["negative_control"]["control_passed"]
    else "NOT_CONFIRMED"
)
print(json.dumps(report, indent=2))
