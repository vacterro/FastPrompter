"""T-1401: do the two shipped gates agree on what a legal SWEEP ledger looks like?

`write_sweep_entry` validates its PROPOSED text with `improve.validate_sweep`
before committing (improve.py:1030-1036). The core conformance gate re-reads
the committed text with its own rule (validate.py:4265-4286). If one accepts a
line the other reds, the writer can put the project into a state its own gate
forbids -- and there is no in-protocol route back, because the duplicate guard
(improve.py:1004-1010) refuses to re-dispose a finding_ref already in the ledger.

This runs BOTH gates on the REAL committed ledger bytes, so the disagreement is
measured on the file that is actually failing the gate, not on a synthetic one.

Negative control: the same two gates on a line carrying reproduced=y. A control
that also disagreed would mean the harness, not the ledger, is broken.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

TOOLS = Path(r"C:/Users/vac34/AppData/Local/saipen/scheduled-source/tools")
sys.path.insert(0, str(TOOLS))

import improve as imp  # noqa: E402

PROJECT = Path(__file__).resolve().parents[3]
LEDGER = PROJECT / ".saipen/improve/imp-vacterro-fastprompter-20261002-2/SWEEP.md"

# The core gate's rule, transcribed from validate.py:4259-4287. Kept as a
# transcription, not an import: validate.py is a 570 KB script whose import
# side effects are not worth paying for a 30-line predicate.
CORE_GATE_RE = re.compile(
    r"^- (IMP-\d+|RUN-\d+/IMP-\d+) \[([A-Z_]+)\]\s+(\S+)\s+report=([^\s]+)\s+reproduced=(\S+)"
)


def core_gate(text: str) -> list[str]:
    """The CONFIRMED arm of the core sweep rule. Returns one string per violation."""
    out = []
    for line_no, line in enumerate(text.splitlines(), 1):
        m = CORE_GATE_RE.match(line.strip())
        if not m:
            continue
        ref, disp, _ticket, _report, repro = m.groups()
        if disp == "CONFIRMED" and repro != "y":
            out.append(f"line {line_no}: {ref} CONFIRMED with reproduced={repro}")
    return out


def gates(label: str, text: str) -> dict:
    writer = imp.validate_sweep(text)
    core = core_gate(text)
    return {
        "case": label,
        "writer_gate_validate_sweep_errors": writer,
        "writer_gate_verdict": "ACCEPT" if not writer else "REJECT",
        "core_gate_verdicts": core,
        "core_gate_verdict": "ACCEPT" if not core else "REJECT",
        "the_gates_agree": (not writer) == (not core),
    }


ledger_text = LEDGER.read_text(encoding="utf-8")
target_line = next(
    line for line in ledger_text.splitlines() if "RUN-1/IMP-002" in line and "T-1392" in line
)
control_text = ledger_text.replace(target_line, target_line.replace("reproduced=n", "reproduced=y"))

report = {
    "harness": "t1401_gate_disagreement.py",
    "ticket": "T-1401",
    "question": "can write_sweep_entry commit a ledger line that validate.py reds?",
    "ledger_under_test": str(LEDGER),
    "target_line": target_line,
    "control_line": target_line.replace("reproduced=n", "reproduced=y"),
    "cases": [
        gates("real-ledger (reproduced=n)", ledger_text),
        gates("negative-control (reproduced=y)", control_text),
    ],
    "method": (
        "both gates run on the real committed bytes; the writer gate is "
        "improve.validate_sweep as imported from the install, the core gate is "
        "the CONFIRMED arm of validate.py transcribed verbatim"
    ),
    "negative_control": (
        "the reproduced=y control must pass both gates; if it did not, the "
        "harness would be reporting a disagreement that is really its own bug"
    ),
}
report["conclusion"] = (
    "DISAGREE"
    if not report["cases"][0]["the_gates_agree"] and report["cases"][1]["the_gates_agree"]
    else "NO_DISAGREEMENT_MEASURED"
)
print(json.dumps(report, indent=2))
