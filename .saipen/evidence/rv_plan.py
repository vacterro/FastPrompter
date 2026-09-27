"""Build a per-ticket reverify plan: for each DONE ticket, the test files the
LOG itself attributes to it (and that still exist on disk)."""
import io
import os
import re
import sys
from collections import defaultdict

TICKETS = sys.argv[1:]
files = defaultdict(set)
for line in io.open(".saipen/LOG.md", encoding="utf-8").read().splitlines():
    for t in TICKETS:
        if t in line:
            for m in re.findall(r"tests/[\w\-./]+\.py", line):
                if os.path.exists(m.replace("/", os.sep)):
                    files[t].add(m)
for t in TICKETS:
    hits = sorted(files[t])
    print(t, "|", ",".join(hits) if hits else "-")
