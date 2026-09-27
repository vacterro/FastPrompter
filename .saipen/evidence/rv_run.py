"""Drive `saipen work reverify` with an EXECUTED check per ticket.

A ticket with test files the LOG attributes to it gets exactly those files
run by the engine. A ticket with no recoverable attribution gets the
whole-tree ruff gate, and the report says so -- no receipt is dressed up as
behavioural proof it is not.
"""
import io
import re
import subprocess
import sys
import time
from collections import defaultdict

SAIPEN = r"C:\Users\vac34\AppData\Local\saipen\scheduled-source\bin\saipen.cmd"
STATIC = "python -m ruff check src/fastprompter/ tests/"

TICKETS = sys.argv[1:]
attributed = defaultdict(set)
for line in io.open(".saipen/LOG.md", encoding="utf-8").read().splitlines():
    for t in TICKETS:
        if t in line:
            for m in re.findall(r"tests/[\w\-./]+\.py", line):
                attributed[t].add(m)

results = []
for t in TICKETS:
    files = sorted(attributed[t])
    if files:
        cmd = "python -m pytest %s -q" % " ".join(files)
        kind = "behavioural(%d files)" % len(files)
    else:
        cmd = STATIC
        kind = "static-gate"
    start = time.time()
    out = subprocess.run([SAIPEN, "work", "reverify", t, "--run", cmd],
                         capture_output=True, text=True, shell=False)
    blob = (out.stdout or "") + (out.stderr or "")
    code = "?"
    m = re.search(r"code: ([A-Z_]+)", blob)
    if m:
        code = m.group(1)
    results.append((t, kind, code, round(time.time() - start, 1)))
    print("%s %-24s %-18s %6.1fs" % results[-1], flush=True)

# Written OUTSIDE the repository on purpose: every tracked byte written after
# a reverify receipt moves the tree and invalidates it.
with io.open("C:/Users/vac34/AppData/Local/Temp/rv_exec_log.txt", "w", encoding="utf-8") as fh:
    for row in results:
        fh.write("%s %s %s %ss\n" % row)
print("DONE", len(results), "failures:",
      [r[0] for r in results if r[2] not in ("WORK_REVERIFIED", "REVERIFY_REUSED")])
