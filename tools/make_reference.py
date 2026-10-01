import json
from pathlib import Path

root = Path("V:/___VAC/__K/__CODE/_PY/_FastPrompter")
locales_dir = root / ".saipen/saitranslate/locales"

hr_un = json.loads((root / "build/untranslated/hr.json").read_text(encoding="utf-8"))
ro_un = json.loads((root / "build/untranslated/ro.json").read_text(encoding="utf-8"))
el_un = json.loads((root / "build/untranslated/el.json").read_text(encoding="utf-8"))

all_keys = sorted(set(hr_un) | set(ro_un) | set(el_un))

langs = ["ru", "bg", "ukr", "cs", "pl", "it", "fra", "spa", "de", "est", "el", "ro", "hr"]
locales = {}
for l in langs:
    path = locales_dir / f"{l}.json"
    if path.exists():
        locales[l] = json.loads(path.read_text(encoding="utf-8")).get("translations", {})

# Save a reference dictionary for all_keys
ref = {}
for k in all_keys:
    ref[k] = {
        "in_hr": k in hr_un,
        "in_ro": k in ro_un,
        "in_el": k in el_un,
        "ru": locales.get("ru", {}).get(k, ""),
        "bg": locales.get("bg", {}).get(k, ""),
        "ukr": locales.get("ukr", {}).get(k, ""),
        "it": locales.get("it", {}).get(k, ""),
        "fra": locales.get("fra", {}).get(k, ""),
        "spa": locales.get("spa", {}).get(k, ""),
        "de": locales.get("de", {}).get(k, ""),
        "est": locales.get("est", {}).get(k, ""),
    }

(root / "build/reference_703.json").write_text(json.dumps(ref, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"Generated reference for {len(all_keys)} keys")
