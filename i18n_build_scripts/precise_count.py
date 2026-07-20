import os, re

d = r'V:\___VAC\__K\__CODE\_PY\_FastPrompter\src\fastprompter\core\i18n'

def count_entries(text):
    lines = text.split('\n')
    in_dict = False
    count = 0
    for line in lines:
        stripped = line.strip()
        if stripped.startswith('TRANSLATIONS'):
            in_dict = True
            continue
        if in_dict:
            if stripped == '}':
                break
            if stripped and not stripped.startswith('#') and not stripped.startswith('"""') and stripped != '':
                if ':' in stripped:
                    count += 1
    return count

for fname in ['en.py','he.py','ar.py','tr.py','th.py']:
    p = os.path.join(d, fname)
    with open(p, 'r', encoding='utf-8') as f:
        ct = f.read()
    cnt = count_entries(ct)
    print(f'{fname}: {cnt} entries')
