import os

d = r'V:\___VAC\__K\__CODE\_PY\_FastPrompter\src\fastprompter\core\i18n'
targets = ['en.py', 'he.py', 'ar.py', 'tr.py', 'th.py', 'vi.py', 'hi.py', 'id.py', 'ms.py']

for fname in targets:
    p = os.path.join(d, fname)
    if not os.path.exists(p):
        print(f'{fname}: NOT FOUND')
        continue
    with open(p, 'r', encoding='utf-8') as f:
        ct = f.read()
    lines = ct.split('\n')
    in_dict = False
    count = 0
    for line in lines:
        s = line.strip()
        if s.startswith('TRANSLATIONS'):
            in_dict = True
            continue
        if in_dict:
            if s == '}':
                break
            if s and ':' in s and not s.startswith('#') and not s.startswith('"""') and s != '':
                count += 1
    print(f'{fname}: {count} entries')
