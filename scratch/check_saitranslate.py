import os
import json
import re

src_dir = r"V:\___VAC\__K\__CODE\_PY\_FastPrompter\src\fastprompter"
tr_pattern = re.compile(r'tr\(\s*["\'](.*?)["\']\s*(?:,|\))')

collected_keys = set()
for root, dirs, files in os.walk(src_dir):
    for f in files:
        if f.endswith('.py'):
            path = os.path.join(root, f)
            with open(path, 'r', encoding='utf-8') as file:
                content = file.read()
                matches = tr_pattern.findall(content)
                for m in matches:
                    collected_keys.add(m)

locales_dir = r"V:\___VAC\__K\__CODE\_PY\_FastPrompter\.saitranslate\locales"
locale_files = [f for f in os.listdir(locales_dir) if f.endswith('.json')]

missing_per_lang = {}
for lf in locale_files:
    lang = lf.replace('.json', '')
    filepath = os.path.join(locales_dir, lf)
    with open(filepath, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    trans = data.get("translations", {})
    missing = [k for k in collected_keys if k not in trans]
    if missing:
        missing_per_lang[lang] = missing
        print(f"Language {lang}: {len(missing)} missing keys out of {len(collected_keys)} total (Coverage: {(1 - len(missing)/len(collected_keys))*100:.1f}%)")
    else:
        print(f"Language {lang}: 100% complete ({len(trans)} keys)")

print("\nMissing keys summary across all languages:")
for lang, keys in missing_per_lang.items():
    print(f"  {lang}: {keys[:5]} ... (+{len(keys)-5} more)" if len(keys) > 5 else f"  {lang}: {keys}")
