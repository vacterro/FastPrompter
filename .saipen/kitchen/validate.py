"""SAIPEN conformance checks, written from RFC.md 1.2 + CONFORMANCE.md.

The canonical `tools/validate.py` is not present in the saipen home on this
machine (only the .md docs are), and neither is the portable
`tests/validate.ps1` floor. So the three vectors are implemented here from
the spec rather than assumed to pass.

Stdlib only. Run from the project root:  python .saipen/kitchen/validate.py
"""

from __future__ import annotations

import os
import re
import sys

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")

PHASES = {"INIT", "PLAN", "SCOUT", "BUILD", "VERIFY", "REVIEW", "SHIP",
          "DONE", "BLOCKED", "VALIDATE", "HUNT", "ADD", "CLEAN", "TRANSLATE"}
MODES = {"full", "read-only", "no-publish", "manual-verify"}
# RFC 1.3: read-only cannot reach any phase that writes to disk
READ_ONLY_FORBIDS = {"BUILD", "SHIP", "CLEAN", "TRANSLATE", "ADD", "HUNT"}
TAXONOMY = {"RUN", "DEC", "H"}
STATE_REQUIRED = ("phase", "task", "next_action", "blocker", "agent",
                  "saipen_version", "mode", "updated")

LOG_LINE = re.compile(
    r"^- (?P<date>\d{2}\.\d{2}\.\d{2} \d{2}:\d{2}) "
    r"\[E-(?P<eid>\d+)\]"
    r"(?: \[parent: E-(?P<parent>\d+)\])?"
    r"(?: \[(?P<ticket>T-(?:\d+|none))\])?"
    r"(?: \[agent: (?P<agent>[^\]]+)\])?"
    r" (?P<tax>[A-Z]+): (?P<text>.+)$")
BOARD_TICKET = re.compile(r"^- \[( |x|/)\] (T-\d+)\b(.*)$")
BOARD_HEADING = re.compile(r"^## (DOING|TODO|DONE|BLOCKED)\s*$")
ISO_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(Z|\+00:00)$")


def read(name):
    path = os.path.join(ROOT, name)
    if not os.path.isfile(path):
        return None
    return open(path, encoding="utf-8").read()


def check_state(fails):
    text = read("STATE.md")
    if text is None:
        fails.append("STATE.md: missing")
        return {}
    if not text.startswith("---"):
        fails.append("STATE.md: no frontmatter")
        return {}
    body = text.split("---", 2)[1]
    fm = {}
    for line in body.splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            fm[k.strip()] = v.strip().strip('"')

    for key in STATE_REQUIRED:
        if key not in fm:
            fails.append(f"STATE.md: missing required field {key!r}")

    phase = fm.get("phase", "")
    if phase and phase not in PHASES:
        fails.append(f"STATE.md: phase {phase!r} is not one of the 14")
    mode = fm.get("mode", "")
    if mode and mode not in MODES:
        fails.append(f"STATE.md: mode {mode!r} unknown")
    if mode == "read-only" and phase in READ_ONLY_FORBIDS:
        fails.append(f"STATE.md: mode read-only cannot be in phase {phase}")
    if mode == "no-publish" and phase == "SHIP":
        fails.append("STATE.md: mode no-publish cannot be in phase SHIP")
    if phase == "BLOCKED" and not fm.get("blocker"):
        fails.append("STATE.md: phase BLOCKED with an empty blocker")
    upd = fm.get("updated", "")
    if upd and not ISO_UTC.match(upd):
        fails.append(f"STATE.md: updated {upd!r} is not ISO-8601 UTC")
    if not fm.get("next_action"):
        fails.append("STATE.md: next_action is empty")
    return fm


def check_board(fails):
    text = read("BOARD.md")
    if text is None:
        fails.append("BOARD.md: missing")
        return
    headings = [m.group(1) for m in
                (BOARD_HEADING.match(ln) for ln in text.splitlines()) if m]
    if not headings:
        fails.append("BOARD.md: no '## DOING/TODO/DONE/BLOCKED' headings")

    section, seen, where, needs = None, {}, {}, {}
    for ln in text.splitlines():
        h = BOARD_HEADING.match(ln)
        if h:
            section = h.group(1)
            continue
        m = BOARD_TICKET.match(ln)
        if not m:
            continue
        tid, rest = m.group(2), m.group(3)
        if tid in seen:
            fails.append(f"BOARD.md: {tid} appears twice "
                         f"({where[tid]} and {section})")
        seen[tid] = True
        where[tid] = section
        for field in rest.split("|"):
            field = field.strip()
            if field.startswith("needs:"):
                needs[tid] = [t.strip() for t in
                              field[len("needs:"):].split(",") if t.strip()]

    for tid, deps in needs.items():
        for dep in deps:
            if dep not in seen:
                fails.append(f"BOARD.md: {tid} needs {dep}, which is not on "
                             "the board")
    # cycles
    colour = {}

    def walk(node, trail):
        if colour.get(node) == "done":
            return
        if colour.get(node) == "open":
            fails.append("BOARD.md: dependency cycle "
                         + ",".join(trail[trail.index(node):] + [node]))
            return
        colour[node] = "open"
        for dep in needs.get(node, []):
            if dep in seen:
                walk(dep, trail + [node])
        colour[node] = "done"

    for tid in list(needs):
        walk(tid, [])

    if not seen:
        fails.append("BOARD.md: no ticket line matches '- [ ] T-### ...'")


def check_log(fails):
    text = read("LOG.md")
    if text is None:
        fails.append("LOG.md: missing")
        return
    lines = [ln for ln in text.splitlines() if ln.startswith("- ")]
    ids, bad = [], 0
    for i, ln in enumerate(lines, 1):
        m = LOG_LINE.match(ln)
        if not m:
            bad += 1
            if bad <= 3:
                fails.append(f"LOG.md: line {i} does not match the skeleton: "
                             f"{ln[:70]!r}")
            continue
        eid = int(m.group("eid"))
        if eid in ids:
            fails.append(f"LOG.md: E-{eid:03d} reused")
        if ids and eid <= ids[-1]:
            fails.append(f"LOG.md: E-{eid:03d} is not monotonic "
                         f"(after E-{ids[-1]:03d})")
        ids.append(eid)
        if m.group("tax") not in TAXONOMY:
            fails.append(f"LOG.md: line {i} taxonomy {m.group('tax')!r} "
                         "is not RUN/DEC/H")
        parent = m.group("parent")
        if parent is not None and int(parent) not in ids[:-1]:
            fails.append(f"LOG.md: E-{eid:03d} parent E-{int(parent):03d} "
                         "does not resolve to an earlier event")
    if bad > 3:
        fails.append(f"LOG.md: ...and {bad - 3} more malformed lines "
                     f"({bad} of {len(lines)} total)")


def main():
    fails = []
    check_state(fails)
    check_board(fails)
    check_log(fails)
    if not fails:
        print("validate -> PASS")
        return 0
    print(f"validate -> FAIL ({len(fails)} findings)")
    for f in fails:
        print("  " + f)
    return 1


if __name__ == "__main__":
    sys.exit(main())
