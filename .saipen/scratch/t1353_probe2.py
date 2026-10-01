import json
import sys

sys.stdout.reconfigure(encoding="utf-8")
packs = {
    l: json.load(open(f".saipen/saitranslate/locales/{l}.json", encoding="utf-8"))["translations"]
    for l in ("de", "ru", "est", "fr".replace("fr", "fra"))
}
keys = ["Bind", "BkUp", "Rpl", "Rstr", "Vol", "B", "C", "H", "I", "L", "R", "S", "U",
        "Markdown", "Problip", "SiloKanban", "SiloTable", "OK", "RGB", "RU",
        "More\\nButtons hidden because the window is narrow.", "Pool", "Item", "Rule", "Name"]
for k in keys:
    row = {l: packs[l].get(k, "<MISSING>") for l in packs}
    print(repr(k))
    for l, v in row.items():
        print(f"    {l:4} {v!r}")