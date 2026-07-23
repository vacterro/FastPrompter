import os
import json

locales_dir = r"V:\___VAC\__K\__CODE\_PY\_FastPrompter\.saipen\saitranslate\locales"
i18n_dir = r"V:\___VAC\__K\__CODE\_PY\_FastPrompter\src\fastprompter\core\i18n"

# 1. Remove tr.py in i18n_dir
tr_py = os.path.join(i18n_dir, "tr.py")
if os.path.exists(tr_py):
    os.remove(tr_py)
    print("Removed colliding tr.py from i18n package.")

# 2. Rename tr.json -> tur.json in .saipen/saitranslate/locales
tr_json = os.path.join(locales_dir, "tr.json")
tur_json = os.path.join(locales_dir, "tur.json")
if os.path.exists(tr_json):
    with open(tr_json, 'r', encoding='utf-8') as f:
        data = json.load(f)
    data["_meta"]["code"] = "TUR"
    with open(tur_json, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.remove(tr_json)
    print("Renamed tr.json -> tur.json with code TUR.")

# Re-run inject_translations.py
import subprocess
res = subprocess.run(["python", r"scratch\inject_translations.py"], cwd=r"V:\___VAC\__K\__CODE\_PY\_FastPrompter", capture_output=True, text=True)
print(res.stdout)
print(res.stderr)
