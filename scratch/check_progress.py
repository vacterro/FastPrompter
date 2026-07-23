import os
import json

locales_dir = r"V:\___VAC\__K\__CODE\_PY\_FastPrompter\.saipen\saitranslate\locales"
files = [f for f in os.listdir(locales_dir) if f.endswith('.json')]

print(f"Total locale files found: {len(files)}")
for f in sorted(files):
    path = os.path.join(locales_dir, f)
    with open(path, 'r', encoding='utf-8') as json_file:
        data = json.load(json_file)
        trans = data.get("translations", {})
        cov = data.get("coverage_pct", 0)
        print(f"  {f}: {len(trans)} keys, coverage: {cov}%")
