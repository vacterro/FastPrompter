import re

def extract_keys(filepath):
    keys = set()
    with open(filepath, 'r', encoding='utf-8') as f:
        for line in f:
            m = re.match(r'^\s+[\"\'](.+?)[\"\']\s*:', line)
            if m:
                keys.add(m.group(1))
    return keys

en = extract_keys(r'V:\___VAC\__K\__CODE\_PY\_FastPrompter\src\fastprompter\core\i18n\en.py')
bg = extract_keys(r'V:\___VAC\__K\__CODE\_PY\_FastPrompter\src\fastprompter\core\i18n\bg.py')
el = extract_keys(r'V:\___VAC\__K\__CODE\_PY\_FastPrompter\src\fastprompter\core\i18n\el.py')

print(f'EN: {len(en)}')
print(f'BG: {len(bg)}')
print(f'EL: {len(el)}')

missing_bg = sorted(en - bg)
missing_el = sorted(en - el)

if missing_bg:
    print(f'\nBG missing {len(missing_bg)} keys:')
    for k in missing_bg:
        print(repr(k))
if missing_el:
    print(f'\nEL missing {len(missing_el)} keys:')
    for k in missing_el:
        print(repr(k))
