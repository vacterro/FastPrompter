import os
d = r'V:\___VAC\__K\__CODE\_PY\_FastPrompter\src\fastprompter\core\i18n'
ct = open(os.path.join(d,'id.py'),'r',encoding='utf-8').read()
s = ct.index('TRANSLATIONS')
s = ct.index('{', s)
depth = 1
i = s + 1
while i < len(ct) and depth > 0:
    if ct[i] == '{': depth += 1
    if ct[i] == '}': depth -= 1
    i += 1
body = ct[s+1:i-1]
lines = [l.strip() for l in body.split('\n') if ':' in l.strip() and l.strip() != '}']
print(f'Entries: {len(lines)}')
# Check for translations vs fallbacks
translated = sum(1 for l in lines if l.count("': '") == 1)
print(f'Translated entries: {translated}')
# Sample first few
for l in lines[:10]:
    print(f'  {l[:80]}')
