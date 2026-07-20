# -*- coding: utf-8 -*-
"""Batch translate untranslated entries in all i18n language files."""
import sys, os, json, re, time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))
sys.stdout.reconfigure(encoding='utf-8')

from deep_translator import GoogleTranslator
from fastprompter.core.i18n import ensure_initialized
from fastprompter.core.i18n._engine import _registry as r

ensure_initialized()
en = r.get("EN", {})

with open("_untranslated.json", "r", encoding="utf-8") as f:
    unt_data = json.load(f)

LANG_MAP = {
    "AR": "ar", "DA": "da", "DE": "de", "EST": "et", "FI": "fi",
    "FRA": "fr", "HE": "iw", "IT": "it", "JA": "ja", "KO": "ko",
    "NL": "nl", "NO": "no", "PL": "pl", "PT": "pt", "RU": "ru",
    "SPA": "es", "SV": "sv", "TH": "th", "UKR": "uk", "VI": "vi",
    "ZH": "zh-CN",
}

i18n_dir = os.path.join("src", "fastprompter", "core", "i18n")

for code in sorted(unt_data.keys()):
    target = LANG_MAP.get(code)
    if not target:
        continue
    keys = unt_data[code]
    if not keys:
        continue
    
    print(f"\n=== {code} ({target}) \u2014 {len(keys)} entries ===")
    
    filepath = os.path.join(i18n_dir, f"{code.lower()}.py")
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()
    
    changes = 0
    for key in keys:
        if key == "**__{text}__** ({time})" or key == "RGB":
            continue
        
        # Detect if key uses single or double quotes in file
        sq_key = key.replace("'", "\\'")
        dq_key = key.replace('"', '\\"')
        
        # Translate
        try:
            translator = GoogleTranslator(source="en", target=target)
            translated = translator.translate(key)
            if not translated or translated == key:
                print(f"  SKIP: {key[:50]}")
                continue
        except Exception as e:
            print(f"  FAIL: {key[:50]} - {e}")
            time.sleep(2)
            continue
        
        sq_val = translated.replace("'", "\'")
        dq_val = translated.replace('"', '\\"')
        
        # Try single-quoted pattern: 'key': 'key' -> 'key': 'translated'
        old_sq = f"'{sq_key}': '{sq_key}'"
        new_sq = f"'{sq_key}': '{sq_val}'"
        
        if old_sq in content:
            content = content.replace(old_sq, new_sq, 1)
            changes += 1
        else:
            # Try double-quoted pattern: "key": "key" -> "key": "translated"
            old_dq = f'"{dq_key}": "{dq_key}"'
            new_dq = f'"{dq_key}": "{dq_val}"'
            if old_dq in content:
                content = content.replace(old_dq, new_dq, 1)
                changes += 1
            else:
                print(f"  NOT FOUND: {key[:50]}")
        
        time.sleep(0.3)
    
    if changes > 0:
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)
        print(f"  -> {changes} changes to {code.lower()}.py")
    else:
        print(f"  -> No changes")

print("\n=== DONE ===")
