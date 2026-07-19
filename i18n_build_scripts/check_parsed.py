import os
d = r'V:\___VAC\__K\__CODE\_PY\_FastPrompter\src\fastprompter\core\i18n'

exec(open(os.path.join(d, '_parsed.py'), 'r', encoding='utf-8').read())

# Check keys with special chars
for k, v in en_entries:
    if any(ord(c) > 127 for c in k) or any(ord(c) > 127 for c in v):
        print(repr(k))
        print(repr(v))
        print()
        break  # just first one
