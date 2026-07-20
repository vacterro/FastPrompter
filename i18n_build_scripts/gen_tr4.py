#!/usr/bin/env python3
"""Generate vi.py, hi.py, id.py, ms.py with full natural translations.

Usage: python gen_tr4.py
Reads _parsed.py for EN entries, applies translations from data dicts below,
writes each .py file with 483 entries.
"""
import os, sys, json

d = r'V:\___VAC\__K\__CODE\_PY\_FastPrompter\src\fastprompter\core\i18n'
tmp = r'V:\_TEMP_\opencode'

# Load EN entries
exec(open(os.path.join(d, '_parsed.py'), 'r', encoding='utf-8').read())
entries = en_entries

def load_translations(lang):
    path = os.path.join(tmp, f'tr_{lang}.json')
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)

def write_file(filename, lang_header, translations):
    all_keys = {k for k, _ in entries}
    tr_keys = set(translations.keys())
    missing = all_keys - tr_keys
    # Use translation if available, else fallback to EN value
    en_map = {k: v for k, v in entries}
    
    lines = []
    lines.append(f'"""{lang_header}"""')
    lines.append('')
    lines.append('from __future__ import annotations')
    lines.append('')
    lines.append('TRANSLATIONS: dict[str, str] = {')
    for k, _ in entries:
        tv = translations.get(k, en_map.get(k, k))
        # Escape single quotes and backslashes for Python source
        tv = tv.replace('\\', '\\\\').replace("'", "\\'")
        ek = k.replace('\\', '\\\\').replace("'", "\\'")
        lines.append(f"    '{ek}': '{tv}',")
    lines.append('}')
    content = '\n'.join(lines) + '\n'
    
    path = os.path.join(d, filename)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)
    
    cnt = content.count("': '")
    print(f'{filename}: {cnt} entries')
    return cnt

# Load translation JSONs and generate
for lang, header in [('vi', 'Tiếng Việt (Vietnamese) — 483 khóa.'),
                      ('hi', 'हिन्दी (Hindi) — 483 कुंजियाँ।'),
                      ('id', 'Bahasa Indonesia (Indonesian) — 483 kunci.'),
                      ('ms', 'Bahasa Melayu (Malay) — 483 kunci.')]:
    tr = load_translations(lang)
    write_file(f'{lang}.py', header, tr)
    print(f'  {len(tr)} translations loaded')
