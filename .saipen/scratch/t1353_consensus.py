import json
import sys
from collections import Counter

sys.path.insert(0, "tools")
from i18n_identical_audit import classify_key, load_pack

sys.stdout.reconfigure(encoding="utf-8")

en = load_pack("en")["translations"]
langs = sorted(p.stem for p in __import__("pathlib").Path(
    ".saipen/saitranslate/locales").glob("*.json") if p.stem != "en")
packs = {l: load_pack(l)["translations"] for l in langs}

identical_counts = Counter()
for k, v in en.items():
    n = sum(1 for l in langs if packs[l].get(k) == v)
    identical_counts[k] = n

struct = {k for k, v in en.items() if classify_key(v) == "neutral"}
consensus = {k for k, c in identical_counts.items() if c >= 28}
union = sorted(struct | consensus)
print("structural neutral :", len(struct))
print("consensus >=28/32  :", len(consensus))
print("union              :", len(union))
print()
for k in union:
    mark = "S" if k in struct else "c"
    print(f"{mark} {identical_counts[k]:2d}/32  {en[k]!r}")