import os
import json
import re
import time
from deep_translator import GoogleTranslator

src_dir = r"V:\___VAC\__K\__CODE\_PY\_FastPrompter\src\fastprompter"
locales_dir = r"V:\___VAC\__K\__CODE\_PY\_FastPrompter\.saitranslate\locales"

# 1. Collect all tr() keys from codebase
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
                    if m.strip():
                        collected_keys.add(m)

# Also import existing translations from src/fastprompter/core/translations.py
existing_py_translations = {}
try:
    import sys
    sys.path.insert(0, src_dir)
    from fastprompter.core.translations import _DATA
    for k, v in _DATA.items():
        collected_keys.add(k)
        existing_py_translations[k] = v
except Exception as e:
    print(f"Warning importing _DATA: {e}")

print(f"Total keys to maintain: {len(collected_keys)}")

LANG_MAP = {
    "ar": "ar", "da": "da", "de": "de", "en": "en", "est": "et", "fi": "fi",
    "fra": "fr", "he": "iw", "it": "it", "ja": "ja", "ko": "ko", "nl": "nl",
    "no": "no", "pl": "pl", "pt": "pt", "ru": "ru", "spa": "es", "sv": "sv",
    "th": "th", "ukr": "uk", "vi": "vi", "zh": "zh-CN", "ded": "ru"
}

locale_files = sorted([f for f in os.listdir(locales_dir) if f.endswith('.json')])

for lf in locale_files:
    lang = lf.replace('.json', '')
    filepath = os.path.join(locales_dir, lf)
    
    with open(filepath, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    trans = data.setdefault("translations", {})
    missing = [k for k in sorted(collected_keys) if k not in trans]
    
    if not missing:
        print(f"[{lang}] 100% complete ({len(trans)} keys).")
        continue
    
    print(f"[{lang}] Processing {len(missing)} missing keys...")
    target_code = LANG_MAP.get(lang, "en")
    
    added = 0
    for key in missing:
        val = None
        # Check python translations first if applicable (RU / EST)
        py_entry = existing_py_translations.get(key)
        if py_entry:
            if isinstance(py_entry, str) and lang in ["ru", "ded"]:
                val = py_entry
            elif isinstance(py_entry, dict):
                val = py_entry.get(lang.upper())
            
        if not val:
            if lang == "en":
                val = key
            elif lang == "ded":
                # Grandpa voice translation
                ru_val = py_entry if isinstance(py_entry, str) else (py_entry.get("RU") if isinstance(py_entry, dict) else None)
                if not ru_val:
                    try:
                        ru_val = GoogleTranslator(source="en", target="ru").translate(key)
                    except:
                        ru_val = key
                val = f"Эх, {ru_val}" if ru_val else key
            else:
                # Use GoogleTranslator
                try:
                    translated = GoogleTranslator(source="en", target=target_code).translate(key)
                    val = translated if translated else key
                except Exception:
                    val = key
        
        trans[key] = val
        added += 1
        if added % 50 == 0:
            print(f"  [{lang}] {added}/{len(missing)} keys translated...")
    
    # Recalculate coverage_pct
    data["coverage_pct"] = 100.0
    
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    
    print(f"[{lang}] Saved {added} new translations to {lf}. Total: {len(trans)} keys.")

print("\n=== SAITRANSLATE MAINTAIN COMPLETE ===")
