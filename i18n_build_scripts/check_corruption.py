import os
d = r'V:\___VAC\__K\__CODE\_PY\_FastPrompter\src\fastprompter\core\i18n'

exec(open(os.path.join(d, '_parsed.py'), 'r', encoding='utf-8').read())

issues = []
for k, v in en_entries:
    if '\ufffd' in k or '\ufffd' in v:
        issues.append((k, v))
    elif any(ord(c) > 127 for c in k):
        issues.append(('SPECIAL', k, v))
    
print(f'Entries with replacement char: {len(issues)}')
for k, v in issues[:10]:
    print(f'  {repr(k)}')
    print(f'  {repr(v)}')
    print()
