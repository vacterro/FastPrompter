"""T-1395 audit: does the improve supersession path constrain a replacement by phase?

Claim under test (BOARD.md T-1395): "a stale COMPLETE seat can only be superseded by
a replacement minted in the same phase".

Negative control: the audit also reports the count of `phase` occurrences in the WHOLE
improve module. A non-zero total that is attributable to this path would mean the grep is
live and a zero in the path would be meaningful; a total of exactly the known
phase_docs inventory lines means the path has no phase concept to grep for.
"""
from __future__ import annotations

import ast
import json
import re
from pathlib import Path

COPIES = [
    "V:/___VAC/__K/__CODE/_AI_STUFF_AGENTIC/_SAIPEN/tools/improve.py",
    "C:/Users/vac34/AppData/Local/saipen/scheduled-source/tools/improve.py",
]
# every def that can participate in choosing or applying a supersession replacement
PATH_DEFS = (
    "classify_cycle_seat",
    "_replacement_for",
    "reconcile_cycle",
    "resolve_stale_complete_seat",
    "retire_seat",
    "verify_cycle",
)
# the only phase vocabulary the module is expected to carry
KNOWN_INVENTORY = re.compile(r"phase_docs|saipen/phases/\{phase\}")


def audit(path: str) -> dict:
    src = Path(path).read_text(encoding="utf-8")
    tree = ast.parse(src)
    lines = src.splitlines()
    funcs = {
        n.name: n
        for n in ast.walk(tree)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    whole = [
        {"line": i + 1, "text": line.strip()}
        for i, line in enumerate(lines)
        if re.search("phase", line, re.I)
    ]
    per_def = {}
    for name in PATH_DEFS:
        node = funcs.get(name)
        if node is None:
            per_def[name] = {"present": False, "phase_refs": []}
            continue
        body = lines[node.lineno - 1 : node.end_lineno]
        refs = [
            {"line": node.lineno + i, "text": line.strip()}
            for i, line in enumerate(body)
            if re.search("phase", line, re.I)
        ]
        per_def[name] = {"present": True, "lineno": node.lineno, "phase_refs": refs}
    path_refs = [
        r for d in per_def.values() for r in d.get("phase_refs", [])
    ]
    unaccounted = [
        r for r in whole
        if not KNOWN_INVENTORY.search(r["text"]) and r not in path_refs
    ]
    return {
        "path": path,
        "bytes": len(src.encode("utf-8")),
        "whole_module_phase_occurrences": len(whole),
        "whole_module_occurrences": whole,
        "supersession_path": {
            name: {
                "present": d["present"],
                "lineno": d.get("lineno"),
                "phase_ref_count": len(d.get("phase_refs", [])),
                "phase_refs": d.get("phase_refs", []),
            }
            for name, d in per_def.items()
        },
        "phase_refs_in_supersession_path": len(path_refs),
        "unaccounted_phase_occurrences": unaccounted,
    }


report = {
    "harness": "t1395_phase_audit.py",
    "ticket": "T-1395",
    "claim_under_test": (
        "a stale COMPLETE seat can only be superseded by a replacement minted "
        "in the same phase"
    ),
    "method": (
        "AST-locate every function that can choose or apply a supersession "
        "replacement, then count case-insensitive 'phase' occurrences in each "
        "body and in the module as a whole."
    ),
    "negative_control": (
        "the whole-module count must be non-zero and fully explained by the "
        "phase_docs inventory lines; otherwise a zero path count would prove "
        "nothing. See t1395_control.py for the stronger inversion."
    ),
    "copies": [audit(p) for p in COPIES],
}
report["verdict"] = (
    "NOT_REPRODUCED"
    if all(
        c["phase_refs_in_supersession_path"] == 0
        and not c["unaccounted_phase_occurrences"]
        and c["whole_module_phase_occurrences"] > 0
        for c in report["copies"]
    )
    else "REPRODUCED"
)

if __name__ == "__main__":
    print(json.dumps(report, indent=2))
