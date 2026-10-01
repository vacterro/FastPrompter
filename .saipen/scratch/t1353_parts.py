"""Split each locale's untranslated backlog into fixed-size fill-in parts.

Each part is a flat JSON object {english_key: ""}. A translator agent fills the
values in place, one part per Write, so no single tool call has to carry a
600-entry file and a truncated write costs one part instead of a locale.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, "tools")
sys.stdout.reconfigure(encoding="utf-8")

from i18n_identical_audit import classify_key, load_pack

PART_SIZE = 120
BATCHES = Path(".saipen/saitranslate/batches")
OUT = BATCHES / "out"
OUT.mkdir(parents=True, exist_ok=True)
for stale in OUT.glob("*.json"):
    stale.unlink()

en = load_pack("en")["translations"]
neutral = {k for k, v in en.items() if classify_key(v) == "neutral"}

manifest = {}
for path in sorted(BATCHES.glob("*.json")):
    if path.name == "manifest.json":
        continue
    lang = path.stem
    batch = json.load(open(path, encoding="utf-8"))
    items = list(batch["source_texts"].items())
    parts = [items[i:i + PART_SIZE] for i in range(0, len(items), PART_SIZE)]
    files = []
    for index, chunk in enumerate(parts, start=1):
        part_file = OUT / f"{lang}.part{index}.json"
        part_file.write_text(
            json.dumps({k: "" for k, _ in chunk}, ensure_ascii=False, indent=1),
            encoding="utf-8",
        )
        files.append(part_file.name)
    manifest[lang] = {
        "target_language": batch["target_language"],
        "language_name_en": batch["language_name_en"],
        "strings": len(items),
        "parts": files,
    }

(BATCHES / "parts.json").write_text(
    json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8"
)
print(f"locales: {len(manifest)}  strings: {sum(v['strings'] for v in manifest.values())}  "
      f"parts: {sum(len(v['parts']) for v in manifest.values())}")
for lang, info in sorted(manifest.items(), key=lambda kv: -kv[1]["strings"]):
    print(f"  {lang:<4} {info['target_language']:<14} {info['strings']:>4} in {len(info['parts'])} parts")