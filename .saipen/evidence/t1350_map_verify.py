"""T-1350: map every outstanding conformance ticket to a REAL runnable verify
command. Nothing here runs anything; it only reads BOARD.md and the tests/
directory so the sweep can be driven by evidence rather than by guesswork."""

import io
import os
import re

WANT = set(
    "T-1205 T-1208 T-1210 T-1211 T-1212 T-1213 T-1214 T-1215 T-1221 T-1222 "
    "T-1225 T-1226 T-1229 T-1230 T-1231 T-1232 T-1233 T-1234 T-1235 T-1236 "
    "T-1240 T-1242 T-1243 T-1244 T-1245 T-1247 T-1248 T-1249 T-1250 T-1251 "
    "T-1252 T-1253 T-1254 T-1255 T-1256 T-1260 T-1261 T-1265 T-1266 T-1267 "
    "T-1268 T-1294 T-1295 T-1296 T-1297 T-1336 T-1349".split()
)

root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
root = os.path.dirname(root)
board = io.open(os.path.join(root, ".saipen", "BOARD.md"), encoding="utf-8").read()

rows = []
for line in board.split("\n"):
    m = re.match(r"^- \[x\] (T-\d+)\b", line)
    if not (m and m.group(1) in WANT):
        continue
    v = re.search(
        r"\| verify: (.*?)(?: \| owner: | \| needs: | \| regression: "
        r"\| source_receipts: |$)",
        line,
    )
    clause = v.group(1) if v else ""
    named = re.findall(r"tests/[A-Za-z0-9_./]+\.py", clause)
    ok = sorted({f for f in named if os.path.exists(os.path.join(root, f))})
    rows.append((m.group(1), ok, clause))

have = [r for r in rows if r[1]]
print("WITH a named, existing test file: {} / {}".format(len(have), len(rows)))
for t, f, _ in have:
    print("   {} -> {}".format(t, ", ".join(f[:3])))
print()
print("WITHOUT one: {}".format(len(rows) - len(have)))
for t, f, c in rows:
    if not f:
        print("   {} | {}".format(t, c[:110]))

out = os.path.join(root, ".saipen", "evidence", "t1350_verify_map.txt")
io.open(out, "w", encoding="utf-8").write(
    "\n".join("{}\t{}".format(t, ",".join(f)) for t, f, _ in rows)
)
