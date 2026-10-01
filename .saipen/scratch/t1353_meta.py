import json
import sys
from pathlib import Path

sys.path.insert(0, "tools")
sys.stdout.reconfigure(encoding="utf-8")

from i18n_identical_audit import classify_key, load_pack

LOCALES = Path(".saipen/saitranslate/locales")
OUT = Path(".saipen/saitranslate/batches")
OUT.mkdir(parents=True, exist_ok=True)

en = load_pack("en")["translations"]
neutral = {k for k, v in en.items() if classify_key(v) == "neutral"}

manifest = {}
for path in sorted(LOCALES.glob("*.json")):
    lang = path.stem
    if lang == "en":
        continue
    data = json.load(open(path, encoding="utf-8"))
    meta = data.get("_meta", {})
    pack = data["translations"]
    todo = {k: en[k] for k in en if k not in neutral and pack.get(k) == en[k]}
    batch = {
        "lang": lang,
        "target_language": meta.get("name_native") or meta.get("name") or lang,
        "language_name_en": meta.get("name", lang),
        "source_texts": todo,
    }
    out_file = OUT / f"{lang}.json"
    out_file.write_text(json.dumps(batch, ensure_ascii=False, indent=1), encoding="utf-8")
    manifest[lang] = {
        "target": batch["target_language"],
        "count": len(todo),
        "batch": str(out_file).replace("\\", "/"),
        "out": str((OUT / "out" / f"{lang}.json")).replace("\\", "/"),
    }

(OUT / "manifest.json").write_text(
    json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8"
)
total = sum(v["count"] for v in manifest.values())
print(f"batches written: {len(manifest)} locales, {total} strings to translate")
for lang, info in sorted(manifest.items(), key=lambda kv: -kv[1]["count"]):
    print(f"  {lang:<4} {info['target']:<14} {info['count']}")