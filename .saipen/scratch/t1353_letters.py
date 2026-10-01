import json
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
en = json.load(open(".saipen/saitranslate/locales/en.json", encoding="utf-8"))["translations"]
targets = {"B", "C", "H", "I", "L", "R", "S", "U", "Markdown", "Problip", "SiloKanban"}
found = {t: [] for t in targets}
pat = re.compile(r"tr\(\s*(['\"])([^'\"]{1,80})\1")
for path in Path("src").rglob("*.py"):
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        continue
    for m in pat.finditer(text):
        key = m.group(2)
        if key in found:
            line_no = text[: m.start()].count("\n") + 1
            found[key].append(f"{path}:{line_no}")
for k in sorted(found):
    print(f"{k!r}: {len(found[k])} -> {found[k][:3]}")