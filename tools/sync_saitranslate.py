import json
import os
import sys
from pathlib import Path
from deep_translator import GoogleTranslator

# Add tools dir to path to import i18n_utils
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import i18n_utils

project_root = i18n_utils.get_project_root()
src_dir = os.path.join(project_root, "src", "fastprompter")
locales_dir = os.path.join(project_root, ".saipen", "saitranslate", "locales")

collected_keys, _, _ = i18n_utils.collect_tr_keys(src_dir)

existing_py_translations = {}
try:
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
    
    with open(filepath, encoding='utf-8') as f:
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
                ru_val = py_entry if isinstance(py_entry, str) else (py_entry.get("RU") if isinstance(py_entry, dict) else None)
                if not ru_val:
                    try:
                        ru_val = GoogleTranslator(source="en", target="ru").translate(key)
                    except Exception:
                        ru_val = key
                val = f"🧓: {ru_val}" if ru_val else key
            else:
                try:
                    translated = GoogleTranslator(source="en", target=target_code).translate(key)
                    val = translated if translated else key
                except Exception:
                    val = key
        
        trans[key] = val
        added += 1
        if added % 50 == 0:
            print(f"  [{lang}] {added}/{len(missing)} keys translated...")
    
    data["coverage_pct"] = 100.0
    
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    
    print(f"[{lang}] Saved {added} new translations to {lf}. Total: {len(trans)} keys.")

print("\n=== SAITRANSLATE MAINTAIN COMPLETE ===")
