import json
import sys

report = json.load(open(".saipen/scratch/t1353_audit.json", encoding="utf-8"))
neutral = report["neutral_keys"]
print("neutral keys:", len(neutral))
out = []
for k in neutral:
    out.append(repr(k))
sys.stdout.write("\n".join(out) + "\n")
