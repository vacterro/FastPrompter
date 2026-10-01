import json
import sys

spa_un = json.load(open('build/untranslated/spa.json', encoding='utf-8'))
pt_un = json.load(open('build/untranslated/pt.json', encoding='utf-8'))

from fastprompter.core.i18n import ru, de, fra, it

all_keys = sorted(list(set(spa_un.keys()) | set(pt_un.keys())))

records = []
for k in all_keys:
    rec = {
        "key": k,
        "spa": k in spa_un,
        "pt": k in pt_un,
        "ru": ru.TRANSLATIONS.get(k, ""),
        "de": de.TRANSLATIONS.get(k, ""),
        "fra": fra.TRANSLATIONS.get(k, ""),
    }
    records.append(rec)

with open("all_untranslated_context.json", "w", encoding="utf-8") as f:
    json.dump(records, f, ensure_ascii=False, indent=2)

print(f"Exported {len(records)} records to all_untranslated_context.json")
