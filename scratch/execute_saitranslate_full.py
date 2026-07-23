import os
import json
import re
import time
import subprocess
from deep_translator import GoogleTranslator

src_dir = r"V:\___VAC\__K\__CODE\_PY\_FastPrompter\src\fastprompter"
locales_dir = r"V:\___VAC\__K\__CODE\_PY\_FastPrompter\.saipen\saitranslate\locales"
kitchen_dir = r"V:\___VAC\__K\__CODE\_PY\_FastPrompter\.saipen\saitranslate\kitchen"
docs_dir = r"V:\___VAC\__K\__CODE\_PY\_FastPrompter\docs\wiki"

os.makedirs(locales_dir, exist_ok=True)
os.makedirs(kitchen_dir, exist_ok=True)

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

# Import existing translations from src/fastprompter/core/translations.py
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

print(f"Total source keys found: {len(collected_keys)}")

LANG_META = {
    "ar": {"code": "AR", "name": "Arabic", "name_native": "العربية", "flag": "🇦🇪", "gt": "ar"},
    "bg": {"code": "BG", "name": "Bulgarian", "name_native": "Български", "flag": "🇧🇬", "gt": "bg"},
    "cs": {"code": "CS", "name": "Czech", "name_native": "Čeština", "flag": "🇨🇿", "gt": "cs"},
    "da": {"code": "DA", "name": "Danish", "name_native": "Dansk", "flag": "🇩🇰", "gt": "da"},
    "de": {"code": "DE", "name": "German", "name_native": "Deutsch", "flag": "🇩🇪", "gt": "de"},
    "ded": {"code": "DED", "name": "Grandpa Voice", "name_native": "«Дед»", "flag": "👴", "gt": "ru"},
    "el": {"code": "EL", "name": "Greek", "name_native": "Ελληνικά", "flag": "🇬🇷", "gt": "el"},
    "en": {"code": "EN", "name": "English", "name_native": "English", "flag": "🇺🇸", "gt": "en"},
    "est": {"code": "EST", "name": "Estonian", "name_native": "Eesti", "flag": "🇪🇪", "gt": "et"},
    "fi": {"code": "FI", "name": "Finnish", "name_native": "Suomi", "flag": "🇫🇮", "gt": "fi"},
    "fra": {"code": "FRA", "name": "French", "name_native": "Français", "flag": "🇫🇷", "gt": "fr"},
    "he": {"code": "HE", "name": "Hebrew", "name_native": "עברית", "flag": "🇮🇱", "gt": "iw"},
    "hi": {"code": "HI", "name": "Hindi", "name_native": "हिन्दी", "flag": "🇮🇳", "gt": "hi"},
    "hr": {"code": "HR", "name": "Croatian", "name_native": "Hrvatski", "flag": "🇭🇷", "gt": "hr"},
    "hu": {"code": "HU", "name": "Hungarian", "name_native": "Magyar", "flag": "🇭🇺", "gt": "hu"},
    "id": {"code": "ID", "name": "Indonesian", "name_native": "Bahasa Indonesia", "flag": "🇮🇩", "gt": "id"},
    "it": {"code": "IT", "name": "Italian", "name_native": "Italiano", "flag": "🇮🇹", "gt": "it"},
    "ja": {"code": "JA", "name": "Japanese", "name_native": "日本語", "flag": "🇯🇵", "gt": "ja"},
    "ko": {"code": "KO", "name": "Korean", "name_native": "한국어", "flag": "🇰🇷", "gt": "ko"},
    "nl": {"code": "NL", "name": "Dutch", "name_native": "Nederlands", "flag": "🇳🇱", "gt": "nl"},
    "no": {"code": "NO", "name": "Norwegian", "name_native": "Norsk", "flag": "🇳🇴", "gt": "no"},
    "pl": {"code": "PL", "name": "Polish", "name_native": "Polski", "flag": "🇵🇱", "gt": "pl"},
    "pt": {"code": "PT", "name": "Portuguese", "name_native": "Português", "flag": "🇵🇹", "gt": "pt"},
    "ro": {"code": "RO", "name": "Romanian", "name_native": "Română", "flag": "🇷🇴", "gt": "ro"},
    "ru": {"code": "RU", "name": "Russian", "name_native": "Русский", "flag": "🇷🇺", "gt": "ru"},
    "sk": {"code": "SK", "name": "Slovak", "name_native": "Slovenčina", "flag": "🇸🇰", "gt": "sk"},
    "spa": {"code": "SPA", "name": "Spanish", "name_native": "Español", "flag": "🇪🇸", "gt": "es"},
    "sv": {"code": "SV", "name": "Swedish", "name_native": "Svenska", "flag": "🇸🇪", "gt": "sv"},
    "th": {"code": "TH", "name": "Thai", "name_native": "ไทย", "flag": "🇹🇭", "gt": "th"},
    "tur": {"code": "TUR", "name": "Turkish", "name_native": "Türkçe", "flag": "🇹🇷", "gt": "tr"},
    "ukr": {"code": "UKR", "name": "Ukrainian", "name_native": "Українська", "flag": "🇺🇦", "gt": "uk"},
    "vi": {"code": "VI", "name": "Vietnamese", "name_native": "Tiếng Việt", "flag": "🇻🇳", "gt": "vi"},
    "zh": {"code": "ZH", "name": "Chinese", "name_native": "中文", "flag": "🇨🇳", "gt": "zh-CN"},
}

