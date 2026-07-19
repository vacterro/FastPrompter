import re

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

print('EN:', len(en), 'BG:', len(bg), 'EL:', len(el))

extra_bg = [k for k in bg if k not in en]
extra_el = [k for k in el if k not in en]
print('Extra in BG:', extra_bg)
print('Extra in EL:', extra_el)

missing_bg = [k for k in en if k not in bg]
missing_el = [k for k in en if k not in el]
print('Missing in BG:', len(missing_bg), missing_bg)
print('Missing in EL:', len(missing_el), missing_el)
