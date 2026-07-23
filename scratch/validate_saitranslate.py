import os
import json
import re
import sys

sys.stdout.reconfigure(encoding='utf-8')

locales_dir = r"V:\___VAC\__K\__CODE\_PY\_FastPrompter\.saipen\saitranslate\locales"
kitchen_docs_dir = r"V:\___VAC\__K\__CODE\_PY\_FastPrompter\.saipen\saitranslate\kitchen\docs"
state_file = r"V:\___VAC\__K\__CODE\_PY\_FastPrompter\.saipen\saitranslate\STATE.md"
src_dir = r"V:\___VAC\__K\__CODE\_PY\_FastPrompter\src\fastprompter"

errors = []
warnings = []

# 1. Validate STATE.md
if not os.path.exists(state_file):
    errors.append("STATE.md missing in .saipen/saitranslate/")
else:
    with open(state_file, 'r', encoding='utf-8') as f:
        content = f.read()
        if "phase: DONE" not in content and "phase: TRANSLATE" not in content:
            warnings.append("STATE.md phase is neither DONE nor TRANSLATE")

# 2. Collect all tr() keys in codebase
tr_pattern = re.compile(r'tr\(\s*["\'](.*?)["\']\s*(?:,|\))')
collected_keys = set()
for root, dirs, files in os.walk(src_dir):
    for f in files:
        if f.endswith('.py'):
            with open(os.path.join(root, f), 'r', encoding='utf-8') as file:
                matches = tr_pattern.findall(file.read())
                for m in matches:
                    if m.strip():
                        collected_keys.add(m)

# 3. Validate Locales
REQUIRED_LANGS = [
    "ar", "bg", "cs", "da", "de", "ded", "el", "en", "est", "fi",
    "fra", "he", "hi", "hr", "hu", "id", "it", "ja", "ko", "nl",
    "no", "pl", "pt", "ro", "ru", "sk", "spa", "sv", "th", "tur",
    "ukr", "vi", "zh"
]

if not os.path.exists(locales_dir):
    errors.append(f"Locales directory missing at {locales_dir}")
else:
    files = [f.replace('.json', '') for f in os.listdir(locales_dir) if f.endswith('.json')]
    missing_files = [l for l in REQUIRED_LANGS if l not in files]
    if missing_files:
        errors.append(f"Missing locale JSON files: {missing_files}")
    
    locale_stats = {}
    for lang in REQUIRED_LANGS:
        lpath = os.path.join(locales_dir, f"{lang}.json")
        if not os.path.exists(lpath):
            continue
        try:
            with open(lpath, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            meta = data.get("_meta", {})
            if not meta.get("code") or not meta.get("flag"):
                warnings.append(f"[{lang}] Incomplete _meta tags")
            
            trans = data.get("translations", {})
            cov = data.get("coverage_pct", 0)
            
            locale_stats[lang] = {
                "keys": len(trans),
                "coverage": cov,
                "flag": meta.get("flag", "?")
            }
        except Exception as e:
            errors.append(f"[{lang}] Corrupt JSON: {e}")

# 4. Validate Kitchen Docs
doc_langs = ["ru", "est", "ja", "de"]
doc_stats = {}
if os.path.exists(kitchen_docs_dir):
    for dl in doc_langs:
        dpath = os.path.join(kitchen_docs_dir, dl)
        if os.path.exists(dpath):
            dfiles = [f for f in os.listdir(dpath) if f.endswith('.md')]
            doc_stats[dl] = len(dfiles)
        else:
            warnings.append(f"Kitchen docs missing for language: {dl}")
else:
    warnings.append("Kitchen docs directory missing")

# 5. Output Validation Summary
print("==========================================")
print("       SAITRANSLATE VALIDATION REPORT     ")
print("==========================================")
print(f"Total Source Keys Scanned : {len(collected_keys)}")
print(f"Target Locales Present     : {len(locale_stats)} / {len(REQUIRED_LANGS)}")

if errors:
    print("\n[ERRORS]")
    for e in errors:
        print(f"  [ERROR] {e}")
else:
    print("\n[OK] Zero structural errors found.")

if warnings:
    print("\n[WARNINGS]")
    for w in warnings:
        print(f"  [WARN] {w}")
else:
    print("[OK] Zero warnings found.")

print("\n--- Locale Coverage Summary ---")
for lang, stats in locale_stats.items():
    print(f"  {stats['flag']} {lang.upper():<4} : {stats['keys']} keys | {stats['coverage']}% coverage")

print("\n--- Translated Docs Summary ---")
for dl, count in doc_stats.items():
    print(f"  DOCS {dl.upper()}: {count} markdown docs translated")

if not errors:
    print("\nSTATUS: VALIDATION PASSED (100% OK)")
else:
    print("\nSTATUS: VALIDATION FAILED")
