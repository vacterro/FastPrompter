"""Negative control for t1395_phase_audit.py.

The audit's real result is a ZERO: no `phase` reference anywhere in the improve
supersession path. A zero is only evidence if the method can produce a non-zero, so
this control mutates a scratch COPY of the module -- injecting one phase comparison
into `_replacement_for` -- and asserts the audit flips to REPRODUCED against it.
The real installs are never written to.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("t1395_phase_audit", HERE / "t1395_phase_audit.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

INJECT = (
    "        if _field(candidate_text, \"phase\") != _field(source_text, \"phase\"):\n"
    "            continue\n"
)
scratch = HERE / "control_improve_scratch.py"
src = Path(mod.COPIES[0]).read_text(encoding="utf-8")
anchor = (
    "        candidate_text = _read_maybe("
    "cycle_dir / record[\"seat_id\"] / record[\"report_path\"])\n"
)
assert src.count(anchor) == 1, f"anchor is not unique: {src.count(anchor)}"
scratch.write_text(src.replace(anchor, anchor + INJECT), encoding="utf-8")

result = mod.audit(str(scratch))
control = {
    "control": "t1395_control.py",
    "purpose": "prove the phase audit can report a non-zero",
    "injection": INJECT.strip(),
    "injection_target": "_replacement_for",
    "scratch_copy": str(scratch),
    "real_installs_written_to": [],
    "whole_module_phase_occurrences": result["whole_module_phase_occurrences"],
    "phase_refs_in_supersession_path": result["phase_refs_in_supersession_path"],
    "unaccounted_phase_occurrences": result["unaccounted_phase_occurrences"],
    "_replacement_for_phase_refs": result["supersession_path"]["_replacement_for"]["phase_refs"],
    "audit_is_live": result["phase_refs_in_supersession_path"] > 0,
}
control["control_passed"] = control["audit_is_live"] and not control["unaccounted_phase_occurrences"]
scratch.unlink(missing_ok=True)
print(json.dumps(control, indent=2))
