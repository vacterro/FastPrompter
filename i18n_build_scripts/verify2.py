import re, sys

sys.stdout.reconfigure(encoding='utf-8')

def parse(path):
    r = {}
    with open(path, encoding='utf-8') as f:
        c = f.read()
    pat = r"^\s+([\"'])(.+?)\1\s*:\s*([\"'])(.*?)\3,?\s*$"
    for m in re.finditer(pat, c, re.MULTILINE | re.DOTALL):
        r[m.group(2)] = m.group(4)
    return r

en = parse(r'V:\___VAC\__K\__CODE\_PY\_FastPrompter\src\fastprompter\core\i18n\en.py')
bg = parse(r'V:\___VAC\__K\__CODE\_PY\_FastPrompter\src\fastprompter\core\i18n\bg.py')
el = parse(r'V:\___VAC\__K\__CODE\_PY\_FastPrompter\src\fastprompter\core\i18n\el.py')

print(f'EN: {len(en)} BG: {len(bg)} EL: {len(el)}')

extra_bg = [k for k in bg if k not in en]
extra_el = [k for k in el if k not in en]
print(f'Extra in BG ({len(extra_bg)}):')
for k in extra_bg:
    print(f'  {repr(k)}')
print(f'Extra in EL ({len(extra_el)}):')
for k in extra_el:
    print(f'  {repr(k)}')

missing_bg = [k for k in en if k not in bg]
missing_el = [k for k in en if k not in el]
print(f'Missing in BG: {len(missing_bg)}')
print(f'Missing in EL: {len(missing_el)}')

# Check duplicate values
bg_keys = list(bg.keys())
for i, k in enumerate(bg_keys):
    for k2 in bg_keys[i+1:]:
        if k.lower() == k2.lower():
            print(f'DUP in BG: {repr(k)} vs {repr(k2)}')
el_keys = list(el.keys())
for i, k in enumerate(el_keys):
    for k2 in el_keys[i+1:]:
        if k.lower() == k2.lower():
            print(f'DUP in EL: {repr(k)} vs {repr(k2)}')