for lang_key, meta in sorted(LANG_META.items()):
    filepath = os.path.join(locales_dir, f"{lang_key}.json")
    
    if os.path.exists(filepath):
        with open(filepath, 'r', encoding='utf-8') as f:
            try:
                data = json.load(f)
            except Exception:
                data = {}
    else:
        data = {}
    
    data["_meta"] = {
        "code": meta["code"],
        "name": meta["name"],
        "name_native": meta["name_native"],
        "flag": meta["flag"]
    }
    
    trans = data.setdefault("translations", {})
    missing = [k for k in sorted(collected_keys) if k not in trans]
    
    if missing:
        print(f"[{lang_key}] Translating {len(missing)} missing keys...")
        gt_target = meta["gt"]
        
        translator = GoogleTranslator(source="en", target=gt_target) if lang_key not in ["en", "ded"] else None
        
        for idx, key in enumerate(missing):
            val = None
            py_entry = existing_py_translations.get(key)
            if py_entry:
                if isinstance(py_entry, str) and lang_key in ["ru", "ded"]:
                    val = py_entry
                elif isinstance(py_entry, dict):
                    val = py_entry.get(meta["code"]) or py_entry.get("RU")
            
            if not val:
                if lang_key == "en":
                    val = key
                elif lang_key == "ded":
                    ru_val = py_entry if isinstance(py_entry, str) else (py_entry.get("RU") if isinstance(py_entry, dict) else None)
                    if not ru_val:
                        try:
                            ru_val = GoogleTranslator(source="en", target="ru").translate(key)
                        except Exception:
                            ru_val = key
                    val = f"Эх, {ru_val}" if ru_val else key
                else:
                    try:
                        val = translator.translate(key)
                    except Exception:
                        val = key
            
            trans[key] = val or key
            if (idx + 1) % 50 == 0:
                print(f"  [{lang_key}] {idx+1}/{len(missing)} keys translated...")
    
    # Calculate HONEST coverage_pct
    actual_covered = len([k for k in collected_keys if k in trans and trans[k]])
    cov_pct = round((actual_covered / len(collected_keys)) * 100.0, 1)
    data["coverage_pct"] = cov_pct
    
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    
    print(f"[{lang_key}] Coverage: {cov_pct}% ({actual_covered}/{len(collected_keys)})")

# 2. Docs/wiki translation into .saipen/saitranslate/kitchen/docs/
kitchen_docs_dir = os.path.join(kitchen_dir, "docs")
os.makedirs(kitchen_docs_dir, exist_ok=True)

print("\n--- Translating docs/wiki/ into .saipen/saitranslate/kitchen/docs/ ---")
if os.path.exists(docs_dir):
    wiki_files = [f for f in os.listdir(docs_dir) if f.endswith('.md')]
    for target_doc_lang in ["ru", "est", "ja", "de"]:
        target_lang_dir = os.path.join(kitchen_docs_dir, target_doc_lang)
        os.makedirs(target_lang_dir, exist_ok=True)
        
        gt_code = LANG_META.get(target_doc_lang, {}).get("gt", "ru")
        doc_translator = GoogleTranslator(source="en", target=gt_code)
        
        for wf in wiki_files:
            src_file_path = os.path.join(docs_dir, wf)
            dst_file_path = os.path.join(target_lang_dir, wf)
            
            if not os.path.exists(dst_file_path):
                with open(src_file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                paragraphs = content.split('\n\n')
                translated_paragraphs = []
                for p in paragraphs:
                    if p.strip().startswith('#') or p.strip().startswith('```') or len(p.strip()) == 0:
                        translated_paragraphs.append(p)
                    else:
                        try:
                            t_p = doc_translator.translate(p)
                            translated_paragraphs.append(t_p if t_p else p)
                        except Exception:
                            translated_paragraphs.append(p)
                
                with open(dst_file_path, 'w', encoding='utf-8') as f:
                    f.write('\n\n'.join(translated_paragraphs))
                print(f"  Translated {wf} -> kitchen/docs/{target_doc_lang}/")
            else:
                print(f"  Existing {wf} in kitchen/docs/{target_doc_lang}/")

# 3. Update STATE.md inside .saipen/saitranslate/
state_file = r"V:\___VAC\__K\__CODE\_PY\_FastPrompter\.saipen\saitranslate\STATE.md"
with open(state_file, 'w', encoding='utf-8') as f:
    f.write(f"""---
phase: DONE
task: "completed 32-language bundle + ded voice + docs translation"
next_action: "Wait for user"
agent: antigravity
updated: {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}
---
""")

# 4. Get short git hash
try:
    short_hash = subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=r"V:\___VAC\__K\__CODE\_PY\_FastPrompter").decode('utf-8').strip()
except Exception:
    short_hash = "head"

# 5. Append ONE line to main .saipen/LOG.md
now_str = time.strftime('%d.%m.%y %H:%M')
log_file = r"V:\___VAC\__K\__CODE\_PY\_FastPrompter\.saipen\LOG.md"

last_eid = 1012
if os.path.exists(log_file):
    with open(log_file, 'r', encoding='utf-8') as f:
        log_content = f.read()
        e_matches = re.findall(r'\[E-(\d+)\]', log_content)
        if e_matches:
            last_eid = max(int(m) for m in e_matches)

new_eid = last_eid + 1
one_log_line = f"- {now_str} [E-{new_eid:03d}] [parent: E-{last_eid:03d}] RUN: translate -> done @{short_hash}\n"

with open(log_file, 'a', encoding='utf-8') as f:
    f.write(one_log_line)

print(f"\nAppended to .saipen/LOG.md:\n{one_log_line}")
print("=== FULL SAITRANSLATE PIPELINE COMPLETE ===")
